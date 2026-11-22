"""Match original head context around separately authored feature endpoints.

The remaining head has holes smaller than the feature tiles by 2 source pixels,
so opaque source edges overlap without a rectangular alpha seam. No full-body
frames are added. Head/gesture transitions remain an independent authoring task.
"""
import json
from rig import ROOT,connect
raise SystemExit('Rejected experiment: do not replace heads per expression. Use one shared head with clean feature masks and authored deformation; see reports/g2/STATUS.md.')
catalog=json.loads((ROOT/'design/feature-catalog.json').read_text(encoding='utf-8'))
with connect() as client:
    client.edit('project_open',path=str(ROOT/'authoring/reference-fidelity-v4.psd2live'))
    mats=client.call('material_list',dict(limit=256,recursive=True))[0]['items'];by_name={m['name']:m['id'] for m in mats}
    client.edit('layer_set_variant',layer_id='remainder-SmilePatch',variant='switch',parameter='ParamReferenceFrame',switch_id=0)
    # Place and generate every new source before splitting. Splitting an unbuilt
    # layer after an earlier source split can fail in PSD2Live 3.6.7.
    for index,frame in catalog['unique_frames'].items():
        if index=='0':continue
        rect=dict(left=0,top=0,width=2236,height=730);mid=f'head-context-material-{index}';layer=f'head-context-{index}-source'
        edits=[dict(operation='material_crop',request=dict(id=by_name[frame],rect=rect,name=mid,new_id=mid)),dict(operation='layer_place',request=dict(material_id=mid,layer_id=layer,rect=rect))]
        edits.append(dict(operation='layer_classify',request=dict(layer_id=layer,role='face',side='none',type='switch',parameter='ParamReferenceFrame',switch_id=int(index))))
        client.edit('workspace_apply_edits',summary='Place head context: '+frame,edits=edits)
    client.edit('rig_generate')
    for index,frame in catalog['unique_frames'].items():
        if index=='0':continue
        layer=f'head-context-{index}-source';edits=[]
        for name,r in catalog['regions'].items():
            inside=f'context-discard-{index}-{name}';outside=f'head-context-{index}-{name}'
            x,y,w,h=r['left']+2,r['top']+2,r['width']-4,r['height']-4
            edits.append(dict(operation='source_split_polygon',request=dict(layer_id=layer,polygon=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]],names=[inside,outside],piece_ids=[inside,outside])))
            edits.append(dict(operation='layer_delete',request=dict(layer_id=inside)))
            layer=outside
        edits.append(dict(operation='layer_classify',request=dict(layer_id=layer,role='face',side='none',type='switch',parameter='ParamReferenceFrame',switch_id=int(index))))
        client.edit('workspace_apply_edits',summary='Original head context: '+frame,edits=edits)
        print('Added head context:',frame,flush=True)
    client.edit('rig_generate')
    objects=client.call('workspace_inspect',dict(scope='objects',query='head-context',limit=64))[0]['items']
    edits=[dict(operation='layer_draw_order',request=dict(target=obj['target'],order=900)) for obj in objects if obj.get('layerId','').startswith('head-context-')]
    client.edit('workspace_apply_edits',summary='Head context behind independent features',edits=edits)
    objects=client.call('workspace_inspect',dict(scope='objects',query='reference-hand',limit=64))[0]['items']
    mapping={obj['layerId'].replace('reference-hand-',''):obj['target'].removeprefix('mesh:') for obj in objects if obj.get('layerId','').startswith('reference-hand-')}
    (ROOT/'design/hand-runtime-map.json').write_text(json.dumps(mapping,indent=2),encoding='utf-8')
    client.edit('project_save_as',path=str(ROOT/'authoring/reference-fidelity-v5.psd2live'))
    export=client.edit('project_export_model',output_directory=str(ROOT/'models/face-fidelity'))
    (ROOT/'reports/g2/reference-v5-export.json').write_text(json.dumps(export,indent=2),encoding='utf-8')
    print('Exported source-matched facial contexts',flush=True)
