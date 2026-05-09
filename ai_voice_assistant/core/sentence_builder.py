from collections import deque

import numpy as np

from utils.logger import get_logger

logger = get_logger(__name__)


class SentenceBuilder:
    def __init__(self, pre_roll_ms: int = 500, chunk_ms: int = 32):
        """
        Collect one utterance sliced by VAD.

        `pre_roll_ms` keeps a short lead-in so the first syllable is not clipped.
        """
        self.speech_buffer = []
        self.is_speaking = False

        max_pre_roll = max(1, pre_roll_ms // chunk_ms)
        self.pre_roll_buffer = deque(maxlen=max_pre_roll)

    def is_empty(self) -> bool:
        return len(self.speech_buffer) == 0

    def has_partial_audio(self) -> bool:
        return len(self.speech_buffer) > 0

    def add_chunk(self, chunk: np.ndarray, speech_event: dict):
        """
        Feed one audio chunk and its matching VAD event.

        Return full `float32` utterance audio when the sentence ends.
        """
        result_audio = None

        if speech_event:
            if "start" in speech_event:
                if not self.is_speaking:
                    logger.debug(
                        f"偵測到語音開始，補回 pre-roll chunk 數量：{len(self.pre_roll_buffer)}"
                    )
                    self.is_speaking = True
                    self.speech_buffer = list(self.pre_roll_buffer)
                    self.speech_buffer.append(chunk)
                    self.pre_roll_buffer.clear()

            elif "end" in speech_event:
                if self.is_speaking:
                    logger.debug("偵測到語音結束。")
                    self.is_speaking = False
                    self.speech_buffer.append(chunk)

                    if len(self.speech_buffer) > 0:
                        logger.debug(
                            f"準備輸出完整句子，累積長度：{sum(len(c) for c in self.speech_buffer)} samples"
                        )
                        result_audio = self._build_audio()

                    self.speech_buffer = []
        else:
            if self.is_speaking:
                self.speech_buffer.append(chunk)
            else:
                self.pre_roll_buffer.append(chunk)

        return result_audio

    def _build_audio(self) -> np.ndarray:
        """Merge buffered `int16` audio and convert it to Whisper `float32`."""
        accumulated_int16 = np.concatenate(self.speech_buffer)
        if accumulated_int16.ndim > 1:
            accumulated_int16 = np.squeeze(accumulated_int16)

        return accumulated_int16.astype(np.float32) / 32768.0

    def flush_partial(self) -> np.ndarray | None:
        """Flush the currently buffered speech without an end event."""
        if not self.speech_buffer:
            self.is_speaking = False
            return None

        logger.debug(
            f"收集逾時，強制輸出目前語音，累積長度：{sum(len(c) for c in self.speech_buffer)} samples"
        )
        result_audio = self._build_audio()
        self.reset()
        return result_audio

    def reset(self, *, clear_pre_roll: bool = False):
        """Clear the current utterance state."""
        self.is_speaking = False
        self.speech_buffer = []
        if clear_pre_roll:
            self.pre_roll_buffer.clear()
