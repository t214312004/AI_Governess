import logging
import queue
import time

import numpy as np
import sounddevice as sd

from utils.logger import get_logger, log_event

logger = get_logger(__name__)

# About 6.4 seconds at 512 samples/block and 16 kHz.
_QUEUE_MAXSIZE = 200


class AudioCapture:
    def __init__(self, sample_rate: int = 16000, channels: int = 1, blocksize: int = 512):
        self.sample_rate = sample_rate
        self.channels = channels
        self.blocksize = blocksize
        self.audio_queue = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        self.stream = None
        self._dropped_chunks = 0
        self._last_overflow_log_at = 0.0

    def _input_callback(self, indata: np.ndarray, frames: int, time_info, status: sd.CallbackFlags):
        if status:
            logger.warning(f"Audio input status: {status}")
        # sounddevice reuses callback buffers, so copy before queueing.
        try:
            self.audio_queue.put_nowait(indata.copy())
        except queue.Full:
            self._dropped_chunks += 1
            now = time.monotonic()
            if self._dropped_chunks == 1 or (now - self._last_overflow_log_at) >= 5.0:
                self._last_overflow_log_at = now
                log_event(
                    logger,
                    logging.WARNING,
                    "audio_input.queue_overflow",
                    dropped_chunks=self._dropped_chunks,
                    queue_maxsize=self.audio_queue.maxsize,
                )

            # Keep the newest audio when the callback falls behind.
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                pass  # pragma: no cover
            try:
                self.audio_queue.put_nowait(indata.copy())
            except queue.Full:
                pass

    def start(self):
        if self.stream is not None:
            logger.warning("Audio capture is already running.")
            return

        try:
            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                blocksize=self.blocksize,
                callback=self._input_callback,
            )
            self.stream.start()
            logger.info(
                f"Started audio capture (Sample rate: {self.sample_rate}, Block size: {self.blocksize})"
            )
        except Exception as e:
            logger.error(f"Failed to start audio capture: {e}")
            raise

    def stop(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
            logger.info("Stopped audio capture.")
        if self._dropped_chunks:
            log_event(
                logger,
                logging.INFO,
                "audio_input.drop_summary",
                dropped_chunks=self._dropped_chunks,
            )

    def get_audio_queue(self) -> queue.Queue:
        return self.audio_queue
