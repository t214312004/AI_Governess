"""Split elbow/wrist ownership, then bind each segment to its own bone."""
import json
from rig import ROOT, connect

with connect() as client:
    client.edit('skeleton_delete')
    for side in ['right','left']:
        client.edit('source_split_polygon',layer_id=f'arm-{side}',polygon=[[0,700],[1086,700],[1086,1448],[0,1448]],names=[f'fore-{side}',f'upper-{side}'],piece_ids=[f'fore-{side}',f'upper-{side}'])
        client.edit('source_split_polygon',layer_id=f'fore-{side}',polygon=[[0,945],[1086,945],[1086,1448],[0,1448]],names=[f'hand-{side}',f'forearm-{side}'],piece_ids=[f'hand-{side}',f'forearm-{side}'])
    client.edit('rig_generate',refresh_geometry=['upper-right','forearm-right','hand-right','upper-left','forearm-left','hand-left','body'])
    objects=client.call('workspace_inspect',{'scope':'objects'})[0]['items']
    meshes={o['layerId']:o['target'].removeprefix('mesh:') for o in objects if o['target'].startswith('mesh:')}
    bones=[dict(id='torso',role='UPPER_BODY',head=[543,760],tail=[543,430],drawables=[meshes['body']],minAngle=0,maxAngle=0)]
    for suffix,side,sign,points in [
        ('r','RIGHT',1,[[393,450],[315,700],[210,945],[165,1060]]),
        ('l','LEFT',-1,[[693,450],[771,700],[876,945],[921,1060]])
    ]:
        for i,(role,name,layername) in enumerate([('UPPER_ARM','upper','upper'),('FOREARM','fore','forearm'),('HAND','hand','hand')]):
            bones.append(dict(id=f'{name}_{suffix}',role=role,side=side,parent='torso' if i==0 else f'{["upper","fore"][i-1]}_{suffix}',head=points[i],tail=points[i+1],drawables=[meshes[f'{layername}-{side.lower()}']],direction=sign,minAngle=-150,maxAngle=150,blendWidth=12,ik=dict(chainLength=3,iterations=128,tolerancePx=1,bendDirection=0)))
    spec=dict(version=11,enabled=True,symmetryAxisX=543,bones=bones,sampling=dict(tolerancePx=1,minimumStepDegrees=7.5,maxMeshKeyforms=600,jointMeshSegments=16))
    client.edit('skeleton_put',spec=spec)
    client.edit('project_save_as',path=str(ROOT/'authoring/arm-spike-segmented.psd2live'))
    poses={}
    for name,target in [('chin',[510,350]),('index',[290,300])]:
        poses[name]=client.call('skeleton_pose',dict(bone_id='hand_r',target=target,ik=True))[0]['values']
    (ROOT/'reports/g1/arm-segmented-ik.json').write_text(json.dumps(poses,indent=2),encoding='utf-8')
    for name,parameters in {'neutral':{},**poses}.items():
        result,images=client.call('view_render_model',dict(viewport=dict(mode='canvas_rect',left=0,top=0,width=1086,height=1448),parameters=parameters,target_long_edge=1200))
        (ROOT/f'reports/g1/arm-segmented-{name}.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        for i,image in enumerate(images): (ROOT/f'reports/g1/arm-segmented-{name}-{i}.png').write_bytes(image)
    print(json.dumps({'meshes':meshes,'poses':poses}))
