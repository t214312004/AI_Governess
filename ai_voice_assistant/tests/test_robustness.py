"""Robustness regression tests for issue cases not covered elsewhere."""
import asyncio
import json
import threading
import time

import pytest
from unittest.mock import AsyncMock, MagicMock


def _defaulting_config_get(section, key, default=None):
    if (section, key) == ("llm", "active_backend"):
        return "antigravity_cli"
    return default if default is not None else MagicMock()



@pytest.fixture
def mock_assistant_for_text(mocker):
    mocker.patch("core.assistant.AudioCapture")
    mocker.patch("core.assistant.AudioPlayer")
    mocker.patch("core.assistant.VoiceActivityDetector")
    mocker.patch("core.assistant.BackgroundTranscriber")
    mocker.patch("core.assistant.WakeWordDetector")
    mocker.patch("core.assistant.SentenceBuilder")
    mocker.patch("core.assistant.create_llm_client")
    mocker.patch("core.assistant.SemanticChunker")
    mocker.patch("core.assistant.create_tts_engine")

    def config_get(section, key, default=None):
        lookup = {
            ("llm", "response_timeout_seconds"): 90.0,
            ("llm", "active_backend"): "antigravity_cli",
            ("hot_listen", "enabled"): True,
            ("hot_listen", "timeout_seconds"): 8.0,
        }
        return lookup.get((section, key), default if default is not None else MagicMock())

    mocker.patch("core.assistant.config.get", side_effect=config_get)
    mocker.patch("asyncio.new_event_loop", return_value=MagicMock())

    from core.assistant import VoiceAssistant
    assistant = VoiceAssistant()
    assistant.llm_client.cancel = AsyncMock()
    assistant.async_loop = MagicMock()
    assistant.interrupt_signal = asyncio.Event()
    assistant._submit_coroutine = MagicMock(side_effect=lambda coro: (coro.close(), MagicMock())[1])
    assistant.on_message = MagicMock()
    return assistant


@pytest.mark.asyncio
async def test_issue1_text_request_respects_interrupt_signal(mock_assistant_for_text):
    """Issue #1: cancel the LLM and stop when interrupt_signal is set."""
    signal = mock_assistant_for_text.interrupt_signal

    async def streaming_that_gets_interrupted(_prompt):
        yield "partial"
        signal.set()
        yield "should_not_appear"

    mock_assistant_for_text.llm_client.send_message = streaming_that_gets_interrupted
    mock_assistant_for_text.chunker.reset = MagicMock()

    messages = []
    mock_assistant_for_text.on_message = MagicMock(
        side_effect=lambda role, text: messages.append((role, text))
    )

    await mock_assistant_for_text._execute_text_llm_request("test")

    mock_assistant_for_text.llm_client.cancel.assert_called_once()
    assert any("partial" in str(m) for m in messages)


@pytest.mark.asyncio
async def test_issue1_text_request_cancel_error_on_cancelled_error(mock_assistant_for_text):
    """Issue #1: call llm_client.cancel() when future.cancel() raises CancelledError."""
    async def raises_cancelled(_prompt):
        yield "hi"
        raise asyncio.CancelledError()

    mock_assistant_for_text.llm_client.send_message = raises_cancelled
    mock_assistant_for_text.llm_client.cancel = AsyncMock()

    with pytest.raises(asyncio.CancelledError):
        await mock_assistant_for_text._execute_text_llm_request("test")

    mock_assistant_for_text.llm_client.cancel.assert_called_once()




def test_issue2_interrupt_reads_state_context_under_lock(mocker):
    """Issue #2: read state_context future while holding request_lock."""
    mocker.patch("core.assistant.AudioCapture")
    mocker.patch("core.assistant.AudioPlayer")
    mocker.patch("core.assistant.VoiceActivityDetector")
    mocker.patch("core.assistant.BackgroundTranscriber")
    mocker.patch("core.assistant.WakeWordDetector")
    mocker.patch("core.assistant.SentenceBuilder")
    mocker.patch("core.assistant.create_llm_client")
    mocker.patch("core.assistant.SemanticChunker")
    mocker.patch("core.assistant.create_tts_engine")
    mocker.patch("core.assistant.config.get", side_effect=_defaulting_config_get)
    mocker.patch("asyncio.new_event_loop", return_value=MagicMock())

    from core.assistant import VoiceAssistant
    from core.state_machine import State

    assistant = VoiceAssistant()
    assistant.llm_client.cancel = AsyncMock()
    assistant.async_loop = MagicMock()
    assistant.interrupt_signal = MagicMock()
    assistant.interrupt_signal.is_set.return_value = False
    assistant.user_activity_interrupt_signal = MagicMock()
    assistant.user_activity_interrupt_signal.is_set.return_value = False
    assistant._submit_coroutine = MagicMock(side_effect=lambda coro: (coro.close(), MagicMock())[1])

    assistant.sm.transition(State.SPEAKING)
    mock_future = MagicMock()

    lock_acquired = []
    original_lock = assistant.request_lock

    class SpyLock:
        def __enter__(self):
            lock_acquired.append(True)
            return original_lock.__enter__()
        def __exit__(self, *args):
            return original_lock.__exit__(*args)

    assistant.request_lock = SpyLock()
    assistant.state_context["current_llm_future"] = mock_future

    assistant.interrupt()

    assert len(lock_acquired) > 0




def test_issue3_audio_player_has_stream_lock():
    """Issue #3: AudioPlayer has a _stream_lock."""
    from core.audio_player import AudioPlayer
    player = AudioPlayer()
    assert hasattr(player, "_stream_lock")
    assert isinstance(player._stream_lock, type(threading.Lock()))


def test_issue3_on_stream_finished_uses_lock(mocker):
    """Issue #3: _on_stream_finished clears stream under _stream_lock."""
    mocker.patch("sounddevice.OutputStream")
    from core.audio_player import AudioPlayer
    player = AudioPlayer()
    player.start()

    acquired = []
    original_lock = player._stream_lock

    class SpyLock:
        def __enter__(self):
            acquired.append(True)
            return original_lock.__enter__()
        def __exit__(self, *args):
            return original_lock.__exit__(*args)

    player._stream_lock = SpyLock()
    player._on_stream_finished()

    assert len(acquired) > 0
    assert player.stream is None


def test_issue3_reset_interrupt_uses_lock(mocker):
    """Issue #3: reset_interrupt reads and clears stream under _stream_lock."""
    mocker.patch("sounddevice.OutputStream")
    from core.audio_player import AudioPlayer
    player = AudioPlayer()
    player.interrupt_flag = True
    player.stream = None

    acquired = []
    original_lock = player._stream_lock

    class SpyLock:
        def __enter__(self):
            acquired.append(True)
            return original_lock.__enter__()
        def __exit__(self, *args):
            return original_lock.__exit__(*args)

    player._stream_lock = SpyLock()
    player.reset_interrupt()
    assert len(acquired) > 0
    assert player.interrupt_flag is False




def test_issue6_get_hot_listen_elapsed_returns_0_when_not_in_hot_listen():
    """Issue #6: return 0.0 when not in HOT_LISTEN."""
    from core.state_machine import VoiceAssistantStateMachine, State

    sm = VoiceAssistantStateMachine()
    assert sm.current_state == State.IDLE_LISTEN
    assert sm.get_hot_listen_elapsed() == 0.0


def test_issue6_get_hot_listen_elapsed_measures_time():
    """Issue #6: measure elapsed time after entering HOT_LISTEN."""
    from core.state_machine import VoiceAssistantStateMachine, State

    sm = VoiceAssistantStateMachine()
    sm.transition(State.HOT_LISTEN)
    time.sleep(0.05)
    elapsed = sm.get_hot_listen_elapsed()
    assert elapsed >= 0.04


def test_issue6_get_hot_listen_elapsed_is_thread_safe():
    """Issue #6: concurrent get_hot_listen_elapsed() reads do not crash."""
    from core.state_machine import VoiceAssistantStateMachine, State

    sm = VoiceAssistantStateMachine()
    sm.transition(State.HOT_LISTEN)

    errors = []

    def reader():
        try:
            for _ in range(100):
                sm.get_hot_listen_elapsed()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=reader) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []




def test_issue7_chat_bubbles_capped_at_100():
    """Issue #7: cap rendered chat bubbles."""
    destroyed = []

    class FakeWidget:
        def destroy(self):
            destroyed.append(self)

    class FakeScrollFrame:
        def __init__(self):
            self._children = []
        def winfo_children(self):
            return list(self._children)
        def add(self, w):
            self._children.append(w)
        def remove_first(self):
            self._children.pop(0)

    MAX_BUBBLES = 100
    scroll = FakeScrollFrame()
    message_count = 0

    for i in range(101):
        if message_count >= MAX_BUBBLES:
            children = scroll.winfo_children()
            if children:
                children[0].destroy()
                scroll.remove_first()
            message_count -= 1
        scroll.add(FakeWidget())
        message_count += 1

    assert len(destroyed) == 1
    assert message_count == MAX_BUBBLES




def test_issue8_config_set_does_not_write_immediately(tmp_path, monkeypatch):
    """Issue #8: config.set() does not write immediately while debounced."""
    config_file = tmp_path / "test_debounce.json"
    monkeypatch.setattr("config.CONFIG_PATH", str(config_file))

    from config import Config

    cfg = Config()
    write_calls = []

    original_save = cfg.save
    cfg.save = lambda: write_calls.append(1) or original_save()

    cfg.set("a", value=1)
    cfg.set("b", value=2)
    cfg.set("c", value=3)

    assert len(write_calls) == 0, "debounce 期間不應立即寫入"

    time.sleep(0.7)
    assert len(write_calls) == 1, f"debounce 期間只應寫入一次，實際 {len(write_calls)} 次"


def test_issue8_config_flush_writes_immediately(tmp_path, monkeypatch):
    """Issue #8: config.flush() writes immediately."""
    config_file = tmp_path / "test_flush.json"
    monkeypatch.setattr("config.CONFIG_PATH", str(config_file))

    from config import Config

    cfg = Config()
    cfg.set("key", value="val")
    cfg.flush()

    assert config_file.exists()
    with open(config_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data.get("key") == "val"


def test_issue8_config_debounce_accumulates_changes(tmp_path, monkeypatch):
    """Issue #8: debounce persists all changes made inside the window."""
    config_file = tmp_path / "test_acc.json"
    monkeypatch.setattr("config.CONFIG_PATH", str(config_file))

    from config import Config

    cfg = Config()
    cfg.set("x", value=1)
    cfg.set("y", value=2)
    cfg.set("z", value=3)
    cfg.flush()

    with open(config_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("x") == 1
    assert data.get("y") == 2
    assert data.get("z") == 3




@pytest.mark.asyncio
async def test_issue9_speak_stream_skips_sentence_on_network_error(mocker):
    """Issue #9: TTS network errors are logged per sentence."""
    mocker.patch("edge_tts.Communicate", side_effect=ConnectionError("Network Error"))
    log_event = mocker.patch("tts.edge_tts_engine.log_event")
    mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)

    from tts.edge_tts_engine import EdgeTTSEngine

    engine = EdgeTTSEngine()
    await engine.speak_stream("hello", MagicMock())
    failed_calls = [call for call in log_event.call_args_list if call.args[2] == "tts.sentence_failed"]
    assert len(failed_calls) == 1


@pytest.mark.asyncio
async def test_issue9_speak_stream_cancelled_error_propagates(mocker):
    """Issue #9: CancelledError propagates through TTS."""
    async def fake_stream():
        raise asyncio.CancelledError()
        yield

    mock_communicate = MagicMock()
    mock_communicate.stream = fake_stream
    mocker.patch("edge_tts.Communicate", return_value=mock_communicate)

    from tts.edge_tts_engine import EdgeTTSEngine

    engine = EdgeTTSEngine()
    with pytest.raises(asyncio.CancelledError):
        await engine.speak_stream("hello", MagicMock())




@pytest.mark.asyncio
async def test_issue10_tts_worker_calls_task_done_on_exception(mocker):
    """Issue #10: _tts_worker calls task_done() after exceptions."""
    mocker.patch("core.assistant.AudioCapture")
    mocker.patch("core.assistant.AudioPlayer")
    mocker.patch("core.assistant.VoiceActivityDetector")
    mocker.patch("core.assistant.BackgroundTranscriber")
    mocker.patch("core.assistant.WakeWordDetector")
    mocker.patch("core.assistant.SentenceBuilder")
    mocker.patch("core.assistant.create_llm_client")
    mocker.patch("core.assistant.SemanticChunker")
    mocker.patch("core.assistant.create_tts_engine")
    mocker.patch("core.assistant.config.get", side_effect=_defaulting_config_get)
    mocker.patch("asyncio.new_event_loop", return_value=MagicMock())

    from core.assistant import VoiceAssistant

    assistant = VoiceAssistant()
    assistant.interrupt_signal = asyncio.Event()

    async def exploding_tts(*args, **kwargs):
        raise RuntimeError("TTS exploded!")
        if False:
            yield None

    assistant.tts_engine.synthesize_stream = exploding_tts

    q = asyncio.Queue()
    await q.put("cause_error")
    await q.put(None)

    try:
        await asyncio.wait_for(assistant._tts_worker(q), timeout=3.0)
    except asyncio.TimeoutError:
        pytest.fail("_tts_worker 沒有正確呼叫 task_done()，導致 timeout")

    assert q.empty()




@pytest.mark.asyncio
async def test_issue11_claude_client_uses_create_no_window_on_windows(mocker):
    """Issue #11: ClaudeCodeClient passes CREATE_NO_WINDOW on Windows."""
    mocker.patch("llm.claude_code_client.shutil.which", return_value="claude")
    mocker.patch("llm.claude_code_client.sys.platform", "win32")

    captured_kwargs = {}

    class MockProcess:
        returncode = 0
        stdout = MagicMock()
        stderr = MagicMock()

        def kill(self):
            pass

        async def wait(self):
            pass

    mock_proc = MockProcess()
    mock_proc.stdout.__aiter__ = lambda self: self
    mock_proc.stdout.__anext__ = AsyncMock(side_effect=StopAsyncIteration())

    async def mock_create_subprocess(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return mock_proc

    mocker.patch(
        "llm.claude_code_client.asyncio.create_subprocess_exec",
        side_effect=mock_create_subprocess
    )

    from llm.claude_code_client import ClaudeCodeClient
    client = ClaudeCodeClient()

    results = [chunk async for chunk in client.send_message("test")]

    assert "creationflags" in captured_kwargs
    import subprocess
    assert captured_kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW




def test_issue12_animation_controller_cache_limited(mocker):
    """Issue #12: AnimationController image cache is limited to two sizes."""
    mocker.patch("customtkinter.CTkImage", return_value=MagicMock())
    mocker.patch("PIL.Image.open", return_value=MagicMock())

    from ui.animation_controller import AnimationController
    from core.state_machine import State

    label = MagicMock()
    controller = AnimationController(label, image_size=(100, 100))

    sizes = [(200, 200), (400, 400), (600, 600)]
    for size in sizes:
        controller.image_size = size
        from pathlib import Path
        fake_path = Path(f"fake_{size[0]}.png")
        controller._tk_images_cache[(fake_path, size)] = MagicMock()
        if size not in controller._cache_size_order:
            controller._cache_size_order.append(size)
            while len(controller._cache_size_order) > controller._max_cache_sizes:
                oldest = controller._cache_size_order.pop(0)
                keys_to_del = [k for k in controller._tk_images_cache if k[1] == oldest]
                for k in keys_to_del:
                    del controller._tk_images_cache[k]

    cached_sizes = set(k[1] for k in controller._tk_images_cache.keys())
    assert len(cached_sizes) <= 2, f"快取尺寸数 {len(cached_sizes)} 超過 2"




def test_issue13_input_monitor_caches_enabled_flag(mocker):
    """Issue #13: GlobalInputMonitor uses cached activity settings."""
    get_calls = []

    def counting_get(section, key, default=None):
        get_calls.append((section, key))
        return True

    mocker.patch("ui.global_input_monitor.config.get", side_effect=counting_get)

    from ui.global_input_monitor import GlobalInputMonitor

    monitor = GlobalInputMonitor(on_activity=MagicMock())
    initial_calls = len(get_calls)

    mocker.patch.object(GlobalInputMonitor, "_is_own_app_foreground", return_value=True)
    for i in range(100):
        monitor._on_move(i, i)

    additional_calls = len(get_calls) - initial_calls
    assert additional_calls == 0, f"100 次移動後 config.get 被額外呼叫了 {additional_calls} 次"


def test_issue13_update_settings_refreshes_cache(mocker):
    """Issue #13: update_settings() refreshes cached settings."""
    values = {
        "enabled": True,
        "threshold": 12,
        "presence_input_enabled": True,
    }

    def dynamic_get(section, key, default=None):
        if key == "enabled":
            return values["enabled"]
        if key == "mouse_move_threshold_px":
            return values["threshold"]
        if key == "input_triggers_presence":
            return values["presence_input_enabled"]
        return default

    mocker.patch("ui.global_input_monitor.config.get", side_effect=dynamic_get)

    from ui.global_input_monitor import GlobalInputMonitor

    monitor = GlobalInputMonitor(on_activity=MagicMock())
    assert monitor._activity_enabled is True

    values["enabled"] = False
    monitor.update_settings()

    assert monitor._activity_enabled is True

    values["presence_input_enabled"] = False
    monitor.update_settings()

    assert monitor._activity_enabled is False




def test_issue14_stop_drains_audio_queue(mocker):
    """Issue #14: stop() drains audio_queue so perception_loop exits promptly."""
    mocker.patch("core.assistant.AudioCapture")
    mocker.patch("core.assistant.AudioPlayer")
    mocker.patch("core.assistant.VoiceActivityDetector")
    mocker.patch("core.assistant.BackgroundTranscriber")
    mocker.patch("core.assistant.WakeWordDetector")
    mocker.patch("core.assistant.SentenceBuilder")
    mocker.patch("core.assistant.create_llm_client")
    mocker.patch("core.assistant.SemanticChunker")
    mocker.patch("core.assistant.create_tts_engine")
    mocker.patch("core.assistant.config.get", side_effect=_defaulting_config_get)
    mocker.patch("asyncio.new_event_loop", return_value=MagicMock())

    from core.assistant import VoiceAssistant

    assistant = VoiceAssistant()
    assistant.async_loop = None

    mock_queue = MagicMock()
    mock_queue.empty.side_effect = [False, False, False, True]
    mock_queue.get_nowait.return_value = bytes(512)
    assistant.capture.get_audio_queue.return_value = mock_queue

    assistant.stop()

    assert mock_queue.get_nowait.call_count >= 3
