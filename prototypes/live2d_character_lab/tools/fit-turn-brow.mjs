import {chromium} from 'playwright';import {readFile,writeFile} from 'node:fs/promises';import {createHash} from 'node:crypto';
const prior=JSON.parse(await readFile('design/brow-tail-constraints.json','utf8'));
const b=await chromium.launch({channel:'msedge',headless:true});
try{
 const p=await b.newPage();await p.route('**/@vite/client',r=>r.fulfill({body:'',contentType:'application/javascript'}));await p.goto('http://127.0.0.1:5187/.cache/probe-v10.html');
 const result=await p.evaluate(async ({prior,dense})=>{
  const {Avatar}=await import('/viewer/avatar.ts'),{fitEyeAffine}=await import('/tools/eye-affine.mjs');const c=document.createElement('canvas');c.width=c.height=900;const gl=c.getContext('webgl'),a=await Avatar.open('/generated/models/turn-face/original.model3.json',gl,c),m=a.getModel(),info=m.getModel().canvasinfo;
  for(let i=0;i<m.getParameterCount();i++)m.setParameterValueByIndex(i,m.getParameterDefaultValue(i));m.update();
  const get=id=>{const i=Array.from({length:m.getDrawableCount()},(_,i)=>i).find(i=>m.getDrawableId(i).getString()===id);return {v:Array.from(m.getDrawableVertices(i),(v,j)=>j%2?info.CanvasOriginY-v*info.PixelsPerUnit:info.CanvasOriginX+v*info.PixelsPerUnit),indices:Array.from(m.getDrawableVertexIndices(i))};};
  const pointAt=(v,ids,w)=>[0,1].map(axis=>ids.reduce((sum,id,i)=>sum+v[id*2+axis]*w[i],0));
  const locate=(mesh,point)=>{const v=mesh.v;for(let k=0;k<mesh.indices.length;k+=3){const ids=mesh.indices.slice(k,k+3),[a,b,c]=ids.map(i=>[v[i*2],v[i*2+1]]),d=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1]);if(Math.abs(d)<1e-8)continue;const u=((b[1]-c[1])*(point[0]-c[0])+(c[0]-b[0])*(point[1]-c[1]))/d,w=((c[1]-a[1])*(point[0]-c[0])+(a[0]-c[0])*(point[1]-c[1]))/d;if(Math.min(u,w,1-u-w)>=-1e-5)return {ids,w:[u,w,1-u-w]};}throw new Error('Tail not on skin mesh');};
  const rest=get('ArtMeshEyebrowR').v,restSkin=get('ArtMeshFace');const clean=v=>v.filter((_,i)=>!prior.selected.includes(Math.floor(i/2)));const keys=[];let maxBefore=0,maxAffineError=0;
  for(const height of (dense?[-1,-.5,0,.5,1]:[-1,0,1]))for(const angle of (dense?[-1,-.5,0,.5,1]:[-1,0,1]))for(const form of (dense?[-1,-.5,0,.5,1]:[-1,0,1])){
   a.set('ParamAngleX',0);a.set('ParamAngleY',0);a.set('ParamBrowRY',height);a.set('ParamBrowRAngle',angle);a.set('ParamBrowRForm',form);m.update();
   const base=get('ArtMeshEyebrowR').v,tail=pointAt(base,prior.triangle,prior.weights),onSkin=locate(restSkin,tail);
   for(const x of [-6,0,6])for(const y of [-4,0,4]){
    a.set('ParamAngleX',x);a.set('ParamAngleY',y);m.update();const now=get('ArtMeshEyebrowR').v,skin=get('ArtMeshFace').v,expected=pointAt(skin,onSkin.ids,onSkin.w),actual=pointAt(now,prior.triangle,prior.weights),mapping=fitEyeAffine(clean(rest),clean(now));
    const from=mapping.inverse(actual),to=mapping.inverse(expected),delta=[(to[0]-from[0])/prior.width,(to[1]-from[1])/prior.height];maxBefore=Math.max(maxBefore,Math.hypot(actual[0]-expected[0],actual[1]-expected[1]));maxAffineError=Math.max(maxAffineError,mapping.maxError);
    keys.push({key:{ParamBrowRY:height,ParamBrowRAngle:angle,ParamBrowRForm:form,ParamAngleX:x,ParamAngleY:y},delta,expected,actual});
   }
  }return {keys,selected:prior.selected,softRadius:.35,maxBefore,maxAffineError};
 },{prior,dense:process.argv.includes('--dense')});
 result.modelSha256=createHash('sha256').update(await readFile('models/turn-face/original.moc3')).digest('hex');await writeFile(process.argv[2]??'design/head-turn-brow-constraints.json',JSON.stringify(result,null,2));console.log({keys:result.keys.length,maxBefore:result.maxBefore,maxAffineError:result.maxAffineError});
}finally{await b.close();}
