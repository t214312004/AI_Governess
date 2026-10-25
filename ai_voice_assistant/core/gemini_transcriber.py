"""Gemini audio-to-text adapter with local speech and output quality gates."""
from __future__ import annotations

import asyncio
import io
import re
import threading
import time
import unicodedata

import numpy as np

from utils.gemini_audio import GeminiAPIError, model_content, resolve_api_key, stt_payload, wav_bytes
from utils.gemini_settings import audio_settings
from utils.gemini_transport import request_json


class GeminiTranscriber:
    def __init__(self, *, api_key="", api_key_env="GEMINI_API_KEY", settings=None, sample_rate=16000):
        self.settings = audio_settings("stt", settings)
        self.api_key = resolve_api_key(api_key, api_key_env)
        self.sample_rate = int(sample_rate)
        if self.sample_rate not in (8000, 16000):
            raise ValueError("Gemini STT input sample rate 必須是 8000 或 16000")
        self.last_diagnostics = {}
        self._cancel = threading.Event()
        self._closed = False
        self._vad_model = None
        self._lock = threading.Lock()

    def cancel(self):
        self._cancel.set()

    def close(self):
        self._closed = True
        self.cancel()

    def _has_speech(self, audio):
        if not np.any(np.abs(audio) > 1e-7):
            return False
        if not self.settings["speech_gate_enabled"]:
            return True
        import torch
        from core.vad import _find_bundled_model_path
        if self._vad_model is None:
            with open(_find_bundled_model_path(), "rb") as source:
                self._vad_model = torch.jit.load(io.BytesIO(source.read()), map_location="cpu")
            self._vad_model.eval()
        self._vad_model.reset_states()
        window = 512 if self.sample_rate == 16000 else 256
        speech_samples = 0
        with torch.no_grad():
            for start in range(0, len(audio), window):
                if self._cancel.is_set():
                    raise asyncio.CancelledError
                frame = np.pad(audio[start:start+window], (0, max(0, window-len(audio[start:start+window]))))
                probability = float(self._vad_model(torch.from_numpy(frame), self.sample_rate).item())
                if probability >= self.settings["speech_gate_threshold"]:
                    speech_samples += min(window, len(audio)-start)
                    if speech_samples*1000/self.sample_rate >= self.settings["speech_gate_min_ms"]:
                        return True
        return False

    def _validate_text(self, text, seconds):
        normalized = "".join(c.lower() for c in unicodedata.normalize("NFKC", text)
            if not c.isspace() and not unicodedata.category(c).startswith("P"))
        if len(normalized) > self.settings["max_chars_per_second"]*max(seconds, 1):
            raise GeminiAPIError("excessive_transcript_length")
        limit = self.settings["repetition_limit"]
        if re.search(r"(.{3,40}?)\1{" + str(limit-1) + r",}", normalized):
            raise GeminiAPIError("repeated_transcript")
        if normalized in ("無人聲", "無語音", "無法辨識", "沒有可辨識的人聲", "nospeech"):
            return ""
        from core.transcriber import _sanitize_transcript_text
        return _sanitize_transcript_text(text.strip().strip('"'), None)

    async def transcribe_async(self, audio, cancel_event=None):
        engine = self
        class Signal:
            def is_set(self):
                return engine._closed or engine._cancel.is_set() or (cancel_event is not None and cancel_event.is_set())
        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim != 1 or not np.isfinite(audio).all():
            raise GeminiAPIError("invalid_audio")
        seconds = len(audio)/self.sample_rate
        if seconds > self.settings["max_audio_seconds"]:
            raise GeminiAPIError("audio_too_long")
        if not len(audio) or not self._has_speech(audio):
            self.last_diagnostics.update(status="no_speech", reason="speech_gate")
            return ""
        s = self.settings
        payload = stt_payload(wav_bytes(audio, self.sample_rate), model=s["model"],
            thinking_level=s["thinking_level"], prompt=s["transcription_prompt"],
            vocabulary_hints=s["vocabulary_hints"], max_output_tokens=s["max_output_tokens"])
        response = await request_json(payload, self.api_key, s, signal=Signal(), diagnostics=self.last_diagnostics)
        self.last_diagnostics["usage"] = response.get("usage", {})
        usage = response.get("usage", {})
        if usage.get("total_output_tokens", 0)+usage.get("total_thought_tokens", 0) >= s["max_output_tokens"]:
            raise GeminiAPIError("truncated_transcript")
        if response.get("errors"):
            raise GeminiAPIError("blocked_response")
        blocks = model_content(response, "text")
        if not blocks:
            raise GeminiAPIError("missing_text_output")
        text = self._validate_text("".join(part.get("text", "") for part in blocks), seconds)
        self.last_diagnostics.update(status="ok" if text else "no_speech", reason="")
        return text

    def transcribe(self, audio, cancel_event=None):
        with self._lock:
            started = time.monotonic()
            self._cancel.clear()
            self.last_diagnostics = {"backend": "gemini", "model": self.settings["model"], "attempts": 0}
            try:
                if self._closed:
                    raise asyncio.CancelledError
                return asyncio.run(self.transcribe_async(audio, cancel_event))
            except asyncio.CancelledError:
                self.last_diagnostics.update(status="cancelled", reason="cancelled")
                return ""
            except Exception as exc:
                self.last_diagnostics.update(status="error", reason=exc.reason if isinstance(exc, GeminiAPIError) else "invalid_audio_or_response")
                return ""
            finally:
                self.last_diagnostics["elapsed_ms"] = (time.monotonic()-started)*1000
