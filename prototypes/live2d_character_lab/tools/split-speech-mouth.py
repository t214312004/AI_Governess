"""Native extraction of source mouth and lower lip, without skin-border dilation."""
import json
import numpy as np
from PIL import Image
from scipy import ndimage
from rig import ROOT,connect
out=ROOT/'authoring/speech-face';out.mkdir(exist_ok=True)
source=ROOT.parents[1]/'ai_voice_assistant/assets/states/layers'
def svg(content):return '<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">'+content+'</svg>'
def path(mask):
    rows=[]
    for y in np.flatnonzero(mask.any(axis=1)):
        edges=np.diff(np.pad(mask[y].astype(int),(1,1)));starts=np.flatnonzero(edges==1);ends=np.flatnonzero(edges==-1)
        rows.extend(f'M{x} {y}h{end-x}v1h-{end-x}z' for x,end in zip(starts,ends))
    return ' '.join(rows)
report={}
with connect() as c:
    c.edit('project_open',path=str(ROOT/'authoring/shared-face/materials-irises-v1.psd2live'),discard_unsaved=True)
    c.edit('material_draw',id='speech-transparent',name='speech-transparent',svg=svg(''))
    imported=c.edit('material_import',paths=[str(ROOT/'authoring/shared-face/Mouth.png')])
    accepted_closed=next(item.split(':',1)[1] for item in imported['changed'] if item.startswith('material:'))
    imported=c.edit('material_import',paths=[str(ROOT/'authoring/shared-face/OpenMouth.png')])
    accepted_open=next(item.split(':',1)[1] for item in imported['changed'] if item.startswith('material:'))
    for frame,prefix in [('idle_listen_1','Closed'),('speaking_1','Open')]:
        original='head-original' if prefix=='Closed' else frame+'-head'
        a=np.asarray(Image.open(source/f'{frame}.png').convert('RGB'))[:1024,600:1624].astype(int)
        r,g,b=a.transpose(2,0,1);yy,xx=np.indices(r.shape)
        for part,top,bottom in [('Mouth',556,578 if prefix=='Closed' else 595),('LowerLip',580 if prefix=='Closed' else 596,598 if prefix=='Closed' else 610)]:
            region=(xx>=460)&(xx<=563)&(yy>=top)&(yy<bottom)
            mask=region&(((r<210)&(g<170))|((r-g>30)&(r>180)))
            mask=ndimage.binary_closing(mask,iterations=1)
            mask=ndimage.binary_fill_holes(mask)
            labels,count=ndimage.label(mask);sizes=np.bincount(labels.ravel());sizes[0]=0;mask=labels==sizes.argmax()
            if part=='Mouth' and prefix=='Open':
                # Include white teeth between the continuous upper and lower boundary.
                for x in np.flatnonzero(mask.any(axis=0)):
                    ys=np.flatnonzero(mask[:,x]);mask[ys[0]:ys[-1]+1,x]=True
            name=prefix+part;mask_id='speech-mask-'+name
            drawing=svg('<defs><filter id="edge"><feGaussianBlur stdDeviation="0.45"/></filter></defs><path filter="url(#edge)" fill="white" d="'+path(mask)+'"/>')
            # Preserve the accepted closed-mouth raster exactly, splitting only
            # at transparent rows between the main lip and the lower-lip shadow.
            if prefix=='Closed':
                start,end=(0,580) if part=='Mouth' else (580,1024)
                drawing=svg(f'<rect x="0" y="{start}" width="1024" height="{end-start}" fill="white"/>')
            elif part=='Mouth':
                # Recutting the cavity worsened source fidelity. Retain its existing
                # pixels; only detach the incomplete lower lip below this boundary.
                drawing=svg('<rect x="0" y="0" width="1024" height="595" fill="white"/>')
            (out/f'{name}-mask.svg').write_text(drawing,encoding='utf-8')
            c.edit('material_draw',id=mask_id,name=mask_id,svg=drawing)
            original_id=accepted_closed if prefix=='Closed' else accepted_open if part=='Mouth' else original
            c.edit('material_peel',id=original_id,revealed='speech-transparent',region=mask_id,threshold=[0,.01],core=0,grow=0,close=0,color_match=False,name=name,part_id='speech-'+name,base_id='speech-unused-'+name)
            c.edit('material_export_png',id='speech-'+name,path=str(out/f'{name}.png'))
            image=Image.open(out/f'{name}.png').convert('RGBA');pixels=np.asarray(image)
            assert image.size==(1024,1024) and image.getbbox()
            solid=pixels[:,:,3]==255
            assert np.max(np.abs(pixels[:,:,:3][solid].astype(int)-a[solid]))==0
            report[name]={'source':frame,'bbox':image.getbbox(),'solid_pixels':int(solid.sum()),'solid_rgb_max_error':0}
            print('Extracted',name,image.getbbox(),flush=True)
    c.edit('project_save_as',path=str(out/'materials-mouth-v7.psd2live'))
(ROOT/'reports/g2/speech-mouth-parts.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
