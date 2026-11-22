"""Preserve the user-accepted v9 head/neck candidate before further work."""
import hashlib,json,shutil
from rig import ROOT
target=ROOT/'authoring/checkpoints/head-v9'
files=list((ROOT/'models/head-face').rglob('*'))+list((ROOT/'authoring/head-v9').glob('*'))
files += [ROOT/p for p in ['viewer/shared-face.ts','viewer/shared-reference.ts','viewer/avatar.ts','shared-face.html','design/HEAD_NECK.md','design/head-neck-calibration.json','design/head-tilt-source-geometry.json','tools/rig-head-neck.py','tools/refine-head-neck.py','tools/head-neck-test.mjs','tools/record-head.mjs','reports/g2/head-neck-results.json','reports/g2/head-neck-authoring.json','reports/g2/head-neck-refinement.json','reports/g2/head-neck-roundtrip.json','reports/g2/head-neck-recording.json','reports/g2/head-neck-v9.webm','reports/g2/head-neck-asset-integrity.json']]
manifest={'scope':'User accepted v9 small head/neck roll; yaw/pitch, full expression fidelity, body and gestures remain unaccepted','user_confirmation':'好 接下來\n轉頭與俯仰可以限制在小角度，免得live2D 不夠真實','files':{}}
for source in files:
    if not source.is_file():continue
    relative=source.relative_to(ROOT);destination=target/relative;digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if destination.exists():assert hashlib.sha256(destination.read_bytes()).hexdigest()==digest,f'Checkpoint already differs: {relative}'
    else:destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
    manifest['files'][relative.as_posix()]=digest
(ROOT/'reports/g2/head-v9-accepted.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('Preserved accepted head/neck roll:',len(manifest['files']),'files')
