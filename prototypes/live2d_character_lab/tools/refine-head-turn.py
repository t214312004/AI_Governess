"""Keep the accepted neck/shoulder pose while retaining small generated head turns."""
import hashlib,json,numpy as np
from rig import ROOT,connect
read=lambda p:json.loads((ROOT/p).read_text(encoding='utf-8-sig'))
capture=read('.cache/head-turn-samples.json')
assert capture['modelSha256']==hashlib.sha256((ROOT/'models/turn-face/original.moc3').read_bytes()).hexdigest(),'Stale geometry capture; resample current export'
samples=capture['samples']
keyid=lambda k:','.join(str(k[p]) for p in ['ParamAngleX','ParamAngleY','ParamHeadTilt'])
current={keyid(s['key']):np.array(s['vertices']).reshape(-1,2) for s in samples}
neutral=current['0,0,0'];weight=np.clip((neutral[:,1]-620)/180,0,1);weight=weight*weight*(3-2*weight)
target_path=ROOT/'design/head-turn-skin-targets.json'
if not target_path.exists():
 targets={}
 for s in samples:
  k=s['key'];raw=current[keyid(k)];base=current[f"0,0,{k['ParamHeadTilt']}"]
  targets[keyid(k)]=(raw-weight[:,None]*(raw-base)).flatten().tolist()
 target_path.write_text(json.dumps(targets),encoding='utf-8')
targets=read('design/head-turn-skin-targets.json')
cal=read('design/head-neck-calibration.json');base=np.array(cal['0']).reshape(-1,2)
jac=np.stack([(np.array(cal[str(v)]).reshape(-1,2)-base)/.001 for v in [6,-6]],axis=1)
changes=[];max_before=0
for s in samples:
 k=s['key'];z=k['ParamHeadTilt']
 if k['ParamAngleX']==0 and k['ParamAngleY']==0:continue
 actual=current[keyid(k)];target=np.array(targets[keyid(k)]).reshape(-1,2);residual=target-actual
 max_before=max(max_before,float(np.linalg.norm(residual[weight==1],axis=1).max()))
 angle=np.deg2rad(z);r=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
 delta=np.einsum('ij,ijk->ik',residual@r,np.linalg.inv(jac))
 ops=[dict(type='translate',delta=delta[i].tolist(),selection=dict(indices=[i])) for i in range(len(base)) if weight[i]>0]
 changes.extend(dict(target='mesh:ArtMeshFace',key=k,operations=ops[i:i+16]) for i in range(0,len(ops),16))
with connect() as c:
 c.edit('project_open',path=str(ROOT/'authoring/turn-v10/shared-face-rig-v10-turn.psd2live'),discard_unsaved=True)
 # Commit whole poses atomically: slicing a pose between requests temporarily
 # leaves neighboring vertices uncorrected and can fold narrow triangles.
 groups={}
 for change in changes:groups.setdefault(keyid(change['key']),[]).append(change)
 batches=[];batch=[]
 for group in groups.values():
  if len(batch)+len(group)>128:batches.append(batch);batch=[]
  batch.extend(group)
 if batch:batches.append(batch)
 for index,batch in enumerate(batches):
  try:c.edit('rig_deform',changes=batch)
  except Exception as e:
   (ROOT/'.cache/turn-deform-error.json').write_text(json.dumps({'batch':index,'detail':getattr(e,'detail',str(e))},indent=2),encoding='utf-8');raise
  print('Corrected batch',index+1,'of',len(batches),flush=True)
 c.edit('project_save_as',path=str(ROOT/'authoring/turn-v10/shared-face-rig-v10-turn.psd2live'))
 c.edit('project_export_model',output_directory=str(ROOT/'models/turn-face'))
path=ROOT/'reports/g2/head-turn-refinement.json';history=json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
history.append({'max_before_anchor_error_px':max_before,'changes':len(changes)});path.write_text(json.dumps(history,indent=2),encoding='utf-8')
print('Corrected combined neck keys; before max anchor drift',max_before,flush=True)
