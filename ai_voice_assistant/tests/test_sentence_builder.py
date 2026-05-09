import numpy as np
import pytest
from core.sentence_builder import SentenceBuilder

def test_init():
    builder = SentenceBuilder()
    assert builder.is_speaking is False
    assert builder.speech_buffer == []

def test_add_chunk_no_event():
    builder = SentenceBuilder()
    chunk = np.zeros(160, dtype=np.int16)

    result = builder.add_chunk(chunk, None)
    assert result is None
    assert len(builder.speech_buffer) == 0
    assert builder.is_speaking is False

def test_add_chunk_start_event():
    builder = SentenceBuilder()
    chunk = np.ones(160, dtype=np.int16)

    result = builder.add_chunk(chunk, {'start': 1.0})
    assert result is None
    assert builder.is_speaking is True
    assert len(builder.speech_buffer) == 1
    np.testing.assert_array_equal(builder.speech_buffer[0], chunk)

def test_add_chunk_start_event_already_speaking():
    builder = SentenceBuilder()
    builder.is_speaking = True
    builder.speech_buffer = [np.ones(160, dtype=np.int16)]

    chunk = np.zeros(160, dtype=np.int16)
    result = builder.add_chunk(chunk, {'start': 1.0})

    assert result is None
    assert builder.is_speaking is True

    assert len(builder.speech_buffer) == 1

def test_add_chunk_while_speaking_no_event():
    builder = SentenceBuilder()
    builder.is_speaking = True
    builder.speech_buffer = [np.ones((160, 1), dtype=np.int16)]

    chunk = np.zeros((160, 1), dtype=np.int16)
    result = builder.add_chunk(chunk, None)

    assert result is None
    assert builder.is_speaking is True
    assert len(builder.speech_buffer) == 2

def test_add_chunk_end_event():
    builder = SentenceBuilder()
    builder.is_speaking = True
    chunk1 = np.ones((160, 1), dtype=np.int16)
    builder.speech_buffer = [chunk1]

    chunk2 = np.ones((160, 1), dtype=np.int16) * 2

    result = builder.add_chunk(chunk2, {'end': 2.0})

    assert builder.is_speaking is False
    assert len(builder.speech_buffer) == 0
    assert result is not None
    assert result.ndim == 1
    assert len(result) == 320


    expected = np.concatenate([np.ones(160), np.ones(160)*2]).astype(np.float32) / 32768.0
    np.testing.assert_array_equal(result, expected)

def test_add_chunk_end_event_empty_buffer():
    builder = SentenceBuilder()
    builder.is_speaking = True
    builder.speech_buffer = []

    chunk2 = np.zeros(0, dtype=np.int16)
    result = builder.add_chunk(chunk2, {'end': 2.0})





    assert builder.is_speaking is False
    assert result is not None
    assert len(result) == 0

def test_add_chunk_end_event_not_speaking():
    builder = SentenceBuilder()
    builder.is_speaking = False

    chunk = np.ones(160, dtype=np.int16)
    result = builder.add_chunk(chunk, {'end': 2.0})

    assert result is None
    assert builder.is_speaking is False
    assert len(builder.speech_buffer) == 0

def test_reset():
    builder = SentenceBuilder()
    builder.is_speaking = True
    builder.speech_buffer = [np.ones(160, dtype=np.int16)]
    builder.pre_roll_buffer.append(np.zeros(160, dtype=np.int16))

    builder.reset()
    assert builder.is_speaking is False
    assert builder.speech_buffer == []
    assert len(builder.pre_roll_buffer) == 1

def test_reset_can_clear_pre_roll():
    builder = SentenceBuilder()
    builder.is_speaking = True
    builder.speech_buffer = [np.ones(160, dtype=np.int16)]
    builder.pre_roll_buffer.append(np.zeros(160, dtype=np.int16))

    builder.reset(clear_pre_roll=True)
    assert builder.is_speaking is False
    assert builder.speech_buffer == []
    assert len(builder.pre_roll_buffer) == 0

def test_is_empty():
    builder = SentenceBuilder()
    assert builder.is_empty() is True
    builder.speech_buffer = [np.ones(160, dtype=np.int16)]
    assert builder.is_empty() is False

def test_has_partial_audio():
    builder = SentenceBuilder()
    assert builder.has_partial_audio() is False
    builder.speech_buffer = [np.ones(160, dtype=np.int16)]
    assert builder.has_partial_audio() is True

def test_flush_partial_returns_audio_and_resets_state():
    builder = SentenceBuilder()
    builder.is_speaking = True
    builder.speech_buffer = [
        np.ones(160, dtype=np.int16),
        np.ones(160, dtype=np.int16) * 2,
    ]

    result = builder.flush_partial()

    expected = np.concatenate([np.ones(160), np.ones(160) * 2]).astype(np.float32) / 32768.0
    np.testing.assert_array_equal(result, expected)
    assert builder.is_speaking is False
    assert builder.speech_buffer == []

def test_flush_partial_without_audio_returns_none():
    builder = SentenceBuilder()
    builder.is_speaking = True

    result = builder.flush_partial()

    assert result is None
    assert builder.is_speaking is False

def test_pre_roll_buffer_usage():
    builder = SentenceBuilder(pre_roll_ms=64, chunk_ms=32)
    chunk1 = np.ones(160, dtype=np.int16) * 1
    chunk2 = np.ones(160, dtype=np.int16) * 2
    chunk3 = np.ones(160, dtype=np.int16) * 3

    builder.add_chunk(chunk1, None)
    builder.add_chunk(chunk2, None)
    assert len(builder.pre_roll_buffer) == 2

    builder.add_chunk(chunk3, None)
    assert len(builder.pre_roll_buffer) == 2
    np.testing.assert_array_equal(builder.pre_roll_buffer[0], chunk2)
    np.testing.assert_array_equal(builder.pre_roll_buffer[1], chunk3)

    chunk_start = np.ones(160, dtype=np.int16) * 4
    builder.add_chunk(chunk_start, {'start': 1.0})

    assert builder.is_speaking is True
    assert len(builder.speech_buffer) == 3
    np.testing.assert_array_equal(builder.speech_buffer[0], chunk2)
    np.testing.assert_array_equal(builder.speech_buffer[1], chunk3)
    np.testing.assert_array_equal(builder.speech_buffer[2], chunk_start)
    assert len(builder.pre_roll_buffer) == 0

