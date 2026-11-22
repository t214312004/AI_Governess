"""Bind two explicit FK/IK chains to the split neutral arm artwork."""
import json
from rig import ROOT, connect

bones=[dict(id='torso',role='UPPER_BODY',head=[543,760],tail=[543,430],drawables=['ArtMeshLayer2'],minAngle=0,maxAngle=0)]
for suffix, side, sign, points, mesh in [
    ('r','RIGHT',1,[[393,450],[315,715],[210,930],[165,1060]],'ArtMeshHandwearR'),
    ('l','LEFT',-1,[[693,450],[771,715],[876,930],[921,1060]],'ArtMeshHandwearL'),
]:
    for i,(role,name) in enumerate([('UPPER_ARM','upper'),('FOREARM','fore'),('HAND','hand')]):
        bones.append(dict(id=f'{name}_{suffix}',role=role,side=side,parent='torso' if i==0 else f'{["upper","fore"][i-1]}_{suffix}',head=points[i],tail=points[i+1],drawables=[mesh] if i==0 else [],direction=sign,minAngle=-120,maxAngle=150,blendWidth=36,ik=dict(chainLength=3,iterations=64,tolerancePx=1,bendDirection=0)))
spec=dict(version=11,enabled=True,symmetryAxisX=543,bones=bones,sampling=dict(tolerancePx=1,minimumStepDegrees=7.5,maxMeshKeyforms=600,jointMeshSegments=16))
with connect() as client:
    result=client.edit('skeleton_put',spec=spec)
    (ROOT/'reports/g1/arm-binding.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    client.edit('project_save')
    overview=client.call('workspace_overview')[0]
    (ROOT/'reports/g1/arm-rig-overview.json').write_text(json.dumps(overview,indent=2),encoding='utf-8')
    poses={}
    for name,target in [('chin',[510,350]),('index',[290,300])]:
        pose=client.call('skeleton_pose',dict(bone_id='hand_r',target=target,ik=True))[0]
        poses[name]=pose
    (ROOT/'reports/g1/arm-ik.json').write_text(json.dumps(poses,indent=2),encoding='utf-8')
    print(json.dumps({'binding':result,'poses':poses}))
