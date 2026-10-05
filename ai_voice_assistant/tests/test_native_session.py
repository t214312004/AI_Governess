"""Opt-in Windows GUI checks. Run serially with AI_GOVERNESS_NATIVE_TESTS=1."""
from copy import deepcopy
import json
import os
from pathlib import Path
import time
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.skipif(os.environ.get('AI_GOVERNESS_NATIVE_TESTS') != '1',
    reason='Requires an unlocked interactive Windows desktop and Edge; run serially.')


@pytest.fixture
def native_ui(tmp_path):
    from config import config
    from core.whiteboard_manager import WhiteboardManager
    from core.session_settings import SessionConfig
    from ui.session_window import VoiceAssistantUI
    settings = json.loads(Path(config.default_path).read_text(encoding='utf-8'))
    old = config.snapshot()
    config._config = settings
    assistant = MagicMock()
    assistant.app_dir = str(tmp_path)
    assistant.whiteboard_manager = WhiteboardManager(tmp_path)
    assistant.schedule_manager.list_schedules.return_value = {'schedules': []}
    assistant.schedule_manager.count_pending_reports.return_value = 0
    assistant.audio_player.is_playing = False
    assistant.can_accept_text_message.return_value = True
    assistant.send_text_message.return_value = (True, None)
    ui = VoiceAssistantUI(assistant, SessionConfig('antigravity_cli', 'from-catalog', '', False, False))
    errors = []
    ui.report_callback_exception = lambda typ, value, trace: errors.append((typ.__name__, str(value)))
    ui.update()  # Map CTk once before installing bounded event-loop waits.
    yield ui, assistant, errors
    if not ui._is_closing():
        ui._close_session()
    ui.input_monitor.stop()
    ui.html_whiteboard_renderer.stop()
    ui._set_keyboard_shortcut_block(False)
    ui._set_screensaver_block(False)
    ui._set_display_awake(False)
    ui.animator.destroy()
    config._config = old


def pump(ui, seconds=.25):
    ui.after(max(1, int(seconds*1000)), ui.quit)
    ui.mainloop()


@pytest.mark.parametrize('content_type', [None, 'markdown', 'html'])
def test_composer_accepts_keyboard_input_after_click(native_ui, content_type):
    ui, assistant, errors = native_ui
    pump(ui)
    manager = assistant.whiteboard_manager
    if content_type == 'markdown':
        manager.show_markdown({'markdown': '# Input check'})
    elif content_type == 'html':
        page = manager.apps_root / 'composer-check.html'
        page.write_text('<!doctype html><h1>Input check</h1>', encoding='utf-8')
        manager.show_html({'html_path': str(page)})
    if content_type:
        ui._render_whiteboard_state(manager.get_active())
        pump(ui)
    if content_type == 'html':
        deadline = time.monotonic() + 15
        while not ui.html_whiteboard_renderer.is_attached and time.monotonic() < deadline:
            pump(ui, .2)
        assert ui.html_whiteboard_renderer.is_attached
        assert ui.html_whiteboard_renderer.focus()
        ui.html_whiteboard_renderer.set_keyboard_capture(True)
        pump(ui)
    textbox = ui.input._textbox
    textbox.event_generate('<Button-1>', x=20, y=20)
    textbox.event_generate('<ButtonRelease-1>', x=20, y=20)
    pump(ui)
    assert ui.focus_get() is textbox
    assert ui._composer_focused
    assert not ui.html_whiteboard_renderer.keyboard_capture_requested
    ui._restore_whiteboard_html_focus()
    assert ui.focus_get() is textbox
    textbox.event_generate('<KeyPress>', keysym='a')
    textbox.event_generate('<KeyPress>', keysym='b')
    textbox.event_generate('<Return>')
    textbox.event_generate('<KeyPress>', keysym='c')
    pump(ui)
    assert ui.input.get('1.0', 'end-1c') == 'ab\nc'
    assistant.send_text_message.assert_not_called()
    textbox.event_generate('<Control-Return>')
    pump(ui)
    assistant.send_text_message.assert_called_once_with('ab\nc')
    assert ui.input.get('1.0', 'end-1c') == ''
    if content_type == 'html':
        assert ui.html_whiteboard_renderer.focus()
        pump(ui)
        assert not ui._composer_focused
        assert ui.html_whiteboard_renderer.keyboard_capture_requested
        textbox.event_generate('<Button-1>', x=20, y=20)
        pump(ui)
        assert ui.focus_get() is textbox
        assert ui._composer_focused
        assert not ui.html_whiteboard_renderer.keyboard_capture_requested
    assert not errors


def test_production_layout_fullscreen_scrolling_hide_restore_and_queue(native_ui):
    ui, assistant, errors = native_ui
    pump(ui)
    host = ui._fullscreen_host
    assert host.window_bounds() == host.monitor_bounds()
    assert ui._screen_guard_proc and ui._keyboard_hook_handle
    manager = assistant.whiteboard_manager
    result = manager.show_markdown({'markdown': '# Document\n\n' + '\n\n'.join(f'Long paragraph {i}' for i in range(80))})
    assert result['status'] == 'shown'
    ui._render_whiteboard_state(manager.get_active())
    pump(ui)
    assert ui.whiteboard_body.winfo_height() > 1
    document = ui.whiteboard_markdown_renderer.widget
    assert document.winfo_height() > ui.board_body.winfo_height() * .9
    assert document._textbox.yview()[1] < 1
    assert ui.input_monitor._activity_paused
    ui.hide_board()
    assert not ui.board_visible and not ui.input_monitor._activity_paused
    assert ui.restore_button.place_info()['anchor'] == 'sw'
    ui.restore_board()
    assert ui.whiteboard_markdown_renderer.widget is document
    ui.close_board()
    ui.input.insert('1.0', '\n'.join(f'Line {i}' for i in range(30)))
    pump(ui)
    assert ui.input._textbox.yview()[1] < 1
    assistant.audio_player.is_playing = True
    ui.send()
    pump(ui)
    assert len(ui.pending) == 1
    assert ui.queue_frame.winfo_height()/ui.queue_frame._get_widget_scaling() < 170
    assistant.send_text_message.assert_not_called()
    assistant.audio_player.is_playing = False
    ui.dispatch()
    assistant.send_text_message.assert_called_once()
    assert not ui.pending
    assert not errors


def test_real_embedded_html_hide_restore_expiry_and_markdown(native_ui):
    ui, assistant, errors = native_ui
    manager = assistant.whiteboard_manager
    page = manager.apps_root / 'native-check.html'
    page.write_text('<!doctype html><html><body><h1>Native whiteboard</h1><button onclick="this.textContent=\'OK\'">Check</button></body></html>', encoding='utf-8')
    assert manager.show_html({'html_path': str(page)})['status'] == 'shown'
    ui._render_whiteboard_state(manager.get_active())
    deadline = time.monotonic()+15
    while not ui.html_whiteboard_renderer.is_attached and time.monotonic() < deadline:
        pump(ui, .2)
    assert ui.html_whiteboard_renderer.is_attached, ui.html_whiteboard_renderer.last_error
    assert ui.input_monitor._activity_paused
    before = ui.budget.remaining
    pump(ui, 1.2)
    assert ui.budget.remaining < before
    ui.hide_board()
    hidden = ui.budget.remaining
    pump(ui, .5)
    assert ui.budget.remaining == hidden
    assert not ui.html_whiteboard_renderer.is_active
    ui.restore_board()
    deadline = time.monotonic()+15
    while not ui.html_whiteboard_renderer.is_attached and time.monotonic() < deadline:
        pump(ui, .2)
    assert ui.html_whiteboard_renderer.is_attached
    ui.budget.limit = ui.budget.used
    ui.tick()
    assert manager.get_active() is None and not ui.board_visible
    assert manager.show_markdown({'markdown': '# Still readable'})['status'] == 'shown'
    ui._render_whiteboard_state(manager.get_active())
    assert ui.board_visible
    assert not errors


@pytest.mark.parametrize('content_type', ['markdown', 'image', 'html'])
def test_whiteboard_content_survives_native_ui_restart(native_ui, content_type):
    from PIL import Image
    from core.whiteboard_manager import WhiteboardManager
    from ui.session_window import VoiceAssistantUI
    ui, assistant, errors = native_ui
    manager = assistant.whiteboard_manager
    if content_type == 'markdown':
        result = manager.show_markdown({'markdown': '# Retained document\n\nSame content after restart.'})
    elif content_type == 'image':
        source = manager.payload_root / 'retained.png'
        Image.new('RGB', (320, 180), '#315E91').save(source)
        result = manager.show_image({'image_path': str(source)})
    else:
        source = manager.apps_root / 'retained.html'
        source.write_text('<!doctype html><h1>Retained HTML</h1>', encoding='utf-8')
        result = manager.show_html({'html_path': str(source)})
    assert result['status'] == 'shown'
    state = manager.get_active()
    ui._render_whiteboard_state(state)
    if content_type == 'html':
        deadline = time.monotonic()+18
        while not ui.html_whiteboard_renderer.is_attached and time.monotonic() < deadline:
            pump(ui, .2)
        assert ui.html_whiteboard_renderer.is_attached
        pump(ui, .7)
    session = ui.session
    ui._close_session()
    assert manager.get_active() == state  # Closing a session is not closing its board.
    used = json.loads((manager.state_dir / 'html-usage.json').read_text())['used_seconds']
    assistant.whiteboard_manager = WhiteboardManager(manager.app_dir)
    assert assistant.whiteboard_manager.get_active() == state
    reopened = VoiceAssistantUI(assistant, session)
    reopened.report_callback_exception = lambda typ, value, trace: errors.append((typ.__name__, str(value)))
    try:
        reopened.update()
        pump(reopened, .6)  # The normal state-file poll restores the board.
        assert reopened.board_visible and reopened._whiteboard_current_state == state
        assert reopened.budget.used >= used
        if content_type == 'html':
            deadline = time.monotonic()+18
            while not reopened.html_whiteboard_renderer.is_attached and time.monotonic() < deadline:
                pump(reopened, .2)
            assert reopened.html_whiteboard_renderer.is_attached
        elif content_type == 'markdown':
            assert 'Retained document' in reopened.whiteboard_markdown_renderer.widget.get('1.0', 'end')
        else:
            assert reopened._whiteboard_image_ref is not None
        assert not errors
    finally:
        reopened._close_session()


def test_partial_markdown_failure_releases_widget_and_timers(native_ui):
    ui, assistant, errors = native_ui
    manager = assistant.whiteboard_manager
    assert manager.show_markdown({'markdown': '# Render failure fixture'})['status'] == 'shown'
    with patch('ctk_markdown.CTkMarkdown.set_markdown', side_effect=ValueError('parse failure')):
        ui._render_whiteboard_state(manager.get_active())
    pump(ui, .6)
    assert len(ui.board_body.winfo_children()) == 1
    assert ui.whiteboard_markdown_renderer.widget.winfo_height() > ui.board_body.winfo_height() * .9
    ui.close_board()
    pump(ui, .6)
    assert not errors


def test_startup_draft_is_frozen_during_preparation():
    from config import config
    from ui.startup_window import StartupWindow
    settings = json.loads(Path(config.default_path).read_text(encoding='utf-8'))
    with patch.object(config, 'snapshot', return_value=settings):
        window = StartupWindow(MagicMock())
    errors = []
    window.report_callback_exception = lambda typ, value, trace: errors.append((typ.__name__, str(value)))
    try:
        window.update()
        view = window.view
        view.navigate(4)
        view.advance()  # Missing query returns to the first page without poisoning retry.
        assert view.step == 0 and not view.preparing
        view.set_preparing(True)
        view.navigate(3)
        view.advance()
        view.query()
        assert view.step == 0 and view.query_thread is None
        assert view.next.cget('state') == 'disabled'
        assert view.previous.cget('state') == 'disabled'
        assert all(control.cget('state') == 'disabled' for control in view.nav_buttons)
        view.set_preparing(False)
        assert view.next.cget('state') == 'normal'
        assert view.previous.cget('state') == 'disabled'  # First-page disabled state is retained.
        view.navigate(4)
        assert view.step == 4
        assert not errors
    finally:
        window._destroy_owned()
