from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from uuid import uuid4

import numpy as np

from core.audio_player import PlaybackChunk, PlaybackChunkMetadata
from tts.base import PlaybackChunkCollector, TTSPlaybackResult
from utils.logger import get_logger, log_event

logger = get_logger(__name__)

_DEFAULT_CHUNK_SAMPLES = 4096


def _worker_creationflags() -> int:
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


class BlueMagpieTTSEngine:
    backend = "bluemagpie"

    def __init__(
        self,
        *,
        app_dir: str,
        enabled: bool,
        worker_python: str,
        worker_script: str,
        model_dir: str,
        hf_repo: str,
        hf_token_env: str,
        device: str,
        cfg_value: float,
        inference_timesteps: int,
        max_len: int,
        retry_badcase: bool,
        seed: int | None,
        fade_out_ms: float,
        tail_silence_ms: float,
        speaker_centroid_path: str,
        prompt_text: str,
        prompt_wav_path: str,
        seed_retry_count: int,
        min_rms: float,
        min_nonzero_ratio: float,
        warm_on_start: bool,
        request_timeout_seconds: float,
        output_sample_rate: int,
        temp_dir: str,
        chunk_samples: int = _DEFAULT_CHUNK_SAMPLES,
    ):
        self.app_dir = app_dir
        self.enabled = enabled
        self.worker_python = worker_python
        self.worker_script = worker_script
        self.model_dir = model_dir
        self.hf_repo = hf_repo
        self.hf_token_env = hf_token_env
        self.device = device
        self.cfg_value = cfg_value
        self.inference_timesteps = inference_timesteps
        self.max_len = max_len
        self.retry_badcase = retry_badcase
        self.seed = seed
        self.fade_out_ms = fade_out_ms
        self.tail_silence_ms = tail_silence_ms
        self.speaker_centroid_path = speaker_centroid_path
        self.prompt_text = prompt_text
        self.prompt_wav_path = prompt_wav_path
        self.seed_retry_count = max(int(seed_retry_count), 0)
        self.min_rms = max(float(min_rms), 0.0)
        self.min_nonzero_ratio = max(float(min_nonzero_ratio), 0.0)
        self.warm_on_start = bool(warm_on_start)
        self.request_timeout_seconds = request_timeout_seconds
        self.output_sample_rate = output_sample_rate
        self.temp_dir = temp_dir
        self.chunk_samples = max(int(chunk_samples), 1)
        self._worker_process: asyncio.subprocess.Process | None = None
        self._worker_lock = asyncio.Lock()

    def update_settings(self, **kwargs) -> None:
        # Edge-style voice/rate/volume settings are not applicable to BlueMagpie V1.
        return None

    async def warm_up(self) -> dict:
        if not self.enabled:
            return {"ok": False, "reason": "disabled"}

        request_id = f"tts-warmup-{uuid4().hex}"
        response = await self._send_worker_payload(
            {
                "command": "warmup",
                "request_id": request_id,
                "speaker_centroid_path": self.speaker_centroid_path,
                "prompt_text": self.prompt_text,
                "prompt_wav_path": self.prompt_wav_path,
            },
            interrupt_signal=None,
        )
        if response.get("ok"):
            log_event(
                logger,
                logging.INFO,
                "tts.bluemagpie.warmup_completed",
                warmup_seconds=response.get("warmup_seconds"),
                speaker_centroid_used=response.get("speaker_centroid_used"),
                prompt_wav_used=response.get("prompt_wav_used"),
            )
        else:
            log_event(
                logger,
                logging.WARNING,
                "tts.bluemagpie.warmup_failed",
                reason=response.get("reason"),
                error_type=response.get("error_type"),
                error=response.get("error"),
                traceback=response.get("traceback"),
            )
        return response

    def close(self) -> None:
        process = self._worker_process
        self._worker_process = None
        if process is not None and process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            except Exception:
                logger.exception("Failed to terminate BlueMagpie TTS worker.")

    async def aclose(self, timeout_seconds: float = 5.0) -> None:
        async with self._worker_lock:
            process = self._worker_process
            self._worker_process = None
            if process is None or process.returncode is not None:
                return

            try:
                if process.stdin is not None and not process.stdin.is_closing():
                    payload = json.dumps({"command": "shutdown"}) + "\n"
                    process.stdin.write(payload.encode("utf-8"))
                    await process.stdin.drain()
            except Exception:
                logger.debug("Failed to request BlueMagpie worker shutdown.", exc_info=True)

            try:
                await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
                return
            except asyncio.TimeoutError:
                pass

            try:
                process.terminate()
            except ProcessLookupError:
                return
            except Exception:
                logger.exception("Failed to terminate BlueMagpie TTS worker.")
                return

            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
                return
            except asyncio.TimeoutError:
                pass

            try:
                process.kill()
            except ProcessLookupError:
                return
            except Exception:
                logger.exception("Failed to kill BlueMagpie TTS worker.")
                return
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except Exception:
                logger.debug("BlueMagpie worker did not exit after kill.", exc_info=True)

    async def synthesize_stream(
        self,
        text: str,
        interrupt_signal: asyncio.Event | None = None,
        *,
        response_generation: int | None = None,
        turn_id: str | None = None,
    ):
        collector = PlaybackChunkCollector(
            self.output_sample_rate,
            response_generation=response_generation,
            turn_id=turn_id,
        )
        await self.speak_stream(text, collector, interrupt_signal)
        for chunk in collector.chunks:
            if interrupt_signal and interrupt_signal.is_set():
                return
            yield chunk

    async def speak_stream(
        self,
        text: str,
        audio_player,
        interrupt_signal: asyncio.Event | None = None,
    ) -> TTSPlaybackResult:
        text = (text or "").strip()
        if not text:
            return TTSPlaybackResult(False, self.backend, reason="empty_text")
        if interrupt_signal and interrupt_signal.is_set():
            return TTSPlaybackResult(False, self.backend, reason="interrupted")
        if not self.enabled:
            log_event(
                logger,
                logging.WARNING,
                "tts.bluemagpie.disabled",
                text_chars=len(text),
            )
            return TTSPlaybackResult(False, self.backend, reason="disabled")

        target_sample_rate = int(getattr(audio_player, "sample_rate", self.output_sample_rate))
        response = await self._send_worker_request(
            text=text,
            output_sample_rate=target_sample_rate,
            interrupt_signal=interrupt_signal,
        )
        if interrupt_signal and interrupt_signal.is_set():
            self._cleanup_pcm_path(response.get("pcm_path"))
            return TTSPlaybackResult(False, self.backend, reason="interrupted")
        if not response.get("ok"):
            self._cleanup_pcm_path(response.get("pcm_path"))
            reason = str(response.get("reason") or "worker_failed")
            error_type = response.get("error_type")
            log_event(
                logger,
                logging.WARNING,
                "tts.bluemagpie.sentence_failed",
                text_chars=len(text),
                reason=reason,
                error_type=error_type,
                error=response.get("error"),
                traceback=response.get("traceback"),
            )
            return TTSPlaybackResult(False, self.backend, reason=reason, error_type=error_type)

        response_sample_rate = int(response.get("sample_rate") or 0)
        if response_sample_rate != target_sample_rate:
            self._cleanup_pcm_path(response.get("pcm_path"))
            log_event(
                logger,
                logging.WARNING,
                "tts.bluemagpie.sample_rate_mismatch",
                expected_sample_rate=target_sample_rate,
                actual_sample_rate=response_sample_rate,
            )
            return TTSPlaybackResult(False, self.backend, reason="sample_rate_mismatch")

        try:
            pcm = self._load_pcm_file(str(response["pcm_path"]))
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                "tts.bluemagpie.pcm_load_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return TTSPlaybackResult(False, self.backend, reason="pcm_load_failed", error_type=type(exc).__name__)

        log_event(
            logger,
            logging.INFO,
            "tts.bluemagpie.sentence_generated",
            text_chars=len(text),
            sample_rate=response_sample_rate,
            pcm_samples=len(pcm),
            duration_seconds=response.get("duration_seconds"),
            generation_seconds=response.get("generation_seconds"),
            rtf=response.get("rtf"),
            speaker_centroid_used=response.get("speaker_centroid_used"),
            prompt_wav_used=response.get("prompt_wav_used"),
            seed=response.get("seed"),
            base_seed=response.get("base_seed"),
            seed_attempt=response.get("seed_attempt"),
            seed_retry_count=response.get("seed_retry_count"),
            fade_out_ms=response.get("fade_out_ms"),
            tail_silence_ms=response.get("tail_silence_ms"),
            audio_rms=response.get("audio_rms"),
            audio_peak=response.get("audio_peak"),
            audio_nonzero_ratio=response.get("audio_nonzero_ratio"),
        )

        played = False
        for chunk in self._build_playback_chunks(text, pcm):
            if interrupt_signal and interrupt_signal.is_set():
                return TTSPlaybackResult(played, self.backend, reason="interrupted")
            audio_player.play(chunk)
            played = True

        return TTSPlaybackResult(played, self.backend, reason=None if played else "empty_audio")

    def _preflight_worker(self) -> dict:
        if not self.worker_python or not os.path.exists(self.worker_python):
            return {
                "ok": False,
                "reason": "worker_python_missing",
                "error": self.worker_python,
                "error_type": "FileNotFoundError",
            }
        if not self.worker_script or not os.path.exists(self.worker_script):
            return {
                "ok": False,
                "reason": "worker_script_missing",
                "error": self.worker_script,
                "error_type": "FileNotFoundError",
            }
        return {"ok": True}

    async def _ensure_worker(self) -> dict:
        preflight = self._preflight_worker()
        if not preflight.get("ok"):
            return preflight
        if self._worker_process is not None and self._worker_process.returncode is None:
            return {"ok": True}

        os.makedirs(self.temp_dir, exist_ok=True)
        subprocess_kwargs = {
            "stdin": asyncio.subprocess.PIPE,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.DEVNULL,
            "cwd": self.app_dir,
        }
        creationflags = _worker_creationflags()
        if creationflags:
            subprocess_kwargs["creationflags"] = creationflags
        try:
            self._worker_process = await asyncio.create_subprocess_exec(
                self.worker_python,
                "-u",
                self.worker_script,
                "--model-dir",
                self.model_dir,
                "--hf-repo",
                self.hf_repo,
                "--hf-token-env",
                self.hf_token_env,
                "--device",
                self.device,
                "--output-dir",
                self.temp_dir,
                **subprocess_kwargs,
            )
            return {"ok": True}
        except Exception as exc:
            self._worker_process = None
            return {
                "ok": False,
                "reason": "worker_start_failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

    async def _send_worker_request(
        self,
        *,
        text: str,
        output_sample_rate: int,
        interrupt_signal: asyncio.Event | None,
    ) -> dict:
        request_id = f"tts-{uuid4().hex}"
        payload = {
            "request_id": request_id,
            "text": text,
            "speaker_centroid_path": self.speaker_centroid_path,
            "cfg_value": self.cfg_value,
            "inference_timesteps": self.inference_timesteps,
            "max_len": self.max_len,
            "retry_badcase": self.retry_badcase,
            "seed": self.seed,
            "fade_out_ms": self.fade_out_ms,
            "tail_silence_ms": self.tail_silence_ms,
            "prompt_text": self.prompt_text,
            "prompt_wav_path": self.prompt_wav_path,
            "seed_retry_count": self.seed_retry_count,
            "min_rms": self.min_rms,
            "min_nonzero_ratio": self.min_nonzero_ratio,
            "output_sample_rate": output_sample_rate,
        }
        return await self._send_worker_payload(payload, interrupt_signal)

    async def _send_worker_payload(
        self,
        payload: dict,
        interrupt_signal: asyncio.Event | None,
    ) -> dict:
        async with self._worker_lock:
            worker_status = await self._ensure_worker()
            if not worker_status.get("ok"):
                return worker_status

            process = self._worker_process
            if process is None or process.stdin is None or process.stdout is None:
                return {"ok": False, "reason": "worker_unavailable"}

            try:
                process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
                await process.stdin.drain()
            except Exception as exc:
                self._terminate_worker()
                return {
                    "ok": False,
                    "reason": "worker_write_failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }

            return await self._read_worker_response(process, interrupt_signal)

    async def _read_worker_response(
        self,
        process: asyncio.subprocess.Process,
        interrupt_signal: asyncio.Event | None,
    ) -> dict:
        if process.stdout is None:
            return {"ok": False, "reason": "worker_stdout_missing"}

        read_task = asyncio.create_task(process.stdout.readline())
        interrupt_task = None
        if interrupt_signal is not None:
            interrupt_task = asyncio.create_task(interrupt_signal.wait())

        tasks = [read_task]
        if interrupt_task is not None:
            tasks.append(interrupt_task)

        try:
            done, pending = await asyncio.wait(
                tasks,
                timeout=self.request_timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                self._terminate_worker()
                return {"ok": False, "reason": "timeout", "error_type": "TimeoutError"}

            if interrupt_task is not None and interrupt_task in done and interrupt_signal and interrupt_signal.is_set():
                self._terminate_worker()
                return {"ok": False, "reason": "interrupted"}

            line = read_task.result()
            if not line:
                self._terminate_worker()
                return {"ok": False, "reason": "worker_exited"}
            return json.loads(line.decode("utf-8"))
        except Exception as exc:
            self._terminate_worker()
            return {
                "ok": False,
                "reason": "response_read_failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    def _terminate_worker(self) -> None:
        process = self._worker_process
        self._worker_process = None
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            except Exception:
                logger.exception("Failed to kill BlueMagpie TTS worker.")

    def _load_pcm_file(self, pcm_path: str) -> np.ndarray:
        try:
            pcm = np.load(pcm_path)
        finally:
            try:
                os.remove(pcm_path)
            except OSError:
                pass
        pcm = np.asarray(pcm)
        if pcm.ndim > 1:
            pcm = pcm[0]
        if pcm.dtype != np.int16:
            pcm = pcm.astype(np.int16)
        return pcm

    @staticmethod
    def _cleanup_pcm_path(pcm_path) -> None:
        if not pcm_path:
            return
        try:
            os.remove(str(pcm_path))
        except OSError:
            pass

    def _build_playback_chunks(self, text: str, pcm: np.ndarray) -> list[PlaybackChunk]:
        if pcm.size == 0:
            return []
        sentence_id = uuid4().hex
        total_samples = int(pcm.size)
        chunks: list[PlaybackChunk] = []
        for start in range(0, total_samples, self.chunk_samples):
            frame = pcm[start:start + self.chunk_samples]
            metadata = PlaybackChunkMetadata(
                sentence_id=sentence_id,
                sentence_text=text,
                boundaries=(),
                start_sample=start,
                total_samples=total_samples,
            )
            chunks.append(PlaybackChunk(pcm_data=frame, metadata=metadata))
        return chunks
