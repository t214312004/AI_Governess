import queue
import sys
import threading
import types
import pytest
from unittest.mock import MagicMock, patch

from core.state_machine import State
from ui.main_window import (
    CHAT_BUBBLE_MAX_WRAP,
    ES_CONTINUOUS,
    ES_DISPLAY_REQUIRED,
    ES_SYSTEM_REQUIRED,
    LLKHF_ALTDOWN,
    MAX_VISIBLE_CHAT_TURNS,
    OVERLAY_PANEL_RELWIDTH,
    SC_MONITORPOWER,
    SC_SCREENSAVE,
    VK_ESCAPE,
    VK_F4,
    VK_LWIN,
    VK_SPACE,
    VK_TAB,
    FONT_BODY,
    VoiceAssistantUI,
    WHITEBOARD_MARKDOWN_FONT,
    WHITEBOARD_TABLE_CELL_FONT,
    WHITEBOARD_TABLE_HEADER_FONT,
    WhiteboardMarkdownRenderer,
)


def make_ui_stub():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui._windowed_geometry = "1920x1160+0+0"
    ui.update_idletasks = MagicMock()
    ui.after_idle = MagicMock()
    ui.winfo_screenwidth = MagicMock(return_value=2560)
    ui.winfo_screenheight = MagicMock(return_value=1440)
    ui.overrideredirect = MagicMock()
    ui.geometry = MagicMock()
    ui.attributes = MagicMock()
    ui.lift = MagicMock()
    ui.focus_force = MagicMock()
    ui.after = MagicMock()
    ui.after_cancel = MagicMock()
    ui.state = MagicMock()
    ui._set_display_awake = MagicMock()
    ui._set_screensaver_block = MagicMock()
    ui._set_keyboard_shortcut_block = MagicMock()
    ui.input_monitor = MagicMock()
    ui._ui_event_queue = queue.SimpleQueue()
    ui._ui_event_after_id = None
    ui._closing_event = threading.Event()
    ui._startup_fullscreen_pending = True
    return ui


class FakeChatScroll:
    def __init__(self):
        self.children = []
        self._parent_canvas = MagicMock()

    def winfo_children(self):
        return list(self.children)


class FakeBubbleWidget:
    def __init__(self, parent, text: str, role: str):
        self.parent = parent
        self.text = text
        self.role = role
        self.wraplength = None
        self.pack_kwargs = None
        self.destroyed = False

    def set_wraplength(self, wraplength: int):
        self.wraplength = wraplength

    def pack(self, **kwargs):
        self.pack_kwargs = kwargs
        if self not in self.parent.children:
            self.parent.children.append(self)

    def update_text(self, text: str):
        self.text = text

    def destroy(self):
        self.destroyed = True
        if self in self.parent.children:
            self.parent.children.remove(self)


def test_set_fullscreen_enables_borderless_screen_sized_window():
    ui = make_ui_stub()

    VoiceAssistantUI._set_fullscreen(ui, True)

    ui.update_idletasks.assert_called_once()
    ui.overrideredirect.assert_called_once_with(True)
    ui.geometry.assert_called_once_with("2560x1440+0+0")
    ui.attributes.assert_called_once_with("-topmost", True)
    ui._set_display_awake.assert_called_once_with(True)
    ui._set_screensaver_block.assert_called_once_with(True)
    ui._set_keyboard_shortcut_block.assert_called_once_with(True)
    ui.after_idle.assert_called_once()

    assert ui.after.call_count == 2
    assert ui.after.call_args_list[0][0][0] == 10
    assert ui.after.call_args_list[1][0][0] == 120

    callback = ui.after.call_args_list[0][0][1]
    callback()
    ui.attributes.assert_any_call("-topmost", False)


def test_set_fullscreen_disables_borderless_and_restores_window():
    ui = make_ui_stub()

    VoiceAssistantUI._set_fullscreen(ui, False)

    ui.update_idletasks.assert_called_once()
    ui.overrideredirect.assert_called_once_with(False)
    ui.geometry.assert_called_once_with("1920x1160+0+0")
    ui.state.assert_called_once_with("zoomed")
    ui._set_display_awake.assert_called_once_with(False)
    ui._set_screensaver_block.assert_called_once_with(False)
    ui._set_keyboard_shortcut_block.assert_called_once_with(False)
    ui.after_idle.assert_called_once()
    assert ui.after.call_count == 1
    assert ui.after.call_args_list[0][0][0] == 120


def test_raise_for_speaking_if_fullscreen_requests_transient_topmost():
    ui = make_ui_stub()
    ui.overrideredirect.return_value = True

    VoiceAssistantUI._raise_for_speaking_if_fullscreen(ui, State.IDLE_LISTEN, State.SPEAKING)

    ui.attributes.assert_called_once_with("-topmost", True)
    ui.lift.assert_called_once()
    ui.focus_force.assert_called_once()
    ui.after.assert_called_once()
    assert ui.after.call_args[0][0] == 10

    callback = ui.after.call_args[0][1]
    callback()
    ui.attributes.assert_any_call("-topmost", False)


def test_raise_for_speaking_if_fullscreen_ignores_non_transition_or_windowed():
    ui = make_ui_stub()
    ui.overrideredirect.return_value = True

    VoiceAssistantUI._raise_for_speaking_if_fullscreen(ui, State.SPEAKING, State.SPEAKING)
    VoiceAssistantUI._raise_for_speaking_if_fullscreen(ui, State.IDLE_LISTEN, State.COLLECTING)

    ui.overrideredirect.return_value = False
    VoiceAssistantUI._raise_for_speaking_if_fullscreen(ui, State.IDLE_LISTEN, State.SPEAKING)

    ui.attributes.assert_not_called()
    ui.lift.assert_not_called()
    ui.focus_force.assert_not_called()


def test_get_logical_screen_size_uses_tk_screen_metrics():
    ui = make_ui_stub()

    logical_width, logical_height = VoiceAssistantUI._get_logical_screen_size(ui)

    assert (logical_width, logical_height) == (2560, 1440)


def test_enter_startup_fullscreen_waits_until_main_frame_is_ready():
    ui = make_ui_stub()
    ui.main_frame = MagicMock()
    ui.main_frame.winfo_width.return_value = 1
    ui.main_frame.winfo_height.return_value = 1
    ui._set_fullscreen = MagicMock()

    VoiceAssistantUI._enter_startup_fullscreen(ui)

    assert ui._startup_fullscreen_pending is True
    ui._set_fullscreen.assert_not_called()
    ui.after.assert_called_once()
    assert ui.after.call_args[0][0] == 30


def test_enter_startup_fullscreen_applies_fullscreen_once_layout_is_ready():
    ui = make_ui_stub()
    ui.main_frame = MagicMock()
    ui.main_frame.winfo_width.return_value = 1920
    ui.main_frame.winfo_height.return_value = 1200
    ui._set_fullscreen = MagicMock()

    VoiceAssistantUI._enter_startup_fullscreen(ui)

    assert ui._startup_fullscreen_pending is False
    ui._set_fullscreen.assert_called_once_with(True)


def test_toggle_fullscreen_enters_when_windowed():
    ui = make_ui_stub()
    ui.overrideredirect.return_value = False
    ui._set_fullscreen = MagicMock()

    result = VoiceAssistantUI._toggle_fullscreen(ui)

    assert result == "break"
    ui._set_fullscreen.assert_called_once_with(True)


def test_toggle_fullscreen_exits_when_already_fullscreen():
    ui = make_ui_stub()
    ui.overrideredirect.return_value = True
    ui._set_fullscreen = MagicMock()

    result = VoiceAssistantUI._toggle_fullscreen(ui)

    assert result == "break"
    ui._set_fullscreen.assert_called_once_with(False)


def test_exit_fullscreen_returns_break():
    ui = make_ui_stub()
    ui._set_fullscreen = MagicMock()

    result = VoiceAssistantUI._exit_fullscreen(ui)

    assert result == "break"
    ui._set_fullscreen.assert_called_once_with(False)


def test_normalize_fullscreen_shortcuts_accepts_aliases_and_deduplicates():
    shortcuts = VoiceAssistantUI._normalize_fullscreen_shortcuts(
        ["escape", "F11", "alt + f4", "CONTROL+SHIFT+A", "ESC"]
    )

    assert shortcuts == (
        (frozenset(), "ESC"),
        (frozenset(), "F11"),
        (frozenset({"ALT"}), "F4"),
        (frozenset({"CTRL", "SHIFT"}), "A"),
    )


def test_configure_fullscreen_exit_shortcuts_binds_only_configured_values():
    ui = make_ui_stub()
    ui.bind = MagicMock()

    with patch("ui.main_window.config.get", return_value=["ALT+F4"]):
        VoiceAssistantUI._configure_fullscreen_exit_shortcuts(ui)

    assert ui._fullscreen_exit_shortcuts == ((frozenset({"ALT"}), "F4"),)
    ui.bind.assert_called_once_with(
        "<Alt-F4>",
        ui._handle_fullscreen_exit_shortcut,
        add="+",
    )


def test_configure_fullscreen_enter_shortcuts_binds_only_configured_values():
    ui = make_ui_stub()
    ui.bind = MagicMock()

    with patch("ui.main_window.config.get", return_value=["F11"]):
        VoiceAssistantUI._configure_fullscreen_enter_shortcuts(ui)

    assert ui._fullscreen_enter_shortcuts == ((frozenset(), "F11"),)
    ui.bind.assert_called_once_with(
        "<F11>",
        ui._handle_fullscreen_enter_shortcut,
        add="+",
    )


def test_alt_f4_only_configuration_matches_no_other_exit_shortcut():
    ui = make_ui_stub()
    ui._fullscreen_exit_shortcuts = ((frozenset({"ALT"}), "F4"),)

    assert VoiceAssistantUI._matches_fullscreen_exit_shortcut(
        ui,
        VK_F4,
        flags=LLKHF_ALTDOWN,
    )
    assert not VoiceAssistantUI._matches_fullscreen_exit_shortcut(ui, VK_F4)
    assert not VoiceAssistantUI._matches_fullscreen_exit_shortcut(ui, VK_ESCAPE)
    assert not VoiceAssistantUI._matches_fullscreen_exit_shortcut(
        ui,
        VK_ESCAPE,
        flags=LLKHF_ALTDOWN,
    )


def test_fullscreen_exit_waits_until_all_shortcut_modifiers_are_released():
    modifiers = frozenset({"CTRL", "ALT", "SHIFT"})

    assert not VoiceAssistantUI._fullscreen_exit_modifiers_released(
        modifiers,
        ctrl_down=False,
        alt_down=True,
        shift_down=False,
    )
    assert not VoiceAssistantUI._fullscreen_exit_modifiers_released(
        modifiers,
        ctrl_down=True,
        alt_down=False,
        shift_down=False,
    )
    assert VoiceAssistantUI._fullscreen_exit_modifiers_released(
        modifiers,
        ctrl_down=False,
        alt_down=False,
        shift_down=False,
    )


def test_fullscreen_exit_handler_only_exits_while_fullscreen():
    ui = make_ui_stub()
    ui._set_fullscreen = MagicMock()
    ui.overrideredirect.return_value = True

    assert VoiceAssistantUI._handle_fullscreen_exit_shortcut(ui) == "break"
    ui._set_fullscreen.assert_called_once_with(False)

    ui._set_fullscreen.reset_mock()
    ui.overrideredirect.return_value = False
    assert VoiceAssistantUI._handle_fullscreen_exit_shortcut(ui) is None
    ui._set_fullscreen.assert_not_called()


def test_fullscreen_exit_handler_rejects_unconfigured_modifier_variant():
    ui = make_ui_stub()
    ui._fullscreen_exit_shortcuts = ((frozenset(), "ESC"),)
    ui._set_fullscreen = MagicMock()
    ui.overrideredirect.return_value = True
    shifted_escape = types.SimpleNamespace(keysym="Escape", state=0x0001)

    with patch.object(
        VoiceAssistantUI,
        "_get_windows_pressed_modifiers",
        return_value=frozenset({"SHIFT"}),
    ):
        assert VoiceAssistantUI._handle_fullscreen_exit_shortcut(ui, shifted_escape) is None
    ui._set_fullscreen.assert_not_called()


def test_fullscreen_enter_handler_only_enters_while_windowed():
    ui = make_ui_stub()
    ui._fullscreen_enter_shortcuts = ((frozenset(), "F11"),)
    ui._set_fullscreen = MagicMock()
    f11_event = types.SimpleNamespace(keysym="F11", state=0)
    ui.overrideredirect.return_value = False

    assert VoiceAssistantUI._handle_fullscreen_enter_shortcut(ui, f11_event) == "break"
    ui._set_fullscreen.assert_called_once_with(True)

    ui._set_fullscreen.reset_mock()
    ui.overrideredirect.return_value = True
    assert VoiceAssistantUI._handle_fullscreen_enter_shortcut(ui, f11_event) is None
    ui._set_fullscreen.assert_not_called()


def test_local_shortcut_modes_make_f11_enter_only_and_alt_f4_exit_only():
    ui = make_ui_stub()
    ui._fullscreen_exit_shortcuts = ((frozenset({"ALT"}), "F4"),)
    ui._fullscreen_enter_shortcuts = ((frozenset(), "F11"),)
    ui._set_fullscreen = MagicMock()
    f11_event = types.SimpleNamespace(keysym="F11", state=0)
    alt_f4_event = types.SimpleNamespace(keysym="F4", state=0x0008)

    def pressed_modifiers():
        return frozenset({"ALT"}) if current_event[0] is alt_f4_event else frozenset()

    current_event = [f11_event]
    with patch.object(
        VoiceAssistantUI,
        "_get_windows_pressed_modifiers",
        side_effect=pressed_modifiers,
    ):
        ui.overrideredirect.return_value = True
        assert VoiceAssistantUI._handle_fullscreen_enter_shortcut(ui, f11_event) is None
        assert VoiceAssistantUI._handle_fullscreen_exit_shortcut(ui, f11_event) is None
        current_event[0] = alt_f4_event
        assert VoiceAssistantUI._handle_fullscreen_exit_shortcut(ui, alt_f4_event) == "break"
        ui._set_fullscreen.assert_called_once_with(False)

        ui._set_fullscreen.reset_mock()
        ui.overrideredirect.return_value = False
        assert VoiceAssistantUI._handle_fullscreen_exit_shortcut(ui, alt_f4_event) is None
        current_event[0] = f11_event
        assert VoiceAssistantUI._handle_fullscreen_enter_shortcut(ui, f11_event) == "break"
        ui._set_fullscreen.assert_called_once_with(True)


def test_windows_tk_shortcut_ignores_platform_specific_event_state_bits():
    event = types.SimpleNamespace(keysym="F11", state=0x0008)

    with patch.object(
        VoiceAssistantUI,
        "_get_windows_pressed_modifiers",
        return_value=frozenset(),
    ):
        assert VoiceAssistantUI._shortcut_from_tk_event(event) == (frozenset(), "F11")


def test_set_display_awake_enables_display_and_system_required(mocker):
    execution_state = mocker.patch(
        "ui.main_window.ctypes.windll.kernel32.SetThreadExecutionState"
    )
    ui = make_ui_stub()

    VoiceAssistantUI._set_display_awake(ui, True)

    execution_state.assert_called_once_with(
        ES_CONTINUOUS | ES_DISPLAY_REQUIRED | ES_SYSTEM_REQUIRED
    )


def test_set_display_awake_restores_default_execution_state(mocker):
    execution_state = mocker.patch(
        "ui.main_window.ctypes.windll.kernel32.SetThreadExecutionState"
    )
    ui = make_ui_stub()

    VoiceAssistantUI._set_display_awake(ui, False)

    execution_state.assert_called_once_with(ES_CONTINUOUS)


def test_should_block_fullscreen_system_command_only_for_screen_related_commands():
    assert VoiceAssistantUI._should_block_fullscreen_system_command(SC_SCREENSAVE)
    assert VoiceAssistantUI._should_block_fullscreen_system_command(SC_SCREENSAVE | 0x0002)
    assert VoiceAssistantUI._should_block_fullscreen_system_command(SC_MONITORPOWER)
    assert not VoiceAssistantUI._should_block_fullscreen_system_command(0xF060)


def test_set_screensaver_block_routes_to_install_and_remove_helpers():
    ui = make_ui_stub()
    ui._install_fullscreen_screen_guard = MagicMock()
    ui._remove_fullscreen_screen_guard = MagicMock()

    VoiceAssistantUI._set_screensaver_block(ui, True)
    VoiceAssistantUI._set_screensaver_block(ui, False)

    ui._install_fullscreen_screen_guard.assert_called_once()
    ui._remove_fullscreen_screen_guard.assert_called_once()


def test_should_block_fullscreen_keyboard_shortcut_only_for_switch_keys():
    assert VoiceAssistantUI._should_block_fullscreen_keyboard_shortcut(VK_LWIN)
    assert VoiceAssistantUI._should_block_fullscreen_keyboard_shortcut(
        VK_TAB,
        flags=LLKHF_ALTDOWN,
    )
    assert VoiceAssistantUI._should_block_fullscreen_keyboard_shortcut(
        VK_ESCAPE,
        ctrl_down=True,
    )
    assert not VoiceAssistantUI._should_block_fullscreen_keyboard_shortcut(
        VK_F4,
        flags=LLKHF_ALTDOWN,
    )
    assert VoiceAssistantUI._should_block_fullscreen_keyboard_shortcut(
        VK_SPACE,
        flags=LLKHF_ALTDOWN,
    )
    assert not VoiceAssistantUI._should_block_fullscreen_keyboard_shortcut(ord("A"))
    assert not VoiceAssistantUI._should_block_fullscreen_keyboard_shortcut(0x0D)
    assert not VoiceAssistantUI._should_block_fullscreen_keyboard_shortcut(
        ord("C"),
        ctrl_down=True,
    )


def test_set_keyboard_shortcut_block_routes_to_install_and_remove_helpers():
    ui = make_ui_stub()
    ui._install_fullscreen_keyboard_guard = MagicMock()
    ui._remove_fullscreen_keyboard_guard = MagicMock()

    VoiceAssistantUI._set_keyboard_shortcut_block(ui, True)
    VoiceAssistantUI._set_keyboard_shortcut_block(ui, False)

    ui._install_fullscreen_keyboard_guard.assert_called_once()
    ui._remove_fullscreen_keyboard_guard.assert_called_once()


def test_run_clears_awake_state_and_stops_assistant():
    ui = make_ui_stub()
    ui.assistant = MagicMock()
    ui.mainloop = MagicMock()
    ui.animator = MagicMock()
    ui._set_display_awake = MagicMock()
    ui._set_screensaver_block = MagicMock()
    ui._set_keyboard_shortcut_block = MagicMock()
    flush_config = MagicMock()

    with patch("ui.main_window.config.flush", flush_config):
        VoiceAssistantUI.run(ui)

    ui.assistant.start.assert_called_once()
    ui.input_monitor.start.assert_called_once()
    ui.mainloop.assert_called_once()
    ui.input_monitor.stop.assert_called_once()
    ui._set_keyboard_shortcut_block.assert_called_once_with(False)
    ui._set_screensaver_block.assert_called_once_with(False)
    ui._set_display_awake.assert_called_once_with(False)
    ui.animator.destroy.assert_called_once()
    flush_config.assert_called_once()
    ui.assistant.stop.assert_called_once()


def test_stop_status_pulse_ignores_destroyed_indicator():
    ui = make_ui_stub()
    ui.after_cancel = MagicMock()
    ui._pulse_after_id = "pulse-token"
    ui.state_indicator = MagicMock()
    ui.state_indicator.winfo_exists.return_value = False

    VoiceAssistantUI._stop_status_pulse(ui)

    ui.after_cancel.assert_called_once_with("pulse-token")
    ui.state_indicator.configure.assert_not_called()
    ui.state_indicator.place.assert_not_called()


def test_run_continues_shutdown_when_cleanup_step_raises():
    ui = make_ui_stub()
    ui.assistant = MagicMock()
    ui.mainloop = MagicMock()
    ui.animator = MagicMock()
    ui._set_display_awake = MagicMock()
    ui._set_screensaver_block = MagicMock()
    ui._set_keyboard_shortcut_block = MagicMock()
    ui._stop_status_pulse = MagicMock(side_effect=RuntimeError("widget destroyed"))
    flush_config = MagicMock()

    with patch("ui.main_window.config.flush", flush_config):
        VoiceAssistantUI.run(ui)

    ui.input_monitor.stop.assert_called_once()
    ui._set_keyboard_shortcut_block.assert_called_once_with(False)
    ui._set_screensaver_block.assert_called_once_with(False)
    ui.animator.destroy.assert_called_once()
    flush_config.assert_called_once()
    ui.assistant.stop.assert_called_once()


def test_ui_event_queue_runs_callbacks_only_from_poller():
    ui = make_ui_stub()
    callback = MagicMock()
    ui._ui_event_queue.put((callback, ("value",), {"flag": True}))

    VoiceAssistantUI._drain_ui_events(ui)

    callback.assert_called_once_with("value", flag=True)
    ui.after.assert_called_once_with(20, ui._drain_ui_events)


def test_begin_ui_shutdown_detaches_callbacks_and_drops_late_events():
    ui = make_ui_stub()
    ui.assistant = MagicMock()
    ui._ui_event_after_id = "ui-poll"
    queued_callback = MagicMock()
    ui._ui_event_queue.put((queued_callback, (), {}))

    VoiceAssistantUI._begin_ui_shutdown(ui)
    posted = VoiceAssistantUI._post_to_ui(ui, queued_callback)

    assert posted is False
    assert ui._closing_event.is_set()
    ui.assistant.clear_callbacks.assert_called_once()
    ui.after_cancel.assert_called_once_with("ui-poll")
    with pytest.raises(queue.Empty):
        ui._ui_event_queue.get_nowait()
    queued_callback.assert_not_called()


def test_compute_proportional_panel_widths_follow_ratio():
    left_width, right_width = VoiceAssistantUI._compute_proportional_panel_widths(
        total_width=1920,
        left_weight=64,
        right_weight=36,
    )

    assert left_width + right_width <= 1920
    assert left_width == 1229
    assert right_width == 691


def test_compute_proportional_panel_widths_handle_zero_total_weight():
    left_width, right_width = VoiceAssistantUI._compute_proportional_panel_widths(
        total_width=900,
        left_weight=0,
        right_weight=0,
    )

    assert left_width == 0
    assert right_width == 0


def test_apply_panel_split_uses_proportional_widths_and_logical_sizes():
    ui = make_ui_stub()
    ui.main_frame = MagicMock()
    ui.main_frame.winfo_width.return_value = 1920
    ui.main_frame.winfo_height.return_value = 1080

    ui.left_panel = MagicMock()
    ui.left_panel._reverse_widget_scaling.side_effect = lambda value: value / 1.25

    ui.right_panel = MagicMock()
    ui.right_panel._reverse_widget_scaling.side_effect = lambda value: value / 1.25

    VoiceAssistantUI._apply_panel_split(ui)

    ui.main_frame.grid_columnconfigure.assert_any_call(0, weight=64, minsize=1229)
    ui.main_frame.grid_columnconfigure.assert_any_call(1, weight=36, minsize=691)
    ui.left_panel.configure.assert_called_once_with(width=983)
    ui.right_panel.configure.assert_called_once_with(width=553)
    ui.after_idle.assert_called_once()


def test_apply_panel_split_reserves_required_right_panel_width():
    ui = make_ui_stub()
    ui.main_frame = MagicMock()
    ui.main_frame.winfo_width.return_value = 1024
    ui.main_frame.winfo_height.return_value = 600
    ui.left_panel = MagicMock()
    ui.right_panel = MagicMock()

    VoiceAssistantUI._apply_panel_split(ui)

    ui.main_frame.grid_columnconfigure.assert_any_call(0, weight=64, minsize=612)
    ui.main_frame.grid_columnconfigure.assert_any_call(1, weight=36, minsize=412)


def test_compute_right_panel_content_min_width_keeps_send_button_visible():
    content_min_width = VoiceAssistantUI._compute_right_panel_content_min_width()

    assert content_min_width >= 400


def test_compute_available_wraplength_subtracts_badges_and_padding():
    wraplength = VoiceAssistantUI._compute_available_wraplength(
        container_width=472,
        occupied_widths=(104,),
        padding=56,
        min_wrap=160,
    )

    assert wraplength == 312


def test_compute_available_wraplength_respects_minimum():
    wraplength = VoiceAssistantUI._compute_available_wraplength(
        container_width=180,
        occupied_widths=(72,),
        padding=48,
        min_wrap=160,
    )

    assert wraplength == 160


def test_compute_inner_width_subtracts_horizontal_padding():
    inner_width = VoiceAssistantUI._compute_inner_width(
        container_width=500,
        horizontal_padding=28,
    )

    assert inner_width == 472


def test_compute_chat_bubble_wraplength_tracks_available_width_and_cap():
    wraplength = VoiceAssistantUI._compute_chat_bubble_wraplength(chat_content_width=472)

    assert wraplength == 400

    capped_wraplength = VoiceAssistantUI._compute_chat_bubble_wraplength(chat_content_width=700)

    assert capped_wraplength == CHAT_BUBBLE_MAX_WRAP


def test_update_right_panel_text_layout_uses_visible_panel_width():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.right_panel = MagicMock()
    ui.right_panel.winfo_width.return_value = 500
    ui.right_panel.winfo_reqwidth.return_value = 500

    ui.chat_header = MagicMock()
    ui.chat_header_badge = MagicMock()
    ui.chat_header_badge.winfo_width.return_value = 180
    ui.chat_header_badge.winfo_reqwidth.return_value = 180
    ui.chat_header_hint = MagicMock()

    ui.empty_state = MagicMock()
    ui.empty_state_title = MagicMock()
    ui.empty_state_body = MagicMock()
    ui.empty_state_hint = MagicMock()

    ui.input_helper = MagicMock()
    ui.input_mode_hint = MagicMock()
    ui.input_mode_hint.winfo_width.return_value = 120
    ui.input_mode_hint.winfo_reqwidth.return_value = 120
    ui.input_helper_label = MagicMock()

    VoiceAssistantUI._update_right_panel_text_layout(ui)

    ui.chat_header.configure.assert_called_once_with(width=472)
    ui.chat_header_hint.configure.assert_called_once_with(wraplength=236)

    ui.empty_state.configure.assert_called_once_with(width=448)
    ui.empty_state_title.configure.assert_called_once_with(wraplength=412)
    ui.empty_state_body.configure.assert_called_once_with(wraplength=412)
    ui.empty_state_hint.configure.assert_called_once_with(wraplength=412)

    ui.input_helper.configure.assert_called_once_with(width=476)
    ui.input_helper_label.configure.assert_called_once_with(wraplength=308)


def test_update_right_panel_text_layout_updates_existing_chat_bubbles():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.right_panel = MagicMock()
    ui.right_panel.winfo_width.return_value = 500
    ui.right_panel.winfo_reqwidth.return_value = 500

    ui.chat_header = MagicMock()
    ui.chat_header_badge = MagicMock()
    ui.chat_header_badge.winfo_width.return_value = 180
    ui.chat_header_badge.winfo_reqwidth.return_value = 180
    ui.chat_header_hint = MagicMock()

    ui.empty_state = MagicMock()
    ui.empty_state_title = MagicMock()
    ui.empty_state_body = MagicMock()
    ui.empty_state_hint = MagicMock()

    ui.input_helper = MagicMock()
    ui.input_mode_hint = MagicMock()
    ui.input_mode_hint.winfo_width.return_value = 120
    ui.input_mode_hint.winfo_reqwidth.return_value = 120
    ui.input_helper_label = MagicMock()

    bubble_one = MagicMock()
    bubble_two = MagicMock()
    other_child = MagicMock()
    del other_child.set_wraplength

    ui.chat_scroll = MagicMock()
    ui.chat_scroll.winfo_children.return_value = [bubble_one, other_child, bubble_two]

    VoiceAssistantUI._update_right_panel_text_layout(ui)

    bubble_one.set_wraplength.assert_called_once_with(400)
    bubble_two.set_wraplength.assert_called_once_with(400)


def test_sync_settings_drawer_uses_wide_overlay_width():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui._settings_visible = True
    ui.settings_drawer = MagicMock()
    ui.settings_button = MagicMock()

    VoiceAssistantUI._sync_settings_drawer_visibility(ui)

    ui.settings_drawer.place.assert_called_once()
    place_kwargs = ui.settings_drawer.place.call_args.kwargs
    assert place_kwargs["relwidth"] == OVERLAY_PANEL_RELWIDTH
    assert place_kwargs["relwidth"] >= 0.75
    assert place_kwargs["relheight"] == 0.84


def test_sync_settings_drawer_uses_near_full_width_on_compact_panel():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui._settings_visible = True
    ui._compact_topbar = True
    ui.right_panel = MagicMock()
    ui.right_panel._current_width = 430
    ui.settings_drawer = MagicMock()
    ui.settings_button = MagicMock()

    VoiceAssistantUI._sync_settings_drawer_visibility(ui)

    place_kwargs = ui.settings_drawer.place.call_args.kwargs
    assert place_kwargs["relwidth"] == 0.96
    assert place_kwargs["y"] == 162


def test_sync_schedule_panel_uses_wide_overlay_width():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui._schedule_visible = True
    ui.schedule_panel = MagicMock()
    ui.schedule_button = MagicMock()

    VoiceAssistantUI._sync_schedule_panel_visibility(ui)

    ui.schedule_panel.place.assert_called_once()
    place_kwargs = ui.schedule_panel.place.call_args.kwargs
    assert place_kwargs["relwidth"] == OVERLAY_PANEL_RELWIDTH
    assert place_kwargs["relwidth"] >= 0.75
    assert place_kwargs["relheight"] == 0.84


def test_render_whiteboard_state_none_hides_overlay():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.whiteboard_panel = MagicMock()
    ui.whiteboard_body = MagicMock()
    ui.whiteboard_body.winfo_children.return_value = []
    ui.whiteboard_markdown_renderer = MagicMock()
    ui.input_monitor = MagicMock()

    VoiceAssistantUI._render_whiteboard_state(ui, None)

    ui.whiteboard_panel.place_forget.assert_called_once()
    ui.whiteboard_markdown_renderer.clear.assert_called_once()
    ui.input_monitor.set_activity_paused.assert_called_once_with(False)
    assert ui._whiteboard_current_state is None


def test_render_whiteboard_markdown_calls_renderer_and_lifts(tmp_path):
    app_dir = tmp_path / "app"
    markdown_path = app_dir / "whiteboard_state" / "assets" / "wb_1" / "content.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text("# 白板", encoding="utf-8")
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.assistant = MagicMock()
    ui.assistant.app_dir = str(app_dir)
    ui.whiteboard_title_label = MagicMock()
    ui.whiteboard_panel = MagicMock()
    ui.whiteboard_body = MagicMock()
    ui.whiteboard_body.winfo_children.return_value = []
    ui.whiteboard_markdown_renderer = MagicMock()
    ui.input_monitor = MagicMock()

    VoiceAssistantUI._render_whiteboard_state(
        ui,
        {
            "content_id": "wb_1",
            "content_type": "markdown",
            "title": "白板",
            "markdown_path": "whiteboard_state/assets/wb_1/content.md",
        },
    )

    ui.whiteboard_title_label.configure.assert_called_once_with(text="白板")
    ui.whiteboard_markdown_renderer.render.assert_called_once_with(ui.whiteboard_body, "# 白板")
    ui.whiteboard_panel.place.assert_called_once_with(relx=0, rely=0, relwidth=1, relheight=1)
    ui.whiteboard_panel.lift.assert_called_once()
    ui.input_monitor.set_activity_paused.assert_called_once_with(True)


def test_whiteboard_markdown_renderer_uses_larger_font(monkeypatch):
    created = {}

    class FakeMarkdown:
        def __init__(self, parent, **kwargs):
            created["parent"] = parent
            created["kwargs"] = kwargs

        def pack(self, **kwargs):
            created["pack"] = kwargs

        def set_markdown(self, markdown):
            created["markdown"] = markdown

        def configure(self, **kwargs):
            created["configure"] = kwargs

    monkeypatch.setitem(
        sys.modules,
        "ctk_markdown",
        types.SimpleNamespace(CTkMarkdown=FakeMarkdown),
    )
    renderer = WhiteboardMarkdownRenderer()
    parent = MagicMock()

    renderer.render(parent, "# 白板")

    assert WHITEBOARD_MARKDOWN_FONT == (FONT_BODY[0], FONT_BODY[1] + 4)
    assert created["parent"] is parent
    assert created["kwargs"]["font"] == WHITEBOARD_MARKDOWN_FONT
    assert created["markdown"] == "# 白板"


def test_whiteboard_markdown_renderer_uses_larger_table_fonts(monkeypatch):
    created = {"labels": []}

    class FakeTextbox:
        def yview_scroll(self, *_args):
            pass

        def window_create(self, *_args, **_kwargs):
            created["window_created"] = True

    class FakeMarkdown:
        def __init__(self, parent, **kwargs):
            created["parent"] = parent
            created["kwargs"] = kwargs
            self._textbox = FakeTextbox()
            self._theme_colors = {
                "light": {
                    "table_border": "#000",
                    "table_header_bg": "#111",
                    "table_header_fg": "#222",
                    "table_cell_bg": "#333",
                    "table_cell_fg": "#444",
                    "table_row_alt_bg": "#555",
                }
            }

        def _get_mode(self, _mode=None):
            return "light"

        def insert(self, *_args):
            pass

        def pack(self, **kwargs):
            created["pack"] = kwargs

        def set_markdown(self, markdown):
            created["markdown"] = markdown
            self._insert_table(
                [
                    "| **A** | B |",
                    "|---|---|",
                    "| **1** | 2 |",
                    "| __3__ | x **partial** |",
                ]
            )

        def configure(self, **kwargs):
            created["configure"] = kwargs

    class FakeFrame:
        def __init__(self, parent, **kwargs):
            created["frame_parent"] = parent
            created["frame_kwargs"] = kwargs

        def bind(self, *_args):
            pass

        def columnconfigure(self, *_args, **_kwargs):
            pass

        def configure(self, **kwargs):
            created["frame_configure"] = kwargs

    class FakeLabel:
        def __init__(self, parent, **kwargs):
            self.parent = parent
            self.kwargs = kwargs
            created["labels"].append(self)

        def grid(self, **kwargs):
            self.grid_kwargs = kwargs

        def bind(self, *_args):
            pass

        def configure(self, **kwargs):
            self.configure_kwargs = kwargs

    monkeypatch.setitem(
        sys.modules,
        "ctk_markdown",
        types.SimpleNamespace(CTkMarkdown=FakeMarkdown),
    )
    monkeypatch.setattr("ui.main_window.tk.Frame", FakeFrame)
    monkeypatch.setattr("ui.main_window.tk.Label", FakeLabel)

    renderer = WhiteboardMarkdownRenderer()
    parent = MagicMock()

    renderer.render(parent, "| A | B |\n|---|---|\n| 1 | 2 |")

    labels = created["labels"]
    assert len(labels) == 6
    assert labels[0].kwargs["text"] == "A"
    assert labels[0].kwargs["font"] == WHITEBOARD_TABLE_HEADER_FONT
    assert labels[1].kwargs["font"] == WHITEBOARD_TABLE_HEADER_FONT
    assert labels[2].kwargs["text"] == "1"
    assert labels[2].kwargs["font"] == WHITEBOARD_TABLE_HEADER_FONT
    assert labels[3].kwargs["text"] == "2"
    assert labels[3].kwargs["font"] == WHITEBOARD_TABLE_CELL_FONT
    assert labels[4].kwargs["text"] == "3"
    assert labels[4].kwargs["font"] == WHITEBOARD_TABLE_HEADER_FONT
    assert labels[5].kwargs["text"] == "x **partial**"
    assert labels[5].kwargs["font"] == WHITEBOARD_TABLE_CELL_FONT
    assert created["window_created"] is True


def test_close_whiteboard_from_ui_calls_manager_with_content_id():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    manager = MagicMock()
    manager.active_mtime_ns.return_value = None
    manager.get_active.return_value = None
    ui.assistant = MagicMock()
    ui.assistant.whiteboard_manager = manager
    ui._whiteboard_current_state = {"content_id": "wb_1"}
    ui._render_whiteboard_state = MagicMock()

    VoiceAssistantUI._close_whiteboard_from_ui(ui)

    manager.close.assert_called_once_with("wb_1")
    ui._render_whiteboard_state.assert_called_once_with(None)


def test_stage_card_resize_updates_whiteboard_layout():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui._update_stage_image_layout = MagicMock()
    ui._update_whiteboard_layout = MagicMock()
    ui._stage_resize_after_id = "previous-resize"
    ui.after = MagicMock(return_value="next-resize")
    ui.after_cancel = MagicMock()

    VoiceAssistantUI._on_stage_card_resize(ui, MagicMock())

    ui._update_stage_image_layout.assert_not_called()
    ui.after_cancel.assert_called_once_with("previous-resize")
    assert ui.after.call_args.args[0] == 180
    assert ui._stage_resize_after_id == "next-resize"
    ui._update_whiteboard_layout.assert_called_once()


def test_scheduled_stage_card_resize_updates_image_once():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui._stage_resize_after_id = "pending-resize"
    ui._update_stage_image_layout = MagicMock()

    VoiceAssistantUI._apply_scheduled_stage_image_layout(ui)

    assert ui._stage_resize_after_id is None
    ui._update_stage_image_layout.assert_called_once()


@pytest.mark.parametrize("widget_scaling", [1.0, 1.25, 1.5])
@pytest.mark.parametrize(
    ("source_size", "expected_size"),
    [
        ((1000, 750), (800, 600)),
        ((750, 1000), (450, 600)),
        ((2000, 500), (800, 200)),
    ],
)
def test_whiteboard_image_fit_size_is_dpi_independent(
    widget_scaling,
    source_size,
    expected_size,
):
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.update_idletasks = MagicMock()
    ui.whiteboard_body = MagicMock()
    ui.whiteboard_body.winfo_width.return_value = round(800 * widget_scaling)
    ui.whiteboard_body.winfo_height.return_value = round(600 * widget_scaling)
    ui.whiteboard_body._reverse_widget_scaling.side_effect = (
        lambda value: value / widget_scaling
    )

    display_size = VoiceAssistantUI._whiteboard_image_fit_size(ui, source_size)

    assert display_size == expected_size
    assert round(display_size[0] * widget_scaling) <= ui.whiteboard_body.winfo_width()
    assert round(display_size[1] * widget_scaling) <= ui.whiteboard_body.winfo_height()


@pytest.mark.parametrize("widget_scaling", [1.0, 1.25, 1.5])
def test_whiteboard_image_fit_size_fallback_is_dpi_independent(widget_scaling):
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.update_idletasks = MagicMock()
    ui.whiteboard_body = MagicMock()
    ui.whiteboard_body.winfo_width.return_value = 1
    ui.whiteboard_body.winfo_height.return_value = 1
    ui.whiteboard_body._reverse_widget_scaling.side_effect = (
        lambda value: value / widget_scaling
    )
    ui.stage_card = MagicMock()
    ui.stage_card.winfo_width.return_value = round(1000 * widget_scaling)
    ui.stage_card.winfo_height.return_value = round(800 * widget_scaling)
    ui.stage_card._reverse_widget_scaling.side_effect = (
        lambda value: value / widget_scaling
    )

    display_size = VoiceAssistantUI._whiteboard_image_fit_size(ui, (1000, 750))

    assert display_size == (939, 704)
    assert round(display_size[0] * widget_scaling) <= round(952 * widget_scaling)
    assert round(display_size[1] * widget_scaling) <= round(704 * widget_scaling)


def test_load_whiteboard_display_image_releases_source_file(tmp_path):
    import shutil

    from PIL import Image

    asset_dir = tmp_path / "asset"
    asset_dir.mkdir()
    image_path = asset_dir / "sample.png"
    Image.new("RGB", (10, 10), color="white").save(image_path)
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)

    loaded = VoiceAssistantUI._load_whiteboard_display_image(ui, image_path)
    try:
        shutil.rmtree(asset_dir)
    finally:
        loaded.close()

    assert not asset_dir.exists()


def test_on_text_submit_reads_multiline_textbox_and_clears():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.text_input = MagicMock()
    ui.text_input.get.return_value = "first line\nsecond line"
    ui.assistant = MagicMock()
    ui.assistant.send_text_message.return_value = (True, None)
    ui.add_message_ui = MagicMock()
    ui._refresh_interaction_controls = MagicMock()
    ui._sync_text_input_placeholder = MagicMock()
    event = MagicMock()
    event.state = 0

    result = VoiceAssistantUI._on_text_submit(ui, event)

    assert result == "break"
    ui.text_input.get.assert_called_once_with("1.0", "end-1c")
    ui.assistant.send_text_message.assert_called_once_with("first line\nsecond line")
    ui.text_input.delete.assert_called_once_with("1.0", "end")
    ui.add_message_ui.assert_called_once_with("user", "first line\nsecond line")
    ui._sync_text_input_placeholder.assert_called_once()


def test_on_text_submit_shift_enter_inserts_newline_without_sending():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.text_input = MagicMock()
    ui.assistant = MagicMock()
    ui._sync_text_input_placeholder = MagicMock()
    event = MagicMock()
    event.state = 0x0001

    result = VoiceAssistantUI._on_text_submit(ui, event)

    assert result == "break"
    ui.text_input.insert.assert_called_once_with("insert", "\n")
    ui.assistant.send_text_message.assert_not_called()
    ui._sync_text_input_placeholder.assert_called_once()


def test_add_bubble_logic_applies_current_wraplength_to_new_bubbles(mocker):
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui._message_count = 0
    ui.empty_state = MagicMock()
    ui.chat_scroll = MagicMock()
    ui.chat_scroll._parent_canvas = MagicMock()
    ui.after = MagicMock()
    ui.last_ai_bubble = None
    ui.right_panel = MagicMock()
    ui.right_panel.winfo_width.return_value = 500
    ui.right_panel.winfo_reqwidth.return_value = 500

    user_bubble = MagicMock()
    assistant_bubble = MagicMock()
    chat_bubble = mocker.patch(
        "ui.main_window.ChatBubble",
        side_effect=[user_bubble, assistant_bubble],
    )

    VoiceAssistantUI._add_bubble_logic(ui, "user", "hello")
    VoiceAssistantUI._add_bubble_logic(ui, "assistant", "reply")

    assert chat_bubble.call_count == 2
    user_bubble.set_wraplength.assert_called_once_with(400)
    assistant_bubble.set_wraplength.assert_called_once_with(400)
    user_bubble.pack.assert_called_once_with(fill="x", padx=8, pady=3)
    assistant_bubble.pack.assert_called_once_with(fill="x", padx=8, pady=3)


def test_add_bubble_logic_prefixes_user_bubble_when_speaker_known(mocker):
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui._message_count = 0
    ui.empty_state = MagicMock()
    ui.chat_scroll = MagicMock()
    ui.chat_scroll._parent_canvas = MagicMock()
    ui.after = MagicMock()
    ui.last_ai_bubble = None
    ui.right_panel = MagicMock()
    ui.right_panel.winfo_width.return_value = 500
    ui.right_panel.winfo_reqwidth.return_value = 500

    user_bubble = MagicMock()
    chat_bubble = mocker.patch(
        "ui.main_window.ChatBubble",
        return_value=user_bubble,
    )

    VoiceAssistantUI._add_bubble_logic(ui, "user", "hello", speaker_name="PersonB")

    chat_bubble.assert_called_once_with(ui.chat_scroll, text="PersonB: hello", role="user")
    user_bubble.set_wraplength.assert_called_once_with(400)
    user_bubble.pack.assert_called_once_with(fill="x", padx=8, pady=3)


def test_add_bubble_logic_updates_existing_assistant_bubble_wraplength_when_streaming():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui._message_count = 1
    ui.chat_scroll = MagicMock()
    ui.chat_scroll._parent_canvas = MagicMock()
    ui.after = MagicMock()
    ui.right_panel = MagicMock()
    ui.right_panel.winfo_width.return_value = 500
    ui.right_panel.winfo_reqwidth.return_value = 500

    ui.last_ai_bubble = MagicMock()

    VoiceAssistantUI._add_bubble_logic(ui, "assistant", "streamed reply")

    ui.last_ai_bubble.set_wraplength.assert_called_once_with(400)
    ui.last_ai_bubble.update_text.assert_called_once_with("streamed reply")


def test_scroll_chat_to_latest_refreshes_scrollregion_before_scrolling():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui._chat_scroll_after_id = "pending"
    ui.update_idletasks = MagicMock()
    ui.chat_scroll = MagicMock()
    ui.chat_scroll._parent_canvas = MagicMock()
    ui.chat_scroll._parent_canvas.bbox.return_value = (0, 0, 320, 640)

    VoiceAssistantUI._scroll_chat_to_latest(ui)

    assert ui._chat_scroll_after_id is None
    ui.update_idletasks.assert_called_once()
    ui.chat_scroll._parent_canvas.configure.assert_called_once_with(
        scrollregion=(0, 0, 320, 640)
    )
    ui.chat_scroll._parent_canvas.yview_moveto.assert_called_once_with(1.0)


def test_schedule_chat_scroll_to_latest_cancels_previous_pending_scroll():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.chat_scroll = MagicMock()
    ui._chat_scroll_after_id = "old-after-id"
    ui.after_cancel = MagicMock()
    ui.after = MagicMock(return_value="new-after-id")

    VoiceAssistantUI._schedule_chat_scroll_to_latest(ui)

    ui.after_cancel.assert_called_once_with("old-after-id")
    ui.after.assert_called_once_with(0, ui._scroll_chat_to_latest)
    assert ui._chat_scroll_after_id == "new-after-id"


def test_clear_chat_history_ui_forwards_to_logic():
    ui = make_ui_stub()
    ui._clear_chat_history_logic = MagicMock()

    VoiceAssistantUI.clear_chat_history_ui(ui)

    callback, args, kwargs = ui._ui_event_queue.get_nowait()
    assert callback == ui._clear_chat_history_logic
    assert args == ()
    assert kwargs == {}


def test_clear_chat_history_logic_removes_messages_and_restores_empty_state():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.chat_scroll = FakeChatScroll()
    ui.empty_state = MagicMock()
    ui._message_count = 2
    ui._chat_scroll_after_id = "pending"
    ui.after_cancel = MagicMock()
    ui.after = MagicMock(return_value="new-after-id")
    user_bubble = FakeBubbleWidget(ui.chat_scroll, "user 1", "user")
    assistant_bubble = FakeBubbleWidget(ui.chat_scroll, "assistant 1", "assistant")
    user_bubble.pack()
    assistant_bubble.pack()
    ui.last_ai_bubble = assistant_bubble

    assert len(ui.chat_scroll.winfo_children()) == 2

    VoiceAssistantUI._clear_chat_history_logic(ui)

    assert ui.chat_scroll.winfo_children() == []
    assert ui._message_count == 0
    assert ui.last_ai_bubble is None
    ui.after_cancel.assert_called_once_with("pending")
    ui.empty_state.pack.assert_called_once_with(fill="x", padx=12, pady=(8, 14))
    ui.after.assert_called_once_with(0, ui._scroll_chat_to_latest)
    assert ui._chat_scroll_after_id == "new-after-id"


def test_add_bubble_logic_keeps_only_recent_three_turns(mocker):
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui._message_count = 0
    ui.empty_state = MagicMock()
    ui.chat_scroll = FakeChatScroll()
    ui.after = MagicMock()
    ui.last_ai_bubble = None
    ui.right_panel = MagicMock()
    ui.right_panel.winfo_width.return_value = 500
    ui.right_panel.winfo_reqwidth.return_value = 500

    mocker.patch(
        "ui.main_window.ChatBubble",
        side_effect=lambda master, text, role: FakeBubbleWidget(master, text, role),
    )

    for turn in range(1, MAX_VISIBLE_CHAT_TURNS + 2):
        VoiceAssistantUI._add_bubble_logic(ui, "user", f"user {turn}")
        VoiceAssistantUI._add_bubble_logic(ui, "assistant", f"assistant {turn}")

    remaining = ui.chat_scroll.winfo_children()

    assert [(child.role, child.text) for child in remaining] == [
        ("user", "user 2"),
        ("assistant", "assistant 2"),
        ("user", "user 3"),
        ("assistant", "assistant 3"),
        ("user", "user 4"),
        ("assistant", "assistant 4"),
    ]
    assert ui._message_count == 6


def test_add_bubble_logic_removes_oldest_full_turn_when_new_turn_starts(mocker):
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui._message_count = 0
    ui.empty_state = MagicMock()
    ui.chat_scroll = FakeChatScroll()
    ui.after = MagicMock()
    ui.last_ai_bubble = None
    ui.right_panel = MagicMock()
    ui.right_panel.winfo_width.return_value = 500
    ui.right_panel.winfo_reqwidth.return_value = 500

    mocker.patch(
        "ui.main_window.ChatBubble",
        side_effect=lambda master, text, role: FakeBubbleWidget(master, text, role),
    )

    for turn in range(1, MAX_VISIBLE_CHAT_TURNS + 1):
        VoiceAssistantUI._add_bubble_logic(ui, "user", f"user {turn}")
        VoiceAssistantUI._add_bubble_logic(ui, "assistant", f"assistant {turn}")

    VoiceAssistantUI._add_bubble_logic(ui, "user", "user 4")

    remaining = ui.chat_scroll.winfo_children()

    assert [(child.role, child.text) for child in remaining] == [
        ("user", "user 2"),
        ("assistant", "assistant 2"),
        ("user", "user 3"),
        ("assistant", "assistant 3"),
        ("user", "user 4"),
    ]
    assert ui._message_count == 5


def test_compute_square_image_side_stays_inside_available_area():
    side = VoiceAssistantUI._compute_square_image_side(
        available_width=1100,
        available_height=780,
        horizontal_padding=36,
        vertical_padding=36,
        min_side=240,
        max_side=760,
    )

    assert side <= 760
    assert side <= 1100 - 36
    assert side <= 780 - 36


def test_compute_square_image_side_shrinks_in_small_spaces():
    side = VoiceAssistantUI._compute_square_image_side(
        available_width=260,
        available_height=250,
        horizontal_padding=36,
        vertical_padding=36,
        min_side=240,
        max_side=760,
    )

    assert side == min(260 - 36, 250 - 36)

def test_on_primary_action_starts_manual_capture_when_idle():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui._voice_mode = True
    ui._current_state = State.IDLE_LISTEN
    ui.assistant = MagicMock()
    ui.assistant.begin_manual_capture.return_value = True
    ui.add_message_ui = MagicMock()

    VoiceAssistantUI._on_primary_action(ui)

    ui.assistant.begin_manual_capture.assert_called_once()
    ui.add_message_ui.assert_called_once()


def test_backend_change_runs_off_ui_thread(mocker):
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui._backend_switch_in_progress = False
    ui._refresh_interaction_controls = MagicMock()
    ui._change_backend_worker = MagicMock()
    thread = MagicMock()
    thread_type = mocker.patch("ui.main_window.threading.Thread", return_value=thread)

    VoiceAssistantUI._on_backend_change(ui, "codex_cli")

    thread_type.assert_called_once_with(
        target=ui._change_backend_worker,
        args=("codex_cli",),
        name="LLMBackendSwitch",
        daemon=True,
    )
    thread.start.assert_called_once()
    assert ui._backend_switch_thread is thread


def test_backend_menu_is_disabled_while_switch_is_in_progress():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui._backend_switch_in_progress = True
    ui._voice_mode = False
    ui._current_state = State.IDLE_LISTEN
    ui.assistant = MagicMock()
    ui.assistant.can_accept_text_message.return_value = True
    ui.assistant.can_change_backend.return_value = True
    ui.text_input = MagicMock()
    ui.send_button = MagicMock()
    ui.backend_menu = MagicMock()
    ui.mode_badge = MagicMock()
    ui.input_mode_hint = MagicMock()
    ui.primary_action_button = MagicMock()

    VoiceAssistantUI._refresh_interaction_controls(ui)

    ui.text_input.configure.assert_called_once_with(state="disabled")
    ui.send_button.configure.assert_called_once_with(state="disabled")
    ui.backend_menu.configure.assert_called_once_with(state="disabled")
    assert ui.primary_action_button.configure.call_args.kwargs["state"] == "disabled"


def test_cancel_pending_chat_scroll_does_not_clear_backend_switch_state():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui._chat_scroll_after_id = None
    ui._backend_switch_in_progress = True

    VoiceAssistantUI._cancel_pending_chat_scroll(ui)

    assert ui._backend_switch_in_progress is True


def test_wait_for_backend_switch_worker_joins_and_clears_finished_thread():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    worker = MagicMock()
    worker.is_alive.return_value = False
    ui._backend_switch_thread = worker

    VoiceAssistantUI._wait_for_backend_switch_worker(ui)

    worker.join.assert_called_once_with(timeout=1)
    assert ui._backend_switch_thread is None


def test_run_cleans_prepared_resources_when_assistant_start_fails():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.assistant = MagicMock()
    ui.assistant.start.side_effect = RuntimeError("startup failed")
    ui.input_monitor = MagicMock()
    ui._safe_cleanup_call = lambda _name, callback: callback()
    ui._cancel_whiteboard_poll = MagicMock()
    ui._stop_status_pulse = MagicMock()
    ui._set_keyboard_shortcut_block = MagicMock()
    ui._set_screensaver_block = MagicMock()
    ui._set_display_awake = MagicMock()
    ui.animator = MagicMock()

    with patch("ui.main_window.config.flush"), pytest.raises(RuntimeError, match="startup failed"):
        VoiceAssistantUI.run(ui)

    ui.input_monitor.stop.assert_called_once()
    ui.assistant.shutdown_prepared_resources.assert_called_once()
    ui.assistant.stop.assert_not_called()


def test_on_primary_action_hot_listen_shows_follow_up_hint_without_restarting_capture():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui._voice_mode = True
    ui._current_state = State.HOT_LISTEN
    ui.assistant = MagicMock()
    ui.add_message_ui = MagicMock()

    VoiceAssistantUI._on_primary_action(ui)

    ui.assistant.begin_manual_capture.assert_not_called()
    ui.add_message_ui.assert_called_once()


def test_update_state_logic_enables_stop_button_during_collecting():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui._current_state = State.IDLE_LISTEN
    ui.state_label = MagicMock()
    ui.state_hint_label = MagicMock()
    ui.state_indicator = MagicMock()
    ui.chat_header_badge = MagicMock()
    ui.chat_header_hint = MagicMock()
    ui.stop_button = MagicMock()
    ui.animator = MagicMock()
    ui._sync_stage_ambience = MagicMock()
    ui._start_status_pulse = MagicMock()
    ui._raise_for_speaking_if_fullscreen = MagicMock()
    ui._update_context_chips = MagicMock()
    ui._refresh_interaction_controls = MagicMock()

    VoiceAssistantUI._update_state_logic(ui, State.COLLECTING)

    ui.stop_button.configure.assert_called_once_with(
        state="normal",
        fg_color="#C64E43",
        hover_color="#A83C32",
        text_color="white",
    )


def test_on_tts_rate_change_updates_assistant_runtime_settings(mocker):
    config_set = mocker.patch("ui.main_window.config.set")
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.tts_rate_label = MagicMock()
    ui.tts_backend_var = MagicMock()
    ui.tts_backend_var.get.return_value = "edge"
    ui.assistant = MagicMock()

    VoiceAssistantUI._on_tts_rate_change(ui, "15")

    ui.tts_rate_label.configure.assert_called_once_with(text="+15%")
    config_set.assert_called_once_with("tts", "rate", value="+15%")
    ui.assistant.update_tts_settings.assert_called_once_with(rate="+15%")


def test_on_tts_rate_change_clamps_to_supported_range(mocker):
    config_set = mocker.patch("ui.main_window.config.set")
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.tts_rate_label = MagicMock()
    ui.tts_backend_var = MagicMock()
    ui.tts_backend_var.get.return_value = "edge"
    ui.assistant = MagicMock()

    VoiceAssistantUI._on_tts_rate_change(ui, "100")

    ui.tts_rate_label.configure.assert_called_once_with(text="+30%")
    config_set.assert_called_once_with("tts", "rate", value="+30%")
    ui.assistant.update_tts_settings.assert_called_once_with(rate="+30%")


def test_on_tts_rate_change_ignores_bluemagpie_backend(mocker):
    config_set = mocker.patch("ui.main_window.config.set")
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.tts_rate_label = MagicMock()
    ui.tts_backend_var = MagicMock()
    ui.tts_backend_var.get.return_value = "bluemagpie"
    ui.assistant = MagicMock()

    VoiceAssistantUI._on_tts_rate_change(ui, "15")

    ui.tts_rate_label.configure.assert_called_once_with(text="N/A")
    config_set.assert_not_called()
    ui.assistant.update_tts_settings.assert_not_called()


def test_on_tts_backend_change_updates_config_and_disables_edge_rate(mocker):
    config_set = mocker.patch("ui.main_window.config.set")
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.tts_backend_var = MagicMock()
    ui.tts_backend_var.get.return_value = "bluemagpie"
    ui.tts_rate_slider = MagicMock()
    ui.tts_rate_label = MagicMock()
    ui.add_message_ui = MagicMock()

    VoiceAssistantUI._on_tts_backend_change(ui, "bluemagpie")

    config_set.assert_called_once_with("tts", "backend", value="bluemagpie")
    ui.tts_backend_var.set.assert_called_once_with("bluemagpie")
    ui.tts_rate_slider.configure.assert_called_once_with(state="disabled")
    ui.tts_rate_label.configure.assert_called_once_with(text="N/A")
    ui.add_message_ui.assert_called_once_with("system", "TTS backend 已設為 bluemagpie，重啟後生效")


def test_parse_rate_clamps_existing_config_value():
    assert VoiceAssistantUI._parse_rate("+100%") == 30.0
    assert VoiceAssistantUI._parse_rate("-50%") == -30.0


def test_on_hot_listen_toggle_applies_runtime_settings(mocker):
    config_set = mocker.patch("ui.main_window.config.set")
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.hot_listen_var = MagicMock()
    ui.hot_listen_var.get.return_value = False
    ui.assistant = MagicMock()
    ui._update_context_chips = MagicMock()

    VoiceAssistantUI._on_hot_listen_toggle(ui)

    config_set.assert_called_once_with("hot_listen", "enabled", value=False)
    ui.assistant.apply_hot_listen_settings.assert_called_once()
    ui._update_context_chips.assert_called_once()


def test_on_heartbeat_toggle_applies_runtime_settings(mocker):
    config_set = mocker.patch("ui.main_window.config.set")
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.heartbeat_var = MagicMock()
    ui.heartbeat_var.get.return_value = False
    ui.assistant = MagicMock()

    VoiceAssistantUI._on_heartbeat_toggle(ui)

    config_set.assert_called_once_with("heartbeat", "enabled", value=False)
    ui.assistant.apply_heartbeat_settings.assert_called_once()


def test_parse_schedule_weekdays_accepts_comma_separated_days():
    assert VoiceAssistantUI._parse_schedule_weekdays("0, 2，6") == [0, 2, 6]


def test_parse_schedule_weekdays_accepts_readable_labels():
    assert VoiceAssistantUI._parse_schedule_weekdays("週一至週五") == [0, 1, 2, 3, 4]
    assert VoiceAssistantUI._parse_schedule_weekdays("工作日") == [0, 1, 2, 3, 4]


def test_parse_schedule_weekdays_rejects_out_of_range_day():
    try:
        VoiceAssistantUI._parse_schedule_weekdays("7")
    except ValueError as exc:
        assert "weekday" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_format_schedule_weekdays_uses_readable_workday_label():
    assert VoiceAssistantUI._format_schedule_weekdays_for_input([0, 1, 2, 3, 4]) == "週一至週五"
    assert VoiceAssistantUI._format_schedule_trigger(
        {"type": "weekly", "time": "09:00", "weekdays": [0, 1, 2, 3, 4]}
    ) == "週一至週五 09:00"


def test_schedule_payload_from_form_builds_report_payload():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.schedule_title_var = MagicMock()
    ui.schedule_title_var.get.return_value = "Daily summary"
    ui.schedule_prompt_var = MagicMock()
    ui.schedule_prompt_var.get.return_value = "Summarize the day."
    ui.schedule_trigger_var = MagicMock()
    ui.schedule_trigger_var.get.return_value = "weekly"
    ui.schedule_date_var = MagicMock()
    ui.schedule_date_var.get.return_value = "2026-06-21"
    ui.schedule_time_var = MagicMock()
    ui.schedule_time_var.get.return_value = "20:00"
    ui.schedule_weekdays_var = MagicMock()
    ui.schedule_weekdays_var.get.return_value = "0,4"
    ui.schedule_report_required_var = MagicMock()
    ui.schedule_report_required_var.get.return_value = True
    ui.schedule_report_recipient_var = MagicMock()
    ui.schedule_report_recipient_var.get.return_value = "PersonA"
    ui.schedule_sensitive_report_var = MagicMock()
    ui.schedule_sensitive_report_var.get.return_value = True
    ui.schedule_keep_latest_report_only_var = MagicMock()
    ui.schedule_keep_latest_report_only_var.get.return_value = True

    payload = VoiceAssistantUI._schedule_payload_from_form(ui)

    assert payload["trigger"]["type"] == "weekly"
    assert payload["trigger"]["weekdays"] == [0, 4]
    assert payload["report"] == {
        "required": True,
        "recipient": "PersonA",
        "sensitive": True,
        "keep_latest_report_only": True,
    }


def test_update_schedule_pending_badge_shows_pending_count():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.schedule_button = MagicMock()

    VoiceAssistantUI._update_schedule_pending_badge(ui, 2)

    ui.schedule_button.configure.assert_called_once_with(text="排程 (2)")


def test_deliver_pending_report_from_ui_uses_assistant_owned_delivery():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.assistant = MagicMock()
    ui.assistant.deliver_pending_report_from_ui.return_value = (True, None)
    ui._set_schedule_form_message = MagicMock()
    ui._refresh_schedule_panel = MagicMock()

    VoiceAssistantUI._deliver_pending_report_from_ui(ui, "sched_1", "PersonA")

    ui.assistant.deliver_pending_report_from_ui.assert_called_once_with(
        recipient="PersonA",
        schedule_id="sched_1",
    )
    ui._set_schedule_form_message.assert_called_once_with("已領取排程報告。", error=False)
    ui._refresh_schedule_panel.assert_called_once()

def test_delete_schedule_from_ui_requires_confirmation(mocker):
    ask_yes_no = mocker.patch(
        "ui.main_window.messagebox.askyesno",
        return_value=False,
    )
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.assistant = MagicMock()
    ui._set_schedule_form_message = MagicMock()
    ui._refresh_schedule_panel = MagicMock()

    VoiceAssistantUI._delete_schedule_from_ui(ui, "sched_1", "Daily summary")

    ask_yes_no.assert_called_once()
    ui.assistant.schedule_manager.delete_schedule.assert_not_called()


def test_delete_schedule_from_ui_deletes_after_confirmation(mocker):
    mocker.patch("ui.main_window.messagebox.askyesno", return_value=True)
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.assistant = MagicMock()
    ui.assistant.schedule_manager.delete_schedule.return_value = {
        "status": "deleted",
        "message_for_user": "deleted",
    }
    ui._set_schedule_form_message = MagicMock()
    ui._refresh_schedule_panel = MagicMock()

    VoiceAssistantUI._delete_schedule_from_ui(ui, "sched_1", "Daily summary")

    ui.assistant.schedule_manager.delete_schedule.assert_called_once_with("sched_1")
    ui._set_schedule_form_message.assert_called_once_with("deleted", error=False)
    ui._refresh_schedule_panel.assert_called_once()


def test_save_schedule_from_form_reports_storage_failure():
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui._schedule_payload_from_form = MagicMock(return_value={"title": "test"})
    ui._schedule_editing_id = None
    ui.assistant = MagicMock()
    ui.assistant.schedule_manager.create_schedule.side_effect = OSError("disk unavailable")
    ui._set_schedule_form_message = MagicMock()

    VoiceAssistantUI._save_schedule_from_form(ui)

    ui._set_schedule_form_message.assert_called_once_with(
        "排程儲存失敗，請檢查檔案權限或稍後再試。",
        error=True,
    )


def test_on_hot_timeout_change_applies_runtime_settings(mocker):
    config_set = mocker.patch("ui.main_window.config.set")
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.hot_timeout_var = MagicMock()
    ui.hot_timeout_var.get.return_value = "7"
    ui.assistant = MagicMock()

    VoiceAssistantUI._on_hot_timeout_change(ui)

    ui.hot_timeout_var.set.assert_called_once_with("7")
    config_set.assert_called_once_with("hot_listen", "timeout_seconds", value=7.0)
    ui.assistant.apply_hot_listen_settings.assert_called_once()


def test_on_hot_timeout_change_clamps_large_values(mocker):
    config_set = mocker.patch("ui.main_window.config.set")
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.hot_timeout_var = MagicMock()
    ui.hot_timeout_var.get.return_value = "999999999999999999999"
    ui.assistant = MagicMock()

    VoiceAssistantUI._on_hot_timeout_change(ui)

    ui.hot_timeout_var.set.assert_called_once_with("60")
    config_set.assert_called_once_with("hot_listen", "timeout_seconds", value=60.0)
    ui.assistant.apply_hot_listen_settings.assert_called_once()


def test_on_vad_ms_change_updates_runtime_vad(mocker):
    config_set = mocker.patch("ui.main_window.config.set")
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.vad_ms_label = MagicMock()
    ui.assistant = MagicMock()

    VoiceAssistantUI._on_vad_ms_change(ui, "600")

    ui.vad_ms_label.configure.assert_called_once_with(text="600 ms")
    config_set.assert_called_once_with("vad", "min_silence_duration_ms", value=600)
    ui.assistant.update_vad_min_silence.assert_called_once_with(600)


def test_add_message_ui_forwards_update_existing_flag():
    ui = make_ui_stub()
    ui._add_bubble_logic = MagicMock()

    VoiceAssistantUI.add_message_ui(ui, "assistant", "follow-up", update_existing=False)
    callback, args, kwargs = ui._ui_event_queue.get_nowait()
    callback(*args, **kwargs)

    ui._add_bubble_logic.assert_called_once_with(
        "assistant",
        "follow-up",
        update_existing=False,
    )


def test_add_bubble_logic_creates_new_assistant_bubble_when_update_existing_is_false(mocker):
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui._message_count = 1
    ui.empty_state = MagicMock()
    ui.chat_scroll = FakeChatScroll()
    ui.after = MagicMock()
    ui.right_panel = MagicMock()
    ui.right_panel.winfo_width.return_value = 500
    ui.right_panel.winfo_reqwidth.return_value = 500

    existing_bubble = FakeBubbleWidget(ui.chat_scroll, "existing reply", "assistant")
    existing_bubble.pack()
    ui.last_ai_bubble = existing_bubble

    mocker.patch(
        "ui.main_window.ChatBubble",
        side_effect=lambda master, text, role: FakeBubbleWidget(master, text, role),
    )

    VoiceAssistantUI._add_bubble_logic(
        ui,
        "assistant",
        "follow-up prompt",
        update_existing=False,
    )

    remaining = ui.chat_scroll.winfo_children()

    assert len(remaining) == 2
    assert remaining[0].text == "existing reply"
    assert remaining[1].text == "follow-up prompt"
    assert ui.last_ai_bubble is remaining[1]
