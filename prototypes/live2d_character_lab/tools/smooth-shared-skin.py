"""Use one continuous AI underpaint field, preserving original hair, jaw and nose."""
from rig import ROOT,connect
out=ROOT/'authoring/shared-face'
with connect() as c:
    c.edit('project_open',path=str(out/'materials-peeled-v1.psd2live'),discard_unsaved=True)
    mats=c.call('material_list',dict(limit=128))[0]['items'];revealed=next(m['id'] for m in mats if m['name']=='skin-underpaint-normalized-v1')
    # The outer mask remains inside the facial skin. Nose stays original via a hole.
    path='M414 306 Q470 286 542 300 Q570 322 585 348 L608 394 L638 428 L655 453 Q651 510 619 553 Q578 595 522 630 Q462 620 421 578 Q380 535 366 477 L366 445 L382 403 L397 360 Z M489 482 L529 482 L535 542 L486 544 Z'
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024"><path d="{path}" fill="white" fill-rule="evenodd"/></svg>'
    c.edit('material_draw',id='continuous-skin-mask',name='continuous-skin-mask',svg=svg)
    c.edit('material_export_png',id='continuous-skin-mask',path=str(out/'continuous-skin-mask.png'))
    c.edit('material_peel',id='head-original',revealed=revealed,region='continuous-skin-mask',threshold=[0,0.01],grow=0,core=1,close=0,color_match=False,name='comparison-only-facial-delta',part_id='comparison-only-facial-delta',base_id='SharedSkinContinuous')
    c.edit('material_export_png',id='SharedSkinContinuous',path=str(out/'SharedSkinContinuous.png'))
    c.edit('project_save_as',path=str(out/'materials-peeled-v2.psd2live'))
