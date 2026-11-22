"""Preserve the user-approved v6 gaze candidate and its reproducible authoring inputs."""
import hashlib,json,shutil
from rig import ROOT
target=ROOT/'authoring/checkpoints/gaze-v6'
files=list((ROOT/'models/gaze-face').rglob('*'))
files+=list((ROOT/'authoring/shared-face').glob('*.png'))
files+=[ROOT/path for path in ['authoring/shared-face/shared-face-rig-v6-gaze.psd2live','authoring/shared-face/shared-face-rig-v6-gaze.psd','authoring/shared-face/materials-irises-v1.psd2live','tools/rig-shared-face.py','tools/split-irises.py','viewer/shared-face.ts','viewer/shared-reference.ts','shared-face.html','design/gaze-face-runtime-map.json','design/iris-parts.json','design/shared-reference-poses.json','design/iris-completion-prompt.txt','reports/g2/gaze-face-results.json','reports/g2/gaze-asset-integrity.json']]
manifest={'scope':'User accepted v6 gaze after v5 blink; remaining original-expression fidelity and gestures are unaccepted','user_confirmation':'通過\n繼續下個步驟吧','files':{}}
for source in files:
    if not source.is_file():continue
    relative=source.relative_to(ROOT);destination=target/relative;digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if destination.exists():assert hashlib.sha256(destination.read_bytes()).hexdigest()==digest,f'Checkpoint already differs: {relative}'
    else:destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
    manifest['files'][relative.as_posix()]=digest
(ROOT/'reports/g2/gaze-v6-accepted.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('Preserved accepted gaze:',len(manifest['files']),'files')
