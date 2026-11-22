from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
import numpy as np
import sounddevice as sd
from unittest.mock import MagicMock, patch
from core.audio_player import (
    AudioPlayer,
    PlaybackBoundary,
    PlaybackChunk,
    PlaybackChunkMetadata,
)

@pytest.fixture
def mock_sd_output_stream(mocker):
    return mocker.patch("sounddevice.OutputStream")

def test_audio_player_init():
    player = AudioPlayer(sample_rate=24000, channels=1, blocksize=1024)
    assert player.sample_rate == 24000
    assert player.channels == 1
    assert player.blocksize == 1024
    assert player.interrupt_flag is False

def test_audio_player_start(mock_sd_output_stream):
    player = AudioPlayer()
    player.start()
    mock_sd_output_stream.assert_called_once()
    assert player.stream is not None
    assert player.interrupt_flag is False

def test_audio_player_stop(mock_sd_output_stream):
    player = AudioPlayer()
    player.start()
    player.stop()
    assert player.stream is None

def test_audio_player_play():
    player = AudioPlayer()
    data = np.zeros(1024, dtype=np.int16)
    player.play(data)
    assert player.playback_queue.get_nowait() is data

def test_audio_player_play_interrupted(mocker):
    logger_mock = mocker.patch("core.audio_player.logger")
    player = AudioPlayer()
    player.interrupt_flag = True
    player.play(np.zeros(1024, dtype=np.int16))
    assert player.playback_queue.empty()
    logger_mock.warning.assert_called_with("Interrupt flag is set, ignoring play request.")

def test_audio_player_interrupt(mock_sd_output_stream):
    """BUG-2 fix: interrupt() sets flag + clears queue but does NOT call stop().
    Stream stops itself via CallbackStop -> _on_stream_finished."""
    player = AudioPlayer()
    player.start()
    player.play(np.zeros(1024, dtype=np.int16))
    player.interrupt()
    assert player.interrupt_flag is True
    assert player.playback_queue.empty()
    assert player._residual_data is None

    assert player.stream is not None

def test_interrupt_drains_audio_from_an_inflight_queue_write(mocker):
    player = AudioPlayer(max_queue_chunks=1)
    player.stream = MagicMock()
    put_started = Event()
    finish_put = Event()
    queue_put = player.playback_queue.put

    def delayed_put(*args, **kwargs):
        put_started.set()
        assert finish_put.wait(timeout=2)
        queue_put(*args, **kwargs)

    mocker.patch.object(player.playback_queue, "put", side_effect=delayed_put)
    # Resume the in-flight write when interruption reaches residual cleanup.
    residual_lock = mocker.patch.object(player, "_residual_lock")
    residual_lock.__enter__.side_effect = finish_put.set
    with ThreadPoolExecutor(max_workers=1) as executor:
        write = executor.submit(player.play, np.ones(8, dtype=np.int16), response_generation=0)
        assert put_started.wait(timeout=2)
        player.interrupt()
        write.result(timeout=2)

    outdata = np.ones((4, 1), dtype=np.int16)
    with pytest.raises(sd.CallbackStop):
        player._output_callback(outdata, 4, None, sd.CallbackFlags())
    player._on_stream_finished()

    assert not np.any(outdata)
    assert player.playback_queue.empty()
    assert not player.is_playing


def test_interrupt_frees_capacity_for_blocked_audio_producer(mocker):
    player = AudioPlayer(max_queue_chunks=1, queue_put_timeout_seconds=3)
    pcm = np.ones(4, dtype=np.int16)
    assert player.play(pcm)
    put_started = Event()
    put = player.playback_queue.put

    def mark_put(*args, **kwargs):
        put_started.set()
        put(*args, **kwargs)

    mocker.patch.object(player.playback_queue, "put", side_effect=mark_put)
    with ThreadPoolExecutor(max_workers=1) as pool:
        producer = pool.submit(player.play, pcm)
        assert put_started.wait(timeout=2)
        player.interrupt()
        assert producer.result(timeout=2)

    assert player.playback_queue.empty()
    assert player.queue_overflow_count == 0


def test_audio_player_interrupt_no_stream():
    player = AudioPlayer()
    player.stream = None
    player.interrupt()
    assert player.interrupt_flag is True
    assert player.software_silent_at is not None


def test_audio_player_interrupt_with_active_stream_waits_for_callback():
    player = AudioPlayer()
    player.stream = MagicMock()

    player.interrupt()

    assert player.software_silent_at is None
    outdata = np.ones((1024, 1), dtype=np.int16)
    with pytest.raises(sd.CallbackStop):
        player._output_callback(outdata, 1024, None, sd.CallbackFlags())
    assert player.software_silent_at is not None
    assert np.all(outdata == 0)

def test_audio_player_interrupt_returns_progress_snapshot():
    player = AudioPlayer(blocksize=256)
    metadata = PlaybackChunkMetadata(
        sentence_id="sentence-1",
        sentence_text="你好世界",
        boundaries=(
            PlaybackBoundary(text="你好", start_sample=0, end_sample=256),
            PlaybackBoundary(text="世界", start_sample=256, end_sample=512),
        ),
        start_sample=0,
        total_samples=512,
    )
    player.play(
        PlaybackChunk(
            pcm_data=np.ones(512, dtype=np.int16),
            metadata=metadata,
        )
    )

    outdata = np.zeros((256, 1), dtype=np.int16)
    player._output_callback(outdata, 256, None, sd.CallbackFlags())
    snapshot = player.interrupt()

    assert snapshot is not None
    assert snapshot.sentence_text == "你好世界"
    assert snapshot.heard_text == "你好"

def test_on_stream_finished(mock_sd_output_stream):
    """_on_stream_finished should nil out stream so reset_interrupt can restart."""
    player = AudioPlayer()
    player.start()
    assert player.stream is not None
    player._on_stream_finished()
    assert player.stream is None


def test_old_stream_finished_callback_does_not_clear_new_stream():
    player = AudioPlayer()
    old_stream = MagicMock()
    new_stream = MagicMock()
    player.stream = new_stream

    player._on_stream_finished(old_stream)

    assert player.stream is new_stream

def test_audio_player_reset_interrupt(mock_sd_output_stream):
    """reset_interrupt should clear flag and start a fresh stream."""
    player = AudioPlayer()
    player.interrupt_flag = True
    player.stream = None
    player.reset_interrupt()
    assert player.interrupt_flag is False
    assert player.stream is not None

def test_audio_player_reset_interrupt_force_close(mock_sd_output_stream):
    """reset_interrupt force-closes existing stream before restarting."""
    player = AudioPlayer()
    player.start()
    player.interrupt_flag = True

    player.reset_interrupt()
    assert player.interrupt_flag is False


def test_audio_player_reset_interrupt_closes_stream_when_stop_fails(mock_sd_output_stream):
    player = AudioPlayer()
    stale_stream = MagicMock()
    stale_stream.stop.side_effect = RuntimeError("stop failed")
    player.stream = stale_stream

    player.reset_interrupt()

    stale_stream.close.assert_called_once()
    assert player.stream is not stale_stream

def test_output_callback_normal():
    player = AudioPlayer(blocksize=512)
    outdata = np.zeros((512, 1), dtype=np.int16)
    pcm_data = np.ones(512, dtype=np.int16) * 100
    player.play(pcm_data)
    player._output_callback(outdata, 512, None, sd.CallbackFlags())
    assert np.array_equal(outdata.flatten(), pcm_data)
    assert player._residual_data is None

def test_output_callback_with_residual():
    player = AudioPlayer(blocksize=256)
    outdata = np.zeros((256, 1), dtype=np.int16)
    pcm_data = np.ones(512, dtype=np.int16) * 100
    player.play(pcm_data)
    player._output_callback(outdata, 256, None, sd.CallbackFlags())
    assert np.all(outdata == 100)
    assert len(player._residual_data) == 256
    outdata.fill(0)
    player._output_callback(outdata, 256, None, sd.CallbackFlags())
    assert np.all(outdata == 100)
    assert player._residual_data is None

def test_output_callback_and_interrupt_use_residual_lock():
    class RecordingLock:
        def __init__(self):
            self.enter_count = 0

        def __enter__(self):
            self.enter_count += 1

        def __exit__(self, exc_type, exc, tb):
            return False

    player = AudioPlayer(blocksize=256)
    recording_lock = RecordingLock()
    player._residual_lock = recording_lock
    player.play(np.ones(512, dtype=np.int16))

    outdata = np.zeros((256, 1), dtype=np.int16)
    player._output_callback(outdata, 256, None, sd.CallbackFlags())
    player.interrupt()

    assert recording_lock.enter_count >= 2
    assert player._residual_data is None

def test_output_callback_with_none_marker():
    player = AudioPlayer(blocksize=512)
    outdata = np.zeros((512, 1), dtype=np.int16)
    player.playback_queue.put(None)
    player._output_callback(outdata, 512, None, sd.CallbackFlags())
    assert np.all(outdata == 0)

def test_output_callback_interrupt():
    """BUG-2 fix: should now raise CallbackStop (not CallbackAbort) for graceful stop."""
    player = AudioPlayer()
    player.interrupt_flag = True
    outdata = np.zeros((1024, 1), dtype=np.int16)
    with pytest.raises(sd.CallbackStop):
        player._output_callback(outdata, 1024, None, sd.CallbackFlags())

    assert np.all(outdata == 0)

def test_interrupt_discards_audio_dequeued_by_the_callback(mocker):
    player = AudioPlayer()
    player.play(np.ones(8, dtype=np.int16))
    normalize = player._normalize_payload

    def interrupt_before_storing_residual(payload):
        player.interrupt()
        return normalize(payload)

    mocker.patch.object(player, "_normalize_payload", side_effect=interrupt_before_storing_residual)
    outdata = np.ones((4, 1), dtype=np.int16)
    with pytest.raises(sd.CallbackStop):
        player._output_callback(outdata, 4, None, sd.CallbackFlags())

    assert not np.any(outdata)
    assert player._residual_data is None
    assert not player.is_playing


@pytest.mark.parametrize("action", ["interrupt", "invalidate_generation"])
def test_output_callback_silences_audio_invalidated_during_copy(mocker, action):
    player = AudioPlayer()
    player.play(np.ones(4, dtype=np.int16))
    mocker.patch.object(
        player, "_advance_playback_progress",
        side_effect=lambda *_args: getattr(player, action)(),
    )
    outdata = np.empty((4, 1), dtype=np.int16)

    if action == "interrupt":
        with pytest.raises(sd.CallbackStop):
            player._output_callback(outdata, 4, None, sd.CallbackFlags())
        assert player.software_silent_at is not None
    else:
        player._output_callback(outdata, 4, None, sd.CallbackFlags())

    assert not np.any(outdata)
    assert player.first_nonzero_pcm_at is None
    assert player.is_playing is False


def test_output_callback_empty_queue():
    player = AudioPlayer()
    outdata = np.ones((1024, 1), dtype=np.int16)
    player._output_callback(outdata, 1024, None, sd.CallbackFlags())
    assert np.all(outdata == 0)

def test_output_callback_status_warning(mocker):
    logger_mock = mocker.patch("core.audio_player.logger")
    player = AudioPlayer()
    outdata = np.zeros((1024, 1), dtype=np.int16)
    status = sd.CallbackFlags()
    status.output_underflow = True
    player._output_callback(outdata, 1024, None, status)
    logger_mock.warning.assert_not_called()
    assert player.drain_status_events() == ["output underflow"]

def test_audio_player_start_already_running(mock_sd_output_stream, mocker):
    logger_mock = mocker.patch("core.audio_player.logger")
    player = AudioPlayer()
    player.start()
    player.start()
    logger_mock.warning.assert_called_with("Audio player is already running.")

def test_audio_player_start_exception(mocker):
    mocker.patch("sounddevice.OutputStream", side_effect=Exception("Hardware error"))
    player = AudioPlayer()
    with pytest.raises(Exception, match="Hardware error"):
        player.start()

def test_audio_player_stop_exception(mocker):
    player = AudioPlayer()
    stream = mocker.Mock()
    stream.stop.side_effect = Exception("Stop error")
    player.stream = stream
    player.stop()
    stream.close.assert_called_once()
    assert player.stream is None

def test_is_playing_false_when_empty():
    player = AudioPlayer()
    assert player.is_playing is False

def test_is_playing_true_when_residual():
    player = AudioPlayer()
    player._residual_data = np.zeros(10, dtype=np.int16)
    assert player.is_playing is True

def test_is_playing_true_when_queue_not_empty():
    player = AudioPlayer()
    player.playback_queue.put(np.zeros(10, dtype=np.int16))
    assert player.is_playing is True

def test_is_playing_stays_true_until_last_buffer_has_finished():
    player = AudioPlayer(sample_rate=1000, blocksize=4)
    player.play(np.arange(4, dtype=np.int16))
    outdata = np.zeros((4, 1), dtype=np.int16)

    with patch("core.audio_player.time.monotonic", side_effect=[10.0, 10.001]):
        player._output_callback(outdata, 4, None, sd.CallbackFlags())
        assert player.is_playing is True

    with patch("core.audio_player.time.monotonic", return_value=10.01):
        assert player.is_playing is False


def test_generation_aware_player_drops_stale_chunk_before_queueing():
    player = AudioPlayer(max_queue_chunks=2)
    player.set_response_generation(4)

    accepted = player.play(
        PlaybackChunk(
            pcm_data=np.ones(4, dtype=np.int16),
            response_generation=3,
        )
    )

    assert accepted is False
    assert player.playback_queue.empty()
    assert player.stale_chunk_drop_count == 1


def test_bounded_playback_queue_rejects_overflow():
    player = AudioPlayer(max_queue_chunks=1, queue_put_timeout_seconds=0)

    assert player.play(np.ones(4, dtype=np.int16)) is True
    assert player.play(np.ones(4, dtype=np.int16)) is False
    assert player.queue_overflow_count == 1


def test_output_callback_discards_chunk_that_became_stale_after_queueing():
    player = AudioPlayer()
    player.set_response_generation(1)
    player.play(
        PlaybackChunk(
            pcm_data=np.ones(4, dtype=np.int16),
            response_generation=1,
        )
    )
    player.set_response_generation(2)
    outdata = np.ones((4, 1), dtype=np.int16)

    player._output_callback(outdata, 4, None, sd.CallbackFlags())

    assert np.all(outdata == 0)
    assert player.stale_chunk_drop_count == 1


def test_output_callback_discards_raw_audio_generation_after_queueing():
    player = AudioPlayer()
    player.set_response_generation(1)
    player.play(np.ones(4, dtype=np.int16), response_generation=1)
    player.set_response_generation(2)
    outdata = np.ones((4, 1), dtype=np.int16)

    player._output_callback(outdata, 4, None, sd.CallbackFlags())

    assert np.all(outdata == 0)
    assert player.stale_chunk_drop_count == 1


def test_output_callback_discards_residual_from_previous_generation():
    player = AudioPlayer()
    player.set_response_generation(1)
    player.play(np.ones(8, dtype=np.int16), response_generation=1)
    outdata = np.zeros((4, 1), dtype=np.int16)
    player._output_callback(outdata, 4, None, sd.CallbackFlags())
    assert np.all(outdata == 1)
    player.set_response_generation(2)

    player._output_callback(outdata, 4, None, sd.CallbackFlags())

    assert np.all(outdata == 0)
    assert player._residual_data is None


def test_cancelled_progress_drops_residual_and_late_audio_but_keeps_same_turn_answer():
    player = AudioPlayer()
    player.set_response_generation(1)
    signal = Event()
    progress = PlaybackChunk(np.ones(8, dtype=np.int16), response_generation=1, cancel_signal=signal)
    assert player.play(progress)
    assert player.play(progress)
    out = np.empty((4, 1), dtype=np.int16)
    player._output_callback(out, 4, None, sd.CallbackFlags())
    assert out[:, 0].tolist() == [1, 1, 1, 1]

    signal.set()
    assert not player.play(progress)
    assert player.play(np.full(4, 2, dtype=np.int16), response_generation=1)
    player._output_callback(out, 4, None, sd.CallbackFlags())
    assert out[:, 0].tolist() == [2, 2, 2, 2]
    assert player.response_generation == 1


def test_progress_cancelled_during_callback_does_not_erase_answer_in_same_buffer():
    player = AudioPlayer()
    signal = Event()
    assert player.play(PlaybackChunk(np.ones(2, dtype=np.int16), cancel_signal=signal))
    assert player.play(np.full(2, 2, dtype=np.int16))
    out = np.empty((4, 1), dtype=np.int16)
    with patch.object(player, "_advance_playback_progress", side_effect=lambda *_: signal.set()):
        player._output_callback(out, 4, None, sd.CallbackFlags())
    assert out[:, 0].tolist() == [0, 0, 2, 2]


def test_old_callback_leaves_new_generation_audio_for_next_buffer():
    player = AudioPlayer()
    player.set_response_generation(1)
    assert player.play(np.ones(2, dtype=np.int16), response_generation=1)

    def start_new_response(*_args):
        player.set_response_generation(2)
        assert player.play(np.full(4, 2, dtype=np.int16), response_generation=2)

    outdata = np.empty((4, 1), dtype=np.int16)
    with patch.object(
        player, "_advance_playback_progress", side_effect=start_new_response
    ):
        player._output_callback(outdata, 4, None, sd.CallbackFlags())
    assert not np.any(outdata)

    player._output_callback(outdata, 4, None, sd.CallbackFlags())
    assert np.all(outdata == 2)


@pytest.mark.parametrize("cleanup", ["reset_interrupt", "stop"])
def test_finished_stream_is_closed_during_cleanup(mock_sd_output_stream, cleanup):
    player = AudioPlayer()
    player.start()
    old_stream = player.stream
    player.interrupt()
    mock_sd_output_stream.call_args.kwargs["finished_callback"]()
    assert player.stream is None
    old_stream.close.assert_not_called()

    getattr(player, cleanup)()

    old_stream.close.assert_called_once()


def test_unmute_does_not_warn_when_stream_is_already_running(mock_sd_output_stream, mocker):
    logger_mock = mocker.patch("core.audio_player.logger")
    player = AudioPlayer()
    player.start()

    player.set_muted(True)
    player.set_muted(False)

    assert player.muted is False
    assert player.stream is not None
    logger_mock.warning.assert_not_called()
