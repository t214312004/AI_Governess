"""Build a local-only audio review page. Never uploads audio or references."""
from __future__ import annotations

import argparse
from collections import Counter
import html
import json
import os
from pathlib import Path
from urllib.parse import quote


def load_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def audio_tag(path, output):
    try:
        url = quote(Path(os.path.relpath(path, output)).as_posix(), safe='/')
    except ValueError:  # Windows recordings may live on a different volume.
        url = Path(path).resolve().as_uri()
    return '<audio controls preload="none" src="' + html.escape(url, quote=True) + '"></audio>'


def make_review(stt_dir, tts_dir=None):
    samples = json.loads((stt_dir/"manifest.json").read_text(encoding="utf-8"))
    rows = load_rows(stt_dir/"results.jsonl")
    sections = []
    for sample in samples:
        sid = sample["sample_id"]
        provider_cells = []
        for provider in ("groq", "gemini"):
            chosen = [r for r in rows if r["sample_id"] == sid and r["backend"] == provider]
            counts = Counter(r["text"] for r in chosen if r["success"])
            texts = "".join('<p><b>' + str(count) + ' 次：</b>' + html.escape(text or "（空白）") + '</p>' for text, count in counts.items())
            errors = [r["error"] for r in chosen if not r["success"]]
            texts += "".join('<p class="warning">' + html.escape(error) + '</p>' for error in errors)
            if any(len(r["text"])/sample["duration_s"] > 40 for r in chosen):
                texts += '<p class="warning">候選異常：轉錄超過每秒 40 個字元，請回聽確認是否重複或幻覺。</p>'
            provider_cells.append('<div><h3>' + provider.title() + '</h3>' + texts + '</div>')
        sections.append('<section data-id="' + html.escape(sid) + '" data-hash="' + html.escape(sample["sha256"], quote=True) + '">'
            + '<h2>' + html.escape(sid) + ' · ' + f'{sample["duration_s"]:.2f}' + ' 秒</h2>'
            + audio_tag(Path(sample["path"]), stt_dir)
            + '<div class="columns">' + ''.join(provider_cells) + '</div>'
            + '<details><summary>未校對的舊 ASR 文字（僅供參考）</summary><p>' + html.escape(sample["reference"]) + '</p></details>'
            + '<label>聽音後自行填寫的標準答案<textarea aria-label="人工逐字稿"></textarea></label>'
            + '<label><input type="checkbox">我已聽音並校對這段文字</label></section>')
    if tts_dir:
        tts_rows = load_rows(tts_dir/"results.jsonl")
        sections.append('<h2>TTS 比較：相同文字，第一輪輸出</h2><p>請比較發音、自然度、台灣華語與漏字；下列速度由軟體量測，聽感需自行確認。</p>')
        for text_id in sorted({r["text_id"] for r in tts_rows}):
            selected = [r for r in tts_rows if r["text_id"] == text_id and r["round"] == 1]
            if not selected:
                continue
            cells = []
            for row in selected:
                body = audio_tag(tts_dir/row["file"], stt_dir) if row["success"] else html.escape(row.get("error", "failed"))
                cells.append('<div><h3>' + html.escape(row["backend"]) + '</h3>' + body + '</div>')
            sections.append('<section><h3>' + html.escape(selected[0]["text"]) + '</h3><div class="columns">' + ''.join(cells) + '</div></section>')
        voices = []
        for voice in ("Puck", "Charon", "Zephyr"):
            preview = tts_dir.parent/("gemini_tts_voice_"+voice)/"gemini_01_1.wav"
            if preview.is_file():
                voices.append('<div><h3>'+voice+'</h3>'+audio_tag(preview, stt_dir)+'</div>')
        kore = tts_dir/"gemini_01_1.wav"
        if kore.is_file():
            voices.insert(0, '<div><h3>Kore</h3>'+audio_tag(kore, stt_dir)+'</div>')
        if voices:
            sections.append('<section><h2>音色試聽</h2><p>相同文字：你好，我是愛管家。</p><div class="columns">'+''.join(voices)+'</div></section>')
    page = '''<!doctype html><html lang="zh-Hant"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; media-src 'self' file:;">
<title>Gemini／Groq 本機音訊比較</title><style>
body{font:17px/1.65 system-ui,sans-serif;background:#f5f2ed;color:#262d36;margin:0 auto;padding:32px;max-width:1100px}
section{background:white;border:1px solid #ddd;border-radius:14px;padding:24px;margin:20px 0}
h1,h2,h3{line-height:1.4}h2{font-size:22px}h3{font-size:18px}.columns{display:grid;grid-template-columns:1fr 1fr;gap:24px}
audio{width:100%;max-width:480px}textarea{display:block;width:100%;min-height:100px;margin:10px 0;font:inherit;box-sizing:border-box}
.warning{color:#9c332d}button{font:inherit;padding:12px 20px;cursor:pointer}details{margin:12px 0}p{overflow-wrap:anywhere}
@media(max-width:700px){body{padding:16px}.columns{grid-template-columns:1fr}}
</style><h1>Gemini／Groq 本機音訊比較</h1>
<p>這份頁面包含私人錄音，僅留在本機。舊逐字稿未經人工校對，與舊稿的差異不能當作準確率。
先回聽，再填寫人工答案並勾選確認；不預填標準答案，避免把舊 ASR 誤當真值。</p>
<button onclick="exportReferences()">匯出已校對的標準答案</button>
'''+''.join(sections)+'''
<script>function exportReferences(){const rows=[...document.querySelectorAll('section[data-id]')]
.filter(s=>s.querySelector('input').checked).map(s=>({sample_id:s.dataset.id,sha256:s.dataset.hash,
reference:s.querySelector('textarea').value,reference_kind:'human_verified'}));
const url=URL.createObjectURL(new Blob([JSON.stringify(rows,null,2)],{type:'application/json'}));
const a=document.createElement('a');a.href=url;a.download='human_references.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
</script></html>'''
    target = stt_dir/"review.html"
    target.write_text(page, encoding="utf-8")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stt_dir", type=Path)
    parser.add_argument("--tts-dir", type=Path)
    args = parser.parse_args()
    print(make_review(args.stt_dir.resolve(), args.tts_dir.resolve() if args.tts_dir else None))
