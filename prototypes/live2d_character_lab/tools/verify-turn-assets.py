"""Protect accepted checkpoints and source art, and bind v9 evidence to actual assets."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
read=lambda p:json.loads((ROOT/p).read_text(encoding='utf-8-sig'))
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
report={'accepted_checkpoints':{},'turn_quality_accepted':False}
for version in ['blink-v5','gaze-v6','speech-v7','brows-v8-1','head-v9']:
 manifest=read(f'reports/g2/{version}-accepted.json');models=0
 for relative,sha in manifest['files'].items():
  assert digest(ROOT/f'authoring/checkpoints/{version}'/relative)==sha,relative
  if relative.startswith('models/'):
   assert digest(ROOT/relative)==sha,relative
   models+=1
 report['accepted_checkpoints'][version]={'backup_files':len(manifest['files']),'unchanged_model_files':models}
originals=[frame for state in read('references/inventory.json')['states'].values() for frame in state['frames']]
for frame in originals:assert digest(ROOT.parent.parent/frame['path'])==frame['sha256'],frame['path']
report['unchanged_original_frames']=len(originals)
parts={p:sha for p,sha in read('reports/g2/brows-v8-1-accepted.json')['files'].items() if p.startswith('authoring/') and p.endswith('.png')}
for p,sha in parts.items():assert digest(ROOT/p)==sha,p
report['unchanged_source_parts']=len(parts)
model_hash=digest(ROOT/'models/turn-face/original.moc3');test=read('reports/g2/head-turn-results.json');recording=read('reports/g2/head-turn-recording.json')
assert test['passed'] and not test['errors'] and test['modelSha256']==model_hash
assert recording['modelSha256']==model_hash and recording['loads']==1 and not recording['errors']
assert (ROOT/'reports/g2'/recording['file']).stat().st_size>10000
assert all(read('reports/g2/head-turn-roundtrip.json')['reopened_project_reproduces_runtime_assets'].values())
blink=read('reports/g2/head-turn-blink-results.json');assert blink['passed'] and blink['modelSha256']==model_hash
brow=read('reports/g2/head-turn-brow-dense.json');assert brow['modelSha256']==model_hash and brow['maxBefore']<.15
report['dense_brow_samples']=len(brow['keys']);report['max_brow_attachment_change']=brow['maxBefore']
assert digest(ROOT/'dist/generated/models/turn-face/original.moc3')==model_hash
report['tested_recorded_model_sha256']=model_hash
report['candidate_assets']={str(p.relative_to(ROOT/'models/turn-face')).replace('\\','/'):digest(p) for p in (ROOT/'models/turn-face').rglob('*') if p.is_file() and (p.suffix in ['.png','.moc3'] or p.name.endswith('.model3.json'))}
report['recording_sha256']=digest(ROOT/'reports/g2'/recording['file'])
report['utf8_files_checked']=0
for folder,patterns in [('viewer',['*.ts']),('design',['*.md']),('tools',['*head*.py','*head*.mjs','*turn*.py','*turn*.mjs'])]:
 for pattern in patterns:
  for p in (ROOT/folder).glob(pattern):
   text=p.read_bytes().decode('utf-8-sig',errors='strict');assert '\ufffd' not in text,p
   report['utf8_files_checked']+=1
(ROOT/'reports/g2/head-turn-asset-integrity.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
