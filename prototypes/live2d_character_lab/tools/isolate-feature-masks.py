"""Analyze source colors to make native authoring masks, never replacement art."""
import json
import numpy as np
from PIL import Image,ImageDraw
from scipy import ndimage
from rig import ROOT,connect
out=ROOT/'authoring/shared-face';source=ROOT.parents[1]/'ai_voice_assistant/assets/states/layers'
regions=json.loads((ROOT/'design/shared-face-masks.json').read_text(encoding='utf-8'))
specs=[('BrowR','idle_listen_1','BrowR'),('BrowL','idle_listen_1','BrowL'),('EyeR','idle_listen_1','EyeR'),('EyeL','idle_listen_1','EyeL'),('ClosedR','idle_listen_4','EyeR'),('ClosedL','idle_listen_4','EyeL'),('Mouth','idle_listen_1','Mouth'),('OpenMouth','speaking_1','Mouth')]
with connect() as c:
    c.edit('project_open',path=str(out/'materials-complete-v1.psd2live'),discard_unsaved=True)
    mats=c.call('material_list',dict(limit=256,recursive=True))[0]['items'];by_name={m['name']:m['id'] for m in mats};revealed=by_name['skin-underpaint-normalized-v1']
    report={}
    for name,frame,region in specs:
        rgba=np.asarray(Image.open(source/(frame+'.png')).convert('RGBA'))[:1024,600:1624];rgb=rgba[:,:,:3].astype(int);r,g,b=rgb.transpose(2,0,1)
        polygon=Image.new('1',(1024,1024));ImageDraw.Draw(polygon).polygon([tuple(v) for v in regions[region]['points']],fill=1);roi=np.asarray(polygon)
        yy=np.indices((1024,1024))[0]
        dark=(r<210)&(g<170)&(b<155)
        if name.startswith('Brow'):selected=dark&roi
        elif name in ['Mouth','OpenMouth']:
            selected=roi&(dark|((r-g>40)&(r>180))|((r>235)&(g>235)&(b>235)&(yy>560)&(yy<584)))
        else:
            selected=roi&(dark|((r>235)&(g>235)&(b>230)&(yy>425))|((r-g>45)&(r>180)&(yy<435)))
        labels,_=ndimage.label(selected);sizes=np.bincount(labels.ravel());selected&=sizes[labels]>=5
        selected=ndimage.binary_closing(selected,iterations=1)
        selected=ndimage.binary_fill_holes(selected)
        selected=ndimage.binary_dilation(selected,iterations=1)&roi
        # Each row run is a vector mask rectangle. Actual artwork stays in native materials.
        runs=[]
        for y in np.flatnonzero(selected.any(axis=1)):
            row=np.pad(selected[y].astype(int),(1,1));starts=np.flatnonzero(np.diff(row)==1);ends=np.flatnonzero(np.diff(row)==-1)
            runs.extend(f'M{x} {y}h{end-x}v1h-{end-x}z' for x,end in zip(starts,ends))
        svg='<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024"><path fill="white" d="'+' '.join(runs)+'"/></svg>'
        (out/f'mask-{name}.svg').write_text(svg,encoding='utf-8')
        mask='isolate-'+name;c.edit('material_draw',id=mask,name=mask,svg=svg)
        original='head-original' if frame=='idle_listen_1' else frame+'-head'
        eye=name.startswith('Eye') or name.startswith('Closed')
        options=dict(region='mask-'+region,threshold=[10,32],core=0,keep=regions[region]['keep']) if eye else dict(region=mask,threshold=[0,.01],core=1)
        c.edit('material_peel',id=original,revealed=revealed,**options,grow=0,close=0,color_match=False,name='clean-'+name,part_id='clean-'+name,base_id='unused-clean-'+name)
        c.edit('material_export_png',id='clean-'+name,path=str(out/f'{name}.png'))
        report[name]={'source':frame,'selected_pixels':int(selected.sum()),'mask':f'mask-{name}.svg'}
        print('Isolated',name,flush=True)
    c.edit('project_save_as',path=str(out/'materials-isolated-v3.psd2live'))
    (ROOT/'reports/g2/feature-isolation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
