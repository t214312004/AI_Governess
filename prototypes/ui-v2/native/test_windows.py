"""Real Windows ownership and loopback server integration tests."""
import bootstrap
import ctypes
from ctypes import wintypes as w
import subprocess
import sys
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from html_host import NativeHtmlRenderer
from windows_job import WindowsJob
from fullscreen_host import Bounds


class HtmlViewportTests(unittest.TestCase):
    def test_resize_gets_a_new_bounded_settling_period(self):
        renderer=NativeHtmlRenderer.__new__(NativeHtmlRenderer)
        renderer._lock=threading.RLock();renderer._hwnd=33
        renderer._content_ready=True;renderer._content_deadline=0;renderer.last_error=None
        api=Mock();api.IsWindow.return_value=True
        with patch.object(renderer,'_windows_api',return_value=api),patch.object(renderer,'_fit_content_locked',return_value=False),patch('html_host.time.monotonic',return_value=100) as clock:
            renderer.ensure_layout()
            self.assertEqual(renderer._content_deadline,104)
            self.assertIsNone(renderer.last_error)
            clock.return_value=101;renderer.ensure_layout()
            self.assertIsNone(renderer.last_error)
            clock.return_value=105;renderer.ensure_layout()
            self.assertIsNotNone(renderer.last_error)

    def test_attach_waits_for_mapped_parent_and_dispatches_embedding_to_ui_thread(self):
        renderer=NativeHtmlRenderer.__new__(NativeHtmlRenderer)
        renderer._parent_hwnd=11;renderer._lock=threading.RLock()
        renderer._generation=1;renderer._job=Mock();renderer._job.pids.return_value=(100,)
        renderer._ui_post=Mock()
        api=Mock();api.IsWindowVisible.side_effect=[False,True]
        with patch.object(renderer,'_windows_api',return_value=api),patch.object(renderer,'_find_window_for_pid',return_value=33) as find,patch.object(renderer,'_embed_window_locked') as embed,patch('html_host.time.sleep'):
            renderer._attach_browser_window(100,1)
        find.assert_called_once_with(100)
        renderer._ui_post.assert_called_once_with(renderer._finish_attach,33,100,1)
        embed.assert_not_called()

    def test_cancelled_attach_callback_cannot_reparent_a_replacement_window(self):
        renderer=NativeHtmlRenderer.__new__(NativeHtmlRenderer)
        renderer._lock=threading.RLock();renderer._generation=2;renderer._job=Mock()
        with patch.object(renderer,'_embed_window_locked') as embed:
            renderer._finish_attach(33,100,1)
        embed.assert_not_called()

    def test_attach_rechecks_window_owner_before_embedding(self):
        renderer=NativeHtmlRenderer.__new__(NativeHtmlRenderer)
        renderer._lock=threading.RLock();renderer._generation=1;renderer._job=Mock()
        api=Mock()
        def owner(_hwnd,pointer):
            ctypes.cast(pointer,ctypes.POINTER(w.DWORD)).contents.value=200
            return 1
        api.GetWindowThreadProcessId.side_effect=owner
        with patch.object(renderer,'_windows_api',return_value=api),patch.object(renderer,'_embed_window_locked') as embed:
            renderer._finish_attach(33,100,1)
        embed.assert_not_called()
        self.assertIn('RuntimeError',renderer.last_error)

    def test_crops_client_drawn_titlebar_and_borders_using_native_content_bounds(self):
        renderer=NativeHtmlRenderer.__new__(NativeHtmlRenderer)
        renderer._parent_hwnd=11
        api=Mock();api.SetWindowPos.return_value=True
        target=Bounds(-800,200,-200,800)
        with patch.object(renderer,'_find_input_window',return_value=22),patch.object(renderer,'_viewport_api',return_value=api),patch.object(renderer,'_rect',return_value=Bounds(-800,200,-200,800)),patch.object(renderer,'_client_screen_rect',side_effect=[
            Bounds(-792,280,-208,792),target,target]):
            self.assertTrue(renderer._fit_content_locked(33))
        api.SetWindowPos.assert_called_once_with(33,None,-8,-80,616,688,0x0004|0x0010)

    def test_unsettled_content_is_not_reported_ready(self):
        renderer=NativeHtmlRenderer.__new__(NativeHtmlRenderer)
        renderer._parent_hwnd=11;api=Mock()
        with patch.object(renderer,'_find_input_window',return_value=22),patch.object(renderer,'_viewport_api',return_value=api),patch.object(renderer,'_rect',return_value=Bounds(0,0,600,600)),patch.object(renderer,'_client_screen_rect',return_value=Bounds(-8,-8,608,608)):
            self.assertFalse(renderer._fit_content_locked(33))
        api.SetWindowPos.assert_not_called()

    def test_dpi_overscan_fills_host_without_resize_oscillation(self):
        renderer=NativeHtmlRenderer.__new__(NativeHtmlRenderer)
        renderer._parent_hwnd=11;target=Bounds(-800,200,-200,800)
        for extra in (1,2):
            with self.subTest(extra_pixels=extra):
                api=Mock()
                viewport=Bounds(target.left,target.top,target.right+extra,target.bottom+extra)
                outer=Bounds(target.left-8,target.top-80,viewport.right+8,viewport.bottom+8)
                with patch.object(renderer,'_find_input_window',return_value=22),patch.object(renderer,'_viewport_api',return_value=api),patch.object(renderer,'_rect',return_value=outer),patch.object(renderer,'_client_screen_rect',side_effect=[viewport,target]):
                    self.assertTrue(renderer._fit_content_locked(33))
                api.SetWindowPos.assert_not_called()

    def test_dpi_fit_rejects_gaps_shifted_origin_and_excessive_overscan(self):
        renderer=NativeHtmlRenderer.__new__(NativeHtmlRenderer)
        renderer._parent_hwnd=11;target=Bounds(-800,200,-200,800)
        outer=Bounds(target.left-8,target.top-80,target.right+16,target.bottom+16)
        for viewport in (Bounds(-800,200,-200,799),Bounds(-800,200,-201,800),
                         Bounds(-799,200,-199,800),Bounds(-800,199,-200,800),
                         Bounds(-800,200,-197,800),Bounds(-800,200,-200,803)):
            with self.subTest(viewport=viewport):
                api=Mock();api.SetWindowPos.return_value=True
                with patch.object(renderer,'_find_input_window',return_value=22),patch.object(renderer,'_viewport_api',return_value=api),patch.object(renderer,'_rect',return_value=outer),patch.object(renderer,'_client_screen_rect',side_effect=[viewport,target,viewport]):
                    self.assertFalse(renderer._fit_content_locked(33))
                api.SetWindowPos.assert_called_once()


class WindowsJobTests(unittest.TestCase):
    def test_job_kills_its_descendants_and_preserves_unrelated_process(self):
        job=WindowsJob();self.addCleanup(job.close)
        unrelated=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(60)'],creationflags=subprocess.CREATE_NO_WINDOW)
        self.addCleanup(lambda:(unrelated.terminate(),unrelated.wait(3)) if unrelated.poll() is None else None)
        code="import subprocess,sys,time;subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(60)']);time.sleep(60)"
        process=job.launch([sys.executable,'-B','-c',code]);self.addCleanup(process.close)
        deadline=time.monotonic()+5
        while len(job.pids())<2 and time.monotonic()<deadline: time.sleep(.05)
        members=job.pids()
        self.assertGreaterEqual(len(members),2)
        self.assertFalse(job.owns(unrelated.pid))
        handles=[job.api.OpenProcess(0x00101000,False,pid) for pid in members]
        try:
            self.assertTrue(all(handles))
            job.close()
            for handle in handles:
                self.assertEqual(job.api.WaitForSingleObject(handle,3000),0)
            self.assertIsNone(unrelated.poll())
        finally:
            for handle in handles:
                if handle: job.api.CloseHandle(handle)

    def test_assignment_failure_never_runs_the_suspended_process(self):
        with TemporaryDirectory() as directory:
            marker=Path(directory)/'should-not-exist'
            job=WindowsJob();self.addCleanup(job.close)
            command=[sys.executable,'-B','-c',f'from pathlib import Path;Path({str(marker)!r}).write_text("ran")']
            with patch.object(job.api,'AssignProcessToJobObject',return_value=False):
                with self.assertRaises(OSError): job.launch(command)
            self.assertFalse(marker.exists())
            self.assertFalse(job.pids())


class AssetServerTests(unittest.TestCase):
    def test_server_restricts_root_and_rejects_cross_origin_focus(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);assets=root/'assets';assets.mkdir()
            source=assets/'game.html';source.write_text('<h1>demo</h1>',encoding='utf-8')
            (root/'private.txt').write_text('outside-root',encoding='utf-8')
            renderer=NativeHtmlRenderer(root/'profile')
            with patch.object(renderer,'_preferred_port',return_value=0): renderer._start_server(source)
            try:
                base=f'http://127.0.0.1:{renderer._server.server_address[1]}'
                with urlopen(base+'/',timeout=2) as response:
                    self.assertIn(b'<h1>demo</h1>',response.read())
                    self.assertIn("connect-src 'self'",response.headers['Content-Security-Policy'])
                for path in ('/../private.txt','/%2e%2e/private.txt','/C%3a/private.txt','/%5cprivate.txt'):
                    with self.subTest(path=path),self.assertRaises(HTTPError) as error: urlopen(base+path,timeout=2)
                    error.exception.close()
                request=Request(base+'/__ai_governess/focus',data=b'',headers={'Origin':'https://outside.example'})
                with self.assertRaises(HTTPError) as error: urlopen(request,timeout=2)
                self.assertEqual(error.exception.code,403)
                error.exception.close()
                self.assertFalse(renderer.keyboard_capture_requested)
                request=Request(base+'/__ai_governess/focus',data=b'',headers={'Origin':base})
                with urlopen(request,timeout=2) as response: self.assertEqual(response.status,204)
                self.assertTrue(renderer.keyboard_capture_requested)
            finally:
                renderer.stop()


if __name__=='__main__': unittest.main()
