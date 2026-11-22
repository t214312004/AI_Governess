"""Put source hand endpoints in the same moc as the 16 expression endpoints.

Inspection only: arm attachment and continuous gesture transitions are unfinished.
"""
import json
from rig import ROOT,connect
with connect() as client:
    client.edit('project_open',path=str(ROOT/'authoring/face-fidelity-v2.psd2live'))
    client.edit('material_import',paths=[str(ROOT/f'authoring/source-parts/{name}-hand-v2.png') for name in ['index','chin']])
    mats=client.call('material_list',dict(limit=256,recursive=True))[0]['items']
    by_name={m['name']:m['id'] for m in mats}
    for index,name in enumerate(['index','chin'],1):
        layer=f'reference-hand-{name}'
        client.edit('layer_place',material_id=by_name[f'{name}-hand-v2'],layer_id=layer,rect=dict(left=0,top=0,width=2236,height=2024))
        client.edit('layer_classify',layer_id=layer,role='objects',side='none')
        client.edit('layer_set_variant',layer_id=layer,variant='switch',parameter='ParamHandReference',switch_id=index)
    client.edit('rig_generate')
    objects=client.call('workspace_inspect',dict(scope='objects',query='reference-hand',limit=64))[0]['items']
    mapping={obj['layerId'].replace('reference-hand-',''):obj['target'].removeprefix('mesh:') for obj in objects if obj.get('layerId','').startswith('reference-hand-')}
    assert set(mapping)=={'index','chin'},mapping
    (ROOT/'design/hand-runtime-map.json').write_text(json.dumps(mapping,indent=2),encoding='utf-8')
    client.edit('project_save_as',path=str(ROOT/'authoring/reference-fidelity-v3.psd2live'))
    export=client.edit('project_export_model',output_directory=str(ROOT/'models/face-fidelity'))
    (ROOT/'reports/g2/reference-v3-export.json').write_text(json.dumps(export,indent=2),encoding='utf-8')
    print('Saved expression and original hand endpoints in the same model',flush=True)
