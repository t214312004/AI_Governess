"""Main UI window for AI Governess."""
import ctypes
import os
import threading
import tkinter as tk
import customtkinter as ctk
from core.state_machine import State
from config import config
from tts.rate_limits import (
    EDGE_TTS_RATE_MAX_PERCENT,
    EDGE_TTS_RATE_MIN_PERCENT,
    EDGE_TTS_RATE_STEPS,
    normalize_edge_tts_rate,
)
from ui.animation_controller import AnimationController
from ui.global_input_monitor import GlobalInputMonitor
from utils.logger import get_logger

logger = get_logger(__name__)

ES_CONTINUOUS = 0x80000000
ES_DISPLAY_REQUIRED = 0x00000002
ES_SYSTEM_REQUIRED = 0x00000001
WH_KEYBOARD_LL = 13
HC_ACTION = 0
PM_NOREMOVE = 0x0000
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
WM_SYSCOMMAND = 0x0112
SC_SCREENSAVE = 0xF140
SC_MONITORPOWER = 0xF170
GWL_WNDPROC = -4
HOT_LISTEN_TIMEOUT_MIN_SECONDS = 1
HOT_LISTEN_TIMEOUT_MAX_SECONDS = 60
HOT_LISTEN_TIMEOUT_DEFAULT_SECONDS = 10
LONG_PTR = ctypes.c_ssize_t
VK_TAB = 0x09
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_CONTROL = 0x11
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_F4 = 0x73
VK_LWIN = 0x5B
VK_RWIN = 0x5C
LLKHF_ALTDOWN = 0x20
WNDPROC = (
    ctypes.WINFUNCTYPE(
        LONG_PTR,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )
    if hasattr(ctypes, "WINFUNCTYPE")
    else None
)
HOOKPROC = (
    ctypes.WINFUNCTYPE(
        LONG_PTR,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )
    if hasattr(ctypes, "WINFUNCTYPE")
    else None
)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.c_uint32),
        ("scanCode", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
        ("lPrivate", ctypes.c_uint),
    ]

C_BG_BOTTOM = "#E8EEF8"
C_STAGE = "#FFF9F1"
C_STAGE_BORDER = "#E5D9C9"
C_STAGE_PANEL = "#FFFCF8"
C_PANEL = "#FFFDFC"
C_PANEL_BORDER = "#DED6CB"
C_PANEL_SOFT = "#F7F0E7"
C_PANEL_MUTED = "#EFE7DD"
C_ACCENT = "#294C7A"
C_ACCENT_HOVER = "#1E3A5D"
C_ACCENT_SOFT = "#DCE7F7"
C_GOLD = "#C58A3A"
C_GOLD_SOFT = "#F4E2C7"
C_SUCCESS = "#2A8877"
C_SUCCESS_SOFT = "#D7EFEA"
C_DANGER = "#C64E43"
C_DANGER_HOVER = "#A83C32"
C_USER_BUBBLE = "#E4ECFA"
C_AI_BUBBLE = "#EFF6EA"
C_TEXT_PRI = "#1D2733"
C_TEXT_SEC = "#66717D"
C_TEXT_MUTED = "#8D97A2"
C_INPUT = "#F6F1EA"
C_WHITE = "#FFFFFF"
C_STAGE_GLOW = "#FFF3DF"
LEFT_PANEL_WEIGHT = 74
RIGHT_PANEL_WEIGHT = 26
MAX_STAGE_IMAGE_SIDE = 760
INPUT_SHELL_HORIZONTAL_PADDING = 12
INPUT_ROW_LEFT_PADDING = 12
INPUT_ROW_GAP = 8
INPUT_ROW_RIGHT_PADDING = 12
SEND_BUTTON_WIDTH = 88
TEXT_INPUT_MIN_WIDTH = 220
RIGHT_PANEL_SAFETY_PADDING = 48
RIGHT_PANEL_HINT_MIN_WRAP = 160
RIGHT_PANEL_BODY_MIN_WRAP = 220
CHAT_BUBBLE_MIN_WRAP = 180
CHAT_BUBBLE_MAX_WRAP = 430
CHAT_BUBBLE_WRAP_PADDING = 72
MAX_VISIBLE_CHAT_TURNS = 3
MAX_RENDERED_MESSAGES = 100
RIGHT_PANEL_TOPBAR_HEIGHT = 88
SETTINGS_DRAWER_OFFSET_Y = RIGHT_PANEL_TOPBAR_HEIGHT + 12
SMALL_TEXT_SAFE_HEIGHT = 30
TEXT_SAFE_PADX = 2
INPUT_MODE_HINT_MIN_WIDTH = 120

FONT_BRAND = ("Microsoft JhengHei", 32, "bold")
FONT_TITLE = ("Microsoft JhengHei", 28, "bold")
FONT_SUBTITLE = ("Microsoft JhengHei", 16)
FONT_SECTION = ("Microsoft JhengHei", 18, "bold")
FONT_BODY = ("Microsoft JhengHei", 16)
FONT_BODY_BOLD = ("Microsoft JhengHei", 16, "bold")
FONT_SMALL = ("Microsoft JhengHei", 13)
FONT_BUTTON = ("Microsoft JhengHei", 18, "bold")
FONT_BUTTON_SMALL = ("Microsoft JhengHei", 15, "bold")

STATE_TEXT = {
    State.IDLE_LISTEN: "待命中",
    State.COLLECTING: "正在聆聽",
    State.SENDING: "思考中",
    State.SPEAKING: "回覆中",
    State.HOT_LISTEN: "繼續聽你說",
}

STATE_HINT = {
    State.IDLE_LISTEN: "請說「愛管家」開始對話",
    State.COLLECTING: "請直接說出想做的事",
    State.SENDING: "我正在整理回覆",
    State.SPEAKING: "你可以隨時打斷我",
    State.HOT_LISTEN: "接下來幾秒內可直接接話",
}

STATE_COLOR = {
    State.IDLE_LISTEN: C_GOLD,
    State.COLLECTING: C_SUCCESS,
    State.SENDING: "#E08A2E",
    State.SPEAKING: C_ACCENT,
    State.HOT_LISTEN: "#3B7F6B",
}

STATE_SURFACE = {
    State.IDLE_LISTEN: C_GOLD_SOFT,
    State.COLLECTING: C_SUCCESS_SOFT,
    State.SENDING: "#F9E6C9",
    State.SPEAKING: C_ACCENT_SOFT,
    State.HOT_LISTEN: "#DCEFE8",
}


class ChatBubble(ctk.CTkFrame):
    def __init__(self, master, text: str, role: str, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        is_user = role == "user"
        bg = C_USER_BUBBLE if is_user else C_AI_BUBBLE
        border = C_ACCENT_SOFT if is_user else "#D6E7D0"
        self._wraplength = CHAT_BUBBLE_MAX_WRAP

        self.bubble = ctk.CTkFrame(
            self,
            fg_color=bg,
            corner_radius=18,
            border_width=1,
            border_color=border,
        )
        self.bubble.pack(side="right" if is_user else "left", padx=10, pady=5, fill="none")

        self.label = tk.Label(
            self.bubble,
            text=text,
            wraplength=self._wraplength,
            justify="right" if is_user else "left",
            font=FONT_BODY,
            anchor="e" if is_user else "w",
            fg=C_TEXT_PRI,
            bg=bg,
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        self.label.pack(padx=18, pady=14)

    def update_text(self, text: str):
        self.label.configure(text=text)

    def set_wraplength(self, wraplength: int):
        self._wraplength = max(0, int(wraplength))
        self.label.configure(wraplength=self._wraplength)


class VoiceAssistantUI(ctk.CTk):
    @staticmethod
    def _format_user_message_for_display(text: str, speaker_name: str | None = None) -> str:
        if not speaker_name:
            return text
        return f"{speaker_name}: {text}"

    @staticmethod
    def _compute_proportional_panel_widths(
        total_width: int,
        left_weight: int = LEFT_PANEL_WEIGHT,
        right_weight: int = RIGHT_PANEL_WEIGHT,
    ) -> tuple[int, int]:
        total_width = max(0, int(total_width))
        left_weight = max(0, int(left_weight))
        right_weight = max(0, int(right_weight))
        total_weight = left_weight + right_weight

        if total_width <= 0 or total_weight <= 0:
            return 0, 0

        left_width = round(total_width * left_weight / total_weight)
        left_width = min(total_width, max(0, left_width))
        right_width = max(0, total_width - left_width)
        return left_width, right_width

    @staticmethod
    def _compute_right_panel_content_min_width(
        shell_horizontal_padding: int = INPUT_SHELL_HORIZONTAL_PADDING,
        input_left_padding: int = INPUT_ROW_LEFT_PADDING,
        input_gap: int = INPUT_ROW_GAP,
        input_right_padding: int = INPUT_ROW_RIGHT_PADDING,
        send_button_width: int = SEND_BUTTON_WIDTH,
        text_input_min_width: int = TEXT_INPUT_MIN_WIDTH,
        safety_padding: int = RIGHT_PANEL_SAFETY_PADDING,
    ) -> int:
        return (
            int(shell_horizontal_padding) * 2
            + int(input_left_padding)
            + int(input_gap)
            + int(input_right_padding)
            + int(send_button_width)
            + int(text_input_min_width)
            + int(safety_padding)
        )

    @staticmethod
    def _compute_available_wraplength(
        container_width: int,
        occupied_widths: tuple[int, ...] = (),
        padding: int = 0,
        min_wrap: int = RIGHT_PANEL_HINT_MIN_WRAP,
    ) -> int:
        container_width = max(0, int(container_width))
        occupied_total = sum(max(0, int(width)) for width in occupied_widths)
        available_width = container_width - occupied_total - max(0, int(padding))
        return max(int(min_wrap), available_width)

    @staticmethod
    def _compute_inner_width(container_width: int, horizontal_padding: int = 0) -> int:
        container_width = max(0, int(container_width))
        horizontal_padding = max(0, int(horizontal_padding))
        return max(0, container_width - horizontal_padding)

    @staticmethod
    def _compute_chat_bubble_wraplength(
        chat_content_width: int,
        horizontal_padding: int = CHAT_BUBBLE_WRAP_PADDING,
        min_wrap: int = CHAT_BUBBLE_MIN_WRAP,
        max_wrap: int = CHAT_BUBBLE_MAX_WRAP,
    ) -> int:
        min_wrap = max(0, int(min_wrap))
        max_wrap = max(min_wrap, int(max_wrap))
        available_width = VoiceAssistantUI._compute_inner_width(
            chat_content_width,
            horizontal_padding=horizontal_padding,
        )
        return min(max_wrap, max(min_wrap, available_width))

    @staticmethod
    def _get_widget_measured_width(widget) -> int:
        if widget is None:
            return 0
        measured_widths: list[int] = []
        for getter_name in ("winfo_width", "winfo_reqwidth"):
            getter = getattr(widget, getter_name, None)
            if callable(getter):
                try:
                    width_value = getter()
                except Exception:
                    continue
                if isinstance(width_value, (int, float)):
                    measured_widths.append(max(0, int(round(width_value))))
        return max(measured_widths, default=0)

    @staticmethod
    def _to_widget_logical_size(widget, size: int) -> int:
        size = max(0, int(round(size)))
        if widget is None:
            return size
        try:
            logical_size = widget._reverse_widget_scaling(size)
        except Exception:
            return size
        if isinstance(logical_size, (int, float)):
            return max(0, int(round(logical_size)))
        return size

    @staticmethod
    def _get_widget_logical_width(widget) -> int:
        if widget is None:
            return 0

        current_width = getattr(widget, "_current_width", None)
        if isinstance(current_width, (int, float)):
            return max(0, int(round(current_width)))

        return VoiceAssistantUI._to_widget_logical_size(
            widget,
            VoiceAssistantUI._get_widget_measured_width(widget),
        )

    def _get_current_chat_bubble_wraplength(self) -> int:
        if "right_panel" not in self.__dict__:
            return CHAT_BUBBLE_MAX_WRAP

        panel_width = self._get_widget_logical_width(self.right_panel)
        if panel_width <= 0:
            return CHAT_BUBBLE_MAX_WRAP

        chat_content_width = self._compute_inner_width(panel_width, horizontal_padding=28)
        return self._compute_chat_bubble_wraplength(chat_content_width)

    def _update_chat_bubble_wraplengths(self, chat_content_width: int):
        if "chat_scroll" not in self.__dict__:
            return

        bubble_wrap = self._compute_chat_bubble_wraplength(chat_content_width)
        for child in self.chat_scroll.winfo_children():
            set_wraplength = getattr(child, "set_wraplength", None)
            if callable(set_wraplength):
                set_wraplength(bubble_wrap)

    def _tag_message_widget(self, widget, role: str, *, counts_toward_recent_turns: bool):
        if widget is None:
            return
        widget._message_role = role
        widget._counts_toward_recent_turns = bool(counts_toward_recent_turns)

    def _destroy_message_widget(self, widget) -> bool:
        if widget is None or widget is getattr(self, "empty_state", None):
            return False

        if widget is getattr(self, "last_ai_bubble", None):
            self.last_ai_bubble = None

        destroy = getattr(widget, "destroy", None)
        if callable(destroy):
            destroy()

        if self._message_count > 0:
            self._message_count -= 1
        return True

    def _trim_total_rendered_messages(self):
        if "chat_scroll" not in self.__dict__:
            return

        while self._message_count > MAX_RENDERED_MESSAGES:
            removed = False
            for child in list(self.chat_scroll.winfo_children()):
                if self._destroy_message_widget(child):
                    removed = True
                    break
            if not removed:
                break

    def _trim_conversation_turns(self):
        if "chat_scroll" not in self.__dict__:
            return

        rounds: list[list[object]] = []
        current_round: list[object] = []

        for child in list(self.chat_scroll.winfo_children()):
            if not getattr(child, "_counts_toward_recent_turns", False):
                continue

            role = getattr(child, "_message_role", "")
            if role == "user":
                if current_round:
                    rounds.append(current_round)
                current_round = [child]
                continue

            if current_round:
                current_round.append(child)
            else:
                current_round = [child]

        if current_round:
            rounds.append(current_round)

        overflow_rounds = len(rounds) - MAX_VISIBLE_CHAT_TURNS
        if overflow_rounds <= 0:
            return

        for old_round in rounds[:overflow_rounds]:
            for child in old_round:
                self._destroy_message_widget(child)

    def _cancel_pending_chat_scroll(self):
        pending_after_id = self.__dict__.get("_chat_scroll_after_id")
        try:
            after_cancel = object.__getattribute__(self, "after_cancel")
        except AttributeError:
            after_cancel = None
        if pending_after_id is not None and callable(after_cancel):
            try:
                after_cancel(pending_after_id)
            except Exception:
                pass

        self._chat_scroll_after_id = None

    def _schedule_chat_scroll_to_latest(self):
        if "chat_scroll" not in self.__dict__:
            return

        self._cancel_pending_chat_scroll()

        self._chat_scroll_after_id = self.after(0, self._scroll_chat_to_latest)

    def _scroll_chat_to_latest(self):
        self._chat_scroll_after_id = None

        if "chat_scroll" not in self.__dict__:
            return

        canvas = getattr(self.chat_scroll, "_parent_canvas", None)
        if canvas is None:
            return

        try:
            update_idletasks = object.__getattribute__(self, "update_idletasks")
        except AttributeError:
            update_idletasks = None
        if callable(update_idletasks):
            try:
                update_idletasks()
            except Exception:
                pass

        bbox = None
        bbox_getter = getattr(canvas, "bbox", None)
        if callable(bbox_getter):
            try:
                bbox = bbox_getter("all")
            except Exception:
                bbox = None

        canvas_configure = getattr(canvas, "configure", None)
        if bbox is not None and callable(canvas_configure):
            try:
                canvas_configure(scrollregion=bbox)
            except Exception:
                pass

        yview_moveto = getattr(canvas, "yview_moveto", None)
        if callable(yview_moveto):
            try:
                yview_moveto(1.0)
            except Exception:
                pass

    def clear_chat_history_ui(self):
        self.after(0, self._clear_chat_history_logic)

    def _clear_chat_history_logic(self):
        if "chat_scroll" not in self.__dict__:
            return

        self._cancel_pending_chat_scroll()

        for child in list(self.chat_scroll.winfo_children()):
            self._destroy_message_widget(child)

        self.last_ai_bubble = None
        self._message_count = 0

        if hasattr(self, "empty_state"):
            self.empty_state.pack(fill="x", padx=12, pady=(8, 14))

        self._schedule_chat_scroll_to_latest()

    def _get_logical_screen_size(self) -> tuple[int, int]:
        screen_width = max(0, int(self.winfo_screenwidth()))
        screen_height = max(0, int(self.winfo_screenheight()))
        # CTk.geometry() expects Tk's logical desktop size and applies window scaling internally.
        # Reversing the scaling here would shrink fullscreen on scaled displays.
        return screen_width, screen_height

    @staticmethod
    def _compute_square_image_side(
        available_width: int,
        available_height: int,
        horizontal_padding: int = 36,
        vertical_padding: int = 36,
        min_side: int = 240,
        max_side: int = MAX_STAGE_IMAGE_SIDE,
    ) -> int:
        usable_width = max(0, int(available_width) - int(horizontal_padding))
        usable_height = max(0, int(available_height) - int(vertical_padding))
        if usable_width <= 0 or usable_height <= 0:
            return 0

        preferred_side = min(usable_width, usable_height, int(max_side))
        if preferred_side < int(min_side):
            return max(0, preferred_side)
        return preferred_side

    def __init__(self, assistant):
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        super().__init__()

        self.assistant = assistant
        self.assistant.set_callbacks(
            self.update_state_ui,
            self.add_message_ui,
            self.clear_chat_history_ui,
        )

        self.last_ai_bubble = None
        self._message_count = 0
        self._current_state: State = State.IDLE_LISTEN
        self._settings_visible = False
        self._voice_mode = True
        self._pulse_after_id = None
        self._pulse_step = 0
        self._chat_scroll_after_id = None
        self._startup_fullscreen_pending = True
        self._screen_guard_hwnd = None
        self._screen_guard_prev_wndproc = None
        self._screen_guard_proc = None
        self._keyboard_hook_handle = None
        self._keyboard_hook_proc = None
        self._keyboard_guard_thread = None
        self._keyboard_guard_thread_id = None
        self.input_monitor = GlobalInputMonitor(self.assistant.on_user_activity, widget=self)

        self.title("AI 愛管家")
        self._windowed_geometry = "1920x1160+0+0"
        self.geometry(self._windowed_geometry)
        self.configure(fg_color=C_BG_BOTTOM)
        self.resizable(True, True)
        self.bind("<Escape>", self._exit_fullscreen)
        self.bind("<F11>", self._toggle_fullscreen)
        self.bind("<Configure>", self._handle_window_resize)

        self._setup_ui()
        self._apply_panel_split()
        self._update_context_chips()
        self.update_state_ui(State.IDLE_LISTEN)
        self._refresh_interaction_controls()
        self.after_idle(self._enter_startup_fullscreen)
        self.after(150, self._update_stage_image_layout)

    def _setup_ui(self):
        self.main_frame = ctk.CTkFrame(self, fg_color=C_BG_BOTTOM, corner_radius=0)
        self.main_frame.pack(fill="both", expand=True)
        self.main_frame.columnconfigure(0, weight=LEFT_PANEL_WEIGHT)
        self.main_frame.columnconfigure(1, weight=RIGHT_PANEL_WEIGHT)
        self.main_frame.rowconfigure(0, weight=1)

        self._build_left_stage()
        self._build_right_panel()

    def _build_left_stage(self):
        left = ctk.CTkFrame(self.main_frame, fg_color=C_BG_BOTTOM, corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_propagate(False)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.left_panel = left

        self.stage_shell = ctk.CTkFrame(left, fg_color=C_STAGE, corner_radius=0)
        self.stage_shell.grid(row=0, column=0, sticky="nsew", padx=(32, 18), pady=(28, 24))
        self.stage_shell.rowconfigure(1, weight=1)
        self.stage_shell.columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self.stage_shell, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=(4, 8))
        header.columnconfigure(0, weight=1)

        text_group = ctk.CTkFrame(header, fg_color="transparent")
        text_group.grid(row=0, column=0, sticky="w")

        self.brand_title = ctk.CTkLabel(text_group, text="愛管家", font=FONT_BRAND, text_color=C_ACCENT, anchor="w")
        self.brand_title.pack(anchor="w")

        self.brand_subtitle = ctk.CTkLabel(
            text_group,
            text="陪伴型家庭 AI 語音管家",
            font=FONT_SUBTITLE,
            text_color=C_TEXT_SEC,
            anchor="w",
        )
        self.brand_subtitle.pack(anchor="w", pady=(4, 0))

        self.mode_badge = ctk.CTkLabel(
            header,
            text="語音待命",
            font=FONT_SMALL,
            text_color=C_ACCENT,
            fg_color=C_ACCENT_SOFT,
            corner_radius=18,
            padx=16,
            pady=8,
        )
        self.mode_badge.grid(row=0, column=1, sticky="e", padx=(16, 0))

        self.stage_frame = ctk.CTkFrame(self.stage_shell, fg_color="transparent")
        self.stage_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.stage_frame.rowconfigure(0, weight=1)
        self.stage_frame.columnconfigure(0, weight=1)

        self.stage_card = ctk.CTkFrame(
            self.stage_frame,
            fg_color=C_STAGE_PANEL,
            corner_radius=32,
            border_width=1,
            border_color=C_STAGE_BORDER,
        )
        self.stage_card.grid(row=0, column=0, sticky="nsew")
        self.stage_card.grid_propagate(False)
        self.stage_card.rowconfigure(0, weight=1)
        self.stage_card.columnconfigure(0, weight=1)
        self.stage_card.bind("<Configure>", self._on_stage_card_resize)

        self.stage_glow_bar = ctk.CTkFrame(
            self.stage_card,
            fg_color=C_STAGE_GLOW,
            corner_radius=999,
            height=12,
        )
        self.stage_glow_bar.place(relx=0.5, y=10, relwidth=0.72, anchor="n")

        self.image_frame = ctk.CTkFrame(
            self.stage_card,
            fg_color="transparent",
            width=640,
            height=640,
        )
        self.image_frame.grid(row=0, column=0, sticky="")
        self.image_frame.grid_propagate(False)

        self.bg_img_label = ctk.CTkLabel(self.image_frame, text="", fg_color="transparent")
        self.bg_img_label.place(relx=0.5, rely=0.5, anchor="center")

        self.img_label = ctk.CTkLabel(self.image_frame, text="", fg_color="transparent")
        self.img_label.place(relx=0.5, rely=0.5, anchor="center")

        interval = config.get("ui", "animation_interval_ms", default=500)
        foreground_y_offset_px = config.get("ui", "animation_foreground_y_offset_px", default=0)
        self.animator = AnimationController(
            self.img_label,
            interval_ms=interval,
            background_label_widget=self.bg_img_label,
            foreground_y_offset_px=foreground_y_offset_px,
        )

        self.status_card = ctk.CTkFrame(
            self.stage_shell,
            fg_color=C_PANEL,
            corner_radius=22,
            border_width=1,
            border_color=C_PANEL_BORDER,
        )
        self.status_card.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 10))
        self.status_card.columnconfigure(1, weight=1)

        self.state_indicator_slot = ctk.CTkFrame(
            self.status_card,
            width=24,
            height=24,
            corner_radius=999,
            fg_color="transparent",
        )
        self.state_indicator_slot.grid(row=0, column=0, sticky="w", padx=(18, 0), pady=16)
        self.state_indicator_slot.grid_propagate(False)

        self.state_indicator = ctk.CTkFrame(
            self.state_indicator_slot,
            width=14,
            height=14,
            corner_radius=999,
            fg_color=STATE_COLOR[State.IDLE_LISTEN],
        )
        self.state_indicator.place(relx=0.5, rely=0.5, anchor="center")

        self.state_label = ctk.CTkLabel(
            self.status_card,
            text=STATE_TEXT[State.IDLE_LISTEN],
            font=("Microsoft JhengHei", 22, "bold"),
            text_color=C_TEXT_PRI,
            anchor="w",
        )
        self.state_label.grid(row=0, column=1, sticky="ew", padx=(12, 20), pady=(10, 0))

        self.state_hint_label = ctk.CTkLabel(
            self.status_card,
            text=STATE_HINT[State.IDLE_LISTEN],
            font=FONT_SMALL,
            text_color=C_TEXT_SEC,
            anchor="w",
        )
        self.state_hint_label.grid(row=1, column=0, columnspan=2, sticky="ew", padx=18, pady=(0, 14))

        action_bar = ctk.CTkFrame(self.stage_shell, fg_color="transparent")
        action_bar.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 0))
        action_bar.columnconfigure(0, weight=1)
        action_bar.columnconfigure(1, weight=1)

        self.primary_action_button = ctk.CTkButton(
            action_bar,
            text="開始說話",
            fg_color=C_ACCENT,
            hover_color=C_ACCENT_HOVER,
            text_color="white",
            font=FONT_BUTTON,
            corner_radius=18,
            height=56,
            command=self._on_primary_action,
        )
        self.primary_action_button.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        self.stop_button = ctk.CTkButton(
            action_bar,
            text="停止 / 打斷",
            fg_color=C_DANGER,
            hover_color=C_DANGER_HOVER,
            text_color="white",
            font=FONT_BUTTON,
            corner_radius=18,
            height=56,
            command=self.on_stop_click,
        )
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=(10, 0))

    def _build_right_panel(self):
        self.right_panel = ctk.CTkFrame(
            self.main_frame,
            fg_color=C_PANEL,
            corner_radius=0,
            border_width=1,
            border_color=C_PANEL_BORDER,
        )
        self.right_panel.grid(row=0, column=1, sticky="nsew")
        self.right_panel.grid_propagate(False)
        self.right_panel.rowconfigure(1, weight=1)
        self.right_panel.columnconfigure(0, weight=1)
        self.right_panel.bind("<Configure>", self._on_right_panel_resize)

        topbar = ctk.CTkFrame(
            self.right_panel,
            fg_color=C_PANEL_SOFT,
            height=RIGHT_PANEL_TOPBAR_HEIGHT,
            corner_radius=0,
            border_width=0,
        )
        topbar.grid(row=0, column=0, sticky="ew")
        topbar.grid_propagate(False)
        topbar.grid_columnconfigure(0, weight=1)

        brand_box = ctk.CTkFrame(topbar, fg_color="transparent")
        brand_box.grid(row=0, column=0, sticky="ew", padx=22, pady=14)
        self.brand_title_label = ctk.CTkLabel(
            brand_box,
            text="對話工作台",
            font=FONT_SECTION,
            text_color=C_TEXT_PRI,
            anchor="w",
            height=26,
        )
        self.brand_title_label.pack(anchor="w", fill="x")
        self.brand_subtitle_label = tk.Label(
            brand_box,
            text="用語音或文字都能自然接續互動",
            font=FONT_SMALL,
            fg=C_TEXT_MUTED,
            bg=C_PANEL_SOFT,
            bd=0,
            padx=TEXT_SAFE_PADX,
            pady=0,
            anchor="w",
            justify="left",
            relief="flat",
            highlightthickness=0,
        )
        self.brand_subtitle_label.pack(anchor="w", fill="x", pady=(2, 0))

        self.top_actions = ctk.CTkFrame(topbar, fg_color="transparent")
        self.top_actions.grid(row=0, column=1, sticky="e", padx=18, pady=12)

        self.mode_btn = ctk.CTkButton(
            self.top_actions,
            text="語音模式",
            fg_color=C_ACCENT,
            hover_color=C_ACCENT_HOVER,
            text_color="white",
            font=FONT_BUTTON_SMALL,
            corner_radius=18,
            width=112,
            height=42,
            command=self._on_mode_toggle,
        )
        self.mode_btn.pack(side="left", padx=(0, 10))

        self.settings_button = ctk.CTkButton(
            self.top_actions,
            text="設定",
            fg_color=C_PANEL_MUTED,
            hover_color="#E6DDD2",
            text_color=C_TEXT_PRI,
            font=FONT_BUTTON_SMALL,
            corner_radius=18,
            width=84,
            height=42,
            command=self._toggle_settings,
        )
        self.settings_button.pack(side="left")

        self.chat_area = ctk.CTkFrame(self.right_panel, fg_color=C_PANEL, corner_radius=0)
        self.chat_area.grid(row=1, column=0, sticky="nsew", padx=14, pady=(14, 8))
        self.chat_area.rowconfigure(2, weight=1)
        self.chat_area.columnconfigure(0, weight=1)

        self.chat_header = ctk.CTkFrame(
            self.chat_area, fg_color=C_PANEL_SOFT, corner_radius=20, border_width=1, border_color=C_PANEL_BORDER
        )
        self.chat_header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.chat_header.columnconfigure(1, weight=1)

        self.chat_header_badge = ctk.CTkLabel(
            self.chat_header,
            text="最近互動",
            font=FONT_SMALL,
            text_color=C_ACCENT,
            fg_color=C_ACCENT_SOFT,
            corner_radius=16,
            padx=12,
            pady=6,
        )
        self.chat_header_badge.grid(row=0, column=0, sticky="w", padx=16, pady=14)

        self.chat_header_hint = ctk.CTkLabel(
            self.chat_header,
            text="我會保留最新對話脈絡，方便你直接接著聊",
            font=FONT_SMALL,
            text_color=C_TEXT_SEC,
            anchor="w",
            justify="left",
        )
        self.chat_header_hint.grid(row=0, column=1, sticky="ew", padx=(8, 16), pady=14)

        self.chat_summary_card = ctk.CTkFrame(
            self.chat_area,
            fg_color=C_WHITE,
            corner_radius=22,
            border_width=1,
            border_color=C_PANEL_BORDER,
        )
        self.chat_summary_card.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        self.chat_summary_card.columnconfigure(1, weight=1)

        self.chat_summary_badge = ctk.CTkLabel(
            self.chat_summary_card,
            text="今日互動風格",
            font=FONT_SMALL,
            text_color=C_GOLD,
            fg_color=C_GOLD_SOFT,
            corner_radius=16,
            padx=12,
            pady=6,
        )
        self.chat_summary_badge.grid(row=0, column=0, sticky="nw", padx=16, pady=16)

        self.chat_summary_text = ctk.CTkFrame(self.chat_summary_card, fg_color="transparent")
        self.chat_summary_text.grid(row=0, column=1, sticky="ew", padx=(4, 16), pady=14)

        self.chat_summary_title = ctk.CTkLabel(
            self.chat_summary_text,
            text="自然、即時、可打斷",
            font=FONT_BODY_BOLD,
            text_color=C_TEXT_PRI,
            anchor="w",
            justify="left",
        )
        self.chat_summary_title.pack(anchor="w")

        self.chat_summary_hint = ctk.CTkLabel(
            self.chat_summary_text,
            text="你可以把它當成家中的語音管家，想到就說，不需要記操作流程。",
            font=FONT_SMALL,
            text_color=C_TEXT_SEC,
            anchor="w",
            wraplength=420,
            justify="left",
        )
        self.chat_summary_hint.pack(anchor="w", pady=(4, 0))

        self.chat_scroll = ctk.CTkScrollableFrame(
            self.chat_area,
            fg_color=C_PANEL,
            corner_radius=24,
            scrollbar_button_color="#D4CCBF",
            scrollbar_button_hover_color=C_ACCENT,
        )
        self.chat_scroll.grid(row=2, column=0, sticky="nsew")

        self.empty_state = ctk.CTkFrame(
            self.chat_scroll,
            fg_color=C_PANEL_SOFT,
            corner_radius=24,
            border_width=1,
            border_color=C_PANEL_BORDER,
        )
        self.empty_state.pack(fill="x", padx=12, pady=(8, 14))

        self.empty_state_title = ctk.CTkLabel(
            self.empty_state,
            text="從自然一句話開始",
            font=FONT_SECTION,
            text_color=C_TEXT_PRI,
            anchor="w",
            justify="left",
        )
        self.empty_state_title.pack(anchor="w", padx=18, pady=(18, 6))

        self.empty_state_body = ctk.CTkLabel(
            self.empty_state,
            text="你可以直接說「愛管家，幫我...」，或切成文字模式輸入需求。",
            font=FONT_BODY,
            text_color=C_TEXT_SEC,
            wraplength=420,
            justify="left",
            anchor="w",
        )
        self.empty_state_body.pack(anchor="w", padx=18)

        self.empty_state_hint = ctk.CTkLabel(
            self.empty_state,
            text="常見起手式：提醒我明天早上七點、幫孩子講睡前故事、現在幾點了",
            font=FONT_SMALL,
            text_color=C_TEXT_MUTED,
            wraplength=420,
            justify="left",
            anchor="w",
        )
        self.empty_state_hint.pack(anchor="w", padx=18, pady=(8, 18))

        self._build_text_input(self.right_panel)
        self._build_settings_drawer(self.right_panel)

    def _build_settings_drawer(self, parent):
        self.settings_drawer = ctk.CTkFrame(
            parent,
            fg_color=C_STAGE_PANEL,
            corner_radius=28,
            border_width=1,
            border_color=C_PANEL_BORDER,
            width=392,
        )
        self.settings_drawer.grid_rowconfigure(1, weight=1)
        self.settings_drawer.grid_columnconfigure(0, weight=1)

        drawer_header = ctk.CTkFrame(self.settings_drawer, fg_color="transparent")
        drawer_header.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 10))
        drawer_header.grid_columnconfigure(0, weight=1)

        title_wrap = ctk.CTkFrame(drawer_header, fg_color="transparent")
        title_wrap.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(title_wrap, text="設定", font=FONT_SECTION, text_color=C_TEXT_PRI).pack(anchor="w")
        ctk.CTkLabel(
            title_wrap,
            text="進階調校預設收起，不干擾日常使用",
            font=FONT_SMALL,
            text_color=C_TEXT_SEC,
        ).pack(anchor="w", pady=(2, 0))

        self.drawer_close_button = ctk.CTkButton(
            drawer_header,
            text="關閉",
            fg_color=C_PANEL_MUTED,
            hover_color="#E6DDD2",
            text_color=C_TEXT_PRI,
            font=FONT_SMALL,
            corner_radius=16,
            width=62,
            height=34,
            command=self._toggle_settings,
        )
        self.drawer_close_button.grid(row=0, column=1, sticky="e")

        self.settings_body_scroll = ctk.CTkScrollableFrame(
            self.settings_drawer,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color="#D4CCBF",
            scrollbar_button_hover_color=C_ACCENT,
        )
        self.settings_body_scroll.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self.settings_body_scroll.grid_columnconfigure(0, weight=1)

        self._build_settings_content(self.settings_body_scroll)
        self._sync_settings_drawer_visibility()

    @staticmethod
    def _current_stt_backend_option():
        backend = config.get("whisper", "backend", default="local") or "local"
        if str(backend).strip().lower() == "groq":
            return "groq"
        return config.get("whisper", "device") or "cuda"

    def _build_settings_content(self, parent):
        self.backend_var = ctk.StringVar(value=config.get("llm", "active_backend") or "antigravity_cli")
        self.device_var = ctk.StringVar(value=self._current_stt_backend_option())

        hot_enabled = config.get("hot_listen", "enabled")
        if hot_enabled is None:
            hot_enabled = True
        self.hot_listen_var = ctk.BooleanVar(value=bool(hot_enabled))

        heartbeat_enabled = config.get("heartbeat", "enabled")
        if heartbeat_enabled is None:
            heartbeat_enabled = True
        self.heartbeat_var = ctk.BooleanVar(value=bool(heartbeat_enabled))

        hot_timeout = self._coerce_hot_timeout_seconds(
            config.get("hot_listen", "timeout_seconds"),
            default=HOT_LISTEN_TIMEOUT_DEFAULT_SECONDS,
        )
        self.hot_timeout_var = ctk.StringVar(value=str(int(hot_timeout)))

        tts_rate_str = normalize_edge_tts_rate(config.get("tts", "rate") or "+0%")
        self.tts_rate_var = ctk.DoubleVar(value=self._parse_rate(tts_rate_str))

        vad_ms = config.get("vad", "min_silence_duration_ms") or 1500
        self.vad_ms_var = ctk.DoubleVar(value=float(vad_ms))

        row = 0
        self._settings_section_label(parent, row, "常用設定")
        row += 1
        common = self._settings_card(parent, row)
        self._card_switch(
            common,
            2,
            "Heartbeat",
            "啟用後會定時檢查是否需要主動提醒，且只在 08:00 到 21:00 之間運作。",
            self.heartbeat_var,
            self._on_heartbeat_toggle,
        )

        self._card_option_menu(
            common,
            0,
            "LLM 後端",
            "切換目前使用的 AI 大腦",
            self.backend_var,
            ["antigravity_cli", "opencode_cli", "codex_cli", "claude_code", "openclaw"],
            self._on_backend_change,
        )
        self.backend_menu = common._option_widgets[-1]

        self._card_switch(
            common,
            1,
            "熱監聽",
            "回覆後短時間內可直接接話",
            self.hot_listen_var,
            self._on_hot_listen_toggle,
        )

        row += 1
        self._settings_section_label(parent, row, "進階設定")
        row += 1

        advanced = self._settings_card(parent, row)

        self._card_option_menu(
            advanced,
            0,
            "STT Backend",
            "變更語音辨識後端，重啟後生效",
            self.device_var,
            ["cuda", "cpu", "groq"],
            self._on_device_change,
        )

        self.tts_rate_label = self._card_slider(
            advanced,
            1,
            "TTS 語速",
            "調整語音回覆的速度",
            self.tts_rate_var,
            EDGE_TTS_RATE_MIN_PERCENT,
            EDGE_TTS_RATE_MAX_PERCENT,
            EDGE_TTS_RATE_STEPS,
            self._on_tts_rate_change,
            tts_rate_str,
            C_ACCENT,
            C_ACCENT,
        )

        self._card_entry(
            advanced,
            2,
            "熱監聽秒數",
            "控制免喚醒詞可接話的時間",
            self.hot_timeout_var,
            self._on_hot_timeout_change,
        )

        self.vad_ms_label = self._card_slider(
            advanced,
            3,
            "VAD 靜音 (ms)",
            "調整停頓多久後送出語音內容",
            self.vad_ms_var,
            300,
            3000,
            27,
            self._on_vad_ms_change,
            f"{int(vad_ms)} ms",
            C_SUCCESS,
            C_SUCCESS,
        )

    def _settings_section_label(self, parent, row: int, text: str):
        ctk.CTkLabel(
            parent,
            text=text,
            font=FONT_BODY_BOLD,
            text_color=C_TEXT_PRI,
            anchor="w",
        ).grid(row=row, column=0, sticky="ew", padx=4, pady=(8, 8))

    def _settings_card(self, parent, row: int):
        card = ctk.CTkFrame(
            parent,
            fg_color=C_PANEL,
            corner_radius=22,
            border_width=1,
            border_color=C_PANEL_BORDER,
        )
        card.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        card.grid_columnconfigure(0, weight=1)
        card._option_widgets = []
        return card

    def _setting_row_shell(self, parent, row: int, title: str, subtitle: str):
        shell = ctk.CTkFrame(parent, fg_color="transparent")
        shell.grid(row=row, column=0, sticky="ew", padx=16, pady=12)
        shell.grid_columnconfigure(0, weight=1)

        text = ctk.CTkFrame(shell, fg_color="transparent")
        text.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        ctk.CTkLabel(text, text=title, font=FONT_BODY_BOLD, text_color=C_TEXT_PRI, anchor="w").pack(anchor="w")
        ctk.CTkLabel(text, text=subtitle, font=FONT_SMALL, text_color=C_TEXT_SEC, anchor="w").pack(anchor="w", pady=(2, 0))
        return shell

    def _card_option_menu(self, parent, row, title, subtitle, variable, values, command):
        shell = self._setting_row_shell(parent, row, title, subtitle)
        widget = ctk.CTkOptionMenu(
            shell,
            values=values,
            variable=variable,
            command=command,
            fg_color=C_PANEL_MUTED,
            button_color=C_ACCENT,
            button_hover_color=C_ACCENT_HOVER,
            text_color=C_TEXT_PRI,
            font=FONT_SMALL,
            width=136,
            height=42,
        )
        widget.grid(row=0, column=1, sticky="e")
        parent._option_widgets.append(widget)

    def _card_switch(self, parent, row, title, subtitle, variable, command):
        shell = self._setting_row_shell(parent, row, title, subtitle)
        ctk.CTkSwitch(
            shell,
            text="",
            variable=variable,
            command=command,
            progress_color=C_ACCENT,
            button_color=C_TEXT_PRI,
            width=68,
        ).grid(row=0, column=1, sticky="e")

    def _card_slider(
        self,
        parent,
        row,
        title,
        subtitle,
        variable,
        from_,
        to,
        steps,
        command,
        value_text,
        progress_color,
        button_color,
    ):
        shell = ctk.CTkFrame(parent, fg_color="transparent")
        shell.grid(row=row, column=0, sticky="ew", padx=16, pady=12)
        shell.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(shell, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        head.grid_columnconfigure(0, weight=1)

        label_group = ctk.CTkFrame(head, fg_color="transparent")
        label_group.grid(row=0, column=0, sticky="w", padx=(0, 12))
        ctk.CTkLabel(label_group, text=title, font=FONT_BODY_BOLD, text_color=C_TEXT_PRI, anchor="w").pack(anchor="w")
        ctk.CTkLabel(
            label_group,
            text=subtitle,
            font=FONT_SMALL,
            text_color=C_TEXT_SEC,
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        value_label = ctk.CTkLabel(head, text=value_text, font=FONT_SMALL, text_color=C_TEXT_PRI, anchor="e")
        value_label.grid(row=0, column=1, sticky="e")

        ctk.CTkSlider(
            shell,
            from_=from_,
            to=to,
            variable=variable,
            number_of_steps=steps,
            command=command,
            progress_color=progress_color,
            button_color=button_color,
            button_hover_color=C_ACCENT_HOVER,
        ).grid(row=1, column=0, sticky="ew", pady=(10, 0))
        return value_label

    def _card_entry(self, parent, row, title, subtitle, variable, command):
        shell = self._setting_row_shell(parent, row, title, subtitle)
        widget = ctk.CTkEntry(
            shell,
            textvariable=variable,
            width=88,
            justify="center",
            fg_color=C_INPUT,
            border_color=C_ACCENT,
            text_color=C_TEXT_PRI,
            font=FONT_SMALL,
            height=42,
            corner_radius=12,
        )
        widget.grid(row=0, column=1, sticky="e")
        widget.bind("<Return>", command)
        widget.bind("<FocusOut>", command)

    def _build_text_input(self, parent):
        self.input_shell = ctk.CTkFrame(parent, fg_color=C_PANEL, corner_radius=0)
        self.input_shell.grid(row=2, column=0, sticky="ew", padx=INPUT_SHELL_HORIZONTAL_PADDING, pady=(0, 16))
        self.input_shell.columnconfigure(0, weight=1)

        self.input_helper = ctk.CTkFrame(
            self.input_shell,
            fg_color=C_PANEL_SOFT,
            corner_radius=20,
            border_width=1,
            border_color=C_PANEL_BORDER,
        )
        self.input_helper.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.input_helper.columnconfigure(0, weight=1)
        self.input_helper.columnconfigure(1, minsize=INPUT_MODE_HINT_MIN_WIDTH)

        self.input_helper_label = tk.Label(
            self.input_helper,
            text="文字模式適合安靜環境或不方便開口時使用",
            font=FONT_SMALL,
            fg=C_TEXT_SEC,
            bg=C_PANEL_SOFT,
            bd=0,
            padx=TEXT_SAFE_PADX,
            pady=0,
            anchor="w",
            justify="left",
            relief="flat",
            highlightthickness=0,
        )
        self.input_helper_label.grid(row=0, column=0, sticky="ew", padx=16, pady=12)

        self.input_mode_hint = ctk.CTkLabel(
            self.input_helper,
            text="目前：語音待命",
            font=FONT_SMALL,
            text_color=C_ACCENT,
            anchor="e",
            width=INPUT_MODE_HINT_MIN_WIDTH,
            height=SMALL_TEXT_SAFE_HEIGHT,
            padx=TEXT_SAFE_PADX,
        )
        self.input_mode_hint.grid(row=0, column=1, sticky="e", padx=16, pady=12)

        input_row = ctk.CTkFrame(
            self.input_shell,
            fg_color=C_PANEL_SOFT,
            corner_radius=24,
            border_width=1,
            border_color=C_PANEL_BORDER,
            height=92,
        )
        input_row.grid(row=1, column=0, sticky="ew")
        input_row.columnconfigure(0, weight=1)

        self.text_input = ctk.CTkEntry(
            input_row,
            placeholder_text="輸入訊息，按 Enter 送出...",
            placeholder_text_color=C_TEXT_MUTED,
            fg_color=C_INPUT,
            border_color=C_ACCENT_SOFT,
            border_width=1,
            text_color=C_TEXT_PRI,
            font=FONT_BODY,
            height=56,
            corner_radius=18,
            width=TEXT_INPUT_MIN_WIDTH,
        )
        self.text_input.grid(row=0, column=0, sticky="ew", padx=(INPUT_ROW_LEFT_PADDING, INPUT_ROW_GAP), pady=18)
        self.text_input.bind("<Return>", self._on_text_submit)

        self.send_button = ctk.CTkButton(
            input_row,
            text="送出",
            fg_color=C_ACCENT,
            hover_color=C_ACCENT_HOVER,
            text_color="white",
            font=FONT_BUTTON_SMALL,
            width=SEND_BUTTON_WIDTH,
            height=56,
            corner_radius=18,
            command=self._on_text_submit,
        )
        self.send_button.grid(row=0, column=1, padx=(0, INPUT_ROW_RIGHT_PADDING), pady=18)

    def on_stop_click(self):
        self.assistant.interrupt()

    def _on_primary_action(self):
        if not self._voice_mode:
            self._on_mode_toggle()
            return

        if self._current_state in (State.SENDING, State.SPEAKING):
            self.assistant.interrupt()
            return

        if self._current_state == State.COLLECTING:
            self.add_message_ui("system", "我正在聽，請直接說出你想做的事。")
            return

        if self._current_state == State.HOT_LISTEN:
            self.add_message_ui("system", "現在可以直接接著說，不需要再喚醒一次。")
            return

        if self.assistant.begin_manual_capture():
            self.add_message_ui("system", "我正在聽，請直接說出你想做的事。")
            return

        if self._current_state == State.HOT_LISTEN:
            self.add_message_ui("system", "現在可以直接接著說，不需要再喚醒一次。")
            return

        self.add_message_ui("system", "目前無法開始收音，請稍候再試。")

    def _on_mode_toggle(self):
        self._voice_mode = not self._voice_mode
        if self._voice_mode:
            self.mode_btn.configure(text="語音模式", fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER)
            self.assistant.set_voice_enabled(True)
            self.add_message_ui("system", "已切換回語音模式")
        else:
            self.mode_btn.configure(text="文字模式", fg_color=C_SUCCESS, hover_color="#21695D")
            self.assistant.set_voice_enabled(False)
            self.add_message_ui("system", "已切換為文字模式，語音收聽暫停")
            self.text_input.focus_set()
        self._refresh_interaction_controls()

    def _toggle_settings(self):
        self._settings_visible = not self._settings_visible
        self._sync_settings_drawer_visibility()

    def _sync_settings_drawer_visibility(self):
        if not hasattr(self, "settings_drawer"):
            return
        if self._settings_visible:
            self.settings_drawer.place(
                relx=1.0,
                rely=0.0,
                x=-14,
                y=SETTINGS_DRAWER_OFFSET_Y,
                anchor="ne",
                relheight=0.84,
            )
            self.settings_button.configure(fg_color=C_ACCENT_SOFT, text_color=C_ACCENT)
        else:
            self.settings_drawer.place_forget()
            self.settings_button.configure(fg_color=C_PANEL_MUTED, text_color=C_TEXT_PRI)

    def _handle_window_resize(self, event):
        if event.widget is self:
            self._apply_panel_split()
            self._sync_settings_drawer_visibility()

    def _on_right_panel_resize(self, event):
        self._update_right_panel_text_layout()

    def _on_stage_card_resize(self, event):
        self._update_stage_image_layout()

    def _enter_startup_fullscreen(self):
        if not self.__dict__.get("_startup_fullscreen_pending", False):
            return
        if "main_frame" not in self.__dict__:
            self.after(30, self._enter_startup_fullscreen)
            return

        self.update_idletasks()
        if self.main_frame.winfo_width() <= 1 or self.main_frame.winfo_height() <= 1:
            self.after(30, self._enter_startup_fullscreen)
            return

        self._startup_fullscreen_pending = False
        self._set_fullscreen(True)

    def _refresh_layout_after_window_mode_change(self):
        if "main_frame" not in self.__dict__:
            return

        self.update_idletasks()
        self._apply_panel_split()
        self._update_stage_image_layout()
        self._update_right_panel_text_layout()
        self._sync_settings_drawer_visibility()

    def _schedule_window_mode_layout_refresh(self):
        self.after_idle(self._refresh_layout_after_window_mode_change)
        self.after(120, self._refresh_layout_after_window_mode_change)

    def _apply_panel_split(self):
        if "main_frame" not in self.__dict__:
            return

        total_width = self.main_frame.winfo_width()
        total_height = self.main_frame.winfo_height()
        if total_width <= 1 or total_height <= 1:
            return

        left_width, right_width = self._compute_proportional_panel_widths(
            total_width=total_width,
            left_weight=LEFT_PANEL_WEIGHT,
            right_weight=RIGHT_PANEL_WEIGHT,
        )

        self.main_frame.grid_columnconfigure(0, weight=LEFT_PANEL_WEIGHT, minsize=max(0, left_width))
        self.main_frame.grid_columnconfigure(1, weight=RIGHT_PANEL_WEIGHT, minsize=max(0, right_width))

        if "left_panel" in self.__dict__:
            self.left_panel.configure(width=self._to_widget_logical_size(self.left_panel, left_width))
        if "right_panel" in self.__dict__:
            self.right_panel.configure(width=self._to_widget_logical_size(self.right_panel, right_width))

        self.after_idle(self._update_right_panel_text_layout)

    def _update_right_panel_text_layout(self):
        if "right_panel" not in self.__dict__:
            return

        panel_width = self._get_widget_logical_width(self.right_panel)
        if panel_width <= 0:
            return

        chat_content_width = self._compute_inner_width(panel_width, horizontal_padding=28)
        input_content_width = self._compute_inner_width(panel_width, horizontal_padding=24)
        empty_state_width = self._compute_inner_width(chat_content_width, horizontal_padding=24)
        self._update_chat_bubble_wraplengths(chat_content_width)

        if "brand_subtitle_label" in self.__dict__ and "top_actions" in self.__dict__:
            brand_wrap = self._compute_available_wraplength(
                container_width=panel_width,
                occupied_widths=(self._get_widget_logical_width(self.top_actions),),
                padding=72,
                min_wrap=180,
            )
            self.brand_subtitle_label.configure(wraplength=brand_wrap)

        if "chat_header" in self.__dict__ and "chat_header_badge" in self.__dict__ and "chat_header_hint" in self.__dict__:
            header_wrap = self._compute_available_wraplength(
                container_width=chat_content_width,
                occupied_widths=(self._get_widget_logical_width(self.chat_header_badge),),
                padding=56,
                min_wrap=RIGHT_PANEL_HINT_MIN_WRAP,
            )
            self.chat_header.configure(width=chat_content_width)
            self.chat_header_hint.configure(wraplength=header_wrap)

        if "chat_summary_card" in self.__dict__ and "chat_summary_badge" in self.__dict__:
            summary_wrap = self._compute_available_wraplength(
                container_width=chat_content_width,
                occupied_widths=(self._get_widget_logical_width(self.chat_summary_badge),),
                padding=56,
                min_wrap=RIGHT_PANEL_BODY_MIN_WRAP,
            )
            self.chat_summary_card.configure(width=chat_content_width)
            self.chat_summary_title.configure(wraplength=summary_wrap)
            self.chat_summary_hint.configure(wraplength=summary_wrap)

        if "empty_state" in self.__dict__:
            empty_state_wrap = self._compute_available_wraplength(
                container_width=empty_state_width,
                padding=36,
                min_wrap=RIGHT_PANEL_BODY_MIN_WRAP,
            )
            self.empty_state.configure(width=empty_state_width)
            self.empty_state_title.configure(wraplength=empty_state_wrap)
            self.empty_state_body.configure(wraplength=empty_state_wrap)
            self.empty_state_hint.configure(wraplength=empty_state_wrap)

        if "input_helper" in self.__dict__ and "input_mode_hint" in self.__dict__ and "input_helper_label" in self.__dict__:
            helper_wrap = self._compute_available_wraplength(
                container_width=input_content_width,
                occupied_widths=(self._get_widget_logical_width(self.input_mode_hint),),
                padding=48,
                min_wrap=RIGHT_PANEL_HINT_MIN_WRAP,
            )
            self.input_helper.configure(width=input_content_width)
            self.input_helper_label.configure(wraplength=helper_wrap)

        if "text_input" in self.__dict__:
            text_input_width = self._compute_inner_width(
                input_content_width,
                horizontal_padding=INPUT_ROW_LEFT_PADDING + INPUT_ROW_GAP + INPUT_ROW_RIGHT_PADDING + SEND_BUTTON_WIDTH,
            )
            self.text_input.configure(width=max(140, text_input_width))

    def _update_stage_image_layout(self):
        if "stage_card" not in self.__dict__ or "image_frame" not in self.__dict__:
            return

        self.update_idletasks()

        card_width = self.stage_card.winfo_width()
        card_height = self.stage_card.winfo_height()
        if card_width <= 1 or card_height <= 1:
            return

        side = self._compute_square_image_side(
            available_width=card_width,
            available_height=card_height,
            horizontal_padding=36,
            vertical_padding=36,
            min_side=240,
            max_side=MAX_STAGE_IMAGE_SIDE,
        )

        self.image_frame.configure(width=side, height=side)
        self.animator.set_image_size(side, side)

    def _on_text_submit(self, event=None):
        text = self.text_input.get().strip()
        if not text:
            return

        accepted, reason = self.assistant.send_text_message(text)
        if not accepted:
            if reason == "busy":
                self.add_message_ui("system", "系統仍在處理上一則訊息，請稍候再送出。")
            elif reason == "unavailable":
                self.add_message_ui("system", "系統尚未完成初始化，暫時無法送出文字訊息。")
            return

        self.text_input.delete(0, "end")
        self.add_message_ui("user", text)
        self._refresh_interaction_controls()

    def _on_backend_change(self, new_backend: str):
        if self.assistant.change_backend(new_backend):
            self.add_message_ui("system", f"已切換至 {new_backend} 後端")
        else:
            self.backend_var.set(config.get("llm", "active_backend") or "antigravity_cli")
            message = (
                getattr(self.assistant, "last_backend_switch_error", "")
                or "系統忙碌中，請等目前回覆完成後再切換 LLM 後端。"
            )
            self.add_message_ui("system", message)
        self._update_context_chips()
        self._refresh_interaction_controls()

    def _on_device_change(self, new_device: str):
        if new_device == "groq":
            config.set("whisper", "backend", value="groq")
            self.add_message_ui("system", "STT backend 已設為 groq，重啟後生效")
            return

        config.set("whisper", "backend", value="local")
        config.set("whisper", "device", value=new_device)
        ct = "float16" if new_device == "cuda" else "int8"
        config.set("whisper", "compute_type", value=ct)
        self.add_message_ui("system", f"STT backend 已設為 {new_device}，重啟後生效")

    def _on_tts_rate_change(self, value):
        rate_str = normalize_edge_tts_rate(value)
        self.tts_rate_label.configure(text=rate_str)
        config.set("tts", "rate", value=rate_str)
        if hasattr(self.assistant, "update_tts_settings"):
            self.assistant.update_tts_settings(rate=rate_str)

    def _on_hot_listen_toggle(self):
        enabled = self.hot_listen_var.get()
        config.set("hot_listen", "enabled", value=enabled)
        if hasattr(self.assistant, "apply_hot_listen_settings"):
            self.assistant.apply_hot_listen_settings()
        self._update_context_chips()

    def _on_heartbeat_toggle(self):
        enabled = self.heartbeat_var.get()
        config.set("heartbeat", "enabled", value=enabled)
        if hasattr(self.assistant, "apply_heartbeat_settings"):
            self.assistant.apply_heartbeat_settings()

    def _on_hot_timeout_change(self, event=None):
        try:
            val = self._coerce_hot_timeout_seconds(
                self.hot_timeout_var.get(),
                default=HOT_LISTEN_TIMEOUT_DEFAULT_SECONDS,
                strict=True,
            )
            self.hot_timeout_var.set(str(val))
            config.set("hot_listen", "timeout_seconds", value=float(val))
            if hasattr(self.assistant, "apply_hot_listen_settings"):
                self.assistant.apply_hot_listen_settings()
        except ValueError:
            fallback = self._coerce_hot_timeout_seconds(
                config.get("hot_listen", "timeout_seconds", default=HOT_LISTEN_TIMEOUT_DEFAULT_SECONDS),
                default=HOT_LISTEN_TIMEOUT_DEFAULT_SECONDS,
            )
            self.hot_timeout_var.set(str(fallback))
            self.add_message_ui("system", "熱監聽秒數必須是整數，已恢復成上一個有效值。")

    @staticmethod
    def _coerce_hot_timeout_seconds(raw_value, *, default: int, strict: bool = False) -> int:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            if strict:
                raise ValueError
            value = int(default)
        return min(
            max(value, HOT_LISTEN_TIMEOUT_MIN_SECONDS),
            HOT_LISTEN_TIMEOUT_MAX_SECONDS,
        )

    def _on_vad_ms_change(self, value):
        v = int(value)
        self.vad_ms_label.configure(text=f"{v} ms")
        config.set("vad", "min_silence_duration_ms", value=v)
        if hasattr(self.assistant, "update_vad_min_silence"):
            self.assistant.update_vad_min_silence(v)

    def update_state_ui(self, state: State):
        self.after(0, lambda: self._update_state_logic(state))

    def _update_state_logic(self, state: State):
        previous_state = self.__dict__.get("_current_state", State.IDLE_LISTEN)
        self._current_state = state
        self._raise_for_speaking_if_fullscreen(previous_state, state)
        state_text = STATE_TEXT.get(state, "未知狀態")
        state_hint = STATE_HINT.get(state, "")
        color = STATE_COLOR.get(state, C_TEXT_SEC)
        surface = STATE_SURFACE.get(state, C_PANEL_SOFT)

        self.state_label.configure(text=state_text)
        self.state_hint_label.configure(text=state_hint)
        self.state_indicator.configure(fg_color=color)
        self.chat_header_badge.configure(text=state_text, text_color=color, fg_color=surface)
        self.chat_header_hint.configure(text=state_hint or "我會保留最新對話脈絡，方便你直接接著聊")

        if state == State.HOT_LISTEN:
            timeout_seconds = int(config.get("hot_listen", "timeout_seconds", default=10))
            self.state_hint_label.configure(text=f"接下來 {timeout_seconds} 秒內可直接接話。")
        elif state == State.SPEAKING:
            self.state_hint_label.configure(text="你可以隨時打斷我。")
        elif state == State.SENDING:
            self.state_hint_label.configure(text="我正在整理回覆。")
        elif state == State.COLLECTING:
            self.state_hint_label.configure(text="直接把整句話說完就可以。")

        can_interrupt = state in (State.COLLECTING, State.SENDING, State.SPEAKING, State.HOT_LISTEN)
        self.stop_button.configure(
            state="normal" if can_interrupt else "disabled",
            fg_color=C_DANGER if can_interrupt else C_PANEL_MUTED,
            hover_color=C_DANGER_HOVER if can_interrupt else C_PANEL_MUTED,
            text_color="white" if can_interrupt else C_TEXT_MUTED,
        )

        self.animator.set_state(state)
        self._sync_stage_ambience(state)
        self._start_status_pulse(state)
        self._update_context_chips()
        self._refresh_interaction_controls()

    def _raise_for_speaking_if_fullscreen(self, previous_state: State, state: State):
        if previous_state == State.SPEAKING or state != State.SPEAKING:
            return
        if not bool(self.overrideredirect()):
            return

        self.attributes("-topmost", True)
        self.lift()
        try:
            self.focus_force()
        except tk.TclError:
            pass
        self.after(10, lambda: self.attributes("-topmost", False))

    def add_message_ui(
        self,
        role: str,
        text: str,
        *,
        update_existing: bool | None = None,
        speaker_name: str | None = None,
    ):
        bubble_kwargs = {"update_existing": update_existing}
        if speaker_name is not None:
            bubble_kwargs["speaker_name"] = speaker_name

        self.after(
            0,
            lambda: self._add_bubble_logic(role, text, **bubble_kwargs),
        )

    def _add_bubble_logic(
        self,
        role: str,
        text: str,
        *,
        update_existing: bool | None = None,
        speaker_name: str | None = None,
    ):
        if update_existing is None:
            update_existing = role == "assistant"

        if role == "assistant" and update_existing and self.last_ai_bubble:
            self.last_ai_bubble.set_wraplength(self._get_current_chat_bubble_wraplength())
            self.last_ai_bubble.update_text(text)
            self._schedule_chat_scroll_to_latest()
            return

        MAX_BUBBLES = MAX_RENDERED_MESSAGES

        MAX_BUBBLES = 100
        if self._message_count >= MAX_BUBBLES:
            children = self.chat_scroll.winfo_children()
            for child in children:
                if child is not getattr(self, "empty_state", None):
                    child.destroy()
                    self._message_count -= 1
                    break

        if self._message_count == 0 and hasattr(self, "empty_state"):
            self.empty_state.pack_forget()

        if role == "system":
            box = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
            box.pack(fill="x", padx=8, pady=6)
            ctk.CTkLabel(
                box,
                text=text,
                font=FONT_SMALL,
                text_color=C_TEXT_SEC,
                fg_color=C_PANEL_SOFT,
                corner_radius=14,
                padx=12,
                pady=8,
                anchor="center",
            ).pack()
            self._tag_message_widget(box, "system", counts_toward_recent_turns=False)
            self.last_ai_bubble = None
        elif role == "user":
            display_text = self._format_user_message_for_display(text, speaker_name)
            bubble = ChatBubble(self.chat_scroll, text=display_text, role="user")
            bubble.set_wraplength(self._get_current_chat_bubble_wraplength())
            bubble.pack(fill="x", padx=8, pady=3)
            self._tag_message_widget(bubble, "user", counts_toward_recent_turns=True)
            self.last_ai_bubble = None
        elif role == "assistant":
            bubble = ChatBubble(self.chat_scroll, text=text, role="assistant")
            bubble.set_wraplength(self._get_current_chat_bubble_wraplength())
            bubble.pack(fill="x", padx=8, pady=3)
            self._tag_message_widget(bubble, "assistant", counts_toward_recent_turns=True)
            self.last_ai_bubble = bubble
        else:
            return

        self._message_count += 1
        self._trim_total_rendered_messages()
        self._trim_conversation_turns()

        self._schedule_chat_scroll_to_latest()

    def _refresh_interaction_controls(self):
        text_enabled = (not self._voice_mode) and self.assistant.can_accept_text_message()
        widget_state = "normal" if text_enabled else "disabled"
        self.text_input.configure(state=widget_state)
        self.send_button.configure(state=widget_state)

        backend_state = "normal" if self.assistant.can_change_backend() else "disabled"
        if hasattr(self, "backend_menu"):
            self.backend_menu.configure(state=backend_state)

        if self._voice_mode:
            self.mode_badge.configure(text="語音待命", fg_color=C_ACCENT_SOFT, text_color=C_ACCENT)
            self.input_mode_hint.configure(text="目前：語音待命", text_color=C_ACCENT)
        else:
            self.mode_badge.configure(text="文字模式", fg_color=C_SUCCESS_SOFT, text_color=C_SUCCESS)
            self.input_mode_hint.configure(text="目前：文字模式", text_color=C_SUCCESS)

        if self._current_state in (State.SENDING, State.SPEAKING):
            primary_text = "正在回應"
        elif self._current_state == State.COLLECTING:
            primary_text = "聆聽中..."
        elif self._current_state == State.HOT_LISTEN:
            primary_text = "直接接著說"
        elif self._voice_mode:
            primary_text = "開始說話"
        else:
            primary_text = "切換回語音"

        self.primary_action_button.configure(
            text=primary_text,
            fg_color=C_ACCENT if self._voice_mode else C_SUCCESS,
            hover_color=C_ACCENT_HOVER if self._voice_mode else "#21695D",
        )

    def _update_context_chips(self):
        backend = config.get("llm", "active_backend") or "antigravity_cli"
        backend_label = {
            "antigravity_cli": "Antigravity CLI",
            "opencode_cli": "OpenCode CLI",
            "codex_cli": "Codex CLI",
            "claude_code": "Claude Code",
            "openclaw": "OpenClaw",
        }.get(backend, backend)
        if "backend_chip" in self.__dict__:
            self.backend_chip.configure(text=f"後端：{backend_label}")

        hot_enabled = bool(config.get("hot_listen", "enabled", default=True))
        timeout_seconds = int(config.get("hot_listen", "timeout_seconds", default=10))
        if "hot_listen_chip" in self.__dict__:
            if hot_enabled:
                self.hot_listen_chip.configure(
                    text=f"熱監聽：開啟 {timeout_seconds}s",
                    text_color=C_SUCCESS,
                    fg_color=C_SUCCESS_SOFT,
                )
            else:
                self.hot_listen_chip.configure(
                    text="熱監聽：關閉",
                    text_color=C_TEXT_SEC,
                    fg_color=C_PANEL_SOFT,
                )

    def _sync_stage_ambience(self, state: State):
        surface = STATE_SURFACE.get(state, C_STAGE_GLOW)
        border = STATE_COLOR.get(state, C_STAGE_BORDER)

        self.stage_glow_bar.configure(fg_color=surface)
        self.stage_card.configure(border_color=border)
        self.status_card.configure(border_color=border)

        if state == State.SPEAKING:
            self.chat_summary_badge.configure(text="互動節奏", text_color=C_ACCENT, fg_color=C_ACCENT_SOFT)
            self.chat_summary_title.configure(text="正在自然回覆中")
            self.chat_summary_hint.configure(text="現在最適合直接聽回覆；若你想插話，也可以立即打斷重新說。")
        elif state == State.SENDING:
            self.chat_summary_badge.configure(text="思考階段", text_color="#B26B1E", fg_color="#F9E6C9")
            self.chat_summary_title.configure(text="已收到需求，正在整理")
            self.chat_summary_hint.configure(text="系統正把你的內容轉成適合回答與朗讀的回覆，通常不需要再操作。")
        elif state == State.COLLECTING:
            self.chat_summary_badge.configure(text="收音中", text_color=C_SUCCESS, fg_color=C_SUCCESS_SOFT)
            self.chat_summary_title.configure(text="直接把整句話說完")
            self.chat_summary_hint.configure(text="不用停下來找按鈕，像平常跟人說話那樣講完整句就好。")
        elif state == State.HOT_LISTEN:
            self.chat_summary_badge.configure(text="接話模式", text_color=C_SUCCESS, fg_color=C_SUCCESS_SOFT)
            self.chat_summary_title.configure(text="現在最適合直接延續話題")
            self.chat_summary_hint.configure(text="剛聽完回覆時，不用再次喚醒，這幾秒內直接補一句就能延續對話。")
        else:
            self.chat_summary_badge.configure(text="今日互動風格", text_color=C_GOLD, fg_color=C_GOLD_SOFT)
            self.chat_summary_title.configure(text="自然、即時、可打斷")
            self.chat_summary_hint.configure(text="你可以把它當成家中的語音管家，想到就說，不需要記操作流程。")

    def _safe_cleanup_call(self, label: str, action):
        try:
            action()
        except Exception:
            logger.warning("UI cleanup step failed: %s", label, exc_info=True)

    def _state_indicator_is_alive(self) -> bool:
        widget = self.__dict__.get("state_indicator")
        if widget is None:
            return False

        exists = getattr(widget, "winfo_exists", None)
        if not callable(exists):
            return True

        try:
            return bool(exists())
        except tk.TclError:
            return False

    def _start_status_pulse(self, state: State):
        self._stop_status_pulse()
        if state not in (State.COLLECTING, State.SENDING, State.SPEAKING, State.HOT_LISTEN):
            return
        self._pulse_step = 0
        self._pulse_status_indicator()

    def _pulse_status_indicator(self):
        if not self._state_indicator_is_alive():
            self._pulse_after_id = None
            return
        cycle = [
            (18, 18),
            (14, 14),
            (20, 20),
            (14, 14),
        ]
        width, height = cycle[self._pulse_step % len(cycle)]
        try:
            self.state_indicator.configure(width=width, height=height, corner_radius=max(width, height))
            self.state_indicator.place(relx=0.5, rely=0.5, anchor="center")
            self._pulse_step += 1
            self._pulse_after_id = self.after(280, self._pulse_status_indicator)
        except tk.TclError:
            self._pulse_after_id = None

    def _stop_status_pulse(self):
        pulse_after_id = self.__dict__.get("_pulse_after_id")
        if pulse_after_id is not None:
            try:
                self.after_cancel(pulse_after_id)
            except Exception:
                pass
            self._pulse_after_id = None
        if self._state_indicator_is_alive():
            try:
                self.state_indicator.configure(width=14, height=14, corner_radius=999)
                self.state_indicator.place(relx=0.5, rely=0.5, anchor="center")
            except tk.TclError:
                pass

    @staticmethod
    def _parse_rate(rate_str: str) -> float:
        try:
            return float(normalize_edge_tts_rate(rate_str).replace("%", "").replace("+", ""))
        except ValueError:
            return 0.0

    @staticmethod
    def _should_block_fullscreen_system_command(wparam: int) -> bool:
        command = int(wparam) & 0xFFF0
        return command in (SC_SCREENSAVE, SC_MONITORPOWER)

    @staticmethod
    def _get_window_long_accessors():
        user32 = ctypes.windll.user32
        if ctypes.sizeof(ctypes.c_void_p) == ctypes.sizeof(ctypes.c_long):
            getter = user32.GetWindowLongW
            setter = user32.SetWindowLongW
        else:
            getter = user32.GetWindowLongPtrW
            setter = user32.SetWindowLongPtrW

        getter.argtypes = [ctypes.c_void_p, ctypes.c_int]
        getter.restype = LONG_PTR
        setter.argtypes = [ctypes.c_void_p, ctypes.c_int, LONG_PTR]
        setter.restype = LONG_PTR
        return getter, setter

    @staticmethod
    def _get_call_window_proc():
        call_window_proc = ctypes.windll.user32.CallWindowProcW
        call_window_proc.argtypes = [
            LONG_PTR,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        call_window_proc.restype = LONG_PTR
        return call_window_proc

    @staticmethod
    def _get_keyboard_hook_accessors():
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        set_windows_hook = user32.SetWindowsHookExW
        set_windows_hook.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, ctypes.c_uint]
        set_windows_hook.restype = ctypes.c_void_p

        call_next_hook = user32.CallNextHookEx
        call_next_hook.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
        call_next_hook.restype = LONG_PTR

        unhook_windows_hook = user32.UnhookWindowsHookEx
        unhook_windows_hook.argtypes = [ctypes.c_void_p]
        unhook_windows_hook.restype = ctypes.c_int

        peek_message = user32.PeekMessageW
        peek_message.argtypes = [ctypes.POINTER(MSG), ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
        peek_message.restype = ctypes.c_int

        get_message = user32.GetMessageW
        get_message.argtypes = [ctypes.POINTER(MSG), ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
        get_message.restype = ctypes.c_int

        translate_message = user32.TranslateMessage
        translate_message.argtypes = [ctypes.POINTER(MSG)]
        translate_message.restype = ctypes.c_int

        dispatch_message = user32.DispatchMessageW
        dispatch_message.argtypes = [ctypes.POINTER(MSG)]
        dispatch_message.restype = LONG_PTR

        post_thread_message = user32.PostThreadMessageW
        post_thread_message.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        post_thread_message.restype = ctypes.c_int

        get_current_thread_id = kernel32.GetCurrentThreadId
        get_current_thread_id.argtypes = []
        get_current_thread_id.restype = ctypes.c_uint

        return (
            set_windows_hook,
            call_next_hook,
            unhook_windows_hook,
            peek_message,
            get_message,
            translate_message,
            dispatch_message,
            post_thread_message,
            get_current_thread_id,
        )

    @staticmethod
    def _should_block_fullscreen_keyboard_shortcut(
        vk_code: int,
        flags: int = 0,
        ctrl_down: bool = False,
    ) -> bool:
        vk_code = int(vk_code)
        flags = int(flags)
        if vk_code in (VK_LWIN, VK_RWIN):
            return True
        if flags & LLKHF_ALTDOWN and vk_code in (VK_TAB, VK_ESCAPE, VK_F4, VK_SPACE):
            return True
        if ctrl_down and vk_code == VK_ESCAPE:
            return True
        return False

    def _install_fullscreen_screen_guard(self):
        if os.name != "nt" or WNDPROC is None:
            return
        if self.__dict__.get("_screen_guard_hwnd") is not None:
            return

        try:
            hwnd = int(self.winfo_id())
            getter, setter = self._get_window_long_accessors()
            call_window_proc = self._get_call_window_proc()
            previous_wndproc = getter(hwnd, GWL_WNDPROC)
            if not previous_wndproc:
                logger.warning("Failed to read window proc for fullscreen screen guard.")
                return

            def _screen_guard_wndproc(window_handle, msg, wparam, lparam):
                try:
                    if msg == WM_SYSCOMMAND and self._should_block_fullscreen_system_command(wparam):
                        logger.info(
                            "Blocked Windows system screen command while fullscreen.",
                            extra={"command": hex(int(wparam) & 0xFFF0)},
                        )
                        return 0
                except Exception:
                    logger.warning("Fullscreen screen guard callback failed.", exc_info=True)
                return call_window_proc(previous_wndproc, window_handle, msg, wparam, lparam)

            screen_guard_proc = WNDPROC(_screen_guard_wndproc)
            setter(hwnd, GWL_WNDPROC, ctypes.cast(screen_guard_proc, ctypes.c_void_p).value)
            self._screen_guard_hwnd = hwnd
            self._screen_guard_prev_wndproc = previous_wndproc
            self._screen_guard_proc = screen_guard_proc
        except Exception:
            logger.warning("Failed to install fullscreen screen guard.", exc_info=True)

    def _remove_fullscreen_screen_guard(self):
        hwnd = self.__dict__.get("_screen_guard_hwnd")
        previous_wndproc = self.__dict__.get("_screen_guard_prev_wndproc")
        screen_guard_proc = self.__dict__.get("_screen_guard_proc")

        if hwnd is None or previous_wndproc is None or screen_guard_proc is None:
            self._screen_guard_hwnd = None
            self._screen_guard_prev_wndproc = None
            self._screen_guard_proc = None
            return

        try:
            _, setter = self._get_window_long_accessors()
            setter(hwnd, GWL_WNDPROC, previous_wndproc)
        except Exception:
            logger.warning("Failed to remove fullscreen screen guard.", exc_info=True)
        finally:
            self._screen_guard_hwnd = None
            self._screen_guard_prev_wndproc = None
            self._screen_guard_proc = None

    def _set_screensaver_block(self, enabled: bool):
        if enabled:
            self._install_fullscreen_screen_guard()
        else:
            self._remove_fullscreen_screen_guard()

    def _install_fullscreen_keyboard_guard(self):
        if os.name != "nt" or HOOKPROC is None:
            return
        if self.__dict__.get("_keyboard_guard_thread") is not None:
            return

        ready_event = threading.Event()

        def _keyboard_guard_loop():
            hook_handle = None
            keyboard_hook_proc = None
            ctrl_down = False

            try:
                (
                    set_windows_hook,
                    call_next_hook,
                    unhook_windows_hook,
                    peek_message,
                    get_message,
                    translate_message,
                    dispatch_message,
                    _post_thread_message,
                    get_current_thread_id,
                ) = self._get_keyboard_hook_accessors()

                self._keyboard_guard_thread_id = int(get_current_thread_id())

                # Force the thread message queue to exist before installing the low-level hook.
                bootstrap_msg = MSG()
                peek_message(ctypes.byref(bootstrap_msg), None, 0, 0, PM_NOREMOVE)

                def _keyboard_guard_proc(n_code, w_param, l_param):
                    nonlocal ctrl_down, hook_handle

                    if n_code != HC_ACTION:
                        return call_next_hook(hook_handle, n_code, w_param, l_param)

                    message = int(w_param)
                    if message not in (WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP):
                        return call_next_hook(hook_handle, n_code, w_param, l_param)

                    keyboard_data = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    vk_code = int(keyboard_data.vkCode)
                    is_keydown = message in (WM_KEYDOWN, WM_SYSKEYDOWN)
                    is_keyup = message in (WM_KEYUP, WM_SYSKEYUP)

                    if vk_code in (VK_CONTROL, VK_LCONTROL, VK_RCONTROL):
                        if is_keydown:
                            ctrl_down = True
                        elif is_keyup:
                            ctrl_down = False

                    if self._should_block_fullscreen_keyboard_shortcut(
                        vk_code,
                        flags=keyboard_data.flags,
                        ctrl_down=ctrl_down,
                    ):
                        return 1

                    return call_next_hook(hook_handle, n_code, w_param, l_param)

                keyboard_hook_proc = HOOKPROC(_keyboard_guard_proc)
                hook_handle = set_windows_hook(
                    WH_KEYBOARD_LL,
                    keyboard_hook_proc,
                    None,
                    0,
                )
                if not hook_handle:
                    logger.warning("Failed to install fullscreen keyboard guard.")
                    return

                self._keyboard_hook_handle = hook_handle
                self._keyboard_hook_proc = keyboard_hook_proc
                ready_event.set()

                message = MSG()
                while get_message(ctypes.byref(message), None, 0, 0) > 0:
                    translate_message(ctypes.byref(message))
                    dispatch_message(ctypes.byref(message))
            except Exception:
                logger.warning("Failed to install fullscreen keyboard guard.", exc_info=True)
            finally:
                ready_event.set()
                if hook_handle:
                    try:
                        (
                            _set_windows_hook,
                            _call_next_hook,
                            unhook_windows_hook,
                            _peek_message,
                            _get_message,
                            _translate_message,
                            _dispatch_message,
                            _post_thread_message,
                            _get_current_thread_id,
                        ) = self._get_keyboard_hook_accessors()
                        unhook_windows_hook(hook_handle)
                    except Exception:
                        logger.warning("Failed to remove fullscreen keyboard guard.", exc_info=True)
                self._keyboard_hook_handle = None
                self._keyboard_hook_proc = None
                self._keyboard_guard_thread_id = None
                self._keyboard_guard_thread = None

        keyboard_guard_thread = threading.Thread(
            target=_keyboard_guard_loop,
            name="fullscreen-keyboard-guard",
            daemon=True,
        )
        self._keyboard_guard_thread = keyboard_guard_thread
        keyboard_guard_thread.start()
        ready_event.wait(timeout=1.0)

        if self.__dict__.get("_keyboard_hook_handle") is None:
            logger.warning("Fullscreen keyboard guard did not become active.")

    def _remove_fullscreen_keyboard_guard(self):
        keyboard_guard_thread = self.__dict__.get("_keyboard_guard_thread")
        keyboard_guard_thread_id = self.__dict__.get("_keyboard_guard_thread_id")

        if keyboard_guard_thread is None:
            self._keyboard_hook_handle = None
            self._keyboard_hook_proc = None
            self._keyboard_guard_thread_id = None
            self._keyboard_guard_thread = None
            return

        try:
            (
                _set_windows_hook,
                _call_next_hook,
                _unhook_windows_hook,
                _peek_message,
                _get_message,
                _translate_message,
                _dispatch_message,
                post_thread_message,
                _get_current_thread_id,
            ) = self._get_keyboard_hook_accessors()
            if keyboard_guard_thread_id is not None:
                post_thread_message(int(keyboard_guard_thread_id), WM_QUIT, 0, 0)
            keyboard_guard_thread.join(timeout=1.0)
        except Exception:
            logger.warning("Failed to remove fullscreen keyboard guard.", exc_info=True)
        finally:
            self._keyboard_hook_handle = None
            self._keyboard_hook_proc = None
            self._keyboard_guard_thread_id = None
            self._keyboard_guard_thread = None

    def _set_keyboard_shortcut_block(self, enabled: bool):
        if enabled:
            self._install_fullscreen_keyboard_guard()
        else:
            self._remove_fullscreen_keyboard_guard()

    def _set_fullscreen(self, enabled: bool):
        self.update_idletasks()
        if enabled:
            logical_screen_width, logical_screen_height = self._get_logical_screen_size()
            self.overrideredirect(True)
            self.geometry(f"{logical_screen_width}x{logical_screen_height}+0+0")
            self.attributes("-topmost", True)
            self.after(10, lambda: self.attributes("-topmost", False))
            self._set_display_awake(True)
            self._set_screensaver_block(True)
            self._set_keyboard_shortcut_block(True)
        else:
            self._set_keyboard_shortcut_block(False)
            self._set_screensaver_block(False)
            self.overrideredirect(False)
            self.geometry(self._windowed_geometry)
            self.state("zoomed")
            self._set_display_awake(False)

        self._schedule_window_mode_layout_refresh()

    def _exit_fullscreen(self, event=None):
        self._set_fullscreen(False)
        return "break"

    def _toggle_fullscreen(self, event=None):
        is_fullscreen = bool(self.overrideredirect())
        self._set_fullscreen(not is_fullscreen)
        return "break"

    def _set_display_awake(self, enabled: bool):
        if enabled:
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_DISPLAY_REQUIRED | ES_SYSTEM_REQUIRED
            )
        else:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)

    def run(self):
        self.assistant.start()
        self.input_monitor.start()
        try:
            self.mainloop()
        finally:
            self._safe_cleanup_call("status_pulse", self._stop_status_pulse)
            self._safe_cleanup_call("input_monitor", self.input_monitor.stop)
            self._safe_cleanup_call("keyboard_shortcuts", lambda: self._set_keyboard_shortcut_block(False))
            self._safe_cleanup_call("screensaver_block", lambda: self._set_screensaver_block(False))
            self._safe_cleanup_call("display_awake", lambda: self._set_display_awake(False))
            self._safe_cleanup_call("animator", self.animator.destroy)
            self._safe_cleanup_call("config_flush", config.flush)
            self._safe_cleanup_call("assistant_stop", self.assistant.stop)


if __name__ == "__main__":
    from core.assistant import VoiceAssistant

    assistant = VoiceAssistant()
    app = VoiceAssistantUI(assistant)
    app.run()
