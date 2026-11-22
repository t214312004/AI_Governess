"""Keep the accepted eyebrow/hairline attachment while turning the face."""
import hashlib,json,shutil,sys
from rig import ROOT,connect
path=ROOT/'authoring/turn-v10/shared-face-rig-v10-turn.psd2live';backup=ROOT/'authoring/turn-v10/turn-before-brow.psd2live'
if not backup.exists():shutil.copy2(path,backup)
fit=json.loads((ROOT/(sys.argv[1] if len(sys.argv)>1 else 'design/head-turn-brow-constraints.json')).read_text(encoding='utf-8'))
assert fit['modelSha256']==hashlib.sha256((ROOT/'models/turn-face/original.moc3').read_bytes()).hexdigest()
with connect() as c:
 c.edit('project_open',path=str(path),discard_unsaved=True)
 target='mesh:ArtMeshEyebrowR'
 axes=c.call('workspace_inspect',{'target':target})[0]['axes']
 if 'ParamAngleX' not in axes or 'ParamAngleY' not in axes:
  for axis,v in [('ParamAngleX',6),('ParamAngleY',4)]:c.edit('author_axis',parameter={'id':axis},shapes=[dict(target=target,value=v,operations=[dict(type='translate',delta=[0,0])])])
  changes=[dict(op='seed',target=target,key=item['key']) for item in fit['keys']]
  for i in range(0,len(changes),128):c.edit('keyform_apply',changes=changes[i:i+128])
 changes=[dict(target=target,key=item['key'],operations=[dict(type='translate',delta=item['delta'],selection=dict(indices=fit['selected'],soft_radius=fit['softRadius'],falloff='smooth'))]) for item in fit['keys'] if item['key']['ParamAngleX'] or item['key']['ParamAngleY']]
 for i in range(0,len(changes),128):c.edit('rig_deform',changes=changes[i:i+128])
 c.edit('project_save_as',path=str(path))
 c.edit('project_export_model',output_directory=str(ROOT/'models/turn-face'))
print('Authored turning eyebrow attachment constraints')
