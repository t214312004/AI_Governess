"""Gemini TTS with bounded streaming, cancellation and conservative progress."""
from __future__ import annotations

import asyncio
import base64
import io
import time
import threading
from uuid import uuid4
import wave

import av
import httpx
import numpy as np

from core.audio_player import PlaybackChunk, PlaybackChunkMetadata
from tts.base import TTSPlaybackResult
from utils.gemini_audio import (GeminiAPIError, INTERACTIONS_URL, check_response,
    model_content, resolve_api_key, tts_payload)
from utils.gemini_settings import audio_settings
from utils.gemini_transport import (async_sse_messages, backoff, bounded, cancelled,
    response_error, retryable, safe_error)


class PCMConverter:
    def __init__(self, source_rate, target_rate, gain=1.0):
        self.source_rate, self.target_rate, self.gain = source_rate, target_rate, gain
        self.resampler = av.AudioResampler(format="s16", layout="mono", rate=target_rate) if source_rate != target_rate else None

    def convert(self, pcm=None):
        if self.resampler is None:
            arrays = [] if pcm is None else [pcm]
        else:
            frame = None
            if pcm is not None:
                frame = av.AudioFrame.from_ndarray(np.asarray(pcm, dtype=np.int16)[None, :], format="s16", layout="mono")
                frame.sample_rate = self.source_rate
            arrays = [frame.to_ndarray().reshape(-1) for frame in self.resampler.resample(frame)]
        return [np.clip(np.asarray(array, dtype=np.float32)*self.gain, -32768, 32767).astype(np.int16)
                for array in arrays if len(array)]


class GeminiTTSEngine:
    backend = "gemini"

    def __init__(self, *, api_key="", api_key_env="GEMINI_API_KEY", sample_rate=24000,
                 settings=None, streaming=True):
        self.settings = audio_settings("tts", settings)
        # Fixed-text output may retain a Gemini selection without a credential.
        # Startup preflight validates active audio; resolve only when generating.
        self.api_key, self.api_key_env = api_key, api_key_env
        self.sample_rate = int(sample_rate)
        if self.sample_rate <= 0:
            raise ValueError("Playback sample rate must be positive")
        self.streaming = bool(streaming)
        self.last_diagnostics = {}
        self._closed = False
        self._next_request_at = 0.0
        self._lock = asyncio.Lock()
        self._clients = set()
        self._calls = set()
        self._calls_lock = threading.Lock()
        self._failed_generation = object()

    def update_settings(self, *, voice=None, style=None, volume_gain=None, **kwargs):
        changes = {k: v for k, v in {"voice": voice, "style": style, "volume_gain": volume_gain}.items() if v is not None}
        self.settings = audio_settings("tts", dict(self.settings, **changes))

    def close(self):
        self._closed = True
        self.cancel()

    def cancel(self):
        with self._calls_lock:
            for event in self._calls:
                event.set()

    async def aclose(self):
        self.close()
        for client in tuple(self._clients):
            await client.aclose()

    async def _audio_bytes(self, payload, signal, deadline, settings, diagnostics):
        api_key = resolve_api_key(self.api_key, self.api_key_env)
        timeout = httpx.Timeout(settings["stream_idle_timeout_seconds"], connect=settings["connect_timeout_seconds"])
        async with httpx.AsyncClient(timeout=timeout) as client:
            self._clients.add(client)
            try:
                first_deadline = min(deadline, time.monotonic()+settings["first_audio_timeout_seconds"])
                response = await bounded(client.send(client.build_request("POST", INTERACTIONS_URL,
                    headers={"x-goog-api-key": api_key}, json=payload), stream=True),
                    signal=signal, deadline=first_deadline)
                try:
                    response_error(response)
                    if not payload["stream"]:
                        await bounded(response.aread(), signal=signal, deadline=first_deadline)
                        result = check_response(response)
                        diagnostics["usage"] = result.get("usage", {})
                        blocks = model_content(result, "audio")
                        if not blocks:
                            raise GeminiAPIError("missing_audio_output")
                        for block in blocks:
                            yield base64.b64decode(block["data"], validate=True), block.get("mime_type", settings["audio_format"])
                        return
                    events = async_sse_messages(response.aiter_lines())
                    first = True
                    completed = False
                    received_bytes = 0
                    try:
                        while True:
                            try:
                                event = await bounded(anext(events), signal=signal,
                                    deadline=first_deadline if first else deadline,
                                    timeout=settings["stream_idle_timeout_seconds"] if not first else None)
                            except StopAsyncIteration:
                                break
                            kind = event.get("event_type") or event.get("type", "")
                            interaction = event.get("interaction", {})
                            if kind in ("error", "interaction.failed") or interaction.get("status") in ("failed", "incomplete", "cancelled"):
                                raise GeminiAPIError("incomplete_audio_stream")
                            if kind == "interaction.completed":
                                if interaction.get("status", "completed") != "completed":
                                    raise GeminiAPIError("incomplete_audio_stream")
                                completed = True
                                diagnostics["usage"] = interaction.get("usage", event.get("usage", {}))
                            delta = event.get("delta", {})
                            if kind == "step.delta" and delta.get("type") == "audio":
                                data = base64.b64decode(delta.get("data", ""), validate=True)
                                received_bytes += len(data)
                                first = received_bytes < 2
                                if delta.get("sample_rate", settings["api_sample_rate"]) != settings["api_sample_rate"]:
                                    raise GeminiAPIError("invalid_audio_sample_rate")
                                yield data, delta.get("mime_type", "audio/l16")
                    finally:
                        await events.aclose()
                    if not completed:
                        raise GeminiAPIError("incomplete_audio_stream")
                finally:
                    await response.aclose()
            finally:
                self._clients.discard(client)

    async def synthesize_stream(self, text, interrupt_signal=None, *, response_generation=None, turn_id=None):
        engine = self
        call_cancel = threading.Event()
        class Signal:
            def is_set(self):
                return engine._closed or call_cancel.is_set() or cancelled(interrupt_signal)
        signal = Signal()
        if not str(text or "").strip() or signal.is_set():
            return
        if response_generation is not None and response_generation == self._failed_generation:
            return
        with self._calls_lock:
            self._calls.add(call_cancel)
        started = time.monotonic()
        diagnostics = {"backend": "gemini", "status": "pending", "attempts": 0}
        settings = dict(self.settings)
        deadline = started+settings["total_timeout_seconds"]
        acquired = False
        emitted = 0
        try:
            async def acquire():
                nonlocal acquired
                await self._lock.acquire()
                # bounded() can notice cancellation after acquire completes.
                # Record ownership inside its task so finally always releases it.
                acquired = True
            await bounded(acquire(), signal=signal, deadline=deadline)
            self.last_diagnostics = diagnostics
            if response_generation is not None and response_generation == self._failed_generation:
                diagnostics.update(status="error", reason="generation_failed")
                return
            for attempt in range(settings["max_retries"]+1):
                wait = max(0, self._next_request_at-time.monotonic())
                if time.monotonic()+wait >= deadline:
                    raise GeminiAPIError("rate_limited", 429, wait)
                await bounded(asyncio.sleep(wait), signal=signal, deadline=deadline)
                self._next_request_at = time.monotonic()+settings["min_request_interval_seconds"]
                diagnostics["attempts"] = attempt+1
                payload = tts_payload(text, model=settings["model"], voice=settings["voice"],
                    style=settings["style"], stream=self.streaming, sample_rate=settings["api_sample_rate"])
                if not self.streaming:
                    payload["response_format"]["mime_type"] = settings["audio_format"]
                source = self._audio_bytes(payload, signal, deadline, settings, diagnostics)
                converter = PCMConverter(settings["api_sample_rate"], self.sample_rate, settings["volume_gain"])
                carry, pending = b"", None
                total_source_bytes = 0
                sentence_id = uuid4().hex
                def playback(frame, total=0):
                    return PlaybackChunk(frame, PlaybackChunkMetadata(sentence_id, text,
                        start_sample=emitted, total_samples=total), response_generation, turn_id)
                try:
                    async for data, mime in source:
                        total_source_bytes += len(data)
                        if total_source_bytes > settings["max_audio_seconds"]*settings["api_sample_rate"]*2+4096:
                            raise GeminiAPIError("audio_too_long")
                        mime = mime.split(";")[0].lower()
                        if mime == "audio/wav" and not self.streaming:
                            with wave.open(io.BytesIO(data), "rb") as wav:
                                if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                                    raise GeminiAPIError("invalid_audio_format")
                                converter = PCMConverter(wav.getframerate(), self.sample_rate, settings["volume_gain"])
                                pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
                        elif mime == "audio/l16":
                            carry += data
                            size = len(carry)-len(carry)%2
                            if not size:
                                continue
                            pcm = np.frombuffer(carry[:size], dtype="<i2")
                            carry = carry[size:]
                        else:
                            raise GeminiAPIError("invalid_audio_format")
                        for frame in converter.convert(pcm):
                            chunk_samples = max(1, self.sample_rate//50)
                            for offset in range(0, len(frame), chunk_samples):
                                if signal.is_set():
                                    return
                                if pending is not None:
                                    yield playback(pending)
                                    emitted += len(pending)
                                pending = frame[offset:offset+chunk_samples]
                    if carry:
                        raise GeminiAPIError("invalid_pcm_tail")
                    for frame in converter.convert():
                        if pending is not None:
                            yield playback(pending)
                            emitted += len(pending)
                        pending = frame
                    if pending is None:
                        raise GeminiAPIError("empty_audio")
                    if signal.is_set():
                        return
                    yield playback(pending, emitted+len(pending))
                    emitted += len(pending)
                    diagnostics["status"] = "ok"
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await source.aclose()
                    if isinstance(exc, GeminiAPIError) and exc.status_code == 429:
                        self._next_request_at = max(self._next_request_at, time.monotonic()+max(60, exc.retry_after))
                    if emitted or attempt >= settings["max_retries"] or not retryable(exc):
                        raise safe_error(exc) from None
                    await backoff(exc, attempt, signal=signal, deadline=deadline)
                finally:
                    await source.aclose()
        except asyncio.CancelledError:
            diagnostics.update(status="cancelled", reason="interrupted")
            if not signal.is_set():
                raise
        except Exception as exc:
            error = safe_error(exc)
            diagnostics.update(status="error", reason=error.reason, http_status=error.status_code)
            if response_generation is not None:
                self._failed_generation = response_generation
        finally:
            with self._calls_lock:
                self._calls.discard(call_cancel)
            if acquired:
                self._lock.release()
            if diagnostics["status"] == "pending":
                diagnostics.update(status="cancelled", reason="interrupted")
            diagnostics["elapsed_ms"] = (time.monotonic()-started)*1000
            self.last_diagnostics = diagnostics

    async def speak_stream(self, text, audio_player, interrupt_signal=None):
        played = False
        source = self.synthesize_stream(text, interrupt_signal)
        try:
            async for chunk in source:
                if cancelled(interrupt_signal) or self._closed:
                    break
                played = await asyncio.to_thread(audio_player.play, chunk) or played
        finally:
            await source.aclose()
        reason = "interrupted" if cancelled(interrupt_signal) else self.last_diagnostics.get("reason")
        return TTSPlaybackResult(played, "gemini", reason or (None if played else "empty_text"))
