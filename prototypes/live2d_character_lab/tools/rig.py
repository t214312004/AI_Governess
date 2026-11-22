"""Call the lab-only PSD2Live MCP workspace; keep credentials outside reports."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
from mcp_proxy import Client

def connect():
    settings = json.loads((ROOT / '.cache/rig-connection.json').read_text())
    return Client(endpoint=settings['endpoint'], token=settings['token'])

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation')
    parser.add_argument('request', nargs='?', default='{}', help='JSON or @path')
    parser.add_argument('--edit', action='store_true')
    parser.add_argument('--out', default='reports/g1/rig-result.json')
    args = parser.parse_args()
    raw = Path(args.request[1:]).read_text(encoding='utf-8') if args.request.startswith('@') else args.request
    request = json.loads(raw)
    with connect() as client:
        if args.edit:
            request.setdefault('state', client.state())
        result, images = client.call(args.operation, request)
    target = ROOT / args.out
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    for index, image in enumerate(images):
        target.with_name(f'{target.stem}-{index}.png').write_bytes(image)
    printed = { 'id': result['id'], 'request_schema': result['request_schema'] } if args.operation == 'workspace_get_operation' else result
    print(json.dumps(printed, ensure_ascii=True)[:16000])
