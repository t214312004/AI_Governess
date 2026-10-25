"""Explicit paid TTS test with fixed, non-private utterances and PCM timing."""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
import random
import sys
import time
import wave

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
os.environ.setdefault("AI_GOVERNESS_DISABLE_LOGGING", "1")

import httpx
import numpy as np

from config import config
from tts.edge_tts_engine import EdgeTTSEngine
from utils.gemini_audio import (INTERACTIONS_URL, GeminiAPIError, estimated_cost,
    resolve_api_key, sse_messages, tts_payload)

TEXTS = (
    "你好，我是愛管家。",
    "好的，我先暫停，等你準備好再繼續。",
    "提醒你，今天下午三點半要開會，請提前十分鐘準備。",
    "這筆費用是一千兩百三十四元，不是一萬兩千元。",
    "請開啟 Google AI Studio，檢查 Gemini API key 是否已經設定完成。",
    "我們會比較 Groq Whisper、Gemini Flash 和本機語音辨識的速度。",
    "你想先聽故事，還是先玩遊戲？",
    "別急，我們可以一步一步來。先按下開始，再選擇你喜歡的顏色。",
    "API、Python、PowerShell 和 GitHub，這些英文名稱請保留原本的發音。",
    "窗外開始下雨了，出門前記得帶傘。回來以後，先把濕掉的雨傘放在門口，再換上舒服的拖鞋。我會在這裡等你。",
)


def save_audio(path, frames, sample_rate=24000):
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        for frame in frames:
            target.writeframesraw(np.asarray(frame, dtype="<i2").tobytes())


def gemini_speech(key, text, voice, style):
    started = time.perf_counter()
    first_chunk = first_nonzero = None
    frames, carry, usage, completed = [], b"", {}, False
    event_types = set()
    with httpx.Client(timeout=45) as client:
        with client.stream("POST", INTERACTIONS_URL, headers={"x-goog-api-key": key},
                json=tts_payload(text, voice=voice, style=style, stream=True)) as response:
            if response.status_code != 200:
                try:
                    retry_after = float(response.headers.get("retry-after", 0))
                except ValueError:
                    retry_after = 0
                raise GeminiAPIError("http_error", response.status_code, retry_after)
            for event in sse_messages(response.iter_lines()):
                event_type = event.get("event_type") or event.get("type", "")
                event_types.add(event_type)
                interaction = event.get("interaction", {})
                usage = event.get("usage") or interaction.get("usage") or usage
                if event_type == "error":
                    raise GeminiAPIError("stream_error")
                if event_type == "interaction.completed" or interaction.get("status") == "completed":
                    completed = True
                delta = event.get("delta", {})
                if event_type != "step.delta" or delta.get("type") != "audio":
                    continue
                carry += base64.b64decode(delta.get("data", ""), validate=True)
                length = len(carry) - len(carry) % 2
                if not length:
                    continue
                frame = np.frombuffer(carry[:length], dtype="<i2").copy()
                carry = carry[length:]
                now = (time.perf_counter()-started)*1000
                if first_chunk is None:
                    first_chunk = now
                if first_nonzero is None and np.any(frame):
                    first_nonzero = now
                frames.append(frame)
    if carry or not frames or not completed:
        raise GeminiAPIError("incomplete_audio_stream")
    return frames, {"first_pcm_ms": first_chunk, "first_nonzero_ms": first_nonzero,
        "elapsed_ms": (time.perf_counter()-started)*1000, "usage": usage,
        "event_types": sorted(event_types), "estimated_cost_usd": estimated_cost(usage, tts=True)}


async def edge_speech(text):
    started = time.perf_counter()
    first_chunk = first_nonzero = None
    frames = []
    engine = EdgeTTSEngine(voice=config.get("tts", "voice", default="zh-TW-HsiaoChenNeural"),
        sample_rate=24000, rate=config.get("tts", "rate", default="+0%"),
        volume=config.get("tts", "volume", default="+0%"), streaming_decode=True)
    async for chunk in engine.synthesize_stream(text):
        frame = chunk.pcm_data
        now = (time.perf_counter()-started)*1000
        if first_chunk is None:
            first_chunk = now
        if first_nonzero is None and np.any(frame):
            first_nonzero = now
        frames.append(frame)
    if not frames:
        raise RuntimeError("empty_edge_audio")
    return frames, {"first_pcm_ms": first_chunk, "first_nonzero_ms": first_nonzero,
        "elapsed_ms": (time.perf_counter()-started)*1000, "usage": {}, "estimated_cost_usd": 0}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path, default=APP/"logs/audio_benchmark/gemini_tts_20261018")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--text-count", type=int, default=10)
    parser.add_argument("--voice", default="Kore")
    parser.add_argument("--retry-failed", action="store_true",
        help="Append new attempts for failed identities; retain all original errors")
    parser.add_argument("--min-gemini-interval", type=float, default=8.0)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 3 or not 1 <= args.text_count <= len(TEXTS):
        parser.error("Invalid repeat or text count")
    output = args.output.resolve()
    if not output.is_relative_to((APP/"logs/audio_benchmark").resolve()):
        parser.error("Output must stay under private logs/audio_benchmark")
    output.mkdir(parents=True, exist_ok=True)
    print(json.dumps({"run": args.run, "calls": args.repeats*args.text_count*2, "output": str(output)}), flush=True)
    if not args.run:
        return
    key = resolve_api_key(config.get("gemini", "api_key", default=""),
        config.get("gemini", "api_key_env", default="GEMINI_API_KEY"))
    style = "以自然、溫暖的台灣華語朗讀，速度適中，英文照原文發音。"
    settings = {"model": "gemini-3.8-flash-tts", "voice": args.voice, "style": style,
        "edge_voice": config.get("tts", "voice"), "edge_rate": config.get("tts", "rate", default="+0%"),
        "edge_volume": config.get("tts", "volume", default="+0%"), "sample_rate": 24000,
        "stream": True, "texts": list(TEXTS[:args.text_count]), "repeats": args.repeats}
    settings_path = output/"settings.json"
    if settings_path.exists() and json.loads(settings_path.read_text(encoding="utf-8")) != settings:
        parser.error("Existing run has different settings; use a new output directory")
    settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    path = output/"results.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    done = {(r["text_id"], r["round"], r["backend"]) for r in rows
            if r["success"] or not args.retry_failed}
    consecutive_errors = {"edge": 0, "gemini": 0}
    last_gemini_started = 0.0
    cooldown_until = 0.0
    rng = random.Random(20261018)
    with path.open("a", encoding="utf-8") as target:
        for repeat in range(args.repeats):
            order = list(enumerate(TEXTS[:args.text_count], 1))
            rng.shuffle(order)
            for text_id, text in order:
                providers = ["edge", "gemini"]
                rng.shuffle(providers)
                for backend in providers:
                    if (text_id, repeat+1, backend) in done:
                        continue
                    if len(rows) >= 80 or sum(r["estimated_cost_usd"] for r in rows) >= 1.0:
                        print(json.dumps({"stopped": True, "reason": "request_or_cost_budget"}), flush=True)
                        return
                    row = {"text_id": text_id, "round": repeat+1, "backend": backend,
                           "text": text, "voice": args.voice if backend == "gemini" else config.get("tts", "voice"),
                           "success": False, "estimated_cost_usd": 0}
                    if backend == "gemini":
                        wait = max(0, last_gemini_started+args.min_gemini_interval-time.monotonic(),
                                   cooldown_until-time.monotonic())
                        if wait:
                            await asyncio.sleep(wait)
                        last_gemini_started = time.monotonic()
                        row["scheduler_wait_ms"] = wait*1000
                    try:
                        frames, metrics = await asyncio.to_thread(gemini_speech, key, text, args.voice, style) if backend == "gemini" else await edge_speech(text)
                        filename = f"{backend}_{text_id:02d}_{repeat+1}.wav"
                        save_audio(output/filename, frames)
                        row.update(metrics, success=True, file=filename,
                            audio_seconds=sum(len(frame) for frame in frames)/24000)
                    except Exception as exc:
                        row["error"] = str(exc) if isinstance(exc, GeminiAPIError) else type(exc).__name__
                        if isinstance(exc, GeminiAPIError) and exc.status_code == 429:
                            cooldown_until = time.monotonic()+max(60, exc.retry_after)
                            row["retry_after_seconds"] = exc.retry_after
                    rows.append(row)
                    consecutive_errors[backend] = 0 if row["success"] else consecutive_errors[backend]+1
                    target.write(json.dumps(row, ensure_ascii=False)+"\n")
                    target.flush()
                    print(json.dumps({"finished": len(rows), "backend": backend,
                        "success": row["success"], "first_nonzero_ms": row.get("first_nonzero_ms"),
                        "error": row.get("error")}), flush=True)
                    if consecutive_errors[backend] >= 3:
                        print(json.dumps({"stopped": True, "reason": "three_provider_failures", "backend": backend}), flush=True)
                        return
    summary = {}
    for backend in ("edge", "gemini"):
        selected = [r for r in rows if r["backend"] == backend]
        success = [r for r in selected if r["success"]]
        summary[backend] = {"calls": len(selected), "success": len(success),
            "estimated_cost_usd": sum(r["estimated_cost_usd"] for r in selected)}
        for metric in ("first_pcm_ms", "first_nonzero_ms", "elapsed_ms"):
            values = [r[metric] for r in success if r.get(metric) is not None]
            summary[backend][metric] = {"p50": float(np.percentile(values, 50)), "p95": float(np.percentile(values, 95))} if values else None
    (output/"summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
