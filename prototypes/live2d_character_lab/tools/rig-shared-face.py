"""Build semantic controls from reviewed shared-face source parts."""
import json,argparse
from PIL import Image
from rig import ROOT,connect
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--gaze',action='store_true',help='Export a separate iris/gaze candidate, preserving accepted v5')
parser.add_argument('--speech',action='store_true',help='Export mouth/lower-lip refinement as a separate candidate')
args=parser.parse_args();speech=args.speech;gaze=args.gaze or speech
model_name='speech-face' if speech else 'gaze-face' if gaze else 'shared-face'
version='v7-speech' if speech else 'v6-gaze' if gaze else 'v5'
out=ROOT/'authoring/shared-face'
roles=[('SharedSkinContinuous','face','none'),('BrowR','eyebrow','right'),('BrowL','eyebrow','left'),('EyeR','eyelash','right'),('EyeL','eyelash','left'),('ClosedR','eye_close','right'),('ClosedL','eye_close','left'),('Mouth','mouth_close','none'),('OpenMouth','mouth_open','none')]
roles += [(f'EyeWindow{s}','eyewhite',side) for s,side in [('R','right'),('L','left')]]
roles += [(f'Interior{s}','face_detail','none') for s in ['R','L']]
roles += [(f'Fold{s}','face_detail','none') for s in ['R','L']]
roles += [(f'ClosedFold{s}','face_detail','none') for s in ['R','L']]
if gaze:roles += [(f'Iris{s}','face_detail','none') for s in ['R','L']]
if speech:roles += [('LowerLip','face_detail','none')]
def source(name):
    if name in ['EyeR','EyeL']:return 'Lash'+name[-1]
    if gaze and name.startswith('Interior'):return 'Sclera'+name[-1]
    return name
def source_path(name):
    if speech and name in ['Mouth','OpenMouth','LowerLip']:
        filename={'Mouth':'ClosedMouth','OpenMouth':'OpenMouth','LowerLip':'ClosedLowerLip'}[name]
        return ROOT/f'authoring/speech-face/{filename}.png'
    return out/f'{source(name)}.png'
with connect() as c:
    c.edit('project_open',path=str(out/('materials-irises-v1.psd2live' if gaze else 'materials-eye-window-v1.psd2live')),discard_unsaved=True)
    c.edit('project_create_artwork',width=1024,height=1024,layers=[dict(path=str(source_path(name)),name=name,role=role,side=side) for name,role,side in roles])
    c.edit('settings_update',changes=dict(mouthOutlineEnabled=False,seeThroughBrows=False,seeThroughEyes=False))
    c.edit('rig_generate')
    objects=c.call('workspace_inspect',dict(scope='objects',limit=64))[0]['items'];meshes={o['name']:o['target'] for o in objects if o['target'].startswith('mesh:')}
    # Keep iris texture undistorted while the eye window closes over it.
    static=[]
    for name,target in meshes.items():
        order=0 if name=='SharedSkinContinuous' else 30 if name.startswith('EyeWindow') else 31 if name.startswith('Interior') else 39 if name.startswith('Fold') else 40 if name.startswith('Eye') else 45 if name.startswith('Closed') else 50 if name.startswith('Brow') else 60
        edit=dict(action='static',kind='mesh',id=target.split(':')[1],draw_order=order)
        if name.startswith('Iris'):edit['draw_order']=32
        if name.startswith(('Interior','Iris')):edit['masked_by']=[meshes['EyeWindow'+name[-1]].split(':')[1]]
        static.append(edit)
    c.edit('rig_edit_structure',edits=static)
    for side in ['R','L']:
        axis=f'ParamEye{side}Open'
        for name in ['Eye'+side,'EyeWindow'+side]:
            c.edit('keyform_apply',changes=[dict(op='copy',target=meshes[name],key={axis:0},**{'from':{axis:1}})])
        # One shared deformation, not two scales about different mesh bounds.
        # The iris stays outside this warp; only its visible mask follows the lash.
        warp='SharedLid'+side
        c.edit('rig_create_warp',id=warp,name='Shared lid and lash '+side,targets=[meshes['Eye'+side],meshes['EyeWindow'+side]],rows=8,columns=8,fit_local=True)
        c.edit('author_axis',parameter=dict(id=axis),shapes=[dict(target='warp:'+warp,value=0,operations=[dict(type='scale',factors=[1,.025],pivot=[.5,.7])])])
        # Introduce the closed stroke as a narrow line, then thicken it into the
        # source shape. Fading in a full-size closed eye caused gray double lashes.
        closed=meshes['Closed'+side]
        c.edit('keyform_apply',changes=[dict(op='seed',target=closed,key={axis:value}) for value in [0,.16,1]])
        c.edit('rig_deform',changes=[dict(target=closed,key={axis:value},operations=[dict(type='scale',factors=[1,.08],pivot=[.5,.5]),dict(type='translate',delta=[0,-.2 if side=='R' else -.15])]) for value in [.16,1]])
        for name,keys in [('Closed'+side,[(0,1),(.14,1),(.16,0),(1,0)]),('Eye'+side,[(0,0),(.12,0),(.16,1),(1,1)]),('EyeWindow'+side,[(0,0),(1,0)]),('Interior'+side,[(0,0),(.02,1),(1,1)])]:
            c.edit('keyform_apply',changes=[dict(op='set',target=meshes[name],key={axis:v},channels={'opacity':opacity}) for v,opacity in keys])
        # Open-eye crease follows the upper lid down, flattens, then disappears.
        # Closed-eye source has a separate lower pink lid shadow, not that crease.
        c.edit('author_axis',parameter=dict(id=axis),shapes=[dict(target=meshes['Fold'+side],value=0,operations=[dict(type='scale',factors=[1,.4],pivot=[.5,.5]),dict(type='translate',delta=[0,1.2])])])
        for name,keys in [('Fold'+side,[(0,0),(.15,0),(.5,.7),(1,1)]),('ClosedFold'+side,[(0,1),(.2,0),(1,0)])]:
            c.edit('keyform_apply',changes=[dict(op='set',target=meshes[name],key={axis:v},channels={'opacity':opacity}) for v,opacity in keys])
    for side in ['R','L']:
        # Generated downward travel cannot reach the original closed-eye brow.
        # Extend that local shape while preserving the neutral and upper endpoint.
        c.edit('author_axis',parameter=dict(id=f'ParamBrow{side}Y'),shapes=[dict(target=meshes['Brow'+side],value=-1,operations=[dict(type='translate',delta=[0,.3])])])
        c.edit('author_axis',parameter=dict(id=f'ParamBrow{side}Angle',min=-1,max=1,default=0),shapes=[dict(target=meshes['Brow'+side],value=v,operations=[dict(type='rotate',degrees=v*12,pivot=[.5,.5])]) for v in [-1,1]])
    # Anchor the opening near the original upper lip, avoiding a sliding mouth.
    c.edit('keyform_apply',changes=[dict(op='copy',target=meshes['OpenMouth'],key={'ParamMouthOpenY':v,'ParamMouthForm':f},**{'from':{'ParamMouthOpenY':1,'ParamMouthForm':0}}) for v in [0,.5] for f in [-1,0,1]])
    c.edit('rig_deform',changes=[dict(target=meshes['OpenMouth'],key={'ParamMouthOpenY':v,'ParamMouthForm':f},operations=[dict(type='scale',factors=[.96+.04*v,.025+.975*v],pivot=[.5,.25])]) for v in [0,.5] for f in [-1,0,1]])
    # The generated parameter exists but does not deform these source mouth meshes.
    # Author both corners at every existing opening key, keeping neutral untouched.
    shapes=[]
    for name in ['Mouth','OpenMouth']:
        for opening in [0,.5,1]:
            for value in [-1,1]:
                shapes.append(dict(target=meshes[name],value=value,key={'ParamMouthOpenY':opening},operations=[
                    dict(type='translate',delta=[0,-.16*value],selection=dict(center=[x,.45],radius=.42,feather=.25)) for x in [.05,.95]
                ]))
    c.edit('author_axis',parameter=dict(id='ParamMouthForm'),shapes=shapes)
    # Suppress the compressed open-mouth mesh at closure; do not leave a thin line.
    # Opacity has both opening and form axes: cover the entire grid, not just form=0.
    for name,keys in [('OpenMouth',[(0,0),(.15,1),(1,1)]),('Mouth',[(0,1),(.15,0),(1,0)])]:
        c.edit('keyform_apply',changes=[dict(op='set',target=meshes[name],key={'ParamMouthOpenY':v,'ParamMouthForm':form},channels={'opacity':opacity}) for v,opacity in keys for form in [-1,0,1]])
    if gaze:
        for side in ['R','L']:
            target=meshes['Iris'+side]
            box=Image.open(out/f'Iris{side}.png').getbbox();width=box[2]-box[0];height=box[3]-box[1]
            c.edit('author_axis',parameter=dict(id='ParamEyeBallX'),shapes=[dict(target=target,value=v,operations=[dict(type='translate',delta=[v*6/width,0])]) for v in [-1,1]])
            c.edit('author_axis',parameter=dict(id='ParamEyeBallY'),shapes=[dict(target=target,value=v,key={'ParamEyeBallX':x},operations=[dict(type='translate',delta=[0,-v*4/height])]) for x in [-1,0,1] for v in [-1,1]])
            # Cover the full combined grid: no early fading when looking sideways.
            c.edit('keyform_apply',changes=[dict(op='set',target=target,key={f'ParamEye{side}Open':opening,'ParamEyeBallX':x,'ParamEyeBallY':y},channels={'opacity':opacity}) for opening,opacity in [(0,0),(.02,1),(1,1)] for x in [-1,0,1] for y in [-1,0,1]])
    if speech:
        # The lower lip follows jaw opening; it is never flattened with the cavity.
        lip=meshes['LowerLip'];closed_box=Image.open(source_path('LowerLip')).getbbox();open_box=Image.open(ROOT/'authoring/speech-face/OpenLowerLip.png').getbbox()
        cw,ch=closed_box[2]-closed_box[0],closed_box[3]-closed_box[1];ow,oh=open_box[2]-open_box[0],open_box[3]-open_box[1]
        dx=((open_box[0]+open_box[2])-(closed_box[0]+closed_box[2]))/2
        dy=((open_box[1]+open_box[3])-(closed_box[1]+closed_box[3]))/2
        c.edit('keyform_apply',changes=[dict(op='seed',target=lip,key={'ParamMouthOpenY':v}) for v in [0,1]])
        c.edit('rig_deform',changes=[dict(target=lip,key={'ParamMouthOpenY':1},operations=[dict(type='scale',factors=[ow/cw,oh/ch],pivot=[.5,.5]),dict(type='translate',delta=[dx/cw,dy/ch])])])
        # Main lips share one width warp; the lower-lip warp keeps its opening keys.
        for warp,targets in [('SpeechMouthWidth',[meshes['Mouth'],meshes['OpenMouth']]),('SpeechLipWidth',[lip])]:
            c.edit('rig_create_warp',id=warp,name=warp,targets=targets,rows=8,columns=8,fit_local=True)
            c.edit('author_axis',parameter=dict(id='ParamMouthWidth',name='Mouth width',min=-1,max=1,default=0),shapes=[dict(target='warp:'+warp,value=v,operations=[dict(type='scale',factors=[1+.18*v,1],pivot=[.5,.5])]) for v in [-1,1]])
    c.edit('project_save_as',path=str(out/f'shared-face-rig-{version}.psd2live'))
    c.edit('project_export_psd',path=str(out/f'shared-face-rig-{version}.psd'))
    export=c.edit('project_export_model',output_directory=str(ROOT/f'models/{model_name}'))
    overview=c.call('workspace_overview')[0]
    (ROOT/f'reports/g2/{model_name}-export.json').write_text(json.dumps(export,indent=2),encoding='utf-8')
    (ROOT/f'reports/g2/{model_name}-overview.json').write_text(json.dumps(overview,indent=2),encoding='utf-8')
    (ROOT/f'design/{model_name}-runtime-map.json').write_text(json.dumps(meshes,indent=2),encoding='utf-8')
    print('Exported semantic shared-face rig:',len(meshes),'meshes',flush=True)
