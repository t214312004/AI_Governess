"""Download and verify the pinned CT2 model, without changing app settings."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ai_voice_assistant'))
from utils.breeze_model import DEFAULT_MODEL_DIR, prepare_model, readiness


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir', default=DEFAULT_MODEL_DIR)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if args.verify_only:
        reason = readiness(args.model_dir, verify=True)
        if reason:
            print(reason)
            return 1
        print('Breeze model checksums verified.')
        return 0
    last = [-1]
    def progress(event):
        percent = int(event['level'] * 100)
        if percent != last[0]:
            print(f'Breeze model: {percent}%', flush=True)
            last[0] = percent
    try:
        path = prepare_model(args.model_dir, progress=progress)
        print(f'Model ready: {path}')
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
