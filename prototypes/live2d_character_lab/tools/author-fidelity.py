"""Preserve original face pixels in separate, parameter-controlled native parts.

Requires the OriginalReference artwork and idle_listen_4 / speaking_1 materials.
All extraction runs through PSD2Live's native authoring API; source PNGs stay intact.
"""
import json
from rig import ROOT, connect

regions={
    'FeatureR':dict(left=945,top=355,width=140,height=140),
    'FeatureL':dict(left=1135,top=355,width=140,height=140),
    'SmilePatch':dict(left=1045,top=545,width=140,height=85),
}
with connect() as client:
    layers=client.call('workspace_overview')[0]['layers']['items']
    if len(layers)!=1 or layers[0]['name']!='OriginalReference': raise RuntimeError('Unexpected project')
    client.edit('source_split_polygon',layer_id=layers[0]['id'],polygon=[[0,0],[2236,0],[2236,730],[0,730]],names=['PortraitBase','BodyBase'],piece_ids=['portrait-base','body-base'])
    remaining='portrait-base'
    for name,rect in regions.items():
        x,y,w,h=rect['left'],rect['top'],rect['width'],rect['height']
        next_id=f'remainder-{name}'
        client.edit('source_split_polygon',layer_id=remaining,polygon=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]],names=[name,'PortraitBase'],piece_ids=[name,next_id])
        client.edit('layer_classify',layer_id=name,role='face_detail',side='none')
        remaining=next_id
    client.edit('layer_classify',layer_id=remaining,role='face',side='none')
    materials=client.call('material_list',dict(limit=100))[0]['items']
    by_name={m['name']:m['id'] for m in materials}
    overlays=[('ClosedR','idle_listen_4','FeatureR','ParamEyesClosed'),('ClosedL','idle_listen_4','FeatureL','ParamEyesClosed'),('TalkingPatch','speaking_1','SmilePatch','ParamMouthOpenY')]
    for name,frame,region,param in overlays:
        rect=regions[region]
        client.edit('material_crop',id=by_name[frame],rect=rect,name=name,new_id=f'mat-{name}')
        client.edit('layer_place',material_id=f'mat-{name}',layer_id=name,rect=rect)
        client.edit('layer_classify',layer_id=name,role='face_detail',side='none')
        client.edit('layer_set_variant',layer_id=name,variant='toggle',parameter=param)
    client.edit('rig_generate')
    objects=client.call('workspace_inspect',{'scope':'objects'})[0]['items']
    for obj in objects:
        if obj.get('layerId') in [o[0] for o in overlays]: client.edit('layer_draw_order',target=obj['target'],order=950)
    client.edit('project_save_as',path=str(ROOT/'authoring/face-fidelity-v1.psd2live'))
    client.edit('project_export_psd',path=str(ROOT/'authoring/face-fidelity-v1.psd'))
    export=client.edit('project_export_model',output_directory=str(ROOT/'models/face-fidelity'))
    (ROOT/'reports/g2/face-export.json').write_text(json.dumps(export,indent=2),encoding='utf-8')
    overview=client.call('workspace_overview')[0]
    (ROOT/'reports/g2/face-overview.json').write_text(json.dumps(overview,indent=2),encoding='utf-8')
    print(json.dumps({'parameters':overview['parameters'],'layers':overview['layers'],'warnings':export.get('warnings')}))
