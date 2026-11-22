"""Give source feature switches a real neutral key and hidden hand defaults."""
import json
from rig import ROOT,connect
with connect() as client:
    client.edit('project_open',path=str(ROOT/'authoring/face-fidelity-v2.psd2live'))
    client.edit('material_import',paths=[str(ROOT/f'authoring/source-parts/{name}-hand-v2.png') for name in ['index','chin']])
    mats=client.call('material_list',dict(limit=256,recursive=True))[0]['items']
    by_name={m['name']:m['id'] for m in mats}
    edits=[]
    for layer in ['FeatureR','FeatureL','SmilePatch']:
        edits.append(dict(operation='layer_set_variant',request=dict(layer_id=layer,variant='switch',parameter='ParamReferenceFrame',switch_id=0)))
    for name in ['index','chin']:
        layer=f'reference-hand-{name}'
        edits.append(dict(operation='layer_place',request=dict(material_id=by_name[f'{name}-hand-v2'],layer_id=layer,rect=dict(left=0,top=0,width=2236,height=2024))))
        edits.append(dict(operation='layer_classify',request=dict(layer_id=layer,role='objects',side='none',type='toggle',parameter=f'ParamHand{name.title()}')))
    client.edit('workspace_apply_edits',summary='Neutral expression and hidden hand defaults',edits=edits)
    client.edit('rig_generate')
    objects=client.call('workspace_inspect',dict(scope='objects',query='reference-hand',limit=64))[0]['items']
    mapping={obj['layerId'].replace('reference-hand-',''):obj['target'].removeprefix('mesh:') for obj in objects if obj.get('layerId','').startswith('reference-hand-')}
    (ROOT/'design/hand-runtime-map.json').write_text(json.dumps(mapping,indent=2),encoding='utf-8')
    client.edit('project_save_as',path=str(ROOT/'authoring/reference-fidelity-v4.psd2live'))
    export=client.edit('project_export_model',output_directory=str(ROOT/'models/face-fidelity'))
    (ROOT/'reports/g2/reference-v4-export.json').write_text(json.dumps(export,indent=2),encoding='utf-8')
    print('Exported neutral-safe reference model',flush=True)
