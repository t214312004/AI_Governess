"""Record local candidate hashes without including external-service credentials."""
import hashlib
import json
from pathlib import Path

root=Path(__file__).resolve().parents[1]
files=list((root/'models/governess').rglob('*'))+list((root/'models/arm-spike-clean').rglob('*'))
files+=list((root/'authoring').glob('*.psd2live'))+list((root/'authoring').glob('*.psd'))
files+=list((root/'authoring/imagegen').glob('*.png'))
files+=list((root/'fixtures/audio').glob('*.wav'))
files+=[root/'vendor/mcp_proxy.py']
records=[]
for path in sorted(files):
    if path.is_file():
        with path.open('rb') as stream:
            digest=hashlib.file_digest(stream,'sha256').hexdigest()
        records.append(dict(path=path.relative_to(root).as_posix(),bytes=path.stat().st_size,sha256=digest))
target=root/'reports/g1/artifact-hashes.json'
target.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
print(f'Recorded {len(records)} local artifact hashes.')
