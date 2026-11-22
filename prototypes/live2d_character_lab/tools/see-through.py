"""Upload a character reference to the public See-through demo (not offline).

Use gradio_client==2.7.2 in an independent environment or --packages vendor/python.
The external demo is not version pinned; preserve its PSD output and SHA256.
"""
import argparse
import json
import os
from pathlib import Path
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('image', type=Path)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--packages', type=Path)
args = parser.parse_args()
if args.packages:
    sys.path.insert(0, str(args.packages.resolve()))
os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
os.environ['HF_HOME'] = str(Path(__file__).resolve().parents[1] / '.cache/huggingface')
from gradio_client import Client, handle_file

args.output.mkdir(parents=True, exist_ok=True)
client = Client('https://24yearsold-see-through-demo.hf.space/', download_files=str(args.output.resolve()), verbose=False)
result = client.predict(handle_file(str(args.image.resolve())), 768, 42, True, api_name='/inference')
(args.output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print('Saved PSD and decomposition result in', args.output)
