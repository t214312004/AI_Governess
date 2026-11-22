"""Extend accepted v9 with bounded yaw/pitch and combined neck compensation keys."""
import itertools,json
from rig import ROOT,connect
out=ROOT/'authoring/turn-v10';out.mkdir(exist_ok=True)
rolls=[-6,-4.5,-3,-1.5,0,1.5,3,4.5,6]
keys=[{'ParamAngleX':x,'ParamAngleY':y,'ParamHeadTilt':z} for x,y,z in itertools.product([-6,0,6],[-4,0,4],rolls)]
with connect() as c:
 c.edit('project_open',path=str(ROOT/'authoring/head-v9/shared-face-rig-v9-head.psd2live'),discard_unsaved=True)
 for axis,value in [('ParamAngleX',6),('ParamAngleY',4)]:
  c.edit('author_axis',parameter={'id':axis},shapes=[dict(target='mesh:ArtMeshFace',value=value,operations=[dict(type='translate',delta=[0,0])])])
 c.edit('keyform_apply',changes=[dict(op='seed',target='mesh:ArtMeshFace',key=key) for key in keys])
 c.edit('keyform_apply',changes=[dict(op='delete',target='mesh:ArtMeshFace',parameter=axis,value=value,channel='geometry') for axis,values in [('ParamAngleX',[-45,45]),('ParamAngleY',[-30,30])] for value in values])
 for axis,limit in [('ParamAngleX',6),('ParamAngleY',4)]:
  c.edit('parameter_update',parameter_id=axis,min=-limit,max=limit,default=0)
 c.edit('project_save_as',path=str(out/'shared-face-rig-v10-turn.psd2live'))
 c.edit('project_export_model',output_directory=str(ROOT/'models/turn-face'))
(ROOT/'design/head-turn-keys.json').write_text(json.dumps(keys,indent=2),encoding='utf-8')
print('Seeded',len(keys),'combined yaw/pitch/roll skin keys')
