import pytest
import asyncio
import numpy as np
import io
from core.audio_player import PlaybackChunk
from tts.edge_tts_engine import EdgeTTSEngine, sanitize_edge_tts_text

class MockAudioPlayer:
    def __init__(self):
        self.played_data = []
    def play(self, data):
        self.played_data.append(data)

class MockCommunicate:
    """Mocked edge-tts Communicate that yields audio chunks."""
    def __init__(self, audio_chunks=None, include_non_audio=False, metadata_chunks=None):
        self.audio_chunks = audio_chunks or []
        self.include_non_audio = include_non_audio
        self.metadata_chunks = metadata_chunks or []

    async def stream(self):
        if self.include_non_audio:
            yield {"type": "metadata", "data": "info"}
        for chunk in self.metadata_chunks:
            yield chunk
        for chunk in self.audio_chunks:
            yield {"type": "audio", "data": chunk}

@pytest.fixture
def tts_engine():
    return EdgeTTSEngine()



@pytest.mark.asyncio
async def test_speak_stream_success(mocker, tts_engine):
    """speak_stream should call play() with decoded PCM data after full stream."""
    chunk = b"\x00" * 1024
    mocker.patch("edge_tts.Communicate", return_value=MockCommunicate([chunk]))

    mock_frame = mocker.Mock()
    mock_frame.to_ndarray.return_value = np.zeros((1, 1024), dtype=np.int16)
    mock_container = mocker.Mock()
    mock_container.decode.return_value = [mock_frame]
    mocker.patch("av.open", return_value=mock_container)

    player = MockAudioPlayer()
    await tts_engine.speak_stream("你好", player)
    assert len(player.played_data) > 0
    assert isinstance(player.played_data[0], PlaybackChunk)

@pytest.mark.asyncio
async def test_speak_stream_interrupt_before_audio(mocker, tts_engine):
    """interrupt_signal set before streaming starts → no audio played."""
    interrupt_signal = asyncio.Event()
    interrupt_signal.set()
    mocker.patch("edge_tts.Communicate", return_value=MockCommunicate([b"data"]))
    player = MockAudioPlayer()
    await tts_engine.speak_stream("你好", player, interrupt_signal)
    assert len(player.played_data) == 0

@pytest.mark.asyncio
async def test_speak_stream_no_audio_chunks(mocker, tts_engine):
    """No audio chunks at all → play() never called."""
    mocker.patch("edge_tts.Communicate", return_value=MockCommunicate([]))
    player = MockAudioPlayer()
    await tts_engine.speak_stream("你好", player)
    assert len(player.played_data) == 0

@pytest.mark.asyncio
async def test_speak_stream_non_audio_chunks_ignored(mocker, tts_engine):
    """Non-audio chunks (metadata) should be silently ignored."""
    mocker.patch("edge_tts.Communicate", return_value=MockCommunicate([], include_non_audio=True))
    player = MockAudioPlayer()
    await tts_engine.speak_stream("你好", player)
    assert len(player.played_data) == 0

@pytest.mark.asyncio
async def test_speak_stream_attaches_word_boundaries(mocker, tts_engine):
    chunk = b"\x00" * 1024
    mocker.patch(
        "edge_tts.Communicate",
        return_value=MockCommunicate(
            [chunk],
            metadata_chunks=[
                {
                    "type": "WordBoundary",
                    "offset": 0,
                    "duration": 5_000_000,
                    "text": "你好",
                }
            ],
        ),
    )

    mock_frame = mocker.Mock()
    mock_frame.to_ndarray.return_value = np.zeros((1, 1024), dtype=np.int16)
    mock_container = mocker.Mock()
    mock_container.decode.return_value = [mock_frame]
    mocker.patch("av.open", return_value=mock_container)

    player = MockAudioPlayer()
    await tts_engine.speak_stream("你好", player)

    played_chunk = player.played_data[0]
    assert isinstance(played_chunk, PlaybackChunk)
    assert played_chunk.metadata is not None
    assert played_chunk.metadata.sentence_text == "你好"
    assert played_chunk.metadata.boundaries[0].text == "你好"

@pytest.mark.asyncio
async def test_speak_stream_exception(mocker, tts_engine):
    """Exception during streaming should be logged AND re-raised (Fix #9)."""
    mocker.patch("edge_tts.Communicate", side_effect=Exception("Stream error"))
    logger_mock = mocker.patch("tts.edge_tts_engine.logger")
    with pytest.raises(Exception, match="Stream error"):
        await tts_engine.speak_stream("你好", MockAudioPlayer())
    logger_mock.error.assert_called()

@pytest.mark.asyncio
async def test_speak_stream_retries_transient_error_then_succeeds(mocker, tts_engine):
    chunk = b"\x00" * 1024
    attempts = {"count": 0}

    def build_communicate(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ConnectionError("temporary network error")
        return MockCommunicate([chunk])

    mocker.patch("edge_tts.Communicate", side_effect=build_communicate)
    log_event = mocker.patch("tts.edge_tts_engine.log_event")
    sleep_mock = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)

    mock_frame = mocker.Mock()
    mock_frame.to_ndarray.return_value = np.zeros((1, 1024), dtype=np.int16)
    mock_container = mocker.Mock()
    mock_container.decode.return_value = [mock_frame]
    mocker.patch("av.open", return_value=mock_container)

    player = MockAudioPlayer()
    await tts_engine.speak_stream("測試文字", player)

    assert attempts["count"] == 3
    assert len(player.played_data) > 0
    retry_calls = [call for call in log_event.call_args_list if call.args[2] == "tts.retry_scheduled"]
    assert len(retry_calls) == 2
    assert sleep_mock.await_count == 2

@pytest.mark.asyncio
async def test_speak_stream_skips_sentence_after_retry_exhausted(mocker, tts_engine):
    mocker.patch("edge_tts.Communicate", side_effect=ConnectionError("temporary network error"))
    log_event = mocker.patch("tts.edge_tts_engine.log_event")
    sleep_mock = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
    player = MockAudioPlayer()

    await tts_engine.speak_stream("測試文字", player)

    assert len(player.played_data) == 0
    retry_calls = [call for call in log_event.call_args_list if call.args[2] == "tts.retry_scheduled"]
    failed_calls = [call for call in log_event.call_args_list if call.args[2] == "tts.sentence_failed"]
    assert len(retry_calls) == 2
    assert len(failed_calls) == 1
    assert sleep_mock.await_count == 2



def test_try_decode_partial_empty(tts_engine):
    """Empty input → empty list returned immediately."""
    result = tts_engine._try_decode_partial(b"")
    assert result == []

def test_try_decode_partial_invalid_data(tts_engine):
    """Invalid MP3 data → PyAV fails silently, empty list returned."""
    result = tts_engine._try_decode_partial(b"not_valid_mp3_data_at_all")
    assert isinstance(result, list)

def test_try_decode_partial_float32_conversion(mocker, tts_engine):
    """float32 PCM frames should be converted to int16."""
    mock_frame = mocker.Mock()
    mock_frame.to_ndarray.return_value = np.array([[0.5, -0.5]], dtype=np.float32)
    mock_container = mocker.Mock()
    mock_container.decode.return_value = [mock_frame]
    mocker.patch("av.open", return_value=mock_container)

    result = tts_engine._try_decode_partial(b"fake_data")
    assert len(result) == 1
    assert result[0].dtype == np.int16

def test_try_decode_partial_float64_conversion(mocker, tts_engine):
    """float64 PCM frames should also be converted to int16."""
    mock_frame = mocker.Mock()
    mock_frame.to_ndarray.return_value = np.array([[0.1, -0.1]], dtype=np.float64)
    mock_container = mocker.Mock()
    mock_container.decode.return_value = [mock_frame]
    mocker.patch("av.open", return_value=mock_container)

    result = tts_engine._try_decode_partial(b"fake_data")
    assert result[0].dtype == np.int16

def test_try_decode_partial_int16_passthrough(mocker, tts_engine):
    """int16 PCM frames should not be converted (passthrough)."""
    mock_frame = mocker.Mock()
    mock_frame.to_ndarray.return_value = np.zeros((1, 512), dtype=np.int16)
    mock_container = mocker.Mock()
    mock_container.decode.return_value = [mock_frame]
    mocker.patch("av.open", return_value=mock_container)

    result = tts_engine._try_decode_partial(b"fake_data")
    assert result[0].dtype == np.int16
    assert result[0].shape == (512,)

def test_try_decode_partial_other_dtype_conversion(mocker, tts_engine):
    """Non-float, non-int16 dtypes should be cast to int16."""
    mock_frame = mocker.Mock()
    mock_frame.to_ndarray.return_value = np.zeros((1, 512), dtype=np.int32)
    mock_container = mocker.Mock()
    mock_container.decode.return_value = [mock_frame]
    mocker.patch("av.open", return_value=mock_container)

    result = tts_engine._try_decode_partial(b"fake_data")
    assert result[0].dtype == np.int16

def test_try_decode_partial_multichannel_squeeze(mocker, tts_engine):
    """Multichannel audio should be squeezed to first channel."""
    mock_frame = mocker.Mock()
    mock_frame.to_ndarray.return_value = np.zeros((2, 512), dtype=np.int16)
    mock_container = mocker.Mock()
    mock_container.decode.return_value = [mock_frame]
    mocker.patch("av.open", return_value=mock_container)

    result = tts_engine._try_decode_partial(b"fake_data")
    assert result[0].shape == (512,)

@pytest.mark.asyncio
async def test_speak_stream_passes_voice_rate_and_volume(mocker):
    communicate = mocker.patch("edge_tts.Communicate", return_value=MockCommunicate([]))
    engine = EdgeTTSEngine(voice="zh-TW-HsiaoChenNeural", rate="+20%", volume="+10%")

    await engine.speak_stream("測試", MockAudioPlayer())

    communicate.assert_called_once_with(
        "測試",
        voice="zh-TW-HsiaoChenNeural",
        rate="+20%",
        volume="+10%",
        boundary="WordBoundary",
    )

def test_update_settings_updates_selected_fields(tts_engine):
    tts_engine.update_settings(rate="+15%", volume="+5%")

    assert tts_engine.voice == "zh-TW-HsiaoChenNeural"
    assert tts_engine.rate == "+15%"
    assert tts_engine.volume == "+5%"


def test_tts_rate_is_clamped_to_supported_range(tts_engine):
    fast_engine = EdgeTTSEngine(rate="+100%")
    assert fast_engine.rate == "+30%"

    tts_engine.update_settings(rate="-50%")
    assert tts_engine.rate == "-30%"

def test_sanitize_edge_tts_text_removes_markdown_markers():
    text = "### 1. Core route\n*   **First segment**: follow **Keelung River**."

    assert sanitize_edge_tts_text(text) == "1. Core route\nFirst segment: follow Keelung River."

def test_sanitize_edge_tts_text_preserves_non_markdown_hash_by_default():
    assert sanitize_edge_tts_text("C# and #1 are labels.") == "C# and #1 are labels."

def test_sanitize_edge_tts_text_can_remove_all_hashes():
    assert (
        sanitize_edge_tts_text("C# and #1 are labels.", remove_all_hashes=True)
        == "C and 1 are labels."
    )

@pytest.mark.asyncio
async def test_speak_stream_sanitizes_text_before_edge_tts(mocker):
    communicate = mocker.patch("edge_tts.Communicate", return_value=MockCommunicate([]))
    engine = EdgeTTSEngine(voice="zh-TW-HsiaoChenNeural")

    await engine.speak_stream("### 1. Route\n*   **First** item", MockAudioPlayer())

    communicate.assert_called_once_with(
        "1. Route\nFirst item",
        voice="zh-TW-HsiaoChenNeural",
        rate="+0%",
        volume="+0%",
        boundary="WordBoundary",
    )


def test_sanitize_edge_tts_text_replaces_thanks_pronunciation():
    assert sanitize_edge_tts_text("謝謝你的幫忙。") == "謝些你的幫忙。"
