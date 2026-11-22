"""Select visible background spill in the original hair silhouette for native erasure."""
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage
ROOT=Path(__file__).resolve().parents[1]
import json
source=np.asarray(Image.open(ROOT/'authoring/shared-face/SharedSkinContinuous.png').convert('RGBA')).astype(int)
r,g,b,a=source.transpose(2,0,1)
y,x=np.indices(a.shape)
# Restrict warm-yellow removal to the right temple and lower curls, outside the face.
curls=((x<330)&(y>530))|((x>595)&(y>540))|((x>735)&(y>340))
outer=((x<345)|(x>635)|(y<270)|(y>675))&(y<748)
spill=(a>0)&outer&(((g>r)&(g>b))|(curls&(g-b>40)&(r-b>40)&(g>=r*.90)))
# The cutout has detached flecks outside the hair and around the neckline.
labels,n=ndimage.label(a>0,structure=np.ones((3,3)))
counts=np.bincount(labels.ravel())
flecks=(labels>0)&(counts[labels]<=65)&outer
# Preserve the dark ink immediately bordering warm hair. Farther out, remove
# isolated dark matte fragments along with the colored pixels that surround them.
hair_ink=(a>128)&(r>g+3)&(r>b+3)&(~spill)
# Reconstruct a soft ink boundary from the hair side of each contaminated curl.
# Outside these zones, preserve connected outlines and remove detached flecks only.
zones=(((x>731)&(x<807)&(y>371)&(y<613))|
       ((x>238)&(x<327)&(y>535)&(y<642))|
       ((x>284)&(x<382)&(y>671)&(y<725))|
       ((x>618)&(x<755)&(y>658)&(y<725)))
near=ndimage.distance_transform_edt(~spill)<10
boundary=ndimage.gaussian_filter(((ndimage.distance_transform_edt(~hair_ink)<2.4)).astype(float),.75)
clean=np.minimum(a,np.rint(255*boundary)).astype(int)
affected=zones&near&(a>0)
result=a.copy()
result[affected]=clean[affected]
result[flecks]=0
tint=affected&spill&(result>0)
# Discard islands left behind when the colored matte was removed.
components,count=ndimage.label(result>=96,structure=np.ones((3,3)))
sizes=np.bincount(components.ravel())
body=components==np.argmax(sizes[1:])+1
isolated=(ndimage.distance_transform_edt(~body)>1.5)&outer
result[isolated]=0
tint&=result>0
rows,cols=np.where((result!=a)|tint)
patch=[[int(X),int(Y),int(result[Y,X]),bool(tint[Y,X])] for Y,X in zip(rows,cols)]
folder=ROOT/'authoring/polish-v11'
folder.mkdir(exist_ok=True)
(folder/'hair-edge-patch.json').write_text(json.dumps(patch,separators=(',',':')),encoding='utf-8')
print(len(patch),'affected source pixels')
