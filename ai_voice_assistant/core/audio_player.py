from dataclasses import dataclass, replace
import queue
import threading
import time

import numpy as np
import sounddevice as sd

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PlaybackBoundary:
    text: str
    start_sample: int
    end_sample: int


@dataclass(frozen=True, slots=True)
class PlaybackChunkMetadata:
    sentence_id: str
    sentence_text: str
    boundaries: tuple[PlaybackBoundary, ...] = ()
    start_sample: int = 0
    total_samples: int = 0


@dataclass(frozen=True, slots=True)
class PlaybackChunk:
    pcm_data: np.ndarray
    metadata: PlaybackChunkMetadata | None = None


@dataclass(frozen=True, slots=True)
class PlaybackProgressSnapshot:
    status: str
    sentence_text: str | None
    heard_text: str
    current_word: str | None
    remaining_text: str
    played_samples: int
    total_samples: int


class AudioPlayer:
    def __init__(self, sample_rate: int = 24000, channels: int = 1, blocksize: int = 1024):
        self.sample_rate = sample_rate
        self.channels = channels
        self.blocksize = blocksize
        self.playback_queue = queue.Queue()
        self.interrupt_flag = False
        self.stream = None
        self._residual_data: np.ndarray | None = None
        self._residual_metadata: PlaybackChunkMetadata | None = None
        self._stream_lock = threading.Lock()
        self._residual_lock = threading.Lock()
        self._tracking_lock = threading.Lock()
        self._active_metadata: PlaybackChunkMetadata | None = None
        self._active_played_samples = 0
        self._last_progress_snapshot: PlaybackProgressSnapshot | None = None
        self._playback_deadline = 0.0

    def _output_callback(self, outdata: np.ndarray, frames: int, time_info, status: sd.CallbackFlags):
        if status:
            logger.warning(f"Audio output status: {status}")

        if self.interrupt_flag:
            outdata.fill(0)
            raise sd.CallbackStop()

        filled_frames = 0
        copied_audio_samples = 0
        outdata.fill(0)

        while filled_frames < frames:
            copied_metadata = None
            copied_frames = 0
            with self._residual_lock:
                if self._residual_data is not None and len(self._residual_data) > 0:
                    copied_metadata = self._residual_metadata
                    needed = frames - filled_frames
                    copied_frames = min(len(self._residual_data), needed)
                    outdata[filled_frames:filled_frames + copied_frames, 0] = self._residual_data[:copied_frames]

                    if len(self._residual_data) > copied_frames:
                        self._residual_data = self._residual_data[copied_frames:]
                        if copied_metadata is not None:
                            self._residual_metadata = replace(
                                copied_metadata,
                                start_sample=copied_metadata.start_sample + copied_frames,
                            )
                    else:
                        self._residual_data = None
                        self._residual_metadata = None

            if copied_frames:
                self._advance_playback_progress(copied_metadata, copied_frames)
                copied_audio_samples += copied_frames
                filled_frames += copied_frames
                continue

            try:
                payload = self.playback_queue.get_nowait()
            except queue.Empty:
                break

            if payload is None:
                break

            data, metadata = self._normalize_payload(payload)
            with self._residual_lock:
                self._residual_data = data
                self._residual_metadata = metadata

        if copied_audio_samples > 0:
            with self._tracking_lock:
                self._playback_deadline = max(
                    self._playback_deadline,
                    time.monotonic() + (copied_audio_samples / max(float(self.sample_rate), 1.0)),
                )

    @property
    def is_playing(self) -> bool:
        with self._residual_lock:
            has_residual = self._residual_data is not None
        with self._tracking_lock:
            has_buffered_output = time.monotonic() < self._playback_deadline
        return not self.playback_queue.empty() or has_residual or has_buffered_output

    def start(self):
        with self._stream_lock:
            if self.stream is not None:
                logger.warning("Audio player is already running.")
                return

        try:
            self.interrupt_flag = False
            self._reset_progress_tracking()
            new_stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                blocksize=self.blocksize,
                callback=self._output_callback,
                finished_callback=self._on_stream_finished,
            )
            new_stream.start()
            with self._stream_lock:
                self.stream = new_stream
            logger.info(
                f"Started audio player (Sample rate: {self.sample_rate}, Block size: {self.blocksize})"
            )
        except Exception as e:
            logger.error(f"Failed to start audio player: {e}")
            raise

    def _on_stream_finished(self):
        logger.debug("Audio stream finished (stopped or interrupted).")
        with self._stream_lock:
            self.stream = None

    def stop(self):
        with self._stream_lock:
            stream_to_stop = self.stream
            self.stream = None
        if stream_to_stop is not None:
            try:
                stream_to_stop.stop()
                stream_to_stop.close()
            except Exception:
                pass
            logger.info("Stopped audio player.")
        self._reset_progress_tracking()

    def play(self, pcm_data: np.ndarray | PlaybackChunk):
        if self.interrupt_flag:
            logger.warning("Interrupt flag is set, ignoring play request.")
            return
        self.playback_queue.put(pcm_data)

    def interrupt(self) -> PlaybackProgressSnapshot | None:
        logger.info("Interrupting audio playback...")
        snapshot = self._capture_progress_snapshot()
        self.interrupt_flag = True
        while not self.playback_queue.empty():
            try:
                self.playback_queue.get_nowait()
            except queue.Empty:
                break
        with self._residual_lock:
            self._residual_data = None
            self._residual_metadata = None
        with self._tracking_lock:
            self._active_metadata = None
            self._active_played_samples = 0
            self._playback_deadline = 0.0
            if snapshot is not None:
                self._last_progress_snapshot = snapshot
        return snapshot

    def reset_interrupt(self):
        self.interrupt_flag = False
        with self._stream_lock:
            stream_to_close = self.stream
            self.stream = None
        if stream_to_close is not None:
            try:
                stream_to_close.stop()
                stream_to_close.close()
            except Exception:
                pass
        self._reset_progress_tracking()
        self.start()

    def _normalize_payload(
        self,
        payload: np.ndarray | PlaybackChunk,
    ) -> tuple[np.ndarray, PlaybackChunkMetadata | None]:
        if isinstance(payload, PlaybackChunk):
            return payload.pcm_data, payload.metadata
        return payload, None

    def _advance_playback_progress(
        self,
        metadata: PlaybackChunkMetadata | None,
        sample_count: int,
    ) -> None:
        if metadata is None or not metadata.sentence_id:
            return

        with self._tracking_lock:
            if (
                self._active_metadata is None
                or self._active_metadata.sentence_id != metadata.sentence_id
            ):
                self._active_metadata = metadata
                self._active_played_samples = metadata.start_sample
            elif metadata.start_sample > self._active_played_samples:
                self._active_played_samples = metadata.start_sample

            total_samples = metadata.total_samples or (metadata.start_sample + sample_count)
            self._active_played_samples = min(
                total_samples,
                self._active_played_samples + sample_count,
            )
            self._last_progress_snapshot = self._build_progress_snapshot_locked()

    def _capture_progress_snapshot(self) -> PlaybackProgressSnapshot | None:
        with self._tracking_lock:
            if self._active_metadata is not None:
                return self._build_progress_snapshot_locked()
            return self._last_progress_snapshot

    def _build_progress_snapshot_locked(self) -> PlaybackProgressSnapshot | None:
        if self._active_metadata is None:
            return self._last_progress_snapshot

        total_samples = self._active_metadata.total_samples
        played_samples = min(
            self._active_played_samples,
            total_samples or self._active_played_samples,
        )
        heard_text, current_word, remaining_text = self._estimate_sentence_progress(
            self._active_metadata.sentence_text,
            self._active_metadata.boundaries,
            played_samples,
            total_samples,
        )
        return PlaybackProgressSnapshot(
            status="playing" if played_samples > 0 else "queued",
            sentence_text=self._active_metadata.sentence_text,
            heard_text=heard_text,
            current_word=current_word,
            remaining_text=remaining_text,
            played_samples=played_samples,
            total_samples=total_samples,
        )

    def _reset_progress_tracking(self) -> None:
        with self._residual_lock:
            self._residual_data = None
            self._residual_metadata = None
        with self._tracking_lock:
            self._active_metadata = None
            self._active_played_samples = 0
            self._last_progress_snapshot = None
            self._playback_deadline = 0.0

    @staticmethod
    def _estimate_sentence_progress(
        sentence_text: str | None,
        boundaries: tuple[PlaybackBoundary, ...],
        played_samples: int,
        total_samples: int,
    ) -> tuple[str, str | None, str]:
        sentence_text = sentence_text or ""
        if not sentence_text:
            return "", None, ""

        if not boundaries:
            return AudioPlayer._estimate_progress_by_ratio(
                sentence_text,
                played_samples,
                total_samples,
            )

        heard_parts: list[str] = []
        current_word = None
        for boundary in boundaries:
            text = boundary.text or ""
            if not text:
                continue
            if played_samples >= boundary.end_sample:
                heard_parts.append(text)
                current_word = text
                continue
            if played_samples <= boundary.start_sample:
                break

            current_word = text
            partial = AudioPlayer._take_partial_text(
                text,
                played_samples - boundary.start_sample,
                max(boundary.end_sample - boundary.start_sample, 1),
            )
            if partial:
                heard_parts.append(partial)
            break

        heard_text = "".join(heard_parts)
        if sentence_text.startswith(heard_text):
            remaining_text = sentence_text[len(heard_text):]
        else:
            joined_boundary_text = "".join(boundary.text for boundary in boundaries if boundary.text)
            if joined_boundary_text:
                ratio = min(1.0, len(heard_text) / len(joined_boundary_text))
                cutoff = min(len(sentence_text), int(round(len(sentence_text) * ratio)))
                remaining_text = sentence_text[cutoff:]
            else:
                remaining_text = sentence_text

        return heard_text, current_word, remaining_text

    @staticmethod
    def _estimate_progress_by_ratio(
        sentence_text: str,
        played_samples: int,
        total_samples: int,
    ) -> tuple[str, str | None, str]:
        if total_samples <= 0:
            return "", None, sentence_text
        ratio = min(max(played_samples / total_samples, 0.0), 1.0)
        cutoff = min(len(sentence_text), int(round(len(sentence_text) * ratio)))
        heard_text = sentence_text[:cutoff]
        remaining_text = sentence_text[cutoff:]
        current_word = heard_text[-1:] or None
        return heard_text, current_word, remaining_text

    @staticmethod
    def _take_partial_text(text: str, played_samples: int, word_samples: int) -> str:
        if played_samples <= 0 or not text:
            return ""
        ratio = min(max(played_samples / word_samples, 0.0), 1.0)
        cutoff = min(len(text), int(round(len(text) * ratio)))
        return text[:cutoff]
