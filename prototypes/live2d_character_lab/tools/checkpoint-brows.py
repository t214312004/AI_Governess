"""Preserve the user-accepted v8.1 eyebrow/hairline candidate before further work."""
import hashlib,json,shutil
from rig import ROOT
target=ROOT/'authoring/checkpoints/brows-v8-1'
files=list((ROOT/'models/expression-face').rglob('*'))+list((ROOT/'authoring/shared-face').glob('*.png'))+list((ROOT/'authoring/brow-v8-1').glob('*'))
files += [ROOT/p for p in ['viewer/shared-face.ts','viewer/shared-reference.ts','shared-face.html','design/expression-face-runtime-map.json','design/expression-reference-poses.json','design/brow-tail-constraints.json','design/BROW_HAIRLINE.md','tools/fix-brow-hairline.py','tools/fit-brow-tail.mjs','tools/rig-brow-hairline.py','tools/brow-hairline-test.mjs','tools/expression-face-test.mjs','reports/g2/brow-hairline-results.json','reports/g2/brow-hairline-authoring-boundary.json','reports/g2/brow-hairline-authoring.json','reports/g2/brow-hairline-rig.json','reports/g2/brow-roundtrip.json','reports/g2/brow-recording.json','reports/g2/brow-v8-1.webm','reports/g2/expression-face-results.json','reports/g2/expression-asset-integrity.json']]
manifest={'scope':'User accepted v8.1 eyebrow hairline repair; full expression fidelity, head/body and gestures remain unaccepted','user_confirmation':'好 通過，繼續吧','files':{}}
for source in files:
    if not source.is_file():continue
    relative=source.relative_to(ROOT);destination=target/relative;digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if destination.exists():assert hashlib.sha256(destination.read_bytes()).hexdigest()==digest,f'Checkpoint already differs: {relative}'
    else:destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
    manifest['files'][relative.as_posix()]=digest
(ROOT/'reports/g2/brows-v8-1-accepted.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('Preserved accepted eyebrow repair:',len(manifest['files']),'files')
