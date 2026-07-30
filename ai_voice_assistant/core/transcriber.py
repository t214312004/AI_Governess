import io
import logging
import numpy as np
import os
import re
import sys
import threading
import unicodedata
import wave
from faster_whisper import WhisperModel
import httpx
from utils.logger import get_logger, log_event

logger = get_logger(__name__)

_BACKGROUND_LOAD_TIMEOUT_SECONDS = 180.0
DEFAULT_GROQ_TRANSCRIPTION_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_GROQ_MODEL = "whisper-large-v3"
DEFAULT_GROQ_GATE_AVG_LOGPROB_THRESHOLD = -1.0
DEFAULT_GROQ_GATE_NO_SPEECH_PROB_THRESHOLD = 0.9
DEFAULT_GROQ_GATE_TEMPERATURE_THRESHOLD = 0.0
DEFAULT_GROQ_GATE_MIN_TRANSCRIPT_SIMILARITY = 0.5


def _normalize_noise_match_text(text: str) -> str:
    return "".join(
        ch.lower()
        for ch in text
        if not unicodedata.category(ch).startswith(("P", "Z"))
    )


def _normalized_levenshtein_similarity(left: str, right: str) -> float:
    normalized_left = _normalize_noise_match_text(left)
    normalized_right = _normalize_noise_match_text(right)
    if normalized_left == normalized_right:
        return 1.0
    if not normalized_left or not normalized_right:
        return 0.0

    if len(normalized_left) > len(normalized_right):
        normalized_left, normalized_right = normalized_right, normalized_left

    previous_row = list(range(len(normalized_left) + 1))
    for right_index, right_character in enumerate(normalized_right, start=1):
        current_row = [right_index]
        for left_index, left_character in enumerate(normalized_left, start=1):
            current_row.append(
                min(
                    current_row[-1] + 1,
                    previous_row[left_index] + 1,
                    previous_row[left_index - 1]
                    + (left_character != right_character),
                )
            )
        previous_row = current_row

    edit_distance = previous_row[-1]
    return 1.0 - (edit_distance / max(len(normalized_left), len(normalized_right)))

NOISY_TRANSCRIPT_PLACEHOLDER = "(聲音雜亂, 系統無法辨識)"
NOISY_TRANSCRIPT_SYSTEM_HINT = "聲音雜亂，系統無法辨識。"
NOISY_TRANSCRIPT_KEYWORDS = (
    "Amara.org 社群提供",
    "Amara.org 社区提供",
    "請留意,這段影片的主題曲是《雜誌》的主題曲。",
    "請留意,這段影片的主題曲是《天使》的主題曲。",
    "請留意,我們下期的影片會有更多更新。",
    "請留意,這段影片是為了提醒大家,請留意,這段影片是為了提醒大家,",
    "請訂閱、按讚、分享及分享。",
    "請訂閱,按讚,分享,和留言。",
    "多多支持,讓我們可以更多的支持您的朋友。",
    "在這裡,請留意下,這段影片是在上一段影片中的最新的一段。",
    "請觀看下方的影片。",
    "謝謝觀看,再見。",
    "請訂閱按讚分享",
    "謝謝觀看再見",
    "請留意我們下期的影片會有更多更新",
    "請留意這段影片是為了提醒大家",
    "請留意這段影片的主題曲是",
    "多多支持讓我們可以更多的支持您的朋友",
    "上一段影片中的最新的一段",
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
    "請不吝點贊訂閱打賞",
    "請不吝點讚訂閱打賞",
    "請留意中文字幕",
    "請留意下方的字幕",
    "請留意下方的詳細資訊",
    "請留意這段影片是由",
    "請點喜歡並且訂閱並且按讚",
    "請訂閱按讚分享並且按下小鈴鐺",
)
NORMALIZED_NOISY_TRANSCRIPT_KEYWORDS = tuple(
    _normalize_noise_match_text(keyword) for keyword in NOISY_TRANSCRIPT_KEYWORDS
)
NOISY_TRANSCRIPT_EXACT_MATCHES = (
    "請留意下方的內容",
    "請按讚、訂閱、分享及分享",
    "歡迎觀看，下次再見",
    "在這裏的字幕中，我會把字幕放在其他字幕中",
    "在這裡的字幕中，我會把字幕放在其他字幕中",
    "感謝觀賞 感謝觀賞謝謝так varieties",
    "請留意下方的影片",
    "請看下方的內容",
    "請點讚、訂閱、分享",
    "本集完",
    "請勿模仿",
    "謝謝觀看",
    "謝謝觀看下次見",
    "謝謝收看下次見",
    "謝謝您收看下次見",
    "謝謝您的收看",
    "謝謝收看",
    "謝謝你看下次的節目",
    "請看",
    "請觀看",
    "請您收集",
    "請看下方的影片",
    "請看片段",
    "請多多支持我們我們會努力",
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
        confidence_gate_enabled: bool = True,
        confidence_gate_avg_logprob_threshold: float = DEFAULT_GROQ_GATE_AVG_LOGPROB_THRESHOLD,
        confidence_gate_no_speech_prob_threshold: float = DEFAULT_GROQ_GATE_NO_SPEECH_PROB_THRESHOLD,
        confidence_gate_temperature_threshold: float = DEFAULT_GROQ_GATE_TEMPERATURE_THRESHOLD,
        confidence_gate_min_transcript_similarity: float = DEFAULT_GROQ_GATE_MIN_TRANSCRIPT_SIMILARITY,
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
        self.confidence_gate_enabled = bool(confidence_gate_enabled)
        self.confidence_gate_avg_logprob_threshold = float(
            confidence_gate_avg_logprob_threshold
        )
        self.confidence_gate_no_speech_prob_threshold = float(
            confidence_gate_no_speech_prob_threshold
        )
        self.confidence_gate_temperature_threshold = float(
            confidence_gate_temperature_threshold
        )
        self.confidence_gate_min_transcript_similarity = float(
            confidence_gate_min_transcript_similarity
        )
        if not 0.0 <= self.confidence_gate_no_speech_prob_threshold <= 1.0:
            raise ValueError("confidence_gate_no_speech_prob_threshold must be between 0 and 1.")
        if not 0.0 <= self.confidence_gate_min_transcript_similarity <= 1.0:
            raise ValueError("confidence_gate_min_transcript_similarity must be between 0 and 1.")
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

    @staticmethod
    def _safe_float(value) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _segment_metric_values(cls, payload: dict, metric_name: str) -> list[float]:
        segments = payload.get("segments")
        if not isinstance(segments, list):
            return []

        values = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            value = cls._safe_float(segment.get(metric_name))
            if value is not None:
                values.append(value)
        return values

    def _confidence_risks(self, payload: dict) -> tuple[list[str], dict[str, float | None]]:
        temperatures = self._segment_metric_values(payload, "temperature")
        avg_logprobs = self._segment_metric_values(payload, "avg_logprob")
        no_speech_probs = self._segment_metric_values(payload, "no_speech_prob")

        max_temperature = max(temperatures, default=None)
        min_avg_logprob = min(avg_logprobs, default=None)
        max_no_speech_prob = max(no_speech_probs, default=None)
        min_no_speech_prob = min(no_speech_probs, default=None)
        risks = []
        if (
            max_temperature is not None
            and max_temperature > self.confidence_gate_temperature_threshold
        ):
            risks.append("temperature")
        if (
            min_avg_logprob is not None
            and min_avg_logprob < self.confidence_gate_avg_logprob_threshold
        ):
            risks.append("avg_logprob")
        if (
            max_no_speech_prob is not None
            and max_no_speech_prob >= self.confidence_gate_no_speech_prob_threshold
        ):
            risks.append("no_speech_prob")

        return risks, {
            "max_temperature": max_temperature,
            "min_avg_logprob": min_avg_logprob,
            "max_no_speech_prob": max_no_speech_prob,
            "min_no_speech_prob": min_no_speech_prob,
        }

    @staticmethod
    def _has_speech_contrast(
        audio_np_float32: np.ndarray,
        *,
        sample_rate: int = 16000,
    ) -> bool:
        """Detect a speech-shaped energy rise without treating steady noise as speech."""
        audio = np.asarray(audio_np_float32, dtype=np.float32).reshape(-1)
        frame_samples = max(1, int(sample_rate * 0.02))
        if audio.size < frame_samples:
            return False
        padding = (-audio.size) % frame_samples
        if padding:
            audio = np.pad(audio, (0, padding))
        frames = audio.reshape(-1, frame_samples)
        frame_rms = np.sqrt(np.mean(frames * frames, axis=1))
        speech_level = float(np.percentile(frame_rms, 95))
        noise_floor = float(np.percentile(frame_rms, 20))
        return (
            speech_level >= 0.001
            and speech_level >= max(noise_floor * 4.0, noise_floor + 0.0005)
        )

    def _request_transcription(
        self,
        client: httpx.Client,
        wav_bytes: bytes,
        *,
        include_prompt: bool = True,
    ) -> dict:
        data = {
            "model": self.model,
            "language": self.language,
            "response_format": "verbose_json" if self.confidence_gate_enabled else "json",
            "temperature": "0",
        }
        if include_prompt and self.initial_prompt:
            data["prompt"] = self.initial_prompt

        response = client.post(
            self.api_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            data=data,
            files={"file": ("audio.wav", wav_bytes, "audio/wav")},
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def transcribe(self, audio_np_float32: np.ndarray) -> str:
        if len(audio_np_float32) == 0:
            return ""

        try:
            wav_bytes = self._float32_audio_to_wav_bytes(audio_np_float32)
            with httpx.Client(timeout=self.timeout_seconds) as client:
                first_payload = self._request_transcription(client, wav_bytes)
                first_text = str(first_payload.get("text", "")).strip()
                if not first_text:
                    return ""
                if not self.confidence_gate_enabled:
                    return self._sanitize_transcript(first_text)

                first_risks, first_metrics = self._confidence_risks(first_payload)
                if not first_risks:
                    return self._sanitize_transcript(first_text)

                log_event(
                    logger,
                    logging.INFO,
                    "whisper.confidence_gate.retry",
                    reasons=",".join(first_risks),
                    **first_metrics,
                )

                # Retry without the initial prompt.  On short, quiet speech the
                # prompt can dominate decoding and produce a stable subtitle-
                # style hallucination even though the captured audio is valid.
                second_payload = self._request_transcription(
                    client,
                    wav_bytes,
                    include_prompt=False,
                )
                second_text = str(second_payload.get("text", "")).strip()
                second_risks, second_metrics = self._confidence_risks(second_payload)
                similarity = _normalized_levenshtein_similarity(first_text, second_text)

                if not second_text:
                    log_event(
                        logger,
                        logging.WARNING,
                        "whisper.confidence_gate.reject",
                        reasons="empty_retry",
                        similarity=similarity,
                    )
                    return ""

                has_speech_contrast = self._has_speech_contrast(audio_np_float32)
                if not has_speech_contrast:
                    log_event(
                        logger,
                        logging.WARNING,
                        "whisper.confidence_gate.reject",
                        reasons="insufficient_audio_contrast",
                        similarity=similarity,
                    )
                    return ""

                prompt_dominated_retry = (
                    bool(self.initial_prompt)
                    and "no_speech_prob" in first_risks
                )
                if not second_risks and (
                    similarity >= self.confidence_gate_min_transcript_similarity
                    or prompt_dominated_retry
                ):
                    log_event(
                        logger,
                        logging.INFO,
                        "whisper.confidence_gate.accept",
                        selection="retry_without_prompt",
                        similarity=similarity,
                        second_risks="none",
                        second_min_avg_logprob=second_metrics["min_avg_logprob"],
                        second_max_no_speech_prob=second_metrics["max_no_speech_prob"],
                    )
                    return self._sanitize_transcript(second_text)

                if not second_risks:
                    log_event(
                        logger,
                        logging.WARNING,
                        "whisper.confidence_gate.reject",
                        reasons="low_consensus",
                        similarity=similarity,
                    )
                    return ""

                first_no_speech = first_metrics["min_no_speech_prob"]
                second_no_speech = second_metrics["min_no_speech_prob"]
                first_avg_logprob = first_metrics["min_avg_logprob"]
                second_avg_logprob = second_metrics["min_avg_logprob"]
                # Match Whisper's silence semantics: a high no-speech score is
                # only decisive when token confidence is also low.  Short,
                # quiet utterances can otherwise produce a high no-speech
                # score alongside stable, high-confidence text.
                first_supports_silence = (
                    first_no_speech is not None
                    and first_no_speech >= self.confidence_gate_no_speech_prob_threshold
                    and (
                        first_avg_logprob is None
                        or first_avg_logprob < self.confidence_gate_avg_logprob_threshold
                    )
                )
                second_supports_silence = (
                    second_no_speech is not None
                    and second_no_speech >= self.confidence_gate_no_speech_prob_threshold
                    and (
                        second_avg_logprob is None
                        or second_avg_logprob < self.confidence_gate_avg_logprob_threshold
                    )
                )
                persistent_no_speech = (
                    first_supports_silence and second_supports_silence
                )
                if (
                    similarity < self.confidence_gate_min_transcript_similarity
                    or persistent_no_speech
                ):
                    rejection_reasons = []
                    if similarity < self.confidence_gate_min_transcript_similarity:
                        rejection_reasons.append("low_consensus")
                    if persistent_no_speech:
                        rejection_reasons.append("persistent_no_speech")
                    log_event(
                        logger,
                        logging.WARNING,
                        "whisper.confidence_gate.reject",
                        reasons=",".join(rejection_reasons),
                        similarity=similarity,
                        first_min_no_speech_prob=first_no_speech,
                        second_min_no_speech_prob=second_no_speech,
                        first_min_avg_logprob=first_avg_logprob,
                        second_min_avg_logprob=second_avg_logprob,
                    )
                    return ""

                log_event(
                    logger,
                    logging.INFO,
                    "whisper.confidence_gate.accept",
                    selection="retry_consensus",
                    similarity=similarity,
                    second_risks=",".join(second_risks) or "none",
                    second_min_avg_logprob=second_metrics["min_avg_logprob"],
                    second_max_no_speech_prob=second_metrics["max_no_speech_prob"],
                )
                return self._sanitize_transcript(second_text)
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
        groq_confidence_gate_enabled: bool = True,
        groq_confidence_gate_avg_logprob_threshold: float = DEFAULT_GROQ_GATE_AVG_LOGPROB_THRESHOLD,
        groq_confidence_gate_no_speech_prob_threshold: float = DEFAULT_GROQ_GATE_NO_SPEECH_PROB_THRESHOLD,
        groq_confidence_gate_temperature_threshold: float = DEFAULT_GROQ_GATE_TEMPERATURE_THRESHOLD,
        groq_confidence_gate_min_transcript_similarity: float = DEFAULT_GROQ_GATE_MIN_TRANSCRIPT_SIMILARITY,
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
            "confidence_gate_enabled": groq_confidence_gate_enabled,
            "confidence_gate_avg_logprob_threshold": groq_confidence_gate_avg_logprob_threshold,
            "confidence_gate_no_speech_prob_threshold": groq_confidence_gate_no_speech_prob_threshold,
            "confidence_gate_temperature_threshold": groq_confidence_gate_temperature_threshold,
            "confidence_gate_min_transcript_similarity": groq_confidence_gate_min_transcript_similarity,
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
        if not self._ready.wait(timeout=_BACKGROUND_LOAD_TIMEOUT_SECONDS):
            logger.error("Timed out waiting for STT transcriber to finish loading.")
            return ""

        with self._lock:
            transcriber = self._transcriber
            load_error = self._load_error

        if transcriber is None:
            logger.error(f"Transcription unavailable because STT transcriber failed to load: {load_error}")
            return ""

        return transcriber.transcribe(audio_np_float32)
