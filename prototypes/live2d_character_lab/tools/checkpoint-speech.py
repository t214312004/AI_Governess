"""Freeze the accepted v7 mouth model and its authoring inputs."""
import hashlib,json,shutil
from rig import ROOT
target=ROOT/'authoring/checkpoints/speech-v7'
files=list((ROOT/'models/speech-face').rglob('*'))+list((ROOT/'authoring/shared-face').glob('*.png'))+list((ROOT/'authoring/speech-face').glob('*'))
files+=[ROOT/p for p in ['authoring/shared-face/shared-face-rig-v7-speech.psd2live','authoring/shared-face/shared-face-rig-v7-speech.psd','tools/rig-shared-face.py','tools/split-speech-mouth.py','viewer/shared-face.ts','viewer/shared-reference.ts','shared-face.html','design/speech-face-runtime-map.json','design/shared-reference-poses.json','reports/g2/speech-face-results.json','reports/g2/speech-asset-integrity.json']]
manifest={'scope':'User accepted v7 mouth refinement; remaining expression fidelity and gestures are unaccepted','user_confirmation':'好 通過，繼續下個步驟吧','files':{}}
for source in files:
    if not source.is_file():continue
    relative=source.relative_to(ROOT);destination=target/relative;digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if destination.exists():assert hashlib.sha256(destination.read_bytes()).hexdigest()==digest,f'Checkpoint already differs: {relative}'
    else:destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
    manifest['files'][relative.as_posix()]=digest
(ROOT/'reports/g2/speech-v7-accepted.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('Preserved accepted mouth:',len(manifest['files']),'files')
