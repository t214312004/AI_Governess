"""Preserve the user-approved blink without overwriting an existing checkpoint."""
import hashlib,json,shutil
from pathlib import Path
from rig import ROOT
target=ROOT/'authoring/checkpoints/blink-v5'
files=list((ROOT/'models/shared-face').rglob('*'))
files += [ROOT/'authoring/shared-face/shared-face-rig-v5.psd2live',ROOT/'authoring/shared-face/shared-face-rig-v5.psd',ROOT/'tools/rig-shared-face.py',ROOT/'tools/split-eye-geometry.py',ROOT/'viewer/shared-face.ts',ROOT/'design/shared-face-runtime-map.json']
files += list((ROOT/'authoring/shared-face').glob('*.png'))
manifest={'scope':'User accepted blink only; other facial expressions and gestures remain unaccepted','user_confirmation':'很好，閉眼通過。繼續吧','files':{}}
for source in files:
    if not source.is_file():continue
    relative=source.relative_to(ROOT);destination=target/relative;digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if destination.exists():assert hashlib.sha256(destination.read_bytes()).hexdigest()==digest,f'Checkpoint already differs: {relative}'
    else:destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
    manifest['files'][relative.as_posix()]=digest
(ROOT/'reports/g2/blink-v5-accepted.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('Preserved accepted blink:',len(manifest['files']),'files')
