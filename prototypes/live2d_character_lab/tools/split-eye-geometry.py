"""Native eye masks and source-pixel extraction; bitmap analysis only in Python."""
import json
import numpy as np
from PIL import Image,ImageDraw
from scipy import ndimage
from rig import ROOT,connect
out=ROOT/'authoring/shared-face'
paths={
 'R':'M390 448 Q402 430 424 427 Q450 426 476 450 Q465 480 435 480 Q407 483 390 448Z',
 'L':'M546 449 Q562 429 585 427 Q614 428 635 448 Q631 477 599 480 Q565 482 546 449Z'
}
def svg(path):return f'<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024"><path fill="white" d="{path}"/></svg>'
with connect() as c:
    c.edit('project_open',path=str(out/'materials-isolated-v3.psd2live'),discard_unsaved=True)
    mats=c.call('material_list',dict(limit=256,recursive=True))[0]['items'];revealed=next(m['id'] for m in mats if m['name']=='skin-underpaint-normalized-v1')
    rgba=np.asarray(Image.open(out/'head-original.png').convert('RGBA'));r,g,b=rgba[:,:,:3].astype(int).transpose(2,0,1);yy,xx=np.indices(r.shape)
    for side,path in paths.items():
        mask='EyeWindow'+side;c.edit('material_draw',id=mask,name=mask,svg=svg(path));c.edit('material_export_png',id=mask,path=str(out/f'{mask}.png'))
        c.edit('material_peel',id='head-original',revealed=revealed,region=mask,threshold=[0,.01],core=1,grow=0,close=0,color_match=False,name='Interior'+side,part_id='Interior'+side,base_id='unused-interior'+side)
        c.edit('material_export_png',id='Interior'+side,path=str(out/f'Interior{side}.png'))
        interior=np.asarray(Image.open(out/f'{mask}.png').convert('RGBA'))[:,:,3]>8
        roi=(yy>=408)&(yy<=483)&(xx>=(364 if side=='R' else 542))&(xx<=(478 if side=='R' else 656))
        hair_free=(xx>=np.maximum(364,385-(yy-408)*.55)) if side=='R' else (xx<=np.minimum(656,620+(yy-408)*.9))
        selected=(r<160)&(g<130)&(b<130)&roi&~interior&hair_free
        # Two pixels of overlap prevent an antialias crack between adjacent meshes.
        selected=ndimage.binary_dilation(selected,iterations=2)&roi&hair_free
        runs=[]
        for y in np.flatnonzero(selected.any(axis=1)):
            row=np.pad(selected[y].astype(int),(1,1));starts=np.flatnonzero(np.diff(row)==1);ends=np.flatnonzero(np.diff(row)==-1)
            runs.extend(f'M{x} {y}h{end-x}v1h-{end-x}z' for x,end in zip(starts,ends))
        mask='lash-mask-'+side;c.edit('material_draw',id=mask,name=mask,svg=svg(' '.join(runs)))
        lash_seed=[451,430] if side=='R' else [635,428]
        c.edit('material_peel',id='head-original',revealed=revealed,region=mask,threshold=[0,.01],core=1,grow=0,close=0,color_match=False,keep=[lash_seed],name='Lash'+side,part_id='Lash'+side,base_id='unused-lash'+side)
        c.edit('material_export_png',id='Lash'+side,path=str(out/f'Lash{side}.png'))
        # Keep only the closed-eye lash from the source, not surrounding skin patches.
        original=ROOT.parents[1]/'ai_voice_assistant/assets/states/layers/idle_listen_4.png'
        closed=np.asarray(Image.open(original).convert('RGBA'))[:1024,600:1624,:3].astype(int)
        selected=(closed[:,:,0]<80)&(closed[:,:,1]<60)&(closed[:,:,2]<60)&roi&hair_free&(yy>=440)&(yy<=476)
        selected=ndimage.binary_dilation(selected,iterations=2)&roi&hair_free
        runs=[]
        for y in np.flatnonzero(selected.any(axis=1)):
            row=np.pad(selected[y].astype(int),(1,1));starts=np.flatnonzero(np.diff(row)==1);ends=np.flatnonzero(np.diff(row)==-1)
            runs.extend(f'M{x} {y}h{end-x}v1h-{end-x}z' for x,end in zip(starts,ends))
        cmask='closed-mask-'+side;c.edit('material_draw',id=cmask,name=cmask,svg=svg(' '.join(runs)))
        c.edit('material_peel',id='idle_listen_4-head',revealed=revealed,region=cmask,threshold=[12,50],core=0,grow=0,close=0,color_match=False,keep=[[425,467] if side=='R' else [598,467]],name='ClosedClean'+side,part_id='ClosedClean'+side,base_id='unused-closed'+side)
        c.edit('material_export_png',id='ClosedClean'+side,path=str(out/f'Closed{side}.png'))
        fold='M382 432 Q396 402 425 402 Q458 402 471 432 Q452 413 425 411 Q403 412 382 432Z' if side=='R' else 'M546 430 Q555 400 588 401 Q620 402 633 430 Q611 412 587 410 Q562 412 546 430Z'
        fmask='fold-mask-'+side;c.edit('material_draw',id=fmask,name=fmask,svg=svg(fold))
        c.edit('material_peel',id='head-original',revealed=revealed,region=fmask,threshold=[25,65],core=0,grow=0,close=0,color_match=False,name='Fold'+side,part_id='Fold'+side,base_id='unused-fold'+side)
        c.edit('material_export_png',id='Fold'+side,path=str(out/f'Fold{side}.png'))
        cr,cg,cb=closed.transpose(2,0,1)
        boundary=[(373,440),(400,446),(434,445),(457,437),(470,439),(474,452),(446,460),(406,461),(374,452)] if side=='R' else [(545,440),(560,438),(587,445),(617,443),(638,436),(648,436),(646,451),(616,459),(582,460),(547,453)]
        roi_image=Image.new('1',(1024,1024));ImageDraw.Draw(roi_image).polygon(boundary,fill=1);lower=np.asarray(roi_image)
        upper=(yy>=400)&(yy<=438)&(xx>=(420 if side=='R' else 551))&(xx<=(474 if side=='R' else 609))
        selected=(cr>230)&(cr-cg>18)&(lower|upper)
        # Expansion must not import adjacent black lash pixels into pink skin shading.
        selected=ndimage.binary_dilation(selected,iterations=1)&(lower|upper)&(cr>230)
        runs=[]
        for y in np.flatnonzero(selected.any(axis=1)):
            row=np.pad(selected[y].astype(int),(1,1));starts=np.flatnonzero(np.diff(row)==1);ends=np.flatnonzero(np.diff(row)==-1)
            runs.extend(f'M{x} {y}h{end-x}v1h-{end-x}z' for x,end in zip(starts,ends))
        mask='closed-fold-mask-'+side;c.edit('material_draw',id=mask,name=mask,svg=svg(' '.join(runs)))
        fold_seeds=[[454,418],[430,451]] if side=='R' else [[575,418],[592,450]]
        c.edit('material_peel',id='idle_listen_4-head',revealed=revealed,region=mask,threshold=[8,45],core=0,grow=0,close=0,color_match=False,keep=fold_seeds,name='ClosedFold'+side,part_id='ClosedFold'+side,base_id='unused-closed-fold'+side)
        c.edit('material_export_png',id='ClosedFold'+side,path=str(out/f'ClosedFold{side}.png'))
        print('Split eye window / interior / lash',side,flush=True)
    c.edit('project_save_as',path=str(out/'materials-eye-window-v1.psd2live'))
    (ROOT/'design/eye-windows.json').write_text(json.dumps(paths,indent=2),encoding='utf-8')
