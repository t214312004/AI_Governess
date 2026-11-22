"""Read-only source-boundary and shared-face asset integrity checks."""
import hashlib,json
import numpy as np
from PIL import Image
from scipy import ndimage
from rig import ROOT
root=ROOT/'authoring/shared-face'
original=np.asarray(Image.open(root/'head-original.png').convert('RGBA'))
skin=np.asarray(Image.open(root/'SharedSkinContinuous.png').convert('RGBA'))
mask=np.asarray(Image.open(root/'continuous-skin-mask.png').convert('RGBA'))[:,:,3]
outside=mask==0
delta=np.abs(original.astype(int)-skin.astype(int))
report={'outside_skin_field_pixels':int(outside.sum()),'outside_skin_field_rgba_max_error':int(delta[outside].max()),'assets':{}}
report['eye_components']={}
for name in ['LashR','LashL','ClosedFoldR','ClosedFoldL']:
    rgba=np.asarray(Image.open(root/f'{name}.png').convert('RGBA'));alpha=rgba[:,:,3]
    labels,count=ndimage.label(alpha>12);sizes=np.bincount(labels.ravel())[1:]
    report['eye_components'][name]={'alpha_threshold':12,'component_pixels_over_3':sorted([int(size) for size in sizes if size>3],reverse=True)}
    if name.startswith('ClosedFold'):
        dark=int(((alpha>12)&(rgba[:,:,0]<180)).sum())
        report['eye_components'][name]['dark_lash_pixels']=dark
        assert dark==0,'Closed skin shading contains black lash pixels'
assert report['outside_skin_field_rgba_max_error']==0,'Original hair/jaw/nose outside the underpaint field changed'
for path in sorted(root.glob('*.png')):
    report['assets'][path.name]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':Image.open(path).size}
(ROOT/'reports/g2/shared-source-integrity.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='assets'},indent=2))
