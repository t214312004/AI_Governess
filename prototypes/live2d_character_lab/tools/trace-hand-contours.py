"""Analyze original pixels to propose native polygon cuts; no replacement art."""
import json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from scipy import ndimage
ROOT=Path(__file__).resolve().parents[1];SOURCE=ROOT.parents[1]/'ai_voice_assistant/assets/states/layers'
specs={
 'index':dict(frame='speaking_1',box=(770,610,975,1085),seeds=[(849,650),(860,710),(921,765),(923,840),(870,885),(870,1000)]),
 'chin':dict(frame='sending_1',box=(900,610,1150,1050),seeds=[(1077,646),(1080,680),(1050,750),(1110,780),(1050,840),(980,980)])
}
def simplify(points,eps):
    if len(points)<3:return points
    a,b=points[0],points[-1];v=b-a
    dist=np.linalg.norm(points-a,axis=1) if np.dot(v,v)==0 else np.abs(v[0]*(a[1]-points[:,1])-(a[0]-points[:,0])*v[1])/np.linalg.norm(v)
    i=int(np.argmax(dist))
    if dist[i]<=eps:return np.array([a,b])
    return np.concatenate([simplify(points[:i+1],eps)[:-1],simplify(points[i:],eps)])
def contour(mask):
    edges={}
    for y,x in np.argwhere(mask):
        for missing,a,b in [(y==0 or not mask[y-1,x],(x,y),(x+1,y)),(x==mask.shape[1]-1 or not mask[y,x+1],(x+1,y),(x+1,y+1)),(y==mask.shape[0]-1 or not mask[y+1,x],(x+1,y+1),(x,y+1)),(x==0 or not mask[y,x-1],(x,y+1),(x,y))]:
            if missing:edges.setdefault(a,[]).append(b)
    loops=[]
    while edges:
        start=next(iter(edges));p=start;loop=[]
        while p in edges:
            loop.append(p);n=edges[p].pop()
            if not edges[p]:del edges[p]
            p=n
            if p==start:break
        loops.append(loop)
    return np.array(max(loops,key=len),dtype=float)
records={}
for name,spec in specs.items():
    rgba=np.asarray(Image.open(SOURCE/(spec['frame']+'.png')).convert('RGBA'))
    x0,y0,x1,y1=spec['box'];crop=rgba[y0:y1,x0:x1];rgb=crop[:,:,:3].astype(int)
    skin=(rgb[:,:,0]>=160)&(rgb[:,:,0]>=rgb[:,:,1])&(rgb[:,:,1]>=rgb[:,:,2]+3)&(crop[:,:,3]>200)
    labels,count=ndimage.label(skin)
    ids={int(labels[y-y0,x-x0]) for x,y in spec['seeds']};ids.discard(0)
    selected=np.isin(labels,list(ids))
    selected=ndimage.binary_closing(selected,iterations=2)
    selected=ndimage.binary_fill_holes(selected)
    selected=ndimage.binary_dilation(selected,iterations=3)
    points=contour(selected)
    far=int(np.argmax(np.linalg.norm(points-points[0],axis=1)))
    for eps in np.linspace(.3,8,155):
        simple=np.concatenate([simplify(points[:far+1],eps)[:-1],simplify(np.concatenate([points[far:],points[:1]]),eps)[:-1]])
        if len(simple)<=32:break
    polygon=(simple+np.array([x0,y0])).astype(int).tolist()
    records[name]=dict(polygon=polygon,vertices=len(polygon),simplification_epsilon=float(eps),skin_components=sorted(ids),frame=spec['frame'])
    im=Image.fromarray(crop);bg=Image.new('RGBA',im.size,(235,238,233,255));bg.alpha_composite(im);bg=bg.resize((im.width*3,im.height*3)).convert('RGB')
    d=ImageDraw.Draw(bg);xy=[((x-x0)*3,(y-y0)*3) for x,y in polygon];d.line(xy+xy[:1],fill='red',width=2)
    for i,(x,y) in enumerate(xy):d.text((x,y),str(i),fill='blue')
    bg.save(ROOT/f'reports/g2/{name}-contour-proposal.png')
    print(name,json.dumps(records[name]),flush=True)
(ROOT/'design/hand-contour-proposals.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
