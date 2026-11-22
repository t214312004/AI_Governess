"""Prepare a native, lossless head crop for feature removal and peeling."""
import json
from rig import ROOT,connect
out=ROOT/'authoring/shared-face';out.mkdir(parents=True,exist_ok=True)
with connect() as c:
    c.edit('project_create',width=2236,height=2024)
    c.edit('material_import',paths=[str(ROOT.parents[1]/'ai_voice_assistant/assets/states/layers/idle_listen_1.png')])
    mats=c.call('material_list',dict(limit=64))[0]['items'];original=next(m['id'] for m in mats if m['name']=='idle_listen_1')
    c.edit('material_crop',id=original,rect=dict(left=600,top=0,width=1024,height=1024),name='head-original',new_id='head-original')
    c.edit('material_export_png',id='head-original',path=str(out/'head-original.png'))
    c.edit('project_save_as',path=str(out/'materials-v1.psd2live'))
    (ROOT/'design/shared-face-source.json').write_text(json.dumps(dict(original=original,crop=[600,0,1024,1024],source='idle_listen_1',status='preparing clean shared-face rig'),indent=2),encoding='utf-8')
