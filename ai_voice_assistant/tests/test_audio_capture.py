import pytest
import numpy as np
import queue
from unittest.mock import patch, MagicMock
from core.audio_capture import AudioCapture, _QUEUE_MAXSIZE

@patch("core.audio_capture.sd.InputStream")
def test_audio_capture_start_stop(mock_input_stream):
    mock_stream_instance = MagicMock()
    mock_input_stream.return_value = mock_stream_instance

    capture = AudioCapture(sample_rate=16000, blocksize=512)
    assert capture.audio_queue.maxsize == _QUEUE_MAXSIZE


    capture.start()
    mock_input_stream.assert_called_once()
    mock_stream_instance.start.assert_called_once()


    capture.start()
    assert mock_input_stream.call_count == 1


    test_data = np.zeros((512, 1), dtype=np.int16)
    capture._input_callback(test_data, 512, None, None)


    capture._input_callback(test_data, 512, None, "overflow")

    q = capture.get_audio_queue()
    assert q.qsize() == 2
    np.testing.assert_array_equal(q.get(), test_data)
    np.testing.assert_array_equal(q.get(), test_data)
    assert capture.drain_status_events() == [("portaudio", "overflow")]


    capture.stop()
    mock_stream_instance.stop.assert_called_once()
    mock_stream_instance.close.assert_called_once()
    assert capture.stream is None

def test_audio_capture_queue_full_eviction():
    """BUG-7/O-5 fix: when queue is full, oldest item evicted, new item accepted."""
    capture = AudioCapture(sample_rate=16000, blocksize=512)

    old_data = np.ones((512, 1), dtype=np.int16) * 1
    new_data = np.ones((512, 1), dtype=np.int16) * 99


    for _ in range(_QUEUE_MAXSIZE):
        capture.audio_queue.put_nowait(old_data.copy())


    capture._input_callback(new_data, 512, None, None)

    assert capture.audio_queue.full()
    items = []
    while not capture.audio_queue.empty():
        items.append(capture.audio_queue.get_nowait())


    assert np.array_equal(items[-1], new_data)

@patch("core.audio_capture.sd.InputStream")
def test_audio_capture_start_exception(mock_input_stream):
    mock_input_stream.side_effect = Exception("Sounddevice Error")
    capture = AudioCapture()
    with pytest.raises(Exception):
        capture.start()

def test_audio_capture_stop_no_stream():
    """stop() should be safe to call when stream is None."""
    capture = AudioCapture()
    capture.stop()

def test_audio_capture_get_queue_type():
    capture = AudioCapture()
    q = capture.get_audio_queue()
    assert isinstance(q, queue.Queue)
    assert q.maxsize == _QUEUE_MAXSIZE

