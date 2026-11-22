"""Native hand extraction with original canvas placement and thumb landmarks."""
import argparse,json
from rig import ROOT,connect
source=ROOT.parents[1]/'ai_voice_assistant/assets/states/layers'
out=ROOT/'authoring/source-parts';out.mkdir(parents=True,exist_ok=True)
specs={
 'index':dict(frame='speaking_1',polygon=[[840,626],[854,635],[868,669],[885,745],[898,779],[906,747],[919,729],[931,733],[936,780],[949,825],[947,878],[935,906],[922,923],[920,1000],[924,1059],[905,1079],[875,1082],[845,1073],[823,1059],[830,977],[831,947],[804,911],[786,872],[778,840],[788,814],[804,798],[807,779],[833,764],[850,749],[838,694],[829,649]],landmarks={'index_tip':[841,633],'thumb_tip':[924,734],'thumb_web':[905,790],'wrist':[874,1035]},thumb_note='Original character right hand. Thumb is on screen-right of the raised index, not mirrored.'),
 'chin':dict(frame='sending_1',polygon=[[1058,627],[1095,642],[1126,667],[1126,683],[1133,699],[1138,729],[1141,752],[1137,770],[1122,785],[1119,797],[1108,805],[1103,793],[1096,817],[1084,844],[1069,867],[1056,891],[1034,949],[1009,1045],[976,1035],[944,1019],[917,999],[919,985],[951,930],[973,887],[988,841],[997,791],[1001,740],[1003,697],[1013,675]],landmarks={'index_knuckle':[1059,632],'thumb_tip':[1110,790],'thumb_root':[1121,759],'wrist':[971,1016]},thumb_note='Folded thumb is visible on the screen-right/lower side of the curled fingers; retain the occlusion in the source.'),
}
records={}
proposals=json.loads((ROOT/'design/hand-contour-proposals.json').read_text(encoding='utf-8'))
overrides=json.loads((ROOT/'design/hand-contour-overrides.json').read_text(encoding='utf-8'))
for name,spec in specs.items():
    spec['polygon']=proposals[name]['polygon']
    for vertex,point in overrides.get(name,{}).get('vertices',{}).items(): spec['polygon'][int(vertex)]=point
    spec['mask_revision']='v2: original-pixel contour with manual visual review; no mirroring or warping'
specs['chin']['landmarks']['index_knuckle']=[1077,629]
parser=argparse.ArgumentParser();parser.add_argument('--hand',choices=['index','chin']);args=parser.parse_args()
if args.hand:
    records=json.loads((ROOT/'design/hand-source-landmarks.json').read_text(encoding='utf-8'))
    specs={args.hand:specs[args.hand]}
with connect() as client:
 for name,spec in specs.items():
    imported=client.edit('project_create_artwork',width=2236,height=2024,layers=[dict(path=str(source/(spec['frame']+'.png')),name='HandReference',role='objects')])
    client.edit('source_split_polygon',layer_id=imported['layers'][0],polygon=spec['polygon'],names=[f'{name}-hand','unused'],piece_ids=[f'{name}-hand','unused'])
    client.edit('layer_delete',layer_id='unused')
    client.edit('material_adopt_layers')
    materials=client.call('material_list',dict(limit=100,recursive=True))[0]['items']
    material=next(m for m in materials if m['name']==f'{name}-hand')
    detail=client.call('material_get',dict(id=material['id']))[0]
    client.edit('material_export_png',id=material['id'],path=str(out/f'{name}-hand-v2.png'))
    client.edit('project_export_psd',path=str(out/f'{name}-hand-v2.psd'))
    client.edit('project_save_as',path=str(out/f'{name}-hand-v2.psd2live'))
    records[name]={**spec,'material':detail}
    print(name,json.dumps(detail),flush=True)
(ROOT/'design/hand-source-landmarks.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
