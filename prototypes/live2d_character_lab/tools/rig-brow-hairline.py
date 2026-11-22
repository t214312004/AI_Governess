"""Constrain only the cleaned eyebrow tail to the static hairline, using 27 keys."""
import json
from rig import ROOT,connect
out=ROOT/'authoring/brow-v8-1'
fit=json.loads((ROOT/'design/brow-tail-constraints.json').read_text(encoding='utf-8'))
with connect() as c:
    c.edit('project_open',path=str(out/'shared-face-rig-v8-1-source.psd2live'),discard_unsaved=True)
    target='mesh:ArtMeshEyebrowR'
    c.edit('keyform_apply',changes=[dict(op='seed',target=target,key=item['key']) for item in fit['keys']])
    c.edit('rig_deform',changes=[dict(target=target,key=item['key'],operations=[dict(type='translate',delta=item['delta'],selection=dict(indices=fit['selected'],soft_radius=.35,falloff='smooth'))]) for item in fit['keys']])
    c.edit('project_save_as',path=str(out/'shared-face-rig-v8-1-brow.psd2live'))
    c.edit('project_export_psd',path=str(out/'shared-face-rig-v8-1-brow.psd'))
    export=c.edit('project_export_model',output_directory=str(ROOT/'models/expression-face'))
    report={'source':'shared-face-rig-v8-1-source.psd2live','method':'Local tail constraint, no extra source layers or whole-rig regeneration','keys':len(fit['keys']),'selected':fit['selected'],'export':export}
    (ROOT/'reports/g2/brow-hairline-rig.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Exported local eyebrow-tail constraint; original 20 meshes retained',flush=True)