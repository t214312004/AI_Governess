"""Author one shared skin base with independent semantic facial controls.

Only local closed-eye and open-mouth variants are imported; no full heads switch.
This face rig experiment does not claim independent pupils or finished body rigging.
"""
import json
from rig import ROOT,connect
out=ROOT/'authoring/shared-face';source=ROOT.parents[1]/'ai_voice_assistant/assets/states/layers'
with connect() as c:
    c.edit('project_open',path=str(out/'materials-peeled-v2.psd2live'),discard_unsaved=True)
    c.edit('material_import',paths=[str(source/'idle_listen_4.png'),str(source/'speaking_1.png')])
    mats=c.call('material_list',dict(limit=256,recursive=True))[0]['items'];by_name={m['name']:m['id'] for m in mats}
    revealed=by_name['skin-underpaint-normalized-v1']
    for frame in ['idle_listen_4','speaking_1']:
        c.edit('material_crop',id=by_name[frame],rect=dict(left=600,top=0,width=1024,height=1024),name=frame+'-head',new_id=frame+'-head')
    for name,frame,region,seeds in [('ClosedR','idle_listen_4','EyeR',[[430,453]]),('ClosedL','idle_listen_4','EyeL',[[591,453]]),('OpenMouth','speaking_1','Mouth',[[510,573]])]:
        c.edit('material_peel',id=frame+'-head',revealed=revealed,region='mask-'+region,threshold=[8,30],grow=0,core=0,close=2,color_match=False,keep=seeds,name=name,part_id=name,base_id='unused-base-'+name)
        c.edit('material_export_png',id=name,path=str(out/f'{name}.png'))
    c.edit('project_save_as',path=str(out/'materials-complete-v1.psd2live'))
    roles=[('SharedSkinContinuous','face','none'),('BrowR','eyebrow','right'),('BrowL','eyebrow','left'),('EyeR','eyelash','right'),('EyeL','eyelash','left'),('ClosedR','eye_close','right'),('ClosedL','eye_close','left'),('Mouth','mouth_close','none'),('OpenMouth','mouth_open','none')]
    c.edit('project_create_artwork',width=1024,height=1024,layers=[dict(path=str(out/f'{name}.png'),name=name,role=role,side=side) for name,role,side in roles])
    objects=c.call('workspace_inspect',dict(scope='objects',limit=64))[0]['items'];meshes={o['name']:o['target'] for o in objects if o['target'].startswith('mesh:')}
    for side in ['R','L']:
        c.edit('author_axis',parameter=dict(id=f'ParamBrow{side}Angle',min=-1,max=1,default=0),shapes=[dict(target=meshes['Brow'+side],value=v,operations=[dict(type='rotate',degrees=v*12,pivot=[.5,.5])]) for v in [-1,1]])
    c.edit('project_save_as',path=str(out/'shared-face-rig-v1.psd2live'))
    c.edit('project_export_psd',path=str(out/'shared-face-rig-v1.psd'))
    export=c.edit('project_export_model',output_directory=str(ROOT/'models/shared-face'))
    overview=c.call('workspace_overview')[0]
    (ROOT/'reports/g2/shared-face-export.json').write_text(json.dumps(export,indent=2),encoding='utf-8')
    (ROOT/'reports/g2/shared-face-overview.json').write_text(json.dumps(overview,indent=2),encoding='utf-8')
    (ROOT/'design/shared-face-runtime-map.json').write_text(json.dumps(meshes,indent=2),encoding='utf-8')
    print('Exported semantic shared-face rig:',len(meshes),'meshes',flush=True)
