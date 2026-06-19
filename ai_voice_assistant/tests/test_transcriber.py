import pytest
import numpy as np
import threading
from unittest.mock import patch, MagicMock

@patch("core.transcriber.WhisperModel")
def test_transcriber_config_params(mock_whisper_model_class):
    """BUG-5 fix: Transcriber should accept and use compute_type/language/initial_prompt constructor args."""
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance

    from core.transcriber import Transcriber

    t = Transcriber(
        model_size="tiny",
        device="cpu",
        compute_type="float16",
        language="ja",
        initial_prompt="Japanese transcription.",
    )


    assert t.language == "ja"
    assert t.initial_prompt == "Japanese transcription."


    mock_whisper_model_class.assert_called_once_with("tiny", device="cpu", compute_type="float16")

@patch("core.transcriber.WhisperModel")
def test_transcriber_default_params(mock_whisper_model_class):
    """Default compute_type is int8, language zh, with sensible initial_prompt."""
    mock_whisper_model_class.return_value = MagicMock()
    from core.transcriber import Transcriber
    t = Transcriber()
    assert t.language == "zh"
    assert "繁體中文" in t.initial_prompt or "逐字稿" in t.initial_prompt

@patch("core.transcriber.WhisperModel")
def test_transcriber_empty_audio(mock_whisper_model_class):
    """Empty audio returns empty string without calling WhisperModel.transcribe."""
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    from core.transcriber import Transcriber
    t = Transcriber(model_size="tiny", device="cpu")
    result = t.transcribe(np.array([], dtype=np.float32))
    assert result == ""
    mock_model_instance.transcribe.assert_not_called()

@patch("core.transcriber.WhisperModel")
def test_transcriber_replaces_entire_whisper_turn_when_promo_phrase_detected(mock_whisper_model_class):
    """Promo keywords mean the whole Whisper result should be discarded."""
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    from core.transcriber import Transcriber, NOISY_TRANSCRIPT_PLACEHOLDER

    mock_segment = MagicMock()
    mock_segment.text = "請大家點讚、訂閱、轉發、打賞支持一下"
    mock_model_instance.transcribe.return_value = ([mock_segment], None)

    t = Transcriber(model_size="tiny", device="cpu")
    result = t.transcribe(np.zeros(16000, dtype=np.float32))

    assert result == NOISY_TRANSCRIPT_PLACEHOLDER

@patch("core.transcriber.WhisperModel")
def test_transcriber_replaces_entire_whisper_turn_when_subtitle_credit_detected(mock_whisper_model_class):
    """Subtitle credit patterns should also invalidate the whole Whisper turn."""
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    from core.transcriber import Transcriber, NOISY_TRANSCRIPT_PLACEHOLDER

    mock_segment = MagicMock()
    mock_segment.text = "字幕由 Amara.org 提供"
    mock_model_instance.transcribe.return_value = ([mock_segment], None)

    t = Transcriber(model_size="tiny", device="cpu")
    result = t.transcribe(np.zeros(16000, dtype=np.float32))

    assert result == NOISY_TRANSCRIPT_PLACEHOLDER

@patch("core.transcriber.WhisperModel")
def test_transcriber_replaces_entire_whisper_turn_when_song_credit_detected(mock_whisper_model_class):
    """Song credit markers should also invalidate the whole Whisper turn."""
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    from core.transcriber import Transcriber, NOISY_TRANSCRIPT_PLACEHOLDER

    mock_segment = MagicMock()
    mock_segment.text = "詞曲 李宗盛"
    mock_model_instance.transcribe.return_value = ([mock_segment], None)

    t = Transcriber(model_size="tiny", device="cpu")
    result = t.transcribe(np.zeros(16000, dtype=np.float32))

    assert result == NOISY_TRANSCRIPT_PLACEHOLDER

@patch("core.transcriber.WhisperModel")
def test_transcriber_replaces_entire_whisper_turn_when_outro_phrase_detected(mock_whisper_model_class):
    """Outro thank-you phrases should also invalidate the whole Whisper turn."""
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    from core.transcriber import Transcriber, NOISY_TRANSCRIPT_PLACEHOLDER

    mock_segment = MagicMock()
    mock_segment.text = "感謝您的觀看"
    mock_model_instance.transcribe.return_value = ([mock_segment], None)

    t = Transcriber(model_size="tiny", device="cpu")
    result = t.transcribe(np.zeros(16000, dtype=np.float32))

    assert result == NOISY_TRANSCRIPT_PLACEHOLDER

@patch("core.transcriber.WhisperModel")
def test_transcriber_replaces_entire_whisper_turn_when_magic_savi_channel_detected(mock_whisper_model_class):
    """Known hallucinated promo lines should be filtered even with spaces and Latin letters."""
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    from core.transcriber import Transcriber, NOISY_TRANSCRIPT_PLACEHOLDER

    mock_segment = MagicMock()
    mock_segment.text = "請搜尋 魔人SAVI的頻道 才能收到最新消息!"
    mock_model_instance.transcribe.return_value = ([mock_segment], None)

    t = Transcriber(model_size="tiny", device="cpu")
    result = t.transcribe(np.zeros(16000, dtype=np.float32))

    assert result == NOISY_TRANSCRIPT_PLACEHOLDER

@patch("core.transcriber.WhisperModel")
def test_transcriber_replaces_entire_whisper_turn_when_video_credit_detected(mock_whisper_model_class):
    """Video credit hallucinations should also invalidate the whole Whisper turn."""
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    from core.transcriber import Transcriber, NOISY_TRANSCRIPT_PLACEHOLDER

    mock_segment = MagicMock()
    mock_segment.text = "本視頻由 Amara.org 社群提供"
    mock_model_instance.transcribe.return_value = ([mock_segment], None)

    t = Transcriber(model_size="tiny", device="cpu")
    result = t.transcribe(np.zeros(16000, dtype=np.float32))

    assert result == NOISY_TRANSCRIPT_PLACEHOLDER


@patch("core.transcriber.WhisperModel")
def test_transcriber_replaces_entire_whisper_turn_when_youtube_outro_detected(mock_whisper_model_class):
    """YouTube-style outro hallucinations should be filtered."""
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    from core.transcriber import Transcriber, NOISY_TRANSCRIPT_PLACEHOLDER

    mock_segment = MagicMock()
    mock_segment.text = "請別忘了分享給你的朋友 並且記得訂閱我們的頻道 才能收到最新消息喔!"
    mock_model_instance.transcribe.return_value = ([mock_segment], None)

    t = Transcriber(model_size="tiny", device="cpu")
    result = t.transcribe(np.zeros(16000, dtype=np.float32))

    assert result == NOISY_TRANSCRIPT_PLACEHOLDER


@pytest.mark.parametrize(
    "transcript",
    [
        "謝謝觀看,下次見!",
        "謝謝你看下次的節目。",
        "謝謝您收看,下次見!",
        "請觀看。",
        "請您收集。",
        "在這裡,謝謝你,謝謝你。我剛剛在那裡,我在基礎。哦,謝謝。請留意下方的字幕,並且記得訂閱、按讚、分享及分享唷!",
        "請留意,這段影片是由小胤和小胤的主持人, 並且希望大家可以多多支持我們。",
        "謝謝收看,下次見!",
        "請留意下方的詳細資訊。",
        "謝謝收看。",
        "請留意中文字幕的功能。",
        "請不吝點贊 訂閱 打賞 打賞 打賞",
        "請留意,這段影片是由我自己創作的,並且是由我自己創作的。",
        "請看下方的影片。",
        "請留意中文字幕的關鍵字幕。",
        "請點喜歡,並且訂閱,並且按讚!",
        "請訂閱,按讚,分享,並且按下小鈴鐺。",
        "謝謝您的收看。",
        "請看片段。",
        "謝謝觀看,下次見。",
        "請留意,這段影片是由我自己創作的。",
        "請多多支持我們,我們會努力!",
    ],
)
@patch("core.transcriber.WhisperModel")
def test_transcriber_replaces_confirmed_h_series_hallucinations(mock_whisper_model_class, transcript):
    """Confirmed H-series Whisper hallucinations from June 2026 logs should be filtered."""
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    from core.transcriber import Transcriber, NOISY_TRANSCRIPT_PLACEHOLDER

    mock_segment = MagicMock()
    mock_segment.text = transcript
    mock_model_instance.transcribe.return_value = ([mock_segment], None)

    t = Transcriber(model_size="tiny", device="cpu")
    result = t.transcribe(np.zeros(16000, dtype=np.float32))

    assert result == NOISY_TRANSCRIPT_PLACEHOLDER


@patch("core.transcriber.WhisperModel")
def test_transcriber_replaces_entire_whisper_turn_when_exact_do_not_imitate_detected(mock_whisper_model_class):
    """The short '請勿模仿' hallucination should be filtered as an exact match."""
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    from core.transcriber import Transcriber, NOISY_TRANSCRIPT_PLACEHOLDER

    mock_segment = MagicMock()
    mock_segment.text = "請勿模仿"
    mock_model_instance.transcribe.return_value = ([mock_segment], None)

    t = Transcriber(model_size="tiny", device="cpu")
    result = t.transcribe(np.zeros(16000, dtype=np.float32))

    assert result == NOISY_TRANSCRIPT_PLACEHOLDER


@patch("core.transcriber.WhisperModel")
def test_transcriber_keeps_longer_phrase_containing_do_not_imitate(mock_whisper_model_class):
    """Only the exact short hallucination is filtered; longer user directives can pass through."""
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    from core.transcriber import Transcriber

    mock_segment = MagicMock()
    mock_segment.text = "請勿模仿剛剛那種語氣"
    mock_model_instance.transcribe.return_value = ([mock_segment], None)

    t = Transcriber(model_size="tiny", device="cpu")
    result = t.transcribe(np.zeros(16000, dtype=np.float32))

    assert result == "請勿模仿剛剛那種語氣"


@patch("core.transcriber.WhisperModel")
def test_transcriber_drops_exact_initial_prompt_echo(mock_whisper_model_class):
    """Whisper sometimes returns the prompt itself for unclear audio; do not treat it as speech."""
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    from core.transcriber import Transcriber

    mock_segment = MagicMock()
    mock_segment.text = "以下是繁體中文語音內容的逐字稿。"
    mock_model_instance.transcribe.return_value = ([mock_segment], None)

    t = Transcriber(model_size="tiny", device="cpu")
    result = t.transcribe(np.zeros(16000, dtype=np.float32))

    assert result == ""

@patch("core.transcriber.WhisperModel")
def test_transcriber_drops_partial_initial_prompt_echo(mock_whisper_model_class):
    """Partial prompt echoes from Whisper should also be discarded."""
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    from core.transcriber import Transcriber

    mock_segment = MagicMock()
    mock_segment.text = "中文語音內容的逐字稿。"
    mock_model_instance.transcribe.return_value = ([mock_segment], None)

    t = Transcriber(model_size="tiny", device="cpu")
    result = t.transcribe(np.zeros(16000, dtype=np.float32))

    assert result == ""

@patch("core.transcriber.WhisperModel")
def test_transcriber_retries_without_prompt_when_initial_prompt_echo_detected(mock_whisper_model_class):
    """Prompt echo should get one no-prompt retry before giving up."""
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    from core.transcriber import Transcriber

    prompt_echo = MagicMock()
    prompt_echo.text = "以下是繁體中文語音內容的逐字稿。"
    recovered = MagicMock()
    recovered.text = "等一下會下雨嗎?"
    mock_model_instance.transcribe.side_effect = [
        ([prompt_echo], None),
        ([recovered], None),
    ]

    t = Transcriber(model_size="tiny", device="cpu")
    result = t.transcribe(np.zeros(16000, dtype=np.float32))

    assert result == "等一下會下雨嗎?"
    assert mock_model_instance.transcribe.call_count == 2
    assert mock_model_instance.transcribe.call_args_list[0].kwargs["initial_prompt"] == t.initial_prompt
    assert mock_model_instance.transcribe.call_args_list[1].kwargs["initial_prompt"] is None

@patch("core.transcriber.WhisperModel")
def test_transcriber_successful_transcription(mock_whisper_model_class):
    """Successful transcription returns stripped text."""
    mock_model_instance = MagicMock()
    mock_whisper_model_class.return_value = mock_model_instance
    from core.transcriber import Transcriber

    mock_segment = MagicMock()
    mock_segment.text = "  Hello World  "
    mock_model_instance.transcribe.return_value = ([mock_segment], None)

    t = Transcriber(model_size="tiny", device="cpu")
    result = t.transcribe(np.zeros(16000, dtype=np.float32))
    assert result == "Hello World"

@patch("core.transcriber.WhisperModel")
def test_transcriber_uses_instance_language(mock_whisper_model_class):
    """transcribe() uses instance.language and instance.initial_prompt, not hardcoded."""
    mock_model_instance = MagicMock()
    mock_model_instance.transcribe.return_value = ([], None)
    mock_whisper_model_class.return_value = mock_model_instance
    from core.transcriber import Transcriber

    t = Transcriber(device="cpu", language="en", initial_prompt="English speech.")
    t.transcribe(np.zeros(1000, dtype=np.float32))

    call_kwargs = mock_model_instance.transcribe.call_args[1]
    assert call_kwargs["language"] == "en"
    assert call_kwargs["initial_prompt"] == "English speech."

@patch("core.transcriber.WhisperModel")
def test_transcriber_exception_returns_empty(mock_whisper_model_class):
    """Exception in WhisperModel.transcribe → safe empty string return."""
    mock_model_instance = MagicMock()
    mock_model_instance.transcribe.side_effect = RuntimeError("CUDA OOM")
    mock_whisper_model_class.return_value = mock_model_instance
    from core.transcriber import Transcriber

    t = Transcriber(model_size="tiny", device="cpu")
    result = t.transcribe(np.zeros(16000, dtype=np.float32))
    assert result == ""


@patch("core.transcriber.Transcriber")
def test_background_transcriber_loads_model_without_blocking_constructor(mock_transcriber_class):
    from core.transcriber import BackgroundTranscriber

    ready_to_finish = threading.Event()

    def build_transcriber(**kwargs):
        ready_to_finish.wait(timeout=2)
        instance = MagicMock()
        instance.transcribe.return_value = "ready"
        return instance

    mock_transcriber_class.side_effect = build_transcriber

    t = BackgroundTranscriber(model_size="tiny", device="cpu")

    assert t.is_ready is False
    ready_to_finish.set()
    assert t.wait_until_ready(timeout=2) is True
    assert t.transcribe(np.zeros(16000, dtype=np.float32)) == "ready"
    mock_transcriber_class.assert_called_once_with(
        model_size="tiny",
        device="cpu",
        compute_type="int8",
        language="zh",
        initial_prompt="以下是繁體中文語音內容的逐字稿。",
    )


@patch("core.transcriber.Transcriber")
def test_background_transcriber_returns_empty_when_model_load_fails(mock_transcriber_class):
    from core.transcriber import BackgroundTranscriber

    mock_transcriber_class.side_effect = RuntimeError("load failed")

    t = BackgroundTranscriber(model_size="tiny", device="cpu")

    assert t.wait_until_ready(timeout=2) is False
    assert isinstance(t.load_error, RuntimeError)
    assert t.transcribe(np.zeros(16000, dtype=np.float32)) == ""


@patch("core.transcriber.httpx.Client")
def test_groq_transcriber_sends_prompt_and_returns_text(mock_httpx_client):
    from core.transcriber import GroqWhisperTranscriber

    client = mock_httpx_client.return_value.__enter__.return_value
    response = MagicMock()
    response.json.return_value = {"text": "  Hello Groq  "}
    client.post.return_value = response

    transcriber = GroqWhisperTranscriber(
        api_key="test-key",
        model="whisper-large-v3",
        language="zh",
        initial_prompt="以下是繁體中文語音內容的逐字稿。",
    )

    result = transcriber.transcribe(np.zeros(16000, dtype=np.float32))

    assert result == "Hello Groq"
    response.raise_for_status.assert_called_once()
    call_kwargs = client.post.call_args.kwargs
    assert call_kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert call_kwargs["data"]["model"] == "whisper-large-v3"
    assert call_kwargs["data"]["language"] == "zh"
    assert call_kwargs["data"]["prompt"] == "以下是繁體中文語音內容的逐字稿。"
    file_name, wav_bytes, content_type = call_kwargs["files"]["file"]
    assert file_name == "audio.wav"
    assert wav_bytes.startswith(b"RIFF")
    assert content_type == "audio/wav"


def test_groq_transcriber_requires_api_key(monkeypatch):
    from core.transcriber import GroqWhisperTranscriber

    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Groq API key missing"):
        GroqWhisperTranscriber(api_key="")


@patch("core.transcriber.GroqWhisperTranscriber")
def test_background_transcriber_can_load_groq_backend(mock_groq_transcriber_class):
    from core.transcriber import BackgroundTranscriber

    instance = MagicMock()
    instance.transcribe.return_value = "groq ready"
    mock_groq_transcriber_class.return_value = instance

    transcriber = BackgroundTranscriber(
        backend="groq",
        groq_api_key="test-key",
        groq_model="whisper-large-v3",
        language="zh",
        initial_prompt="prompt",
    )

    assert transcriber.wait_until_ready(timeout=2) is True
    assert transcriber.transcribe(np.zeros(16000, dtype=np.float32)) == "groq ready"
    mock_groq_transcriber_class.assert_called_once()
    call_kwargs = mock_groq_transcriber_class.call_args.kwargs
    assert call_kwargs["api_key"] == "test-key"
    assert call_kwargs["model"] == "whisper-large-v3"
    assert call_kwargs["language"] == "zh"
    assert call_kwargs["initial_prompt"] == "prompt"

