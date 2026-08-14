import asyncio
import io
import logging
import re
from uuid import uuid4

import aiohttp
import av
import edge_tts
import numpy as np
from edge_tts.exceptions import NoAudioReceived

from core.audio_player import PlaybackBoundary, PlaybackChunk, PlaybackChunkMetadata
from tts.base import PlaybackChunkCollector, TTSPlaybackResult
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


class _EdgeTTSAudioDecodeError(RuntimeError):
    pass


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

    # 修正 Edge TTS 對「謝謝」發音不自然的問題（如「謝協」），替換為諧音「謝些」
    sanitized = sanitized.replace("謝謝", "謝些")

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
        streaming_decode: bool = False,
        streaming_decode_min_bytes: int = 1440,
    ):
        self.voice = voice
        self.sample_rate = sample_rate
        self.rate = normalize_edge_tts_rate(rate)
        self.volume = volume
        self.sanitize_markdown = sanitize_markdown
        self.remove_all_asterisks = remove_all_asterisks
        self.remove_all_hashes = remove_all_hashes
        self.streaming_decode = bool(streaming_decode)
        self.streaming_decode_min_bytes = max(720, int(streaming_decode_min_bytes))

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
        if isinstance(
            exc,
            (
                ConnectionError,
                asyncio.TimeoutError,
                aiohttp.ClientError,
                NoAudioReceived,
                _EdgeTTSAudioDecodeError,
            ),
        ):
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

    async def synthesize_stream(
        self,
        text: str,
        interrupt_signal: asyncio.Event | None = None,
        *,
        response_generation: int | None = None,
        turn_id: str | None = None,
    ):
        if self.streaming_decode:
            async for chunk in self._synthesize_progressive(
                text,
                interrupt_signal,
                response_generation=response_generation,
                turn_id=turn_id,
            ):
                yield chunk
            return

        collector = PlaybackChunkCollector(
            self.sample_rate,
            response_generation=response_generation,
            turn_id=turn_id,
        )
        await self.speak_stream(text, collector, interrupt_signal)
        for chunk in collector.chunks:
            if interrupt_signal and interrupt_signal.is_set():
                return
            yield chunk

    async def _synthesize_progressive(
        self,
        text: str,
        interrupt_signal: asyncio.Event | None,
        *,
        response_generation: int | None,
        turn_id: str | None,
    ):
        text = (text or "").strip()
        if self.sanitize_markdown:
            text = sanitize_edge_tts_text(
                text,
                remove_all_asterisks=self.remove_all_asterisks,
                remove_all_hashes=self.remove_all_hashes,
            )
        if not text:
            return

        attempts = _MAX_TTS_RETRIES + 1
        for attempt in range(1, attempts + 1):
            emitted_samples = 0
            try:
                communicate = edge_tts.Communicate(
                    text,
                    voice=self.voice,
                    rate=self.rate,
                    volume=self.volume,
                    boundary="WordBoundary",
                )
                mp3_data = bytearray()
                word_boundaries: list[dict] = []
                decoded_at_bytes = 0
                sentence_id = uuid4().hex
                chunk_index = 0

                async for source_chunk in communicate.stream():
                    if interrupt_signal and interrupt_signal.is_set():
                        return
                    chunk_type = source_chunk.get("type")
                    if chunk_type == "WordBoundary":
                        word_boundaries.append(source_chunk)
                        continue
                    if chunk_type != "audio":
                        continue
                    mp3_data.extend(source_chunk["data"])
                    if len(mp3_data) - decoded_at_bytes < self.streaming_decode_min_bytes:
                        continue
                    decoded_at_bytes = len(mp3_data)
                    frames = await asyncio.to_thread(
                        self._try_decode_partial,
                        bytes(mp3_data),
                    )
                    total_samples = sum(len(frame) for frame in frames)
                    boundaries = self._build_boundaries(
                        word_boundaries,
                        total_samples,
                    )
                    cursor = 0
                    for frame in frames:
                        frame_end = cursor + len(frame)
                        if frame_end <= emitted_samples:
                            cursor = frame_end
                            continue
                        if emitted_samples > cursor:
                            frame = frame[emitted_samples - cursor :]
                            cursor = emitted_samples
                        if len(frame) == 0:
                            continue
                        metadata = PlaybackChunkMetadata(
                            sentence_id=sentence_id,
                            sentence_text=text,
                            boundaries=boundaries,
                            start_sample=cursor,
                            total_samples=total_samples,
                        )
                        yield PlaybackChunk(
                            pcm_data=frame,
                            metadata=metadata,
                            response_generation=response_generation,
                            turn_id=turn_id,
                        )
                        cursor += len(frame)
                        chunk_index += 1
                    emitted_samples = max(emitted_samples, total_samples)

                if len(mp3_data) > decoded_at_bytes:
                    frames = await asyncio.to_thread(
                        self._try_decode_partial,
                        bytes(mp3_data),
                    )
                    total_samples = sum(len(frame) for frame in frames)
                    boundaries = self._build_boundaries(word_boundaries, total_samples)
                    cursor = 0
                    for frame in frames:
                        frame_end = cursor + len(frame)
                        if frame_end <= emitted_samples:
                            cursor = frame_end
                            continue
                        if emitted_samples > cursor:
                            frame = frame[emitted_samples - cursor :]
                            cursor = emitted_samples
                        if len(frame):
                            yield PlaybackChunk(
                                pcm_data=frame,
                                metadata=PlaybackChunkMetadata(
                                    sentence_id=sentence_id,
                                    sentence_text=text,
                                    boundaries=boundaries,
                                    start_sample=cursor,
                                    total_samples=total_samples,
                                ),
                                response_generation=response_generation,
                                turn_id=turn_id,
                            )
                            cursor += len(frame)
                            chunk_index += 1
                if emitted_samples or chunk_index:
                    return
                raise NoAudioReceived(
                    "No audio was received. Please verify that your parameters are correct."
                )
            except asyncio.CancelledError:
                raise
            except GeneratorExit:
                return
            except Exception as exc:
                if (
                    isinstance(exc, RuntimeError)
                    and "coroutine ignored GeneratorExit" in str(exc)
                ) or (interrupt_signal and interrupt_signal.is_set()):
                    return
                if emitted_samples:
                    log_event(
                        logger,
                        logging.WARNING,
                        "tts.progressive_stream_ended_early",
                        text_chars=len(text),
                        emitted_samples=emitted_samples,
                        error_type=type(exc).__name__,
                    )
                    return
                if not self._is_retryable_error(exc):
                    raise
                if attempt >= attempts:
                    log_event(
                        logger,
                        logging.WARNING,
                        "tts.sentence_failed",
                        text_chars=len(text),
                        attempts=attempt,
                        error_type=type(exc).__name__,
                    )
                    return
                delay_seconds = _TTS_RETRY_DELAYS_SECONDS[
                    min(attempt - 1, len(_TTS_RETRY_DELAYS_SECONDS) - 1)
                ]
                if await self._wait_retry_delay(delay_seconds, interrupt_signal):
                    return

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
            return TTSPlaybackResult(False, "edge", reason="empty_text")

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
                        return TTSPlaybackResult(False, "edge", reason="interrupted")

                    chunk_type = chunk.get("type")
                    if chunk_type == "audio":
                        mp3_buffer.write(chunk["data"])
                    elif chunk_type == "WordBoundary":
                        word_boundaries.append(chunk)

                mp3_data = mp3_buffer.getvalue()
                if not mp3_data:
                    return TTSPlaybackResult(False, "edge", reason="empty_audio")

                frames = self._try_decode_partial(mp3_data)
                if not frames:
                    return TTSPlaybackResult(False, "edge", reason="decode_empty")
                playback_chunks = self._build_playback_chunks(text, frames, word_boundaries)
                for playback_chunk in playback_chunks:
                    if interrupt_signal and interrupt_signal.is_set():
                        return TTSPlaybackResult(False, "edge", reason="interrupted")
                    audio_player.play(playback_chunk)
                return TTSPlaybackResult(bool(playback_chunks), "edge")

            except asyncio.CancelledError:
                raise
            except GeneratorExit:
                log_event(logger, logging.DEBUG, "tts.interrupted", reason="generator_exit")
                return TTSPlaybackResult(False, "edge", reason="interrupted")
            except Exception as exc:
                if (
                    isinstance(exc, RuntimeError)
                    and "coroutine ignored GeneratorExit" in str(exc)
                ) or (interrupt_signal and interrupt_signal.is_set()):
                    log_event(logger, logging.DEBUG, "tts.interrupted", reason=str(exc) if str(exc) else "interrupted")
                    return TTSPlaybackResult(False, "edge", reason="interrupted")

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
                    return TTSPlaybackResult(
                        False,
                        "edge",
                        reason="retry_exhausted",
                        error_type=type(exc).__name__,
                    )

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
                    return TTSPlaybackResult(False, "edge", reason="interrupted")

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
        container = None
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
        except Exception as exc:
            raise _EdgeTTSAudioDecodeError("Edge TTS returned invalid audio data.") from exc
        finally:
            if container is not None:
                container.close()
        return result
