"""Verify the native head candidate round trip without overwriting its tested assets."""
import hashlib,json
from rig import ROOT,connect
with connect() as c:
 c.edit('project_open',path=str(ROOT/'authoring/turn-v10/shared-face-rig-v10-turn.psd2live'),discard_unsaved=True)
 c.edit('project_export_psd',path=str(ROOT/'authoring/turn-v10/shared-face-rig-v10-turn.psd'))
 c.edit('project_export_model',output_directory=str(ROOT/'.cache/turn-roundtrip'))
hash=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
files=['original.moc3']+[str(p.relative_to(ROOT/'models/turn-face')).replace('\\','/') for p in (ROOT/'models/turn-face').rglob('*.png')]
checks={name:hash(ROOT/'models/turn-face'/name)==hash(ROOT/'.cache/turn-roundtrip'/name) for name in files}
(ROOT/'reports/g2/head-turn-roundtrip.json').write_text(json.dumps({'reopened_project_reproduces_runtime_assets':checks},indent=2),encoding='utf-8')
assert all(checks.values()),checks
print(checks)
