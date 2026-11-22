"""Read-only pixel, landmark, hash and UTF-8 checks; never edits source artwork."""
import hashlib,json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parents[1]
inventory=json.loads((ROOT/'references/inventory.json').read_text(encoding='utf-8'))
originals=[frame for state in inventory['states'].values() for frame in state['frames']]
unchanged=all(hashlib.sha256((REPO/f['path']).read_bytes()).hexdigest()==f['sha256'] for f in originals)
report={'original_count':len(originals),'original_hashes_unchanged':unchanged,'hands':{}}
assert unchanged,'Original artwork changed'
for name,spec in json.loads((ROOT/'design/hand-source-landmarks.json').read_text(encoding='utf-8')).items():
    original=Image.open(REPO/inventory['source_directory']/(spec['frame']+'.png')).convert('RGBA')
    candidate=Image.open(ROOT/f'authoring/source-parts/{name}-hand-v2.png').convert('RGBA')
    a,b=np.asarray(original),np.asarray(candidate);solid=b[:,:,3]==255
    delta=np.abs(a[:,:,:3].astype(int)-b[:,:,:3].astype(int))[solid]
    points={label:{'source_xy':point,'candidate_alpha':int(b[point[1],point[0],3])} for label,point in spec['landmarks'].items()}
    report['hands'][name]={'source_frame':spec['frame'],'size':candidate.size,'alpha_bbox':candidate.getbbox(),'solid_pixels':int(solid.sum()),'solid_rgb_max_error':int(delta.max()),'solid_rgb_mean_error':float(delta.mean()),'landmarks':points}
    assert delta.max()==0,'Original hand colors changed'
    assert all(v['candidate_alpha']>0 for v in points.values()),'A hand landmark was clipped'
    box=(770,610,975,1090) if name=='index' else (900,610,1150,1060)
    tile=candidate.crop(box);bg=Image.new('RGBA',tile.size,(235,238,233,255));bg.alpha_composite(tile)
    bg.resize((tile.width*3,tile.height*3)).save(ROOT/f'reports/g2/{name}-hand-v2-inspection.png')
utf8=[]
for path in ROOT.rglob('*'):
    relative=path.relative_to(ROOT)
    if any(part in {'vendor','node_modules','dist','.cache','authoring','models','public','__pycache__'} for part in relative.parts):continue
    if path.is_file() and path.suffix in {'.md','.json','.ts','.mjs','.py','.html','.css'}:
        value=path.read_bytes().decode('utf-8',errors='strict');assert '\ufffd' not in value,str(relative);utf8.append(str(relative))
report['utf8_files_checked']=len(utf8)
output=ROOT/'reports/g2/source-integrity.json';output.write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
