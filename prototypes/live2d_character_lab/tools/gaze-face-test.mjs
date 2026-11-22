import {chromium} from 'playwright';
import {writeFile,readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
import map from '../design/gaze-face-runtime-map.json' with {type:'json'};
const root=new URL('../',import.meta.url),report={errors:[],sweeps:[],facialSweeps:[],combinations:[],qualityAccepted:false};
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:1420,height:1100}});
page.on('pageerror',e=>report.errors.push(String(e)));
const settle=()=>page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
const set=async values=>{for(const [id,value] of Object.entries(values))await page.locator('#'+id).fill(String(value));await settle();};
const snap=()=>page.evaluate(()=>window.__sharedSnapshot());
const mesh=(s,name)=>s.meshes[map[name].split(':')[1]];
const pixels=async()=>Buffer.from(await page.evaluate(()=>{
 const canvas=document.getElementById('avatar'),copy=document.createElement('canvas');copy.width=copy.height=900;
 const ctx=copy.getContext('2d');ctx.drawImage(canvas,0,0);const data=ctx.getImageData(0,0,900,900).data;
 const chunks=[];for(let i=0;i<data.length;i+=16384)chunks.push(String.fromCharCode(...data.subarray(i,i+16384)));
 return btoa(chunks.join(''));
}),'base64');
const screenshot=async name=>{
 const url=await page.locator('#avatar').evaluate(c=>c.toDataURL());
 await writeFile(new URL(`reports/g2/gaze-${name}.png`,root),Buffer.from(url.split(',')[1],'base64'));
};
const difference=(a,b)=>{
 let sum=0,changed=0,max=0;
 for(let i=0;i<a.length;i+=4){let pixel=0;for(let c=0;c<3;c++){const d=Math.abs(a[i+c]-b[i+c]);sum+=d;max=Math.max(max,d);pixel=Math.max(pixel,d);}if(pixel>8)changed++;}
 return {rgbMeanAbsoluteError:sum/(a.length/4*3),pixelsChangedOver8:changed,maxChannelDifference:max};
};
try{
 await page.goto('http://127.0.0.1:5187/shared-face.html');await page.waitForFunction(()=>window.__shared?.ready);await settle();
 const acceptedOpen=await pixels();await screenshot('accepted-open');
 await set({ParamEyeROpen:0,ParamEyeLOpen:0});const acceptedClosed=await pixels();
 await page.goto('http://127.0.0.1:5187/shared-face.html?gaze=1');await page.waitForFunction(()=>window.__shared?.ready);await settle();
 assert.equal(await page.locator('#controls input').count(),10);
 assert.equal(await page.evaluate(()=>window.__shared.drawables),19);
 const neutral=await snap();report.neutralVsAccepted=difference(acceptedOpen,await pixels());await screenshot('neutral');
 for(const axis of ['ParamEyeBallX','ParamEyeBallY'])for(const value of [-1,-.5,0,.5,1]){
  await set({ParamEyeBallX:0,ParamEyeBallY:0,[axis]:value});const current=await snap();const shifts={};
  for(const [name,target] of Object.entries(map)){
   const a=mesh(neutral,name).sourceVertices,b=current.meshes[target.split(':')[1]].sourceVertices;
   if(!name.startsWith('Iris'))assert.deepEqual(a,b,`${axis} must not move ${name}`);
   else {
    const dx=[],dy=[];for(let i=0;i<a.length;i+=2){dx.push(b[i]-a[i]);dy.push(b[i+1]-a[i+1]);}
    shifts[name]={dx:dx.reduce((a,b)=>a+b)/dx.length,dy:dy.reduce((a,b)=>a+b)/dy.length};
    if(value!==0)assert.ok(Math.abs(shifts[name][axis.endsWith('X')?'dx':'dy'])>1,'Gaze must move both irises');
   }
  }
  report.sweeps.push({axis,value,shifts});
 }
 for(const x of [-1,0,1])for(const y of [-1,0,1])for(const open of [1,.75,.5,.25,.14,.12,.05,0]){
  await set({ParamEyeBallX:x,ParamEyeBallY:y,ParamEyeROpen:open,ParamEyeLOpen:open});const s=await snap();
  for(const side of ['R','L']){
   assert.deepEqual(mesh(s,'Iris'+side).masks,[map['EyeWindow'+side].split(':')[1]]);
   assert.equal(mesh(s,'Iris'+side).opacity,open===0?0:1);
   assert.equal(mesh(s,'Interior'+side).opacity,open===0?0:1);
   if(open>0&&open<=.12){assert.equal(mesh(s,'Eye'+side).opacity,0);assert.equal(mesh(s,'Closed'+side).opacity,1);}
   if(open<1){
    const closures=[];
    for(const name of ['Eye'+side,'EyeWindow'+side]){
     const a=mesh(neutral,name).sourceVertices,b=mesh(s,name).sourceVertices,scale=.025+.975*open;
     let sum=0;for(let i=1;i<a.length;i+=2)sum+=(b[i]-scale*a[i])/(1-scale);
     closures.push(sum/(a.length/2));
    }
    assert.ok(Math.abs(closures[0]-closures[1])<.35,'Lid and lash must preserve the accepted shared path');
   }
  }
  report.combinations.push({x,y,open});
  if(y===0&&open===1)await screenshot(x===0?'front':x===-1?'left':'right');
  if(x===0&&open===1&&y!==0)await screenshot(y===1?'up':'down');
  if(x===0&&y===0&&open===.5)await screenshot('half-blink');
 }
 report.closedVsAccepted=difference(acceptedClosed,await pixels());await screenshot('closed');
 assert.ok(report.closedVsAccepted.rgbMeanAbsoluteError<.15,'Closed-eye rendering must preserve accepted v5');
 for(const id of ['ParamEyeROpen','ParamEyeLOpen','ParamBrowRY','ParamBrowLY','ParamBrowRAngle','ParamBrowLAngle','ParamMouthForm','ParamMouthOpenY']){
  await page.locator('[data-preset=neutral]').click();await set({ParamEyeBallX:.45,ParamEyeBallY:-.3});const before=await snap();
  const min=Number(await page.locator('#'+id).getAttribute('min')),hashes=[];
  for(const value of [min,(3*min+1)/4,(min+1)/2,(min+3)/4,1]){
   await set({[id]:value});const s=await snap();
   for(const side of ['R','L']){
    const rest=mesh(before,'Iris'+side).sourceVertices,now=mesh(s,'Iris'+side).sourceVertices;
    assert.ok(now.every((value,i)=>Math.abs(value-rest[i])<.001),`${id} must not deform iris geometry beyond floating-point interpolation`);
   }
   assert.ok(Object.values(s.meshes).every(m=>m.vertices.every(Number.isFinite)));
   hashes.push(createHash('sha256').update(JSON.stringify(s.meshes)).digest('hex'));
  }
  assert.equal(new Set(hashes).size,5);report.facialSweeps.push({id,distinctPoses:5});
 }
 await page.locator('[data-preset=neutral]').click();await page.locator('#sequence').click();
 await page.waitForFunction(()=>Math.abs(window.__shared.values.ParamEyeBallX)>.15);report.programmaticGazeSequence=true;
 await page.locator('#stop').click();
 await set({ParamEyeROpen:1,ParamEyeLOpen:1,ParamEyeBallX:.5,ParamEyeBallY:.5});
 await page.locator('#audio').evaluate(a=>a.play());await page.waitForFunction(()=>window.__shared.audioDriven&&window.__shared.values.ParamMouthOpenY>.05);
 report.audioDuringGaze=true;await page.locator('#stop').click();await settle();assert.equal((await snap()).values.ParamMouthOpenY,0);
 assert.equal((await snap()).loads,1);assert.deepEqual(report.errors,[]);
 report.modelSha256=createHash('sha256').update(await readFile(new URL('models/gaze-face/model.moc3',root))).digest('hex');
 const modelFile=new URL('models/gaze-face/model.model3.json',root),model=JSON.parse(await readFile(modelFile,'utf8'));report.assetHashes={};
 for(const path of ['model.model3.json',model.FileReferences.Moc,...model.FileReferences.Textures])report.assetHashes[path]=createHash('sha256').update(await readFile(new URL(path,modelFile))).digest('hex');
 report.passed=true;
}catch(error){report.failure=String(error);process.exitCode=1;}
finally{await browser.close();await writeFile(new URL('reports/g2/gaze-face-results.json',root),JSON.stringify(report,null,2));}
console.log(JSON.stringify({passed:report.passed,failure:report.failure,sweeps:report.sweeps.length,combinations:report.combinations.length,neutral:report.neutralVsAccepted,closed:report.closedVsAccepted},null,2));
