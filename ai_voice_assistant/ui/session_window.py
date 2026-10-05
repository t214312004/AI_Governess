"""Production session UI. The original assistant and lifecycle remain the owner.

The base constructor installs the real callbacks, polling and Windows guards.
Only layout and startup-fixed interaction policies are replaced here.
"""
from collections import deque
import ctypes
import math
from pathlib import Path
import time
import tkinter as tk

import customtkinter as ctk
from config import config
from core.session_settings import SessionConfig, EFFORT_KEYS
from core.state_machine import State
from ui.main_window import VoiceAssistantUI as AssistantWindow
from ui.global_input_monitor import GlobalInputMonitor
from ui.components import icon_image
from ui.session_theme import (SessionIconButton as IconButton, SURFACE as PANEL,
    PRIMARY as GREEN, MUTED, GOLD, BLUE_SOFT, BLUE_LINE, WARM_SOFT,
    label, button, set_phase_style)
from ui.session_layout import build_session_layout
from ui.embedded_html import NativeHtmlRenderer
from ui.markdown_host import OwnedMarkdownRenderer
from ui.fullscreen_host import FullscreenHost
from ui.window_environment import desktop_available
from utils.logger import get_logger

logger = get_logger(__name__)


class SessionInputMonitor(GlobalInputMonitor):
    def _can_use_widget_bindings(self):
        return False  # Embedded Edge has its own event loop.

    def _is_own_app_foreground(self):
        return self.widget._keyboard_guard_in_scope()


class SessionChatBubble(ctk.CTkFrame):
    def __init__(self, parent, *, text, role, font_size):
        super().__init__(parent, fg_color='transparent')
        user = role == 'user'
        role_row = ctk.CTkFrame(self, fg_color='transparent', height=24)
        role_row.pack(fill='x', padx=3, pady=(5, 5))
        mark = ctk.CTkFrame(role_row, width=22, height=22, corner_radius=8,
                           fg_color=BLUE_SOFT if user else '#EEDBC2')
        mark.pack(side='right' if user else 'left', padx=(5, 0) if user else (0, 6))
        mark.pack_propagate(False)
        if user:
            label(mark, '你', 10, color=GREEN).place(relx=.5, rely=.5, anchor='center')
        else:
            ctk.CTkLabel(mark, text='', image=icon_image('chat', color='#8B6942', size=14),
                         width=14, height=14).place(relx=.5, rely=.5, anchor='center')
            label(role_row, 'Sophia · 愛管家', 11, color=MUTED, height=22).pack(side='left')
        self.bubble = ctk.CTkFrame(self, fg_color=BLUE_SOFT if user else WARM_SOFT,
            border_width=1, border_color=BLUE_LINE if user else '#E9D8C9', corner_radius=14)
        self.bubble.pack(fill='x', pady=(0, 8))
        self.label = label(self.bubble, text, font_size, justify='left', anchor='w', wraplength=300)
        self.label.pack(fill='x', padx=16, pady=14)

    def update_text(self, text):
        self.label.configure(text=text)

    def set_wraplength(self, wraplength):
        self.label.configure(wraplength=max(100, int(wraplength)))


class VoiceAssistantUI(AssistantWindow):
    def __init__(self, assistant, session=None):
        self.settings = config.snapshot()
        backend = self.settings['llm']['active_backend']
        selected = self.settings['llm'][backend]
        self.session = session or SessionConfig(backend, selected.get('model', ''),
            selected.get(EFFORT_KEYS.get(backend, 'reasoning_effort'), ''),
            self.settings['interaction']['voice_input'], self.settings['interaction']['voice_output'],
            self.settings['whiteboard']['html_daily_minutes'], self.settings['ui']['chat_font_size'])
        self.manual_mute = not self.session.voice_input
        self.speaker_muted = not self.session.voice_output
        self.pending = deque()
        self._pending_id = 0
        self._tick_job = self._resize_job = self._html_resize_job = self._notice_job = None
        self._html_status_job = None
        self._fullscreen_host = None
        self._fullscreen_resize_job = None
        self._native_root = None
        self._composer_focused = False
        self.board_visible = False
        self._whiteboard_rendered_content_id = None
        self._quota_failed = False
        self.budget = None
        super().__init__(assistant)
        self.title('愛管家')
        self._tick_job = self.after(250, self.tick)

    def _setup_ui(self):
        build_session_layout(self)
        # Keep all established callbacks and history helpers on their real widgets.
        self.main_frame, self.left_panel, self.right_panel = self.shell, self.stage, self.chat
        self.stage_card, self.image_frame, self.image_label = self.stage, self.scene, self.scene_label
        self.chat_scroll, self.text_input = self.messages, self.input
        self.whiteboard_panel, self.whiteboard_body = self.board, self.board_body
        self.whiteboard_title_label = self.board_title
        self.board_sound = IconButton(self.board_toolbar, 'speaker', self._toggle_html_sound, tip='白板音效')
        self.board_reload = IconButton(self.board_toolbar, 'reload', self._reload_whiteboard_html, tip='重新載入白板')
        self.whiteboard_markdown_renderer.clear()
        self.whiteboard_markdown_renderer = OwnedMarkdownRenderer()
        self.html_whiteboard_renderer.stop()
        manager = getattr(self.assistant, 'whiteboard_manager', None)
        state_dir = manager.state_dir if manager else Path(self.assistant.app_dir) / 'whiteboard_state'
        self.html_whiteboard_renderer = NativeHtmlRenderer(state_dir,
            duck_volume=self.settings['whiteboard']['html_audio_duck_volume'], ui_post=self._post_to_ui)
        if manager:
            try:
                self.budget = manager.html_budget()
            except (OSError, ValueError, KeyError, TypeError):
                self._quota_failed = True
                self.notify('無法讀取每日額度，HTML 已停用')
        self.input_monitor = SessionInputMonitor(self.assistant.on_user_activity, widget=self)
        self._voice_mode = self.session.voice_input
        self.board_body.bind('<Configure>', self.resize_html)
        if self.settings['schedule']['enabled']:
            self.schedule_button = IconButton(self.chat_header_holder, 'calendar', self._toggle_schedule_panel, tip='排程')
            self.schedule_button.pack(side='right', padx=4)
            self._build_schedule_panel(self.shell)

    def _apply_panel_split(self):
        if not hasattr(self, 'shell'):
            return
        scale = self.shell._get_widget_scaling()
        width = self.shell.winfo_width() / scale
        chat_width = min(460, max(360, int(width * .30)))
        self.shell.grid_columnconfigure(0, weight=1)
        self.shell.grid_columnconfigure(1, weight=0, minsize=chat_width)
        self.chat.configure(width=chat_width)
        self._update_right_panel_text_layout()

    def _update_right_panel_text_layout(self):
        if hasattr(self, 'chat_scroll'):
            width = self.chat.winfo_width() / self.chat._get_widget_scaling()
            self._update_chat_bubble_wraplengths(max(100, int(width) - 44))

    def _update_context_chips(self):
        pass  # Startup selections are displayed in the main header.

    def schedule_resize(self, event=None):
        self._schedule_stage_image_layout_update()

    def _update_stage_image_layout(self):
        if hasattr(self, 'animator') and not self._is_closing():
            scale = self.scene._get_widget_scaling()
            self.animator.set_image_size(max(1, int(self.scene.winfo_width() / scale)),
                                         max(1, int(self.scene.winfo_height() / scale)))

    def _update_state_logic(self, state):
        previous = self._current_state
        self._current_state = state
        self._raise_for_speaking_if_fullscreen(previous, state)
        names = {State.IDLE_LISTEN: '待機', State.HOT_LISTEN: '聆聽',
                 State.COLLECTING: '聆聽', State.SENDING: '思考', State.SPEAKING: '回應'}
        self.phase_label.configure(text='●  ' + names.get(state, '待機'))
        set_phase_style(self.phase_label, state)
        self.animator.set_state(state)
        self._sync_whiteboard_audio_ducking(state)
        self._refresh_interaction_controls()

    def _restore_whiteboard_html_focus(self):
        if self.board_visible and not self._composer_focused and not self._is_closing():
            super()._restore_whiteboard_html_focus()

    def _focus_composer(self, event=None):
        # Embedded Edge owns native focus, so Tk's normal Text click binding
        # may only record a pending focus request without emitting FocusIn.
        # Mark the composer first so delayed HTML focus checks cannot reclaim it.
        self._composer_focused = True
        self._release_whiteboard_keyboard_capture()
        self.input.focus_force()

    def _reload_whiteboard_html(self):
        self._account_budget(False)
        self._cancel_html_status_check()
        super()._reload_whiteboard_html()

    @property
    def mic_muted(self):
        return not self.session.voice_input or self.manual_mute or self._speech_active()

    def _speech_active(self):
        return not self.speaker_muted and (self._current_state == State.SPEAKING or
                                          self.assistant.audio_player.is_playing)

    def _refresh_interaction_controls(self):
        if not hasattr(self, 'mic'):
            return
        self.mic.set_status(self.mic_muted, not self.session.voice_input,
            '固定文字輸入' if not self.session.voice_input else '打斷並收音' if self._speech_active()
            else '開啟麥克風' if self.mic_muted else '關閉麥克風')
        self.speaker.set_status(self.speaker_muted, not self.session.voice_output,
            '固定文字輸出' if not self.session.voice_output else '開啟播音' if self.speaker_muted else '關閉播音')
        self.input.configure(state='normal')

    def toggle_mic(self):
        if not self.session.voice_input:
            return
        if self._speech_active():
            self.manual_mute = False
            self.assistant.set_microphone_muted(False)
            if not self.assistant.interrupt(resume_collecting=True, source='ui'):
                self.assistant.begin_manual_capture()
        else:
            self.manual_mute = not self.manual_mute
            self.assistant.set_microphone_muted(self.manual_mute)
        self._refresh_interaction_controls()

    def toggle_speaker(self):
        if self.session.voice_output:
            self.speaker_muted = not self.speaker_muted
            self.assistant.set_output_muted(self.speaker_muted)
            self._refresh_interaction_controls()

    def send(self):
        text = self.input.get('1.0', 'end').strip()
        if not text:
            return 'break'
        if len(text) > 8000 or len(self.pending) >= 10:
            self.notify('每則最多 8,000 字，最多排隊 10 則')
            return 'break'
        self._pending_id += 1
        self.pending.append((self._pending_id, text))
        self.input.delete('1.0', 'end')
        self.dispatch()
        return 'break'

    def dispatch(self):
        if self.pending and not self.assistant.audio_player.is_playing and self.assistant.can_accept_text_message():
            ident, text = self.pending[0]
            try:
                accepted, reason = self.assistant.send_text_message(text)
            except Exception:
                logger.exception('Failed to submit queued text; retaining the message.')
                accepted, reason = False, 'unavailable'
            if accepted:
                self.pending.popleft()
                self._add_bubble_logic('user', text)
            elif reason != 'busy':
                self.notify('後端尚未就緒，訊息保留在待送清單')
        self._refresh_pending()

    def _refresh_pending(self):
        signature = tuple(self.pending)
        if signature == self._queue_signature:
            return
        self._queue_signature = signature
        for child in self.queue_frame.winfo_children():
            child.destroy()
        if not self.pending:
            self.queue_frame.grid_remove()
            return
        self.queue_frame.configure(height=56 + min(100, len(self.pending)*32))
        self.queue_frame.pack_propagate(False)
        self.queue_frame.grid()
        button(self.queue_frame, f'打斷並送出 · {len(self.pending)}', self.interrupt_send,
               height=32).pack(fill='x', padx=10, pady=8)
        items = ctk.CTkScrollableFrame(self.queue_frame, height=min(100, len(self.pending)*32),
            fg_color='transparent', scrollbar_button_color='#CDBBA7')
        items.pack(fill='both', expand=True, padx=6, pady=(0, 8))
        for ident, text in self.pending:
            row = ctk.CTkFrame(items, fg_color='transparent')
            row.pack(fill='x', padx=10, pady=2)
            label(row, text[:24], 12, wraplength=240, anchor='w').pack(side='left', fill='x', expand=True)
            IconButton(row, 'close', lambda ident=ident: self.cancel_message(ident),
                       tip='取消待送訊息', width=28, height=28).pack(side='right')

    def cancel_message(self, ident):
        self.pending = deque(item for item in self.pending if item[0] != ident)
        self._refresh_pending()

    def interrupt_send(self):
        if self.pending:
            self.assistant.interrupt(source='ui')
            self.dispatch()  # A cancelled request must finish releasing its lock first.

    def notify(self, text):
        self.notice.configure(text=text)
        self.notice.grid()
        if self._notice_job:
            self.after_cancel(self._notice_job)
        self._notice_job = self.after(7000, self._clear_notice)

    def _clear_notice(self):
        self._notice_job = None
        self.notice.grid_remove()

    def _add_bubble_logic(self, role, text, **kwargs):
        super()._add_bubble_logic(role, text, **kwargs)
        self._update_right_panel_text_layout()

    def _create_chat_bubble(self, parent, *, text, role):
        return SessionChatBubble(parent, text=text, role=role, font_size=self.session.chat_font)

    def _schedule_chat_scroll_to_latest(self):
        if self.chat_scroll._parent_canvas.yview()[1] > .95:
            super()._schedule_chat_scroll_to_latest()

    def _render_whiteboard_state(self, state):
        self._account_budget(False)
        self._whiteboard_current_state = state
        if not state:
            self._clear_whiteboard_overlay()
            return
        if state.get('hidden', False):
            if self._whiteboard_rendered_content_id != state.get('content_id'):
                self._clear_whiteboard_body()
                self._whiteboard_rendered_content_id = None
            self._hide_board_display()
            return
        is_html = state.get('content_type') == 'html'
        for control in (self.board_sound, self.board_reload):
            control.pack_forget()
            if is_html:
                control.pack(side='right', padx=4)
        if is_html and not self._html_allowed():
            self.close_board()
            self.notify('今日 HTML 額度已用完' if not self._quota_failed else '無法保存每日額度，HTML 已停用')
            return
        self.board_visible = True
        self.restore_button.place_forget()
        self.board_title.configure(text=state.get('title') or '白板')
        self.board.grid(row=0, column=0, sticky='nsew', padx=8, pady=8)
        self.board.tkraise()
        self._set_whiteboard_input_monitor_paused(True)
        self._sync_whiteboard_keyboard_guard()
        if is_html:
            self.board_sound.set_status(self.html_whiteboard_renderer.is_muted, False, '白板音效')
            self.quota_row.grid()
            self._render_whiteboard_html(state)
        else:
            self.quota_row.grid_remove()
            if self._whiteboard_rendered_content_id == state.get('content_id'):
                return  # Preserve the existing document and scroll position.
            if state.get('content_type') == 'markdown':
                self._render_whiteboard_markdown(state)
            elif state.get('content_type') == 'image':
                self._render_whiteboard_image(state)
            self._whiteboard_rendered_content_id = state.get('content_id')

    def _toggle_html_sound(self):
        muted = self.html_whiteboard_renderer.toggle_muted()
        self.board_sound.set_status(muted, False, '白板音效')

    def _html_allowed(self):
        if self._quota_failed or not self.budget:
            return False
        try:
            return self.budget.refresh() > 0
        except (OSError, ValueError, KeyError, TypeError):
            logger.exception('Failed to read daily HTML quota.')
            self._quota_failed = True
            return False

    def _cancel_html_status_check(self):
        if self._html_status_job:
            self.after_cancel(self._html_status_job)
            self._html_status_job = None

    def _schedule_whiteboard_html_status(self, content_id, attempt):
        self._cancel_html_status_check()
        generation = self.html_whiteboard_renderer._generation
        self._html_status_job = self.after(100, self._check_whiteboard_html_status,
            content_id, attempt, generation)

    def _check_whiteboard_html_status(self, content_id, attempt, generation=None):
        self._html_status_job = None
        state = self._whiteboard_current_state or {}
        renderer = self.html_whiteboard_renderer
        if (self._is_closing() or not self.board_visible or state.get('content_type') != 'html'
                or state.get('content_id') != content_id
                or (generation is not None and renderer._generation != generation)):
            return
        if renderer.last_error:
            self._render_whiteboard_error(renderer.last_error)
        elif renderer.is_attached:
            # A delayed attach must not take focus from someone already typing.
            if not self._composer_focused and not renderer.focus():
                if attempt >= 160:
                    self._render_whiteboard_error('HTML 白板無法取得鍵盤焦點，請重新載入。')
                else:
                    self._schedule_whiteboard_html_status(content_id, attempt + 1)
        elif attempt >= 160:
            self._render_whiteboard_error('HTML 白板啟動逾時，請確認 Microsoft Edge 可以正常開啟。')
        else:
            self._schedule_whiteboard_html_status(content_id, attempt + 1)

    def _render_whiteboard_html(self, state):
        self._clear_whiteboard_body()
        self._html_host = tk.Frame(self.board_body, bg=PANEL)
        self._html_host.pack(fill='both', expand=True)
        super()._render_whiteboard_html(state)

    def _clear_whiteboard_body(self, *, stop_html=True):
        self._cancel_html_status_check()
        # The legacy HTML method clears before showing. Its new host must survive.
        if not stop_html and hasattr(self, '_html_host') and self._html_host.winfo_exists():
            self.whiteboard_markdown_renderer.clear()
            self._whiteboard_image_ref = None
            return
        super()._clear_whiteboard_body(stop_html=stop_html)

    def _whiteboard_html_geometry(self):
        self.update_idletasks()
        host = self._html_host
        return host.winfo_id(), max(1, host.winfo_width()), max(1, host.winfo_height())

    def _clear_whiteboard_overlay(self):
        self.board_visible = False
        self._whiteboard_rendered_content_id = None
        self.board.grid_remove()
        self.restore_button.place_forget()
        self._set_whiteboard_input_monitor_paused(False)
        self._clear_whiteboard_body()

    def _hide_board_display(self):
        self._account_budget(False)
        self._cancel_html_status_check()
        self.board_visible = False
        self._release_whiteboard_keyboard_capture()
        if (self._whiteboard_current_state or {}).get('content_type') == 'html':
            self.html_whiteboard_renderer.stop()
        self.board.grid_remove()
        self.restore_button.place(x=18, rely=1, y=-18, anchor='sw')
        self.restore_button.lift()
        self._set_whiteboard_input_monitor_paused(False)

    def restore_board(self):
        self._set_board_hidden(False)

    def hide_board(self):
        self._set_board_hidden(True)

    def _set_board_hidden(self, hidden):
        manager = self.assistant.whiteboard_manager
        state = self._whiteboard_current_state or {}
        self._account_budget(False)
        try:
            result = (manager.hide if hidden else manager.restore)(state.get('content_id'))
            self._whiteboard_active_mtime_ns = manager.active_mtime_ns()
            self._render_whiteboard_state(manager.get_active())
            if result.get('status') not in ('hidden', 'restored', 'empty'):
                self.notify(result.get('message_for_user') or '白板顯示狀態未變更')
        except Exception:
            logger.exception('Failed to change whiteboard visibility.')
            self.notify('白板顯示狀態未變更，請稍後再試')

    def close_board(self):
        self._account_budget(False)
        self._close_whiteboard_from_ui()

    def resize_html(self, event=None):
        if self._html_resize_job:
            self.after_cancel(self._html_resize_job)
        self._html_resize_job = self.after(80, self._resize_board_now)

    def _resize_board_now(self):
        self._html_resize_job = None
        self._update_whiteboard_layout()

    def _update_whiteboard_layout(self):
        if not self.board_visible:
            return
        state = self._whiteboard_current_state or {}
        if state.get('content_type') == 'html' and hasattr(self, '_html_host'):
            self.html_whiteboard_renderer.resize(*self._whiteboard_html_geometry())
        elif state.get('content_type') == 'image':
            self._render_whiteboard_image(state)
        else:
            self.whiteboard_markdown_renderer.resize()

    def _account_budget(self, active=None):
        if not self.budget or self._quota_failed:
            return
        settle = active is not None
        if active is None:
            active = (self.board_visible and (self._whiteboard_current_state or {}).get('content_type') == 'html'
                      and self.html_whiteboard_renderer.is_attached and self.state() != 'iconic' and desktop_available())
        try:
            self.budget.tick(active, settle=settle)
        except (OSError, ValueError, KeyError, TypeError):
            self._quota_failed = True
            self.html_whiteboard_renderer.stop()
            self.notify('無法保存每日額度，HTML 已停用')

    def tick(self):
        self._tick_job = None
        if self._is_closing():
            return
        try:
            self._tick_session()
        except Exception:
            logger.exception('Session polling failed; retrying on the next tick.')
        finally:
            if not self._is_closing():
                self._tick_job = self.after(250, self.tick)

    def _tick_session(self):
        if self.board_visible and (self._whiteboard_current_state or {}).get('content_type') == 'html':
            self.html_whiteboard_renderer.ensure_layout()
        self._account_budget()
        if self.budget:
            remaining = math.ceil(self.budget.remaining)
            self.quota_label.configure(text=f'{remaining//60:02}:{remaining%60:02}')
            self.quota_bar.set(self.budget.remaining / max(1, self.budget.limit))
            self.quota_bar.configure(progress_color=GOLD if remaining <= self.budget.limit * .15 else GREEN)
            if self.board_visible and (self._whiteboard_current_state or {}).get('content_type') == 'html' and (not remaining or self._quota_failed):
                self.close_board()
                self.notify('今日 HTML 額度已用完' if not self._quota_failed else '無法保存每日額度，HTML 已停用')
        self.dispatch()
        self._refresh_interaction_controls()

    def _update_schedule_pending_badge(self, pending_count=None):
        if hasattr(self, 'schedule_button'):
            manager = getattr(self.assistant, 'schedule_manager', None)
            count = pending_count if pending_count is not None else manager.count_pending_reports() if manager else 0
            self.schedule_button.tip = f'排程 · 待讀 {count}' if count else '排程'

    def _set_fullscreen(self, enabled):
        if not enabled:
            return
        self.update_idletasks()
        self.minsize(0, 0)
        self.attributes('-fullscreen', True)
        self.update_idletasks()
        self._fullscreen_host = FullscreenHost(self.winfo_id())
        self._fullscreen_host.fit()
        self._native_root = self._fullscreen_host.hwnd
        self.bind('<Configure>', self._schedule_fullscreen_fit, add='+')
        self._set_display_awake(True)
        self._set_screensaver_block(True)
        self._set_keyboard_shortcut_block(True)
        self._schedule_window_mode_layout_refresh()

    def _schedule_fullscreen_fit(self, event=None):
        if event is not None and event.widget is not self:
            return
        if not self._is_closing() and self._fullscreen_host and not self._fullscreen_resize_job:
            self._fullscreen_resize_job = self.after_idle(self._fit_fullscreen)

    def _fit_fullscreen(self):
        self._fullscreen_resize_job = None
        if self._fullscreen_host and not self._is_closing():
            self._fullscreen_host.fit()

    def _configure_fullscreen_exit_shortcuts(self):
        self._fullscreen_exit_shortcuts = self._normalize_fullscreen_shortcuts(['ALT+F4'])
        self.bind('<Alt-F4>', self._handle_fullscreen_exit_shortcut)
        self.bind('<F11>', lambda event: 'break')
        self.bind('<Escape>', lambda event: 'break')

    def _configure_fullscreen_enter_shortcuts(self):
        self._fullscreen_enter_shortcuts = ()

    def _handle_fullscreen_exit_shortcut(self, event=None):
        self._close_session()
        return 'break'

    def _on_close_requested(self):
        pass  # A session has no window close control; only the Alt+F4 binding exits.

    @staticmethod
    def _should_block_fullscreen_keyboard_shortcut(vk_code, flags=0, ctrl_down=False):
        return vk_code in (0x7A, 0x1B) or AssistantWindow._should_block_fullscreen_keyboard_shortcut(vk_code, flags, ctrl_down)

    def _keyboard_guard_in_scope(self):
        if self._is_closing():
            return False
        if GlobalInputMonitor._is_own_app_foreground():
            return True
        api = ctypes.windll.user32
        api.GetForegroundWindow.restype = ctypes.c_void_p
        api.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        api.GetAncestor.restype = ctypes.c_void_p
        hwnd = api.GetForegroundWindow()
        if hwnd and self._native_root and api.GetAncestor(hwnd, 2) == self._native_root:
            return True
        self.html_whiteboard_renderer.set_keyboard_capture(False)
        return False

    def _forward_captured_whiteboard_key(self, *args, **kwargs):
        if self._composer_focused or not self.board_visible:
            return False
        return super()._forward_captured_whiteboard_key(*args, **kwargs)

    def _close_session(self):
        if self._is_closing():
            return
        self._account_budget(False)
        self._begin_ui_shutdown()
        self.pending.clear()
        for cleanup in (self.whiteboard_markdown_renderer.clear, self.input_monitor.stop,
                self.html_whiteboard_renderer.stop, lambda: self._set_keyboard_shortcut_block(False),
                lambda: self._set_screensaver_block(False), lambda: self._set_display_awake(False),
                self.animator.destroy):
            try:
                cleanup()
            except Exception:
                logger.exception('Session resource cleanup failed.')
        # This root owns its Tcl interpreter and all scheduled widgets.
        for job in self.tk.call('after', 'info'):
            self.tk.call('after', 'cancel', job)
        self.destroy()

    def _remove_fullscreen_screen_guard(self):
        hwnd = self.__dict__.get('_screen_guard_hwnd')
        previous = self.__dict__.get('_screen_guard_prev_wndproc')
        proc = self.__dict__.get('_screen_guard_proc')
        if hwnd and previous and proc:
            _, setter = self._get_window_long_accessors()
            if not setter(hwnd, -4, previous):
                # Never free a callback while the live HWND still refers to it.
                raise RuntimeError('無法還原 screen guard WindowProc')
        self._screen_guard_hwnd = self._screen_guard_prev_wndproc = self._screen_guard_proc = None
