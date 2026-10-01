from __future__ import annotations

import json
import asyncio
import subprocess
import threading
from unittest.mock import MagicMock, call
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import aiohttp

import ui.html_whiteboard as html_whiteboard
from ui.html_whiteboard import HtmlWhiteboardRenderer, inject_audio_bridge


def test_audio_bridge_is_injected_before_game_script():
    source = "<html><head><script>window.gameStarted = true;</script></head></html>"

    rendered = inject_audio_bridge(source)

    assert "__aiGovernessSetGameVolume" in rendered
    assert rendered.index("__aiGovernessSetGameVolume") < rendered.index("window.gameStarted")
    assert "__ai_governess_input_activation_target" in rendered
    assert rendered.index("__ai_governess_input_activation_target") < rendered.index("window.gameStarted")


def test_audio_bridge_preserves_doctype_when_document_has_no_head():
    source = "<!doctype html><html><body><script>startGame()</script></body></html>"

    rendered = inject_audio_bridge(source)

    assert rendered.startswith("<!doctype html><html>")
    assert rendered.index("__aiGovernessSetGameVolume") < rendered.index("startGame()")


@pytest.mark.asyncio
async def test_input_bridge_preserves_fast_tap_repeat_and_dom_bubbling_in_edge(tmp_path):
    edge_path = HtmlWhiteboardRenderer._find_edge_executable()
    if edge_path is None:
        pytest.skip("Microsoft Edge is not installed")
    app_dir = tmp_path / "apps" / "keyboard-test"
    app_dir.mkdir(parents=True)
    source = """<!doctype html><html><body>
    <input id="field" autofocus><pre id="out"></pre><script>
    const seen = [];
    let bodyEvents = 0;
    let windowEvents = 0;
    document.addEventListener('keydown', (event) => seen.push({
      type: event.type, key: event.key, repeat: event.repeat,
      target: event.target.id, shiftKey: event.shiftKey
    }));
    document.addEventListener('keyup', (event) => seen.push({
      type: event.type, key: event.key, repeat: event.repeat,
      target: event.target.id, shiftKey: event.shiftKey
    }));
    document.body.addEventListener('keydown', () => { bodyEvents += 1; });
    document.body.addEventListener('keyup', () => { bodyEvents += 1; });
    window.addEventListener('keydown', () => { windowEvents += 1; });
    window.addEventListener('keyup', () => { windowEvents += 1; });
    field.focus();
    setTimeout(() => {
      out.textContent = JSON.stringify({
        seen, bodyEvents, windowEvents, active: document.activeElement.id
      });
    }, 250);
    </script></body></html>"""
    index_path = app_dir / "index.html"
    index_path.write_text(source, encoding="utf-8")
    renderer = HtmlWhiteboardRenderer(tmp_path / "state")
    renderer._start_server(index_path)
    renderer.set_keyboard_capture(True)
    renderer.forward_key_event(0x26, is_keydown=True, was_down=False)
    renderer.forward_key_event(0x26, is_keydown=True, was_down=True)
    renderer.forward_key_event(0x26, is_keydown=False, was_down=True)
    renderer.forward_key_event(0x20, is_keydown=True, was_down=False)
    renderer.forward_key_event(0x20, is_keydown=False, was_down=True)
    port = renderer._server.server_address[1]

    try:
        process = subprocess.Popen(
            [
                str(edge_path),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--disable-extensions",
                f"--user-data-dir={tmp_path / 'edge-profile'}",
                "--remote-debugging-port=0",
                "about:blank",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        # Windows Edge may hand off to another process, losing --dump-dom's
        # stdout. CDP reads the actual page and closes the isolated browser.
        active_port_file = tmp_path / "edge-profile" / "DevToolsActivePort"
        async with asyncio.timeout(20):
            while not active_port_file.is_file():
                await asyncio.sleep(0.05)
            debug_port, browser_path = active_port_file.read_text().splitlines()[:2]
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(f"http://127.0.0.1:{debug_port}{browser_path}") as ws:
                    request_id = 0

                    async def command(method, params=None, session_id=None):
                        nonlocal request_id
                        request_id += 1
                        payload = {"id": request_id, "method": method, "params": params or {}}
                        if session_id:
                            payload["sessionId"] = session_id
                        await ws.send_json(payload)
                        while True:
                            response = await ws.receive_json()
                            if response.get("id") == request_id:
                                assert "error" not in response, response
                                return response.get("result", {})

                    try:
                        target = await command("Target.createTarget", {"url": f"http://127.0.0.1:{port}/"})
                        attached = await command("Target.attachToTarget", {
                            "targetId": target["targetId"], "flatten": True,
                        })
                        page_session = attached["sessionId"]
                        while True:
                            result = await command("Runtime.evaluate", {
                                "expression": "document.getElementById('out')?.textContent",
                                "returnByValue": True,
                            }, page_session)
                            assert "exceptionDetails" not in result, result
                            rendered_result = result.get("result", {}).get("value")
                            if rendered_result:
                                break
                            await asyncio.sleep(0.05)
                    finally:
                        await command("Browser.close")
        await asyncio.to_thread(process.wait, timeout=5)
    finally:
        renderer.stop()

    expected_events = (
        '"seen":[{"type":"keydown","key":"ArrowUp","repeat":false,"target":"field","shiftKey":false},'
        '{"type":"keydown","key":"ArrowUp","repeat":true,"target":"field","shiftKey":false},'
        '{"type":"keyup","key":"ArrowUp","repeat":false,"target":"field","shiftKey":false},'
        '{"type":"keydown","key":" ","repeat":false,"target":"field","shiftKey":false},'
        '{"type":"keyup","key":" ","repeat":false,"target":"field","shiftKey":false}]'
    )
    assert expected_events in rendered_result
    assert '"bodyEvents":5' in rendered_result
    assert '"windowEvents":5' in rendered_result
    assert '"active":"field"' in rendered_result


def test_focus_activates_chromium_render_widget_through_bridge_target(monkeypatch, tmp_path):
    renderer = HtmlWhiteboardRenderer(tmp_path / "state")
    renderer._hwnd = 101
    renderer._lock = threading.RLock()
    user32 = MagicMock()
    user32.GetWindowThreadProcessId.return_value = 555
    user32.GetFocus.return_value = 202
    renderer._windows_api = MagicMock(return_value=user32)
    renderer._find_input_window = MagicMock(return_value=202)
    monkeypatch.setattr(html_whiteboard.os, "name", "nt")

    assert renderer.focus() is True

    activation_point = (1 << 16) | 1
    assert user32.SetFocus.call_args_list == [call(101), call(202), call(202)]
    assert call(101, 0x0006, 1, 0) in user32.SendMessageW.call_args_list
    assert call(202, 0x0201, 0x0001, activation_point) in user32.SendMessageW.call_args_list
    assert call(202, 0x0202, 0, activation_point) in user32.SendMessageW.call_args_list
    assert user32.AttachThreadInput.call_count == 2
    assert user32.AttachThreadInput.call_args_list[0][0][2] is True
    assert user32.AttachThreadInput.call_args_list[1][0][2] is False

    assert renderer.focus() is True
    assert user32.AttachThreadInput.call_count == 4


def test_embed_window_removes_popup_and_adds_tabstop(monkeypatch, tmp_path):
    renderer = HtmlWhiteboardRenderer(tmp_path / "state")
    renderer._parent_hwnd = 999
    renderer._size = (800, 600)
    user32 = MagicMock()
    # Simulate initial style with WS_POPUP (0x80000000) and WS_CAPTION (0x00C00000)
    user32.GetWindowLongPtrW.return_value = 0x80C00000
    user32.SetWindowPos.return_value = True
    renderer._windows_api = MagicMock(return_value=user32)
    monkeypatch.setattr(html_whiteboard.os, "name", "nt")

    renderer._embed_window_locked(101)

    new_style = user32.SetWindowLongPtrW.call_args[0][2]
    ws_popup = 0x80000000
    ws_child = 0x40000000
    ws_tabstop = 0x00010000
    ws_visible = 0x10000000
    assert not (new_style & ws_popup)
    assert bool(new_style & ws_child)
    assert bool(new_style & ws_tabstop)
    assert bool(new_style & ws_visible)
    user32.SetParent.assert_called_once_with(101, 999)


def test_forward_key_holds_key_before_posting_keyup(monkeypatch, tmp_path):
    renderer = HtmlWhiteboardRenderer(tmp_path / "state")
    renderer._hwnd = 101
    renderer._server = object()
    renderer.set_keyboard_capture(True)
    renderer._lock = threading.RLock()
    timers = []

    class FakeTimer:
        def __init__(self, interval, callback, args):
            self.interval = interval
            self.callback = callback
            self.args = args
            self.daemon = False
            self.started = False
            timers.append(self)

        def start(self):
            self.started = True

    monkeypatch.setattr(html_whiteboard.threading, "Timer", FakeTimer)

    assert renderer.forward_key(0x26) is True

    down_state = renderer.input_state()
    assert down_state["pressed"] == [0x26]
    assert [(event["type"], event["vkCode"], event["repeat"]) for event in down_state["events"]] == [
        ("keydown", 0x26, False)
    ]
    assert len(timers) == 1
    assert timers[0].interval == renderer._FORWARDED_KEY_HOLD_SECONDS
    assert timers[0].daemon is True
    assert timers[0].started is True

    timers[0].callback(*timers[0].args)

    released_state = renderer.input_state(since=down_state["sequence"])
    assert released_state["pressed"] == []
    assert [(event["type"], event["vkCode"]) for event in released_state["events"]] == [
        ("keyup", 0x26)
    ]


def test_forward_key_event_preserves_down_and_up_state(tmp_path):
    renderer = HtmlWhiteboardRenderer(tmp_path / "state")
    renderer._hwnd = 101
    renderer._server = object()
    renderer.set_keyboard_capture(True)

    assert renderer.forward_key_event(0x25, is_keydown=True, was_down=False) is True
    assert renderer.forward_key_event(
        0x25,
        is_keydown=True,
        was_down=True,
        shift_down=True,
    ) is True
    assert renderer.forward_key_event(0x25, is_keydown=False, was_down=True) is True

    state = renderer.input_state()
    assert state["pressed"] == []
    assert [(event["type"], event["repeat"]) for event in state["events"]] == [
        ("keydown", False),
        ("keydown", True),
        ("keyup", False),
    ]
    assert state["events"][1]["shiftKey"] is True

    acknowledged = renderer.input_state(since=state["sequence"])
    assert acknowledged["events"] == []
    assert acknowledged["pressed"] == []


def test_native_keyup_invalidates_pending_tk_fallback_release(monkeypatch, tmp_path):
    renderer = HtmlWhiteboardRenderer(tmp_path / "state")
    renderer._server = object()
    renderer.set_keyboard_capture(True)
    timers = []

    class FakeTimer:
        def __init__(self, _interval, callback, args):
            self.callback = callback
            self.args = args
            self.daemon = False
            timers.append(self)

        def start(self):
            return None

    monkeypatch.setattr(html_whiteboard.threading, "Timer", FakeTimer)

    assert renderer.forward_key(0x20) is True
    assert renderer.forward_key_event(0x20, is_keydown=False, was_down=False) is True
    sequence_after_native_keyup = renderer.input_state()["sequence"]

    timers[0].callback(*timers[0].args)

    state = renderer.input_state()
    assert state["sequence"] == sequence_after_native_keyup
    assert [event["type"] for event in state["events"]] == ["keydown", "keyup"]


def test_html_server_serves_only_app_folder_and_reports_ducking(tmp_path):
    app_dir = tmp_path / "apps" / "rolling_ball"
    app_dir.mkdir(parents=True)
    index_path = app_dir / "index.html"
    index_path.write_text("<!doctype html><canvas id='game'></canvas>", encoding="utf-8")
    secret_path = tmp_path / "secret.txt"
    secret_path.write_text("secret", encoding="utf-8")
    renderer = HtmlWhiteboardRenderer(tmp_path / "state", duck_volume=0.25)
    renderer._start_server(index_path)
    port = renderer._server.server_address[1]

    try:
        with urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
            page = response.read().decode("utf-8")
            assert "__aiGovernessSetGameVolume" in page
            assert "/__ai_governess/input" in page
            assert "connect-src 'self'" in response.headers["Content-Security-Policy"]

        renderer.set_ducked(True)
        with urlopen(f"http://127.0.0.1:{port}/__ai_governess/audio", timeout=2) as response:
            assert json.load(response) == {"volume": 0.25}

        renderer.set_muted(True)
        with urlopen(f"http://127.0.0.1:{port}/__ai_governess/audio", timeout=2) as response:
            assert json.load(response) == {"volume": 0.0}

        request = Request(
            f"http://127.0.0.1:{port}/__ai_governess/focus",
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            assert response.status == 204
        assert renderer.keyboard_capture_requested is True

        assert renderer.set_forwarded_key_state(0x25, True) is True
        with urlopen(f"http://127.0.0.1:{port}/__ai_governess/input", timeout=2) as response:
            input_state = json.load(response)
        assert input_state["pressed"] == [0x25]
        assert input_state["events"][0]["type"] == "keydown"
        assert input_state["events"][0]["vkCode"] == 0x25
        sequence = input_state["sequence"]

        renderer.set_forwarded_key_state(0x25, False)
        with urlopen(
            f"http://127.0.0.1:{port}/__ai_governess/input?since={sequence}", timeout=2
        ) as response:
            delta = json.load(response)
        assert delta["pressed"] == []
        assert [(event["type"], event["vkCode"]) for event in delta["events"]] == [
            ("keyup", 0x25)
        ]

        with pytest.raises(HTTPError) as error:
            urlopen(f"http://127.0.0.1:{port}/%2e%2e/%2e%2e/secret.txt", timeout=2)
        assert error.value.code == 403

        with pytest.raises(HTTPError) as error:
            urlopen(f"http://127.0.0.1:{port}/%5c%5cserver%5cshare", timeout=2)
        assert error.value.code == 403
    finally:
        renderer.stop()
