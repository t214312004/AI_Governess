"""Refine neck anchors from measured exported geometry, preserving the original face."""
import json,numpy as np
from rig import ROOT,connect
read=lambda p:json.loads((ROOT/p).read_text(encoding='utf-8'))
points=np.array(read('design/head-tilt-source-geometry.json')['0']).reshape(-1,2)
cal=read('design/head-neck-calibration.json');base=np.array(cal['0']).reshape(-1,2)
jac=np.stack([(np.array(cal[str(v)]).reshape(-1,2)-base)/.001 for v in [6,-6]],axis=1)
samples=read('.cache/neck-mapping.json');pivot=[512,750]
weight=np.clip((points[:,1]-620)/180,0,1);weight=weight*weight*(3-2*weight)
changes=[];errors={}
for key,current in samples.items():
 v=float(key)
 if not v: continue
 a=np.deg2rad(-v);r=np.array([[np.cos(a),-np.sin(a)],[np.sin(a),np.cos(a)]])
 target=base+weight[:,None]*((base-pivot)@r.T+pivot-base)
 actual=(np.array(current).reshape(-1,2)-pivot)@r.T+pivot
 residual=target-actual;delta=np.einsum('ij,ijk->ik',residual,np.linalg.inv(jac))
 errors[key]=float(np.linalg.norm(residual[weight==1],axis=1).max())
 ops=[dict(type='translate',delta=delta[i].tolist(),selection=dict(indices=[i])) for i in range(len(base)) if weight[i]>0]
 changes.extend(dict(target='mesh:ArtMeshFace',key={'ParamHeadTilt':v},operations=ops[i:i+16]) for i in range(0,len(ops),16))
with connect() as c:
 c.edit('project_open',path=str(ROOT/'authoring/head-v9/shared-face-rig-v9-head.psd2live'),discard_unsaved=True)
 for i in range(0,len(changes),128):c.edit('rig_deform',changes=changes[i:i+128])
 c.edit('project_save_as',path=str(ROOT/'authoring/head-v9/shared-face-rig-v9-head.psd2live'))
 c.edit('project_export_psd',path=str(ROOT/'authoring/head-v9/shared-face-rig-v9-head.psd'))
 c.edit('project_export_model',output_directory=str(ROOT/'models/head-face'))
path=ROOT/'reports/g2/head-neck-refinement.json';history=json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
history.append({'before_anchor_error_px':errors});path.write_text(json.dumps(history,indent=2),encoding='utf-8')
print('Refined anchor drift:',errors)
