import io
import numpy as np
import os
import re
import sys
import threading
import unicodedata
import wave
from faster_whisper import WhisperModel
import httpx
from utils.logger import get_logger

logger = get_logger(__name__)
DEFAULT_GROQ_TRANSCRIPTION_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_GROQ_MODEL = "whisper-large-v3"


def _normalize_noise_match_text(text: str) -> str:
    return "".join(
        ch.lower()
        for ch in text
        if not unicodedata.category(ch).startswith(("P", "Z"))
    )

NOISY_TRANSCRIPT_PLACEHOLDER = "(聲音雜亂, 系統無法辨識)"
NOISY_TRANSCRIPT_SYSTEM_HINT = "聲音雜亂，系統無法辨識。"
NOISY_TRANSCRIPT_KEYWORDS = (
    "Amara.org 社群提供",
    "Amara.org 社区提供",
    "點贊訂閱轉發打賞",
    "點讚訂閱轉發打賞",
    "点赞订阅转发打赏",
    "請別忘了分享給你的朋友",
    "記得訂閱我們的頻道",
    "訂閱我們的頻道",
    "才能收到最新消息",
    "收到最新消息喔",
    "詞曲李宗盛",
    "感謝您的觀看",
    "魔人SAVI的頻道",
)
NORMALIZED_NOISY_TRANSCRIPT_KEYWORDS = tuple(
    _normalize_noise_match_text(keyword) for keyword in NOISY_TRANSCRIPT_KEYWORDS
)
NOISY_TRANSCRIPT_EXACT_MATCHES = (
    "請勿模仿",
)
NORMALIZED_NOISY_TRANSCRIPT_EXACT_MATCHES = tuple(
    _normalize_noise_match_text(text) for text in NOISY_TRANSCRIPT_EXACT_MATCHES
)
NOISY_TRANSCRIPT_PATTERNS = (
    re.compile(r"字幕由.+?提供"),
    re.compile(r"本視頻由.+?提供"),
    re.compile(r"本影片由.+?提供"),
    re.compile(r"本视频由.+?提供"),
)
PROMPT_ECHO_PREFIXES = (
    "以下是",
    "感覺是",
)

def _is_initial_prompt_echo_for_prompt(normalized_text: str, initial_prompt: str | None) -> bool:
    if not normalized_text:
        return False

    normalized_prompt = _normalize_noise_match_text(initial_prompt or "")
    if not normalized_prompt:
        return False

    candidates = [normalized_text]
    for prefix in PROMPT_ECHO_PREFIXES:
        normalized_prefix = _normalize_noise_match_text(prefix)
        if normalized_text.startswith(normalized_prefix):
            candidates.append(normalized_text[len(normalized_prefix):])

    minimum_partial_length = max(8, int(len(normalized_prompt) * 0.55))
    for candidate in candidates:
        if candidate == normalized_prompt:
            return True
        if (
            len(candidate) >= minimum_partial_length
            and normalized_prompt.endswith(candidate)
        ):
            return True

    return False


def _sanitize_transcript_text(text: str, initial_prompt: str | None) -> str:
    normalized_text = _normalize_noise_match_text(text)

    if _is_initial_prompt_echo_for_prompt(normalized_text, initial_prompt):
        logger.info("Detected Whisper initial_prompt echo; dropping transcript.")
        return ""

    # If these markers appear, the entire Whisper turn is treated as unreliable.
    if normalized_text in NORMALIZED_NOISY_TRANSCRIPT_EXACT_MATCHES or any(
        keyword in normalized_text for keyword in NORMALIZED_NOISY_TRANSCRIPT_KEYWORDS
    ) or any(
        pattern.search(normalized_text) for pattern in NOISY_TRANSCRIPT_PATTERNS
    ):
        logger.info("Detected unreliable transcript marker; replacing entire Whisper turn.")
        return NOISY_TRANSCRIPT_PLACEHOLDER

    return text


# On Windows, add the venv/Lib/site-packages/nvidia/*/bin to PATH to find CUDA DLLs
if sys.platform == "win32":
    venv_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    site_packages = os.path.join(venv_base, "venv", "Lib", "site-packages")
    if os.path.exists(site_packages):
        for root, dirs, files in os.walk(site_packages):
            if "bin" in dirs and "nvidia" in root:
                bin_path = os.path.join(root, "bin")
                if bin_path not in os.environ["PATH"]:
                    logger.debug(f"Adding CUDA DLL path: {bin_path}")
                    os.environ["PATH"] = bin_path + os.pathsep + os.environ["PATH"]

class Transcriber:
    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "int8",
        language: str = "zh",
        initial_prompt: str = "以下是繁體中文語音內容的逐字稿。",
    ):
        logger.info(f"Loading faster-whisper model '{model_size}' on '{device}' (Compute type: {compute_type})...")
        self.language = language
        self.initial_prompt = initial_prompt
        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type
        )
        logger.info("Faster-whisper model loaded successfully.")

    def _sanitize_transcript(self, text: str) -> str:
        return _sanitize_transcript_text(text, self.initial_prompt)

    def _is_initial_prompt_echo(self, normalized_text: str) -> bool:
        return _is_initial_prompt_echo_for_prompt(normalized_text, self.initial_prompt)

    def _transcribe_once(
        self,
        audio_np_float32: np.ndarray,
        *,
        initial_prompt: str | None,
    ) -> str:
        segments, info = self.model.transcribe(
            audio_np_float32,
            language=self.language,
            initial_prompt=initial_prompt,
            vad_filter=False  # We use our own VAD logic
        )
        return "".join(seg.text for seg in segments).strip()

    def transcribe(self, audio_np_float32: np.ndarray) -> str:
        """
        Transcribe the audio numpy array into text.
        audio_np_float32: shape=(N,) of float32, sample_rate=16000
        Language and initial_prompt are taken from the constructor parameters.
        """
        if len(audio_np_float32) == 0:
            return ""

        try:
            text = self._transcribe_once(
                audio_np_float32,
                initial_prompt=self.initial_prompt,
            )

            if self._is_initial_prompt_echo(_normalize_noise_match_text(text)):
                logger.info("Detected Whisper initial_prompt echo; retrying without prompt.")
                retry_text = self._transcribe_once(
                    audio_np_float32,
                    initial_prompt=None,
                )
                if retry_text:
                    return self._sanitize_transcript(retry_text)

            return self._sanitize_transcript(text)
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return ""


class GroqWhisperTranscriber:
    def __init__(
        self,
        api_key: str | None = None,
        api_key_env: str = "GROQ_API_KEY",
        model: str = DEFAULT_GROQ_MODEL,
        api_url: str = DEFAULT_GROQ_TRANSCRIPTION_API_URL,
        timeout_seconds: float = 30.0,
        language: str = "zh",
        initial_prompt: str = "",
    ):
        self.api_key_env = api_key_env or "GROQ_API_KEY"
        self.api_key = (api_key or os.environ.get(self.api_key_env) or "").strip()
        if not self.api_key:
            raise RuntimeError(
                f"Groq API key missing. Set whisper.groq.api_key or environment variable {self.api_key_env}."
            )
        self.model = model or DEFAULT_GROQ_MODEL
        self.api_url = api_url or DEFAULT_GROQ_TRANSCRIPTION_API_URL
        self.timeout_seconds = float(timeout_seconds or 30.0)
        self.language = language
        self.initial_prompt = initial_prompt
        logger.info("Groq Whisper transcriber configured with model '%s'.", self.model)

    def _sanitize_transcript(self, text: str) -> str:
        return _sanitize_transcript_text(text, self.initial_prompt)

    @staticmethod
    def _float32_audio_to_wav_bytes(audio_np_float32: np.ndarray, sample_rate: int = 16000) -> bytes:
        clipped = np.clip(audio_np_float32.astype(np.float32, copy=False), -1.0, 1.0)
        pcm_int16 = (clipped * 32767.0).astype("<i2")
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_int16.tobytes())
        return buffer.getvalue()

    def transcribe(self, audio_np_float32: np.ndarray) -> str:
        if len(audio_np_float32) == 0:
            return ""

        data = {
            "model": self.model,
            "language": self.language,
            "response_format": "json",
            "temperature": "0",
        }
        if self.initial_prompt:
            data["prompt"] = self.initial_prompt

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    self.api_url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    data=data,
                    files={
                        "file": (
                            "audio.wav",
                            self._float32_audio_to_wav_bytes(audio_np_float32),
                            "audio/wav",
                        )
                    },
                )
                response.raise_for_status()
            payload = response.json()
            text = str(payload.get("text", "")).strip()
            return self._sanitize_transcript(text)
        except httpx.HTTPStatusError as e:
            logger.error(
                "Groq transcription failed with HTTP %s: %s",
                e.response.status_code,
                e.response.text[:300],
            )
            return ""
        except Exception as e:
            logger.error(f"Groq transcription failed: {e}")
            return ""


class BackgroundTranscriber:
    def __init__(
        self,
        backend: str = "local",
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "int8",
        language: str = "zh",
        initial_prompt: str = "以下是繁體中文語音內容的逐字稿。",
        groq_api_key: str | None = None,
        groq_api_key_env: str = "GROQ_API_KEY",
        groq_model: str = DEFAULT_GROQ_MODEL,
        groq_api_url: str = DEFAULT_GROQ_TRANSCRIPTION_API_URL,
        groq_timeout_seconds: float = 30.0,
    ):
        self.backend = (backend or "local").strip().lower()
        self._kwargs = {
            "model_size": model_size,
            "device": device,
            "compute_type": compute_type,
            "language": language,
            "initial_prompt": initial_prompt,
        }
        self._groq_kwargs = {
            "api_key": groq_api_key,
            "api_key_env": groq_api_key_env,
            "model": groq_model,
            "api_url": groq_api_url,
            "timeout_seconds": groq_timeout_seconds,
            "language": language,
            "initial_prompt": initial_prompt,
        }
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._transcriber: Transcriber | GroqWhisperTranscriber | None = None
        self._load_error: Exception | None = None
        self._load_thread = threading.Thread(
            target=self._load,
            name="WhisperTranscriberLoader",
            daemon=True,
        )
        logger.info(
            "Starting background STT transcriber load, backend='%s', model='%s', device='%s', compute_type='%s'...",
            self.backend,
            model_size,
            device,
            compute_type,
        )
        self._load_thread.start()

    @property
    def is_ready(self) -> bool:
        return self._ready.is_set() and self._transcriber is not None

    @property
    def load_error(self) -> Exception | None:
        return self._load_error

    def wait_until_ready(self, timeout: float | None = None) -> bool:
        return self._ready.wait(timeout=timeout) and self._transcriber is not None

    def _load(self):
        try:
            if self.backend in ("local", "faster_whisper", "faster-whisper"):
                transcriber = Transcriber(**self._kwargs)
            elif self.backend == "groq":
                transcriber = GroqWhisperTranscriber(**self._groq_kwargs)
            else:
                raise ValueError(f"Unsupported Whisper backend: {self.backend}")
        except Exception as exc:
            with self._lock:
                self._load_error = exc
            logger.exception("Background STT transcriber load failed.")
        else:
            with self._lock:
                self._transcriber = transcriber
            logger.info("Background STT transcriber ready.")
        finally:
            self._ready.set()

    def transcribe(self, audio_np_float32: np.ndarray) -> str:
        if len(audio_np_float32) == 0:
            return ""

        if not self._ready.is_set():
            logger.info("Waiting for STT transcriber to finish loading before transcription...")
        self._ready.wait()

        with self._lock:
            transcriber = self._transcriber
            load_error = self._load_error

        if transcriber is None:
            logger.error(f"Transcription unavailable because STT transcriber failed to load: {load_error}")
            return ""

        return transcriber.transcribe(audio_np_float32)
