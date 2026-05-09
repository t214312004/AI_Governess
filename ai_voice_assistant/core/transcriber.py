import numpy as np
import os
import re
import sys
import threading
import unicodedata
from faster_whisper import WhisperModel
from utils.logger import get_logger

logger = get_logger(__name__)


def _normalize_noise_match_text(text: str) -> str:
    return "".join(
        ch.lower()
        for ch in text
        if not unicodedata.category(ch).startswith(("P", "Z"))
    )

NOISY_TRANSCRIPT_PLACEHOLDER = "(聲音雜亂, 系統無法辨識)"
NOISY_TRANSCRIPT_SYSTEM_HINT = "聲音雜亂，系統無法辨識。"
NOISY_TRANSCRIPT_KEYWORDS = (
    "點贊訂閱轉發打賞",
    "點讚訂閱轉發打賞",
    "点赞订阅转发打赏",
    "詞曲李宗盛",
    "感謝您的觀看",
    "魔人SAVI的頻道",
)
NORMALIZED_NOISY_TRANSCRIPT_KEYWORDS = tuple(
    _normalize_noise_match_text(keyword) for keyword in NOISY_TRANSCRIPT_KEYWORDS
)
NOISY_TRANSCRIPT_PATTERNS = (
    re.compile(r"字幕由.+?提供"),
)
PROMPT_ECHO_PREFIXES = (
    "以下是",
    "感覺是",
)

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
        normalized_text = _normalize_noise_match_text(text)

        if self._is_initial_prompt_echo(normalized_text):
            logger.info("Detected Whisper initial_prompt echo; dropping transcript.")
            return ""

        # If these markers appear, the entire Whisper turn is treated as unreliable.
        if any(keyword in normalized_text for keyword in NORMALIZED_NOISY_TRANSCRIPT_KEYWORDS) or any(
            pattern.search(normalized_text) for pattern in NOISY_TRANSCRIPT_PATTERNS
        ):
            logger.info("Detected unreliable transcript marker; replacing entire Whisper turn.")
            return NOISY_TRANSCRIPT_PLACEHOLDER

        return text

    def _is_initial_prompt_echo(self, normalized_text: str) -> bool:
        if not normalized_text:
            return False

        normalized_prompt = _normalize_noise_match_text(self.initial_prompt or "")
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

    def transcribe(self, audio_np_float32: np.ndarray) -> str:
        """
        Transcribe the audio numpy array into text.
        audio_np_float32: shape=(N,) of float32, sample_rate=16000
        Language and initial_prompt are taken from the constructor parameters.
        """
        if len(audio_np_float32) == 0:
            return ""

        try:
            segments, info = self.model.transcribe(
                audio_np_float32,
                language=self.language,
                initial_prompt=self.initial_prompt,
                vad_filter=False  # We use our own VAD logic
            )

            text = "".join(seg.text for seg in segments)
            return self._sanitize_transcript(text.strip())
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return ""


class BackgroundTranscriber:
    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "int8",
        language: str = "zh",
        initial_prompt: str = "以下是繁體中文語音內容的逐字稿。",
    ):
        self._kwargs = {
            "model_size": model_size,
            "device": device,
            "compute_type": compute_type,
            "language": language,
            "initial_prompt": initial_prompt,
        }
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._transcriber: Transcriber | None = None
        self._load_error: Exception | None = None
        self._load_thread = threading.Thread(
            target=self._load,
            name="WhisperModelLoader",
            daemon=True,
        )
        logger.info(
            "Starting background faster-whisper model load '%s' on '%s' (Compute type: %s)...",
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
            transcriber = Transcriber(**self._kwargs)
        except Exception as exc:
            with self._lock:
                self._load_error = exc
            logger.exception("Background faster-whisper model load failed.")
        else:
            with self._lock:
                self._transcriber = transcriber
            logger.info("Background faster-whisper model ready.")
        finally:
            self._ready.set()

    def transcribe(self, audio_np_float32: np.ndarray) -> str:
        if len(audio_np_float32) == 0:
            return ""

        if not self._ready.is_set():
            logger.info("Waiting for faster-whisper model to finish loading before transcription...")
        self._ready.wait()

        with self._lock:
            transcriber = self._transcriber
            load_error = self._load_error

        if transcriber is None:
            logger.error(f"Transcription unavailable because Whisper model failed to load: {load_error}")
            return ""

        return transcriber.transcribe(audio_np_float32)
