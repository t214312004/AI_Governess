"""Rebind freshly imported segment PSD, without inherited split topology."""
import json
from rig import ROOT, connect

with connect() as client:
    objects=client.call('workspace_inspect',{'scope':'objects'})[0]['items']
    meshes={o['name']:o['target'].removeprefix('mesh:') for o in objects if o['target'].startswith('mesh:')}
    bones=[dict(id='torso',role='UPPER_BODY',head=[543,760],tail=[543,430],drawables=[meshes['body']],minAngle=0,maxAngle=0)]
    for suffix,side,sign,points in [
        ('r','RIGHT',1,[[393,450],[315,700],[210,945],[165,1060]]),
        ('l','LEFT',-1,[[693,450],[771,700],[876,945],[921,1060]])
    ]:
        for i,(role,name,layername) in enumerate([('UPPER_ARM','upper','upper'),('FOREARM','fore','forearm'),('HAND','hand','hand')]):
            bones.append(dict(id=f'{name}_{suffix}',role=role,side=side,parent='torso' if i==0 else f'{["upper","fore"][i-1]}_{suffix}',head=points[i],tail=points[i+1],drawables=[meshes[f'{layername}-{side.lower()}']],direction=sign,minAngle=-150,maxAngle=150,blendWidth=12,ik=dict(chainLength=3,iterations=128,tolerancePx=1,bendDirection=0)))
    spec=dict(version=11,enabled=True,symmetryAxisX=543,bones=bones,sampling=dict(tolerancePx=1,minimumStepDegrees=7.5,maxMeshKeyforms=600,jointMeshSegments=16))
    (ROOT/'design/arm-skeleton.json').write_text(json.dumps(spec,indent=2),encoding='utf-8')
    client.edit('skeleton_put',spec=spec)
    client.edit('project_save_as',path=str(ROOT/'authoring/arm-spike-clean.psd2live'))
    poses={}
    for name,target in [('chin',[510,350]),('index',[290,300])]:
        poses[name]=client.call('skeleton_pose',dict(bone_id='hand_r',target=target,ik=True))[0]['values']
    (ROOT/'reports/g1/arm-clean-ik.json').write_text(json.dumps(poses,indent=2),encoding='utf-8')
    for name,parameters in {'neutral':{},**poses}.items():
        result,images=client.call('view_render_model',dict(viewport=dict(mode='canvas_rect',left=0,top=0,width=1086,height=1448),parameters=parameters,target_long_edge=1200))
        for i,image in enumerate(images): (ROOT/f'reports/g1/arm-clean-{name}-{i}.png').write_bytes(image)
    export=client.edit('project_export_model',output_directory=str(ROOT/'models/arm-spike-clean'))
    (ROOT/'reports/g1/arm-clean-export.json').write_text(json.dumps(export,indent=2),encoding='utf-8')
    print(json.dumps({'poses':poses,'warnings':export.get('warnings')}))
