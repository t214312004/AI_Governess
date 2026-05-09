import ctypes
import math
import os
from typing import Callable, Optional

from config import config
from utils.logger import get_logger

logger = get_logger(__name__)


class GlobalInputMonitor:
    def __init__(self, on_activity: Callable[[str], None], widget=None):
        self.on_activity = on_activity
        self.widget = widget
        self._mouse_listener = None
        self._keyboard_listener = None
        self._widget_key_binding = None
        self._widget_motion_binding = None
        self._mouse_anchor_pos: Optional[tuple[int, int]] = None
        self._started = False
        self._activity_enabled = True
        self._mouse_threshold = 12.0
        self._require_foreground = True
        self.update_settings()

    def update_settings(self):
        prompt_enabled = bool(
            config.get("user_activity_prompt", "enabled", default=True)
        )
        presence_input_enabled = bool(
            config.get("presence_detection", "input_triggers_presence", default=True)
        )
        self._activity_enabled = prompt_enabled or presence_input_enabled
        self._mouse_threshold = float(
            config.get("user_activity_prompt", "mouse_move_threshold_px", default=12)
        )
        self._require_foreground = bool(
            config.get("user_activity_prompt", "require_foreground", default=True)
        )

    @staticmethod
    def _is_own_app_foreground() -> bool:
        if os.name != "nt":
            return False

        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return False

            pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return pid.value == os.getpid()
        except Exception:
            return False

    def _can_use_widget_bindings(self) -> bool:
        return self.widget is not None and hasattr(self.widget, "bind") and hasattr(
            self.widget, "unbind"
        )

    def _widget_is_alive(self) -> bool:
        if self.widget is None:
            return False
        if hasattr(self.widget, "winfo_exists"):
            try:
                return bool(self.widget.winfo_exists())
            except Exception:
                return False
        return True

    def _unbind_widget_sequence(self, sequence: str, binding_id):
        if not self._can_use_widget_bindings() or not self._widget_is_alive():
            return
        try:
            if binding_id:
                self.widget.unbind(sequence, binding_id)
            else:
                self.widget.unbind(sequence)
        except Exception as exc:
            logger.warning(f"Failed to unbind widget input listener: {exc}")

    def _start_widget_bindings(self) -> bool:
        if not self._can_use_widget_bindings():
            return False
        try:
            self._widget_key_binding = self.widget.bind(
                "<KeyPress>", self._on_widget_press, add="+"
            )
            self._widget_motion_binding = self.widget.bind(
                "<Motion>", self._on_widget_move, add="+"
            )
            logger.info("Input monitor started in foreground-only widget mode.")
            return True
        except Exception as exc:
            self._widget_key_binding = None
            self._widget_motion_binding = None
            logger.warning(f"Foreground input monitor unavailable: {exc}")
            return False

    def _reset_mouse_anchor(self):
        self._mouse_anchor_pos = None

    def _handle_mouse_activity(self, x, y):
        current_pos = (int(x), int(y))
        if self._mouse_anchor_pos is None:
            self._mouse_anchor_pos = current_pos
            return

        distance = math.dist(self._mouse_anchor_pos, current_pos)
        if distance >= self._mouse_threshold:
            self._mouse_anchor_pos = current_pos
            self.on_activity("mouse")

    def _global_event_in_scope(self) -> bool:
        is_foreground = self._is_own_app_foreground()
        return is_foreground if self._require_foreground else True

    def start(self):
        if self._started:
            return

        if self._require_foreground and self._start_widget_bindings():
            self._started = True
            return

        try:
            from pynput import keyboard, mouse
        except Exception as exc:
            logger.warning(f"Global input monitor unavailable: {exc}")
            return

        self._mouse_listener = mouse.Listener(on_move=self._on_move)
        self._keyboard_listener = keyboard.Listener(on_press=self._on_press)
        self._mouse_listener.start()
        self._keyboard_listener.start()
        self._started = True
        logger.info("Global input monitor started.")

    def stop(self):
        self._unbind_widget_sequence("<KeyPress>", self._widget_key_binding)
        self._unbind_widget_sequence("<Motion>", self._widget_motion_binding)
        self._widget_key_binding = None
        self._widget_motion_binding = None

        for listener in (self._mouse_listener, self._keyboard_listener):
            if listener is None:
                continue
            try:
                listener.stop()
            except Exception as exc:
                logger.warning(f"Failed to stop input listener: {exc}")
        self._mouse_listener = None
        self._keyboard_listener = None
        self._mouse_anchor_pos = None
        self._started = False
        logger.info("Global input monitor stopped.")

    def _on_widget_press(self, _event):
        if not self._activity_enabled:
            return
        self.on_activity("keyboard")

    def _on_widget_move(self, event):
        if not self._activity_enabled:
            return
        x = getattr(event, "x_root", getattr(event, "x", 0))
        y = getattr(event, "y_root", getattr(event, "y", 0))
        self._handle_mouse_activity(x, y)

    def _on_press(self, _key):
        if not self._activity_enabled:
            return
        if not self._global_event_in_scope():
            return
        self.on_activity("keyboard")

    def _on_move(self, x, y):
        if not self._activity_enabled:
            return
        if not self._global_event_in_scope():
            self._reset_mouse_anchor()
            return
        self._handle_mouse_activity(x, y)
