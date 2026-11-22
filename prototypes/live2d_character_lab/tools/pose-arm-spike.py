"""Two-link wrist targets with a downward elbow branch and explicit palm angle."""
import json
import math
from rig import ROOT, connect

def solve(wrist, palm_degrees):
    shoulder=(393,450); elbow=(315,700); rest_wrist=(210,945)
    first=math.dist(shoulder,elbow); second=math.dist(elbow,rest_wrist)
    dx,dy=wrist[0]-shoulder[0],wrist[1]-shoulder[1]; distance=math.hypot(dx,dy)
    base=math.atan2(dy,dx)
    offset=math.acos(max(-1,min(1,(distance**2+first**2-second**2)/(2*distance*first))))
    angle=max([base+offset,base-offset],key=math.sin)
    joint=(shoulder[0]+first*math.cos(angle),shoulder[1]+first*math.sin(angle))
    fore=math.atan2(wrist[1]-joint[1],wrist[0]-joint[0])
    rest_upper=math.atan2(250,-78); rest_fore=math.atan2(245,-105); rest_hand=math.atan2(115,-45)
    upper=math.degrees(angle-rest_upper)
    while upper < -180: upper+=360
    while upper > 180: upper-=360
    lower=math.degrees(fore-rest_fore)-upper
    while lower < -180: lower+=360
    while lower > 180: lower-=360
    hand=palm_degrees-math.degrees(rest_hand)-upper-lower
    while hand < -180: hand+=360
    while hand > 180: hand-=360
    return dict(ParamArmRA=upper,ParamArmRB=lower,ParamHandR=hand)

poses={'neutral':dict(ParamArmRA=0,ParamArmRB=0,ParamHandR=0),'chin':solve((510,480),-90),'raised':solve((285,440),-90)}
(ROOT/'design/arm-poses.json').write_text(json.dumps(poses,indent=2),encoding='utf-8')
with connect() as client:
    for bone in ['fore_r','hand_r']:
        client.edit('skeleton_bone',bone=dict(id=bone,minAngle=-180,maxAngle=180))
    for target, order in [('ArtMeshLayerR',900),('ArtMeshLayerR2',901),('ArtMeshHandwearR',902)]:
        client.edit('layer_draw_order',target=f'mesh:{target}',order=order)
    client.edit('project_save')
    for name,parameters in poses.items():
        result,images=client.call('view_render_model',dict(viewport=dict(mode='canvas_rect',left=0,top=0,width=1086,height=1448),parameters=parameters,target_long_edge=1200))
        for i,image in enumerate(images): (ROOT/f'reports/g1/arm-posed-{name}-{i}.png').write_bytes(image)
    export=client.edit('project_export_model',output_directory=str(ROOT/'models/arm-spike-clean'))
    (ROOT/'reports/g1/arm-clean-export.json').write_text(json.dumps(export,indent=2),encoding='utf-8')
    print(json.dumps(poses))
