from types import SimpleNamespace

from ui.global_input_monitor import GlobalInputMonitor


class FakeWidget:
    def __init__(self):
        self.bind_calls = []
        self.unbind_calls = []
        self._binding_index = 0

    def bind(self, sequence, callback, add=None):
        self.bind_calls.append((sequence, callback, add))
        self._binding_index += 1
        return f"bind-{self._binding_index}"

    def unbind(self, sequence, binding_id=None):
        self.unbind_calls.append((sequence, binding_id))


class DestroyedWidget(FakeWidget):
    def winfo_exists(self):
        return False


def _patch_config(
    mocker,
    *,
    enabled=True,
    threshold=12,
    require_foreground=True,
    presence_input_enabled=True,
):
    def config_side_effect(section, key, default=None):
        values = {
            ("user_activity_prompt", "enabled"): enabled,
            ("user_activity_prompt", "mouse_move_threshold_px"): threshold,
            ("user_activity_prompt", "require_foreground"): require_foreground,
            ("presence_detection", "input_triggers_presence"): presence_input_enabled,
        }
        return values.get((section, key), default)

    mocker.patch("ui.global_input_monitor.config.get", side_effect=config_side_effect)


def test_keyboard_press_triggers_activity_when_app_is_foreground(mocker):
    _patch_config(mocker, require_foreground=True)
    callback = mocker.MagicMock()
    monitor = GlobalInputMonitor(callback)
    mocker.patch.object(monitor, "_is_own_app_foreground", return_value=True)

    monitor._on_press(object())

    callback.assert_called_once_with("keyboard")


def test_keyboard_press_ignores_background_activity_when_foreground_required(mocker):
    _patch_config(mocker, require_foreground=True)
    callback = mocker.MagicMock()
    monitor = GlobalInputMonitor(callback)
    mocker.patch.object(monitor, "_is_own_app_foreground", return_value=False)

    monitor._on_press(object())

    callback.assert_not_called()


def test_keyboard_press_accepts_foreground_activity_when_foreground_not_required(mocker):
    _patch_config(mocker, require_foreground=False)
    callback = mocker.MagicMock()
    monitor = GlobalInputMonitor(callback)
    mocker.patch.object(monitor, "_is_own_app_foreground", return_value=True)

    monitor._on_press(object())

    callback.assert_called_once_with("keyboard")


def test_mouse_move_respects_threshold_in_foreground_scope(mocker):
    _patch_config(mocker, require_foreground=True)
    callback = mocker.MagicMock()
    monitor = GlobalInputMonitor(callback)
    mocker.patch.object(monitor, "_is_own_app_foreground", return_value=True)

    monitor._on_move(100, 100)
    monitor._on_move(110, 110)

    callback.assert_called_once_with("mouse")


def test_mouse_move_resets_anchor_when_event_goes_out_of_scope(mocker):
    _patch_config(mocker, require_foreground=True)
    callback = mocker.MagicMock()
    monitor = GlobalInputMonitor(callback)
    mocker.patch.object(
        monitor,
        "_is_own_app_foreground",
        side_effect=[True, False, True, True],
    )

    monitor._on_move(100, 100)
    monitor._on_move(120, 120)
    monitor._on_move(120, 120)
    monitor._on_move(133, 133)

    callback.assert_called_once_with("mouse")


def test_start_prefers_widget_bindings_when_foreground_required(mocker):
    _patch_config(mocker, require_foreground=True)
    callback = mocker.MagicMock()
    widget = FakeWidget()
    monitor = GlobalInputMonitor(callback, widget=widget)

    monitor.start()

    assert monitor._started is True
    assert [call[0] for call in widget.bind_calls] == ["<KeyPress>", "<Motion>"]


def test_widget_events_trigger_activity_without_global_listener(mocker):
    _patch_config(mocker, require_foreground=True)
    callback = mocker.MagicMock()
    widget = FakeWidget()
    monitor = GlobalInputMonitor(callback, widget=widget)

    monitor._on_widget_press(SimpleNamespace())
    monitor._on_widget_move(SimpleNamespace(x_root=100, y_root=100))
    monitor._on_widget_move(SimpleNamespace(x_root=112, y_root=112))

    assert callback.call_args_list[0].args == ("keyboard",)
    assert callback.call_args_list[1].args == ("mouse",)


def test_stop_unbinds_widget_handlers(mocker):
    _patch_config(mocker, require_foreground=True)
    widget = FakeWidget()
    monitor = GlobalInputMonitor(mocker.MagicMock(), widget=widget)
    monitor.start()

    monitor.stop()

    assert widget.unbind_calls == [
        ("<KeyPress>", "bind-1"),
        ("<Motion>", "bind-2"),
    ]


def test_stop_skips_unbind_when_widget_already_destroyed(mocker):
    _patch_config(mocker, require_foreground=True)
    warning = mocker.patch("ui.global_input_monitor.logger.warning")
    widget = DestroyedWidget()
    monitor = GlobalInputMonitor(mocker.MagicMock(), widget=widget)
    monitor._widget_key_binding = "bind-1"
    monitor._widget_motion_binding = "bind-2"

    monitor.stop()

    assert widget.unbind_calls == []
    warning.assert_not_called()


def test_input_presence_still_emits_activity_when_prompt_disabled(mocker):
    _patch_config(
        mocker,
        enabled=False,
        require_foreground=False,
        presence_input_enabled=True,
    )
    callback = mocker.MagicMock()
    monitor = GlobalInputMonitor(callback)

    monitor._on_press(object())

    callback.assert_called_once_with("keyboard")


def test_input_activity_fully_disabled_when_prompt_and_presence_disabled(mocker):
    _patch_config(
        mocker,
        enabled=False,
        require_foreground=False,
        presence_input_enabled=False,
    )
    callback = mocker.MagicMock()
    monitor = GlobalInputMonitor(callback)

    monitor._on_press(object())
    monitor._on_move(100, 100)
    monitor._on_move(120, 120)

    callback.assert_not_called()


def test_activity_pause_suppresses_events_and_resets_mouse_anchor(mocker):
    _patch_config(mocker, require_foreground=False)
    callback = mocker.MagicMock()
    monitor = GlobalInputMonitor(callback)

    monitor._on_move(100, 100)
    monitor.set_activity_paused(True)

    assert monitor._mouse_anchor_pos is None

    monitor._on_press(object())
    monitor._on_move(200, 200)
    monitor._on_move(220, 220)

    callback.assert_not_called()

    monitor.set_activity_paused(False)

    assert monitor._mouse_anchor_pos is None

    monitor._on_move(220, 220)
    monitor._on_move(240, 240)

    callback.assert_called_once_with("mouse")

