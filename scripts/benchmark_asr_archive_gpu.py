"""GPU-only, offline comparison on immutable recorded utterances.

Historical ASR sidecars are comparison material, never ground truth. Private
results default to ai_voice_assistant/asr_eval_outputs (gitignored). Workers
load one model at a time in separate processes, without changing app config.
"""
from __future__ import annotations

import argparse
import csv
import ctypes
from datetime import datetime
import hashlib
import html
import json
import os
from pathlib import Path
import random
import re
import statistics
import subprocess
import sys
import threading
import time
import unicodedata
import wave

APP_DIR = Path(__file__).resolve().parents[1] / 'ai_voice_assistant'
sys.path.insert(0, str(APP_DIR))


def archive_rows(root):
    rows = []
    for path in sorted(root.glob('*.wav')):
        with wave.open(str(path), 'rb') as audio:
            seconds = audio.getnframes() / audio.getframerate()
            rate, channels, width = audio.getframerate(), audio.getnchannels(), audio.getsampwidth()
        sidecar = path.with_suffix('.txt')
        text = sidecar.read_text(encoding='utf-8').partition('transcript:\n')[2].strip() if sidecar.exists() else ''
        rows.append({'file': path.name, 'audio_seconds': seconds, 'sample_rate': rate,
                     'channels': channels, 'sample_width': width, 'historical_asr': text})
    return rows


def spread(rows, count):
    if len(rows) <= count:
        return rows
    if count == 1:
        return [rows[len(rows) // 2]]
    return [rows[round(i * (len(rows) - 1) / (count - 1))] for i in range(count)]


def select_samples(rows, count=40):
    selected = {}
    def add(candidates, quota, category):
        for row in spread([r for r in candidates if r['file'] not in selected], quota):
            if len(selected) >= count:
                break
            selected[row['file']] = dict(row, selection_category=category)
    add([r for r in rows if re.search(r'[A-Za-z]{2,}', r['historical_asr'])], 10, 'historical_latin')
    add(rows[-8:], 6, 'recent')
    add([r for r in rows if r['audio_seconds'] < 3], 6, 'short')
    add([r for r in rows if r['audio_seconds'] >= 30], 4, 'long')
    add([r for r in rows if not r['historical_asr']], 4, 'historical_empty')
    add([r for r in rows if '系統無法辨識' in r['historical_asr']], 4, 'historical_noise_placeholder')
    add(rows, count - len(selected), 'general')
    return list(selected.values())


def normalized(text):
    return ''.join(c.lower() for c in unicodedata.normalize('NFKC', text)
                   if not unicodedata.category(c).startswith(('P', 'Z')) and not c.isspace())


def percentile(values, q):
    values = sorted(values)
    position = (len(values) - 1) * q
    lo, hi = int(position), min(int(position) + 1, len(values) - 1)
    return values[lo] * (hi - position) + values[hi] * (position - lo) if lo != hi else values[lo]


def committed_memory_available():
    if os.name != 'nt':
        return None
    class State(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong),
                    *[(n, ctypes.c_ulonglong) for n in ('total', 'available', 'page_total',
                        'page_available', 'virtual_total', 'virtual_available', 'extended')]]
    state = State()
    state.length = ctypes.sizeof(state)
    return state.page_available if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)) else None


def worker(args):
    # Deliberately use a benchmark-only loader rather than changing the app's
    # conservative physical-RAM gate. CUDA is mandatory; no CPU fallback exists.
    from core.local_asr import available_memory_bytes
    from utils.breeze_model import model_path, readiness, REVISION
    available = committed_memory_available()
    if available is not None and available < 6 * 1024**3:
        raise ValueError('Less than 6 GiB available commit memory; refusing a large model load.')
    from core.transcriber import Transcriber, _sanitize_transcript_text
    from faster_whisper.audio import decode_audio
    samples = json.loads((args.output / 'manifest.json').read_text(encoding='utf-8'))['samples']
    if args.worker == 'breeze':
        reason = readiness()
        if reason:
            raise ValueError(reason)
        source, revision = str(model_path()), REVISION
        modes = [('breeze_auto', None, ''), ('breeze_en', 'en', ''), ('breeze_zh', 'zh', '')]
        modes = [mode for mode in modes if mode[0].removeprefix('breeze_') in args.breeze_languages]
    else:
        cache = Path(os.environ.get('HF_HUB_CACHE', Path.home() / '.cache/huggingface/hub'))
        repo = cache / 'models--Systran--faster-whisper-large-v1'
        revision = (repo / 'refs/main').read_text(encoding='utf-8').strip()
        source = str(repo / 'snapshots' / revision)
        if not (Path(source) / 'model.bin').is_file():
            raise ValueError('Cached Whisper-large-v1 is unavailable; benchmark never downloads models.')
        modes = [('whisper_v1_zh_prompt', 'zh', '以下是繁體中文語音內容的逐字稿。'),
                 ('whisper_v1_auto', None, '')]
    before_ram = available_memory_bytes()
    started = time.perf_counter()
    transcriber = Transcriber(model_size=source, device='cuda', compute_type='int8_float16',
                             initial_prompt='', language='auto', local_files_only=True)
    native = transcriber.model.model
    if native.device != 'cuda' or native.compute_type != 'int8_float16':
        raise RuntimeError('Unexpected device/compute type; CPU fallback is prohibited.')
    after_ram = available_memory_bytes()
    metadata = {'worker': args.worker, 'device': native.device, 'compute_type': native.compute_type,
                'beam_size': args.beam_size,
                'revision': revision, 'load_seconds': time.perf_counter() - started,
                'available_ram_gib_before': before_ram / 1024**3 if before_ram is not None else None,
                'available_ram_gib_after': after_ram / 1024**3 if after_ram is not None else None,
                'cold_inference': [], 'warmups': []}
    print(json.dumps({'event': 'loaded', **metadata}), flush=True)
    def infer(sample, mode, repeat):
        mode_id, language, prompt = mode
        audio = decode_audio(str(args.archive / sample['file']), sampling_rate=16000)
        start = time.perf_counter()
        segments, info = transcriber.model.transcribe(audio, language=language, initial_prompt=prompt,
                                                      beam_size=args.beam_size, vad_filter=False)
        segments = list(segments)
        elapsed = time.perf_counter() - start
        raw = ''.join(s.text for s in segments).strip()
        return {'file': sample['file'], 'mode': mode_id, 'repeat': repeat,
                'audio_seconds': sample['audio_seconds'], 'elapsed_seconds': elapsed,
                'rtf': elapsed / sample['audio_seconds'], 'raw_text': raw,
                'app_text': _sanitize_transcript_text(raw, prompt),
                'detected_language': info.language, 'language_probability': info.language_probability,
                'segments': [{'start': s.start, 'end': s.end, 'text': s.text, 'avg_logprob': s.avg_logprob,
                              'no_speech_prob': s.no_speech_prob, 'temperature': s.temperature,
                              'compression_ratio': s.compression_ratio} for s in segments]}
    try:
        warmup = next((s for s in samples if 5 <= s['audio_seconds'] <= 12), samples[0])
        metadata['cold_inference'].append(infer(warmup, modes[0], -2))
        # Prime every mode on the same clip; these rows are excluded from latency stats.
        for mode in modes:
            metadata['warmups'].append(infer(warmup, mode, -1))
        target = args.output / (args.worker + '.jsonl')
        total, completed = len(samples) * len(modes) * args.repeats, 0
        with target.open('w', encoding='utf-8') as output:
            for repeat in range(args.repeats):
                order = list(samples)
                random.Random(1729 + repeat).shuffle(order)
                for index, sample in enumerate(order):
                    rotated = modes[index % len(modes):] + modes[:index % len(modes)]
                    for mode in rotated:
                        row = infer(sample, mode, repeat)
                        output.write(json.dumps(row, ensure_ascii=False) + '\n')
                        output.flush()
                        completed += 1
                        if completed % 10 == 0 or completed == total:
                            print(json.dumps({'event': 'progress', 'worker': args.worker,
                                              'completed': completed, 'total': total}), flush=True)
        end_ram = available_memory_bytes()
        metadata['available_ram_gib_end'] = end_ram / 1024**3 if end_ram is not None else None
        (args.output / (args.worker + '_metadata.json')).write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        transcriber.close()
    print(json.dumps({'event': 'finished', 'worker': args.worker}), flush=True)


class GPUMonitor:
    def __init__(self, output):
        self.path = output / 'gpu.csv'
        self.process = None
        self.thread = None

    def start(self):
        self.process = subprocess.Popen(['nvidia-smi', '--query-gpu=memory.used,utilization.gpu,temperature.gpu,power.draw',
            '--format=csv,noheader,nounits', '--loop-ms=500'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        def collect():
            with self.path.open('w', encoding='utf-8', newline='') as output:
                writer = csv.writer(output)
                writer.writerow(['epoch_seconds', 'memory_mib', 'utilization_percent', 'temperature_c', 'power_w'])
                for line in self.process.stdout:
                    fields = [x.strip() for x in line.split(',')]
                    if len(fields) == 4:
                        writer.writerow([time.time(), *fields])
                        output.flush()
        self.thread = threading.Thread(target=collect, daemon=True)
        self.thread.start()

    def stop(self):
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=5)
            self.thread.join(timeout=5)


def validate_runs(manifest, rows):
    modes = []
    for model in manifest.get('models', ['breeze', 'whisper']):
        modes.extend(['breeze_' + lang for lang in manifest.get('breeze_languages', ['auto', 'en', 'zh'])]
                     if model == 'breeze' else ['whisper_v1_zh_prompt', 'whisper_v1_auto'])
    expected = {(sample['file'], mode, repeat) for sample in manifest['samples']
                for mode in modes for repeat in range(manifest['repeats'])}
    actual = [(row['file'], row['mode'], row['repeat']) for row in rows]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError('Incomplete or duplicate benchmark runs; refusing to summarize partial results.')


def summarize(output):
    manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
    rows = []
    for name in manifest.get('models', ['breeze', 'whisper']):
        rows.extend(json.loads(line) for line in (output / (name + '.jsonl')).read_text(encoding='utf-8').splitlines())
    validate_runs(manifest, rows)
    grouped = {}
    for row in rows:
        grouped.setdefault(row['mode'], []).append(row)
    stats = {}
    for mode, items in grouped.items():
        times = [r['elapsed_seconds'] for r in items]
        stats[mode] = {'runs': len(items), 'p50_seconds': statistics.median(times),
                       'p95_seconds': percentile(times, .95),
                       'weighted_rtf': sum(times) / sum(r['audio_seconds'] for r in items),
                       'empty_outputs': sum(not r['raw_text'] for r in items),
                       'app_filtered_outputs': sum(r['app_text'] != r['raw_text'] for r in items),
                       'detected_languages': {lang: sum(r['detected_language'] == lang for r in items)
                                              for lang in sorted({r['detected_language'] for r in items})}}
    gpu = list(csv.DictReader((output / 'gpu.csv').open(encoding='utf-8')))
    peak_vram = max((float(r['memory_mib']) for r in gpu if r['memory_mib'] != '[N/A]'), default=None)
    first = {(r['file'], r['mode']): r for r in rows if r['repeat'] == 0}
    compared = {}
    anchor = 'breeze_auto' if 'breeze_auto' in grouped else next(iter(grouped))
    for mode in grouped:
        if mode == anchor:
            continue
        pairs = [(first[s['file'], anchor]['raw_text'], first[s['file'], mode]['raw_text'])
                 for s in manifest['samples']]
        compared[mode] = {'normalized_exact_matches': sum(normalized(a) == normalized(b) for a, b in pairs),
                          'pairs': len(pairs), 'note': 'Agreement only; not accuracy or CER.'}
    summary = {'dataset': {k: v for k, v in manifest.items() if k != 'samples'}, 'timing': stats,
               'peak_total_gpu_memory_mib': peak_vram, 'agreement_anchor': anchor, 'agreement': compared,
               'limitations': ['Historical ASR text is not human ground truth.',
                              'No cloud ASR was invoked; this is not a Groq accuracy benchmark.',
                              'All inference uses CUDA int8_float16; model precision is not full FP16.',
                              'This is a stratified diagnostic sample, not a random population estimate.']}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    with (output / 'comparison.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        modes = sorted(grouped)
        writer.writerow(['file', 'category', 'audio_seconds', 'historical_asr', *modes])
        for s in manifest['samples']:
            writer.writerow([s['file'], s['selection_category'], s['audio_seconds'], s['historical_asr'],
                             *[first[s['file'], mode]['raw_text'] for mode in modes]])
    render_html(output, manifest, first, stats)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def render_html(output, manifest, first, stats):
    esc = lambda value: html.escape(str(value), quote=True)
    modes = list(stats)
    panels = []
    for s in manifest['samples']:
        source = Path(manifest['archive']) / s['file']
        relative = Path(os.path.relpath(source, output)).as_posix()
        cards = [f'<div><b>歷史 ASR（非人工正解）</b><p>{esc(s["historical_asr"] or "（空白）")}</p></div>']
        for mode in modes:
            row = first[s['file'], mode]
            cards.append(f'<div><b>{esc(mode)}</b><small>{row["elapsed_seconds"]:.3f}s · '
                         f'language={esc(row["detected_language"])}</small><p>{esc(row["raw_text"] or "（空白）")}</p></div>')
        panels.append(f'<section><h2>{esc(s["file"])}</h2><small>{s["audio_seconds"]:.2f} 秒 · '
                      f'{esc(s["selection_category"])}</small><audio controls preload="none" src="{esc(relative)}"></audio>'
                      f'<div class="grid">{"".join(cards)}</div></section>')
    stats_html = ''.join(f'<tr><td>{esc(mode)}</td><td>{value["p50_seconds"]:.3f}</td>'
                         f'<td>{value["p95_seconds"]:.3f}</td><td>{value["weighted_rtf"]:.3f}</td></tr>'
                         for mode, value in stats.items())
    page = '''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Breeze GPU 實際錄音對照</title><style>
body{font:16px/1.65 system-ui,sans-serif;max-width:1500px;margin:32px auto;padding:0 24px;color:#203046;background:#f4f6fa}
h1{font-size:28px}h2{font-size:17px;overflow-wrap:anywhere}small{display:block;color:#58677a}
section{background:white;padding:22px;margin:22px 0;border-radius:12px;border:1px solid #dce2ea}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:16px}.grid>div{background:#f5f7fb;padding:14px;border-radius:8px}
p{white-space:pre-wrap;overflow-wrap:anywhere}audio{width:100%;margin:12px 0}table{border-collapse:collapse;background:white}
td,th{padding:10px 18px;text-align:left;border-bottom:1px solid #dde3eb}input{font:inherit;padding:10px;width:min(90%,600px)}
</style><h1>Breeze-ASR-25 · GPU 實際錄音對照</h1>
<p>搜尋寬度：BEAM。所有推論均為 CUDA / int8_float16，單一模型依序載入。音檔由本機讀取，未上傳。歷史 ASR 不是人工正解；請播放錄音再評斷文字。
表中時間排除載入與暖機，包含自動偵測語言。此頁列出每組第一次正式執行的逐字稿，完整各輪結果保存在 JSONL。</p>
<table><thead><tr><th>設定</th><th>p50 秒</th><th>p95 秒</th><th>總推論／音訊秒數</th></tr></thead><tbody>STATS</tbody></table>
<p><input id="query" placeholder="搜尋檔名、類別或文字"></p>CONTENTS
<script>document.querySelector('#query').addEventListener('input',e=>{for(const s of document.querySelectorAll('section'))s.hidden=!s.textContent.toLowerCase().includes(e.target.value.toLowerCase())})</script></html>'''
    (output / 'comparison.html').write_text(page.replace('BEAM', esc(manifest.get('beam_size', 5)))
        .replace('STATS', stats_html).replace('CONTENTS', ''.join(panels)), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=APP_DIR / 'whisper_audio_archive')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--reuse-manifest', type=Path, help='Reuse exact selected files; verify audio hashes')
    parser.add_argument('--samples', type=int, default=40)
    parser.add_argument('--repeats', type=int, choices=range(1, 4), default=2)
    parser.add_argument('--beam-size', type=int, choices=range(1, 6), default=5)
    parser.add_argument('--models', nargs='+', choices=('breeze', 'whisper'), default=['breeze', 'whisper'])
    parser.add_argument('--breeze-languages', nargs='+', choices=('auto', 'en', 'zh'), default=['auto', 'en', 'zh'])
    parser.add_argument('--worker', choices=('breeze', 'whisper'), help=argparse.SUPPRESS)
    parser.add_argument('--summarize', action='store_true')
    args = parser.parse_args()
    args.models = list(dict.fromkeys(args.models))
    args.breeze_languages = list(dict.fromkeys(args.breeze_languages))
    os.environ['AI_GOVERNESS_DISABLE_LOGGING'] = '1'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    args.archive = args.archive.resolve()
    args.output = args.output.resolve() if args.output else APP_DIR / 'asr_eval_outputs' / datetime.now().strftime('breeze_gpu_%Y%m%d_%H%M%S')
    if args.output == args.archive or args.archive in args.output.parents:
        parser.error('Output must not be inside the immutable audio archive')
    if args.worker:
        worker(args)
        return
    if args.summarize:
        summarize(args.output)
        return
    if args.samples < 1:
        parser.error('--samples must be positive')
    args.output.mkdir(parents=True, exist_ok=False)
    rows = archive_rows(args.archive)
    if not rows:
        parser.error('No WAV recordings found')
    if args.reuse_manifest:
        samples = json.loads(args.reuse_manifest.read_text(encoding='utf-8'))['samples']
        for sample in samples:
            if Path(sample['file']).name != sample['file']:
                raise ValueError('Manifest must contain archive filenames, not paths.')
            digest = hashlib.sha256((args.archive / sample['file']).read_bytes()).hexdigest()
            if digest != sample['sha256']:
                raise ValueError('An archived recording changed; refusing an unmatched comparison.')
    else:
        samples = select_samples(rows, args.samples)
    for sample in samples:
        sample['sha256'] = hashlib.sha256((args.archive / sample['file']).read_bytes()).hexdigest()
    manifest = {'archive': str(args.archive), 'archive_count': len(rows),
                'archive_audio_seconds': sum(r['audio_seconds'] for r in rows), 'selected_count': len(samples),
                'selected_audio_seconds': sum(r['audio_seconds'] for r in samples), 'repeats': args.repeats,
                'beam_size': args.beam_size, 'models': args.models, 'breeze_languages': args.breeze_languages,
                'samples': samples, 'historical_text_is_ground_truth': False}
    (args.output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'event': 'dataset_ready', 'output': str(args.output),
                      'samples': len(samples), 'audio_seconds': manifest['selected_audio_seconds']}), flush=True)
    monitor = GPUMonitor(args.output)
    monitor.start()
    try:
        for model in dict.fromkeys(args.models):
            command = [sys.executable, '-B', str(Path(__file__).resolve()), '--worker', model,
                       '--archive', str(args.archive), '--output', str(args.output), '--repeats', str(args.repeats),
                       '--beam-size', str(args.beam_size), '--breeze-languages', *args.breeze_languages]
            with (args.output / (model + '_worker.log')).open('w', encoding='utf-8') as log:
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                try:
                    for line in process.stdout:
                        log.write(line)
                        log.flush()
                        print(line.rstrip(), flush=True)
                    if process.wait() != 0:
                        raise RuntimeError(f'{model} GPU worker failed; see its private worker log.')
                finally:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=10)
    finally:
        monitor.stop()
    summarize(args.output)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
