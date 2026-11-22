"""Author a reversible arm-rig experiment in the isolated PSD2Live workspace.

Uses native source split and skeleton operations; never rewrites the source PNG.
Run only with the neutral-v2 artwork project loaded. Save a new native project.
"""
import json
from rig import ROOT, connect

with connect() as client:
    overview = client.call('workspace_overview')[0]
    layers = overview['layers']['items']
    if len(layers) != 1 or layers[0]['name'] != 'neutral-source':
        raise RuntimeError('Load the single neutral-source artwork project first')
    splits = [
        (layers[0]['id'], [[399,421],[414,548],[369,684],[302,849],[246,967],[219,1145],[100,1145],[100,750],[200,450]], ['arm-right','body-remainder'], ['arm-right','body-remainder']),
        ('body-remainder', [[687,421],[672,548],[717,684],[784,849],[840,967],[867,1145],[986,1145],[986,750],[886,450]], ['arm-left','body'], ['arm-left','body']),
    ]
    log=[]
    for layer, polygon, names, pieces in splits:
        result=client.edit('source_split_polygon',layer_id=layer,polygon=polygon,names=names,piece_ids=pieces)
        log.append(result)
    client.edit('project_save_as',path=str(ROOT/'authoring/arm-spike.psd2live'))
    result=client.call('workspace_inspect',{'scope':'objects'})[0]
    (ROOT/'reports/g1/arm-objects.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    (ROOT/'reports/g1/arm-splits.json').write_text(json.dumps(log,indent=2),encoding='utf-8')
    print(json.dumps(result)[:12000])
