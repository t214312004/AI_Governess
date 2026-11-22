"""Offline Breeze decoder comparison. Does not change config or contact cloud ASR."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ai_voice_assistant'))
from core.local_asr import available_memory_bytes, resolve_local_profile
from utils.breeze_model import DEFAULT_MODEL_DIR, REVISION, readiness


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='Check files and memory without loading weights')
    mode.add_argument('--audio', type=Path, help='A local audio file; never uploaded')
    parser.add_argument('--model-dir', default=DEFAULT_MODEL_DIR)
    parser.add_argument('--language', nargs='+', choices=('auto', 'en', 'zh'), default=['auto', 'en', 'zh'])
    parser.add_argument('--device', choices=('cuda', 'cpu'), default='cuda')
    parser.add_argument('--compute-type', choices=('int8_float16', 'float16', 'int8', 'int8_float32', 'float32'), default='int8_float16')
    parser.add_argument('--beam-size', type=int, choices=range(1, 6), default=5)
    parser.add_argument('--repeats', type=int, choices=range(1, 11), default=2)
    parser.add_argument('--output', type=Path, help='Optional local JSON, containing transcripts')
    args = parser.parse_args()
    available = available_memory_bytes()
    reason = readiness(args.model_dir)
    if available is not None and available < 2 * 1024**3:
        reason = reason or '可用 RAM 不足 2 GiB；請先關閉其他程式。'
    if args.check or reason:
        print(json.dumps({'model_ready': readiness(args.model_dir) is None, 'available_ram_gib':
              round(available / 1024**3, 2) if available is not None else None, 'reason': reason}, ensure_ascii=False))
        return 2 if reason else 0
    if not args.audio.is_file():
        parser.error('Audio file does not exist')
    settings = {'model_dir': args.model_dir, 'device': args.device, 'compute_type': args.compute_type,
                'language': args.language[0], 'beam_size': args.beam_size}
    options = resolve_local_profile('breeze_asr25', {}, settings)
    # Set before importing project logging; this utility creates no application logs.
    import os
    os.environ['AI_GOVERNESS_DISABLE_LOGGING'] = '1'
    from core.transcriber import Transcriber
    from faster_whisper.audio import decode_audio
    audio = decode_audio(str(args.audio), sampling_rate=16000)
    started = time.perf_counter()
    transcriber = Transcriber(**options)
    report = {'revision': REVISION, 'device': args.device, 'compute_type': args.compute_type,
              'beam_size': args.beam_size, 'audio_seconds': len(audio) / 16000,
              'load_seconds': time.perf_counter() - started, 'runs': []}
    try:
        for language in args.language:
            transcriber.language = None if language == 'auto' else language
            for repeat in range(args.repeats):
                text = transcriber.transcribe(audio)
                diagnostics = dict(transcriber.last_diagnostics)
                report['runs'].append({'requested_language': language, 'repeat': repeat,
                                       'text': text, **diagnostics})
                if diagnostics.get('status') == 'error':
                    raise ValueError(diagnostics['message'])
        report['median_seconds'] = statistics.median(row['elapsed_seconds'] for row in report['runs'])
    finally:
        transcriber.close()
    result = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(result + '\n', encoding='utf-8')
    print(result)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
