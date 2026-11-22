"""Add a neck-based tilt with a continuous pinned neck/shoulder region."""
import json
import numpy as np
from rig import ROOT,connect
out=ROOT/'authoring/head-v9';out.mkdir(exist_ok=True)
points=np.array(json.loads((ROOT/'design/head-tilt-source-geometry.json').read_text(encoding='utf-8'))['0']).reshape(-1,2)
pivot=[512,750];normalized=((np.array(pivot)-points.min(axis=0))/(points.max(axis=0)-points.min(axis=0))).tolist()
values=[-6,-4.5,-3,-1.5,0,1.5,3,4.5,6]
anchors=[int(i) for i,p in enumerate(points) if p[1]>=800]
calibration=json.loads((ROOT/'design/head-neck-calibration.json').read_text(encoding='utf-8'))
base=np.array(calibration['0']).reshape(-1,2)
jacobians=np.stack([(np.array(calibration[str(v)]).reshape(-1,2)-base)/.001 for v in [6,-6]],axis=1)
def correction_operations(degrees):
    angle=np.deg2rad(-degrees);rotation=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
    desired=(points-pivot)@rotation.T+pivot-points
    delta=np.einsum('ij,ijk->ik',desired,np.linalg.inv(jacobians))
    weight=np.clip((points[:,1]-620)/180,0,1)
    weight=weight*weight*(3-2*weight)
    return [dict(type='translate',delta=(delta[i]*weight[i]).tolist(),selection=dict(indices=[i])) for i in range(len(points)) if weight[i]>0]

with connect() as c:
    c.edit('project_open',path=str(ROOT/'authoring/brow-v8-1/shared-face-rig-v8-1-brow.psd2live'),discard_unsaved=True)
    c.edit('canvas_rotation',id='HeadNeckTilt',name='Head tilt around neck',meshes=[],add_to='parent_of_deformer',deformer_id='DeformHeadContainer',origin=pivot,angle=0,preservePose=True)
    c.edit('author_axis',parameter=dict(id='ParamHeadTilt',name='Head and neck tilt',min=-6,max=6,default=0),shapes=[dict(target='mesh:ArtMeshFace',value=6,operations=[dict(type='translate',delta=[0,0])])])
    # Seed the whole grid before deformation: seeding midway after an endpoint
    # was edited would start from its interpolation and apply the transform twice.
    c.edit('keyform_apply',changes=[dict(op='seed',target='mesh:ArtMeshFace',key={'ParamHeadTilt':v}) for v in values])
    # Counter-transform individual vertices in their native local coordinates.
    for v in values:
        if not v: continue
        ops=correction_operations(v)
        changes=[dict(target='mesh:ArtMeshFace',key={'ParamHeadTilt':v},operations=ops[i:i+16]) for i in range(0,len(ops),16)]
        c.edit('rig_deform',changes=changes)
    c.edit('keyform_apply',changes=[dict(op='seed',target='rotation:HeadNeckTilt',key={'ParamHeadTilt':v}) for v in values])
    c.edit('keyform_apply',changes=[dict(op='set',target='rotation:HeadNeckTilt',key={'ParamHeadTilt':v},geometry={'angle':v}) for v in values])
    c.edit('project_save_as',path=str(out/'shared-face-rig-v9-head.psd2live'))
    c.edit('project_export_psd',path=str(out/'shared-face-rig-v9-head.psd'))
    export=c.edit('project_export_model',output_directory=str(ROOT/'models/head-face'))
    (ROOT/'reports/g2/head-neck-authoring.json').write_text(json.dumps({'pivot_source':pivot,'normalized_skin_pivot':normalized,'parameter':'ParamHeadTilt','keys':values,'shoulder_anchor_indices':anchors,'neck_blend_y':[620,800],'method':'per-vertex inverse rotation, calibrated local units; refine against exported Core geometry','export':export},indent=2),encoding='utf-8')
    print('Exported head/neck tilt candidate with 20 original ArtMeshes',flush=True)
