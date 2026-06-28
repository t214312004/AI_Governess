from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from uuid import uuid4

import numpy as np


class SilentAudioError(RuntimeError):
    pass


class BlueMagpieWorker:
    def __init__(
        self,
        *,
        model_dir: str,
        hf_repo: str,
        hf_token_env: str,
        device: str,
        output_dir: str,
    ):
        self.model_dir = model_dir
        self.hf_repo = hf_repo
        self.hf_token_env = hf_token_env
        self.device = device
        self.output_dir = output_dir
        self.model = None
        self.torch = None

    def warmup(self, request: dict) -> dict:
        request_id = request.get("request_id") or f"tts-warmup-{uuid4().hex}"
        started_at = time.monotonic()
        try:
            model = self._load_model()
            speaker_centroid = self._load_speaker_centroid(
                request.get("speaker_centroid_path")
            )
            prompt_text = request.get("prompt_text") or ""
            prompt_wav_path = request.get("prompt_wav_path") or ""
            if prompt_text and prompt_wav_path and not os.path.exists(prompt_wav_path):
                raise FileNotFoundError(prompt_wav_path)

            warmup_seconds = time.monotonic() - started_at
            return {
                "request_id": request_id,
                "ok": True,
                "sample_rate": int(getattr(model, "sample_rate", 48000)),
                "warmup_seconds": warmup_seconds,
                "speaker_centroid_used": speaker_centroid is not None,
                "prompt_wav_used": bool(prompt_text and prompt_wav_path),
            }
        except Exception as exc:
            return {
                "request_id": request_id,
                "ok": False,
                "reason": "warmup_failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(limit=8),
            }

    def synthesize(self, request: dict) -> dict:
        request_id = request.get("request_id") or f"tts-{uuid4().hex}"
        started_at = time.monotonic()
        try:
            model = self._load_model()
            torch = self.torch
            speaker_centroid = self._load_speaker_centroid(
                request.get("speaker_centroid_path")
            )
            base_seed = self._optional_int(request.get("seed"))
            seed_retry_count = max(0, int(request.get("seed_retry_count") or 0))
            min_rms = max(0.0, float(request.get("min_rms", 0.0005)))
            min_nonzero_ratio = max(
                0.0,
                float(request.get("min_nonzero_ratio", 0.001)),
            )
            generate_kwargs = {
                "target_text": request.get("text") or "",
                "cfg_value": float(request.get("cfg_value", 2.8)),
                "inference_timesteps": int(request.get("inference_timesteps", 9)),
                "max_len": int(request.get("max_len", 2000)),
                "retry_badcase": self._bool_setting(request.get("retry_badcase"), True),
            }
            prompt_text = request.get("prompt_text") or ""
            prompt_wav_path = request.get("prompt_wav_path") or ""
            if prompt_text and prompt_wav_path:
                if not os.path.exists(prompt_wav_path):
                    raise FileNotFoundError(prompt_wav_path)
                generate_kwargs["prompt_text"] = prompt_text
                generate_kwargs["prompt_wav_path"] = prompt_wav_path
            if speaker_centroid is not None:
                generate_kwargs["speaker_centroid"] = speaker_centroid

            source_sample_rate = int(getattr(model, "sample_rate", 48000))
            output_sample_rate = int(request.get("output_sample_rate") or source_sample_rate)
            fade_out_ms = float(request.get("fade_out_ms") or 0.0)
            tail_silence_ms = float(request.get("tail_silence_ms") or 0.0)
            waveform = None
            audio_stats = {}
            attempted_seeds = []
            seed_attempt = 0

            for attempt in range(seed_retry_count + 1):
                seed_attempt = attempt
                seed = base_seed + attempt if base_seed is not None else None
                attempted_seeds.append(seed)
                if seed is not None:
                    self._seed_torch(torch, seed)

                with torch.inference_mode():
                    audio = model.generate(**generate_kwargs)

                candidate = self._to_numpy_audio(audio)
                candidate = self._resample_if_needed(
                    candidate,
                    source_sample_rate=source_sample_rate,
                    output_sample_rate=output_sample_rate,
                )
                candidate = self._apply_tail_processing(
                    candidate,
                    sample_rate=output_sample_rate,
                    fade_out_ms=fade_out_ms,
                    tail_silence_ms=tail_silence_ms,
                )
                audio_stats = self._audio_stats(candidate)
                waveform = candidate
                if not self._is_silent_audio(
                    audio_stats,
                    min_rms=min_rms,
                    min_nonzero_ratio=min_nonzero_ratio,
                ):
                    break
            else:
                waveform = None

            if waveform is None:
                audio_stats = {}
            if waveform is None or self._is_silent_audio(
                audio_stats,
                min_rms=min_rms,
                min_nonzero_ratio=min_nonzero_ratio,
            ):
                raise SilentAudioError(
                    "silent_audio "
                    f"rms={audio_stats.get('rms', 0.0):.8f} "
                    f"peak={audio_stats.get('peak', 0.0):.8f} "
                    f"nonzero_ratio={audio_stats.get('nonzero_ratio', 0.0):.8f}"
                )

            pcm = self._float_to_int16(waveform)

            Path(self.output_dir).mkdir(parents=True, exist_ok=True)
            pcm_path = os.path.join(self.output_dir, f"{request_id}.npy")
            np.save(pcm_path, pcm)

            generation_seconds = time.monotonic() - started_at
            duration_seconds = len(pcm) / max(float(output_sample_rate), 1.0)
            return {
                "request_id": request_id,
                "ok": True,
                "sample_rate": output_sample_rate,
                "pcm_path": pcm_path,
                "duration_seconds": duration_seconds,
                "generation_seconds": generation_seconds,
                "rtf": generation_seconds / duration_seconds if duration_seconds > 0 else None,
                "speaker_centroid_used": speaker_centroid is not None,
                "prompt_wav_used": bool(prompt_text and prompt_wav_path),
                "seed": attempted_seeds[seed_attempt] if attempted_seeds else None,
                "base_seed": base_seed,
                "seed_attempt": seed_attempt,
                "attempted_seeds": attempted_seeds,
                "seed_retry_count": seed_retry_count,
                "fade_out_ms": fade_out_ms,
                "tail_silence_ms": tail_silence_ms,
                "audio_rms": audio_stats.get("rms"),
                "audio_peak": audio_stats.get("peak"),
                "audio_nonzero_ratio": audio_stats.get("nonzero_ratio"),
            }
        except SilentAudioError as exc:
            return {
                "request_id": request_id,
                "ok": False,
                "reason": "silent_audio",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(limit=8),
            }
        except Exception as exc:
            return {
                "request_id": request_id,
                "ok": False,
                "reason": "synthesis_failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(limit=8),
            }

    def _load_model(self):
        if self.model is not None:
            return self.model

        import torch
        from bluemagpie import BlueMagpieModel
        from huggingface_hub import snapshot_download
        from transformers import PreTrainedTokenizerFast

        resolved_model_dir = self.model_dir
        tokenizer_path = os.path.join(resolved_model_dir, "tokenizer.json")
        if not os.path.exists(tokenizer_path):
            token_value = os.environ.get(self.hf_token_env) if self.hf_token_env else None
            download_kwargs = {"token": token_value} if token_value else {}
            resolved_model_dir = snapshot_download(self.hf_repo, **download_kwargs)
            tokenizer_path = os.path.join(resolved_model_dir, "tokenizer.json")

        tokenizer = PreTrainedTokenizerFast(tokenizer_file=tokenizer_path)
        device = None if (self.device or "").strip().lower() == "auto" else (self.device or None)
        self.model = BlueMagpieModel.from_local(
            resolved_model_dir,
            tokenizer=tokenizer,
            training=False,
            device=device,
        )
        self.torch = torch
        return self.model

    def _load_speaker_centroid(self, speaker_centroid_path: str | None):
        if not speaker_centroid_path:
            return None
        if not os.path.exists(speaker_centroid_path):
            raise FileNotFoundError(speaker_centroid_path)
        torch = self.torch
        try:
            return torch.load(speaker_centroid_path, map_location="cpu", weights_only=True)
        except TypeError:
            return torch.load(speaker_centroid_path, map_location="cpu")

    @staticmethod
    def _optional_int(value) -> int | None:
        if value is None:
            return None
        if isinstance(value, str) and value.strip() == "":
            return None
        return int(value)

    @staticmethod
    def _bool_setting(value, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, str):
            stripped = value.strip().lower()
            if stripped in {"1", "true", "yes", "on"}:
                return True
            if stripped in {"0", "false", "no", "off", ""}:
                return False
        return bool(value)

    @staticmethod
    def _seed_torch(torch, seed: int) -> None:
        torch.manual_seed(seed)
        if hasattr(torch, "cuda") and torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)

    @staticmethod
    def _to_numpy_audio(audio) -> np.ndarray:
        if hasattr(audio, "detach"):
            audio = audio.detach().cpu().numpy()
        waveform = np.asarray(audio, dtype=np.float32).squeeze()
        if waveform.ndim > 1:
            waveform = waveform[0]
        return waveform

    @staticmethod
    def _resample_if_needed(
        waveform: np.ndarray,
        *,
        source_sample_rate: int,
        output_sample_rate: int,
    ) -> np.ndarray:
        if source_sample_rate == output_sample_rate:
            return waveform.astype(np.float32, copy=False)
        try:
            import librosa

            return librosa.resample(
                waveform.astype(np.float32, copy=False),
                orig_sr=source_sample_rate,
                target_sr=output_sample_rate,
            )
        except Exception:
            if waveform.size == 0:
                return waveform.astype(np.float32, copy=False)
            duration_seconds = waveform.size / max(float(source_sample_rate), 1.0)
            output_len = max(1, int(round(duration_seconds * output_sample_rate)))
            old_x = np.linspace(0.0, 1.0, num=waveform.size, endpoint=False)
            new_x = np.linspace(0.0, 1.0, num=output_len, endpoint=False)
            return np.interp(new_x, old_x, waveform).astype(np.float32)

    @staticmethod
    def _apply_tail_processing(
        waveform: np.ndarray,
        *,
        sample_rate: int,
        fade_out_ms: float,
        tail_silence_ms: float,
    ) -> np.ndarray:
        waveform = np.asarray(waveform, dtype=np.float32)
        if waveform.size == 0:
            return waveform.astype(np.float32, copy=False)

        fade_samples = max(0, int(round(sample_rate * max(fade_out_ms, 0.0) / 1000.0)))
        silence_samples = max(0, int(round(sample_rate * max(tail_silence_ms, 0.0) / 1000.0)))
        if fade_samples == 0 and silence_samples == 0:
            return waveform.astype(np.float32, copy=False)

        processed = waveform.astype(np.float32, copy=True)
        if fade_samples > 0:
            fade_samples = min(fade_samples, processed.size)
            processed[-fade_samples:] *= np.linspace(
                1.0,
                0.0,
                num=fade_samples,
                endpoint=True,
                dtype=np.float32,
            )
        if silence_samples > 0:
            processed = np.concatenate(
                [processed, np.zeros(silence_samples, dtype=np.float32)]
            )
        return processed

    @staticmethod
    def _audio_stats(waveform: np.ndarray) -> dict:
        waveform = np.asarray(waveform, dtype=np.float32).reshape(-1)
        waveform = np.nan_to_num(waveform, nan=0.0, posinf=0.0, neginf=0.0)
        if waveform.size == 0:
            return {"rms": 0.0, "peak": 0.0, "nonzero_ratio": 0.0}
        abs_waveform = np.abs(waveform)
        return {
            "rms": float(np.sqrt(np.mean(waveform * waveform))),
            "peak": float(np.max(abs_waveform)),
            "nonzero_ratio": float(np.count_nonzero(abs_waveform > 1e-6) / waveform.size),
        }

    @staticmethod
    def _is_silent_audio(
        stats: dict,
        *,
        min_rms: float,
        min_nonzero_ratio: float,
    ) -> bool:
        return (
            float(stats.get("peak") or 0.0) <= 0.0
            or float(stats.get("rms") or 0.0) < min_rms
            or float(stats.get("nonzero_ratio") or 0.0) < min_nonzero_ratio
        )

    @staticmethod
    def _float_to_int16(waveform: np.ndarray) -> np.ndarray:
        waveform = np.asarray(waveform, dtype=np.float32)
        waveform = np.nan_to_num(waveform, nan=0.0, posinf=0.0, neginf=0.0)
        peak = float(np.max(np.abs(waveform))) if waveform.size else 0.0
        if peak > 1.0:
            waveform = waveform / peak
        waveform = np.clip(waveform, -1.0, 1.0)
        return (waveform * 32767.0).astype(np.int16)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BlueMagpie TTS JSONL worker")
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--hf-repo", default="OpenFormosa/BlueMagpie-TTS")
    parser.add_argument("--hf-token-env", default="HF_TOKEN")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def run_jsonl_loop(worker: BlueMagpieWorker, input_buffer, output_buffer) -> None:
    for raw_line in input_buffer:
        line = raw_line.decode("utf-8").strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            if request.get("command") == "shutdown":
                break
            if request.get("command") == "warmup":
                response = worker.warmup(request)
            else:
                response = worker.synthesize(request)
        except Exception as exc:
            response = {
                "request_id": None,
                "ok": False,
                "reason": "bad_request",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        response_line = json.dumps(response, ensure_ascii=False) + "\n"
        output_buffer.write(response_line.encode("utf-8"))
        output_buffer.flush()


def main() -> int:
    args = _parse_args()
    worker = BlueMagpieWorker(
        model_dir=args.model_dir,
        hf_repo=args.hf_repo,
        hf_token_env=args.hf_token_env,
        device=args.device,
        output_dir=args.output_dir,
    )

    run_jsonl_loop(worker, sys.stdin.buffer, sys.stdout.buffer)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
