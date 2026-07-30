import io
import importlib.util
import os

import numpy as np
import torch

from utils.logger import get_logger

logger = get_logger(__name__)


def _find_bundled_model_path() -> str:
    """Locate the model without importing silero_vad's torchaudio helpers."""
    spec = importlib.util.find_spec("silero_vad")
    if spec is None or not spec.submodule_search_locations:
        raise ImportError("silero-vad package is not installed")

    package_dir = next(iter(spec.submodule_search_locations))
    model_path = os.path.join(package_dir, "data", "silero_vad.jit")
    if not os.path.isfile(model_path):
        raise FileNotFoundError(f"Silero VAD model not found: {model_path}")
    return model_path


# Adapted from silero-vad 6.2.1's src/silero_vad/utils_vad.py VADIterator.
# Copyright (c) 2020-present Silero Team. Licensed under the MIT License;
# see THIRD_PARTY_NOTICES.md in the repository root for the complete notice.
class VADIterator:
    """Streaming state machine for a loaded Silero VAD model."""

    def __init__(
        self,
        model,
        threshold: float = 0.5,
        sampling_rate: int = 16000,
        min_silence_duration_ms: int = 100,
        speech_pad_ms: int = 30,
    ):
        if sampling_rate not in (8000, 16000):
            raise ValueError("VADIterator supports only 8000 or 16000 Hz")

        self.model = model
        self.threshold = float(threshold)
        self.sampling_rate = int(sampling_rate)
        self.min_silence_samples = self.sampling_rate * min_silence_duration_ms / 1000
        self.speech_pad_samples = self.sampling_rate * speech_pad_ms / 1000
        self.reset_states()

    def reset_states(self):
        self.model.reset_states()
        self.triggered = False
        self.temp_end = 0
        self.current_sample = 0

    @torch.no_grad()
    def __call__(self, chunk, return_seconds: bool = False, time_resolution: int = 1):
        if not torch.is_tensor(chunk):
            try:
                chunk = torch.as_tensor(chunk)
            except (TypeError, ValueError) as exc:
                raise TypeError("Audio cannot be converted to a tensor") from exc

        window_size_samples = chunk.shape[-1]
        self.current_sample += window_size_samples
        speech_probability = self.model(chunk, self.sampling_rate).item()

        if speech_probability >= self.threshold and self.temp_end:
            self.temp_end = 0

        if speech_probability >= self.threshold and not self.triggered:
            self.triggered = True
            speech_start = max(
                0,
                self.current_sample - self.speech_pad_samples - window_size_samples,
            )
            return {
                "start": self._format_timestamp(
                    speech_start,
                    return_seconds,
                    time_resolution,
                )
            }

        if speech_probability < self.threshold - 0.15 and self.triggered:
            if not self.temp_end:
                self.temp_end = self.current_sample
            if self.current_sample - self.temp_end < self.min_silence_samples:
                return None

            speech_end = self.temp_end + self.speech_pad_samples - window_size_samples
            self.temp_end = 0
            self.triggered = False
            return {
                "end": self._format_timestamp(
                    speech_end,
                    return_seconds,
                    time_resolution,
                )
            }

        return None

    def _format_timestamp(
        self,
        sample: float,
        return_seconds: bool,
        time_resolution: int,
    ):
        if return_seconds:
            return round(sample / self.sampling_rate, time_resolution)
        return int(sample)


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
        model_path = _find_bundled_model_path()
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
