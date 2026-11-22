"""Extract and composite native materials; Python only analyses source/mask pixels."""
import json
import numpy as np
from PIL import Image
from rig import ROOT,connect
out=ROOT/'authoring/shared-face'

def document(content):
    return '<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">'+content+'</svg>'

def mask_path(selected):
    runs=[]
    for y in np.flatnonzero(selected.any(axis=1)):
        row=np.pad(selected[y].astype(int),(1,1));starts=np.flatnonzero(np.diff(row)==1);ends=np.flatnonzero(np.diff(row)==-1)
        runs.extend(f'M{x} {y}h{end-x}v1h-{end-x}z' for x,end in zip(starts,ends))
    return '<path fill="white" d="'+' '.join(runs)+'"/>'

generated=out/'iris-complete-v1.png';gen=np.asarray(Image.open(generated).convert('RGBA'));gy,gx=np.where(gen[:,:,3]>64);box=[int(gx.min()),int(gy.min()),int(gx.max()+1),int(gy.max()+1)]
original=np.asarray(Image.open(out/'head-original.png').convert('RGBA'));yy=np.indices(original.shape[:2])[0]
specs={'R':dict(cx=431.5,cy=442,rx=24,ry=30.5),'L':dict(cx=590,cy=442,rx=23.6,ry=30.5)}
full=dict(left=0,top=0,width=1024,height=1024)
with connect() as c:
    c.edit('project_open',path=str(out/'materials-eye-window-v1.psd2live'),discard_unsaved=True)
    c.edit('material_set_placement',id='head-original',canvas_rect=full)
    def draw(id,content):
        c.edit('material_draw',id=id,name=id,svg=document(content))
    def imported(path):
        result=c.edit('material_import',paths=[str(path)])
        return next(x.split(':',1)[1] for x in result['changed'] if x.startswith('material:'))
    def compose(id,items):
        c.edit('material_folder_create',id=id,name=id)
        # The transparent 1024-square canvas guarantees unscaled source coordinates.
        draw(id+'-canvas','<path fill="none" d="M0 0H1024V1024H0Z"/>')
        c.edit('material_move',ids=[id+'-canvas',*items],folder_id=id)
        data,images=c.call('material_preview',dict(id=id,size=1024))
        path=out/(id+'.png');path.write_bytes(images[0])
        image=Image.open(path)
        assert image.size==(1024,1024) and image.getbbox(),(id,image.size,image.getbbox())
        return imported(path)
    draw('iris-transparent','')
    for side,spec in specs.items():
        cx,cy,rx,ry=[spec[k] for k in ['cx','cy','rx','ry']]
        generated_id=imported(generated)
        cap_id='iris-cap-shading-'+side
        c.edit('material_crop',id=generated_id,rect=dict(left=450,top=165,width=400,height=100),new_id=cap_id,name=cap_id)
        c.edit('material_set_placement',id=cap_id,canvas_rect=dict(left=cx-rx,top=cy-ry,width=rx*2,height=440-(cy-ry)))
        normalized=compose('iris-normalized-'+side,[cap_id])
        ellipse=f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="white"/>'
        # Completion supplies ONLY the hidden cap, never a second rim/highlight.
        draw('iris-oval-'+side,f'<defs><clipPath id="cap"><rect x="0" y="0" width="1024" height="440"/></clipPath></defs><g clip-path="url(#cap)">{ellipse}</g>')
        c.edit('material_peel',id=normalized,revealed='iris-transparent',region='iris-oval-'+side,threshold=[0,.01],core=0,grow=0,close=0,color_match=False,name='iris-hidden-'+side,part_id='iris-hidden-'+side,base_id='iris-unused-'+side)
        # A smooth native contour retains the original rim and sole highlight.
        # Row-by-row hard threshold masks caused bright stair-step fringes.
        # Do not bake the original black upper lash into the moving iris.
        selected=(yy>=428)&((yy>=439)|((original[:,:,0]>35)&(original[:,:,1]>18)))
        region='<defs><filter id="soft"><feGaussianBlur stdDeviation="0.45"/></filter><mask id="source" maskUnits="userSpaceOnUse" x="0" y="0" width="1024" height="1024"><g filter="url(#soft)">'+mask_path(selected)+'</g></mask></defs>'
        draw('iris-source-mask-'+side,region+'<g mask="url(#source)">'+ellipse+'</g>')
        c.edit('material_peel',id='head-original',revealed='iris-transparent',region='iris-source-mask-'+side,threshold=[0,.01],core=0,grow=0,close=0,color_match=False,name='iris-visible-'+side,part_id='iris-visible-'+side,base_id='iris-rest-'+side)
        compose('Iris'+side,['iris-hidden-'+side,'iris-visible-'+side])
        c.edit('material_set_placement',id='Interior'+side,canvas_rect=full)
        draw('iris-white-'+side,f'<ellipse cx="{cx}" cy="{cy}" rx="{rx+1.5}" ry="{ry+1}" fill="#fdfcfc"/>')
        compose('Sclera'+side,['Interior'+side,'iris-white-'+side])
        print('Created and verified nonempty iris and sclera',side,flush=True)
    c.edit('project_save_as',path=str(out/'materials-irises-v1.psd2live'))
(ROOT/'design/iris-parts.json').write_text(json.dumps({'generated_alpha_box':box,'generated_shading_crop':[450,165,400,100],'eyes':specs,'visible_source':'idle_listen_1','hidden_completion':'iris-complete-v1.png','status':'candidate, neutral fidelity and gaze extremes require review'},indent=2),encoding='utf-8')
