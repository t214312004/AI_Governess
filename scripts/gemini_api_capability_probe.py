"""Opt-in paid Gemini CLI/API probe; all generated media stays in tool_payloads.

Run with ai_voice_assistant/venv/Scripts/python.exe. No app config is changed.
Credentials are loaded in memory and passed to the child only via environment.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import html
import io
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "ai_voice_assistant"
sys.path.insert(0, str(APP))

import av
import httpx
import numpy as np

from tts.gemini_tts_engine import GeminiTTSEngine
from utils.gemini_audio import INTERACTIONS_URL, model_content, resolve_api_key
from utils.gemini_settings import audio_settings
from core.music_manager import atomic_json

TEXTS = {
    "short": "你好，我是愛管家。今天想聽輕鬆的音樂，還是一起安排接下來的行程？",
    "paragraph": (
        "忙了一整天，現在可以先讓自己休息一下。我會替你準備一段輕柔的背景音樂，"
        "用溫暖的鋼琴和緩慢的節奏，陪你整理今天的心情。你可以調整音量、切換不同風格，"
        "也可以隨時叫我暫停。等你準備好了，我們再一起看看明天的行程，"
        "把重要的事情依照順序安排好，讓生活多一點從容，也留一點時間給自己。"
    ),
}
MUSIC = [
    {
        "id": "mandarin_synthpop", "title": "把今天慢慢唱完", "genre": "Mandarin / Synth-pop",
        "model": "lyria-3.5",
        "prompt": (
            "Create an original approximately 60-second uplifting Mandarin Chinese synth-pop song, 108 BPM, "
            "warm clear female lead vocal with natural Taiwanese Mandarin pronunciation, bright synth arpeggios, "
            "rounded bass and light electronic drums. Sing the supplied lyrics exactly in order, without English "
            "words, extra lyrics, spoken introductions, or quoting an existing song. Structure: short instrumental "
            "intro, verse, chorus, repeat chorus once, brief resolved ending. Do not imitate any artist.\n"
            "[Verse]\n窗邊的雨慢慢停了\n桌上的茶還有餘溫\n愛管家陪我輕輕唱\n把今天慢慢唱完\n"
            "[Chorus]\n留一點時間給自己\n讓心跟著旋律呼吸\n明天還有新的風景\n今晚就安心在這裡"
        ),
        "acceptance": "約 60 秒（軟性）；中文女聲、108 BPM 左右、電子流行；指定八句歌詞依序演唱，副歌重複一次。",
    },
]

# The user auditioned the initial comparison and selected lyria-3.5 for all
# future music. Legacy Clip prompts remain documented in the saved evidence.
MUSIC.extend([{
    "id": "lofi_piano_35", "title": "雨夜書桌・Lyria 3.5", "genre": "Lo-fi / Chill",
    "model": "lyria-3.5",
    "prompt": (
        "請創作一首約 45 秒的原創 Lo-fi hip-hop 純音樂，適合下雨夜晚讀書。"
        "固定節奏約每分鐘 78 拍，四拍子。主奏是溫暖柔和的 Rhodes 電鋼琴，"
        "搭配圓潤低音、輕柔的 boom-bap 鼓與少量黑膠質感。"
        "開頭由電鋼琴先出現，四秒內加入鼓組，結尾輕柔收束。"
        "整首不要任何人聲、哼唱、歌詞或口白，不要模仿既有歌曲或歌手。"
    ),
    "acceptance": "約 45 秒（軟性）；Lo-fi、Rhodes／bass／soft drums；無任何人聲；78 BPM 附近。",
}, {
    "id": "acoustic_waltz_35", "title": "午後的小步舞・Lyria 3.5", "genre": "Acoustic / Waltz",
    "model": "lyria-3.5",
    "prompt": (
        "請創作一首約 45 秒的原創木吉他華爾滋純音樂。最重要條件是整曲明確維持 3/4 三拍子，"
        "每小節三拍，強弱弱、強弱弱，請不要變成四拍子的民謠。四分音符每分鐘約 100 拍。"
        "用尼龍弦古典木吉他指彈出溫暖、輕快且容易記住的旋律，大提琴撥奏標示每小節第一拍，"
        "其餘兩拍由輕柔吉他和弦回應，只有極輕的刷奏打擊樂。"
        "氛圍像晴天下午的台灣咖啡館。不要鋼琴、合成器、人聲、哼唱或口白。"
        "用完整和聲終止式與自然餘音結尾，不要突然切斷。不要模仿任何現有歌曲或音樂人。"
    ),
    "acceptance": "約 45 秒（軟性）；明確 3/4 強弱弱；100 BPM 左右；木吉他與大提琴；無人聲／鋼琴／synth。",
}])


def write_json(path, value):
    atomic_json(path,value)


def validate_output_directory(path):
    candidate=Path(path).resolve()
    if not any(candidate.is_relative_to(root.resolve()) for root in (ROOT/'tool_payloads',APP/'tool_payloads')):
        raise ValueError('Probe output must stay inside the ignored tool_payloads directories.')
    return candidate


def load_config():
    def merge(base, update):
        for key, value in update.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                merge(base[key], value)
            else:
                base[key] = value
        return base
    cfg = json.loads((APP / "config.default.json").read_text(encoding="utf-8-sig"))
    private = APP / "config.local.json"
    if private.exists():
        merge(cfg, json.loads(private.read_text(encoding="utf-8-sig")))
    return cfg


def audio_info(path):
    samples, peak, squares, count, rate, channels = 0, 0.0, 0.0, 0, 0, 0
    first_nonzero = None
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        codec = stream.codec_context.name
        for frame in container.decode(audio=0):
            rate, channels = frame.sample_rate, len(frame.layout.channels)
            array = frame.to_ndarray()
            if np.issubdtype(array.dtype, np.integer):
                values = array.astype(np.float64) / (np.iinfo(array.dtype).max + 1)
            else:
                values = array.astype(np.float64)
            peak = max(peak, float(np.max(np.abs(values))))
            squares += float(np.sum(values * values))
            count += values.size
            if first_nonzero is None and np.any(values):
                first_nonzero = samples / rate
            samples += frame.samples
    return {"duration_seconds": samples / rate, "sample_rate": rate,
            "channels": channels, "codec": codec, "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "peak": peak, "rms": (squares / count) ** .5,
            "first_nonzero_frame_seconds": first_nonzero}


def save_pcm(path, frames, rate=24000):
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(rate)
        target.writeframes(b"".join(np.asarray(f, dtype="<i2").tobytes() for f in frames))


def child_env(key):
    env = dict(os.environ)
    env["GEMINI_API_KEY"] = key
    # CLI's explicit key should not be superseded by a different inherited key.
    env.pop("GOOGLE_API_KEY", None)
    env.pop("GEMINI_ACCESS_TOKEN", None)
    env.pop("GEMINI_DEBUG",None)
    env.pop("DEBUG",None)
    return env


def redact(text, key):
    return str(text).replace(key, "[REDACTED]")


def run_cli(cli, args, key, timeout):
    result = subprocess.run([str(cli), "--no-interactive", *args], env=child_env(key),
                            capture_output=True, encoding="utf-8", errors="replace",
                            timeout=timeout)
    return {"exit_code": result.returncode,
            "stdout": redact(result.stdout, key), "stderr": redact(result.stderr, key)}


async def engine_tts(key, settings, text, path, streaming):
    # Independent operations avoid adding the app's inter-request queue to TTFA.
    engine = GeminiTTSEngine(api_key=key, sample_rate=24000,
                             settings={**settings, "max_retries": 0}, streaming=streaming)
    started = time.perf_counter()
    frames, first_pcm, first_nonzero = [], None, None
    try:
        async for chunk in engine.synthesize_stream(text):
            now = (time.perf_counter() - started) * 1000
            if first_pcm is None:
                first_pcm = now
            frame = np.asarray(chunk.pcm_data)
            if first_nonzero is None and np.any(frame):
                first_nonzero = now
            frames.append(frame.copy())
        elapsed = (time.perf_counter() - started) * 1000
        diag = engine.last_diagnostics
        result = {"success": diag.get("status") == "ok", "elapsed_ms": elapsed,
                  "first_pcm_ms": first_pcm, "first_nonzero_ms": first_nonzero,
                  "diagnostics": diag}
        if frames:
            save_pcm(path, frames)
        return result
    finally:
        await engine.aclose()


def direct_unary(key, payload, path):
    started = time.perf_counter()
    with httpx.Client(timeout=httpx.Timeout(120, connect=5)) as client:
        response = client.post(INTERACTIONS_URL, headers={"x-goog-api-key": key}, json=payload)
        headers_ms = (time.perf_counter() - started) * 1000
        if response.status_code != 200:
            return {"success": False, "http_status": response.status_code,
                    "elapsed_ms": headers_ms, "error": redact(response.text[:2000], key)}
        body = response.json()
        blocks = model_content(body, "audio")
        if not blocks:
            return {"success": False, "error": "missing_audio"}
        block = blocks[0]
        data = base64.b64decode(block["data"], validate=True)
        if data.startswith(b"RIFF"):
            path.write_bytes(data)
        else:
            save_pcm(path, [np.frombuffer(data, dtype="<i2")])
        elapsed = (time.perf_counter() - started) * 1000
        return {"success": True, "elapsed_ms": elapsed,
                "first_pcm_ms": elapsed, "first_nonzero_ms": elapsed,
                "usage": body.get("usage", {}), "mime_type": block.get("mime_type")}


async def probe_tts(args, cfg, key):
    settings = audio_settings("tts", cfg.get("tts", {}).get("gemini", {}))
    streaming = bool(cfg.get("pipeline_v2_5", {}).get("streaming_tts", False))
    arms = ["engine_current", "engine_unstyled", "rest_cli_payload", "cli_tts"]
    rows = []
    write_json(args.output / "tts_settings.json", {
        "settings": settings, "current_streaming": streaming, "texts": TEXTS,
        "repeats": args.repeats, "interval_seconds": args.interval,
        "arms": arms, "notes": "No playback device. First PCM means software availability, not acoustic onset. CLI and REST have identical dry-run bodies; engine_unstyled removes style but retains app schema."})
    last_start = 0.0
    for repeat in range(args.repeats):
        order = arms[repeat % len(arms):] + arms[:repeat % len(arms)]
        for text_id, text in TEXTS.items():
            prompt_path = args.output / f"tts_{text_id}.txt"
            prompt_path.write_text(text, encoding="utf-8")
            dry = run_cli(args.cli, ["tts", "-f", str(prompt_path), "--voice", settings["voice"],
                "--model", settings["model"], "--dry-run", "--output-format", "json"], key, 20)
            payload = json.loads(dry["stdout"])["request"]["body"]
            write_json(args.output / f"cli_tts_{text_id}_payload.json", payload)
            for arm in order:
                await asyncio.sleep(max(0, args.interval - (time.perf_counter() - last_start)))
                last_start = time.perf_counter()
                row = {"arm": arm, "text_id": text_id, "repeat": repeat + 1,
                       "text_chars": len(text), "utc": datetime.now(timezone.utc).isoformat()}
                path = args.output / f"{arm}_{text_id}_{repeat + 1}.wav"
                try:
                    if arm.startswith("engine"):
                        selected = settings if arm == "engine_current" else {**settings, "style": ""}
                        row.update(await engine_tts(key, selected, text, path, streaming))
                    elif arm == "rest_cli_payload":
                        row.update(direct_unary(key, payload, path))
                    else:
                        started = time.perf_counter()
                        result = run_cli(args.cli, ["tts", "-f", str(prompt_path),
                            "--voice", settings["voice"], "--model", settings["model"],
                            "--out", str(path), "--output-format", "json"], key, 120)
                        elapsed = (time.perf_counter() - started) * 1000
                        row.update(result, success=result["exit_code"] == 0 and path.exists(),
                                   elapsed_ms=elapsed, first_pcm_ms=elapsed, first_nonzero_ms=elapsed)
                    if path.exists():
                        row.update(audio=audio_info(path), artifact=path.name)
                except Exception as exc:
                    row.update(success=False, error_type=type(exc).__name__,
                               error=redact(str(exc), key))
                rows.append(row)
                write_json(args.output / "tts_results.json", rows)
                print(json.dumps({k: row.get(k) for k in ("arm", "text_id", "repeat", "success", "first_nonzero_ms", "elapsed_ms", "error")}, ensure_ascii=False), flush=True)
                if row.get("http_status") in (401, 402, 403, 429) or row.get("diagnostics", {}).get("http_status") in (401, 402, 403, 429):
                    raise RuntimeError("TTS stopped after authentication/billing/rate-limit error; inspect saved result")
    summary = []
    for text_id in TEXTS:
        for arm in arms:
            group = [r for r in rows if r["arm"] == arm and r["text_id"] == text_id]
            good = [r for r in group if r["success"]]
            item = {"text_id": text_id, "arm": arm, "attempts": len(group), "successes": len(good)}
            for metric in ("first_nonzero_ms", "elapsed_ms"):
                values = [r[metric] for r in good if r.get(metric) is not None]
                if values:
                    item[metric] = {"median": statistics.median(values), "min": min(values), "max": max(values)}
            if good:
                item["duration_median_seconds"] = statistics.median(r["audio"]["duration_seconds"] for r in good)
            summary.append(item)
    write_json(args.output / "tts_summary.json", summary)


def probe_music(args, key):
    result_path = args.output / "music_results.json"
    results = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else []
    completed = {r["id"] for r in results if r.get("success")}
    for spec in MUSIC:
        if spec["id"] in completed:
            continue
        path = args.output / (spec["id"] + ".mp3")
        if path.exists():
            raise RuntimeError("Use a fresh output directory; existing music is never overwritten")
        prompt_path = args.output / (spec["id"] + "_prompt.txt")
        prompt_path.write_text(spec["prompt"], encoding="utf-8")
        started = time.perf_counter()
        row = dict(spec, utc=datetime.now(timezone.utc).isoformat())
        try:
            result = run_cli(args.cli, ["music", "-f", str(prompt_path), "--model", spec["model"],
                "--out", str(path), "--output-format", "json", "--timeout", "180s"], key, 200)
            row.update(result, elapsed_ms=(time.perf_counter() - started) * 1000,
                       success=result["exit_code"] == 0 and path.exists())
            if path.exists():
                row.update(audio=audio_info(path), artifact=path.name)
        except Exception as exc:
            row.update(success=False, error_type=type(exc).__name__, error=redact(str(exc), key))
        results.append(row)
        write_json(args.output / "music_results.json", results)
        print(json.dumps({k: row.get(k) for k in ("id", "model", "success", "elapsed_ms", "audio", "stderr", "error")}, ensure_ascii=False), flush=True)
        if not row["success"]:
            break
    write_listening_page(args.output, results)


def write_listening_page(output, rows):
    cards = []
    for row in rows:
        if not row.get("success"):
            continue
        cards.append(f'''<article data-genre="{html.escape(row['genre'])}">
<div class="tag">{html.escape(row['genre'])} · {row['audio']['duration_seconds']:.1f} 秒</div>
<h2>{html.escape(row['title'])}</h2>
<p>{html.escape(row['acceptance'])}</p>
<audio controls preload="metadata" src="{html.escape(row['artifact'])}"></audio>
<p class="muted">生成 {row['elapsed_ms']/1000:.2f} 秒 · {html.escape(row['model'])}</p>
<details><summary>指定內容與完整 prompt</summary><pre>{html.escape(row['prompt'])}</pre></details>
<label>你的試聽評語<textarea data-review="{html.escape(row['id'])}" placeholder="風格符合嗎？有沒有不該有的人聲？歌詞、音質、節奏如何？"></textarea></label>
<a href="{html.escape(row['artifact'])}" download>下載 MP3</a></article>''')
    page = '''<!doctype html><html lang="zh-Hant"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Gemini 音樂實測試聽</title>
<style>:root{color-scheme:dark;font:17px/1.6 system-ui;background:#101820;color:#edf2f5}body{max-width:1050px;margin:auto;padding:30px 20px}h1{font-size:2rem;margin-bottom:4px}h2{margin:10px 0}p{margin:10px 0}.intro{max-width:800px;color:#bacad5}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:20px;margin-top:25px}article{background:#1d2b36;border:1px solid #38505e;border-radius:18px;padding:22px}audio,textarea{width:100%;margin:12px 0}audio{height:54px}.tag,a{color:#78d9c7}.muted{font-size:.85rem;color:#abc1cc}pre{white-space:pre-wrap;font:14px/1.6 system-ui}summary{cursor:pointer;padding:12px 0}textarea{box-sizing:border-box;min-height:110px;background:#0c151e;color:#eef;border:1px solid #68808e;border-radius:8px;padding:10px}button,select{min-height:44px;padding:8px 16px;background:#263f4d;color:#fff;border:1px solid #68808e;border-radius:8px;margin:10px 10px 0 0}label{display:block;margin-top:15px}article[hidden]{display:none}</style>
<h1>Gemini 音樂實測試聽</h1><p class="intro">這些曲目都是本次透過官方 gemini-api CLI 實際生成。新增的 Lyria 3.5 版本已標在曲名，可按風格篩選比較。請按播放試聽；一次播放一首，初始音量為 60%。這是獨立試聽頁，正式曲庫請由主畫面的音符圖示開啟。</p>
<p class="intro">「有成功產生音檔」已驗證；旋律好不好聽、指定風格與中文歌詞是否滿意，請由你評定。評語只儲存在這個瀏覽器的 localStorage。</p>
<select id="genre" aria-label="風格篩選"><option value="">全部風格</option></select><button id="export">匯出試聽評語</button><main class="grid">''' + "".join(cards) + '''</main><script>
const audios=[...document.querySelectorAll('audio')];
audios.forEach(a=>{a.volume=.6;a.addEventListener('play',()=>audios.forEach(b=>{if(a!==b)b.pause()}))});
const genre=document.getElementById('genre');
[...new Set([...document.querySelectorAll('article')].map(a=>a.dataset.genre))].forEach(g=>genre.add(new Option(g,g)));
genre.addEventListener('change',()=>document.querySelectorAll('article').forEach(a=>a.hidden=!!genre.value&&a.dataset.genre!==genre.value));
document.querySelectorAll('textarea').forEach(t=>{t.value=localStorage.getItem('gemini-audition-'+t.dataset.review)||'';t.addEventListener('input',()=>localStorage.setItem('gemini-audition-'+t.dataset.review,t.value))});
document.getElementById('export').onclick=()=>{const data=Object.fromEntries([...document.querySelectorAll('textarea')].map(t=>[t.dataset.review,t.value]));const u=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download='gemini-music-listening-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)};
</script></html>'''
    (output / "listen.html").write_text(page, encoding="utf-8")


def review_music(args, key):
    rows = json.loads((args.output / "music_results.json").read_text(encoding="utf-8"))
    write_listening_page(args.output, rows)
    review_path = args.output / "music_blind_reviews.json"
    reviews = json.loads(review_path.read_text(encoding="utf-8")) if review_path.exists() else []
    done = {r["id"] for r in reviews if r.get("http_status") == 200}
    # Blind description: the reviewer does not receive the requested style or lyrics.
    instruction = (
        "請獨立分析附上的音樂。不要假設作者意圖。使用繁體中文回答並盡量精確。"
        "描述：主要樂器、曲風、情緒、估計 BPM 與可能拍號（不確定必須說不確定）、"
        "是否有人聲及其語言性別、能辨識的完整歌詞依序轉錄、結尾是否突然截斷、"
        "明顯音質問題。節拍與樂器只是聽感估計，不可宣稱量測。"
    )
    for row in rows:
        if not row.get("success") or row["id"] in done:
            continue
        started = time.perf_counter()
        payload = {"model": "gemini-3.8-flash", "store": False,
            "input": [{"type": "text", "text": instruction}, {"type": "audio", "mime_type": "audio/mpeg",
                "data": base64.b64encode((args.output / row["artifact"]).read_bytes()).decode("ascii")}],
            "generation_config": {"thinking_level": "low", "max_output_tokens": 3000}}
        with httpx.Client(timeout=120) as client:
            response = client.post(INTERACTIONS_URL, headers={"x-goog-api-key": key}, json=payload)
        review = {"id": row["id"], "reviewer_model": "gemini-3.8-flash", "blind": True,
                  "http_status": response.status_code, "elapsed_ms": (time.perf_counter()-started)*1000}
        if response.status_code == 200:
            body = response.json()
            review.update(text="\n".join(b.get("text", "") for b in model_content(body, "text")),
                          usage=body.get("usage", {}))
        else:
            review["error"] = redact(response.text[:2000], key)
        reviews.append(review)
        write_json(args.output / "music_blind_reviews.json", reviews)
        print(json.dumps(review, ensure_ascii=False), flush=True)


def main():
    # Windows console defaults (e.g. cp950) cannot encode every model response.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Explicitly allow paid calls")
    parser.add_argument("--phase", choices=("tts", "music", "review", "all"), default="all")
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--interval", type=float, default=8)
    args = parser.parse_args()
    if not args.run:
        parser.error("Pass --run to make paid API calls")
    if not 1 <= args.repeats <= 10 or args.interval < 0:
        parser.error("Invalid repeat count or interval")
    try:
        args.output=validate_output_directory(args.output)
    except ValueError as exc:
        parser.error(str(exc))
    args.cli = args.cli.resolve(strict=True)
    args.output.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    credential = cfg.get("gemini", {})
    key = resolve_api_key(credential.get("api_key", ""), credential.get("api_key_env", "GEMINI_API_KEY"))
    if args.phase in ("music", "all"):
        probe_music(args, key)
    if args.phase == "review":
        review_music(args, key)
    if args.phase in ("tts", "all"):
        if (args.output / "tts_results.json").exists():
            parser.error("Use a fresh TTS output directory")
        asyncio.run(probe_tts(args, cfg, key))


if __name__ == "__main__":
    main()
