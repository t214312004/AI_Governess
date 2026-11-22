import {chromium} from 'playwright';
import {readFile,writeFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
import {fitEyeAffine} from './eye-affine.mjs';
const boundary=JSON.parse(await readFile('reports/g2/brow-hairline-authoring-boundary.json','utf8'));
const hairX=y=>{const i=Math.max(0,Math.min(boundary.length-2,Math.floor(y)-boundary[0][1]));const a=boundary[i],b=boundary[i+1];return a[0]+(b[0]-a[0])*(y-a[1]);};
const browser=await chromium.launch({channel:'msedge',headless:true});
try{
 const page=await browser.newPage();await page.goto('http://127.0.0.1:5187/shared-face.html?expression=1');await page.waitForFunction(()=>window.__shared?.ready);
 const set=async values=>{for(const [id,v] of Object.entries(values))await page.locator('#'+id).fill(String(v));await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));};
 const mesh=()=>page.evaluate(()=>window.__sharedSnapshot().meshes.ArtMeshEyebrowR);
 const rest=await mesh(),v=rest.sourceVertices,point=[384.5,392.5];let triangle,weights;
 for(let i=0;i<rest.indices.length;i+=3){
  const ids=rest.indices.slice(i,i+3),[a,b,c]=ids.map(i=>[v[2*i],v[2*i+1]]),den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1]);
  const u=((b[1]-c[1])*(point[0]-c[0])+(c[0]-b[0])*(point[1]-c[1]))/den,w=((c[1]-a[1])*(point[0]-c[0])+(a[0]-c[0])*(point[1]-c[1]))/den;
  if(Math.min(u,w,1-u-w)>=-1e-6){triangle=ids;weights=[u,w,1-u-w];break;}
 }
 assert.ok(triangle,'Tail landmark outside original mesh');
 const width=Math.max(...v.filter((_,i)=>i%2===0))-Math.min(...v.filter((_,i)=>i%2===0)),height=Math.max(...v.filter((_,i)=>i%2===1))-Math.min(...v.filter((_,i)=>i%2===1));
 const selected=v.flatMap((x,i)=>i%2===0&&x<393?[i/2]:[]);assert.ok(triangle.every(i=>selected.includes(i)));
 const report={sourcePoint:point,triangle,weights,selected,width,height,keys:[]};
 for(const y of [-1,0,1])for(const angle of [-1,0,1]){
  await set({ParamBrowRY:y,ParamBrowRAngle:angle,ParamBrowRForm:0});const base=(await mesh()).sourceVertices;
  for(const form of [-1,0,1]){
   await set({ParamBrowRForm:form});const now=(await mesh()).sourceVertices,fit=fitEyeAffine(base,now);assert.ok(fit.maxError<.05);
   const tail=[0,1].map(axis=>triangle.reduce((sum,index,i)=>sum+now[2*index+axis]*weights[i],0));
   const target=[hairX(tail[1])-.25,tail[1]],a=fit.inverse(tail),b=fit.inverse(target);
   report.keys.push({key:{ParamBrowRY:y,ParamBrowRAngle:angle,ParamBrowRForm:form},tail,target,delta:[(b[0]-a[0])/width,(b[1]-a[1])/height]});
  }
 }
 await writeFile('design/brow-tail-constraints.json',JSON.stringify(report,null,2));console.log('Fitted 27 tail/hairline constraints without moving the brow arch.');
}finally{await browser.close();}
