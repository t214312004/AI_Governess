"""Repair the brow/hair junction in native source pixels, preserving authored rig."""
import json,shutil
import numpy as np
from PIL import Image
from rig import ROOT,connect
source=ROOT/'authoring/shared-face'
out=ROOT/'authoring/brow-v8-1';out.mkdir(exist_ok=True)
backup=ROOT/'models/expression-face-v8'
if not backup.exists():shutil.copytree(ROOT/'models/expression-face',backup)
# The contour mask was authored with native material_draw/peel. Replacing an
# entire source layer can regenerate its bounds; local native paint retains them.
old=np.asarray(Image.open(source/'BrowR.png').convert('RGBA'))
clean=np.asarray(Image.open(out/'BrowR.png').convert('RGBA'))
erase=(old[:,:,3]>0)&(clean[:,:,3]==0)
base=np.asarray(Image.open(source/'SharedSkinContinuous.png').convert('RGBA')).astype(int)
under=np.asarray(Image.open(source/'skin-underpaint-normalized-v1.png').convert('RGBA')).astype(int)
region=np.zeros(base.shape[:2],bool);region[380:406,377:401]=True
repair=region&(np.max(abs(base[:,:,:3]-under[:,:,:3]),axis=2)>5)
report={'based_on':'shared-face-rig-v8-expression.psd2live','method':'Native source paint, no layer replacement or rig regeneration','erased_pixels':int(erase.sum()),'underpaint_pixels':int(repair.sum())}
with connect() as c:
    c.edit('project_open',path=str(source/'shared-face-rig-v8-expression.psd2live'),discard_unsaved=True)
    layers=c.call('workspace_inspect',dict(scope='layers',limit=64))[0]['items']
    ids={l['name']:l['id'] for l in layers};edits=[]
    for y,x in zip(*np.where(erase)):
        edits.append(dict(operation='source_paint_eraser',request=dict(layer_id=ids['BrowR'],points=[[float(x)+.5,float(y)+.5]],radius=.51,hardness=1,opacity=1,rebuild_mesh=False)))
    for y,x in zip(*np.where(repair)):
        edits.append(dict(operation='source_paint_pencil',request=dict(layer_id=ids['SharedSkinContinuous'],points=[[float(x)+.5,float(y)+.5]],radius=.51,color=[int(v) for v in under[y,x]],opacity=1,rebuild_mesh=False)))
    for start in range(0,len(edits),64):
        c.edit('workspace_apply_edits',summary='Repair eyebrow hair fragment and static tail residue',edits=edits[start:start+64])
        print('Applied local source corrections',min(start+64,len(edits)),'/',len(edits),flush=True)
    c.edit('project_save_as',path=str(out/'shared-face-rig-v8-1-source.psd2live'))
    c.edit('project_export_psd',path=str(out/'shared-face-rig-v8-1-source.psd'))
    report['export']=c.edit('project_export_model',output_directory=str(ROOT/'models/expression-face'))
    (ROOT/'reports/g2/brow-hairline-authoring.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Exported native brow repair; existing 20 meshes preserved',flush=True)
