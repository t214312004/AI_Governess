import io
import os

import numpy as np
import silero_vad
import torch
from silero_vad import VADIterator

from utils.logger import get_logger

logger = get_logger(__name__)


class VoiceActivityDetector:
    def __init__(
        self,
        threshold: float = 0.5,
        sampling_rate: int = 16000,
        min_silence_duration_ms: int = 500,
        speech_pad_ms: int = 30,
    ):
        self.threshold = threshold
        self.sampling_rate = sampling_rate
        self.min_silence_duration_ms = int(min_silence_duration_ms)
        self.speech_pad_ms = int(speech_pad_ms)

        # Load through bytes first to avoid torch path decoding failures on Windows.
        model_path = os.path.join(os.path.dirname(silero_vad.__file__), "data", "silero_vad.jit")
        with open(model_path, "rb") as f:
            buffer = io.BytesIO(f.read())
        self.vad_model = torch.jit.load(buffer, map_location=torch.device("cpu"))
        self.vad_model.eval()
        self._build_iterator()
        logger.info(
            f"Initialized Silero VAD (Threshold: {threshold}, Min Silence: {self.min_silence_duration_ms}ms)"
        )

    def _build_iterator(self):
        self.vad_iterator = VADIterator(
            self.vad_model,
            threshold=self.threshold,
            sampling_rate=self.sampling_rate,
            min_silence_duration_ms=self.min_silence_duration_ms,
            speech_pad_ms=self.speech_pad_ms,
        )

    def process_chunk(self, chunk_int16: np.ndarray):
        """
        Process one `int16` audio chunk and return a VAD event when present.

        Reset the iterator after sentence end to limit long-lived state drift.
        """
        chunk_float32 = chunk_int16.astype(np.float32) / 32768.0

        if chunk_float32.ndim > 1:
            chunk_float32 = np.squeeze(chunk_float32)

        chunk_tensor = torch.from_numpy(chunk_float32)
        speech_dict = self.vad_iterator(chunk_tensor, return_seconds=True)

        if speech_dict and "end" in speech_dict:
            self.vad_iterator.reset_states()

        return speech_dict

    def reset_states(self):
        """Clear VAD internal state."""
        self.vad_iterator.reset_states()

    def update_min_silence_duration(self, min_silence_duration_ms: int):
        """Update the end-of-speech silence threshold and rebuild the iterator."""
        self.min_silence_duration_ms = int(min_silence_duration_ms)
        self._build_iterator()
