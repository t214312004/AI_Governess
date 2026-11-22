"""Read-only source, accepted checkpoint and mouth-region validation."""
import json,hashlib
import numpy as np
from PIL import Image
from rig import ROOT
report={'accepted_checkpoints':{},'source_parts':{},'source_roi_comparison':{},'quality_accepted':False}
for version in ['blink-v5','gaze-v6']:
    manifest=json.loads((ROOT/f'reports/g2/{version}-accepted.json').read_text(encoding='utf-8'));model_count=0
    for relative,digest in manifest['files'].items():
        backup=ROOT/f'authoring/checkpoints/{version}'/relative
        assert hashlib.sha256(backup.read_bytes()).hexdigest()==digest,relative
        if relative.startswith('models/'):
            assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==digest,relative;model_count+=1
    report['accepted_checkpoints'][version]={'backup_files_verified':len(manifest['files']),'current_model_files_unchanged':model_count}
for name,frame in [('ClosedMouth','idle_listen_1'),('ClosedLowerLip','idle_listen_1'),('OpenMouth','speaking_1'),('OpenLowerLip','speaking_1')]:
    path=ROOT/f'authoring/speech-face/{name}.png';a=np.asarray(Image.open(path).convert('RGBA'));s=np.asarray(Image.open(ROOT.parents[1]/f'ai_voice_assistant/assets/states/layers/{frame}.png').convert('RGBA'))[:1024,600:1624]
    solid=a[:,:,3]==255;delta=np.abs(a[:,:,:3][solid].astype(int)-s[:,:,:3][solid].astype(int));assert delta.max()==0
    report['source_parts'][name]={'solid_pixels':int(solid.sum()),'solid_rgb_max_error':0,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
# Closed parts are a disjoint partition of the accepted closed-mouth asset.
closed=np.asarray(Image.open(ROOT/'authoring/speech-face/ClosedMouth.png').convert('RGBA')).astype(int)
lip=np.asarray(Image.open(ROOT/'authoring/speech-face/ClosedLowerLip.png').convert('RGBA')).astype(int)
old=np.asarray(Image.open(ROOT/'authoring/shared-face/Mouth.png').convert('RGBA')).astype(int)
assert not np.any((closed[:,:,3]>0)&(lip[:,:,3]>0))
combined=closed+lip;visible=old[:,:,3]>0
assert np.array_equal(combined[:,:,3],old[:,:,3]) and np.array_equal(combined[visible],old[visible])
report['closed_source_partition_exact']=True
def composited(im):
    a=np.asarray(im.convert('RGBA')).astype(float);alpha=a[:,:,3:4]/255
    return a[:,:,:3]*alpha+np.array([235,238,233])*(1-alpha)
reference=Image.open(ROOT.parents[1]/'ai_voice_assistant/assets/states/layers/speaking_1.png').crop((900,265,1340,705)).resize((900,900),Image.Resampling.BILINEAR)
reference=composited(reference)
for name,rect in {'oral_cavity':(460,555,565,595),'lower_lip':(487,594,538,611)}.items():
    left,top,right,bottom=rect;x0,x1=[round((x-300)*900/440) for x in [left,right]];y0,y1=[round((y-265)*900/440) for y in [top,bottom]]
    measurements={}
    for label,file in [('v6','speech-v6-open.png'),('v7','speech-open.png')]:
        rendered=composited(Image.open(ROOT/f'reports/g2/{file}'))
        measurements[label]=float(np.abs(rendered[y0:y1,x0:x1]-reference[y0:y1,x0:x1]).mean())
    report['source_roi_comparison'][name]={'source_roi':rect,'rgb_mae_255':measurements,'method':'Fixed source crop, bilinear inspection resampling, same opaque background; diagnostic only'}
(ROOT/'reports/g2/speech-asset-integrity.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({'accepted_checkpoints':report['accepted_checkpoints'],'closed_source_partition_exact':True,'source_roi_comparison':report['source_roi_comparison']},indent=2))
