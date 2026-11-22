"""Native peeling keeps original feature pixels and confines AI underpaint to masks."""
import json
from rig import ROOT,connect
out=ROOT/'authoring/shared-face'
features={
 'BrowR':dict(points=[[383,382],[403,372],[431,370],[450,373],[464,379],[468,392],[444,392],[425,390],[404,394],[381,401]],keep=[[426,382]]),
 'BrowL':dict(points=[[545,376],[559,370],[581,369],[596,372],[606,389],[587,392],[543,392]],keep=[[575,382]]),
 'EyeR':dict(points=[[363,447],[379,414],[400,398],[434,397],[459,402],[476,418],[479,449],[468,478],[440,486],[408,485],[390,474],[376,460]],keep=[[431,447],[425,414],[396,451]]),
 'EyeL':dict(points=[[543,442],[550,416],[571,399],[604,399],[628,410],[653,440],[662,451],[647,478],[617,486],[578,486],[551,471]],keep=[[590,450],[591,413],[623,451]]),
 'Mouth':dict(points=[[462,553],[483,554],[515,554],[550,551],[561,560],[552,577],[538,593],[518,600],[495,600],[478,586],[465,575]],keep=[[510,570],[509,588]])
}
with connect() as c:
    c.edit('project_open',path=str(out/'materials-v1.psd2live'))
    c.edit('material_import',paths=[str(out/'skin-underpaint-v1.png')])
    mats=c.call('material_list',dict(limit=64))[0]['items'];generated=next(m['id'] for m in mats if m['name']=='skin-underpaint-v1')
    _,images=c.call('material_preview',dict(id=generated,size=1024))
    assert len(images)==1
    normalized=out/'skin-underpaint-normalized-v1.png';normalized.write_bytes(images[0])
    c.edit('material_import',paths=[str(normalized)])
    mats=c.call('material_list',dict(limit=64))[0]['items'];revealed=next(m['id'] for m in mats if m['name']=='skin-underpaint-normalized-v1')
    current='head-original';results={}
    for name,spec in features.items():
        points=' '.join(f'{x},{y}' for x,y in spec['points'])
        svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024"><polygon points="{points}" fill="white"/></svg>'
        region=f'mask-{name}';c.edit('material_draw',id=region,name=region,svg=svg)
        base=f'base-after-{name}'
        result=c.edit('material_peel',id=current,revealed=revealed,region=region,threshold=[3,12],grow=0,core=1,close=2,band=20,color_match=False,keep=spec['keep'],name=name,part_id=name,base_id=base)
        results[name]=result;current=base
        c.edit('material_export_png',id=name,path=str(out/f'{name}.png'))
        print('Peeled',name,flush=True)
    c.edit('material_export_png',id=current,path=str(out/'SharedSkin.png'))
    c.edit('project_save_as',path=str(out/'materials-peeled-v1.psd2live'))
    (ROOT/'design/shared-face-masks.json').write_text(json.dumps(features,indent=2),encoding='utf-8')
    (ROOT/'reports/g2/shared-face-peel.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
