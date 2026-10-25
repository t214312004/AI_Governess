"""Opt-in, sequential paired API benchmark; all recordings/results stay private.

Run from ai_voice_assistant. Without --run, only prepares the manifest.
Historical ASR sidecars are comparison references, NOT human ground truth.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import random
import re
import sys
import time
from unittest.mock import patch
import unicodedata
import wave

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
os.environ.setdefault("AI_GOVERNESS_DISABLE_LOGGING", "1")

import httpx
import numpy as np

from config import config
from utils.gemini_audio import (GeminiAPIError, estimated_cost, read_key_file,
    resolve_api_key, transcribe_wav, wav_bytes, STT_MODEL, TRANSCRIPTION_PROMPT)

HTTP_CLIENT = httpx.Client


def normalize(text):
    return "".join(c.lower() for c in unicodedata.normalize("NFKC", text)
                   if not c.isspace() and not unicodedata.category(c).startswith("P"))


def edit_distance(left, right):
    row = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        nxt = [i]
        for j, b in enumerate(right, 1):
            nxt.append(min(nxt[-1] + 1, row[j] + 1, row[j-1] + (a != b)))
        row = nxt
    return row[-1]


def read_audio(path):
    with wave.open(str(path), "rb") as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (16000, 1, 2):
            raise ValueError("Expected mono 16 kHz PCM16 WAV")
        return np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32) / 32768


def prepare_manifest(output, speech_count=20):
    rng = random.Random(20261018)
    groups = [[], [], [], []]
    for path in sorted((APP / "whisper_audio_archive").glob("*.wav")):
        try:
            with wave.open(str(path), "rb") as source:
                duration = source.getnframes() / source.getframerate()
                if source.getframerate() != 16000 or source.getnchannels() != 1 or source.getsampwidth() != 2:
                    continue
            if not 1 <= duration <= 60:
                continue
            sidecar = path.with_suffix(".txt")
            raw = sidecar.read_text(encoding="utf-8-sig") if sidecar.exists() else ""
            parts = re.split(r"(?m)^transcript:\s*\n", raw, maxsplit=1)
            reference = parts[1].strip() if len(parts) == 2 else ""
            group = next((i for i, high in enumerate((4, 8, 15, 60)) if duration <= high), 3)
            groups[group].append({"path": str(path.resolve()), "duration_s": duration,
                "reference": reference, "reference_kind": "unverified_historical_asr",
                "category": ("short", "medium", "long", "extended")[group]})
        except (wave.Error, EOFError, UnicodeError):
            continue
    for group in groups:
        rng.shuffle(group)
    chosen = []
    while len(chosen) < speech_count and any(groups):
        for group in groups:
            if group and len(chosen) < speech_count:
                chosen.append(group.pop())
    for index, row in enumerate(chosen):
        row["sample_id"] = f"speech_{index+1:02d}"
    generated = output / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    t = np.arange(32000) / 16000
    negatives = {
        "silence": np.zeros(32000),
        "noise": np.random.default_rng(42).normal(0, .006, 32000),
        "hum": .01 * np.sin(2 * np.pi * 60 * t),
        "clicks": np.where(np.arange(32000) % 4000 < 4, .08, 0),
    }
    for name, audio in negatives.items():
        path = generated / f"{name}.wav"
        path.write_bytes(wav_bytes(audio))
        chosen.append({"sample_id": "negative_" + name, "path": str(path.resolve()),
            "duration_s": 2, "reference": "", "reference_kind": "known_synthetic_non_speech",
            "category": "negative"})
    for row in chosen:
        row["sha256"] = hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest()
    (output / "manifest.json").write_text(json.dumps(chosen, ensure_ascii=False, indent=2), encoding="utf-8")
    return chosen


def summarize(records):
    result = {}
    for backend in ("groq", "gemini"):
        rows = [r for r in records if r["backend"] == backend]
        success = [r for r in rows if r["success"]]
        speech = [r for r in success if r["category"] != "negative"]
        refs = [r for r in speech if r["reference_chars"]]
        result[backend] = {
            "calls": len(rows), "success": len(success),
            "p50_ms": float(np.percentile([r["elapsed_ms"] for r in success], 50)) if success else None,
            "p95_ms": float(np.percentile([r["elapsed_ms"] for r in success], 95)) if success else None,
            "speech_p50_ms": float(np.percentile([r["elapsed_ms"] for r in speech], 50)) if speech else None,
            "speech_p95_ms": float(np.percentile([r["elapsed_ms"] for r in speech], 95)) if speech else None,
            "historical_reference_cer_NOT_accuracy": sum(r["reference_edits"] for r in refs) / sum(r["reference_chars"] for r in refs) if refs else None,
            "negative_nonempty": sum(bool(r["text"]) for r in success if r["category"] == "negative"),
            "negative_calls": sum(r["category"] == "negative" for r in rows),
            "network_attempts": sum(r["network_attempts"] for r in rows),
            "estimated_cost_usd": sum(r["estimated_cost_usd"] for r in rows),
            "error_counts": dict(Counter(r["error"] for r in rows if not r["success"])),
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Explicitly allow paid API requests")
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--speech-count", type=int, default=20)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--max-attempts", type=int, default=320)
    parser.add_argument("--max-cost-usd", type=float, default=1.0)
    parser.add_argument("--min-groq-interval", type=float, default=8.0,
        help="Seconds between Groq utterances; excludes scheduler wait from STT time")
    args = parser.parse_args()
    if not 1 <= args.speech_count <= 20 or not 1 <= args.repeats <= 5:
        parser.error("speech-count must be 1..20; repeats must be 1..5")
    output = (args.output or APP / "logs" / "audio_benchmark" / datetime.now().strftime("%Y%m%d_%H%M%S")).resolve()
    if not output.is_relative_to((APP / "logs" / "audio_benchmark").resolve()):
        parser.error("Output must stay under private logs/audio_benchmark")
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else prepare_manifest(output, args.speech_count)
    print(json.dumps({"output": str(output), "samples": len(manifest), "requested_calls": len(manifest)*2*args.repeats, "run": args.run}), flush=True)
    if not args.run:
        return
    from core.transcriber import GroqWhisperTranscriber
    groq = config.get("whisper", "groq", default={}) or {}
    gate = groq.get("confidence_gate", {}) or {}
    groq_engine = GroqWhisperTranscriber(api_key=groq.get("api_key"),
        api_key_env=groq.get("api_key_env", "GROQ_API_KEY"), model=groq.get("model", "whisper-large-v3"),
        api_url=groq.get("api_url", "https://api.groq.com/openai/v1/audio/transcriptions"),
        timeout_seconds=groq.get("timeout_seconds", 30),
        language=config.get("whisper", "language", default="zh"),
        initial_prompt=config.get("whisper", "initial_prompt", default="以下是繁體中文語音內容的逐字稿。"),
        **{"confidence_gate_"+k: v for k, v in gate.items() if k in ("enabled", "avg_logprob_threshold", "no_speech_prob_threshold", "temperature_threshold", "min_transcript_similarity")})
    gemini_key = read_key_file(args.key_file) if args.key_file else resolve_api_key(
        config.get("gemini", "api_key", default=""), config.get("gemini", "api_key_env", default="GEMINI_API_KEY"))
    records_path = output / "results.jsonl"
    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()] if records_path.exists() else []
    completed = {(r["sample_id"], r["round"], r["backend"]) for r in records}
    attempts = sum(r["network_attempts"] for r in records)
    cost = sum(r["estimated_cost_usd"] for r in records)
    consecutive_errors = 0
    last_groq_started = 0.0
    groq_cooldown_until = 0.0
    settings = {"model": STT_MODEL, "thinking_level": "low", "prompt": TRANSCRIPTION_PROMPT,
                "groq_model": groq_engine.model, "groq_confidence_gate": groq_engine.confidence_gate_enabled,
                "repeats": args.repeats, "normalization": "NFKC-lower-remove-unicode-punctuation-whitespace-v1",
                "reference_warning": "Historical ASR sidecars are unverified; reference CER is NOT accuracy."}
    settings_path = output / "settings.json"
    if settings_path.exists() and json.loads(settings_path.read_text(encoding="utf-8")) != settings:
        parser.error("Existing run has different settings; use a new output directory")
    settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output/"sessions.jsonl").open("a", encoding="utf-8") as sessions:
        sessions.write(json.dumps({"started_at": datetime.now().astimezone().isoformat(),
            "already_recorded": len(records), "min_groq_interval": args.min_groq_interval,
            "max_attempts": args.max_attempts, "max_cost_usd": args.max_cost_usd})+"\n")
    rng = random.Random(20261018)
    with records_path.open("a", encoding="utf-8") as target:
        for round_index in range(args.repeats):
            ordered = list(manifest)
            rng.shuffle(ordered)
            for sample in ordered:
                audio = read_audio(sample["path"])
                if hashlib.sha256(Path(sample["path"]).read_bytes()).hexdigest() != sample["sha256"]:
                    raise ValueError("A benchmark input changed after manifest creation")
                providers = ["groq", "gemini"]
                rng.shuffle(providers)
                for backend in providers:
                    identity = (sample["sample_id"], round_index+1, backend)
                    if identity in completed:
                        continue
                    # Reserve room for Groq's possible confidence-gate second attempt.
                    if attempts + 2 > args.max_attempts or cost >= args.max_cost_usd or consecutive_errors >= 3:
                        print(json.dumps({"stopped": True, "attempts": attempts, "estimated_cost_usd": cost, "consecutive_errors": consecutive_errors}), flush=True)
                        return
                    current = {"network_attempts": 0, "http_error": None, "retry_after": 0.0, "transport_error": None}
                    class CountingClient(HTTP_CLIENT):
                        def post(self, *a, **kw):
                            current["network_attempts"] += 1
                            try:
                                response = super().post(*a, **kw)
                            except httpx.HTTPError as exc:
                                current["transport_error"] = type(exc).__name__
                                raise
                            if response.status_code >= 400:
                                current["http_error"] = response.status_code
                                try:
                                    current["retry_after"] = float(response.headers.get("retry-after", 0))
                                except ValueError:
                                    pass
                            return response
                    text, usage, error = "", {}, None
                    scheduler_wait = 0.0
                    if backend == "groq":
                        scheduler_wait = max(0, last_groq_started + args.min_groq_interval - time.monotonic(),
                            groq_cooldown_until - time.monotonic())
                        if scheduler_wait:
                            time.sleep(scheduler_wait)
                        last_groq_started = time.monotonic()
                    started = time.perf_counter()
                    try:
                        if backend == "groq":
                            with patch("core.transcriber.httpx.Client", CountingClient):
                                text = groq_engine.transcribe(audio)
                            if current["http_error"]:
                                raise GeminiAPIError("groq_http_error", current["http_error"])
                            if current["transport_error"]:
                                raise GeminiAPIError("groq_transport_error")
                        else:
                            current["network_attempts"] = 1
                            with HTTP_CLIENT(timeout=30) as client:
                                text, usage = transcribe_wav(client, gemini_key, wav_bytes(audio))
                    except Exception as exc:
                        error = str(exc) if isinstance(exc, GeminiAPIError) else type(exc).__name__
                    elapsed = (time.perf_counter()-started)*1000
                    if current["http_error"] == 429:
                        groq_cooldown_until = time.monotonic() + max(10, current["retry_after"])
                    reference = normalize(sample["reference"])
                    estimated = estimated_cost(usage) if backend == "gemini" else max(10, sample["duration_s"])*.111/3600*current["network_attempts"]
                    row = {"sample_id": sample["sample_id"], "round": round_index+1,
                        "backend": backend, "category": sample["category"], "duration_s": sample["duration_s"],
                        "success": error is None, "error": error, "text": text,
                        "elapsed_ms": elapsed, "rtf": elapsed/1000/sample["duration_s"],
                        "scheduler_wait_ms": scheduler_wait*1000,
                        "retry_after_seconds": current["retry_after"],
                        "network_attempts": current["network_attempts"], "usage": usage,
                        "estimated_cost_usd": estimated, "reference_kind": sample["reference_kind"],
                        "reference_chars": len(reference), "reference_edits": edit_distance(reference, normalize(text))}
                    target.write(json.dumps(row, ensure_ascii=False)+"\n")
                    target.flush()
                    records.append(row)
                    attempts += current["network_attempts"]
                    cost += estimated
                    consecutive_errors = consecutive_errors+1 if error else 0
                    summary = summarize(records)
                    (output/"summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
                    if len(records) % 12 == 0 or error:
                        print(json.dumps({"finished": len(records), "of": len(manifest)*2*args.repeats,
                            "attempts": attempts, "estimated_cost_usd": round(cost, 5),
                            "last_error": error}), flush=True)
    print(json.dumps({"complete": True, "summary": summarize(records)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
