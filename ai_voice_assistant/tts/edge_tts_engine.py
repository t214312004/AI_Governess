import asyncio
import io
import logging
import re
from uuid import uuid4

import aiohttp
import av
import edge_tts
import numpy as np

from core.audio_player import PlaybackBoundary, PlaybackChunk, PlaybackChunkMetadata
from tts.rate_limits import normalize_edge_tts_rate
from utils.logger import get_logger, log_event

logger = get_logger(__name__)

_TICKS_PER_SECOND = 10_000_000
_MAX_TTS_RETRIES = 2
_TTS_RETRY_DELAYS_SECONDS = (0.5, 1.5)
_RETRYABLE_TTS_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
_MARKDOWN_HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s*")
_MARKDOWN_HASH_BULLET_RE = re.compile(r"(?m)^\s*#\s+")
_LINE_SPACE_RE = re.compile(r"[ \t]{2,}")


def sanitize_edge_tts_text(
    text: str,
    *,
    remove_all_asterisks: bool = True,
    remove_all_hashes: bool = False,
) -> str:
    """Remove Markdown markers that Edge TTS tends to read aloud."""
    if not text:
        return ""

    sanitized = text

    if remove_all_asterisks:
        sanitized = sanitized.replace("*", "")

    if remove_all_hashes:
        sanitized = sanitized.replace("#", "")
    else:
        sanitized = _MARKDOWN_HEADING_RE.sub("", sanitized)
        sanitized = _MARKDOWN_HASH_BULLET_RE.sub("", sanitized)

    lines = [_LINE_SPACE_RE.sub(" ", line).strip() for line in sanitized.splitlines()]
    return "\n".join(line for line in lines if line).strip()


class EdgeTTSEngine:
    def __init__(
        self,
        voice: str = "zh-TW-HsiaoChenNeural",
        sample_rate: int = 24000,
        rate: str = "+0%",
        volume: str = "+0%",
        sanitize_markdown: bool = True,
        remove_all_asterisks: bool = True,
        remove_all_hashes: bool = False,
    ):
        self.voice = voice
        self.sample_rate = sample_rate
        self.rate = normalize_edge_tts_rate(rate)
        self.volume = volume
        self.sanitize_markdown = sanitize_markdown
        self.remove_all_asterisks = remove_all_asterisks
        self.remove_all_hashes = remove_all_hashes

    def update_settings(
        self,
        *,
        voice: str | None = None,
        rate: str | None = None,
        volume: str | None = None,
    ):
        if voice is not None:
            self.voice = voice
        if rate is not None:
            self.rate = normalize_edge_tts_rate(rate)
        if volume is not None:
            self.volume = volume

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        if isinstance(exc, (ConnectionError, asyncio.TimeoutError, aiohttp.ClientError)):
            status = getattr(exc, "status", None)
            if status is None:
                return True
            return int(status) in _RETRYABLE_TTS_STATUS_CODES
        return False

    @staticmethod
    async def _wait_retry_delay(delay_seconds: float, interrupt_signal: asyncio.Event | None) -> bool:
        if interrupt_signal is None:
            await asyncio.sleep(delay_seconds)
            return False
        try:
            await asyncio.wait_for(interrupt_signal.wait(), timeout=delay_seconds)
            return True
        except asyncio.TimeoutError:
            return False

    async def speak_stream(self, text: str, audio_player, interrupt_signal: asyncio.Event | None = None):
        text = text.strip()
        if self.sanitize_markdown:
            raw_text = text
            text = sanitize_edge_tts_text(
                text,
                remove_all_asterisks=self.remove_all_asterisks,
                remove_all_hashes=self.remove_all_hashes,
            )
            if text != raw_text:
                log_event(
                    logger,
                    logging.DEBUG,
                    "tts.text_sanitized",
                    original_chars=len(raw_text),
                    sanitized_chars=len(text),
                    voice=self.voice,
                )
        if not text:
            return

        log_event(
            logger,
            logging.DEBUG,
            "tts.started",
            text_chars=len(text),
            voice=self.voice,
        )

        attempts = _MAX_TTS_RETRIES + 1
        for attempt in range(1, attempts + 1):
            try:
                communicate = edge_tts.Communicate(
                    text,
                    voice=self.voice,
                    rate=self.rate,
                    volume=self.volume,
                    boundary="WordBoundary",
                )

                mp3_buffer = io.BytesIO()
                word_boundaries: list[dict] = []

                async for chunk in communicate.stream():
                    if interrupt_signal and interrupt_signal.is_set():
                        log_event(logger, logging.DEBUG, "tts.interrupted")
                        return

                    chunk_type = chunk.get("type")
                    if chunk_type == "audio":
                        mp3_buffer.write(chunk["data"])
                    elif chunk_type == "WordBoundary":
                        word_boundaries.append(chunk)

                mp3_data = mp3_buffer.getvalue()
                if not mp3_data:
                    return

                frames = self._try_decode_partial(mp3_data)
                playback_chunks = self._build_playback_chunks(text, frames, word_boundaries)
                for playback_chunk in playback_chunks:
                    if interrupt_signal and interrupt_signal.is_set():
                        return
                    audio_player.play(playback_chunk)
                return

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._is_retryable_error(exc):
                    logger.error(f"TTS Error: {exc}")
                    raise

                if attempt >= attempts:
                    log_event(
                        logger,
                        logging.WARNING,
                        "tts.sentence_failed",
                        text_chars=len(text),
                        attempts=attempt,
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                    return

                delay_seconds = _TTS_RETRY_DELAYS_SECONDS[min(attempt - 1, len(_TTS_RETRY_DELAYS_SECONDS) - 1)]
                log_event(
                    logger,
                    logging.WARNING,
                    "tts.retry_scheduled",
                    text_chars=len(text),
                    attempt=attempt,
                    retry_in_seconds=delay_seconds,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                if await self._wait_retry_delay(delay_seconds, interrupt_signal):
                    log_event(logger, logging.DEBUG, "tts.interrupted")
                    return

    def _build_playback_chunks(
        self,
        text: str,
        frames: list[np.ndarray],
        raw_boundaries: list[dict],
    ) -> list[PlaybackChunk]:
        if not frames:
            return []

        total_samples = sum(len(frame) for frame in frames)
        boundaries = self._build_boundaries(raw_boundaries, total_samples)
        sentence_id = uuid4().hex
        chunk_cursor = 0
        result: list[PlaybackChunk] = []

        for frame in frames:
            metadata = PlaybackChunkMetadata(
                sentence_id=sentence_id,
                sentence_text=text,
                boundaries=boundaries,
                start_sample=chunk_cursor,
                total_samples=total_samples,
            )
            result.append(PlaybackChunk(pcm_data=frame, metadata=metadata))
            chunk_cursor += len(frame)

        return result

    def _build_boundaries(
        self,
        raw_boundaries: list[dict],
        total_samples: int,
    ) -> tuple[PlaybackBoundary, ...]:
        result: list[PlaybackBoundary] = []
        for boundary in raw_boundaries:
            text = (boundary.get("text") or "").strip()
            if not text:
                continue

            offset = float(boundary.get("offset", 0))
            duration = float(boundary.get("duration", 0))
            start_sample = max(0, int(round(offset * self.sample_rate / _TICKS_PER_SECOND)))
            end_sample = max(
                start_sample,
                int(round((offset + duration) * self.sample_rate / _TICKS_PER_SECOND)),
            )
            if total_samples > 0:
                start_sample = min(start_sample, total_samples)
                end_sample = min(end_sample, total_samples)
            result.append(
                PlaybackBoundary(
                    text=text,
                    start_sample=start_sample,
                    end_sample=end_sample,
                )
            )
        return tuple(result)

    def _try_decode_partial(self, mp3_data: bytes) -> list[np.ndarray]:
        if not mp3_data:
            return []
        result: list[np.ndarray] = []
        try:
            buf = io.BytesIO(mp3_data)
            container = av.open(buf, format="mp3")
            for frame in container.decode(audio=0):
                pcm = frame.to_ndarray()
                if pcm.ndim > 1:
                    pcm = pcm[0]
                if pcm.dtype != np.int16:
                    if pcm.dtype in (np.float32, np.float64):
                        pcm = (pcm * 32767).astype(np.int16)
                    else:
                        pcm = pcm.astype(np.int16)  # pragma: no cover
                result.append(pcm)
            container.close()
        except Exception:
            pass  # pragma: no cover
        return result
