import pytest
import numpy as np
import torch
from unittest.mock import patch, MagicMock, mock_open

from core.vad import VADIterator


class _ProbabilityModel:
    def __init__(self, probabilities):
        self._probabilities = iter(probabilities)
        self.reset_count = 0

    def reset_states(self):
        self.reset_count += 1

    def __call__(self, _chunk, _sampling_rate):
        return torch.tensor(next(self._probabilities), dtype=torch.float32)


def test_vad_iterator_emits_start_and_end_samples():
    model = _ProbabilityModel([0.8, 0.1, 0.1, 0.1])
    iterator = VADIterator(
        model,
        sampling_rate=16000,
        min_silence_duration_ms=64,
        speech_pad_ms=30,
    )
    chunk = np.zeros(512, dtype=np.float32)

    assert iterator(chunk) == {"start": 0}
    assert iterator(chunk) is None
    assert iterator(chunk) is None
    assert iterator(chunk) == {"end": 992}
    assert iterator.triggered is False


def test_vad_iterator_clears_pending_end_when_speech_resumes():
    model = _ProbabilityModel([0.8, 0.1, 0.8])
    iterator = VADIterator(model, sampling_rate=16000, min_silence_duration_ms=500)
    chunk = np.zeros(512, dtype=np.float32)

    assert iterator(chunk) == {"start": 0}
    assert iterator(chunk) is None
    assert iterator.temp_end != 0
    assert iterator(chunk) is None
    assert iterator.temp_end == 0
    assert iterator.triggered is True


def test_vad_iterator_rejects_unsupported_sample_rate():
    with pytest.raises(ValueError, match="8000 or 16000"):
        VADIterator(_ProbabilityModel([]), sampling_rate=44100)


@patch("core.vad.open", new_callable=mock_open)
@patch("core.vad.torch.jit.load")
@patch("core.vad.VADIterator")
def test_vad_initialization_and_process(mock_vad_iterator_class, mock_jit_load, mock_file_open):
    mock_model = MagicMock()
    mock_jit_load.return_value = mock_model

    mock_iterator_instance = MagicMock()

    mock_iterator_instance.side_effect = [{'start': 0.1}, {'end': 0.5}]
    mock_vad_iterator_class.return_value = mock_iterator_instance
    mock_file_open.return_value.read.return_value = b"fake_bytes"

    from core.vad import VoiceActivityDetector
    vad = VoiceActivityDetector(threshold=0.5, sampling_rate=16000, min_silence_duration_ms=500)

    assert vad.sampling_rate == 16000
    mock_jit_load.assert_called_once()
    mock_model.eval.assert_called_once()


    chunk_2d = np.zeros((512, 1), dtype=np.int16)
    result = vad.process_chunk(chunk_2d)
    assert result == {'start': 0.1}

    mock_iterator_instance.reset_states.assert_not_called()


    chunk_1d = np.zeros((512,), dtype=np.int16)
    result2 = vad.process_chunk(chunk_1d)
    assert result2 == {'end': 0.5}

    mock_iterator_instance.reset_states.assert_called_once()

@patch("core.vad.open", new_callable=mock_open)
@patch("core.vad.torch.jit.load")
@patch("core.vad.VADIterator")
def test_vad_manual_reset(mock_vad_iterator_class, mock_jit_load, mock_file_open):
    """reset_states() public method delegates to VADIterator.reset_states()."""
    mock_model = MagicMock()
    mock_jit_load.return_value = mock_model
    mock_iterator_instance = MagicMock()
    mock_vad_iterator_class.return_value = mock_iterator_instance
    mock_file_open.return_value.read.return_value = b"fake_bytes"

    from core.vad import VoiceActivityDetector
    vad = VoiceActivityDetector()
    vad.reset_states()
    mock_iterator_instance.reset_states.assert_called_once()

@patch("core.vad.open", new_callable=mock_open)
@patch("core.vad.torch.jit.load")
@patch("core.vad.VADIterator")
def test_vad_no_reset_on_none_event(mock_vad_iterator_class, mock_jit_load, mock_file_open):
    """process_chunk returning None event should NOT call reset_states."""
    mock_model = MagicMock()
    mock_jit_load.return_value = mock_model
    mock_iterator_instance = MagicMock()
    mock_iterator_instance.return_value = None
    mock_vad_iterator_class.return_value = mock_iterator_instance
    mock_file_open.return_value.read.return_value = b"fake_bytes"

    from core.vad import VoiceActivityDetector
    vad = VoiceActivityDetector()
    result = vad.process_chunk(np.zeros(512, dtype=np.int16))
    assert result is None
    mock_iterator_instance.reset_states.assert_not_called()

@patch("core.vad.open", new_callable=mock_open)
@patch("core.vad.torch.jit.load")
@patch("core.vad.VADIterator")
def test_vad_update_min_silence_rebuilds_iterator(mock_vad_iterator_class, mock_jit_load, mock_file_open):
    mock_model = MagicMock()
    mock_jit_load.return_value = mock_model
    first_iterator = MagicMock()
    second_iterator = MagicMock()
    mock_vad_iterator_class.side_effect = [first_iterator, second_iterator]
    mock_file_open.return_value.read.return_value = b"fake_bytes"

    from core.vad import VoiceActivityDetector

    vad = VoiceActivityDetector(min_silence_duration_ms=500)
    vad.update_min_silence_duration(300)

    assert vad.min_silence_duration_ms == 300
    assert vad.vad_iterator is second_iterator
    assert mock_vad_iterator_class.call_args_list[0].kwargs["min_silence_duration_ms"] == 500
    assert mock_vad_iterator_class.call_args_list[1].kwargs["min_silence_duration_ms"] == 300

