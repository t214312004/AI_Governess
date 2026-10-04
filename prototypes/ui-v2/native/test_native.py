"""Native UI failure tests. No fullscreen hooks or production services started."""
import bootstrap
import ctypes
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import customtkinter as ctk

from domain import HtmlBudget, Phase, SessionConfig
from main_window import MainWindow
from services import ModelInfo
from fullscreen_host import Bounds, FullscreenHost
from widgets import OwnedComboBox


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=MainWindow(smoke=True,runtime_path=Path(self.temp.name))
        self.addCleanup(self.app.close)
        self.errors=[]
        self.expected_cleanup_errors=[]
        self.app.report_callback_exception=lambda *args:self.errors.append(args)
        # Map the initial window before test actions enqueue query/animation
        # callbacks. CTk's first mainloop otherwise performs a nested update()
        # that can consume a short quit timer before mainloop actually starts.
        self.app.update()

    def tearDown(self):
        self.app.close()
        self.assertEqual(self.app.cleanup_errors,self.expected_cleanup_errors)

    def start(self):
        with patch('main_window.PreviewInputMonitor'):
            self.app.start_session(SessionConfig('codex_cli','demo-balanced','medium'),self.app.startup.settings)
        self.app.update_idletasks()

    def test_collect_is_transactional(self):
        view=self.app.startup
        before=deepcopy(view.settings)
        view.editors=[(('audio','input_sample_rate'),ctk.StringVar(value='32000'),16000),
                      (('audio','output_sample_rate'),ctk.StringVar(value='invalid'),24000)]
        self.assertFalse(view.collect())
        self.assertEqual(view.settings,before)

    def test_delayed_catalog_result_cannot_apply_to_another_backend(self):
        gate=threading.Event()
        class SlowCatalog:
            def query(self,*args,**kwargs):
                gate.wait(2)
                return (ModelInfo('old-backend-model',()),)
        view=self.app.startup
        view.catalog=SlowCatalog();view.query()
        view.backend.set('claude_code');view.invalidate()
        gate.set();view.query_thread.join(2)
        view.poll_query()
        self.assertFalse(view.ready);self.assertFalse(view.models)

    def test_catalog_timeout_cancels_request(self):
        view=self.app.startup
        view.querying=True;view.query_deadline=0
        view.poll_query()
        self.assertTrue(view.query_cancel.is_set());self.assertFalse(view.querying)

    def test_skip_to_start_then_sequential_retry_launches_session(self):
        view=self.app.startup
        view.nav_buttons[4].invoke();view.next.invoke()
        self.assertEqual(view.step,0)
        self.assertIsNone(self.app.controller)
        view.next.invoke()
        self.pump(300)
        self.assertTrue(view.ready)
        self.assertEqual(view.step,1)
        self.assertEqual(view.effort.get(),'low')
        with patch('main_window.PreviewInputMonitor'):
            for _ in range(4): view.next.invoke()
        self.assertIsNotNone(self.app.controller)
        self.assertTrue(view.destroyed)

    def test_next_query_failure_restores_retry_and_manual_query_stays_on_ai_page(self):
        view=self.app.startup
        view.catalog=Mock()
        view.catalog.query.side_effect=[RuntimeError('offline'),(ModelInfo('recovered',()),)]
        view.next.invoke();self.pump(300)
        self.assertEqual(view.step,0);self.assertFalse(view.ready)
        self.assertEqual(view.next.cget('state'),'normal')
        self.assertIsNone(view.query_next_step)
        view.query_button._clicked();self.pump(300)
        self.assertTrue(view.ready);self.assertEqual(view.step,0)
        self.assertEqual(view.effort.get(),'')
        view.next.invoke();self.assertEqual(view.step,1)

    def test_pending_next_query_cannot_be_skipped_or_advance_after_invalidation(self):
        view=self.app.startup;gate=threading.Event()
        self.addCleanup(gate.set)
        class SlowCatalog:
            def query(self,*args,**kwargs):
                gate.wait(2)
                return (ModelInfo('stale',('high',)),)
        view.catalog=SlowCatalog();view.next.invoke()
        self.assertTrue(view.querying)
        self.assertEqual(view.next.cget('state'),'disabled')
        view.nav_buttons[4].invoke();view.advance()
        self.assertEqual(view.step,0)
        view.backend.set('claude_code');view.invalidate()
        gate.set();view.query_thread.join(2);self.pump(300)
        self.assertFalse(view.ready);self.assertEqual(view.step,0)
        self.assertIsNone(view.query_next_step)
        self.assertEqual(view.next.cget('state'),'normal')

    def test_budget_write_failure_disables_html_and_keeps_timer_alive(self):
        self.start();app=self.app
        renderer=Mock();renderer.is_attached=True;renderer.last_error=None
        app.html_whiteboard_renderer=renderer
        app.board_kind='html';app.board_visible=True
        app.after_cancel(app._tick_job)
        with patch.object(app.budget,'save',side_effect=OSError('disk failed')):
            app._budget_save_stamp=0;app.tick()
        self.assertTrue(app._budget_failed)
        self.assertIsNone(app.board_kind);renderer.stop.assert_called_once()
        self.assertIsNotNone(app._tick_job)
        app.show_board('html');self.assertIsNone(app.board_kind)
        app.show_board('md');self.assertEqual(app.board_kind,'md')
        self.assertFalse(self.errors)

    def test_cleanup_continues_after_service_failure(self):
        self.start();app=self.app
        app.service.cancel=Mock(side_effect=RuntimeError('cancel failed'))
        self.expected_cleanup_errors=[('turn service','RuntimeError')]
        app.input_monitor.stop=Mock()
        with patch.object(app,'_remove_fullscreen_keyboard_guard') as guard:
            app.close()
            guard.assert_called_once()
        app.input_monitor.stop.assert_called_once()
        self.assertIn(('turn service','RuntimeError'),app.cleanup_errors)
        app.close()  # Idempotent despite the earlier error.

    def test_background_turn_events_are_marshaled(self):
        self.start();app=self.app
        worker=[]
        def start(text,event):
            thread=threading.Thread(target=lambda:event('text','background response'))
            thread.start();worker.append(thread)
        app.service.start=start
        app.controller.enqueue('hello');app.dispatch()
        worker[0].join(2)
        self.assertEqual(len(app._message_blocks),1)
        app._drain_ui_events()
        self.assertEqual(len(app._message_blocks),2)
        self.assertFalse(self.errors)

    def test_service_failure_preserves_following_queue(self):
        self.start();app=self.app
        app.service.start=Mock(side_effect=RuntimeError('backend failed'))
        app.controller.enqueue('first');app.controller.enqueue('second');app.dispatch()
        self.assertEqual(app.controller.phase,Phase.IDLE)
        self.assertEqual([item.text for item in app.controller.pending],['second'])
        self.assertIsNone(app._turn_timeout_job)

    def test_unknown_board_kind_does_not_clear_existing_board(self):
        self.start();app=self.app
        app.show_board('md')
        with self.assertRaises(ValueError): app.show_board('invalid')
        self.assertEqual(app.board_kind,'md');self.assertTrue(app.board_visible)

    def test_composer_focus_prevents_html_from_capturing_letters(self):
        self.start();app=self.app
        renderer=Mock();renderer.keyboard_capture_requested=True
        app.html_whiteboard_renderer=renderer
        app._whiteboard_current_state={'content_type':'html'}
        app._composer_focused=True
        self.assertFalse(app._forward_captured_whiteboard_key(ord('W'),is_keydown=True,was_down=False,alt_down=False,ctrl_down=False))
        renderer.forward_key_event.assert_not_called()

    def test_text_queue_waits_for_both_generation_and_playback(self):
        self.start();app=self.app
        app.service.start=Mock()
        app.controller.enqueue('first');app.dispatch()
        generation=app.controller.generation
        app.on_turn_event(generation,'generation_done','')
        app.on_turn_event(generation,'playback_started','')
        app.controller.enqueue('second');app.dispatch()
        self.assertEqual(app.service.start.call_count,1)
        app.on_turn_event(generation,'playback_done','')
        self.assertEqual(app.service.start.call_count,2)
        self.assertEqual(app.controller.phase,Phase.THINKING)
        app.on_turn_event(generation,'playback_done','')
        self.assertEqual(app.controller.phase,Phase.THINKING)

    def test_tooltip_uses_child_panel_and_cancels_timer_on_destroy(self):
        self.start();app=self.app
        app.mic.tip='test';app.mic._show_tip()
        self.assertIsInstance(app.mic._tooltip,ctk.CTkFrame)
        app.mic._enter();self.assertIsNotNone(app.mic._tip_job)
        app.mic.destroy();self.assertIsNone(app.mic._tip_job)

    def test_failed_windowproc_restore_retains_callback_until_destroy(self):
        app=self.app;callback=object()
        app._screen_guard_hwnd=99;app._screen_guard_prev_wndproc=123;app._screen_guard_proc=callback
        try:
            with patch.object(app,'_get_window_long_accessors',return_value=(Mock(),Mock(return_value=0))):
                with self.assertRaises(RuntimeError): app._remove_fullscreen_screen_guard()
            self.assertIs(app._screen_guard_proc,callback)
        finally:
            app._screen_guard_hwnd=None;app._screen_guard_prev_wndproc=None;app._screen_guard_proc=None

    def test_native_screen_guard_installs_and_restores(self):
        app=self.app;app.update_idletasks()
        app._set_screensaver_block(True)
        self.assertIsNotNone(app._screen_guard_proc)
        getter,_=app._get_window_long_accessors()
        self.assertEqual(getter(app._screen_guard_hwnd,-4),ctypes.cast(app._screen_guard_proc,ctypes.c_void_p).value)
        app._set_screensaver_block(False)
        self.assertIsNone(app._screen_guard_proc)

    def test_native_keyboard_hook_installs_and_joins_without_blocking_keys(self):
        app=self.app
        self.assertFalse(app._fullscreen_keyboard_block_enabled)
        app._install_fullscreen_keyboard_guard()
        self.assertIsNotNone(app._keyboard_hook_handle)
        thread=app._keyboard_guard_thread
        app._remove_fullscreen_keyboard_guard()
        self.assertFalse(thread.is_alive())

    def test_markdown_close_releases_extra_theme_callbacks_and_timers(self):
        self.start();app=self.app;app.show_board('md')
        owned=tuple(app.markdown._owned_callbacks)
        self.assertTrue(owned)
        app.close_board()
        self.assertIsNone(app.markdown.widget)
        self.assertFalse(app.markdown._owned_callbacks)
        self.assertTrue(all(callback not in ctk.AppearanceModeTracker.callback_list for callback in owned))

    def test_markdown_fills_board_and_hide_restore_preserves_reading_position(self):
        self.start();app=self.app;app.enter_fullscreen();app.show_board('md')
        app.markdown.render(app.board_body,'# 長篇白板\n\n'+('\n\n閱讀內容'*100))
        self.pump(300)
        widget=app.markdown.widget
        self.assertIs(widget.master,app.board_body)
        self.assertAlmostEqual(widget.winfo_height(),app.board_body.winfo_height(),delta=2)
        self.assertAlmostEqual(widget.winfo_width(),app.board_body.winfo_width(),delta=2)
        widget._textbox.yview_moveto(.5);self.pump(100)
        position=widget._textbox.yview()
        self.assertGreater(position[0],0)
        app.hide_board();self.pump(100)
        restore=app.restore_button
        self.assertTrue(restore.winfo_ismapped())
        self.assertGreaterEqual(restore.winfo_x(),0)
        self.assertLess(restore.winfo_x()+restore.winfo_width(),app.scene.winfo_width()*.25)
        self.assertGreater(restore.winfo_y(),app.scene.winfo_height()*.8)
        self.assertLessEqual(restore.winfo_y()+restore.winfo_height(),app.scene.winfo_height())
        app.restore_board();self.pump(200)
        self.assertFalse(restore.winfo_ismapped())
        self.assertIs(app.markdown.widget,widget)
        self.assertAlmostEqual(widget._textbox.yview()[0],position[0],delta=.01)

    def test_each_visible_board_suppresses_activity_and_hide_close_resume_it(self):
        self.start();app=self.app
        for kind in ('md','image','html'):
            with self.subTest(kind=kind),patch('main_window.NativeHtmlRenderer'):
                app.controller.phase=Phase.IDLE;app.last_activity_prompt=0
                app.show_board(kind)
                app.input_monitor.set_activity_paused.assert_called_with(True)
                before=len(app._message_blocks)
                app.on_activity('mouse');app.on_activity('keyboard')
                self.assertEqual(len(app._message_blocks),before)
                self.assertEqual(app.controller.phase,Phase.IDLE)
                app.refresh()
                app.input_monitor.set_activity_paused.assert_called_with(True)
                app.hide_board()
                app.input_monitor.set_activity_paused.assert_called_with(False)
                app.restore_board()
                app.input_monitor.set_activity_paused.assert_called_with(True)
                app.close_board()
                app.input_monitor.set_activity_paused.assert_called_with(False)
        app.on_activity('mouse')
        self.assertEqual(app.controller.phase,Phase.LISTENING)

    def test_hiding_board_does_not_unpause_activity_during_speech_or_mute(self):
        self.start();app=self.app
        for phase,muted in [(Phase.SPEAKING,False),(Phase.IDLE,True)]:
            with self.subTest(phase=phase,muted=muted):
                app.controller.phase=phase;app.controller.manual_mute=muted
                app.show_board('md');app.hide_board()
                app.input_monitor.set_activity_paused.assert_called_with(True)

    def test_html_created_during_speech_is_already_ducked(self):
        self.start();app=self.app;app.controller.phase=Phase.SPEAKING
        with patch('main_window.NativeHtmlRenderer') as factory:
            app.show_board('html')
            factory.return_value.set_ducked.assert_called_with(True)

    def pump(self,milliseconds=650):
        self.app.after(milliseconds,self.app.quit)
        self.app.mainloop()
        self.assertFalse(self.errors)

    def assert_full_monitor(self):
        host=self.app._fullscreen_host
        target=host.monitor_bounds()
        self.assertEqual(host.window_bounds(),target)
        self.assertEqual(host.client_bounds(),Bounds(0,0,target.width,target.height))
        self.assertTrue(self.app.attributes('-fullscreen'))
        self.assertEqual(self.app._native_root,host.hwnd)

    def test_fullscreen_covers_native_monitor_and_client_after_scaling_changes(self):
        self.start()
        previous=ctk.ScalingTracker.window_scaling
        try:
            self.app.enter_fullscreen()
            for scale in (1,1.25,1.5,2):
                with self.subTest(window_scaling=scale):
                    # App-local scaling only; the OS DPI setting is unchanged.
                    ctk.set_window_scaling(scale)
                    self.pump()
                    self.assert_full_monitor()
        finally:
            ctk.set_window_scaling(previous)

    def test_fullscreen_repairs_native_resize_without_exposing_exit_controls(self):
        self.start();app=self.app;app.enter_fullscreen();self.pump()
        host=app._fullscreen_host;target=host.monitor_bounds()
        host._checked(host.api.SetWindowPos(host.hwnd,None,target.left+20,target.top+20,
                      target.width-80,target.height-80,0x0004|0x0010))
        self.pump();self.assert_full_monitor()
        self.assertEqual(app._fullscreen_exit_shortcuts,app._normalize_fullscreen_shortcuts(['ALT+F4']))
        self.assertTrue(app._should_block_fullscreen_keyboard_shortcut(0x7A))
        self.assertTrue(app._should_block_fullscreen_keyboard_shortcut(0x1B))
        self.assertFalse(app._should_block_fullscreen_keyboard_shortcut(0x73,0x20))

    def test_review_whiteboard_buttons_dispatch_each_format(self):
        self.start();app=self.app;app.build_review_tools()
        panel=app.shell.grid_slaves(row=2,column=0)[0]
        buttons={widget.cget('text'):widget for widget in panel.winfo_children() if isinstance(widget,ctk.CTkButton)}
        with patch.object(app,'show_board') as show:
            for title,kind in [('Markdown','md'),('圖片','image'),('HTML','html')]:
                buttons[title].invoke();show.assert_called_with(kind)

    def test_persisted_exhausted_quota_is_visible_and_demo_reset_reopens_html(self):
        saved=HtmlBudget(Path(self.temp.name)/'html-budget.json',1800)
        saved.used=1800;saved.save()
        self.start();app=self.app;app.build_review_tools()
        self.assertEqual(app._review_html_button.cget('state'),'disabled')
        self.assertIn('今日已用完',app._review_quota_label.cget('text'))
        app.show_board('md')
        with patch('main_window.NativeHtmlRenderer') as factory:
            app.show_board('html')
            factory.assert_not_called()
            self.assertEqual(app.board_kind,'md')
            panel=app.shell.grid_slaves(row=2,column=0)[0]
            reset=next(widget for widget in panel.winfo_children()
                       if isinstance(widget,ctk.CTkButton) and widget.cget('text')=='重設額度')
            reset.invoke()
            self.assertEqual(app._review_html_button.cget('state'),'normal')
            self.assertEqual(app._review_quota_label.cget('text'),'HTML 30:00')
            app._review_html_button.invoke()
            factory.return_value.show.assert_called_once()
        self.assertEqual(HtmlBudget(saved.path,1800).remaining,1800)

    def test_review_reset_does_not_unlock_html_after_storage_failure(self):
        self.start();app=self.app;app.build_review_tools()
        app.budget.used=app.budget.limit
        with patch.object(app.budget,'save',side_effect=OSError('disk failed')):
            app.reset_budget()
        self.assertTrue(app._budget_failed)
        self.assertEqual(app._review_html_button.cget('state'),'disabled')
        self.assertIn('儲存失敗',app._review_quota_label.cget('text'))

    def test_zero_daily_limit_stays_disabled_after_demo_reset(self):
        self.start();app=self.app;app.budget.limit=0;app.build_review_tools()
        app.reset_budget()
        self.assertEqual(app._review_html_button.cget('state'),'disabled')
        with patch('main_window.NativeHtmlRenderer') as factory:
            app.show_board('html');factory.assert_not_called()

    def test_startup_window_and_footer_stay_inside_monitor_work_area(self):
        self.pump(400)
        app=self.app;host=FullscreenHost(app.winfo_id())
        rect=host.window_bounds();work=host.monitor_bounds(work_area=True)
        self.assertGreaterEqual(rect.left,work.left);self.assertLessEqual(rect.right,work.right)
        self.assertGreaterEqual(rect.top,work.top);self.assertLessEqual(rect.bottom,work.bottom)
        footer=app.startup.next.master
        self.assertLessEqual(footer.winfo_y()+footer.winfo_height(),app.startup.winfo_height())

    def test_styled_menu_keyboard_choice_invalidates_catalog_and_releases_root_bindings(self):
        app=self.app;view=app.startup
        view.query();self.pump(400);self.assertTrue(view.ready)
        combo=next(widget for panel in view.content.winfo_children()
            for body in panel.winfo_children() for widget in body.winfo_children()
            if isinstance(widget,OwnedComboBox) and widget.cget('variable') is view.backend)
        sequences=('<Button-1>','<MouseWheel>','<Configure>','<Unmap>')
        before={sequence:app.bind(sequence).strip() for sequence in sequences}
        combo._open_dropdown_menu()
        self.assertAlmostEqual(combo._popup.winfo_width(),combo.winfo_width(),delta=2)
        combo._highlight(0);combo._move_selection(1);combo._accept_selection()
        self.pump(200)
        self.assertEqual(view.backend.get(),'claude_code')
        self.assertFalse(view.ready);self.assertFalse(view.models)
        self.assertFalse(combo.winfo_exists())
        self.assertIsNone(app._open_combo)
        self.assertEqual({sequence:app.bind(sequence).strip() for sequence in sequences},before)

    def test_long_model_menu_scrolls_to_keyboard_selection_and_cleans_up(self):
        app=self.app;self.pump(300)
        chosen=[];variable=ctk.StringVar(value='model-0')
        combo=OwnedComboBox(app.startup.content,variable=variable,state='readonly',
            values=[f'model-{index}' for index in range(500)],command=chosen.append)
        combo.pack(fill='x')
        self.addCleanup(lambda:combo.destroy() if not app._is_closing() and combo.winfo_exists() else None)
        before=app.bind('<MouseWheel>').strip()
        combo._open_dropdown_menu()
        self.assertLessEqual(len(combo._menu_rows),11)
        self.assertLessEqual(combo._popup.winfo_height()/combo._get_widget_scaling(),368)
        combo._highlight(499);combo._reveal_selection()
        app.update_idletasks()
        self.assertGreater(combo._menu_canvas.yview()[0],0)
        self.assertIn('model-499',[text.cget('text') for row,text,check in combo._menu_rows])
        combo._accept_selection()
        self.assertEqual(variable.get(),'model-499');self.assertEqual(chosen,['model-499'])
        self.assertIsNone(combo._popup)
        self.assertEqual(app.bind('<MouseWheel>').strip(),before)

    def test_styled_menu_dismiss_disable_replace_and_destroy_preserve_existing_bindings(self):
        app=self.app;self.pump(300)
        combo=OwnedComboBox(app.startup.content,state='readonly',values=['one','two'])
        combo.pack(fill='x')
        self.addCleanup(lambda:combo.destroy() if not app._is_closing() and combo.winfo_exists() else None)
        before=app.bind('<Button-1>').strip()
        for action in (lambda:combo._dismiss_selection(),
                       lambda:combo._outside_click(SimpleNamespace(widget=app.startup)),
                       lambda:combo._root_changed(SimpleNamespace(widget=app)),
                       lambda:combo.configure(values=['one','two']),
                       lambda:combo.configure(state='disabled')):
            combo._open_dropdown_menu();self.assertIsNotNone(combo._popup)
            action()
            self.assertIsNone(combo._popup);self.assertEqual(app.bind('<Button-1>').strip(),before)
        combo._open_dropdown_menu();self.assertIsNone(combo._popup)
        combo.configure(state='readonly');combo._open_dropdown_menu();combo.destroy()
        self.assertIsNone(app._open_combo)
        self.assertEqual(app.bind('<Button-1>').strip(),before)


class FullscreenBoundsTests(unittest.TestCase):
    def test_negative_monitor_origin_preserves_focus_and_z_order(self):
        host=FullscreenHost.__new__(FullscreenHost)
        host.hwnd=123;host.api=Mock()
        host.api.SetWindowPos.return_value=True
        target=Bounds(-1920,-120,0,1080)
        host.monitor_bounds=Mock(return_value=target)
        host.window_bounds=Mock(side_effect=[Bounds(-1500,0,-300,800),target])
        self.assertEqual(host.fit(),target)
        host.api.SetWindowPos.assert_called_once_with(123,None,-1920,-120,1920,1200,0x0004|0x0010|0x0020)
        host.fit()
        self.assertEqual(host.api.SetWindowPos.call_count,1)


if __name__=='__main__': unittest.main()
