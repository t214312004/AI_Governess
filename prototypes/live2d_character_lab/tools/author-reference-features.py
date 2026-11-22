"""Add original eye/brow/nose/mouth endpoint variants to one shared-head model.

No complete character frames are added. Full-head shape and continuous in-between
animation remain separate acceptance items; this tool preserves feature pixels.
"""
import hashlib,json
from rig import ROOT,connect
source=ROOT.parents[1]/'ai_voice_assistant/assets/states/layers'
regions={'eye_r':dict(left=945,top=355,width=140,height=140),'eye_l':dict(left=1135,top=355,width=140,height=140),'nose':dict(left=1080,top=480,width=80,height=65),'mouth':dict(left=1045,top=545,width=140,height=85)}
paths=sorted(source.glob('*_*.png'))
paths.sort(key=lambda p:(p.stem!='idle_listen_1',p.stem))
unique={};frames={}
for path in paths:
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if digest not in unique: unique[digest]=dict(index=len(unique),path=path)
    frames[path.stem]=unique[digest]['index']
catalog={'source_size':[2236,2024],'regions':regions,'frames':frames,'unique_frames':{str(v['index']):v['path'].stem for v in unique.values()},'status':'feature endpoints only; head contour, occlusions and transition quality are not accepted'}
(ROOT/'design/feature-catalog.json').write_text(json.dumps(catalog,indent=2),encoding='utf-8')
with connect() as client:
    client.edit('project_open',path=str(ROOT/'authoring/face-fidelity-v1.psd2live'))
    client.edit('material_import',paths=[str(v['path']) for v in unique.values()])
    mats=client.call('material_list',dict(limit=256,recursive=True))[0]['items']
    by_name={m['name']:m['id'] for m in mats}
    edits=[]
    def queue(operation,**request): edits.append(dict(operation=operation,request=request))
    def flush(summary):
        if edits:
            client.edit('workspace_apply_edits',summary=summary,edits=list(edits));edits.clear()
    # Underlaps fill antialiased cut boundaries using the same original pixels.
    for name,rect in regions.items():
        expanded=dict(left=rect['left']-2,top=rect['top']-2,width=rect['width']+4,height=rect['height']+4)
        mid=f'under-{name}';queue('material_crop',id=by_name['idle_listen_1'],rect=expanded,name=mid,new_id=mid)
        queue('layer_place',material_id=mid,layer_id=mid,rect=expanded)
        queue('layer_classify',layer_id=mid,role='face_detail',side='none')
    flush('Original-pixel underlaps')
    for entry in unique.values():
        index=entry['index'];frame=entry['path'].stem
        if index==0: continue
        for name,rect in regions.items():
            layer=f'feature-{index}-{name}'
            queue('material_crop',id=by_name[frame],rect=rect,name=layer,new_id=layer)
            queue('layer_place',material_id=layer,layer_id=layer,rect=rect)
            queue('layer_classify',layer_id=layer,role='face_detail',side='none',type='switch',parameter='ParamReferenceFrame',switch_id=index)
        flush('Original feature endpoint: '+frame)
        print('Added original features:',frame,flush=True)
    client.edit('rig_generate')
    objects=[];offset=0
    while True:
        page=client.call('workspace_inspect',dict(scope='objects',limit=64,offset=offset))[0]
        objects.extend(page['items']);offset+=len(page['items'])
        if offset>=page['total'] or not page['items']:break
    for obj in objects:
        lid=obj.get('layerId','')
        if lid.startswith('under-'): queue('layer_draw_order',target=obj['target'],order=0)
        elif lid.startswith('feature-'): queue('layer_draw_order',target=obj['target'],order=970)
    flush('Feature stack order')
    client.edit('project_save_as',path=str(ROOT/'authoring/face-fidelity-v2.psd2live'))
    export=client.edit('project_export_model',output_directory=str(ROOT/'models/face-fidelity'))
    (ROOT/'reports/g2/face-v2-export.json').write_text(json.dumps(export,indent=2),encoding='utf-8')
    print('Exported',len(unique),'unique expression references in one moc3',flush=True)
