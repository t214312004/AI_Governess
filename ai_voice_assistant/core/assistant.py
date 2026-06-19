import os
import time
import queue
import threading
import asyncio
import logging
import subprocess
import inspect
from collections import deque
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime
from core.audio_capture import AudioCapture
from core.audio_player import AudioPlayer, PlaybackProgressSnapshot
from core.heartbeat import HeartbeatScheduler
from core.presence_tracker import PresenceTracker
from core.speaker_recognizer import SpeakerRecognizer
from core.transcriber import (
    BackgroundTranscriber,
    NOISY_TRANSCRIPT_PLACEHOLDER,
    NOISY_TRANSCRIPT_SYSTEM_HINT,
)
from core.vad import VoiceActivityDetector
from core.wake_word import WakeWordDetector
from core.whisper_audio_archive import WhisperAudioArchive
from core.sentence_builder import SentenceBuilder
from core.state_machine import State, VoiceAssistantStateMachine
from llm.base_client import BaseLLMClient, STREAM_ACTIVITY_KEEPALIVE
from llm.client_factory import create_llm_client
from llm.semantic_chunker import SemanticChunker
from tts.edge_tts_engine import EdgeTTSEngine
from utils.logger import get_logger, log_event, log_llm_io
from config import config

logger = get_logger(__name__)

_INTERRUPT_CONTEXT_TTL_SECONDS = 30.0
_REQUEST_INTERRUPT_GRACE_SECONDS = 2.0
_LLM_FAILURE_WINDOW_SECONDS = 90.0
_LLM_FAILURE_THRESHOLD = 3
_LLM_CIRCUIT_COOLDOWN_SECONDS = 120.0
_LLM_CIRCUIT_OPEN_MESSAGE = "我現在連不上語言模型，先不讓你一直等，請稍後再試一次。"
_LLM_EMPTY_RESPONSE_MESSAGE = "我剛剛沒有成功產生回覆，請再試一次。"
_LLM_TIMEOUT_MESSAGE = "抱歉，連線逾時了，請再試一次喔。"
_LLM_PARTIAL_RESPONSE_TIMEOUT_MESSAGE = "我剛剛回覆到一半中斷了，請再試一次。"
_LLM_BACKEND_ERROR_MESSAGE = "抱歉，AI 後端目前連線不穩，請稍後再試一次。"
_NOISY_TRANSCRIPT_RETRY_MESSAGE = "我剛剛沒有聽清楚，請再說一次。"
_HEARTBEAT_NOP_TAG = "[HEARTBEAT_NOP]"
_HEARTBEAT_SILENT_TAG = "[HEARTBEAT_SILENT]"
_HEARTBEAT_SPEAK_MAX_CHARS = 200
_HEARTBEAT_SPEAK_MIN_INTERVAL = 1800.0
_HEARTBEAT_PREEMPT_TIMEOUT = 5.0
_HEARTBEAT_NOP_SESSION_REFRESH_THRESHOLD = 3
_HEARTBEAT_ACTIVE_START_HOUR = 8
_HEARTBEAT_ACTIVE_END_HOUR = 21
_HOT_LISTEN_AUDIO_GUARD_SECONDS = 0.45
_HOT_LISTEN_TIMEOUT_FALLBACK_SECONDS = 8.0
_HOT_LISTEN_TIMEOUT_MIN_SECONDS = 1.0
_HOT_LISTEN_TIMEOUT_MAX_SECONDS = 60.0
_MAX_PENDING_RESPONSE_WHITESPACE = 256
_BACKEND_ERROR_RESPONSE_PREFIXES = (
    "error: failed to send message:",
    "error: timed out waiting for response",
    "無法連線至本地 ai 助理",
    "無法連線至本地 Codex 助理",
    "等等哦！我還沒準備好",
)
_BACKEND_ERROR_RESPONSE_NEEDLES = (
    "trajectory not found",
)


@dataclass(slots=True)
class PendingInterruptContext:
    created_at: float
    keyword: str
    interrupted_state: str
    playback_snapshot: PlaybackProgressSnapshot | None

class VoiceAssistant:
    def __init__(self):
        self.app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.sm = VoiceAssistantStateMachine(hot_listen_timeout=self._effective_hot_listen_timeout())
        self.state_callback = None
        self.message_callback = None
        self.session_refresh_callback = None

        self.capture = AudioCapture(
            sample_rate=config.get("audio", "input_sample_rate"),
            channels=1,
            blocksize=config.get("audio", "input_block_size")
        )
        self.audio_player = AudioPlayer(
            sample_rate=config.get("audio", "output_sample_rate"),
            channels=1,
            blocksize=config.get("audio", "output_block_size")
        )

        self.vad = VoiceActivityDetector(
            threshold=config.get("vad", "threshold"),
            sampling_rate=config.get("audio", "input_sample_rate"),
            min_silence_duration_ms=config.get("vad", "min_silence_duration_ms"),
            speech_pad_ms=config.get("vad", "speech_pad_ms", default=30),
        )

        whisper_backend = config.get("whisper", "backend", default="local") or "local"
        groq_whisper_config = config.get("whisper", "groq", default={}) or {}

        # Large local Whisper models can take a long time to load; keep GUI startup responsive.
        self.transcriber = BackgroundTranscriber(
            backend=whisper_backend,
            model_size=config.get("whisper", "model_size"),
            device=config.get("whisper", "device"),
            compute_type=config.get("whisper", "compute_type", default="int8"),
            language=config.get("whisper", "language", default="zh"),
            initial_prompt=config.get("whisper", "initial_prompt", default="以下是繁體中文語音內容的逐字稿。"),
            groq_api_key=groq_whisper_config.get("api_key"),
            groq_api_key_env=groq_whisper_config.get("api_key_env", "GROQ_API_KEY"),
            groq_model=groq_whisper_config.get("model", "whisper-large-v3"),
            groq_api_url=groq_whisper_config.get(
                "api_url",
                "https://api.groq.com/openai/v1/audio/transcriptions",
            ),
            groq_timeout_seconds=groq_whisper_config.get("timeout_seconds", 30.0),
        )

        wake_word_keywords_file = self._resolve_app_path(
            config.get("wake_word", "keywords_file", default="keywords.txt"),
            "keywords.txt",
        )
        wake_word_model_dir = self._resolve_app_path(
            config.get(
                "wake_word",
                "model_dir",
                default="models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01",
            ),
            "models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01",
        )
        self.wake_word = WakeWordDetector(
            keywords_file=wake_word_keywords_file,
            model_dir=wake_word_model_dir
        )

        self.sentence_builder = SentenceBuilder()

        self.llm_client = self._create_current_llm_client()
        self.chunker = SemanticChunker(
            split_punctuation=config.get("semantic_chunker", "split_punctuation"),
            also_split=config.get("semantic_chunker", "also_split")
        )

        self.tts_engine = EdgeTTSEngine(
            voice=config.get("tts", "voice"),
            rate=config.get("tts", "rate", default="+0%"),
            volume=config.get("tts", "volume", default="+0%"),
        )
        self.whisper_audio_archive = self._create_whisper_audio_archive()
        self.speaker_recognizer = self._create_speaker_recognizer()
        self.presence_tracker = PresenceTracker(
            presence_ttl_seconds=self._resolve_presence_ttl_seconds(),
            enabled=self._presence_enabled(),
        )
        self.heartbeat = HeartbeatScheduler(
            interval_seconds=self._resolve_heartbeat_interval_seconds(),
            fire_callback=self._on_heartbeat_fire,
        )

        self.async_loop = None
        self.async_thread = None
        self._async_loop_ready_event = None
        self.perception_thread = None
        self.interrupt_signal = None
        self.state_context = {"current_llm_future": None, "current_llm_client": None}
        self.last_backend_switch_error = ""
        self._active_request_started_at = 0.0
        self._active_request_first_token_received = False
        now = time.time()
        self.last_interaction_time = now
        self.last_session_activity_time = now
        self._collecting_started_at = 0.0
        self.is_vad_speaking = False
        self.component_lock = threading.Lock()
        self.request_lock = threading.Lock()
        self.voice_execution_lock = threading.Lock()
        self.voice_execution_generation = 0
        self.activity_prompt_lock = threading.Lock()
        self.pending_interrupt_context_lock = threading.Lock()
        self._llm_failure_timestamps = deque()
        self._llm_circuit_open_until = 0.0
        self._llm_circuit_last_reason = None
        self.running = False
        self.voice_paused = False
        self.user_activity_prompt_active = False
        self.user_activity_interrupt_signal = None
        self.pending_interrupt_context = None
        self._heartbeat_active = False
        self._heartbeat_cancel_event = None
        self._last_heartbeat_speak_time = 0.0
        self._heartbeat_consecutive_nop_count = 0
        self._ignore_audio_until = 0.0
        self._heartbeat_off_hours_logged = False

    def _resolve_app_path(self, configured_path: str | None, fallback_dir_name: str) -> str:
        raw_path = configured_path or fallback_dir_name
        if os.path.isabs(raw_path):
            return raw_path
        return os.path.join(self.app_dir, raw_path)

    def _drain_capture_queue(self) -> int:
        """Drop already-captured microphone chunks that belong to a previous state."""
        try:
            audio_q = self.capture.get_audio_queue()
        except Exception:
            return 0

        try:
            pending = audio_q.qsize()
        except Exception:
            pending = 0
        if not isinstance(pending, int) or pending <= 0:
            return 0

        drained = 0
        for _ in range(min(pending, 1000)):
            try:
                audio_q.get_nowait()
                drained += 1
            except queue.Empty:
                break
            except Exception:
                break
        return drained

    def _audio_input_guard_active(self) -> bool:
        return time.monotonic() < self._ignore_audio_until

    def _begin_hot_listen_audio_guard(self, *, reason: str):
        self._ignore_audio_until = max(
            self._ignore_audio_until,
            time.monotonic() + _HOT_LISTEN_AUDIO_GUARD_SECONDS,
        )
        drained_chunks = self._drain_capture_queue()
        log_event(
            logger,
            logging.DEBUG,
            "audio_input.guard_started",
            reason=reason,
            duration_seconds=f"{_HOT_LISTEN_AUDIO_GUARD_SECONDS:.3f}",
            drained_chunks=drained_chunks,
        )

    def _should_send_timeout_partial(self, partial_audio, command_timeout_seconds: float) -> bool:
        if partial_audio is None or len(partial_audio) == 0:
            return False

        sample_rate = config.get("audio", "input_sample_rate", default=16000) or 16000
        duration_seconds = len(partial_audio) / float(sample_rate)
        log_event(
            logger,
            logging.INFO,
            "collecting.timeout_partial_accepted",
            duration_seconds=f"{duration_seconds:.3f}",
            timeout_seconds=f"{float(command_timeout_seconds):.3f}",
            samples=len(partial_audio),
        )
        return True

    def _create_whisper_audio_archive(self):
        if not config.get("whisper_audio_archive", "enabled", default=True):
            logger.info("Whisper audio archiving disabled by config.")
            return None

        sidecar_enabled = config.get(
            "whisper_audio_archive",
            "write_transcript_sidecar",
            default=True,
        )
        archive_dir = self._resolve_app_path(
            config.get("whisper_audio_archive", "directory", default="whisper_audio_archive"),
            "whisper_audio_archive",
        )
        try:
            archive = WhisperAudioArchive(
                base_dir=archive_dir,
                sample_rate=config.get("audio", "input_sample_rate"),
                write_transcript_sidecar=sidecar_enabled,
            )
            log_event(
                logger,
                logging.INFO,
                "whisper_archive.enabled",
                directory=archive_dir,
                sidecar=bool(sidecar_enabled),
            )
            return archive
        except Exception as e:
            logger.warning(f"Failed to initialize Whisper audio archive: {e}")
            return None

    def _create_speaker_recognizer(self):
        if not config.get("speaker_recognition", "enabled", default=True):
            logger.info("Speaker recognition disabled by config.")
            return None

        profile_dir = self._resolve_app_path(
            config.get("speaker_recognition", "profile_dir", default="voice_profiles"),
            "voice_profiles",
        )
        threshold = config.get("speaker_recognition", "threshold", default=0.75)
        min_duration_seconds = config.get(
            "speaker_recognition",
            "min_duration_seconds",
            default=0.8,
        )
        try:
            recognizer = SpeakerRecognizer(
                profile_dir=profile_dir,
                threshold=threshold,
                sample_rate=config.get("audio", "input_sample_rate"),
                min_duration_seconds=min_duration_seconds,
            )
        except Exception as e:
            logger.warning(f"Failed to initialize speaker recognizer: {e}")
            return None

        if not recognizer.is_available():
            logger.warning(
                "Speaker recognizer backend unavailable. Continuing without speaker ID."
            )
            return None

        profile_embeddings = getattr(recognizer, "profile_embeddings", {})
        if isinstance(profile_embeddings, dict):
            active_profiles = sorted(profile_embeddings.keys())
        else:
            active_profiles = []

        log_event(
            logger,
            logging.INFO,
            "speaker_recognition.enabled",
            profile_dir=profile_dir,
            backend=getattr(recognizer, "backend_name", "unknown"),
            threshold=f"{float(threshold):.2f}",
            min_duration_seconds=f"{float(min_duration_seconds):.2f}",
            profile_count=len(active_profiles),
            active_profiles=active_profiles,
        )

        return recognizer

    @staticmethod
    def _format_system_hint(message: str | None) -> str:
        if not message:
            return ""
        compact = " ".join(str(message).split())
        if not compact:
            return ""
        return f"(系統提示: {compact})"

    @staticmethod
    def _extract_transcript_for_llm(text: str) -> tuple[str | None, str | None]:
        if text == NOISY_TRANSCRIPT_PLACEHOLDER:
            return NOISY_TRANSCRIPT_SYSTEM_HINT, None
        return None, text

    def _build_llm_text(
        self,
        text: str,
        speaker_name: str | None,
        interrupt_notice: str | None = None,
    ) -> str:
        sections: list[str] = []
        if interrupt_notice:
            sections.append(self._format_system_hint(interrupt_notice))

        transcript_hint, transcript_text = self._extract_transcript_for_llm(text)
        if transcript_hint:
            sections.append(self._format_system_hint(transcript_hint))

        if speaker_name:
            sections.append(
                self._format_system_hint(f"這句話的說話者可能是 {speaker_name}。")
            )

        if transcript_text:
            sections.append(transcript_text)

        return "\n".join(section for section in sections if section)

    def _build_llm_prompt(self, text: str, *, current_time: str) -> str:
        time_hint = self._format_system_hint(f"目前時間：{current_time}")
        if text:
            return f"{time_hint}\n{text}"
        return time_hint

    def _store_pending_interrupt_context(
        self,
        *,
        keyword: str,
        interrupted_state: State,
        playback_snapshot: PlaybackProgressSnapshot | None,
    ) -> None:
        context = PendingInterruptContext(
            created_at=time.time(),
            keyword=keyword,
            interrupted_state=interrupted_state.name,
            playback_snapshot=playback_snapshot,
        )
        with self.pending_interrupt_context_lock:
            self.pending_interrupt_context = context

    def _consume_pending_interrupt_notice(self) -> str | None:
        with self.pending_interrupt_context_lock:
            context = self.pending_interrupt_context
            if context is None:
                return None
            if time.time() - context.created_at > _INTERRUPT_CONTEXT_TTL_SECONDS:
                self.pending_interrupt_context = None
                return None
            self.pending_interrupt_context = None

        return self._format_pending_interrupt_notice(context)

    def _format_pending_interrupt_notice(self, context: PendingInterruptContext) -> str:
        snapshot = context.playback_snapshot
        if snapshot is None or snapshot.status == "queued":
            return (
                f"上一輪語音回覆在開始播放前或剛開始播放時，就被使用者以喚醒詞「{context.keyword}」打斷。"
                "請不要假設使用者已聽到上一輪回覆內容。"
            )

        sentence_excerpt = self._excerpt_text(snapshot.sentence_text, max_chars=30)
        heard_excerpt = self._excerpt_text(snapshot.heard_text, max_chars=24)
        if heard_excerpt:
            return (
                f"上一輪語音回覆在播放到「{sentence_excerpt}」這一句的「{heard_excerpt}」附近時，"
                f"被使用者以喚醒詞「{context.keyword}」打斷。"
                "後續語音內容使用者不一定聽到，請不要假設使用者已知未播完的內容。"
            )

        if sentence_excerpt:
            return (
                f"上一輪語音回覆在播放「{sentence_excerpt}」這一句附近時，"
                f"被使用者以喚醒詞「{context.keyword}」打斷。"
                "後續語音內容使用者不一定聽到，請不要假設使用者已知未播完的內容。"
            )

        return (
            f"上一輪語音回覆被使用者以喚醒詞「{context.keyword}」打斷。"
            "後續語音內容使用者不一定聽到，請不要假設使用者已知未播完的內容。"
        )

    @staticmethod
    def _excerpt_text(text: str | None, max_chars: int = 24) -> str:
        if not text:
            return ""
        compact = " ".join(text.split())
        if len(compact) <= max_chars:
            return compact
        return compact[: max_chars - 1].rstrip() + "…"

    def _build_utterance_id(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    def _presence_enabled(self) -> bool:
        enabled = config.get("presence_detection", "enabled", default=True)
        return True if enabled is None else bool(enabled)

    def _resolve_presence_ttl_seconds(self) -> float:
        raw_ttl = config.get("presence_detection", "ttl_seconds", default=300.0)
        try:
            ttl = float(raw_ttl)
        except (TypeError, ValueError):
            ttl = 300.0
        return max(0.0, ttl)

    def _heartbeat_enabled(self) -> bool:
        enabled = config.get("heartbeat", "enabled", default=True)
        return True if enabled is None else bool(enabled)

    @staticmethod
    def _heartbeat_within_active_window(now: datetime | None = None) -> bool:
        current_time = (now or datetime.now()).time()
        start = current_time.replace(
            hour=_HEARTBEAT_ACTIVE_START_HOUR,
            minute=0,
            second=0,
            microsecond=0,
        )
        end = current_time.replace(
            hour=_HEARTBEAT_ACTIVE_END_HOUR,
            minute=0,
            second=0,
            microsecond=0,
        )
        return start <= current_time < end

    def _resolve_heartbeat_interval_seconds(self) -> float:
        raw_minutes = config.get("heartbeat", "interval_minutes", default=10) or 10
        try:
            minutes = float(raw_minutes)
        except (TypeError, ValueError):
            minutes = 10.0
        if minutes <= 0:
            minutes = 10.0
        return max(10.0, minutes * 60.0)

    @staticmethod
    def _format_heartbeat_interval_text(interval_seconds: float) -> str:
        if interval_seconds < 60:
            return f"每{int(round(interval_seconds))}秒"

        interval_minutes = interval_seconds / 60.0
        if float(interval_minutes).is_integer():
            return f"每{int(interval_minutes)}分鐘"
        return f"每{interval_minutes:.1f}分鐘"

    def _reset_heartbeat_nop_streak(self) -> None:
        self._heartbeat_consecutive_nop_count = 0

    def _mark_session_activity(self) -> None:
        self.last_session_activity_time = time.time()

    def _mark_user_interaction(self) -> None:
        now = time.time()
        self.last_interaction_time = now
        self.last_session_activity_time = now
        self._reset_heartbeat_nop_streak()

    async def _cancel_heartbeat_llm_client_until(self, deadline: float) -> None:
        if self.llm_client is None:
            return

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return

        cancel_task = asyncio.create_task(self.llm_client.cancel())
        done, _ = await asyncio.wait({cancel_task}, timeout=remaining)
        if cancel_task in done:
            try:
                cancel_task.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("Failed to cancel LLM client while preempting heartbeat.", exc_info=True)
            return

        cancel_task.cancel()
        log_event(
            logger,
            logging.WARNING,
            "heartbeat.preempt_cancel_timeout",
            timeout_seconds=_HEARTBEAT_PREEMPT_TIMEOUT,
        )

    async def _handle_heartbeat_nop(self, heartbeat_id: str) -> None:
        self._heartbeat_consecutive_nop_count += 1
        log_event(
            logger,
            logging.INFO,
            "heartbeat.noop",
            heartbeat_id=heartbeat_id,
            consecutive_nops=self._heartbeat_consecutive_nop_count,
        )

        if self._heartbeat_consecutive_nop_count < _HEARTBEAT_NOP_SESSION_REFRESH_THRESHOLD:
            return

        self._heartbeat_consecutive_nop_count = 0
        log_event(
            logger,
            logging.INFO,
            "heartbeat.noop_refresh_requested",
            heartbeat_id=heartbeat_id,
            threshold=_HEARTBEAT_NOP_SESSION_REFRESH_THRESHOLD,
        )
        try:
            await self._refresh_session_async()
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                "heartbeat.noop_refresh_failed",
                heartbeat_id=heartbeat_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
        else:
            log_event(
                logger,
                logging.INFO,
                "heartbeat.noop_refresh_completed",
                heartbeat_id=heartbeat_id,
                threshold=_HEARTBEAT_NOP_SESSION_REFRESH_THRESHOLD,
            )

    def _request_heartbeat_cancel(self) -> bool:
        cancel_event = self._heartbeat_cancel_event
        if not self._heartbeat_active or cancel_event is None:
            return False

        if threading.current_thread() is self.async_thread:
            cancel_event.set()
            return True

        if (
            self.async_loop is not None
            and self.async_thread is not None
            and hasattr(self.async_thread, "is_alive")
            and self.async_thread.is_alive()
        ):
            try:
                self.async_loop.call_soon_threadsafe(cancel_event.set)
                return True
            except Exception:
                pass

        try:
            cancel_event.set()
        except Exception:
            return False
        return True

    async def _preempt_heartbeat_if_needed(self):
        if not self._heartbeat_active:
            return

        log_event(
            logger,
            logging.DEBUG,
            "heartbeat.preempt_requested",
            state=self.sm.current_state.name,
        )
        deadline = time.monotonic() + _HEARTBEAT_PREEMPT_TIMEOUT
        self._request_heartbeat_cancel()
        await self._cancel_heartbeat_llm_client_until(deadline)
        while self._heartbeat_active and time.monotonic() < deadline:
            await asyncio.sleep(0.05)

        if self._heartbeat_active:
            log_event(
                logger,
                logging.WARNING,
                "heartbeat.preempt_timeout",
                timeout_seconds=_HEARTBEAT_PREEMPT_TIMEOUT,
            )
            return

        log_event(logger, logging.DEBUG, "heartbeat.preempt_completed")

    def _has_active_request(self) -> bool:
        future = self.state_context["current_llm_future"]
        return future is not None and not future.done()

    def is_busy(self) -> bool:
        return self.sm.current_state not in (State.IDLE_LISTEN, State.HOT_LISTEN)

    def can_accept_text_message(self) -> bool:
        with self.request_lock:
            return (not self._has_active_request()) and not self.is_busy()

    def can_change_backend(self) -> bool:
        with self.request_lock:
            return (not self._has_active_request()) and not self.is_busy() and not self._heartbeat_active

    def _register_request(self, future, llm_client):
        with self.request_lock:
            self.state_context["current_llm_future"] = future
            self.state_context["current_llm_client"] = llm_client

    def _next_voice_execution_generation(self) -> int:
        with self.voice_execution_lock:
            self.voice_execution_generation += 1
            return self.voice_execution_generation

    def _current_voice_execution_generation(self) -> int:
        with self.voice_execution_lock:
            return self.voice_execution_generation

    def _invalidate_voice_execution(self, *, reason: str) -> int:
        generation = self._next_voice_execution_generation()
        log_event(
            logger,
            logging.DEBUG,
            "voice.execution_generation_invalidated",
            generation=generation,
            reason=reason,
        )
        return generation

    def _is_voice_execution_current(self, generation: int | None) -> bool:
        if generation is None:
            return True
        return generation == self._current_voice_execution_generation()

    def _should_continue_voice_execution(
        self,
        generation: int | None,
        *,
        utterance_id: str,
        stage: str,
    ) -> bool:
        if self.sm.current_state == State.SENDING and self._is_voice_execution_current(generation):
            return True

        log_event(
            logger,
            logging.INFO,
            "voice.execution_stale_dropped",
            utterance_id=utterance_id,
            generation=generation,
            current_generation=self._current_voice_execution_generation(),
            state=self.sm.current_state.name,
            stage=stage,
        )
        return False

    def _submit_request(self, request_coro, llm_client):
        future_holder = {}

        async def guarded_request():
            try:
                await self._preempt_heartbeat_if_needed()
                return await request_coro
            finally:
                self._clear_request(future_holder.get("future"))

        with self.request_lock:
            self._active_request_started_at = time.monotonic()
            self._active_request_first_token_received = False
            try:
                future = self._submit_coroutine(guarded_request())
            except Exception:
                self._active_request_started_at = 0.0
                self._active_request_first_token_received = False
                request_coro.close()
                raise
            future_holder["future"] = future
            self.state_context["current_llm_future"] = future
            self.state_context["current_llm_client"] = llm_client
            return future

    def _clear_interrupt_signal(self):
        signal = self.interrupt_signal
        if signal is None:
            return

        if threading.current_thread() is self.async_thread:
            signal.clear()
            return

        if (
            self.async_loop is not None
            and self.async_thread is not None
            and hasattr(self.async_thread, "is_alive")
            and self.async_thread.is_alive()
        ):
            cleared = threading.Event()

            def clear_signal():
                try:
                    signal.clear()
                finally:
                    cleared.set()

            try:
                self.async_loop.call_soon_threadsafe(clear_signal)
                if cleared.wait(timeout=1.0):
                    return
            except Exception:
                pass

        try:
            signal.clear()
        except Exception:
            pass

    def _mark_active_request_first_token_received(self):
        with self.request_lock:
            if self._active_request_started_at <= 0:
                return
            self._active_request_first_token_received = True

    def _should_suppress_wake_word_interrupt(self) -> tuple[bool, float]:
        if self.sm.current_state != State.SENDING:
            return False, 0.0

        with self.request_lock:
            started_at = self._active_request_started_at
            first_token_received = self._active_request_first_token_received

        if started_at <= 0 or first_token_received:
            return False, 0.0

        request_age = time.monotonic() - started_at
        return request_age < _REQUEST_INTERRUPT_GRACE_SECONDS, request_age

    @staticmethod
    def _should_retry_transcript_locally(text: str) -> bool:
        return text == NOISY_TRANSCRIPT_PLACEHOLDER

    @staticmethod
    def _is_stream_activity_keepalive(chunk: str) -> bool:
        return chunk == STREAM_ACTIVITY_KEEPALIVE

    @staticmethod
    def _classify_backend_error_response(response: str) -> str | None:
        stripped = (response or "").strip()
        if not stripped:
            return None
        lowered = stripped.lower()
        if any(lowered.startswith(prefix.lower()) for prefix in _BACKEND_ERROR_RESPONSE_PREFIXES):
            return "client_error_text"
        if any(needle in lowered for needle in _BACKEND_ERROR_RESPONSE_NEEDLES):
            return "client_error_text"
        return None

    def _hot_listen_enabled(self) -> bool:
        enabled = config.get("hot_listen", "enabled", default=True)
        return True if enabled is None else bool(enabled)

    def _effective_hot_listen_timeout(self) -> float:
        timeout = config.get("hot_listen", "timeout_seconds", default=_HOT_LISTEN_TIMEOUT_FALLBACK_SECONDS)
        try:
            timeout = float(timeout)
        except (TypeError, ValueError):
            timeout = _HOT_LISTEN_TIMEOUT_FALLBACK_SECONDS
        if timeout <= 0:
            timeout = _HOT_LISTEN_TIMEOUT_FALLBACK_SECONDS
        timeout = min(max(timeout, _HOT_LISTEN_TIMEOUT_MIN_SECONDS), _HOT_LISTEN_TIMEOUT_MAX_SECONDS)
        return timeout if self._hot_listen_enabled() else 0.0

    def apply_hot_listen_settings(self):
        self.sm.hot_listen_timeout = self._effective_hot_listen_timeout()
        log_event(
            logger,
            logging.INFO,
            "hot_listen.settings_applied",
            enabled=self._hot_listen_enabled(),
            timeout_seconds=self.sm.hot_listen_timeout,
        )
        if self.sm.current_state == State.HOT_LISTEN and self.sm.hot_listen_timeout <= 0:
            self._update_state(State.IDLE_LISTEN)

    def apply_heartbeat_settings(self):
        self.heartbeat.interval_seconds = self._resolve_heartbeat_interval_seconds()
        enabled = self._heartbeat_enabled()
        log_event(
            logger,
            logging.INFO,
            "heartbeat.settings_applied",
            enabled=enabled,
            interval_seconds=self.heartbeat.interval_seconds,
            active_hours=f"{_HEARTBEAT_ACTIVE_START_HOUR:02d}:00-{_HEARTBEAT_ACTIVE_END_HOUR:02d}:00",
        )

        if not enabled:
            self._request_heartbeat_cancel()
            if self.async_loop and self.heartbeat.is_enabled:
                self.heartbeat.stop(self.async_loop).result(timeout=5)
            return

        if self.async_loop and not self.heartbeat.is_enabled:
            self.heartbeat.start(self.async_loop).result(timeout=2)

    @staticmethod
    def _normalize_timeout_seconds(raw_timeout, fallback: float) -> float:
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError):
            timeout = float(fallback)
        if timeout <= 0:
            timeout = float(fallback)
        return timeout

    def _resolve_llm_timeout_seconds(self, key: str, *, fallback: float = 90.0) -> float:
        legacy_timeout = self._normalize_timeout_seconds(
            config.get("llm", "response_timeout_seconds", default=fallback),
            fallback,
        )
        raw_timeout = config.get("llm", key, default=legacy_timeout)
        return self._normalize_timeout_seconds(raw_timeout, legacy_timeout)

    @staticmethod
    def _normalize_positive_int(raw_value, fallback: int) -> int:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = int(fallback)
        if value <= 0:
            value = int(fallback)
        return value

    def _next_llm_stream_timeout(self, first_token_received: bool) -> tuple[str, float]:
        if first_token_received:
            return "stream_idle", self._resolve_llm_timeout_seconds("stream_idle_timeout_seconds")
        return "first_token", self._resolve_llm_timeout_seconds("first_token_timeout_seconds")

    def _resolve_llm_failure_window_seconds(self) -> float:
        return self._normalize_timeout_seconds(
            config.get("llm", "failure_window_seconds", default=_LLM_FAILURE_WINDOW_SECONDS),
            _LLM_FAILURE_WINDOW_SECONDS,
        )

    def _resolve_llm_failure_threshold(self) -> int:
        return self._normalize_positive_int(
            config.get("llm", "failure_threshold", default=_LLM_FAILURE_THRESHOLD),
            _LLM_FAILURE_THRESHOLD,
        )

    def _resolve_llm_circuit_cooldown_seconds(self) -> float:
        return self._normalize_timeout_seconds(
            config.get("llm", "circuit_cooldown_seconds", default=_LLM_CIRCUIT_COOLDOWN_SECONDS),
            _LLM_CIRCUIT_COOLDOWN_SECONDS,
        )

    def _prune_llm_failures(self, *, now: float | None = None) -> None:
        current_time = time.monotonic() if now is None else now
        failure_window = self._resolve_llm_failure_window_seconds()
        while self._llm_failure_timestamps and current_time - self._llm_failure_timestamps[0] > failure_window:
            self._llm_failure_timestamps.popleft()

    def _record_llm_success(self) -> None:
        with self.request_lock:
            self._llm_failure_timestamps.clear()
            self._llm_circuit_open_until = 0.0
            self._llm_circuit_last_reason = None

    def _record_llm_failure(
        self,
        *,
        mode: str,
        reason: str,
        request_id: str | None = None,
    ) -> None:
        now = time.monotonic()
        with self.request_lock:
            self._prune_llm_failures(now=now)
            self._llm_failure_timestamps.append(now)
            failure_count = len(self._llm_failure_timestamps)
            threshold = self._resolve_llm_failure_threshold()
            circuit_opened = False
            if failure_count >= threshold:
                if self._llm_circuit_open_until <= now:
                    circuit_opened = True
                self._llm_circuit_open_until = now + self._resolve_llm_circuit_cooldown_seconds()
            self._llm_circuit_last_reason = reason
            retry_after = max(0.0, self._llm_circuit_open_until - now)

        log_event(
            logger,
            logging.WARNING,
            "llm.failure_recorded",
            mode=mode,
            request_id=request_id,
            reason=reason,
            recent_failures=failure_count,
            circuit_open=retry_after > 0,
            circuit_opened=circuit_opened,
            retry_after_seconds=f"{retry_after:.3f}",
        )

    def _get_llm_circuit_status(self) -> tuple[bool, float, str | None]:
        with self.request_lock:
            now = time.monotonic()
            self._prune_llm_failures(now=now)
            remaining = self._llm_circuit_open_until - now
            if remaining <= 0:
                self._llm_circuit_open_until = 0.0
                return False, 0.0, self._llm_circuit_last_reason
            return True, remaining, self._llm_circuit_last_reason

    def _should_skip_llm_request(self, *, mode: str, request_id: str | None = None) -> bool:
        is_open, retry_after, last_reason = self._get_llm_circuit_status()
        if not is_open:
            return False

        self._consume_pending_interrupt_notice()
        log_event(
            logger,
            logging.WARNING,
            "llm.request_skipped",
            mode=mode,
            request_id=request_id,
            reason="circuit_open",
            retry_after_seconds=f"{retry_after:.3f}",
            last_failure_reason=last_reason,
        )
        self.on_message("assistant", _LLM_CIRCUIT_OPEN_MESSAGE, update_existing=False)
        if mode == "voice" and self.sm.current_state == State.SENDING:
            self._submit_coroutine(self._speak_standalone_message_async(_LLM_CIRCUIT_OPEN_MESSAGE, target_state=State.IDLE_LISTEN))
        return True

    def _mark_collecting_started(self):
        self._collecting_started_at = time.time()

    def _force_terminate_llm_process(self, llm_client, *, reason: str) -> bool:
        process = getattr(llm_client, "process", None)
        if process is None or getattr(process, "returncode", None) is not None:
            return False

        pid = getattr(process, "pid", None)
        killed = False
        if os.name == "nt" and isinstance(pid, int) and pid > 0:
            try:
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    check=False,
                )
                killed = True
            except Exception as exc:
                log_event(
                    logger,
                    logging.WARNING,
                    "llm.client_process_taskkill_failed",
                    client_type=type(llm_client).__name__,
                    pid=pid,
                    reason=reason,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )

        if not killed:
            try:
                process.kill()
                killed = True
            except Exception as exc:
                log_event(
                    logger,
                    logging.WARNING,
                    "llm.client_process_kill_failed",
                    client_type=type(llm_client).__name__,
                    pid=pid,
                    reason=reason,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                return False

        log_event(
            logger,
            logging.WARNING,
            "llm.client_process_killed",
            client_type=type(llm_client).__name__,
            pid=pid,
            reason=reason,
        )
        return True

    def _close_llm_client(self, llm_client):
        if llm_client is None:
            return

        future = None
        try:
            close_coro = llm_client.aclose()
            if self.async_loop:
                future = self._submit_coroutine(close_coro)
                if hasattr(future, "result"):
                    future.result(timeout=5)
            else:
                asyncio.run(close_coro)
        except FutureTimeoutError:
            if future is not None and hasattr(future, "cancel"):
                future.cancel()
            log_event(
                logger,
                logging.WARNING,
                "llm.client_close_timeout",
                client_type=type(llm_client).__name__,
                timeout_seconds=5,
            )
            self._force_terminate_llm_process(llm_client, reason="close_timeout")
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                "llm.client_close_failed",
                client_type=type(llm_client).__name__,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            self._force_terminate_llm_process(llm_client, reason="close_failed")

    def _clear_request(self, future=None):
        with self.request_lock:
            current_future = self.state_context["current_llm_future"]
            if future is not None and current_future is not future:
                return
            self.state_context["current_llm_future"] = None
            self.state_context["current_llm_client"] = None
            self._active_request_started_at = 0.0
            self._active_request_first_token_received = False

    @staticmethod
    def _normalize_response_chunk(
        full_response: str,
        pending_whitespace: str,
        chunk: str,
    ) -> tuple[str, str]:
        if not chunk:
            return "", pending_whitespace

        if not chunk.strip():
            return "", (pending_whitespace + chunk)[-_MAX_PENDING_RESPONSE_WHITESPACE:]

        body = chunk.lstrip()
        leading = chunk[: len(chunk) - len(body)]
        if not full_response:
            return body, ""

        prefix = VoiceAssistant._collapse_response_whitespace(
            pending_whitespace + leading,
            full_response,
        )
        return prefix + body, ""

    @staticmethod
    def _collapse_response_whitespace(whitespace: str, previous_text: str) -> str:
        if not whitespace:
            return ""
        if "\n" in whitespace or "\r" in whitespace:
            if previous_text.endswith("\n\n"):
                return ""
            if previous_text.endswith("\n"):
                return "\n"
            return "\n\n"
        if previous_text.endswith((" ", "\t", "\n", "\r")):
            return ""
        return " "

    def _create_current_llm_client(self):
        backend = config.get("llm", "active_backend")
        backend_config = config.get("llm", backend, default={}) or {}
        try:
            client = create_llm_client(backend, **backend_config)
        except Exception:
            logger.exception(f"建立 LLM client 失敗，backend={backend}")
            raise

        log_event(
            logger,
            logging.INFO,
            "llm.client_ready",
            backend=backend,
        )
        return client

    @staticmethod
    def _client_supports_session_refresh(llm_client) -> bool:
        refresh_method = getattr(llm_client, "refresh_session", None)
        if not callable(refresh_method):
            return False
        if not isinstance(llm_client, BaseLLMClient):
            return True
        return getattr(type(llm_client), "refresh_session", None) is not BaseLLMClient.refresh_session

    def _submit_coroutine(self, coro):
        try:
            return asyncio.run_coroutine_threadsafe(coro, self.async_loop)
        except Exception:
            coro.close()
            raise

    def _ensure_async_loop(self, *, wait_until_ready: bool = False):
        if (
            self.async_loop is not None
            and self.async_thread is not None
            and hasattr(self.async_thread, "is_alive")
            and self.async_thread.is_alive()
        ):
            return

        self.async_loop = asyncio.new_event_loop()
        ready_event = threading.Event() if wait_until_ready else None
        self._async_loop_ready_event = ready_event
        self.async_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.async_thread.start()

        if ready_event is not None and not ready_event.wait(timeout=5):
            raise RuntimeError("Async event loop did not become ready in time.")

    def prepare_for_gui(self, status_callback=None):
        status = status_callback or (lambda _message: None)
        log_event(logger, logging.INFO, "startup_prepare.started")

        status("準備背景 async loop...")
        self._ensure_async_loop(wait_until_ready=True)

        status("準備 LLM backend...")
        llm_ready_future = self._submit_coroutine(self._ensure_llm_ready_async())

        status("載入 Whisper 語音辨識模型...")
        self._wait_for_transcriber_ready()

        status("等待 LLM backend ready...")
        if hasattr(llm_ready_future, "result"):
            llm_ready_future.result()

        status("預備完成，啟動 GUI...")
        log_event(logger, logging.INFO, "startup_prepare.completed")

    def _wait_for_transcriber_ready(self):
        wait_until_ready = getattr(self.transcriber, "wait_until_ready", None)
        if not callable(wait_until_ready):
            return

        while True:
            if wait_until_ready(timeout=0.5):
                return

            load_error = getattr(self.transcriber, "load_error", None)
            if load_error is not None:
                raise RuntimeError(f"Whisper model failed to load: {load_error}") from load_error

    async def _ensure_llm_ready_async(self):
        return await self._ensure_specific_llm_ready_async(self.llm_client)

    async def _ensure_specific_llm_ready_async(self, llm_client):
        ensure_ready = getattr(llm_client, "ensure_ready", None)
        if callable(ensure_ready):
            result = ensure_ready()
            if inspect.isawaitable(result):
                return await result
            return result
        return True

    def _ensure_llm_client_ready_blocking(self, llm_client, *, timeout_seconds: float = 60.0):
        ready_coro = self._ensure_specific_llm_ready_async(llm_client)
        if (
            isinstance(self.async_loop, asyncio.AbstractEventLoop)
            and self.async_loop.is_running()
        ):
            future = self._submit_coroutine(ready_coro)
            try:
                if hasattr(future, "result"):
                    return future.result(timeout=timeout_seconds)
                return True
            except FutureTimeoutError:
                if hasattr(future, "cancel"):
                    future.cancel()
                raise RuntimeError(
                    f"LLM backend did not become ready within {timeout_seconds:.0f} seconds."
                )
        return asyncio.run(ready_coro)

    def set_callbacks(self, state_callback, message_callback, session_refresh_callback=None):
        self.state_callback = state_callback
        self.message_callback = message_callback
        self.session_refresh_callback = session_refresh_callback

    def on_state_change(self, state):
        if self.state_callback:
            self.state_callback(state)

    def on_message(
        self,
        role,
        text,
        *,
        update_existing: bool | None = None,
        speaker_name: str | None = None,
    ):
        if self.message_callback:
            callback_kwargs = {}
            if update_existing is not None:
                callback_kwargs["update_existing"] = update_existing
            if speaker_name is not None:
                callback_kwargs["speaker_name"] = speaker_name

            if callback_kwargs:
                self.message_callback(role, text, **callback_kwargs)
            else:
                self.message_callback(role, text)

    def on_session_refreshed(self):
        if self.session_refresh_callback:
            self.session_refresh_callback()

    async def _refresh_session_via_client_async(self) -> bool:
        refreshed = bool(await self.llm_client.refresh_session())
        if refreshed:
            self.on_session_refreshed()
        return refreshed

    def start(self):
        if self.running:
            logger.warning("Voice Assistant is already running.")
            return
        self.running = True
        log_event(
            logger,
            logging.INFO,
            "assistant.starting",
            backend=config.get("llm", "active_backend"),
            hot_listen_enabled=self._hot_listen_enabled(),
            hot_listen_timeout=self._effective_hot_listen_timeout(),
            input_sample_rate=config.get("audio", "input_sample_rate"),
            output_sample_rate=config.get("audio", "output_sample_rate"),
        )
        self._ensure_async_loop()

        try:
            self.capture.start()
            self.audio_player.start()

            self.perception_thread = threading.Thread(target=self._perception_loop, daemon=True)
            self.perception_thread.start()

            self.apply_hot_listen_settings()
            self._update_state(State.IDLE_LISTEN)
            logger.info("Voice Assistant started.")
            log_event(
                logger,
                logging.INFO,
                "assistant.ready",
                state=self.sm.current_state.name,
            )

            self._warm_up_llm()
            self.apply_heartbeat_settings()
        except Exception:
            self.running = False
            try:
                self.capture.stop()
            except Exception:
                pass
            try:
                self.audio_player.stop()
            except Exception:
                pass
            if self.async_loop and self.heartbeat.is_enabled:
                try:
                    self.heartbeat.stop(self.async_loop).result(timeout=5)
                except Exception:
                    pass
            if self.async_loop:
                try:
                    self.async_loop.call_soon_threadsafe(self.async_loop.stop)
                except Exception:
                    pass
            raise

    def _warm_up_llm(self):
        """Start ACP-capable clients in the background when available."""
        try:
            if hasattr(self.llm_client, '_start_acp') and self.async_loop:
                self._submit_coroutine(self.llm_client._start_acp())
                logger.info("LLM 預熱中（背景啟動 ACP）。")
        except Exception as e:
            logger.warning(f"LLM 預熱失敗（不影響功能）：{e}")

    def stop(self):
        log_event(
            logger,
            logging.INFO,
            "assistant.stopping",
            state=self.sm.current_state.name,
        )
        self.running = False
        self._request_heartbeat_cancel()
        if self.async_loop and self.heartbeat.is_enabled:
            try:
                self.heartbeat.stop(self.async_loop).result(timeout=5)
            except FutureTimeoutError:
                log_event(
                    logger,
                    logging.WARNING,
                    "heartbeat.stop_timeout",
                    timeout_seconds=5,
                )
            except Exception as exc:
                log_event(
                    logger,
                    logging.WARNING,
                    "heartbeat.stop_failed",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
        if self.user_activity_prompt_active or self.sm.current_state in [State.SENDING, State.SPEAKING]:
            try:
                self.interrupt()
            except Exception:
                pass
        self.capture.stop()
        # Drain queued chunks so the perception thread can exit promptly after shutdown.
        try:
            audio_q = self.capture.get_audio_queue()
            while not audio_q.empty():
                try:
                    audio_q.get_nowait()
                except Exception:
                    break
        except Exception:
            pass
        self.audio_player.stop()
        self._close_llm_client(self.llm_client)
        if self.async_loop:
            self.async_loop.call_soon_threadsafe(self.async_loop.stop)
        for thread in (self.perception_thread, self.async_thread):
            if thread and hasattr(thread, "join"):
                try:
                    thread.join(timeout=1)
                except Exception:
                    pass
        logger.info("Voice Assistant stopped.")

    def _run_async_loop(self):
        asyncio.set_event_loop(self.async_loop)
        self.interrupt_signal = asyncio.Event()
        self.user_activity_interrupt_signal = asyncio.Event()
        if self._async_loop_ready_event is not None:
            self._async_loop_ready_event.set()
        self.async_loop.run_forever()

    def shutdown_prepared_resources(self):
        self._close_llm_client(self.llm_client)
        if self.async_loop:
            try:
                self.async_loop.call_soon_threadsafe(self.async_loop.stop)
            except Exception:
                pass
        if self.async_thread and hasattr(self.async_thread, "join"):
            try:
                self.async_thread.join(timeout=1)
            except Exception:
                pass

    async def _refresh_session_async(self) -> bool:
        backend = config.get("llm", "active_backend")
        log_event(
            logger,
            logging.INFO,
            "llm.session_refresh_requested",
            backend=backend,
        )
        if backend == "openclaw":
            new_user = f"voice-assistant-{int(time.time())}"
            config.set("llm", "openclaw", "user", value=new_user)

        if self._client_supports_session_refresh(self.llm_client):
            return await self._refresh_session_via_client_async()

        old_client = self.llm_client
        self.llm_client = self._create_current_llm_client()
        if old_client is not None and hasattr(old_client, "aclose"):
            close_result = old_client.aclose()
            if asyncio.iscoroutine(close_result):
                await close_result
        log_event(
            logger,
            logging.INFO,
            "llm.session_refresh_recreated_client",
            backend=backend,
        )
        self.on_session_refreshed()
        return True

    def _refresh_session(self):
        backend = config.get("llm", "active_backend")
        log_event(
            logger,
            logging.INFO,
            "llm.session_refresh_requested",
            backend=backend,
        )
        if backend == "openclaw":
            new_user = f"voice-assistant-{int(time.time())}"
            config.set("llm", "openclaw", "user", value=new_user)

        if self._client_supports_session_refresh(self.llm_client):
            self._submit_coroutine(self._refresh_session_via_client_async())
        else:
            old_client = self.llm_client
            self.llm_client = self._create_current_llm_client()
            self._close_llm_client(old_client)
            log_event(
                logger,
                logging.INFO,
                "llm.session_refresh_recreated_client",
                backend=backend,
            )
            self.on_session_refreshed()

    def _update_state(self, state):
        if state == State.COLLECTING:
            timeout_mins = config.get("llm", "session_timeout_minutes", default=5)
            if time.time() - self.last_session_activity_time > timeout_mins * 60:
                logger.info(f"Session 已超過 {timeout_mins} 分鐘未活動，自動刷新...")
                self._refresh_session()
        else:
            self._collecting_started_at = 0.0

        if state != State.IDLE_LISTEN and threading.current_thread() is not self.async_thread:
            self._request_heartbeat_cancel()

        if state == State.HOT_LISTEN:
            self._begin_hot_listen_audio_guard(reason="enter_hot_listen")

        if state in [State.IDLE_LISTEN, State.HOT_LISTEN]:
            with self.component_lock:
                self.is_vad_speaking = False
                self.sentence_builder.reset(clear_pre_roll=True)
                self.vad.reset_states()

        self.sm.transition(state)
        self.on_state_change(state)

    def interrupt(
        self,
        *,
        resume_collecting: bool = False,
        source: str | None = None,
        keyword: str | None = None,
    ) -> bool:
        """Stop the current voice interaction and optionally resume capture."""
        target_state = State.COLLECTING if resume_collecting else State.IDLE_LISTEN
        self._request_heartbeat_cancel()
        current_state = self.sm.current_state
        interrupted = False
        playback_snapshot = None

        if self.user_activity_prompt_active:
            logger.info("Interrupting user activity prompt.")
            if self.async_loop and self.user_activity_interrupt_signal:
                self.async_loop.call_soon_threadsafe(self.user_activity_interrupt_signal.set)
            self.audio_player.interrupt()
            interrupted = True

        if current_state in (State.SENDING, State.SPEAKING):
            logger.info("Interrupting current task.")

            if self.async_loop and self.interrupt_signal:
                self.async_loop.call_soon_threadsafe(self.interrupt_signal.set)

            playback_snapshot = self.audio_player.interrupt()

            # Keep state_context updates atomic with request registration and cleanup.
            with self.request_lock:
                current_future = self.state_context["current_llm_future"]
                current_client = self.state_context["current_llm_client"] or self.llm_client
                if current_future:
                    current_future.cancel()
                self.state_context["current_llm_future"] = None
                self.state_context["current_llm_client"] = None
                self._active_request_started_at = 0.0
                self._active_request_first_token_received = False

            if self.async_loop and current_client:
                self._submit_coroutine(current_client.cancel())

            interrupted = True
        elif current_state in (State.COLLECTING, State.HOT_LISTEN):
            logger.info(f"Stopping voice interaction from state {current_state.name}.")
            interrupted = True

        if not interrupted:
            log_event(
                logger,
                logging.DEBUG,
                "interrupt.ignored",
                state=current_state.name,
            )
            return False

        self._invalidate_voice_execution(reason=f"interrupt:{current_state.name.lower()}")

        if source == "wake_word" and keyword and current_state in (State.SENDING, State.SPEAKING):
            self._store_pending_interrupt_context(
                keyword=keyword,
                interrupted_state=current_state,
                playback_snapshot=playback_snapshot,
            )

        self.chunker.reset()
        with self.component_lock:
            self.is_vad_speaking = False
            self.sentence_builder.reset(clear_pre_roll=True)
            self.vad.reset_states()

        if target_state == State.COLLECTING:
            self._mark_collecting_started()
        else:
            self._collecting_started_at = 0.0

        self._update_state(target_state)
        return True

    def _perception_loop(self):
        audio_queue = self.capture.get_audio_queue()
        last_result_audio = None
        last_result_time = 0.0

        while self.running:
            try:
                chunk = audio_queue.get(timeout=0.1)
            except queue.Empty:
                if self.sm.check_hot_listen_timeout():
                    log_event(
                        logger,
                        logging.INFO,
                        "state.hot_listen_timeout",
                        timeout_seconds=self.sm.hot_listen_timeout,
                    )
                    self._update_state(State.IDLE_LISTEN)
                continue

            try:
                if self.voice_paused:
                    continue
                if self._audio_input_guard_active():
                    continue
                mark_audio_presence = False
                with self.component_lock:
                    speech_event = self.vad.process_chunk(chunk)
                    if speech_event:
                        if 'start' in speech_event:
                            self.is_vad_speaking = True
                            mark_audio_presence = True
                        elif 'end' in speech_event:
                            self.is_vad_speaking = False
                if (
                    mark_audio_presence
                    and config.get("presence_detection", "audio_triggers_presence", default=True)
                ):
                    self.presence_tracker.mark_present("audio")

                if self.sm.check_hot_listen_timeout():
                    log_event(
                        logger,
                        logging.INFO,
                        "state.hot_listen_timeout",
                        timeout_seconds=self.sm.hot_listen_timeout,
                    )
                    self._update_state(State.IDLE_LISTEN)

                triggered_keyword = self.wake_word.detect(chunk, config.get("audio", "input_sample_rate"))

                if self.sm.current_state in [State.SENDING, State.SPEAKING]:
                    if triggered_keyword:
                        suppress_interrupt, request_age = self._should_suppress_wake_word_interrupt()
                        if suppress_interrupt:
                            log_event(
                                logger,
                                logging.DEBUG,
                                "wake_word.interrupt_suppressed",
                                keyword=triggered_keyword,
                                state=self.sm.current_state.name,
                                reason="sending_grace",
                                request_age_seconds=f"{request_age:.3f}",
                            )
                            with self.component_lock:
                                self.sentence_builder.add_chunk(chunk, speech_event)
                            continue
                        log_event(
                            logger,
                            logging.INFO,
                            "wake_word.interrupt_requested",
                            keyword=triggered_keyword,
                            state=self.sm.current_state.name,
                        )
                        self.interrupt(
                            resume_collecting=True,
                            source="wake_word",
                            keyword=triggered_keyword,
                        )
                        with self.component_lock:
                            self.sentence_builder.add_chunk(chunk, speech_event)
                        continue

                if self.sm.current_state == State.IDLE_LISTEN:
                    with self.component_lock:
                        result_audio = self.sentence_builder.add_chunk(chunk, speech_event)
                    if result_audio is not None:
                        last_result_audio = result_audio
                        last_result_time = time.time()

                    if triggered_keyword:
                        reused_buffered_audio = bool(
                            (not self.is_vad_speaking)
                            and last_result_audio is not None
                            and (time.time() - last_result_time) < 1.0
                        )
                        log_event(
                            logger,
                            logging.INFO,
                            "wake_word.detected",
                            keyword=triggered_keyword,
                            reused_buffered_audio=reused_buffered_audio,
                        )
                        if not self.is_vad_speaking and last_result_audio is not None and (time.time() - last_result_time) < 1.0:
                            self._update_state(State.SENDING)
                            self._start_execution_thread(last_result_audio)
                        else:
                            self._mark_collecting_started()
                            self._update_state(State.COLLECTING)
                    elif result_audio is not None:
                        # Drop idle speech that did not include a wake word to bound buffer growth.
                        with self.component_lock:
                            self.sentence_builder.reset()
                        log_event(
                            logger,
                            logging.DEBUG,
                            "idle_listen.speech_ignored",
                            reason="no_wake_word",
                            audio_samples=len(result_audio),
                        )
                        last_result_audio = None
                        last_result_time = 0.0

                elif self.sm.current_state == State.HOT_LISTEN:
                    with self.component_lock:
                        _ = self.sentence_builder.add_chunk(chunk, speech_event)
                    if self.is_vad_speaking and self.sm.get_hot_listen_elapsed() > 0.8:
                        log_event(
                            logger,
                            logging.INFO,
                            "hot_listen.speech_detected",
                            elapsed_seconds=self.sm.get_hot_listen_elapsed(),
                        )
                        self._mark_collecting_started()
                        self._update_state(State.COLLECTING)

                elif self.sm.current_state == State.COLLECTING:
                    with self.component_lock:
                        result_audio = self.sentence_builder.add_chunk(chunk, speech_event)
                    if result_audio is not None:
                        self._collecting_started_at = 0.0
                        self._update_state(State.SENDING)
                        self._start_execution_thread(result_audio)
                        continue

                    command_timeout_seconds = config.get("vad", "command_timeout_seconds")
                    collecting_elapsed = (time.time() - self._collecting_started_at) if self._collecting_started_at else 0.0
                    if self._collecting_started_at and collecting_elapsed > command_timeout_seconds:
                        partial_audio = None
                        with self.component_lock:
                            partial_audio = self.sentence_builder.flush_partial()
                            self.is_vad_speaking = False
                            self.vad.reset_states()
                        log_event(
                            logger,
                            logging.WARNING,
                            "collecting.timeout",
                            elapsed_seconds=collecting_elapsed,
                            timeout_seconds=command_timeout_seconds,
                            flushed_partial_audio=bool(partial_audio is not None and len(partial_audio) > 0),
                            partial_samples=(len(partial_audio) if partial_audio is not None else 0),
                        )
                        self._collecting_started_at = 0.0
                        should_send_partial = self._should_send_timeout_partial(
                            partial_audio,
                            command_timeout_seconds,
                        )
                        if should_send_partial:
                            self._update_state(State.SENDING)
                            self._start_execution_thread(partial_audio)
                        else:
                            self._update_state(State.IDLE_LISTEN)
                        continue
            except Exception:
                logger.exception("語音感知迴圈發生未預期錯誤。")
                continue

    def _start_execution_thread(self, audio_data):
        generation = self._next_voice_execution_generation()
        log_event(
            logger,
            logging.DEBUG,
            "voice.execution_thread_started",
            samples=len(audio_data),
            generation=generation,
        )
        exec_thread = threading.Thread(
            target=self._execution_func,
            args=(audio_data, generation),
            daemon=True
        )
        exec_thread.start()

    def _execution_func(self, audio_data, execution_generation: int | None = None):
        if execution_generation is None:
            execution_generation = self._current_voice_execution_generation()
        utterance_id = self._build_utterance_id()
        sample_rate = config.get("audio", "input_sample_rate") or 16000
        duration_seconds = (len(audio_data) / float(sample_rate)) if len(audio_data) else 0.0
        log_event(
            logger,
            logging.DEBUG,
            "voice.utterance_started",
            utterance_id=utterance_id,
            samples=len(audio_data),
            duration_seconds=duration_seconds,
            generation=execution_generation,
        )

        archive_record = None
        if self.whisper_audio_archive is not None:
            try:
                archive_record = self.whisper_audio_archive.save(
                    audio_data,
                    utterance_id=utterance_id,
                )
            except Exception as e:
                logger.warning(
                    f"Failed to archive Whisper input audio, utterance_id={utterance_id}: {e}"
                )

        log_event(
            logger,
            logging.DEBUG,
            "whisper.started",
            utterance_id=utterance_id,
        )
        text = self.transcriber.transcribe(audio_data)
        log_event(
            logger,
            logging.INFO,
            "whisper.completed",
            utterance_id=utterance_id,
            transcript_chars=len(text),
            transcript_empty=not bool(text),
        )
        if text:
            log_event(
                logger,
                logging.DEBUG,
                "whisper.transcript",
                utterance_id=utterance_id,
                transcript=text,
            )

        if not self._should_continue_voice_execution(
            execution_generation,
            utterance_id=utterance_id,
            stage="after_whisper",
        ):
            if archive_record is not None:
                try:
                    self.whisper_audio_archive.write_transcript_sidecar(
                        archive_record,
                        transcript=text,
                        speaker_name=None,
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to write Whisper archive sidecar, utterance_id={utterance_id}: {e}"
                    )
            return

        speaker_name = None
        if self.speaker_recognizer is not None and self.sm.current_state == State.SENDING:
            try:
                log_event(
                    logger,
                    logging.DEBUG,
                    "speaker_recognition.started",
                    utterance_id=utterance_id,
                )
                speaker_name = self.speaker_recognizer.identify(
                    audio_data,
                    utterance_id=utterance_id,
                )
                if speaker_name:
                    log_event(
                        logger,
                        logging.INFO,
                        "speaker_recognition.matched",
                        utterance_id=utterance_id,
                        speaker=speaker_name,
                    )
            except Exception as e:
                logger.warning(
                    f"Speaker recognition failed, utterance_id={utterance_id}: {e}"
                )
        elif self.sm.current_state == State.SENDING:
            logger.debug(
                f"Speaker recognition skipped, utterance_id={utterance_id}, "
                "reason=disabled_or_unavailable"
            )

        if archive_record is not None:
            try:
                self.whisper_audio_archive.write_transcript_sidecar(
                    archive_record,
                    transcript=text,
                    speaker_name=speaker_name,
                )
            except Exception as e:
                logger.warning(
                    f"Failed to write Whisper archive sidecar, utterance_id={utterance_id}: {e}"
                )

        if self._should_continue_voice_execution(
            execution_generation,
            utterance_id=utterance_id,
            stage="before_llm",
        ):
            if text:
                self.on_message("user", text, speaker_name=speaker_name or "未知")
                self._mark_user_interaction()
                if self._should_retry_transcript_locally(text):
                    self._consume_pending_interrupt_notice()
                    log_event(
                        logger,
                        logging.INFO,
                        "llm.request_skipped",
                        mode="voice",
                        request_id=utterance_id,
                        reason="noisy_transcript",
                    )
                    self.on_message("assistant", _NOISY_TRANSCRIPT_RETRY_MESSAGE, update_existing=False)
                    self._submit_coroutine(self._speak_standalone_message_async(_NOISY_TRANSCRIPT_RETRY_MESSAGE, target_state=State.IDLE_LISTEN))
                    return

                if self._should_skip_llm_request(mode="voice", request_id=utterance_id):
                    return

                self._clear_interrupt_signal()
                self.audio_player.reset_interrupt()
                self.chunker.reset()

                try:
                    llm_client = self.llm_client
                    interrupt_notice = self._consume_pending_interrupt_notice()
                    llm_text = self._build_llm_text(
                        text,
                        speaker_name,
                        interrupt_notice=interrupt_notice,
                    )
                    if speaker_name:
                        log_event(
                            logger,
                            logging.DEBUG,
                            "llm.prompt_enriched",
                            utterance_id=utterance_id,
                            speaker=speaker_name,
                        )
                    if interrupt_notice:
                        log_event(
                            logger,
                            logging.DEBUG,
                            "llm.interrupt_notice_applied",
                            utterance_id=utterance_id,
                        )
                    self._submit_request(
                        self._execute_llm_request(
                            llm_text,
                            llm_client=llm_client,
                            request_id=utterance_id,
                            speaker_name=speaker_name,
                        ),
                        llm_client,
                    )
                except Exception as e:
                    logger.error(f"無法啟動 LLM 請求：{e}")
                    self._clear_request()
                    self._update_state(State.IDLE_LISTEN)
            else:
                self._consume_pending_interrupt_notice()
                log_event(
                    logger,
                    logging.INFO,
                    "whisper.empty_transcript",
                    utterance_id=utterance_id,
                    duration_seconds=duration_seconds,
                )
                self._update_state(State.IDLE_LISTEN)

    async def _execute_llm_request(
        self,
        text,
        llm_client=None,
        request_id: str | None = None,
        speaker_name: str | None = None,
    ):
        llm_client = llm_client or self.llm_client
        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M（%A）")
        prompt_with_hint = self._build_llm_prompt(text, current_time=current_time)
        log_llm_io(
            "llm_input",
            prompt_with_hint,
            actor=speaker_name or "使用者",
            mode="voice",
            request_id=request_id,
            speaker=speaker_name,
        )

        sentence_queue = asyncio.Queue()
        worker_task = asyncio.create_task(self._tts_worker(sentence_queue))

        full_response = ""
        pending_response_whitespace = ""
        completed_normally = False
        first_token_received = False
        stream_activity_count = 0
        last_stream_activity_at = 0.0
        allow_hot_listen = False
        interrupted = False
        failure_reason = None
        should_refresh_session = False
        timeout_notice = None
        empty_response_notice = None
        backend_error_notice = None
        try:
            log_event(logger, logging.INFO, "llm.request_started", mode="voice", request_id=request_id)
            first_token_received = False
            gen = llm_client.send_message(prompt_with_hint)

            while True:
                timeout_stage, timeout = self._next_llm_stream_timeout(first_token_received)
                try:
                    chunk = await asyncio.wait_for(gen.__anext__(), timeout=timeout)
                except StopAsyncIteration:
                    completed_normally = True
                    break
                except asyncio.TimeoutError:
                    await llm_client.cancel()
                    failure_reason = f"timeout:{timeout_stage}"
                    should_refresh_session = True
                    log_event(
                        logger,
                        logging.ERROR,
                        "llm.timeout",
                        mode="voice",
                        request_id=request_id,
                        stage=timeout_stage,
                        timeout_seconds=timeout,
                        response_chars=len(full_response),
                        stream_activity_count=stream_activity_count,
                        seconds_since_stream_activity=(
                            f"{time.monotonic() - last_stream_activity_at:.3f}"
                            if last_stream_activity_at
                            else None
                        ),
                    )
                    timeout_notice = (
                        _LLM_PARTIAL_RESPONSE_TIMEOUT_MESSAGE
                        if full_response
                        else _LLM_TIMEOUT_MESSAGE
                    )
                    break

                if self._is_stream_activity_keepalive(chunk):
                    stream_activity_count += 1
                    last_stream_activity_at = time.monotonic()
                    if not first_token_received:
                        log_event(
                            logger,
                            logging.DEBUG,
                            "llm.stream_activity_before_first_token",
                            mode="voice",
                            request_id=request_id,
                            stream_activity_count=stream_activity_count,
                        )
                    if self.sm.current_state not in (State.SENDING, State.SPEAKING) or self.interrupt_signal.is_set():
                        interrupted = True
                        await llm_client.cancel()
                        break
                    continue

                chunk, pending_response_whitespace = self._normalize_response_chunk(
                    full_response,
                    pending_response_whitespace,
                    chunk,
                )
                if not chunk:
                    continue

                if not first_token_received:
                    first_token_received = True
                    self._mark_active_request_first_token_received()
                    log_event(logger, logging.DEBUG, "llm.first_token_received", mode="voice", request_id=request_id)

                if self.sm.current_state not in (State.SENDING, State.SPEAKING) or self.interrupt_signal.is_set():
                    interrupted = True
                    await llm_client.cancel()
                    break

                candidate_response = full_response + chunk
                backend_error_reason = self._classify_backend_error_response(candidate_response)
                if backend_error_reason:
                    full_response = candidate_response
                    failure_reason = f"backend_error_output:{backend_error_reason}"
                    should_refresh_session = True
                    backend_error_notice = _LLM_BACKEND_ERROR_MESSAGE
                    log_event(
                        logger,
                        logging.ERROR,
                        "llm.backend_error_output",
                        mode="voice",
                        request_id=request_id,
                        reason=backend_error_reason,
                        response_head=full_response[:200],
                    )
                    break

                full_response += chunk
                self.on_message("assistant", full_response)
                for sentence in self.chunker.add_token(chunk):
                    if self.interrupt_signal.is_set():
                        break
                    if self.sm.current_state == State.SENDING:
                        log_event(logger, logging.DEBUG, "llm.first_sentence_ready", mode="voice", request_id=request_id)
                        self._update_state(State.SPEAKING)
                    await sentence_queue.put(sentence)

            if (
                completed_normally
                and not full_response
                and (
                    self.sm.current_state not in (State.SENDING, State.SPEAKING)
                    or self.interrupt_signal.is_set()
                )
            ):
                interrupted = True

            if completed_normally and full_response and not failure_reason:
                log_event(
                    logger,
                    logging.INFO,
                    "llm.completed",
                    mode="voice",
                    request_id=request_id,
                    response_chars=len(full_response),
                    completion_reason="completed",
                )
            elif completed_normally and not interrupted and not failure_reason:
                failure_reason = "empty_response"
                should_refresh_session = True
                empty_response_notice = _LLM_EMPTY_RESPONSE_MESSAGE
                self.on_message("assistant", _LLM_EMPTY_RESPONSE_MESSAGE, update_existing=False)

            if self.sm.current_state in [State.SENDING, State.SPEAKING] and not self.interrupt_signal.is_set():
                flushed_sentences = list(self.chunker.flush())
                if (
                    flushed_sentences
                    or timeout_notice
                    or empty_response_notice
                    or backend_error_notice
                ) and self.sm.current_state == State.SENDING:
                    log_event(logger, logging.DEBUG, "llm.flush_promoted_to_speaking", mode="voice", request_id=request_id)
                    self._update_state(State.SPEAKING)
                for sentence in flushed_sentences:
                    await sentence_queue.put(sentence)
                if timeout_notice:
                    await sentence_queue.put(timeout_notice)
                    if full_response:
                        self.on_message("assistant", full_response + "\n\n" + timeout_notice)
                    else:
                        self.on_message("assistant", timeout_notice, update_existing=False)
                elif empty_response_notice:
                    await sentence_queue.put(empty_response_notice)
                elif backend_error_notice:
                    await sentence_queue.put(backend_error_notice)
                    self.on_message("assistant", backend_error_notice, update_existing=False)
                elif full_response and not failure_reason:
                    self.on_message("assistant", full_response)

            await sentence_queue.put(None)
            await worker_task

            while self.audio_player.is_playing and not self.interrupt_signal.is_set():
                await asyncio.sleep(0.1)
            if completed_normally and full_response and not interrupted and not failure_reason:
                self._mark_session_activity()
            allow_hot_listen = self._hot_listen_enabled() and not self.interrupt_signal.is_set()

        except asyncio.CancelledError:
            worker_task.cancel()
            raise
        except Exception as exc:
            failure_reason = f"exception:{type(exc).__name__}"
            should_refresh_session = True
            logger.exception("LLM/TTS 錯誤。")
            error_msg = "抱歉，系統運作發生錯誤，請稍後再試。"
            if not worker_task.done():
                if self.sm.current_state == State.SENDING:
                    self._update_state(State.SPEAKING)
                await sentence_queue.put(error_msg)
                await sentence_queue.put(None)
                await worker_task
                while self.audio_player.is_playing and not self.interrupt_signal.is_set():
                    await asyncio.sleep(0.1)

            if full_response:
                self.on_message("assistant", full_response + "\n\n" + error_msg)
            else:
                self.on_message("assistant", error_msg, update_existing=False)
            self._update_state(State.IDLE_LISTEN)
        finally:
            response_status = (
                "interrupted"
                if interrupted
                else failure_reason or ("completed" if completed_normally else "cancelled")
            )
            log_llm_io(
                "llm_output",
                full_response,
                actor="LLM",
                mode="voice",
                request_id=request_id,
                status=response_status,
            )
            if interrupted:
                log_event(logger, logging.INFO, "llm.request_interrupted", mode="voice", request_id=request_id)
            elif failure_reason:
                self._record_llm_failure(mode="voice", reason=failure_reason, request_id=request_id)
                if should_refresh_session:
                    try:
                        await self._refresh_session_async()
                    except Exception:
                        logger.exception("Failed to refresh LLM session after voice request failure.")
            elif completed_normally and full_response and not failure_reason:
                self._record_llm_success()
            if allow_hot_listen and self.sm.current_state == State.SPEAKING:
                self._update_state(State.HOT_LISTEN)
            elif self.sm.current_state in (State.SENDING, State.SPEAKING):
                self._update_state(State.IDLE_LISTEN)

            if self.interrupt_signal.is_set():
                worker_task.cancel()

    async def _tts_worker(self, q: asyncio.Queue):
        while True:
            try:
                sentence = await q.get()
                if sentence is None:
                    q.task_done()
                    break
                if not self.interrupt_signal.is_set():
                    await self.tts_engine.speak_stream(sentence, self.audio_player, self.interrupt_signal)
                q.task_done()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("TTS Worker 錯誤。")
                # Prevent queue.join() from deadlocking after a worker error.
                try:
                    q.task_done()
                except Exception:
                    pass

    def change_backend(self, backend_name):
        """Switch the active LLM backend."""
        self.last_backend_switch_error = ""
        if not self.can_change_backend():
            logger.warning(f"略過後端切換，系統忙碌中：{backend_name}")
            self.last_backend_switch_error = "系統忙碌中，請等目前回覆完成後再切換 LLM 後端。"
            return False
        backend_config = config.get("llm", backend_name, default={}) or {}
        new_client = create_llm_client(backend_name, **backend_config)
        old_client = self.llm_client
        try:
            self._ensure_llm_client_ready_blocking(new_client)
        except Exception as exc:
            self.last_backend_switch_error = str(exc)
            log_event(
                logger,
                logging.WARNING,
                "llm.backend_switch_ready_failed",
                backend=backend_name,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            self._close_llm_client(new_client)
            return False
        self.llm_client = new_client
        config.set("llm", "active_backend", value=backend_name)
        self._close_llm_client(old_client)
        logger.info(f"LLM 後端切換至：{backend_name}")
        return True

    def set_voice_enabled(self, enabled: bool):
        """Enable or pause microphone-driven voice input."""
        previous_state = self.sm.current_state
        was_voice_paused = self.voice_paused
        self.voice_paused = not enabled
        mode = "語音" if enabled else "文字"
        logger.info(f"輸入模式切換至：{mode}模式")

        if enabled:
            if previous_state == State.COLLECTING:
                self._update_state(State.IDLE_LISTEN)
            elif was_voice_paused and previous_state in (State.SENDING, State.SPEAKING):
                self.interrupt()
            return

        if self.user_activity_prompt_active or previous_state != State.IDLE_LISTEN:
            self.interrupt()

    def on_user_activity(self, source: str) -> bool:
        """Handle global input activity and optionally enter hot listen."""
        if config.get("presence_detection", "input_triggers_presence", default=True):
            self.presence_tracker.mark_present(source)
        if self.voice_paused:
            return False
        if not self._hot_listen_enabled():
            return False
        if not config.get("user_activity_prompt", "enabled", default=True):
            return False
        if self.async_loop is None:
            return False
        if self.sm.current_state != State.IDLE_LISTEN:
            return False

        with self.activity_prompt_lock:
            if self.user_activity_prompt_active:
                return False
            if self.sm.current_state != State.IDLE_LISTEN:
                return False
            self.user_activity_prompt_active = True

        prompt_text = config.get(
            "user_activity_prompt",
            "text",
            default="請問有甚麼事嗎？",
        )
        logger.info(f"User activity detected from {source}, prompting hot listen.")
        try:
            self._submit_coroutine(self._speak_prompt_and_enter_hot_listen(prompt_text))
        except Exception:
            with self.activity_prompt_lock:
                self.user_activity_prompt_active = False
            raise
        return True

    def _build_heartbeat_prompt(self) -> str:
        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M（%A）")
        presence_status = self.presence_tracker.get_status_text()
        interval_text = self._format_heartbeat_interval_text(
            self._resolve_heartbeat_interval_seconds()
        )
        sections = [
            self._format_system_hint(f"這是{interval_text}的定期巡檢，不是使用者主動發起的對話"),
            self._format_system_hint(f"目前時間：{current_time}"),
            self._format_system_hint(f"附近偵測狀態：{presence_status}"),
            self._format_system_hint(
                "若附近可能無人，除非有安全或緊急事項需要立刻通知現場，"
                f"請不要發聲提醒；請回覆「{_HEARTBEAT_NOP_TAG}」或「{_HEARTBEAT_SILENT_TAG}」加簡短紀錄。"
            ),
            self._format_system_hint(
                "請檢查是否有需要處理的事項。回覆規則："
                f"若無事可做，只回覆「{_HEARTBEAT_NOP_TAG}」。"
                f"若有事要做但不需發聲提醒，執行完工具後回覆「{_HEARTBEAT_SILENT_TAG}」加簡短紀錄。"
                "若需要對現場的人發聲提醒，直接用自然口語回覆要說的話，請控制在兩三句話以內。"
            ),
        ]
        sections.append(
            self._format_system_hint(
                "Heartbeat checks must be read-only. Do not run shell commands, tests, "
                "or tools that modify files. Use only existing context; if there is no "
                f"explicit scheduled task, reply exactly {_HEARTBEAT_NOP_TAG}."
            )
        )
        return "\n".join(section for section in sections if section)

    @staticmethod
    def _parse_heartbeat_response(response: str) -> tuple[str, str]:
        stripped = (response or "").strip()
        if _HEARTBEAT_NOP_TAG in stripped:
            return "nop", ""
        if _HEARTBEAT_SILENT_TAG in stripped:
            return "silent", ""
        spoken = (
            stripped.replace(_HEARTBEAT_NOP_TAG, "")
            .replace(_HEARTBEAT_SILENT_TAG, "")
            .strip()
        )
        if not spoken:
            return "nop", ""
        if len(spoken) > _HEARTBEAT_SPEAK_MAX_CHARS:
            spoken = spoken[: _HEARTBEAT_SPEAK_MAX_CHARS - 1].rstrip() + "…"
        return "speak", spoken

    async def _wait_for_heartbeat_chunk(self, gen, cancel_event, timeout: float):
        anext_task = asyncio.create_task(gen.__anext__())
        cancel_task = (
            asyncio.create_task(cancel_event.wait())
            if cancel_event is not None
            else None
        )
        tasks = [anext_task]
        if cancel_task is not None:
            tasks.append(cancel_task)

        try:
            done, _ = await asyncio.wait(
                tasks,
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if cancel_task is not None and cancel_task in done:
                anext_task.cancel()
                try:
                    await anext_task
                except (asyncio.CancelledError, StopAsyncIteration):
                    pass
                raise asyncio.CancelledError

            if anext_task in done:
                return anext_task.result()

            anext_task.cancel()
            try:
                await anext_task
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            raise asyncio.TimeoutError
        finally:
            if cancel_task is not None and not cancel_task.done():
                cancel_task.cancel()
                try:
                    await cancel_task
                except asyncio.CancelledError:
                    pass

    async def _close_async_generator(self, gen, *, event_name: str, heartbeat_id: str):
        if gen is None:
            return
        try:
            await gen.aclose()
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                event_name,
                heartbeat_id=heartbeat_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )

    async def _on_heartbeat_fire(self):
        heartbeat_id = self._build_utterance_id()

        if not self.running:
            return
        if not self._heartbeat_enabled():
            return
        if not self._heartbeat_within_active_window():
            if not self._heartbeat_off_hours_logged:
                # Log the first off-hours skip only; later ticks remain quiet.
                log_event(
                    logger,
                    logging.DEBUG,
                    "heartbeat.skipped",
                    heartbeat_id=heartbeat_id,
                    reason="outside_active_hours",
                    active_hours=f"{_HEARTBEAT_ACTIVE_START_HOUR:02d}:00-{_HEARTBEAT_ACTIVE_END_HOUR:02d}:00",
                )
                self._heartbeat_off_hours_logged = True
            return
        # Reset once active hours resume so the next off-hours skip is logged.
        self._heartbeat_off_hours_logged = False
        if self.sm.current_state != State.IDLE_LISTEN:
            log_event(
                logger,
                logging.DEBUG,
                "heartbeat.skipped",
                heartbeat_id=heartbeat_id,
                reason="not_idle",
                state=self.sm.current_state.name,
            )
            return
        with self.request_lock:
            if self._has_active_request():
                log_event(
                    logger,
                    logging.DEBUG,
                    "heartbeat.skipped",
                    heartbeat_id=heartbeat_id,
                    reason="active_request",
                )
                return
        if self.user_activity_prompt_active:
            log_event(
                logger,
                logging.DEBUG,
                "heartbeat.skipped",
                heartbeat_id=heartbeat_id,
                reason="activity_prompt_active",
            )
            return

        is_open, retry_after, _ = self._get_llm_circuit_status()
        if is_open:
            log_event(
                logger,
                logging.DEBUG,
                "heartbeat.skipped",
                heartbeat_id=heartbeat_id,
                reason="circuit_open",
                retry_after_seconds=f"{retry_after:.1f}",
            )
            return

        self._heartbeat_active = True
        self._heartbeat_cancel_event = asyncio.Event()
        log_event(logger, logging.INFO, "heartbeat.tick_started", heartbeat_id=heartbeat_id)

        try:
            await self._execute_heartbeat_request(heartbeat_id)
        except asyncio.CancelledError:
            log_event(logger, logging.INFO, "heartbeat.cancelled", heartbeat_id=heartbeat_id)
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "heartbeat.failed",
                heartbeat_id=heartbeat_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
        finally:
            self._heartbeat_active = False
            self._heartbeat_cancel_event = None
            log_event(logger, logging.INFO, "heartbeat.ended", heartbeat_id=heartbeat_id)

    async def _execute_heartbeat_request(self, heartbeat_id: str):
        prompt = self._build_heartbeat_prompt()
        log_llm_io(
            "llm_input",
            prompt,
            actor="Heartbeat",
            mode="heartbeat",
            request_id=heartbeat_id,
        )

        llm_client = self.llm_client
        full_response = ""
        completed_normally = False
        cancel_event = self._heartbeat_cancel_event
        gen = None
        failure_reason = None
        stream_activity_count = 0
        last_stream_activity_at = 0.0

        try:
            gen = llm_client.send_message(prompt)
            first_token_received = False

            while True:
                if cancel_event is not None and cancel_event.is_set():
                    await llm_client.cancel()
                    log_event(
                        logger,
                        logging.INFO,
                        "heartbeat.preempted",
                        heartbeat_id=heartbeat_id,
                        reason="cancel_requested",
                    )
                    self._reset_heartbeat_nop_streak()
                    return
                if self.sm.current_state != State.IDLE_LISTEN:
                    await llm_client.cancel()
                    log_event(
                        logger,
                        logging.INFO,
                        "heartbeat.preempted",
                        heartbeat_id=heartbeat_id,
                        reason="state_changed",
                        state=self.sm.current_state.name,
                    )
                    self._reset_heartbeat_nop_streak()
                    return

                timeout_stage, timeout = self._next_llm_stream_timeout(first_token_received)
                try:
                    chunk = await self._wait_for_heartbeat_chunk(gen, cancel_event, timeout)
                except StopAsyncIteration:
                    completed_normally = True
                    break
                except asyncio.CancelledError:
                    await llm_client.cancel()
                    log_event(
                        logger,
                        logging.INFO,
                        "heartbeat.preempted",
                        heartbeat_id=heartbeat_id,
                        reason="cancel_requested",
                    )
                    self._reset_heartbeat_nop_streak()
                    return
                except asyncio.TimeoutError:
                    await llm_client.cancel()
                    failure_reason = f"timeout:{timeout_stage}"
                    log_event(
                        logger,
                        logging.WARNING,
                        "heartbeat.timeout",
                        heartbeat_id=heartbeat_id,
                        stage=timeout_stage,
                        timeout_seconds=timeout,
                        response_chars=len(full_response),
                        stream_activity_count=stream_activity_count,
                        seconds_since_stream_activity=(
                            f"{time.monotonic() - last_stream_activity_at:.3f}"
                            if last_stream_activity_at
                            else None
                        ),
                    )
                    self._record_llm_failure(
                        mode="heartbeat",
                        reason=failure_reason,
                        request_id=heartbeat_id,
                    )
                    self._reset_heartbeat_nop_streak()
                    return

                if self._is_stream_activity_keepalive(chunk):
                    stream_activity_count += 1
                    last_stream_activity_at = time.monotonic()
                    continue

                if not first_token_received:
                    first_token_received = True
                candidate_response = full_response + chunk
                backend_error_reason = self._classify_backend_error_response(candidate_response)
                if backend_error_reason:
                    full_response = candidate_response
                    failure_reason = f"backend_error_output:{backend_error_reason}"
                    self._record_llm_failure(
                        mode="heartbeat",
                        reason=failure_reason,
                        request_id=heartbeat_id,
                    )
                    log_event(
                        logger,
                        logging.ERROR,
                        "heartbeat.backend_error_output",
                        heartbeat_id=heartbeat_id,
                        reason=backend_error_reason,
                        response_head=full_response[:200],
                    )
                    self._reset_heartbeat_nop_streak()
                    return
                full_response = candidate_response

        except asyncio.CancelledError:
            try:
                await llm_client.cancel()
            except Exception:
                pass
            self._reset_heartbeat_nop_streak()
            raise
        except Exception as exc:
            failure_reason = f"exception:{type(exc).__name__}"
            self._record_llm_failure(
                mode="heartbeat",
                reason=failure_reason,
                request_id=heartbeat_id,
            )
            log_event(
                logger,
                logging.ERROR,
                "heartbeat.request_failed",
                heartbeat_id=heartbeat_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            self._reset_heartbeat_nop_streak()
            return
        finally:
            await self._close_async_generator(
                gen,
                event_name="heartbeat.generator_close_failed",
                heartbeat_id=heartbeat_id,
            )
            status = "completed" if completed_normally else (failure_reason or "incomplete")
            log_llm_io(
                "llm_output",
                full_response,
                actor="LLM",
                mode="heartbeat",
                request_id=heartbeat_id,
                status=status,
            )

        if not completed_normally or not full_response.strip():
            self._reset_heartbeat_nop_streak()
            if completed_normally:
                log_event(
                    logger,
                    logging.INFO,
                    "heartbeat.empty_response",
                    heartbeat_id=heartbeat_id,
                )
            return

        self._record_llm_success()
        action, spoken_text = self._parse_heartbeat_response(full_response)
        log_event(
            logger,
            logging.INFO,
            "heartbeat.response_parsed",
            heartbeat_id=heartbeat_id,
            action=action,
            spoken_chars=len(spoken_text),
        )

        if action == "nop":
            await self._handle_heartbeat_nop(heartbeat_id)
            return
        self._reset_heartbeat_nop_streak()
        if action == "silent":
            log_event(logger, logging.INFO, "heartbeat.silent", heartbeat_id=heartbeat_id)
            return

        now = time.time()
        seconds_since_last = now - self._last_heartbeat_speak_time
        if seconds_since_last < _HEARTBEAT_SPEAK_MIN_INTERVAL:
            log_event(
                logger,
                logging.INFO,
                "heartbeat.speak_throttled",
                heartbeat_id=heartbeat_id,
                seconds_since_last=f"{seconds_since_last:.0f}",
            )
            return

        if self.sm.current_state != State.IDLE_LISTEN:
            log_event(
                logger,
                logging.INFO,
                "heartbeat.speak_downgraded",
                heartbeat_id=heartbeat_id,
                reason="state_changed",
                state=self.sm.current_state.name,
            )
            return

        self.on_message("assistant", spoken_text, update_existing=False)

        if self.voice_paused:
            self._last_heartbeat_speak_time = now
            log_event(
                logger,
                logging.INFO,
                "heartbeat.speak_text_only",
                heartbeat_id=heartbeat_id,
            )
            return

        if not self.presence_tracker.is_present():
            self._last_heartbeat_speak_time = now
            log_event(
                logger,
                logging.INFO,
                "heartbeat.speak_downgraded_to_ui",
                heartbeat_id=heartbeat_id,
                reason="no_presence",
            )
            return

        self._clear_interrupt_signal()
        self.audio_player.reset_interrupt()
        await self._speak_standalone_message_async(
            spoken_text,
            target_state=State.HOT_LISTEN,
        )
        if self.sm.current_state == State.HOT_LISTEN:
            self._last_heartbeat_speak_time = now
            log_event(
                logger,
                logging.INFO,
                "heartbeat.spoke",
                heartbeat_id=heartbeat_id,
                spoken_chars=len(spoken_text),
            )

    def is_human_present(self) -> bool:
        return self.presence_tracker.is_present()

    def update_vad_min_silence(self, min_silence_duration_ms: int):
        with self.component_lock:
            self.vad.update_min_silence_duration(min_silence_duration_ms)
            self.is_vad_speaking = False
            self.sentence_builder.reset(clear_pre_roll=True)

    def update_tts_settings(self, *, voice: str | None = None, rate: str | None = None, volume: str | None = None):
        self.tts_engine.update_settings(voice=voice, rate=rate, volume=volume)

    def begin_manual_capture(self) -> bool:
        """Start command capture directly from the UI button."""
        if self.voice_paused:
            log_event(logger, logging.INFO, "manual_capture.rejected", reason="voice_paused")
            return False
        if self.user_activity_prompt_active:
            self.interrupt()
        if self.sm.current_state not in (State.IDLE_LISTEN, State.HOT_LISTEN):
            log_event(
                logger,
                logging.INFO,
                "manual_capture.rejected",
                reason="invalid_state",
                state=self.sm.current_state.name,
            )
            return False
        with self.component_lock:
            self.is_vad_speaking = False
            self.sentence_builder.reset(clear_pre_roll=True)
            self.vad.reset_states()
        self._mark_collecting_started()
        log_event(
            logger,
            logging.INFO,
            "manual_capture.started",
            previous_state=self.sm.current_state.name,
        )
        self._update_state(State.COLLECTING)
        return True

    async def _speak_prompt_and_enter_hot_listen(self, text: str):
        interrupted = False
        try:
            if self.sm.current_state != State.IDLE_LISTEN:
                return
            if self.user_activity_interrupt_signal:
                self.user_activity_interrupt_signal.clear()

            self.on_message("assistant", text, update_existing=False)
            self.audio_player.reset_interrupt()
            await self.tts_engine.speak_stream(
                text,
                self.audio_player,
                self.user_activity_interrupt_signal,
            )

            while (
                self.audio_player.is_playing
                and self.user_activity_interrupt_signal
                and not self.user_activity_interrupt_signal.is_set()
            ):
                await asyncio.sleep(0.05)

            interrupted = bool(
                self.user_activity_interrupt_signal
                and self.user_activity_interrupt_signal.is_set()
            )
            if (
                not interrupted
                and self.sm.current_state == State.IDLE_LISTEN
                and self._hot_listen_enabled()
            ):
                self._update_state(State.HOT_LISTEN)
        except Exception as e:
            logger.error(f"User activity prompt failed: {e}")
        finally:
            with self.activity_prompt_lock:
                self.user_activity_prompt_active = False
            if self.user_activity_interrupt_signal and interrupted:
                self.user_activity_interrupt_signal.clear()

    async def _speak_standalone_message_async(self, text: str, target_state: State = State.IDLE_LISTEN):
        """Speak a standalone alert and then restore the target state."""
        interrupted = False
        try:
            self._update_state(State.SPEAKING)
            self._clear_interrupt_signal()
            self.audio_player.reset_interrupt()
            await self.tts_engine.speak_stream(text, self.audio_player, self.interrupt_signal)
            while self.audio_player.is_playing and (not self.interrupt_signal or not self.interrupt_signal.is_set()):
                await asyncio.sleep(0.05)
            interrupted = bool(self.interrupt_signal and self.interrupt_signal.is_set())
        except Exception as e:
            logger.warning(f"Standalone alert failed: {e}")
        finally:
            if not interrupted:
                self._update_state(target_state)

    def send_text_message(self, text: str):
        """Start a text-mode LLM request from the UI."""
        if not text.strip():
            log_event(logger, logging.INFO, "llm.request_rejected", mode="text", reason="empty")
            return False, "empty"
        if not self.async_loop:
            log_event(logger, logging.WARNING, "llm.request_rejected", mode="text", reason="loop_unavailable")
            return False, "unavailable"
        if not self.can_accept_text_message():
            log_event(logger, logging.INFO, "llm.request_rejected", mode="text", reason="busy")
            return False, "busy"
        request_id = self._build_utterance_id()
        log_event(
            logger,
            logging.INFO,
            "llm.request_started",
            mode="text",
            request_id=request_id,
            prompt_chars=len(text),
        )
        log_event(
            logger,
            logging.DEBUG,
            "llm.prompt_text",
            mode="text",
            request_id=request_id,
            prompt=text,
        )
        self._mark_user_interaction()
        llm_client = self.llm_client
        if self._should_skip_llm_request(mode="text", request_id=request_id):
            return True, None
        self._clear_interrupt_signal()
        self._submit_request(
            self._execute_text_llm_request(text, llm_client=llm_client, request_id=request_id),
            llm_client,
        )
        return True, None

    async def _execute_text_llm_request(self, text: str, llm_client=None, request_id: str | None = None):
        """Stream a text-mode LLM response to the UI without TTS."""
        llm_client = llm_client or self.llm_client
        self._update_state(State.SENDING)

        self.audio_player.interrupt()
        self.audio_player.reset_interrupt()
        interrupt_notice = self._consume_pending_interrupt_notice()
        llm_text = self._build_llm_text(
            text,
            speaker_name=None,
            interrupt_notice=interrupt_notice,
        )

        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M（%A）")
        prompt = self._build_llm_prompt(llm_text, current_time=current_time)
        log_llm_io(
            "llm_input",
            prompt,
            actor="使用者",
            mode="text",
            request_id=request_id,
        )
        if interrupt_notice:
            log_event(
                logger,
                logging.DEBUG,
                "llm.interrupt_notice_applied",
                request_id=request_id,
                mode="text",
            )

        full_response = ""
        pending_response_whitespace = ""
        completed_normally = False
        failure_reason = None
        should_refresh_session = False
        try:
            self.chunker.reset()
            gen = llm_client.send_message(prompt)

            while True:
                if self.interrupt_signal and self.interrupt_signal.is_set():
                    log_event(logger, logging.INFO, "llm.request_interrupted", mode="text", request_id=request_id)
                    await llm_client.cancel()
                    break

                timeout_stage, timeout = self._next_llm_stream_timeout(bool(full_response))
                try:
                    chunk = await asyncio.wait_for(gen.__anext__(), timeout=timeout)
                except StopAsyncIteration:
                    completed_normally = True
                    break
                except asyncio.TimeoutError:
                    await llm_client.cancel()
                    failure_reason = f"timeout:{timeout_stage}"
                    should_refresh_session = True
                    log_event(
                        logger,
                        logging.ERROR,
                        "llm.timeout",
                        mode="text",
                        request_id=request_id,
                        stage=timeout_stage,
                        timeout_seconds=timeout,
                        response_chars=len(full_response),
                    )
                    self.on_message("assistant", full_response + "\n\n⚠️ 連線逾時，請再試一次。")
                    return

                if self._is_stream_activity_keepalive(chunk):
                    continue

                chunk, pending_response_whitespace = self._normalize_response_chunk(
                    full_response,
                    pending_response_whitespace,
                    chunk,
                )
                if not chunk:
                    continue

                candidate_response = full_response + chunk
                backend_error_reason = self._classify_backend_error_response(candidate_response)
                if backend_error_reason:
                    full_response = candidate_response
                    failure_reason = f"backend_error_output:{backend_error_reason}"
                    should_refresh_session = True
                    log_event(
                        logger,
                        logging.ERROR,
                        "llm.backend_error_output",
                        mode="text",
                        request_id=request_id,
                        reason=backend_error_reason,
                        response_head=full_response[:200],
                    )
                    self.on_message("assistant", _LLM_BACKEND_ERROR_MESSAGE)
                    break

                full_response = candidate_response
                self.on_message("assistant", full_response)

        except asyncio.CancelledError:
            try:
                await llm_client.cancel()
            except Exception:
                pass
            raise
        except Exception as e:
            failure_reason = f"exception:{type(e).__name__}"
            should_refresh_session = True
            logger.error(f"[文字輸入] LLM 錯誤：{e}")
            if not full_response:
                self.on_message("assistant", "⚠️ 發生錯誤，請稍後再試。")
        finally:
            self.chunker.reset()
            response_status = failure_reason or ("completed" if completed_normally else "interrupted")
            log_llm_io(
                "llm_output",
                full_response,
                actor="LLM",
                mode="text",
                request_id=request_id,
                status=response_status,
            )
            if completed_normally and full_response and not failure_reason:
                log_event(
                    logger,
                    logging.INFO,
                    "llm.completed",
                    mode="text",
                    request_id=request_id,
                    response_chars=len(full_response),
                    completion_reason="completed",
                )
                self._record_llm_success()
                self._mark_session_activity()
            elif completed_normally:
                failure_reason = "empty_response"
                should_refresh_session = True
                self.on_message("assistant", _LLM_EMPTY_RESPONSE_MESSAGE)
            elif failure_reason:
                self._record_llm_failure(mode="text", reason=failure_reason, request_id=request_id)
                if should_refresh_session:
                    try:
                        await self._refresh_session_async()
                    except Exception:
                        logger.exception("Failed to refresh LLM session after text request failure.")
            if full_response:
                log_event(
                    logger,
                    logging.DEBUG,
                    "llm.response_text",
                    mode="text",
                    request_id=request_id,
                    response=full_response,
                )

            self._update_state(State.IDLE_LISTEN)
