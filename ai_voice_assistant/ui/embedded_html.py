"""Embedded Edge with owned processes, cropped chrome and static assets."""
import ctypes
from ctypes import wintypes as w
import threading
import time
from http.server import ThreadingHTTPServer
from ui.html_whiteboard import HtmlWhiteboardRenderer, _WhiteboardRequestHandler, _window_enum_callback_type
from ui.windows_job import WindowsJob
from ui.fullscreen_host import Bounds


class AssetHandler(_WhiteboardRequestHandler):
    def do_POST(self):
        port = self.server.server_address[1]
        if self.headers.get('Origin') != f'http://127.0.0.1:{port}':
            self.send_error(403)
            return
        super().do_POST()


class NativeHtmlRenderer(HtmlWhiteboardRenderer):
    def __init__(self, *args, ui_post=None, **kwargs):
        self._job = None
        self._ui_post = ui_post
        self._content_ready = False
        self._content_deadline = 0
        super().__init__(*args, **kwargs)

    def _start_server(self, source_path):
        # No dynamic port fallback: an origin change would silently lose the
        # game's localStorage when restoring a hidden board.
        server = ThreadingHTTPServer(('127.0.0.1', self._preferred_port(source_path)), AssetHandler)
        server.daemon_threads = True
        server.source_root = source_path.parent.resolve()
        server.entry_path = source_path.resolve()
        server.volume_getter = self._effective_volume
        server.input_getter = self.input_state
        server.keyboard_capture_notifier = self.set_keyboard_capture
        server.handle_error = lambda *_: None
        self._server = server
        self._server_thread = threading.Thread(target=server.serve_forever, daemon=True, name='whiteboard-html-server')
        self._server_thread.start()

    def _launch_browser_locked(self, generation):
        if self._ui_post is None:
            raise RuntimeError('HTML host requires a UI-thread dispatcher')
        edge = self._find_edge_executable()
        if edge is None:
            self.last_error = '找不到 Microsoft Edge'
            return
        port = self._server.server_address[1]
        command = [str(edge), f'--user-data-dir={self.profile_root}',
                   f'--app=http://127.0.0.1:{port}/', '--no-first-run', '--no-default-browser-check',
                   '--disable-extensions', '--disable-sync', '--disable-translate',
                   '--disable-session-crashed-bubble', '--autoplay-policy=no-user-gesture-required',
                   '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1']
        self._job = WindowsJob()
        try:
            self._process = self._job.launch(command)
        except Exception:
            self._job.close()
            self._job = None
            raise
        threading.Thread(target=self._attach_browser_window, args=(self._process.pid, generation),
                         daemon=True, name='whiteboard-html-attach').start()

    def _find_window_for_pid(self, process_id):
        api = self._windows_api()
        found = []
        callback_type = _window_enum_callback_type()
        @callback_type
        def visit(hwnd, _):
            pid = ctypes.c_ulong()
            api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            name = ctypes.create_unicode_buffer(256)
            api.GetClassNameW(hwnd, name, len(name))
            if (pid.value == process_id and api.IsWindowVisible(hwnd)
                    and name.value == 'Chrome_WidgetWin_1' and self._find_input_window(hwnd)):
                # A Chrome shell may appear before its web render window.
                # Reparenting that incomplete shell can prevent child creation.
                found.append(int(hwnd))
                return False
            return True
        api.EnumWindows(visit, 0)
        return found[0] if found else None

    def _attach_browser_window(self, process_id, generation):
        try:
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                with self._lock:
                    if generation != self._generation or self._job is None:
                        return
                    # CTk can keep its root withdrawn until mainloop starts.
                    # Embedding into that hidden parent hides Chromium's render
                    # child; wait for the actual host to be mapped first.
                    if self._windows_api().IsWindowVisible(self._parent_hwnd):
                        for pid in self._job.pids():
                            hwnd = self._find_window_for_pid(pid)
                            if hwnd and self._job.owns(pid):
                                # SetParent/SetWindowPos send messages to Tk's
                                # owning thread. Do not hold this worker's lock
                                # while waiting for those messages to be handled.
                                self._ui_post(self._finish_attach,hwnd,pid,generation)
                                return
                time.sleep(.08)
            with self._lock:
                if generation == self._generation:
                    self.last_error = 'Microsoft Edge 視窗啟動逾時'
        except Exception as exc:
            with self._lock:
                if generation == self._generation:
                    self.last_error = f'HTML 嵌入失敗：{type(exc).__name__}'

    def _finish_attach(self,hwnd,pid,generation):
        with self._lock:
            if generation!=self._generation or self._job is None: return
            try:
                current_pid=w.DWORD()
                self._windows_api().GetWindowThreadProcessId(hwnd,ctypes.byref(current_pid))
                if current_pid.value!=pid or not self._job.owns(pid):
                    raise RuntimeError('Edge ownership changed before attach')
                self._embed_window_locked(hwnd)
                self._hwnd=hwnd
            except Exception as exc:
                self.last_error=f'HTML 嵌入失敗：{type(exc).__name__}'

    def _embed_window_locked(self, hwnd):
        super()._embed_window_locked(hwnd)
        api = self._windows_api()
        api.GetParent.argtypes = [ctypes.c_void_p]
        api.GetParent.restype = ctypes.c_void_p
        # SetParent may fail for mixed DPI awareness even when SetWindowPos
        # succeeds. Do not report a floating Edge window as an attached board.
        if api.GetParent(hwnd) != self._parent_hwnd:
            raise RuntimeError('Edge parent mismatch')
        self._content_ready=self._fit_content_locked(hwnd)
        self._content_deadline=time.monotonic()+4

    @staticmethod
    def _viewport_api():
        api=ctypes.WinDLL('user32',use_last_error=True)
        signatures={
            'GetWindowRect': ([w.HWND,ctypes.POINTER(w.RECT)],w.BOOL),
            'GetClientRect': ([w.HWND,ctypes.POINTER(w.RECT)],w.BOOL),
            'ClientToScreen': ([w.HWND,ctypes.POINTER(w.POINT)],w.BOOL),
            'SetWindowPos': ([w.HWND,w.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.UINT],w.BOOL),
        }
        for name,(args,result) in signatures.items():
            function=getattr(api,name);function.argtypes,function.restype=args,result
        return api

    @staticmethod
    def _check_native(value):
        if not value: raise ctypes.WinError(ctypes.get_last_error())
        return value

    def _rect(self,api,hwnd,client=False):
        rect=w.RECT()
        self._check_native((api.GetClientRect if client else api.GetWindowRect)(hwnd,ctypes.byref(rect)))
        return Bounds.from_rect(rect)

    def _client_screen_rect(self,api,hwnd):
        client=self._rect(api,hwnd,client=True)
        origin=w.POINT();self._check_native(api.ClientToScreen(hwnd,ctypes.byref(origin)))
        return Bounds(origin.x,origin.y,origin.x+client.width,origin.y+client.height)

    @staticmethod
    def _fills_host(viewport,target):
        # Chromium rounds its web client to device pixels. At fractional DPI,
        # requesting an exact height can alternate between one pixel too short
        # and one too tall. A tiny overscan is clipped by the parent; never
        # accept a gap or a shifted origin that could expose browser chrome.
        return (viewport.left==target.left and viewport.top==target.top
                and 0<=viewport.right-target.right<=2
                and 0<=viewport.bottom-target.bottom<=2)

    def _fit_content_locked(self,hwnd):
        content=self._find_input_window(hwnd)
        if not content: return False
        api=self._viewport_api()
        outer=self._rect(api,hwnd)
        viewport=self._client_screen_rect(api,content)
        # Chromium paints its own app titlebar inside the client area. Crop
        # that chrome using the real render HWND, without guessed DPI offsets.
        left=viewport.left-outer.left;top=viewport.top-outer.top
        right=outer.right-viewport.right;bottom=outer.bottom-viewport.bottom
        if min(left,top,right,bottom)<0 or viewport.width<=0 or viewport.height<=0:
            return False  # Browser layout has not settled yet.
        target=self._client_screen_rect(api,self._parent_hwnd)
        if target.width<=0 or target.height<=0: return False
        if not self._fills_host(viewport,target):
            self._check_native(api.SetWindowPos(hwnd,None,-left,-top,
                target.width+left+right,target.height+top+bottom,0x0004|0x0010))
            return self._fills_host(self._client_screen_rect(api,content),target)
        return True

    def ensure_layout(self):
        with self._lock:
            if not self._hwnd: return
            try:
                api=self._windows_api()
                api.IsWindow.argtypes=[w.HWND];api.IsWindow.restype=w.BOOL
                if not api.IsWindow(self._hwnd):
                    raise OSError('HTML window closed')
                self._update_content_layout_locked()
                if not self._content_ready and time.monotonic()>self._content_deadline:
                    self.last_error='HTML 內容尺寸校正逾時'
            except OSError as exc:
                self._content_ready=False
                self.last_error=f'HTML 視窗失效：{type(exc).__name__}'

    def _update_content_layout_locked(self):
        was_ready=self._content_ready
        self._content_ready=self._fit_content_locked(self._hwnd)
        if was_ready and not self._content_ready:
            # A later resize starts its own bounded settling period; it must
            # not inherit an already expired initial-attach deadline.
            self._content_deadline=time.monotonic()+4

    def resize(self,parent_hwnd,width,height):
        with self._lock:
            if self._parent_hwnd and int(parent_hwnd)!=self._parent_hwnd:
                raise ValueError('Cannot move HTML into another host')
            self._parent_hwnd=int(parent_hwnd)
            self._size=(max(1,int(width)),max(1,int(height)))
            if self._hwnd:
                self._update_content_layout_locked()

    @property
    def is_attached(self):
        api = self._windows_api()
        api.IsWindow.argtypes = [ctypes.c_void_p]
        api.IsWindow.restype = ctypes.c_bool
        return bool(self._hwnd and api.IsWindow(self._hwnd) and self._content_ready)

    @property
    def is_active(self):
        return self.is_attached or super().is_active

    def _stop_browser_locked(self):
        self._content_ready=False
        process, job = self._process, self._job
        try:
            super()._stop_browser_locked()
            deadline = time.monotonic() + 1.5
            while job and job.pids() and time.monotonic() < deadline:
                time.sleep(.05)
        finally:
            try:
                if job:
                    job.close()
            finally:
                self._job = None
                if process:
                    process.close()

    def stop(self):
        with self._lock:
            try:
                self._stop_browser_locked()
            finally:
                self._stop_server_locked()
                self._source_path = self._parent_hwnd = None
