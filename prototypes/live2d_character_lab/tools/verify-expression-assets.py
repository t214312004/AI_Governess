"""Verify accepted checkpoints and v8 evidence without modifying source artwork."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
report={'accepted_checkpoints':{},'quality_accepted':False}
for version in ['blink-v5','gaze-v6','speech-v7']:
    manifest=json.loads((ROOT/f'reports/g2/{version}-accepted.json').read_text(encoding='utf-8'));models=0
    for relative,sha in manifest['files'].items():
        assert digest(ROOT/f'authoring/checkpoints/{version}'/relative)==sha,relative
        if relative.startswith('models/'):
            assert digest(ROOT/relative)==sha,relative
            models+=1
    report['accepted_checkpoints'][version]={'verified_backup_files':len(manifest['files']),'unchanged_current_model_files':models}
tests=json.loads((ROOT/'reports/g2/expression-face-results.json').read_text(encoding='utf-8'))
assert tests['passed'] and not tests['errors']
for relative,sha in tests['assetHashes'].items():
    assert digest(ROOT/'models/expression-face'/relative)==sha,relative
recording=json.loads((ROOT/'reports/g2/brow-recording.json').read_text(encoding='utf-8'))
assert recording['modelSha256']==tests['assetHashes']['original.moc3']
assert recording['loads']==1 and not recording['errors']
assert (ROOT/'reports/g2'/recording['file']).stat().st_size>10000
report['candidate_model_sha256']=recording['modelSha256']
report['tested_assets_match_recording']=True
brows=json.loads((ROOT/'reports/g2/brow-hairline-results.json').read_text(encoding='utf-8'))
assert brows['passed'] and brows['modelSha256']==recording['modelSha256']
report['brow_constraints_tested']=len(brows['poses'])
# v8 adds only deformers and parameters. Source PNGs are the accepted v7 assets.
v7=json.loads((ROOT/'reports/g2/speech-v7-accepted.json').read_text(encoding='utf-8'))
parts={p:sha for p,sha in v7['files'].items() if p.startswith('authoring/') and p.endswith('.png')}
assert parts
for relative,sha in parts.items():assert digest(ROOT/relative)==sha,relative
report['unchanged_source_parts']=len(parts)
(ROOT/'reports/g2/expression-asset-integrity.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
