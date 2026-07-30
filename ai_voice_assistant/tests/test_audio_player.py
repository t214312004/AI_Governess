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
