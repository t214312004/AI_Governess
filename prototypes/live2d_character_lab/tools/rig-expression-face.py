"""Add reusable eye/brow shape envelopes on top of the accepted v7 rig."""
import json
from PIL import Image
from rig import ROOT,connect
source=ROOT/'authoring/shared-face'
meshes=json.loads((ROOT/'design/speech-face-runtime-map.json').read_text())
fit=json.loads((ROOT/'design/feature-contour-fit.json').read_text())['features']
report={'based_on':'speech-v7','features':{},'scope':'New eye/brow axes only; no raster or accepted-model replacement'}
def shapes(target,name,width,height):
    p=fit[name]['parameters'];gain=1.5
    return [dict(target=target,value=value,operations=[
        dict(type='scale',factors=[1+(p['sx']-1)*gain*value,1+(p['sy']-1)*gain*value],pivot=[.5,.5]),
        dict(type='rotate',degrees=p['degrees']*gain*value,pivot=[.5,.5]),
        dict(type='translate',delta=[p['dx']*gain*value/width,p['dy']*gain*value/height])
    ]) for value in [-1,1]]
with connect() as c:
    c.edit('project_open',path=str(source/'shared-face-rig-v7-speech.psd2live'),discard_unsaved=True)
    for side in ['R','L']:
        eye='ExpressionEye'+side
        c.edit('canvas_warp',id=eye,name='Eye '+side+' expression envelope',meshes=[],add_to='parent_of_deformer',deformer_id='DeformEyeShape'+side,size_strategy='selection_bounds',rows=8,columns=8)
        # All visible eye components move together, including the accepted lid/lash
        # hierarchy. Canvas-space binding preserves existing gaze and blink keyforms.
        c.edit('object_edit_appearance',edits=[dict(action='bind',kind='mesh',id=meshes[name+side].split(':')[1],parent_id=eye,space='canvas') for name in ['Iris','Interior','Fold','ClosedFold']])
        rect=fit['Eye'+side]['roi']
        c.edit('author_axis',parameter=dict(id='ParamEye'+side+'Form',name='Eye '+side+' shape',min=-1,max=1,default=0),shapes=shapes('warp:'+eye,'Eye'+side,rect[2]-rect[0],rect[3]-rect[1]))
        brow='ExpressionBrow'+side
        c.edit('canvas_warp',id=brow,name='Brow '+side+' expression envelope',meshes=[],add_to='parent_of_deformer',deformer_id='DeformBrowShape'+side,size_strategy='selection_bounds',rows=8,columns=8)
        box=Image.open(source/f'Brow{side}.png').getbbox()
        c.edit('author_axis',parameter=dict(id='ParamBrow'+side+'Form',name='Brow '+side+' shape',min=-1,max=1,default=0),shapes=shapes('warp:'+brow,'Brow'+side,box[2]-box[0],box[3]-box[1]))
        report['features'][side]={'eye':c.call('workspace_inspect',dict(target='warp:'+eye))[0],'brow':c.call('workspace_inspect',dict(target='warp:'+brow))[0]}
        print('Authored eye and brow form',side,flush=True)
    c.edit('project_save_as',path=str(source/'shared-face-rig-v8-expression.psd2live'))
    c.edit('project_export_psd',path=str(source/'shared-face-rig-v8-expression.psd'))
    export=c.edit('project_export_model',output_directory=str(ROOT/'models/expression-face'))
    (ROOT/'design/expression-face-runtime-map.json').write_text(json.dumps(meshes,indent=2),encoding='utf-8')
    (ROOT/'reports/g2/expression-face-authoring.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (ROOT/'reports/g2/expression-face-export.json').write_text(json.dumps(export,indent=2),encoding='utf-8')
    print('Exported expression candidate:',len(meshes),'meshes',flush=True)
