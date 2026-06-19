import pytest
import numpy as np
import queue
import time
import asyncio
import threading
import os
import inspect
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock, ANY, call
from core.assistant import VoiceAssistant
from core.audio_player import PlaybackProgressSnapshot
from core.state_machine import State
from llm.base_client import BaseLLMClient, STREAM_ACTIVITY_KEEPALIVE


def _close_coroutine_tree(coro):
    if not inspect.iscoroutine(coro):
        return

    frame = getattr(coro, "cr_frame", None)
    if frame is not None:
        request_coro = frame.f_locals.get("request_coro")
        if inspect.iscoroutine(request_coro):
            _close_coroutine_tree(request_coro)

    coro.close()


def _mock_submit_returning(future):
    def _submit(coro):
        _close_coroutine_tree(coro)
        return future

    return MagicMock(side_effect=_submit)


@pytest.fixture
def mock_assistant(mocker):

    mocker.patch("core.assistant.AudioCapture")
    mocker.patch("core.assistant.AudioPlayer")
    mocker.patch("core.assistant.VoiceActivityDetector")
    mocker.patch("core.assistant.BackgroundTranscriber")
    mocker.patch("core.assistant.WakeWordDetector")
    mocker.patch("core.assistant.SentenceBuilder")
    mocker.patch("core.assistant.create_llm_client")
    mocker.patch("core.assistant.SemanticChunker")
    mocker.patch("core.assistant.EdgeTTSEngine")
    mocker.patch("core.assistant.WhisperAudioArchive")
    mocker.patch("core.assistant.SpeakerRecognizer")
    mocker.patch("core.assistant.HeartbeatScheduler")


    def config_get(section, key, default=None):
        values = {
            ("audio", "input_sample_rate"): 16000,
            ("audio", "output_sample_rate"): 24000,
            ("audio", "input_block_size"): 512,
            ("audio", "output_block_size"): 512,
            ("vad", "threshold"): 0.5,
            ("vad", "min_silence_duration_ms"): 1500,
            ("vad", "speech_pad_ms"): 30,
            ("vad", "command_timeout_seconds"): 20,
            ("whisper", "model_size"): "tiny",
            ("whisper", "device"): "cpu",
            ("whisper", "compute_type"): "int8",
            ("whisper", "language"): "zh",
            ("whisper", "initial_prompt"): "",
            ("whisper_audio_archive", "enabled"): True,
            ("whisper_audio_archive", "directory"): "whisper_audio_archive",
            ("whisper_audio_archive", "write_transcript_sidecar"): True,
            ("wake_word", "model_dir"): "models",
            ("speaker_recognition", "enabled"): True,
            ("speaker_recognition", "profile_dir"): "voice_profiles",
            ("speaker_recognition", "threshold"): 0.75,
            ("speaker_recognition", "min_duration_seconds"): 0.8,
            ("semantic_chunker", "split_punctuation"): ["。", "！", "？"],
            ("semantic_chunker", "also_split"): [],
            ("tts", "voice"): "test_voice",
            ("tts", "rate"): "+0%",
            ("tts", "volume"): "+0%",
            ("hot_listen", "enabled"): True,
            ("hot_listen", "timeout_seconds"): 8.0,
            ("llm", "active_backend"): "openclaw",
            ("llm", "openclaw"): {},
            ("llm", "claude_code"): {},
            ("llm", "codex_cli"): {},
            ("llm", "gemini_cli"): {},
            ("llm", "response_timeout_seconds"): 90.0,
            ("llm", "first_token_timeout_seconds"): 90.0,
            ("llm", "stream_idle_timeout_seconds"): 15.0,
            ("llm", "session_timeout_minutes"): 5,
            ("user_activity_prompt", "enabled"): True,
            ("user_activity_prompt", "text"): "請問需要我幫忙嗎？",
            ("heartbeat", "enabled"): True,
            ("heartbeat", "interval_minutes"): 10,
            ("presence_detection", "enabled"): True,
            ("presence_detection", "ttl_seconds"): 300,
            ("presence_detection", "audio_triggers_presence"): True,
            ("presence_detection", "input_triggers_presence"): True,
        }
        return values.get((section, key), default if default is not None else MagicMock())

    mocker.patch("core.assistant.config.get", side_effect=config_get)
    mocker.patch("core.assistant.config.set")


    mocker.patch("asyncio.new_event_loop", return_value=MagicMock())

    assistant = VoiceAssistant()
    assistant.llm_client.cancel = AsyncMock()
    assistant.speaker_recognizer.is_available.return_value = True
    assistant.speaker_recognizer.identify.return_value = None
    assistant.sentence_builder.add_chunk.return_value = None
    assistant.async_loop = MagicMock()
    assistant.interrupt_signal = MagicMock()
    assistant.interrupt_signal.is_set.return_value = False
    assistant.user_activity_interrupt_signal = MagicMock()
    assistant.user_activity_interrupt_signal.is_set.return_value = False
    assistant._submit_coroutine = _mock_submit_returning(MagicMock())
    assistant.heartbeat.start.return_value.result.return_value = None
    assistant.heartbeat.stop.return_value.result.return_value = None
    assistant.heartbeat.is_enabled = True
    assistant._heartbeat_within_active_window = MagicMock(return_value=True)

    return assistant

def test_assistant_init(mock_assistant):
    assert mock_assistant.running == False
    assert mock_assistant.sm.current_state == State.IDLE_LISTEN

def test_assistant_init_disables_speaker_recognizer_when_backend_unavailable(mocker):
    mocker.patch("core.assistant.AudioCapture")
    mocker.patch("core.assistant.AudioPlayer")
    mocker.patch("core.assistant.VoiceActivityDetector")
    mocker.patch("core.assistant.BackgroundTranscriber")
    mocker.patch("core.assistant.WakeWordDetector")
    mocker.patch("core.assistant.SentenceBuilder")
    mocker.patch("core.assistant.create_llm_client")
    mocker.patch("core.assistant.SemanticChunker")
    mocker.patch("core.assistant.EdgeTTSEngine")
    mocker.patch("core.assistant.WhisperAudioArchive")
    recognizer_cls = mocker.patch("core.assistant.SpeakerRecognizer")
    recognizer_cls.return_value.is_available.return_value = False

    def config_get(section, key, default=None):
        values = {
            ("audio", "input_sample_rate"): 16000,
            ("audio", "output_sample_rate"): 24000,
            ("audio", "input_block_size"): 512,
            ("audio", "output_block_size"): 512,
            ("vad", "threshold"): 0.5,
            ("vad", "min_silence_duration_ms"): 1500,
            ("vad", "speech_pad_ms"): 30,
            ("whisper", "model_size"): "tiny",
            ("whisper", "device"): "cpu",
            ("whisper", "compute_type"): "int8",
            ("whisper", "language"): "zh",
            ("whisper", "initial_prompt"): "",
            ("whisper_audio_archive", "enabled"): False,
            ("speaker_recognition", "enabled"): True,
            ("speaker_recognition", "profile_dir"): "voice_profiles",
            ("speaker_recognition", "threshold"): 0.75,
            ("speaker_recognition", "min_duration_seconds"): 0.8,
            ("wake_word", "model_dir"): "models",
            ("semantic_chunker", "split_punctuation"): ["。", "！", "？"],
            ("semantic_chunker", "also_split"): [],
            ("tts", "voice"): "test_voice",
            ("tts", "rate"): "+0%",
            ("tts", "volume"): "+0%",
            ("hot_listen", "enabled"): True,
            ("hot_listen", "timeout_seconds"): 8.0,
            ("llm", "active_backend"): "openclaw",
            ("llm", "openclaw"): {},
            ("llm", "codex_cli"): {},
            ("llm", "response_timeout_seconds"): 90.0,
            ("llm", "first_token_timeout_seconds"): 90.0,
            ("llm", "stream_idle_timeout_seconds"): 15.0,
        }
        return values.get((section, key), default if default is not None else MagicMock())

    mocker.patch("core.assistant.config.get", side_effect=config_get)
    mocker.patch("asyncio.new_event_loop", return_value=MagicMock())

    assistant = VoiceAssistant()

    assert assistant.speaker_recognizer is None

def test_clear_request_ignores_non_current_future(mock_assistant):
    current_future = MagicMock()
    other_future = MagicMock()
    mock_assistant.state_context["current_llm_future"] = current_future
    mock_assistant.state_context["current_llm_client"] = mock_assistant.llm_client

    mock_assistant._clear_request(other_future)

    assert mock_assistant.state_context["current_llm_future"] is current_future
    assert mock_assistant.state_context["current_llm_client"] is mock_assistant.llm_client

def test_submit_coroutine_closes_failed_submission(mock_assistant, mocker):
    async def sample():
        await asyncio.sleep(0)

    coro = sample()
    mocker.patch("asyncio.run_coroutine_threadsafe", side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        VoiceAssistant._submit_coroutine(mock_assistant, coro)

    assert coro.cr_frame is None

def test_assistant_start_stop(mock_assistant, mocker):
    with patch("threading.Thread") as mock_thread:

        spy_warmup = mocker.spy(mock_assistant, "_warm_up_llm")
        mock_assistant.start()
        assert mock_assistant.running == True
        spy_warmup.assert_called_once()

        mock_assistant.stop()
        assert mock_assistant.running == False
        mock_assistant.async_loop.call_soon_threadsafe.assert_called()


def test_prepare_for_gui_waits_for_whisper_and_llm(mock_assistant):
    ready_future = MagicMock()
    mock_assistant._ensure_async_loop = MagicMock()
    mock_assistant._submit_coroutine = _mock_submit_returning(ready_future)
    mock_assistant.transcriber.wait_until_ready.side_effect = [False, True]
    mock_assistant.transcriber.load_error = None
    statuses = []

    mock_assistant.prepare_for_gui(status_callback=statuses.append)

    mock_assistant._ensure_async_loop.assert_called_once_with(wait_until_ready=True)
    mock_assistant._submit_coroutine.assert_called_once()
    ready_future.result.assert_called_once()
    assert mock_assistant.transcriber.wait_until_ready.call_count == 2
    assert "準備 LLM backend..." in statuses
    assert "載入 Whisper 語音辨識模型..." in statuses
    assert statuses[-1] == "預備完成，啟動 GUI..."


def test_prepare_for_gui_raises_when_whisper_load_fails(mock_assistant):
    load_error = RuntimeError("load failed")
    mock_assistant._ensure_async_loop = MagicMock()
    mock_assistant._submit_coroutine = _mock_submit_returning(MagicMock())
    mock_assistant.transcriber.wait_until_ready.return_value = False
    mock_assistant.transcriber.load_error = load_error

    with pytest.raises(RuntimeError, match="Whisper model failed to load"):
        mock_assistant.prepare_for_gui()

def test_assistant_start_rolls_back_on_capture_failure(mock_assistant):
    mock_assistant.capture.start.side_effect = RuntimeError("mic unavailable")

    with patch("threading.Thread") as mock_thread, pytest.raises(RuntimeError, match="mic unavailable"):
        mock_thread.return_value = MagicMock()
        mock_assistant.start()

    assert mock_assistant.running is False
    mock_assistant.capture.stop.assert_called_once()
    mock_assistant.audio_player.stop.assert_called_once()
    mock_assistant.async_loop.call_soon_threadsafe.assert_called()

def test_assistant_stop_without_async_loop(mock_assistant):
    mock_assistant.async_loop = None

    mock_assistant.stop()

    mock_assistant.capture.stop.assert_called_once()
    mock_assistant.audio_player.stop.assert_called_once()

def test_close_llm_client_timeout_logs_warning_and_cancels_future(mock_assistant, mocker):
    future = MagicMock()
    future.result.side_effect = FutureTimeoutError()
    mock_assistant._submit_coroutine = _mock_submit_returning(future)
    log_event = mocker.patch("core.assistant.log_event")
    llm_client = MagicMock()
    llm_client.aclose = AsyncMock()

    mock_assistant._close_llm_client(llm_client)

    future.cancel.assert_called_once()
    timeout_calls = [call for call in log_event.call_args_list if call.args[2] == "llm.client_close_timeout"]
    assert len(timeout_calls) == 1

def test_close_llm_client_timeout_kills_process(mock_assistant, mocker):
    future = MagicMock()
    future.result.side_effect = FutureTimeoutError()
    mock_assistant._submit_coroutine = _mock_submit_returning(future)
    mocker.patch("core.assistant.log_event")
    process = MagicMock()
    process.returncode = None
    process.pid = None
    llm_client = MagicMock()
    llm_client.process = process
    llm_client.aclose = AsyncMock()

    mock_assistant._close_llm_client(llm_client)

    future.cancel.assert_called_once()
    process.kill.assert_called_once()

def test_assistant_warm_up_llm(mock_assistant, mocker):
    """O-2: _warm_up_llm schedules _start_acp when supported."""
    mock_assistant.llm_client._start_acp = AsyncMock()
    mock_assistant.async_loop = MagicMock()

    mock_assistant._warm_up_llm()
    mock_assistant._submit_coroutine.assert_called_once()

def test_assistant_interrupt(mock_assistant, mocker):
    mock_assistant.sm.transition(State.SPEAKING)
    mock_future = MagicMock()
    mock_assistant.state_context["current_llm_future"] = mock_future

    mock_assistant.interrupt()

    assert mock_assistant.sm.current_state == State.IDLE_LISTEN
    mock_assistant.audio_player.interrupt.assert_called_once()
    mock_future.cancel.assert_called_once()
    assert mock_assistant.state_context["current_llm_future"] is None
    mock_assistant.llm_client.cancel.assert_called_once()


    mock_assistant.chunker.reset.assert_called_once()
    assert mock_assistant.sentence_builder.reset.call_count >= 1
    assert mock_assistant.vad.reset_states.call_count >= 1

def test_assistant_interrupt_resume_collecting(mock_assistant):
    mock_assistant.sm.transition(State.SPEAKING)
    mock_future = MagicMock()
    mock_assistant.state_context["current_llm_future"] = mock_future

    mock_assistant.interrupt(resume_collecting=True)

    assert mock_assistant.sm.current_state == State.COLLECTING
    mock_future.cancel.assert_called_once()
    mock_assistant.audio_player.interrupt.assert_called_once()


def test_set_voice_enabled_from_sending_keeps_busy_state(mock_assistant):
    mock_assistant.sm.transition(State.SENDING)

    mock_assistant.set_voice_enabled(True)

    assert mock_assistant.voice_paused is False
    assert mock_assistant.sm.current_state == State.SENDING

def test_set_voice_enabled_from_text_mode_interrupts_active_request(mock_assistant):
    mock_assistant.voice_paused = True
    mock_assistant.sm.transition(State.SENDING)
    mock_future = MagicMock()
    mock_assistant.state_context["current_llm_future"] = mock_future

    mock_assistant.set_voice_enabled(True)

    assert mock_assistant.voice_paused is False
    assert mock_assistant.sm.current_state == State.IDLE_LISTEN
    mock_future.cancel.assert_called_once()
    mock_assistant.llm_client.cancel.assert_called_once()


@pytest.mark.asyncio
async def test_submit_request_clears_only_matching_future(mock_assistant):
    release_first = asyncio.Event()
    release_second = asyncio.Event()

    async def first_request():
        await release_first.wait()

    async def second_request():
        await release_second.wait()

    mock_assistant._submit_coroutine = lambda coro: asyncio.create_task(coro)

    first_future = mock_assistant._submit_request(first_request(), mock_assistant.llm_client)
    second_future = mock_assistant._submit_request(second_request(), mock_assistant.llm_client)

    assert mock_assistant.state_context["current_llm_future"] is second_future

    release_first.set()
    await first_future

    assert mock_assistant.state_context["current_llm_future"] is second_future

    release_second.set()
    await second_future

    assert mock_assistant.state_context["current_llm_future"] is None

def test_assistant_on_state_change(mock_assistant):
    callback = MagicMock()
    mock_assistant.set_callbacks(callback, None)
    mock_assistant.on_state_change(State.SENDING)
    callback.assert_called_with(State.SENDING)

def test_assistant_on_message(mock_assistant):
    callback = MagicMock()
    mock_assistant.set_callbacks(None, callback)
    mock_assistant.on_message("user", "hello")
    callback.assert_called_with("user", "hello")

def test_assistant_on_message_can_request_new_bubble(mock_assistant):
    callback = MagicMock()
    mock_assistant.set_callbacks(None, callback)

    mock_assistant.on_message("assistant", "hello", update_existing=False)

    callback.assert_called_once_with("assistant", "hello", update_existing=False)

def test_assistant_on_message_can_include_speaker_name(mock_assistant):
    callback = MagicMock()
    mock_assistant.set_callbacks(None, callback)

    mock_assistant.on_message("user", "hello", speaker_name="ViVi")

    callback.assert_called_once_with("user", "hello", speaker_name="ViVi")

def test_assistant_on_session_refreshed(mock_assistant):
    callback = MagicMock()
    mock_assistant.set_callbacks(None, None, callback)

    mock_assistant.on_session_refreshed()

    callback.assert_called_once_with()

def test_normalize_response_chunk_trims_prefix_and_buffers_whitespace():
    chunk, pending = VoiceAssistant._normalize_response_chunk("", "", "\n\n  hello")
    assert (chunk, pending) == ("hello", "")

    chunk, pending = VoiceAssistant._normalize_response_chunk("", "", "\n\t")
    assert chunk == ""
    assert pending == "\n\t"

    chunk, pending = VoiceAssistant._normalize_response_chunk("hello", pending, "\n\nnext")
    assert (chunk, pending) == ("\n\nnext", "")


def test_normalize_response_chunk_collapses_thinking_newlines():
    pending = ""
    chunk, pending = VoiceAssistant._normalize_response_chunk("please wait.", pending, "\n\n\n")
    assert chunk == ""

    chunk, pending = VoiceAssistant._normalize_response_chunk("please wait.", pending, "\n\nsearch result")
    assert (chunk, pending) == ("\n\nsearch result", "")


def test_classify_backend_error_response_detects_codex_unavailable_message():
    assert (
        VoiceAssistant._classify_backend_error_response("無法連線至本地 Codex 助理。")
        == "client_error_text"
    )


def test_assistant_change_backend(mock_assistant, mocker):
    mocker.patch("core.assistant.config.set")
    assert mock_assistant.change_backend("claude_code") is True
    assert mock_assistant.llm_client is not None

def test_assistant_change_backend_closes_old_client(mock_assistant, mocker):
    old_client = mock_assistant.llm_client
    new_client = MagicMock()
    mocker.patch("core.assistant.config.set")
    mocker.patch("core.assistant.create_llm_client", return_value=new_client)
    spy_close = mocker.spy(mock_assistant, "_close_llm_client")

    assert mock_assistant.change_backend("claude_code") is True

    assert mock_assistant.llm_client is new_client
    spy_close.assert_called_once_with(old_client)

def test_assistant_change_backend_waits_for_ensure_ready_before_commit(mock_assistant, mocker):
    new_client = MagicMock()
    order = []
    mocker.patch("core.assistant.create_llm_client", return_value=new_client)
    mocker.patch.object(
        mock_assistant,
        "_ensure_llm_client_ready_blocking",
        side_effect=lambda _client: order.append("ensure"),
    )
    mocker.patch("core.assistant.config.set", side_effect=lambda *args, **kwargs: order.append("set"))
    mocker.patch.object(mock_assistant, "_close_llm_client", side_effect=lambda _client: order.append("close"))

    assert mock_assistant.change_backend("claude_code") is True

    assert order == ["ensure", "set", "close"]
    assert mock_assistant.llm_client is new_client

def test_assistant_change_backend_rolls_back_when_ensure_ready_fails(mock_assistant, mocker):
    old_client = mock_assistant.llm_client
    new_client = MagicMock()
    mocker.patch("core.assistant.create_llm_client", return_value=new_client)
    mock_set = mocker.patch("core.assistant.config.set")
    mock_close = mocker.patch.object(mock_assistant, "_close_llm_client")
    mocker.patch.object(
        mock_assistant,
        "_ensure_llm_client_ready_blocking",
        side_effect=RuntimeError("OpenCode startup failed"),
    )

    assert mock_assistant.change_backend("opencode_cli") is False

    assert mock_assistant.llm_client is old_client
    mock_set.assert_not_called()
    mock_close.assert_called_once_with(new_client)
    assert "OpenCode startup failed" in mock_assistant.last_backend_switch_error

def test_assistant_change_backend_rejected_while_busy(mock_assistant, mocker):
    mock_set = mocker.patch("core.assistant.config.set")
    mock_future = MagicMock()
    mock_future.done.return_value = False
    mock_assistant.state_context["current_llm_future"] = mock_future

    result = mock_assistant.change_backend("claude_code")

    assert result is False
    mock_set.assert_not_called()

def test_interrupt_ignored_when_idle(mock_assistant):
    mock_assistant.interrupt()

    mock_assistant.audio_player.interrupt.assert_not_called()
    mock_assistant.llm_client.cancel.assert_not_called()

def test_interrupt_from_collecting_returns_idle(mock_assistant):
    mock_assistant.sm.transition(State.COLLECTING)

    interrupted = mock_assistant.interrupt()

    assert interrupted is True
    assert mock_assistant.sm.current_state == State.IDLE_LISTEN

@pytest.mark.asyncio
async def test_assistant_tts_worker_cancel(mock_assistant, mocker):
    q = asyncio.Queue()
    await q.put("test")
    task = asyncio.create_task(mock_assistant._tts_worker(q))
    await asyncio.sleep(0.01)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

@pytest.mark.asyncio
async def test_assistant_tts_worker_none(mock_assistant, mocker):
    """BUG-11 fix: sentinel None calls q.task_done()."""
    q = asyncio.Queue()
    await q.put(None)
    await mock_assistant._tts_worker(q)
    assert q.empty()

@pytest.mark.asyncio
async def test_assistant_tts_worker_error(mock_assistant, mocker):
    q = asyncio.Queue()
    await q.put("error_sentence")

    async def mock_speak(*args, **kwargs):
        raise Exception("tts error")
    mock_assistant.tts_engine.speak_stream = mock_speak

    await q.put(None)
    await mock_assistant._tts_worker(q)

def test_perception_loop_wake_word_trigger(mock_assistant, mocker):
    mocker.patch.object(mock_assistant, "_start_execution_thread")
    audio_queue = MagicMock()
    mock_assistant.capture.get_audio_queue.return_value = audio_queue
    mock_assistant.wake_word.detect.return_value = "愛管家"
    mock_assistant.running = True

    audio_queue.get.side_effect = [np.zeros(512, dtype=np.int16), queue.Empty()]

    def stop_after_one_loop(*args):
        mock_assistant.running = False
        return "愛管家"
    mock_assistant.wake_word.detect.side_effect = stop_after_one_loop

    mock_assistant._perception_loop()
    assert mock_assistant.sm.current_state == State.COLLECTING

def test_perception_loop_wake_word_trigger_sending(mock_assistant, mocker):
    mocker.patch.object(mock_assistant, "_start_execution_thread")
    audio_queue = MagicMock()
    mock_assistant.capture.get_audio_queue.return_value = audio_queue
    mock_assistant.running = True

    audio_queue.get.side_effect = [np.zeros(512, dtype=np.int16), queue.Empty()]
    mock_assistant.sentence_builder.add_chunk.side_effect = [np.zeros(16000), None]

    def stop_after_one_loop(*args):
        mock_assistant.running = False
        return "愛管家"
    mock_assistant.wake_word.detect.side_effect = stop_after_one_loop

    mock_assistant._perception_loop()
    assert mock_assistant.sm.current_state == State.SENDING
    mock_assistant._start_execution_thread.assert_called_once()

def test_perception_loop_timeout(mock_assistant, mocker):
    mock_assistant.sm.transition(State.COLLECTING)
    mock_assistant._collecting_started_at = 70.0
    mock_assistant.sentence_builder.flush_partial.return_value = None
    audio_queue = MagicMock()
    mock_assistant.capture.get_audio_queue.return_value = audio_queue
    mock_assistant.running = True
    audio_queue.get.side_effect = [np.zeros(512, dtype=np.int16), queue.Empty()]

    with patch("time.time", side_effect=[100.0, 120.0, 120.0, 120.0, 120.0, 120.0, 120.0]):
        def stop_loop(*args, **kwargs):
            mock_assistant.running = False
            return None
        mock_assistant.wake_word.detect.side_effect = stop_loop
        mock_assistant._perception_loop()

    assert mock_assistant.sm.current_state == State.IDLE_LISTEN
    mock_assistant.sentence_builder.flush_partial.assert_called_once()

def test_perception_loop_timeout_flushes_partial_audio_into_execution(mock_assistant, mocker):
    mocker.patch.object(mock_assistant, "_start_execution_thread")
    mock_assistant.sm.transition(State.COLLECTING)
    mock_assistant._collecting_started_at = 70.0
    partial_audio = np.ones(16000, dtype=np.float32)
    mock_assistant.sentence_builder.flush_partial.return_value = partial_audio
    audio_queue = MagicMock()
    mock_assistant.capture.get_audio_queue.return_value = audio_queue
    mock_assistant.running = True
    audio_queue.get.side_effect = [np.zeros(512, dtype=np.int16), queue.Empty()]

    with patch("time.time", side_effect=[100.0, 120.0, 120.0, 120.0, 120.0, 120.0, 120.0]):
        def stop_loop(*args, **kwargs):
            mock_assistant.running = False
            return None
        mock_assistant.wake_word.detect.side_effect = stop_loop
        mock_assistant._perception_loop()

    assert mock_assistant.sm.current_state == State.SENDING
    mock_assistant._start_execution_thread.assert_called_once_with(partial_audio)
    mock_assistant.sentence_builder.flush_partial.assert_called_once()

def test_perception_loop_timeout_sends_long_partial_audio(mock_assistant, mocker):
    mocker.patch.object(mock_assistant, "_start_execution_thread")
    mock_assistant.sm.transition(State.COLLECTING)
    mock_assistant._collecting_started_at = 70.0
    partial_audio = np.ones(19 * 16000, dtype=np.float32)
    mock_assistant.sentence_builder.flush_partial.return_value = partial_audio
    audio_queue = MagicMock()
    mock_assistant.capture.get_audio_queue.return_value = audio_queue
    mock_assistant.running = True
    audio_queue.get.side_effect = [np.zeros(512, dtype=np.int16), queue.Empty()]

    with patch("time.time", side_effect=[100.0, 120.0, 120.0, 120.0, 120.0, 120.0, 120.0]):
        def stop_loop(*args, **kwargs):
            mock_assistant.running = False
            return None
        mock_assistant.wake_word.detect.side_effect = stop_loop
        mock_assistant._perception_loop()

    assert mock_assistant.sm.current_state == State.SENDING
    mock_assistant._start_execution_thread.assert_called_once_with(partial_audio)
    mock_assistant.sentence_builder.flush_partial.assert_called_once()

def test_perception_loop_hot_listen_trigger(mock_assistant, mocker):
    mock_assistant.sm.transition(State.HOT_LISTEN)
    mock_assistant.sm._hot_listen_start_time = time.time() - 1.0

    audio_queue = MagicMock()
    mock_assistant.capture.get_audio_queue.return_value = audio_queue
    mock_assistant.running = True
    audio_queue.get.side_effect = [np.zeros(512, dtype=np.int16), queue.Empty()]

    mock_assistant.vad.process_chunk.return_value = {'start': 0.0}

    def stop_loop(*args, **kwargs):
        mock_assistant.running = False
        return None
    mock_assistant.wake_word.detect.side_effect = stop_loop

    mock_assistant._perception_loop()
    assert mock_assistant.sm.current_state == State.COLLECTING

def test_perception_loop_hot_listen_timeout(mock_assistant, mocker):
    mock_assistant.sm.transition(State.HOT_LISTEN)
    mock_assistant.sm._hot_listen_start_time = time.time() - 10.0

    audio_queue = MagicMock()
    mock_assistant.capture.get_audio_queue.return_value = audio_queue
    mock_assistant.running = True
    audio_queue.get.side_effect = [queue.Empty()]

    orig_check = mock_assistant.sm.check_hot_listen_timeout
    def side_effect():
        res = orig_check()
        if res: mock_assistant.running = False
        return res
    mock_assistant.sm.check_hot_listen_timeout = side_effect

    mock_assistant._perception_loop()
    assert mock_assistant.sm.current_state == State.IDLE_LISTEN

def test_execution_func_no_text(mock_assistant, mocker):
    mock_assistant.sm.transition(State.SENDING)
    mock_assistant.transcriber.transcribe.return_value = ""
    mock_assistant._execution_func(np.zeros(16000))
    mock_assistant.whisper_audio_archive.save.assert_called_once()
    mock_assistant.whisper_audio_archive.write_transcript_sidecar.assert_called_once()
    assert mock_assistant.sm.current_state == State.IDLE_LISTEN

def test_execution_func_with_text(mock_assistant, mocker):
    mock_assistant.sm.transition(State.SENDING)
    mock_assistant.transcriber.transcribe.return_value = "hello"

    future = MagicMock()
    mock_assistant._submit_coroutine = _mock_submit_returning(future)
    mock_assistant._execution_func(np.zeros(16000))

    mock_assistant.chunker.reset.assert_called_once()
    mock_assistant.whisper_audio_archive.save.assert_called_once()
    mock_assistant.whisper_audio_archive.write_transcript_sidecar.assert_called_once()
    assert mock_assistant.state_context["current_llm_future"] is future

def test_execution_func_drops_stale_generation_after_interrupt(mock_assistant):
    mock_assistant.sm.transition(State.SENDING)
    stale_generation = mock_assistant._next_voice_execution_generation()

    assert mock_assistant.interrupt(resume_collecting=True) is True
    assert mock_assistant._current_voice_execution_generation() > stale_generation

    mock_assistant._submit_coroutine.reset_mock()
    mock_assistant.on_message = MagicMock()
    mock_assistant._execute_llm_request = AsyncMock()
    mock_assistant.transcriber.transcribe.return_value = "stale transcript"
    mock_assistant.sm.transition(State.SENDING)

    mock_assistant._execution_func(np.zeros(16000), stale_generation)

    mock_assistant.speaker_recognizer.identify.assert_not_called()
    mock_assistant.on_message.assert_not_called()
    mock_assistant._execute_llm_request.assert_not_called()
    mock_assistant._submit_coroutine.assert_not_called()
    mock_assistant.whisper_audio_archive.write_transcript_sidecar.assert_called_once()
    assert mock_assistant.sm.current_state == State.SENDING

def test_execution_func_skips_llm_for_entire_unreliable_whisper_turn(mock_assistant):
    """Noisy transcript stays local and prompts the user to retry without hitting the LLM."""
    mock_assistant.sm.transition(State.SENDING)
    replacement_text = "(聲音雜亂, 系統無法辨識)"
    mock_assistant.transcriber.transcribe.return_value = replacement_text
    mock_assistant.on_message = MagicMock()
    mock_assistant._execute_llm_request = AsyncMock()

    future = MagicMock()
    mock_assistant._submit_coroutine = _mock_submit_returning(future)

    mock_assistant._execution_func(np.zeros(16000))

    mock_assistant.on_message.assert_has_calls(
        [
            call("user", replacement_text, speaker_name="未知"),
            call("assistant", "我剛剛沒有聽清楚，請再說一次。", update_existing=False),
        ]
    )
    mock_assistant._execute_llm_request.assert_not_called()
    mock_assistant._submit_coroutine.assert_called_once()

def test_execution_func_prefixes_llm_text_when_speaker_identified(mock_assistant):
    mock_assistant.sm.transition(State.SENDING)
    mock_assistant.transcriber.transcribe.return_value = "hello"
    mock_assistant.speaker_recognizer.identify.return_value = "ViVi"
    mock_assistant._execute_llm_request = AsyncMock()

    future = MagicMock()
    mock_assistant._submit_coroutine = _mock_submit_returning(future)

    mock_assistant._execution_func(np.zeros(16000))

    mock_assistant._execute_llm_request.assert_called_once_with(
        "(系統提示: 這句話的說話者可能是 ViVi。)\nhello",
        llm_client=mock_assistant.llm_client,
        request_id=ANY,
        speaker_name="ViVi",
    )

def test_execution_func_prefixes_interrupt_notice_when_present(mock_assistant, mocker):
    mock_assistant.sm.transition(State.SENDING)
    mock_assistant.transcriber.transcribe.return_value = "hello"
    mock_assistant._execute_llm_request = AsyncMock()
    mocker.patch.object(
        mock_assistant,
        "_consume_pending_interrupt_notice",
        return_value="上一輪回覆在「你好」附近被打斷。",
    )

    future = MagicMock()
    mock_assistant._submit_coroutine = _mock_submit_returning(future)

    mock_assistant._execution_func(np.zeros(16000))

    sent_text = mock_assistant._execute_llm_request.call_args.args[0]
    assert "(系統提示: 上一輪回覆在「你好」附近被打斷。)" in sent_text
    assert sent_text.endswith("hello")

def test_build_llm_text_combines_system_hints_in_uniform_format(mock_assistant):
    llm_text = mock_assistant._build_llm_text(
        "hello",
        speaker_name="ViVi",
        interrupt_notice="上一輪回覆在「你好」附近被打斷。",
    )

    assert llm_text == (
        "(系統提示: 上一輪回覆在「你好」附近被打斷。)\n"
        "(系統提示: 這句話的說話者可能是 ViVi。)\n"
        "hello"
    )

def test_interrupt_records_wake_word_context(mock_assistant):
    mock_assistant.sm.transition(State.SPEAKING)
    mock_assistant.state_context["current_llm_future"] = MagicMock()
    mock_assistant.audio_player.interrupt.return_value = PlaybackProgressSnapshot(
        status="playing",
        sentence_text="請先打開設定頁面",
        heard_text="請先打開",
        current_word="打開",
        remaining_text="設定頁面",
        played_samples=120,
        total_samples=240,
    )

    mock_assistant.interrupt(
        resume_collecting=True,
        source="wake_word",
        keyword="愛管家",
    )

    notice = mock_assistant._consume_pending_interrupt_notice()
    assert "愛管家" in notice
    assert "請先打開設定頁面" in notice

@pytest.mark.asyncio
async def test_execute_llm_request_flow(mock_assistant, mocker):
    """BUG-3: delayed SPEAKING state up until first chunker sentence."""
    mock_assistant.sm.transition(State.SENDING)
    async def mock_stream(prompt):
        yield "token1"
        yield "token2"
    mock_assistant.llm_client.send_message = mock_stream
    mock_assistant.llm_client.cancel = AsyncMock()


    mock_assistant.chunker.add_token.side_effect = [["sentence1"], ["sentence2"]]
    mock_assistant.chunker.flush.return_value = ["sentence3"]

    type(mock_assistant.audio_player).is_playing = mocker.PropertyMock(side_effect=[True, False])

    async def mock_tts_worker(q):
        while True:
            item = await q.get()
            q.task_done()
            if item is None:
                break
    mocker.patch.object(mock_assistant, "_tts_worker", side_effect=mock_tts_worker)

    await mock_assistant._execute_llm_request("hello")

    assert mock_assistant.sm.current_state == State.HOT_LISTEN

@pytest.mark.asyncio
async def test_execute_llm_request_enters_speaking_when_flush_produces_first_sentence(mock_assistant, mocker):
    mock_assistant.sm.transition(State.SENDING)

    async def mock_stream(prompt):
        yield "token1"
        yield "token2"

    async def mock_tts_worker(q):
        while True:
            item = await q.get()
            q.task_done()
            if item is None:
                break

    mock_assistant.llm_client.send_message = mock_stream
    mock_assistant.chunker.add_token.side_effect = [[], []]
    mock_assistant.chunker.flush.return_value = ["final sentence"]
    mock_assistant.audio_player.is_playing = False
    mocker.patch.object(mock_assistant, "_tts_worker", side_effect=mock_tts_worker)
    spy_update = mocker.spy(mock_assistant, "_update_state")

    await mock_assistant._execute_llm_request("hello")

    assert any(call.args == (State.SPEAKING,) for call in spy_update.call_args_list)
    assert mock_assistant.sm.current_state == State.HOT_LISTEN

@pytest.mark.asyncio
async def test_execute_llm_request_stays_idle_when_hot_listen_disabled(mock_assistant, mocker):
    mock_assistant.sm.transition(State.SENDING)

    async def mock_stream(prompt):
        yield "token1"

    async def mock_tts_worker(q):
        while True:
            item = await q.get()
            q.task_done()
            if item is None:
                break

    def config_get(section, key, default=None):
        if (section, key) == ("hot_listen", "enabled"):
            return False
        if (section, key) == ("hot_listen", "timeout_seconds"):
            return 8.0
        if (section, key) == ("llm", "response_timeout_seconds"):
            return 90.0
        return default

    mocker.patch("core.assistant.config.get", side_effect=config_get)
    mock_assistant.llm_client.send_message = mock_stream
    mock_assistant.chunker.add_token.return_value = ["sentence1"]
    mock_assistant.chunker.flush.return_value = []
    mock_assistant.audio_player.is_playing = False
    mocker.patch.object(mock_assistant, "_tts_worker", side_effect=mock_tts_worker)

    await mock_assistant._execute_llm_request("hello")

    assert mock_assistant.sm.current_state == State.IDLE_LISTEN

@pytest.mark.asyncio
async def test_execute_llm_request_interrupted_by_signal(mock_assistant, mocker):
    mock_assistant.sm.transition(State.SENDING)
    async def mock_stream(prompt):
        yield "token1"
        mock_assistant.interrupt_signal.is_set.return_value = True
        yield "token2"
    mock_assistant.llm_client.send_message = mock_stream
    mock_assistant.llm_client.cancel = AsyncMock()
    mock_assistant.chunker.add_token.side_effect = [["sentence1"], ["sentence2"]]
    mock_assistant.audio_player.is_playing = False
    mock_assistant.interrupt_signal.is_set.side_effect = [False, False, True, True, True, True, True, True]

    async def mock_tts_worker(q):
        while True:
            item = await q.get()
            q.task_done()
            if item is None:
                break
    mocker.patch.object(mock_assistant, "_tts_worker", side_effect=mock_tts_worker)

    await mock_assistant._execute_llm_request("hello")

    assert mock_assistant.llm_client.cancel.called == True


@pytest.mark.asyncio
async def test_execute_llm_request_empty_after_state_change_is_interrupted(mock_assistant, mocker):
    mock_assistant.sm.transition(State.SENDING)
    mock_assistant.llm_client.cancel = AsyncMock()
    mock_record_failure = mocker.patch.object(mock_assistant, "_record_llm_failure")
    mock_assistant._refresh_session_async = AsyncMock()
    mock_assistant.audio_player.is_playing = False

    async def stream_stopped_by_interrupt(_prompt):
        yield STREAM_ACTIVITY_KEEPALIVE
        mock_assistant.sm.transition(State.COLLECTING)

    async def mock_tts_worker(q):
        while True:
            item = await q.get()
            q.task_done()
            if item is None:
                break

    mock_assistant.llm_client.send_message = stream_stopped_by_interrupt
    mocker.patch.object(mock_assistant, "_tts_worker", side_effect=mock_tts_worker)

    await mock_assistant._execute_llm_request("hello", request_id="req-interrupted")

    mock_record_failure.assert_not_called()
    mock_assistant._refresh_session_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_llm_request_keepalive_does_not_switch_to_stream_idle_timeout(mock_assistant, mocker):
    mock_assistant.sm.transition(State.SENDING)
    mock_assistant.llm_client.cancel = AsyncMock()
    log_event = mocker.patch("core.assistant.log_event")
    mock_assistant.on_message = MagicMock()
    queued_items = []

    async def keepalive_then_response(_prompt):
        yield STREAM_ACTIVITY_KEEPALIVE
        await asyncio.sleep(0.01)
        yield "late"

    async def mock_tts_worker(q):
        while True:
            item = await q.get()
            queued_items.append(item)
            q.task_done()
            if item is None:
                break

    def config_get(section, key, default=None):
        values = {
            ("llm", "response_timeout_seconds"): 90.0,
            ("llm", "first_token_timeout_seconds"): 0.05,
            ("llm", "stream_idle_timeout_seconds"): 0.001,
            ("hot_listen", "enabled"): True,
            ("hot_listen", "timeout_seconds"): 8.0,
        }
        return values.get((section, key), default if default is not None else MagicMock())

    mocker.patch("core.assistant.config.get", side_effect=config_get)
    mock_assistant.llm_client.send_message = keepalive_then_response
    mock_assistant.chunker.add_token.return_value = ["late"]
    mock_assistant.chunker.flush.return_value = []
    mock_assistant.audio_player.is_playing = False
    mocker.patch.object(mock_assistant, "_tts_worker", side_effect=mock_tts_worker)

    await mock_assistant._execute_llm_request("hello")

    timeout_calls = [call for call in log_event.call_args_list if call.args[2] == "llm.timeout"]
    assert timeout_calls == []
    assert queued_items == ["late", None]
    assert mock_assistant.on_message.call_args_list[-1] == call("assistant", "late")

@pytest.mark.asyncio
async def test_execute_llm_request_cancel(mock_assistant, mocker):
    mock_assistant.sm.transition(State.SENDING)
    mock_assistant.llm_client.send_message.side_effect = asyncio.CancelledError()
    async def mock_tts_worker(q): pass
    mocker.patch.object(mock_assistant, "_tts_worker", side_effect=mock_tts_worker)

    with pytest.raises(asyncio.CancelledError):
        await mock_assistant._execute_llm_request("hello")

@pytest.mark.asyncio
async def test_execute_llm_request_exception(mock_assistant, mocker):
    """BUG-12 fix: when Exception happens in LLM request, assistant should reset to IDLE_LISTEN."""
    mock_assistant.sm.transition(State.SENDING)
    mock_assistant.llm_client.send_message.side_effect = Exception("error")
    mock_assistant.audio_player.is_playing = False

    async def mock_tts_worker(q): pass
    mocker.patch.object(mock_assistant, "_tts_worker", side_effect=mock_tts_worker)

    await mock_assistant._execute_llm_request("hello")
    assert mock_assistant.sm.current_state == State.IDLE_LISTEN

@pytest.mark.asyncio
async def test_execute_llm_request_exception_records_failure_and_refreshes_session(mock_assistant, mocker):
    mock_assistant.sm.transition(State.SENDING)

    async def boom(_prompt):
        raise RuntimeError("boom")
        yield ""

    mock_assistant.llm_client.send_message = boom
    mock_assistant._refresh_session_async = AsyncMock()
    mock_assistant.audio_player.is_playing = False
    mock_record_failure = mocker.patch.object(mock_assistant, "_record_llm_failure")

    async def mock_tts_worker(q):
        while True:
            item = await q.get()
            q.task_done()
            if item is None:
                break

    mocker.patch.object(mock_assistant, "_tts_worker", side_effect=mock_tts_worker)

    await mock_assistant._execute_llm_request("hello", request_id="req-1")

    mock_record_failure.assert_called_once_with(
        mode="voice",
        reason="exception:RuntimeError",
        request_id="req-1",
    )
    mock_assistant._refresh_session_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_llm_request_backend_error_output_records_failure_without_speaking_raw_error(mock_assistant, mocker):
    mock_assistant.sm.transition(State.SENDING)

    async def backend_error(_prompt):
        yield "Error: failed to send message: trajectory not found: stale-session"

    queued_items = []

    async def mock_tts_worker(q):
        while True:
            item = await q.get()
            queued_items.append(item)
            q.task_done()
            if item is None:
                break

    mock_assistant.llm_client.send_message = backend_error
    mock_assistant._refresh_session_async = AsyncMock()
    mock_assistant.on_message = MagicMock()
    mock_assistant.audio_player.is_playing = False
    mock_record_failure = mocker.patch.object(mock_assistant, "_record_llm_failure")
    mocker.patch.object(mock_assistant, "_tts_worker", side_effect=mock_tts_worker)

    await mock_assistant._execute_llm_request("hello", request_id="req-backend-error")

    mock_record_failure.assert_called_once_with(
        mode="voice",
        reason="backend_error_output:client_error_text",
        request_id="req-backend-error",
    )
    mock_assistant._refresh_session_async.assert_awaited_once()
    mock_assistant.chunker.add_token.assert_not_called()
    assert queued_items == ["抱歉，AI 後端目前連線不穩，請稍後再試一次。", None]
    assert all(
        "trajectory not found" not in call_args.args[1]
        for call_args in mock_assistant.on_message.call_args_list
    )


@pytest.mark.asyncio
async def test_execute_llm_request_timeout_uses_stream_idle_stage_and_skips_completed_log(mock_assistant, mocker):
    mock_assistant.sm.transition(State.SENDING)
    mock_assistant.llm_client.cancel = AsyncMock()
    log_event = mocker.patch("core.assistant.log_event")
    mock_assistant.on_message = MagicMock()
    queued_items = []

    async def slow_stream(_prompt):
        yield "partial"
        await asyncio.sleep(0.05)
        yield "late"

    async def mock_tts_worker(q):
        while True:
            item = await q.get()
            queued_items.append(item)
            q.task_done()
            if item is None:
                break

    def config_get(section, key, default=None):
        values = {
            ("llm", "response_timeout_seconds"): 90.0,
            ("llm", "first_token_timeout_seconds"): 90.0,
            ("llm", "stream_idle_timeout_seconds"): 0.001,
            ("hot_listen", "enabled"): True,
            ("hot_listen", "timeout_seconds"): 8.0,
        }
        return values.get((section, key), default if default is not None else MagicMock())

    mocker.patch("core.assistant.config.get", side_effect=config_get)
    mock_assistant.llm_client.send_message = slow_stream
    mock_assistant.chunker.add_token.return_value = []
    mock_assistant.chunker.flush.return_value = ["partial"]
    mock_assistant.audio_player.is_playing = False
    mocker.patch.object(mock_assistant, "_tts_worker", side_effect=mock_tts_worker)

    await mock_assistant._execute_llm_request("hello")

    timeout_calls = [call for call in log_event.call_args_list if call.args[2] == "llm.timeout"]
    completed_calls = [call for call in log_event.call_args_list if call.args[2] == "llm.completed"]
    assert timeout_calls[0].kwargs["stage"] == "stream_idle"
    assert completed_calls == []
    assert queued_items == ["partial", "我剛剛回覆到一半中斷了，請再試一次。", None]
    assert mock_assistant.on_message.call_args_list[-1] == call(
        "assistant",
        "partial\n\n我剛剛回覆到一半中斷了，請再試一次。",
    )

def test_send_text_message_rejected_while_busy(mock_assistant):
    mock_future = MagicMock()
    mock_future.done.return_value = False
    mock_assistant.state_context["current_llm_future"] = mock_future

    accepted, reason = mock_assistant.send_text_message("hello")

    assert accepted is False
    assert reason == "busy"

def test_send_text_message_rejects_empty(mock_assistant):
    accepted, reason = mock_assistant.send_text_message("   ")

    assert accepted is False
    assert reason == "empty"

def test_send_text_message_rejects_when_loop_unavailable(mock_assistant):
    mock_assistant.async_loop = None

    accepted, reason = mock_assistant.send_text_message("hello")

    assert accepted is False
    assert reason == "unavailable"

def test_send_text_message_skips_when_llm_circuit_is_open(mock_assistant):
    mock_assistant._llm_circuit_open_until = time.monotonic() + 30
    mock_assistant.on_message = MagicMock()
    mock_assistant._submit_request = MagicMock()

    accepted, reason = mock_assistant.send_text_message("hello")

    assert accepted is True
    assert reason is None
    mock_assistant._submit_request.assert_not_called()
    mock_assistant.on_message.assert_called_once_with(
        "assistant",
        "我現在連不上語言模型，先不讓你一直等，請稍後再試一次。",
        update_existing=False,
    )

def test_send_text_message_registers_request(mock_assistant):
    future = MagicMock()
    mock_assistant._submit_coroutine = _mock_submit_returning(future)
    accepted, reason = mock_assistant.send_text_message("hello")

    assert accepted is True
    assert reason is None
    assert mock_assistant.state_context["current_llm_future"] is future
    assert mock_assistant.state_context["current_llm_client"] is mock_assistant.llm_client
    mock_assistant._submit_coroutine.assert_called_once()

def test_send_text_message_clears_interrupt_signal_before_submit(mock_assistant):
    future = MagicMock()
    mock_assistant._submit_coroutine = _mock_submit_returning(future)

    accepted, reason = mock_assistant.send_text_message("hello")

    assert accepted is True
    assert reason is None
    mock_assistant.interrupt_signal.clear.assert_called_once()


@pytest.mark.asyncio
async def test_speak_standalone_clears_stale_interrupt_signal(mock_assistant):
    signal = asyncio.Event()
    signal.set()
    mock_assistant.interrupt_signal = signal
    mock_assistant.audio_player.is_playing = False

    async def fake_speak(text, audio_player, interrupt_signal):
        assert text == "我剛剛沒有聽清楚，請再說一次。"
        assert interrupt_signal is signal
        assert not interrupt_signal.is_set()

    mock_assistant.tts_engine.speak_stream = AsyncMock(side_effect=fake_speak)

    await mock_assistant._speak_standalone_message_async(
        "我剛剛沒有聽清楚，請再說一次。",
        target_state=State.IDLE_LISTEN,
    )

    assert mock_assistant.sm.current_state == State.IDLE_LISTEN
    assert not signal.is_set()


def test_perception_loop_interrupt_during_speaking(mock_assistant, mocker):
    mock_assistant.sm.transition(State.SPEAKING)
    audio_queue = MagicMock()
    mock_assistant.capture.get_audio_queue.return_value = audio_queue
    mock_assistant.running = True
    audio_queue.get.side_effect = [np.zeros(512, dtype=np.int16), queue.Empty()]

    def stop_loop(*args):
        mock_assistant.running = False
        return "愛管家"
    mock_assistant.wake_word.detect.side_effect = stop_loop

    spy_interrupt = mocker.spy(mock_assistant, "interrupt")

    mock_assistant._perception_loop()
    assert mock_assistant.sm.current_state == State.COLLECTING
    mock_assistant.audio_player.interrupt.assert_called()
    spy_interrupt.assert_called_once_with(
        resume_collecting=True,
        source="wake_word",
        keyword="愛管家",
    )

def test_perception_loop_suppresses_wake_word_interrupt_during_sending_grace(mock_assistant, mocker):
    mock_assistant.sm.transition(State.SENDING)
    mock_assistant._active_request_started_at = time.monotonic()
    mock_assistant._active_request_first_token_received = False
    audio_queue = MagicMock()
    mock_assistant.capture.get_audio_queue.return_value = audio_queue
    mock_assistant.running = True
    audio_queue.get.side_effect = [np.zeros(512, dtype=np.int16), queue.Empty()]

    def stop_loop(*args):
        mock_assistant.running = False
        return "愛管家"

    mock_assistant.wake_word.detect.side_effect = stop_loop
    spy_interrupt = mocker.spy(mock_assistant, "interrupt")

    mock_assistant._perception_loop()

    spy_interrupt.assert_not_called()
    mock_assistant.sentence_builder.add_chunk.assert_called()
    assert mock_assistant.sm.current_state == State.SENDING

def test_run_async_loop(mock_assistant, mocker):
    loop = MagicMock()
    mock_assistant.async_loop = loop

    with patch("asyncio.set_event_loop") as mock_set:
        with patch("asyncio.Event") as mock_event:
            loop.run_forever.side_effect = lambda: None
            mock_assistant._run_async_loop()
            mock_set.assert_called_with(loop)
            assert mock_assistant.interrupt_signal is not None

def test_execution_func_exception(mock_assistant, mocker):
    mock_assistant.sm.transition(State.SENDING)
    mock_assistant.transcriber.transcribe.return_value = "hello"

    def submit_raises(coro):
        coro.close()
        raise Exception("async error")

    with patch.object(mock_assistant, "_submit_coroutine", side_effect=submit_raises):
        mock_assistant._execution_func(np.zeros(16000))
        assert mock_assistant.sm.current_state == State.IDLE_LISTEN

def test_start_execution_thread(mock_assistant, mocker):
    with patch("threading.Thread") as mock_thread:
        mock_assistant._start_execution_thread(np.zeros(16000))
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()

def test_update_state_with_session_timeout(mock_assistant, mocker):
    mock_assistant.last_session_activity_time = time.time() - 600
    mock_assistant.sm.transition(State.IDLE_LISTEN)

    mocker.patch.object(mock_assistant, "_refresh_session")
    mock_assistant._update_state(State.COLLECTING)
    mock_assistant._refresh_session.assert_called_once()

def test_update_state_uses_session_activity_for_timeout(mock_assistant, mocker):
    mock_assistant.last_interaction_time = time.time() - 600
    mock_assistant.last_session_activity_time = time.time()
    mock_assistant.sm.transition(State.IDLE_LISTEN)

    mocker.patch.object(mock_assistant, "_refresh_session")
    mock_assistant._update_state(State.COLLECTING)
    mock_assistant._refresh_session.assert_not_called()

def test_refresh_session(mock_assistant, mocker):
    def config_side_effect(*args, **kwargs):
        if args == ("llm", "active_backend"): return "openclaw"
        if args == ("llm", "openclaw"): return {"api_url": "test"}
        return MagicMock()

    mocker.patch("core.assistant.config.get", side_effect=config_side_effect)
    mocker.patch("core.assistant.config.set")

    mock_assistant.llm_client.refresh_session = AsyncMock()
    mock_assistant.async_loop = MagicMock()

    mock_assistant._refresh_session()
    mock_assistant._submit_coroutine.assert_called_once()

@pytest.mark.asyncio
async def test_refresh_session_async_notifies_ui_after_success(mock_assistant, mocker):
    callback = MagicMock()
    mock_assistant.set_callbacks(None, None, callback)
    mock_assistant.llm_client.refresh_session = AsyncMock(return_value=True)
    mocker.patch("core.assistant.config.get", side_effect=lambda section, key, default=None: "codex_cli" if (section, key) == ("llm", "active_backend") else default)

    refreshed = await mock_assistant._refresh_session_async()

    assert refreshed is True
    callback.assert_called_once_with()

@pytest.mark.asyncio
async def test_refresh_session_async_does_not_notify_ui_when_refresh_did_not_change_session(mock_assistant, mocker):
    callback = MagicMock()
    mock_assistant.set_callbacks(None, None, callback)
    mock_assistant.llm_client.refresh_session = AsyncMock(return_value=False)
    mocker.patch("core.assistant.config.get", side_effect=lambda section, key, default=None: "codex_cli" if (section, key) == ("llm", "active_backend") else default)

    refreshed = await mock_assistant._refresh_session_async()

    assert refreshed is False
    callback.assert_not_called()

def test_refresh_session_does_not_write_runtime_session_state(mock_assistant, mocker):
    def config_side_effect(*args, **kwargs):
        if args == ("llm", "active_backend"):
            return "codex_cli"
        if args == ("llm", "codex_cli"):
            return {"thread_id": "thread-old"}
        return MagicMock()

    mocker.patch("core.assistant.config.get", side_effect=config_side_effect)
    mock_set = mocker.patch("core.assistant.config.set")

    mock_assistant.llm_client.refresh_session = AsyncMock()
    mock_assistant.async_loop = MagicMock()

    mock_assistant._refresh_session()

    runtime_state_calls = [
        call_args for call_args in mock_set.call_args_list
        if call_args.args[:3] in {
            ("llm", "codex_cli", "thread_id"),
            ("llm", "gemini_cli", "session_id"),
        }
    ]
    assert runtime_state_calls == []
    mock_assistant._submit_coroutine.assert_called_once()

def test_refresh_session_recreates_client_when_refresh_missing(mock_assistant, mocker):
    replacement = MagicMock(spec=BaseLLMClient)
    mocker.patch.object(mock_assistant, "_create_current_llm_client", return_value=replacement)
    mock_assistant.llm_client = MagicMock(spec=["aclose"])
    spy_close = mocker.spy(mock_assistant, "_close_llm_client")
    session_callback = MagicMock()
    mock_assistant.set_callbacks(None, None, session_callback)

    mock_assistant._refresh_session()

    assert mock_assistant.llm_client is replacement
    spy_close.assert_called_once()
    session_callback.assert_called_once_with()

def test_refresh_session_recreates_client_when_backend_uses_base_refresh(mock_assistant, mocker):
    class DummyClient(BaseLLMClient):
        async def send_message(self, text):
            if False:
                yield text

        async def cancel(self):
            return None

    replacement = MagicMock(spec=BaseLLMClient)
    mocker.patch.object(mock_assistant, "_create_current_llm_client", return_value=replacement)
    mock_assistant.llm_client = DummyClient()
    spy_close = mocker.spy(mock_assistant, "_close_llm_client")

    mock_assistant._refresh_session()

    assert mock_assistant.llm_client is replacement
    spy_close.assert_called_once()

def test_assistant_resolves_wake_word_paths_relative_to_app_dir(mocker):
    mocker.patch("core.assistant.AudioCapture")
    mocker.patch("core.assistant.AudioPlayer")
    mocker.patch("core.assistant.VoiceActivityDetector")
    mocker.patch("core.assistant.BackgroundTranscriber")
    wake_word_cls = mocker.patch("core.assistant.WakeWordDetector")
    mocker.patch("core.assistant.SentenceBuilder")
    mocker.patch("core.assistant.create_llm_client")
    mocker.patch("core.assistant.SemanticChunker")
    mocker.patch("core.assistant.EdgeTTSEngine")
    mocker.patch("core.assistant.WhisperAudioArchive")
    mocker.patch("core.assistant.SpeakerRecognizer")

    def config_get(section, key, default=None):
        values = {
            ("audio", "input_sample_rate"): 16000,
            ("audio", "output_sample_rate"): 24000,
            ("audio", "input_block_size"): 512,
            ("audio", "output_block_size"): 512,
            ("vad", "threshold"): 0.5,
            ("vad", "min_silence_duration_ms"): 1500,
            ("vad", "speech_pad_ms"): 30,
            ("whisper", "model_size"): "tiny",
            ("whisper", "device"): "cpu",
            ("whisper", "compute_type"): "int8",
            ("whisper", "language"): "zh",
            ("whisper", "initial_prompt"): "",
            ("whisper_audio_archive", "enabled"): False,
            ("speaker_recognition", "enabled"): False,
            ("wake_word", "model_dir"): "models",
            ("semantic_chunker", "split_punctuation"): [],
            ("semantic_chunker", "also_split"): [],
            ("tts", "voice"): "test_voice",
            ("tts", "rate"): "+0%",
            ("tts", "volume"): "+0%",
            ("hot_listen", "enabled"): True,
            ("hot_listen", "timeout_seconds"): 8.0,
            ("llm", "active_backend"): "openclaw",
            ("llm", "openclaw"): {},
            ("llm", "codex_cli"): {},
        }
        return values.get((section, key), default)

    mocker.patch("core.assistant.config.get", side_effect=config_get)
    mocker.patch("asyncio.new_event_loop", return_value=MagicMock())

    assistant = VoiceAssistant()

    wake_kwargs = wake_word_cls.call_args.kwargs
    assert wake_kwargs["keywords_file"].endswith("ai_voice_assistant\\keywords.txt")
    assert wake_kwargs["model_dir"].endswith("ai_voice_assistant\\models")
    assert os.path.isabs(wake_kwargs["keywords_file"])
    assert os.path.isabs(wake_kwargs["model_dir"])

def test_set_voice_disabled_interrupts_collecting_and_resets_to_idle(mock_assistant, mocker):
    mock_assistant.sm.transition(State.COLLECTING)
    spy_interrupt = mocker.spy(mock_assistant, "interrupt")

    mock_assistant.set_voice_enabled(False)

    assert mock_assistant.voice_paused is True
    assert mock_assistant.sm.current_state == State.IDLE_LISTEN
    spy_interrupt.assert_called_once_with()


def test_set_voice_enabled_leaves_idle_ready_state(mock_assistant):
    mock_assistant.voice_paused = True

    mock_assistant.set_voice_enabled(True)

    assert mock_assistant.voice_paused is False
    assert mock_assistant.sm.current_state == State.IDLE_LISTEN

def test_on_user_activity_ignored_when_voice_paused(mock_assistant):
    spy_mark_present = MagicMock(wraps=mock_assistant.presence_tracker.mark_present)
    mock_assistant.presence_tracker.mark_present = spy_mark_present
    mock_assistant.voice_paused = True

    triggered = mock_assistant.on_user_activity("keyboard")

    assert triggered is False
    spy_mark_present.assert_called_once_with("keyboard")
    mock_assistant._submit_coroutine.assert_not_called()

def test_apply_hot_listen_settings_disables_hot_listen_and_exits_state(mock_assistant, mocker):
    def config_get(section, key, default=None):
        if (section, key) == ("hot_listen", "enabled"):
            return False
        if (section, key) == ("hot_listen", "timeout_seconds"):
            return 8.0
        return default

    mocker.patch("core.assistant.config.get", side_effect=config_get)
    mock_assistant.sm.transition(State.HOT_LISTEN)

    mock_assistant.apply_hot_listen_settings()

    assert mock_assistant.sm.hot_listen_timeout == 0.0
    assert mock_assistant.sm.current_state == State.IDLE_LISTEN


def test_effective_hot_listen_timeout_clamps_unbounded_config(mock_assistant, mocker):
    def config_get(section, key, default=None):
        if (section, key) == ("hot_listen", "enabled"):
            return True
        if (section, key) == ("hot_listen", "timeout_seconds"):
            return 10**80
        return default

    mocker.patch("core.assistant.config.get", side_effect=config_get)

    mock_assistant.apply_hot_listen_settings()

    assert mock_assistant.sm.hot_listen_timeout == 60.0


def test_apply_heartbeat_settings_starts_scheduler_when_enabled(mock_assistant, mocker):
    def config_get(section, key, default=None):
        if (section, key) == ("heartbeat", "enabled"):
            return True
        if (section, key) == ("heartbeat", "interval_minutes"):
            return 15
        return default

    mocker.patch("core.assistant.config.get", side_effect=config_get)
    mock_assistant.heartbeat.is_enabled = False

    mock_assistant.apply_heartbeat_settings()

    assert mock_assistant.heartbeat.interval_seconds == 900.0
    mock_assistant.heartbeat.start.assert_called_once_with(mock_assistant.async_loop)
    mock_assistant.heartbeat.stop.assert_not_called()


def test_apply_heartbeat_settings_stops_scheduler_when_disabled(mock_assistant, mocker):
    def config_get(section, key, default=None):
        if (section, key) == ("heartbeat", "enabled"):
            return False
        if (section, key) == ("heartbeat", "interval_minutes"):
            return 10
        return default

    mocker.patch("core.assistant.config.get", side_effect=config_get)
    mock_assistant._request_heartbeat_cancel = MagicMock(return_value=True)
    mock_assistant.heartbeat.is_enabled = True

    mock_assistant.apply_heartbeat_settings()

    mock_assistant._request_heartbeat_cancel.assert_called_once()
    mock_assistant.heartbeat.stop.assert_called_once_with(mock_assistant.async_loop)
    mock_assistant.heartbeat.start.assert_not_called()


def test_heartbeat_active_window_is_daytime_only(mock_assistant):
    assert VoiceAssistant._heartbeat_within_active_window(datetime(2026, 4, 20, 8, 0, 0))
    assert VoiceAssistant._heartbeat_within_active_window(datetime(2026, 4, 20, 20, 59, 59))
    assert not VoiceAssistant._heartbeat_within_active_window(datetime(2026, 4, 20, 7, 59, 59))
    assert not VoiceAssistant._heartbeat_within_active_window(datetime(2026, 4, 20, 21, 0, 0))

def test_begin_manual_capture_transitions_to_collecting(mock_assistant):
    started = mock_assistant.begin_manual_capture()

    assert started is True
    assert mock_assistant.sm.current_state == State.COLLECTING
    assert mock_assistant._collecting_started_at > 0
    assert mock_assistant.is_vad_speaking is False
    mock_assistant.sentence_builder.reset.assert_called_once_with(clear_pre_roll=True)
    mock_assistant.vad.reset_states.assert_called_once()

def test_begin_manual_capture_rejected_when_voice_paused(mock_assistant):
    mock_assistant.voice_paused = True

    started = mock_assistant.begin_manual_capture()

    assert started is False
    assert mock_assistant.sm.current_state == State.IDLE_LISTEN

def test_update_vad_min_silence_resets_sentence_collection(mock_assistant):
    mock_assistant.update_vad_min_silence(600)

    mock_assistant.vad.update_min_silence_duration.assert_called_once_with(600)
    mock_assistant.sentence_builder.reset.assert_called()
    assert mock_assistant.is_vad_speaking is False

def test_update_tts_settings_delegates_to_engine(mock_assistant):
    mock_assistant.update_tts_settings(rate="+20%", volume="+10%")

    mock_assistant.tts_engine.update_settings.assert_called_once_with(
        voice=None,
        rate="+20%",
        volume="+10%",
    )

def test_on_user_activity_ignored_when_not_idle(mock_assistant):
    mock_assistant.sm.transition(State.HOT_LISTEN)

    triggered = mock_assistant.on_user_activity("keyboard")

    assert triggered is False
    mock_assistant._submit_coroutine.assert_not_called()

def test_on_user_activity_ignored_when_hot_listen_disabled(mock_assistant, mocker):
    def config_get(section, key, default=None):
        if (section, key) == ("hot_listen", "enabled"):
            return False
        if (section, key) == ("user_activity_prompt", "enabled"):
            return True
        return default

    mocker.patch("core.assistant.config.get", side_effect=config_get)

    triggered = mock_assistant.on_user_activity("keyboard")

    assert triggered is False
    mock_assistant._submit_coroutine.assert_not_called()


def test_on_user_activity_marks_presence_when_prompt_disabled(mock_assistant, mocker):
    def config_get(section, key, default=None):
        if (section, key) == ("user_activity_prompt", "enabled"):
            return False
        if (section, key) == ("presence_detection", "input_triggers_presence"):
            return True
        if (section, key) == ("hot_listen", "enabled"):
            return True
        return default

    mocker.patch("core.assistant.config.get", side_effect=config_get)
    spy_mark_present = MagicMock(wraps=mock_assistant.presence_tracker.mark_present)
    mock_assistant.presence_tracker.mark_present = spy_mark_present

    triggered = mock_assistant.on_user_activity("keyboard")

    assert triggered is False
    spy_mark_present.assert_called_once_with("keyboard")
    mock_assistant._submit_coroutine.assert_not_called()

def test_on_user_activity_registers_local_prompt(mock_assistant, mocker):
    mocker.patch(
        "core.assistant.config.get",
        side_effect=lambda *args, **kwargs: (
            True if args == ("user_activity_prompt", "enabled") else
            "請問有甚麼事嗎？" if args == ("user_activity_prompt", "text") else
            8.0 if "timeout" in str(args) else
            MagicMock()
        ),
    )
    submitted = []

    def capture_submit(coro):
        submitted.append(coro)
        coro.close()
        return MagicMock()

    mock_assistant._submit_coroutine = MagicMock(side_effect=capture_submit)

    triggered = mock_assistant.on_user_activity("keyboard")

    assert triggered is True
    assert mock_assistant.user_activity_prompt_active is True
    mock_assistant._submit_coroutine.assert_called_once()
    assert submitted


def test_can_change_backend_returns_false_during_heartbeat(mock_assistant):
    mock_assistant._heartbeat_active = True

    assert mock_assistant.can_change_backend() is False


def test_perception_loop_marks_presence_on_vad_start(mock_assistant):
    spy_mark_present = MagicMock(wraps=mock_assistant.presence_tracker.mark_present)
    mock_assistant.presence_tracker.mark_present = spy_mark_present
    audio_queue = MagicMock()
    mock_assistant.capture.get_audio_queue.return_value = audio_queue
    mock_assistant.running = True
    audio_queue.get.side_effect = [np.zeros(512, dtype=np.int16), queue.Empty()]
    mock_assistant.vad.process_chunk.side_effect = [{"start": True}]
    mock_assistant.wake_word.detect.side_effect = lambda *_args: setattr(mock_assistant, "running", False)
    mock_assistant.sentence_builder.add_chunk.return_value = None

    mock_assistant._perception_loop()

    spy_mark_present.assert_called_once_with("audio")


def test_update_state_hot_listen_starts_audio_guard_and_clears_queue(mock_assistant):
    audio_queue = queue.Queue()
    audio_queue.put(np.zeros(512, dtype=np.int16))
    audio_queue.put(np.ones(512, dtype=np.int16))
    mock_assistant.capture.get_audio_queue.return_value = audio_queue
    mock_assistant.sentence_builder.reset.reset_mock()
    mock_assistant.vad.reset_states.reset_mock()

    mock_assistant._update_state(State.HOT_LISTEN)

    assert mock_assistant.sm.current_state == State.HOT_LISTEN
    assert audio_queue.empty()
    assert mock_assistant._audio_input_guard_active() is True
    mock_assistant.sentence_builder.reset.assert_called_once_with(clear_pre_roll=True)
    mock_assistant.vad.reset_states.assert_called_once()


def test_perception_loop_discards_audio_during_input_guard(mock_assistant):
    audio_queue = MagicMock()
    mock_assistant.capture.get_audio_queue.return_value = audio_queue
    mock_assistant.running = True
    mock_assistant._ignore_audio_until = time.monotonic() + 10.0

    def return_guarded_chunk(*args, **kwargs):
        mock_assistant.running = False
        return np.zeros(512, dtype=np.int16)

    audio_queue.get.side_effect = return_guarded_chunk

    mock_assistant._perception_loop()

    mock_assistant.vad.process_chunk.assert_not_called()
    mock_assistant.wake_word.detect.assert_not_called()
    mock_assistant.sentence_builder.add_chunk.assert_not_called()


def test_parse_heartbeat_response_truncates_long_speech(mock_assistant):
    action, spoken_text = mock_assistant._parse_heartbeat_response("a" * 240)

    assert action == "speak"
    assert len(spoken_text) == 200
    assert spoken_text.endswith("…")


@pytest.mark.asyncio
async def test_submit_request_preempts_active_heartbeat(mock_assistant):
    mock_assistant._submit_coroutine = lambda coro: asyncio.create_task(coro)
    mock_assistant._heartbeat_active = True
    mock_assistant._heartbeat_cancel_event = asyncio.Event()

    async def release_heartbeat():
        await asyncio.sleep(0.01)
        mock_assistant._heartbeat_active = False

    asyncio.create_task(release_heartbeat())

    future = mock_assistant._submit_request(asyncio.sleep(0), mock_assistant.llm_client)
    await future

    assert mock_assistant._heartbeat_cancel_event.is_set()
    mock_assistant.llm_client.cancel.assert_awaited()


@pytest.mark.asyncio
async def test_heartbeat_skipped_when_not_idle(mock_assistant):
    mock_assistant.running = True
    mock_assistant.sm.transition(State.HOT_LISTEN)
    mock_assistant.on_message = MagicMock()
    mock_assistant.llm_client.send_message = MagicMock()

    await mock_assistant._on_heartbeat_fire()

    mock_assistant.llm_client.send_message.assert_not_called()
    mock_assistant.on_message.assert_not_called()


@pytest.mark.asyncio
async def test_heartbeat_skipped_outside_active_hours(mock_assistant, mocker):
    mock_assistant.running = True
    mock_assistant.on_message = MagicMock()
    mock_assistant.llm_client.send_message = MagicMock()
    mocker.patch.object(
        mock_assistant,
        "_heartbeat_within_active_window",
        return_value=False,
    )

    await mock_assistant._on_heartbeat_fire()

    mock_assistant.llm_client.send_message.assert_not_called()
    mock_assistant.on_message.assert_not_called()


@pytest.mark.asyncio
async def test_heartbeat_skipped_when_circuit_open(mock_assistant):
    mock_assistant.running = True
    mock_assistant._llm_circuit_open_until = time.monotonic() + 30
    mock_assistant.on_message = MagicMock()
    mock_assistant.llm_client.send_message = MagicMock()

    await mock_assistant._on_heartbeat_fire()

    mock_assistant.llm_client.send_message.assert_not_called()
    mock_assistant.on_message.assert_not_called()


@pytest.mark.asyncio
async def test_heartbeat_nop_has_no_side_effects(mock_assistant):
    async def gen():
        yield "[HEARTBEAT_NOP]"

    mock_assistant.running = True
    mock_assistant.on_message = MagicMock()
    mock_assistant.llm_client.send_message = MagicMock(return_value=gen())
    mock_assistant._speak_standalone_message_async = AsyncMock()

    await mock_assistant._on_heartbeat_fire()

    mock_assistant.on_message.assert_not_called()
    mock_assistant._speak_standalone_message_async.assert_not_called()


@pytest.mark.asyncio
async def test_heartbeat_nop_does_not_update_last_interaction_time(mock_assistant):
    async def gen():
        yield "[HEARTBEAT_NOP]"

    mock_assistant.running = True
    mock_assistant.llm_client.send_message = MagicMock(return_value=gen())
    mock_assistant._refresh_session_async = AsyncMock()
    previous_interaction_time = time.time() - 600
    mock_assistant.last_interaction_time = previous_interaction_time

    await mock_assistant._on_heartbeat_fire()

    assert mock_assistant.last_interaction_time == previous_interaction_time
    assert mock_assistant._heartbeat_consecutive_nop_count == 1


@pytest.mark.asyncio
async def test_heartbeat_refreshes_session_after_three_consecutive_nops(mock_assistant):
    async def gen():
        yield "[HEARTBEAT_NOP]"

    mock_assistant.running = True
    mock_assistant.llm_client.send_message = MagicMock(side_effect=[gen(), gen(), gen()])
    mock_assistant._refresh_session_async = AsyncMock()

    await mock_assistant._on_heartbeat_fire()
    await mock_assistant._on_heartbeat_fire()
    await mock_assistant._on_heartbeat_fire()

    mock_assistant._refresh_session_async.assert_awaited_once()
    assert mock_assistant._heartbeat_consecutive_nop_count == 0


@pytest.mark.asyncio
async def test_heartbeat_speak_downgrades_to_ui_without_presence(mock_assistant):
    async def gen():
        yield "記得喝水。"

    mock_assistant.running = True
    mock_assistant.on_message = MagicMock()
    mock_assistant.llm_client.send_message = MagicMock(return_value=gen())
    mock_assistant.presence_tracker.is_present = MagicMock(return_value=False)
    mock_assistant._speak_standalone_message_async = AsyncMock()

    await mock_assistant._on_heartbeat_fire()

    mock_assistant.on_message.assert_called_once_with(
        "assistant",
        "記得喝水。",
        update_existing=False,
    )
    mock_assistant._speak_standalone_message_async.assert_not_called()
    assert mock_assistant._last_heartbeat_speak_time > 0


@pytest.mark.asyncio
async def test_heartbeat_speak_in_text_mode_is_ui_only(mock_assistant):
    async def gen():
        yield "晚點記得看看行事曆。"

    mock_assistant.running = True
    mock_assistant.voice_paused = True
    mock_assistant.on_message = MagicMock()
    mock_assistant.llm_client.send_message = MagicMock(return_value=gen())
    mock_assistant.presence_tracker.is_present = MagicMock(return_value=True)
    mock_assistant._speak_standalone_message_async = AsyncMock()

    await mock_assistant._on_heartbeat_fire()

    mock_assistant.on_message.assert_called_once_with(
        "assistant",
        "晚點記得看看行事曆。",
        update_existing=False,
    )
    mock_assistant._speak_standalone_message_async.assert_not_called()


@pytest.mark.asyncio
async def test_heartbeat_speak_uses_tts_and_enters_hot_listen(mock_assistant):
    async def gen():
        yield "五分鐘後要出門囉。"

    async def fake_speak(text, target_state=State.IDLE_LISTEN):
        mock_assistant.sm.transition(target_state)

    mock_assistant.running = True
    mock_assistant.on_message = MagicMock()
    mock_assistant.llm_client.send_message = MagicMock(return_value=gen())
    mock_assistant.presence_tracker.is_present = MagicMock(return_value=True)
    mock_assistant._speak_standalone_message_async = AsyncMock(side_effect=fake_speak)

    await mock_assistant._on_heartbeat_fire()

    mock_assistant.on_message.assert_called_once_with(
        "assistant",
        "五分鐘後要出門囉。",
        update_existing=False,
    )
    mock_assistant._speak_standalone_message_async.assert_awaited_once_with(
        "五分鐘後要出門囉。",
        target_state=State.HOT_LISTEN,
    )
    assert mock_assistant.sm.current_state == State.HOT_LISTEN


@pytest.mark.asyncio
async def test_heartbeat_speak_is_throttled(mock_assistant):
    async def gen():
        yield "該起來活動一下了。"

    mock_assistant.running = True
    mock_assistant.on_message = MagicMock()
    mock_assistant.llm_client.send_message = MagicMock(return_value=gen())
    mock_assistant.presence_tracker.is_present = MagicMock(return_value=True)
    mock_assistant._speak_standalone_message_async = AsyncMock()
    mock_assistant._last_heartbeat_speak_time = time.time()

    await mock_assistant._on_heartbeat_fire()

    mock_assistant.on_message.assert_not_called()
    mock_assistant._speak_standalone_message_async.assert_not_called()


@pytest.mark.asyncio
async def test_heartbeat_backend_error_output_records_failure_without_speaking(mock_assistant, mocker):
    async def gen():
        yield "Error: failed to send message: trajectory not found: stale-session"

    mock_assistant.running = True
    mock_assistant.on_message = MagicMock()
    mock_assistant.llm_client.send_message = MagicMock(return_value=gen())
    mock_assistant._speak_standalone_message_async = AsyncMock()
    spy_record_failure = mocker.spy(mock_assistant, "_record_llm_failure")

    await mock_assistant._on_heartbeat_fire()

    spy_record_failure.assert_called_once_with(
        mode="heartbeat",
        reason="backend_error_output:client_error_text",
        request_id=ANY,
    )
    mock_assistant.on_message.assert_not_called()
    mock_assistant._speak_standalone_message_async.assert_not_called()


@pytest.mark.asyncio
async def test_preempt_heartbeat_timeout_is_bounded_when_cancel_hangs(mock_assistant, mocker):
    cancel_cleaned = asyncio.Event()

    async def stuck_cancel():
        try:
            await asyncio.Future()
        finally:
            cancel_cleaned.set()

    mocker.patch("core.assistant._HEARTBEAT_PREEMPT_TIMEOUT", 0.05)
    mock_assistant._heartbeat_active = True
    mock_assistant._heartbeat_cancel_event = asyncio.Event()
    mock_assistant.llm_client.cancel = AsyncMock(side_effect=stuck_cancel)

    started_at = time.monotonic()
    await mock_assistant._preempt_heartbeat_if_needed()
    elapsed = time.monotonic() - started_at

    assert elapsed < 0.2
    assert mock_assistant._heartbeat_cancel_event.is_set() is True
    await asyncio.wait_for(cancel_cleaned.wait(), timeout=0.1)


@pytest.mark.asyncio
async def test_heartbeat_cancelled_cleans_up_generator(mock_assistant):
    class ControlledAsyncGen:
        def __init__(self):
            self.closed = False

        async def __anext__(self):
            await asyncio.sleep(0)
            raise StopAsyncIteration

        async def aclose(self):
            self.closed = True

    gen = ControlledAsyncGen()
    mock_assistant._heartbeat_cancel_event = asyncio.Event()
    mock_assistant._heartbeat_cancel_event.set()
    mock_assistant.llm_client.send_message = MagicMock(return_value=gen)

    await mock_assistant._execute_heartbeat_request("hb-test")

    assert gen.closed is True
    mock_assistant.llm_client.cancel.assert_awaited()


@pytest.mark.asyncio
async def test_build_heartbeat_prompt_uses_configured_interval(mock_assistant, mocker):
    mocker.patch.object(mock_assistant, "_resolve_heartbeat_interval_seconds", return_value=180.0)

    prompt = mock_assistant._build_heartbeat_prompt()

    assert "每3分鐘" in prompt
    assert "若附近可能無人" in prompt
    assert "[HEARTBEAT_NOP]" in prompt
    assert "[HEARTBEAT_SILENT]" in prompt
    assert "Heartbeat checks must be read-only" in prompt
    assert "Do not run shell commands, tests" in prompt


@pytest.mark.asyncio
async def test_heartbeat_failure_recorded_once(mock_assistant, mocker):
    class FailingAsyncGen:
        async def __anext__(self):
            raise RuntimeError("boom")

        async def aclose(self):
            return None

    mock_assistant.llm_client.send_message = MagicMock(return_value=FailingAsyncGen())
    spy_record_failure = mocker.spy(mock_assistant, "_record_llm_failure")

    await mock_assistant._execute_heartbeat_request("hb-fail")

    spy_record_failure.assert_called_once_with(
        mode="heartbeat",
        reason="exception:RuntimeError",
        request_id="hb-fail",
    )

@pytest.mark.asyncio
async def test_speak_prompt_and_enter_hot_listen_success(mock_assistant, mocker):
    mock_assistant.audio_player.is_playing = False
    mock_assistant.user_activity_prompt_active = True
    mock_assistant.user_activity_interrupt_signal.is_set.return_value = False
    mock_assistant.tts_engine.speak_stream = AsyncMock()
    mock_assistant.on_message = MagicMock()

    await mock_assistant._speak_prompt_and_enter_hot_listen("請問有甚麼事嗎？")

    mock_assistant.on_message.assert_called_once_with("assistant", "請問有甚麼事嗎？")
    mock_assistant.audio_player.reset_interrupt.assert_called_once()
    mock_assistant.tts_engine.speak_stream.assert_awaited_once()
    assert mock_assistant.sm.current_state == State.HOT_LISTEN
    assert mock_assistant.user_activity_prompt_active is False

@pytest.mark.asyncio
async def test_speak_prompt_and_enter_hot_listen_respects_hot_listen_toggle(mock_assistant, mocker):
    mock_assistant.audio_player.is_playing = False
    mock_assistant.user_activity_prompt_active = True
    mock_assistant.user_activity_interrupt_signal.is_set.return_value = False
    mock_assistant.tts_engine.speak_stream = AsyncMock()

    def config_get(section, key, default=None):
        if (section, key) == ("hot_listen", "enabled"):
            return False
        return default

    mocker.patch("core.assistant.config.get", side_effect=config_get)

    await mock_assistant._speak_prompt_and_enter_hot_listen("請問有甚麼事嗎？")

    assert mock_assistant.sm.current_state == State.IDLE_LISTEN
    assert mock_assistant.user_activity_prompt_active is False

@pytest.mark.asyncio
async def test_speak_prompt_and_enter_hot_listen_skips_transition_when_state_changes(mock_assistant):
    mock_assistant.audio_player.is_playing = False
    mock_assistant.user_activity_prompt_active = True

    async def fake_speak(*args, **kwargs):
        mock_assistant.sm.transition(State.COLLECTING)

    mock_assistant.tts_engine.speak_stream = AsyncMock(side_effect=fake_speak)

    await mock_assistant._speak_prompt_and_enter_hot_listen("請問有甚麼事嗎？")

    assert mock_assistant.sm.current_state == State.COLLECTING
    assert mock_assistant.user_activity_prompt_active is False

@pytest.mark.asyncio
async def test_execute_text_llm_request_success(mock_assistant):
    async def stream(_prompt):
        yield "hello"
        yield " world"

    messages = []
    mock_assistant.llm_client.send_message = stream
    mock_assistant.on_message = MagicMock(side_effect=lambda role, text: messages.append((role, text)))

    await mock_assistant._execute_text_llm_request("hello")

    assert messages[-1] == ("assistant", "hello world")
    assert mock_assistant.sm.current_state == State.IDLE_LISTEN

@pytest.mark.asyncio
async def test_execute_text_llm_request_includes_interrupt_notice(mock_assistant, mocker):
    prompts = []

    async def stream(prompt):
        prompts.append(prompt)
        if False:
            yield ""

    mock_assistant.llm_client.send_message = stream
    mock_assistant.on_message = MagicMock()
    mocker.patch.object(
        mock_assistant,
        "_consume_pending_interrupt_notice",
        return_value="上一輪語音回覆在播放途中被打斷。",
    )

    await mock_assistant._execute_text_llm_request("hello")

    assert "上一輪語音回覆在播放途中被打斷。" in prompts[0]
    assert "hello" in prompts[0]

@pytest.mark.asyncio
async def test_execute_text_llm_request_failure_reports_error(mock_assistant):
    mock_assistant.llm_client.send_message = MagicMock(side_effect=Exception("boom"))
    mock_assistant.on_message = MagicMock()

    await mock_assistant._execute_text_llm_request("hello")

    mock_assistant.on_message.assert_called()
    assert mock_assistant.sm.current_state == State.IDLE_LISTEN

@pytest.mark.asyncio
async def test_execute_text_llm_request_timeout_cancels_client(mock_assistant, mocker):
    mock_assistant.llm_client.cancel = AsyncMock()
    log_event = mocker.patch("core.assistant.log_event")

    async def slow_stream(_prompt):
        yield "partial"
        await asyncio.sleep(0.05)
        yield "late"

    mock_assistant.llm_client.send_message = slow_stream
    mock_assistant.on_message = MagicMock()

    def config_get(section, key, default=None):
        values = {
            ("llm", "response_timeout_seconds"): 90.0,
            ("llm", "first_token_timeout_seconds"): 90.0,
            ("llm", "stream_idle_timeout_seconds"): 0.001,
        }
        return values.get((section, key), default if default is not None else MagicMock())

    with patch("core.assistant.config.get", side_effect=config_get):
        await mock_assistant._execute_text_llm_request("hello")

    mock_assistant.llm_client.cancel.assert_called_once()
    assert mock_assistant.sm.current_state == State.IDLE_LISTEN
    timeout_calls = [call for call in log_event.call_args_list if call.args[2] == "llm.timeout"]
    completed_calls = [call for call in log_event.call_args_list if call.args[2] == "llm.completed"]
    assert timeout_calls[0].kwargs["stage"] == "stream_idle"
    assert completed_calls == []

@pytest.mark.asyncio
async def test_speak_prompt_and_enter_hot_listen_success(mock_assistant):
    prompt_text = "prompt"
    mock_assistant.audio_player.is_playing = False
    mock_assistant.user_activity_prompt_active = True
    mock_assistant.user_activity_interrupt_signal.is_set.return_value = False
    mock_assistant.tts_engine.speak_stream = AsyncMock()
    mock_assistant.on_message = MagicMock()

    await mock_assistant._speak_prompt_and_enter_hot_listen(prompt_text)

    assert mock_assistant.on_message.call_count == 1
    assert mock_assistant.on_message.call_args.args == ("assistant", prompt_text)
    assert mock_assistant.on_message.call_args.kwargs == {"update_existing": False}
    mock_assistant.audio_player.reset_interrupt.assert_called_once()
    mock_assistant.tts_engine.speak_stream.assert_awaited_once()
    assert mock_assistant.sm.current_state == State.HOT_LISTEN
    assert mock_assistant.user_activity_prompt_active is False

