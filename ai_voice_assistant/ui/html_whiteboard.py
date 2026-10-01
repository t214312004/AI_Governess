"""Interactive HTML whiteboard hosted by an embedded Microsoft Edge app window."""
from __future__ import annotations

import ctypes
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit


_WINDOW_ENUM_CALLBACK_TYPE = None


def _window_enum_callback_type():
    global _WINDOW_ENUM_CALLBACK_TYPE
    if _WINDOW_ENUM_CALLBACK_TYPE is None:
        _WINDOW_ENUM_CALLBACK_TYPE = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )
    return _WINDOW_ENUM_CALLBACK_TYPE


HTML_AUDIO_BRIDGE = r"""
<script>
(() => {
  'use strict';
  const nativeConnect = window.AudioNode && window.AudioNode.prototype.connect;
  const masters = new Map();
  const mediaVolumes = new WeakMap();
  const forwardedKeys = new Set();
  const forwardedKeyMap = new Map([
    [32, [' ', 'Space']],
    [37, ['ArrowLeft', 'ArrowLeft']],
    [38, ['ArrowUp', 'ArrowUp']],
    [39, ['ArrowRight', 'ArrowRight']],
    [40, ['ArrowDown', 'ArrowDown']],
    [65, ['a', 'KeyA']],
    [68, ['d', 'KeyD']],
    [83, ['s', 'KeyS']],
    [87, ['w', 'KeyW']]
  ]);
  let currentLevel = 1;
  let inputSyncPending = false;
  let lastInputSequence = 0;

  const activationTarget = document.createElement('div');
  activationTarget.id = '__ai_governess_input_activation_target';
  activationTarget.setAttribute('aria-hidden', 'true');
  const activationStyle = {
    position: 'fixed', left: '0', top: '0', width: '4px', height: '4px',
    opacity: '0', zIndex: '2147483647', pointerEvents: 'auto',
    background: 'transparent'
  };
  Object.entries(activationStyle).forEach(([name, value]) => {
    activationTarget.style.setProperty(
      name.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`),
      value,
      'important'
    );
  });
  document.documentElement.appendChild(activationTarget);
  const swallowActivationEvent = (event) => {
    if (event.target !== activationTarget) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    try {
      window.focus();
    } catch (_) {}
  };
  ['pointerdown', 'pointerup', 'mousedown', 'mouseup', 'click'].forEach((eventName) => {
    window.addEventListener(eventName, swallowActivationEvent, true);
  });
  window.addEventListener('pointerdown', (event) => {
    if (event.target === activationTarget) return;
    fetch('/__ai_governess/focus', {
      method: 'POST', cache: 'no-store', keepalive: true
    }).catch(() => {});
  }, true);

  if (nativeConnect) {
    window.AudioNode.prototype.connect = function(destination, ...args) {
      if (window.AudioDestinationNode && destination instanceof window.AudioDestinationNode) {
        const context = destination.context;
        let master = masters.get(context);
        if (!master) {
          master = context.createGain();
          master.gain.value = currentLevel;
          nativeConnect.call(master, destination);
          masters.set(context, master);
        }
        return nativeConnect.call(this, master, ...args);
      }
      return nativeConnect.call(this, destination, ...args);
    };
  }

  function applyMediaVolume(level) {
    document.querySelectorAll('audio, video').forEach((element) => {
      if (!mediaVolumes.has(element)) mediaVolumes.set(element, element.volume);
      element.volume = Math.max(0, Math.min(1, mediaVolumes.get(element) * level));
    });
  }

  window.__aiGovernessSetGameVolume = (rawLevel) => {
    const level = Math.max(0, Math.min(1, Number(rawLevel)));
    if (!Number.isFinite(level)) return;
    currentLevel = level;
    masters.forEach((master, context) => {
      const now = context.currentTime;
      master.gain.cancelScheduledValues(now);
      master.gain.setTargetAtTime(level, now, 0.035);
    });
    applyMediaVolume(level);
  };

  async function syncAudioState() {
    try {
      const response = await fetch('/__ai_governess/audio', { cache: 'no-store' });
      if (response.ok) {
        const state = await response.json();
        window.__aiGovernessSetGameVolume(state.volume);
      }
    } catch (_) {}
    applyMediaVolume(currentLevel);
  }

  function forwardedKeyboardTarget() {
    const active = document.activeElement;
    if (active && active !== document.documentElement) return active;
    return document.body || document.documentElement || document;
  }

  function dispatchForwardedInput(inputEvent) {
    const vkCode = Number(inputEvent.vkCode);
    const mapping = forwardedKeyMap.get(vkCode);
    if (!mapping) return;
    const isDown = inputEvent.type === 'keydown';
    let [key, code] = mapping;
    if (inputEvent.shiftKey && key.length === 1 && key !== ' ') key = key.toUpperCase();
    const forwardedEvent = new KeyboardEvent(inputEvent.type, {
      key,
      code,
      bubbles: true,
      cancelable: true,
      composed: true,
      repeat: Boolean(inputEvent.repeat),
      altKey: Boolean(inputEvent.altKey),
      ctrlKey: Boolean(inputEvent.ctrlKey),
      shiftKey: Boolean(inputEvent.shiftKey),
      metaKey: Boolean(inputEvent.metaKey)
    });
    try {
      Object.defineProperty(forwardedEvent, 'keyCode', { get: () => vkCode });
      Object.defineProperty(forwardedEvent, 'which', { get: () => vkCode });
    } catch (_) {}
    if (isDown) forwardedKeys.add(vkCode);
    else forwardedKeys.delete(vkCode);
    forwardedKeyboardTarget().dispatchEvent(forwardedEvent);
  }
  async function syncForwardedInput() {
    if (inputSyncPending) return;
    inputSyncPending = true;
    try {
      const response = await fetch(
        `/__ai_governess/input?since=${encodeURIComponent(lastInputSequence)}`,
        { cache: 'no-store' }
      );
      if (!response.ok) return;
      const state = await response.json();
      const events = Array.isArray(state.events) ? state.events : [];
      events
        .filter((inputEvent) => Number(inputEvent.sequence) > lastInputSequence)
        .sort((left, right) => Number(left.sequence) - Number(right.sequence))
        .forEach((inputEvent) => {
          dispatchForwardedInput(inputEvent);
          lastInputSequence = Math.max(lastInputSequence, Number(inputEvent.sequence) || 0);
        });

      // Reconcile against the authoritative state in case the bounded event
      // journal rolled over while the renderer was stalled.
      const pressed = new Set(Array.isArray(state.pressed) ? state.pressed : []);
      forwardedKeyMap.forEach(([key, code], vkCode) => {
        const isDown = pressed.has(vkCode);
        const wasDown = forwardedKeys.has(vkCode);
        if (isDown === wasDown) return;
        dispatchForwardedInput({
          type: isDown ? 'keydown' : 'keyup',
          vkCode,
          repeat: false
        });
      });
      lastInputSequence = Math.max(lastInputSequence, Number(state.sequence) || 0);
    } catch (_) {
    } finally {
      inputSyncPending = false;
    }
  }

  syncAudioState();
  syncForwardedInput();
  window.setInterval(syncAudioState, 100);
  window.setInterval(syncForwardedInput, 30);
})();
</script>
"""


def inject_audio_bridge(html_text: str) -> str:
    """Insert the audio bridge before application scripts start running."""
    head_match = re.search(r"<head\b[^>]*>", html_text, flags=re.IGNORECASE)
    if head_match:
        return html_text[: head_match.end()] + HTML_AUDIO_BRIDGE + html_text[head_match.end() :]
    html_match = re.search(r"<html\b[^>]*>", html_text, flags=re.IGNORECASE)
    if html_match:
        return html_text[: html_match.end()] + HTML_AUDIO_BRIDGE + html_text[html_match.end() :]
    doctype_match = re.match(r"\s*<!doctype\b[^>]*>", html_text, flags=re.IGNORECASE)
    if doctype_match:
        return html_text[: doctype_match.end()] + HTML_AUDIO_BRIDGE + html_text[doctype_match.end() :]
    return HTML_AUDIO_BRIDGE + html_text


class _WhiteboardHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address,
        source_root: Path,
        entry_path: Path,
        volume_getter,
        input_getter,
        keyboard_capture_notifier,
    ):
        self.source_root = source_root.resolve()
        self.entry_path = entry_path.resolve()
        self.volume_getter = volume_getter
        self.input_getter = input_getter
        self.keyboard_capture_notifier = keyboard_capture_notifier
        super().__init__(server_address, _WhiteboardRequestHandler)

    def handle_error(self, _request, _client_address):
        # Edge can cancel in-flight polling requests while its child window closes.
        return


class _WhiteboardRequestHandler(BaseHTTPRequestHandler):
    server_version = "AIGovernessWhiteboard/1.0"

    def log_message(self, _format, *_args):
        return

    def _send_headers(self, status: int, content_type: str, content_length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self' data: blob:; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; media-src 'self' data: blob:; "
            "font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; "
            "frame-src 'self'; object-src 'none'; base-uri 'self'; form-action 'none'",
        )
        self.end_headers()

    def do_GET(self):
        parsed_url = urlsplit(self.path)
        request_path = unquote(parsed_url.path)
        if request_path == "/__ai_governess/audio":
            body = json.dumps({"volume": self.server.volume_getter()}).encode("utf-8")
            self._send_headers(200, "application/json; charset=utf-8", len(body))
            self.wfile.write(body)
            return
        if request_path == "/__ai_governess/input":
            query = parse_qs(parsed_url.query)
            try:
                since = max(0, int((query.get("since") or [0])[0]))
            except (TypeError, ValueError):
                since = 0
            body = json.dumps(self.server.input_getter(since)).encode("utf-8")
            self._send_headers(200, "application/json; charset=utf-8", len(body))
            self.wfile.write(body)
            return

        # Windows treats backslashes, drive prefixes, and UNC paths as filesystem
        # separators even though they are not valid URL path syntax. Reject them
        # before constructing a Path so a request can never trigger a network or
        # drive-path lookup outside the app directory.
        if "\\" in request_path or ":" in request_path or "\0" in request_path:
            self.send_error(403)
            return

        if request_path in {"", "/"}:
            candidate = self.server.entry_path
        else:
            candidate = (self.server.source_root / request_path.lstrip("/")).resolve()
        try:
            candidate.relative_to(self.server.source_root)
        except ValueError:
            self.send_error(403)
            return
        if not candidate.is_file():
            self.send_error(404)
            return

        try:
            if candidate.suffix.lower() in {".html", ".htm"}:
                source = candidate.read_text(encoding="utf-8-sig")
                body = inject_audio_bridge(source).encode("utf-8")
                content_type = "text/html; charset=utf-8"
            else:
                body = candidate.read_bytes()
                content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        except (OSError, UnicodeError):
            self.send_error(500)
            return
        self._send_headers(200, content_type, len(body))
        self.wfile.write(body)

    def do_POST(self):
        request_path = unquote(urlsplit(self.path).path)
        if request_path != "/__ai_governess/focus":
            self.send_error(404)
            return
        self.server.keyboard_capture_notifier(True)
        self._send_headers(204, "text/plain; charset=utf-8", 0)


class HtmlWhiteboardRenderer:
    """Owns a restricted local web server and an Edge child window."""

    _ATTACH_TIMEOUT_SECONDS = 8.0
    _FORWARDED_KEY_HOLD_SECONDS = 0.08
    _MAX_INPUT_EVENTS = 512

    def __init__(self, state_dir: str | os.PathLike[str], *, duck_volume: float = 0.2):
        self.state_dir = Path(state_dir).resolve()
        self.profile_root = self.state_dir / "html_profile"
        self.profile_root.mkdir(parents=True, exist_ok=True)
        self.duck_volume = self._clamp_volume(duck_volume)
        self._ducked = False
        self._user_muted = False
        self._keyboard_capture_requested = False
        self._forwarded_keys = set()
        self._forwarded_key_tokens = {}
        self._input_events = []
        self._input_sequence = 0
        self._server = None
        self._server_thread = None
        self._process = None
        self._hwnd = None
        self._source_path = None
        self._parent_hwnd = None
        self._size = (1, 1)
        self._lock = threading.RLock()
        self._generation = 0
        self.last_error = None

    @staticmethod
    def _clamp_volume(value) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = 0.2
        return max(0.0, min(1.0, number))

    @property
    def is_active(self) -> bool:
        process = self._process
        return bool(process is not None and process.poll() is None)

    @property
    def is_attached(self) -> bool:
        return bool(self._hwnd)

    @property
    def is_muted(self) -> bool:
        return self._user_muted

    def _effective_volume(self) -> float:
        if self._user_muted:
            return 0.0
        return self.duck_volume if self._ducked else 1.0

    def set_ducked(self, ducked: bool) -> None:
        self._ducked = bool(ducked)

    def set_muted(self, muted: bool) -> None:
        self._user_muted = bool(muted)

    def toggle_muted(self) -> bool:
        self.set_muted(not self._user_muted)
        return self._user_muted

    @property
    def keyboard_capture_requested(self) -> bool:
        with self._lock:
            return self._keyboard_capture_requested

    def set_keyboard_capture(self, enabled: bool) -> None:
        with self._lock:
            self._keyboard_capture_requested = bool(enabled)
            if not self._keyboard_capture_requested:
                self._forwarded_keys.clear()
                self._forwarded_key_tokens.clear()

    def input_state(self, since: int = 0) -> dict[str, object]:
        with self._lock:
            try:
                after_sequence = max(0, int(since))
            except (TypeError, ValueError):
                after_sequence = 0
            return {
                "pressed": sorted(self._forwarded_keys),
                "events": [
                    dict(input_event)
                    for input_event in self._input_events
                    if input_event["sequence"] > after_sequence
                ],
                "sequence": self._input_sequence,
            }

    def _record_forwarded_key_event_locked(
        self,
        vk_code: int,
        *,
        is_keydown: bool,
        repeat: bool = False,
        alt_down: bool = False,
        ctrl_down: bool = False,
        shift_down: bool = False,
    ) -> None:
        vk_code = int(vk_code)
        if is_keydown:
            self._forwarded_keys.add(vk_code)
        else:
            self._forwarded_keys.discard(vk_code)
        self._input_sequence += 1
        self._input_events.append(
            {
                "sequence": self._input_sequence,
                "type": "keydown" if is_keydown else "keyup",
                "vkCode": vk_code,
                "repeat": bool(repeat),
                "altKey": bool(alt_down),
                "ctrlKey": bool(ctrl_down),
                "shiftKey": bool(shift_down),
                "metaKey": False,
            }
        )
        if len(self._input_events) > self._MAX_INPUT_EVENTS:
            del self._input_events[: -self._MAX_INPUT_EVENTS]

    def set_forwarded_key_state(self, vk_code: int, is_keydown: bool) -> bool:
        with self._lock:
            if not self._keyboard_capture_requested or self._server is None:
                return False
            vk_code = int(vk_code)
            was_down = vk_code in self._forwarded_keys
            if not is_keydown:
                self._forwarded_key_tokens.pop(vk_code, None)
            if was_down != bool(is_keydown):
                self._record_forwarded_key_event_locked(vk_code, is_keydown=bool(is_keydown))
            return True

    @staticmethod
    def _find_edge_executable() -> Path | None:
        candidates = [
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _preferred_port(source_path: Path) -> int:
        digest = hashlib.sha256(str(source_path).casefold().encode("utf-8")).digest()
        return 18000 + int.from_bytes(digest[:2], "big") % 1000

    def _start_server(self, source_path: Path) -> None:
        preferred_port = self._preferred_port(source_path)
        try:
            server = _WhiteboardHTTPServer(
                ("127.0.0.1", preferred_port),
                source_path.parent,
                source_path,
                self._effective_volume,
                self.input_state,
                self.set_keyboard_capture,
            )
        except OSError:
            server = _WhiteboardHTTPServer(
                ("127.0.0.1", 0),
                source_path.parent,
                source_path,
                self._effective_volume,
                self.input_state,
                self.set_keyboard_capture,
            )
        thread = threading.Thread(target=server.serve_forever, name="html-whiteboard-server", daemon=True)
        thread.start()
        self._server = server
        self._server_thread = thread

    def show(self, parent_hwnd: int, source_path: str | os.PathLike[str], width: int, height: int) -> None:
        source = Path(source_path).resolve()
        with self._lock:
            same_source = source == self._source_path and self._server is not None
            self._stop_browser_locked()
            if not same_source:
                self._stop_server_locked()
                self._start_server(source)
                self._source_path = source
            self._parent_hwnd = int(parent_hwnd)
            self._size = (max(1, int(width)), max(1, int(height)))
            self.last_error = None
            self._generation += 1
            generation = self._generation
            self._launch_browser_locked(generation)

    def reload(self) -> None:
        with self._lock:
            if self._source_path is None or self._server is None or self._parent_hwnd is None:
                return
            self._stop_browser_locked()
            self._generation += 1
            self._launch_browser_locked(self._generation)

    def _launch_browser_locked(self, generation: int) -> None:
        edge_path = self._find_edge_executable()
        if edge_path is None:
            self.last_error = "找不到 Microsoft Edge，無法顯示 HTML 白板。"
            return
        port = int(self._server.server_address[1])
        command = [
            str(edge_path),
            f"--user-data-dir={self.profile_root}",
            f"--app=http://127.0.0.1:{port}/",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-sync",
            "--disable-translate",
            "--disable-session-crashed-bubble",
            "--autoplay-policy=no-user-gesture-required",
            "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
        ]
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "CREATE_NO_WINDOW", 0
        )
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except OSError as exc:
            self.last_error = f"啟動 Microsoft Edge 失敗：{exc}"
            self._process = None
            return
        threading.Thread(
            target=self._attach_browser_window,
            args=(self._process.pid, generation),
            name="html-whiteboard-attach",
            daemon=True,
        ).start()

    @staticmethod
    def _windows_api():
        user32 = ctypes.windll.user32
        enum_callback_type = _window_enum_callback_type()
        user32.EnumWindows.argtypes = [enum_callback_type, ctypes.c_void_p]
        user32.EnumWindows.restype = ctypes.c_bool
        user32.EnumChildWindows.argtypes = [ctypes.c_void_p, enum_callback_type, ctypes.c_void_p]
        user32.EnumChildWindows.restype = ctypes.c_bool
        user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
        user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
        user32.IsWindowVisible.restype = ctypes.c_bool
        user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        user32.GetClassNameW.restype = ctypes.c_int
        user32.SetParent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.SetParent.restype = ctypes.c_void_p
        user32.SetFocus.argtypes = [ctypes.c_void_p]
        user32.SetFocus.restype = ctypes.c_void_p
        user32.GetFocus.argtypes = []
        user32.GetFocus.restype = ctypes.c_void_p
        user32.IsChild.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.IsChild.restype = ctypes.c_bool
        user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.SendMessageW.restype = ctypes.c_ssize_t
        user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowPos.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        user32.SetWindowPos.restype = ctypes.c_bool
        user32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_bool]
        user32.AttachThreadInput.restype = ctypes.c_bool
        user32.MapVirtualKeyW.argtypes = [ctypes.c_uint, ctypes.c_uint]
        user32.MapVirtualKeyW.restype = ctypes.c_uint
        user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.PostMessageW.restype = ctypes.c_bool
        return user32

    def _find_window_for_pid(self, process_id: int) -> int | None:
        if os.name != "nt":
            return None
        user32 = self._windows_api()
        found = []
        callback_type = _window_enum_callback_type()

        @callback_type
        def enum_callback(hwnd, _lparam):
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == process_id and user32.IsWindowVisible(hwnd):
                found.append(int(hwnd))
                return False
            return True

        user32.EnumWindows(enum_callback, 0)
        return found[0] if found else None

    def _find_input_window(self, parent_hwnd: int) -> int | None:
        if os.name != "nt":
            return None
        user32 = self._windows_api()
        found = []
        callback_type = _window_enum_callback_type()

        @callback_type
        def enum_callback(hwnd, _lparam):
            class_name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_name, len(class_name))
            if class_name.value == "Chrome_RenderWidgetHostHWND" and user32.IsWindowVisible(hwnd):
                found.append(int(hwnd))
                return False
            return True

        user32.EnumChildWindows(parent_hwnd, enum_callback, 0)
        return found[0] if found else None

    def _attach_browser_window(self, process_id: int, generation: int) -> None:
        deadline = time.monotonic() + self._ATTACH_TIMEOUT_SECONDS
        hwnd = None
        while time.monotonic() < deadline:
            with self._lock:
                if generation != self._generation or self._process is None:
                    return
                if self._process.poll() is not None:
                    break
            hwnd = self._find_window_for_pid(process_id)
            if hwnd:
                break
            time.sleep(0.05)
        if not hwnd:
            with self._lock:
                if generation == self._generation:
                    self.last_error = "Microsoft Edge 視窗啟動逾時。"
            return

        with self._lock:
            if generation != self._generation or self._parent_hwnd is None:
                return
            try:
                self._embed_window_locked(hwnd)
                self._hwnd = hwnd
            except Exception as exc:
                self.last_error = f"嵌入 HTML 白板失敗：{exc}"

    def _embed_window_locked(self, hwnd: int) -> None:
        user32 = self._windows_api()
        gwl_style = -16
        ws_child = 0x40000000
        ws_visible = 0x10000000
        ws_caption = 0x00C00000
        ws_thickframe = 0x00040000
        ws_minimizebox = 0x00020000
        ws_maximizebox = 0x00010000
        ws_sysmenu = 0x00080000
        ws_popup = 0x80000000
        ws_tabstop = 0x00010000
        swp_framechanged = 0x0020
        swp_showwindow = 0x0040
        style = user32.GetWindowLongPtrW(hwnd, gwl_style)
        style &= ~(ws_caption | ws_thickframe | ws_minimizebox | ws_maximizebox | ws_sysmenu | ws_popup)
        style |= ws_child | ws_visible | ws_tabstop
        user32.SetWindowLongPtrW(hwnd, gwl_style, style)
        user32.SetParent(hwnd, self._parent_hwnd)
        width, height = self._size
        if not user32.SetWindowPos(hwnd, 0, 0, 0, width, height, swp_framechanged | swp_showwindow):
            raise ctypes.WinError()

    def resize(self, parent_hwnd: int, width: int, height: int) -> None:
        with self._lock:
            self._parent_hwnd = int(parent_hwnd)
            self._size = (max(1, int(width)), max(1, int(height)))
            if not self._hwnd or os.name != "nt":
                return
            user32 = self._windows_api()
            user32.SetParent(self._hwnd, self._parent_hwnd)
            user32.SetWindowPos(self._hwnd, 0, 0, 0, self._size[0], self._size[1], 0x0040)

    def focus(self) -> bool:
        with self._lock:
            if not self._hwnd or os.name != "nt":
                return False
            try:
                user32 = self._windows_api()
                kernel32 = getattr(ctypes.windll, "kernel32", None)
                input_hwnd = self._find_input_window(self._hwnd)
                target_hwnd = input_hwnd or self._hwnd

                cur_tid = kernel32.GetCurrentThreadId() if kernel32 else 0
                pid = ctypes.c_ulong()
                target_tid = user32.GetWindowThreadProcessId(target_hwnd, ctypes.byref(pid))

                attached = False
                if cur_tid and target_tid and cur_tid != target_tid:
                    attached = bool(user32.AttachThreadInput(cur_tid, target_tid, True))

                try:
                    user32.SetFocus(self._hwnd)
                    if input_hwnd:
                        user32.SetFocus(input_hwnd)
                    user32.SendMessageW(self._hwnd, 0x0006, 1, 0)
                    activation_point = (1 << 16) | 1
                    user32.SendMessageW(target_hwnd, 0x0201, 0x0001, activation_point)
                    user32.SendMessageW(target_hwnd, 0x0202, 0, activation_point)
                    if input_hwnd:
                        user32.SetFocus(input_hwnd)

                    focused_hwnd = user32.GetFocus()
                    focused = bool(
                        input_hwnd
                        and focused_hwnd
                        and (
                            int(focused_hwnd) == int(input_hwnd)
                            or user32.IsChild(input_hwnd, focused_hwnd)
                        )
                    )
                    if focused:
                        self._keyboard_capture_requested = True
                    return focused
                finally:
                    if attached:
                        user32.AttachThreadInput(cur_tid, target_tid, False)
            except Exception:
                return False

    def forward_key(self, vk_code: int) -> bool:
        vk_code = int(vk_code)
        with self._lock:
            if not self._keyboard_capture_requested or self._server is None:
                return False
            token = int(self._forwarded_key_tokens.get(vk_code, 0)) + 1
            self._forwarded_key_tokens[vk_code] = token
            self._record_forwarded_key_event_locked(
                vk_code,
                is_keydown=True,
                repeat=vk_code in self._forwarded_keys,
            )
        timer = threading.Timer(
            self._FORWARDED_KEY_HOLD_SECONDS,
            self._release_forwarded_key,
            args=(vk_code, token),
        )
        timer.daemon = True
        timer.start()
        return True

    def _release_forwarded_key(self, vk_code: int, token: int) -> None:
        with self._lock:
            if self._forwarded_key_tokens.get(vk_code) != token:
                return
            self._forwarded_key_tokens.pop(vk_code, None)
            if not self._keyboard_capture_requested or self._server is None:
                return
            self._record_forwarded_key_event_locked(vk_code, is_keydown=False)

    def forward_key_event(
        self,
        vk_code: int,
        *,
        is_keydown: bool,
        was_down: bool = False,
        alt_down: bool = False,
        ctrl_down: bool = False,
        shift_down: bool = False,
    ) -> bool:
        with self._lock:
            if not self._keyboard_capture_requested or self._server is None:
                return False
            vk_code = int(vk_code)
            if not is_keydown:
                # A native keyup can follow a Tk fallback keydown after focus
                # moves into Edge. Invalidate the fallback timer so it cannot
                # emit a duplicate keyup later.
                self._forwarded_key_tokens.pop(vk_code, None)
            self._record_forwarded_key_event_locked(
                vk_code,
                is_keydown=bool(is_keydown),
                repeat=bool(is_keydown and was_down),
                alt_down=alt_down,
                ctrl_down=ctrl_down,
                shift_down=shift_down,
            )
            return True

    def _stop_browser_locked(self) -> None:
        self._generation += 1
        hwnd = self._hwnd
        process = self._process
        self._hwnd = None
        self._process = None
        self._keyboard_capture_requested = False
        self._forwarded_keys.clear()
        self._forwarded_key_tokens.clear()
        self._input_events.clear()
        self._input_sequence = 0
        if hwnd and os.name == "nt":
            try:
                ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
            except Exception:
                pass
        if process is not None and process.poll() is None:
            try:
                process.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    process.kill()

    def _stop_server_locked(self) -> None:
        server = self._server
        thread = self._server_thread
        self._server = None
        self._server_thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def stop(self) -> None:
        with self._lock:
            self._stop_browser_locked()
            self._stop_server_locked()
        self._source_path = None
        self._parent_hwnd = None
        self._keyboard_capture_requested = False
        self._forwarded_keys.clear()
