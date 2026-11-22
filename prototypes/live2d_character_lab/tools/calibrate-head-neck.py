"""Measure local deformation units through the exported Core geometry."""
from rig import ROOT,connect
with connect() as c:
 c.edit('project_open',path=str(ROOT/'authoring/brow-v8-1/shared-face-rig-v8-1-brow.psd2live'),discard_unsaved=True)
 c.edit('canvas_rotation',id='HeadNeckTilt',name='Head tilt around neck',meshes=[],add_to='parent_of_deformer',deformer_id='DeformHeadContainer',origin=[512,750],angle=0,preservePose=True)
 c.edit('author_axis',parameter=dict(id='ParamHeadTilt',name='Head and neck tilt',min=-6,max=6,default=0),shapes=[dict(target='mesh:ArtMeshFace',value=6,operations=[dict(type='translate',delta=[0,0])])])
 c.edit('keyform_apply',changes=[dict(op='seed',target='mesh:ArtMeshFace',key={'ParamHeadTilt':v}) for v in [-6,0,6]])
 c.edit('rig_deform',changes=[dict(target='mesh:ArtMeshFace',key={'ParamHeadTilt':v},operations=[dict(type='translate',delta=d)]) for v,d in [(-6,[0,.001]),(6,[.001,0])]])
 c.edit('project_export_model',output_directory=str(ROOT/'models/head-face'))
print('Calibration export ready')
