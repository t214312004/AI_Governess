"""Read-only provenance, accepted-model integrity and local eye-difference checks."""
import hashlib,json
import numpy as np
from PIL import Image
from rig import ROOT
manifest=json.loads((ROOT/'reports/g2/blink-v5-accepted.json').read_text(encoding='utf-8'))
checked=[]
for name,digest in manifest['files'].items():
    if name.startswith(('models/shared-face/','authoring/shared-face/')):
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
        checked.append(name)
report={'accepted_model_and_source_files_unchanged':checked,'parts':{},'eye_regions_vs_v5':{}}
for name in ['IrisR','IrisL','ScleraR','ScleraL']:
    path=ROOT/f'authoring/shared-face/{name}.png';im=Image.open(path).convert('RGBA')
    assert im.size==(1024,1024) and im.getbbox(),name
    report['parts'][name]={'alpha_box':im.getbbox(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
baseline=np.asarray(Image.open(ROOT/'reports/g2/gaze-accepted-open.png').convert('RGB')).astype(int)
candidate=np.asarray(Image.open(ROOT/'reports/g2/gaze-neutral.png').convert('RGB')).astype(int)
for side,(left,top,right,bottom) in {'R':(380,410,480,485),'L':(540,410,650,485)}.items():
    x0,x1=[round((x-300)*900/440) for x in [left,right]]
    y0,y1=[round((y-265)*900/440) for y in [top,bottom]]
    difference=np.abs(baseline[y0:y1,x0:x1]-candidate[y0:y1,x0:x1])
    report['eye_regions_vs_v5'][side]={'source_roi':[left,top,right,bottom],'rgb_mae_255':float(difference.mean()),'pixels_changed_over_8':int((difference.max(axis=2)>8).sum()),'pixels':difference.shape[0]*difference.shape[1]}
report['quality_accepted']=False
(ROOT/'reports/g2/gaze-asset-integrity.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({'accepted_files_unchanged':len(checked),'eye_regions_vs_v5':report['eye_regions_vs_v5']},indent=2))
