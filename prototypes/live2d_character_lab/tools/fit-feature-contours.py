"""Read-only source contour analysis; native rig authoring uses the fitted transforms."""
import json
import numpy as np
from PIL import Image
from scipy import ndimage,optimize,spatial
from rig import ROOT
source=ROOT.parents[1]/'ai_voice_assistant/assets/states/layers'
frames={name:np.asarray(Image.open(source/f'{name}.png').convert('RGB'))[:1024,600:1624].astype(int) for name in ['idle_listen_1','speaking_1']}
yy,xx=np.indices((1024,1024))
specs={'EyeR':[364,408,479,483],'EyeL':[542,408,658,483],'BrowR':[380,360,474,402],'BrowL':[540,360,610,398]}
def contour(a,name,rect):
    left,top,right,bottom=rect;r,g,b=a.transpose(2,0,1)
    mask=(xx>=left)&(xx<right)&(yy>=top)&(yy<bottom)
    if name.startswith('Eye'):
        mask&=(r<100)&(g<80)&(b<80)
        mask&=(xx>=np.maximum(364,385-(yy-408)*.55)) if name.endswith('R') else (xx<=np.minimum(658,620+(yy-408)*.9))
    else:mask&=(r<210)&(g<170)&(b<155)
    labels,n=ndimage.label(mask);sizes=np.bincount(labels.ravel());sizes[0]=0;mask=labels==sizes.argmax()
    edge=mask&~ndimage.binary_erosion(mask);y,x=np.where(edge)
    return np.column_stack((x,y)).astype(float)
report={'source':'idle_listen_1','target':'speaking_1','scope':'Local contour diagnostics, not whole-face registration or quality acceptance','features':{}}
for name,rect in specs.items():
    a=contour(frames['idle_listen_1'],name,rect);b=contour(frames['speaking_1'],name,rect);center=(a.min(axis=0)+a.max(axis=0))/2
    tree=spatial.cKDTree(b)
    def transform(p):
        dx,dy,sx,sy,degrees=p;angle=np.deg2rad(degrees);rotation=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
        return ((a-center)*[sx,sy])@rotation.T+center+[dx,dy]
    def cost(p):
        moved=transform(p);dist1=tree.query(moved)[0];dist2=spatial.cKDTree(moved).query(b)[0]
        # Symmetric distance prevents matching only one fragment of a contour.
        return np.mean(np.minimum(dist1,8)**2)+np.mean(np.minimum(dist2,8)**2)
    baseline=cost([0,0,1,1,0]);bounds=[(-6,6),(-6,6),(.88,1.12),(.8,1.2),(-7,7)]
    result=optimize.differential_evolution(cost,bounds,seed=7,popsize=12,maxiter=120,tol=1e-6,polish=True)
    report['features'][name]={'roi':rect,'center':center.tolist(),'parameters':dict(zip(['dx','dy','sx','sy','degrees'],result.x.tolist())),'baseline_cost':baseline,'fitted_cost':float(result.fun),'source_contour_points':len(a),'target_contour_points':len(b)}
    print(name,report['features'][name]['parameters'],'cost',baseline,'->',result.fun,flush=True)
(ROOT/'design/feature-contour-fit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
