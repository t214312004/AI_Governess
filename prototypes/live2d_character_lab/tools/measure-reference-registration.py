"""Read-only image registration analysis; produces numbers, not replacement art."""
import hashlib,json,math
from pathlib import Path
import numpy as np
from PIL import Image
from scipy.ndimage import map_coordinates
from scipy.optimize import minimize
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT.parents[1]/'ai_voice_assistant/assets/states/layers'
def read(path):
    data=np.asarray(Image.open(path).convert('RGBA'),dtype=np.float32)
    return data[:,:,:3]*(data[:,:,3:4]/255)+238*(1-data[:,:,3:4]/255)
base=read(SOURCE/'idle_listen_1.png')
y,x=np.mgrid[130:730:4,830:1405:4];mask=~(((x>930)&(x<1290)&(y>345)&(y<505))|((x>1030)&(x<1200)&(y>530)&(y<660)))
x=x[mask].astype(float);y=y[mask].astype(float);cx,cy=1118,420
records={};cache={}
for path in sorted(SOURCE.glob('*_*.png')):
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if digest in cache: records[path.stem]={**cache[digest],'duplicate_of':cache[digest]['reference']};continue
    target=read(path)[y.astype(int),x.astype(int)]
    def cost(p):
        sx,sy,angle,dx,dy=p;co,si=math.cos(angle),math.sin(angle)
        xx=x-cx-dx;yy=y-cy-dy
        px=(co*xx+si*yy)/sx+cx;py=(-si*xx+co*yy)/sy+cy
        actual=np.stack([map_coordinates(base[:,:,c],[py,px],order=1,mode='constant',cval=238,prefilter=False) for c in range(3)],axis=1)
        return np.mean(np.minimum(np.abs(actual-target),70))
    initial=[1,1,0,0,0]
    result=minimize(cost,initial,method='Powell',bounds=[(.9,1.1),(.9,1.1),(-.12,.12),(-35,35),(-35,35)],options={'maxiter':35,'xtol':1e-5,'ftol':1e-6})
    item=dict(reference=path.stem,scale_x=float(result.x[0]),scale_y=float(result.x[1]),rotation_degrees=float(np.degrees(result.x[2])),delta_x=float(result.x[3]),delta_y=float(result.x[4]),pivot=[cx,cy],masked_mae_before=float(cost(initial)),masked_mae_after=float(result.fun),optimizer_success=bool(result.success))
    records[path.stem]=item;cache[digest]=item
    print(path.stem,round(item['masked_mae_before'],2),'->',round(item['masked_mae_after'],2),flush=True)
target=ROOT/'design/reference-registration.json';target.write_text(json.dumps(records,indent=2),encoding='utf-8')
