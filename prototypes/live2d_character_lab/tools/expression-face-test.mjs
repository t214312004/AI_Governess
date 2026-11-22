import {chromium} from 'playwright';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
import map from '../design/expression-face-runtime-map.json' with {type:'json'};
import {fitEyeAffine} from './eye-affine.mjs';
const root=new URL('../',import.meta.url),report={errors:[],regressions:[],independence:[],sweeps:[],combinations:[],maxEyeAffineResidual:0,maxLidLashClosureSeparation:0,qualityAccepted:false};
const browser=await chromium.launch({channel:'msedge',headless:true}),page=await browser.newPage({viewport:{width:1420,height:1100}});
page.on('pageerror',e=>report.errors.push(String(e)));
const wait=()=>page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
const set=async values=>{for(const [id,value] of Object.entries(values))await page.locator('#'+id).fill(String(value));await wait();};
const neutral=async()=>{await page.locator('[data-preset=neutral]').click();await wait();};
const snap=()=>page.evaluate(()=>window.__sharedSnapshot());
const mesh=(s,name)=>s.meshes[map[name].split(':')[1]];
const capture=async name=>{const url=await page.locator('#avatar').evaluate(c=>c.toDataURL());await writeFile(new URL(`reports/g2/expression-${name}.png`,root),Buffer.from(url.split(',')[1],'base64'));};
const regressions=[{},...[-1,0,1].flatMap(gaze=>[0,.12,.5,1].map(open=>({ParamEyeBallX:gaze,ParamEyeBallY:-gaze,ParamEyeROpen:open,ParamEyeLOpen:open}))),...[-1,0,1].flatMap(form=>[0,.5,1].map(open=>({ParamMouthForm:form,ParamMouthWidth:form,ParamMouthOpenY:open,ParamBrowRY:form,ParamBrowLY:-form,ParamBrowRAngle:-form,ParamBrowLAngle:form})))];
async function reference(){await page.getByText('與原圖校對',{exact:true}).click();await page.locator('#reference-state').selectOption('speaking_1');await page.waitForFunction(()=>window.__sharedReference?.ready&&window.__sharedReference.source==='speaking_1');await page.locator('#apply-reference').click();await wait();}
try{
 await page.goto('http://127.0.0.1:5187/shared-face.html?speech=1');await page.waitForFunction(()=>window.__shared?.ready);
 const baseline=[];for(const pose of regressions){await neutral();await set(pose);baseline.push(await snap());}
 await reference();report.before=await page.evaluate(()=>window.__measureSharedReference());
 await page.goto('http://127.0.0.1:5187/shared-face.html?expression=1');await page.waitForFunction(()=>window.__shared?.ready);
 assert.equal(await page.locator('#controls input').count(),15);assert.equal(await page.evaluate(()=>window.__shared.drawables),20);
 for(let j=0;j<regressions.length;j++){
  await neutral();await set(regressions[j]);const current=await snap();let max=0;
  for(const [id,old] of Object.entries(baseline[j].meshes)){
   const now=current.meshes[id];assert.equal(old.sourceVertices.length,now.sourceVertices.length);
   // v8.1 deliberately changes only the right brow's tail. Its new 27-key
   // constraint is checked separately against v8 in brow-hairline-test.mjs.
   if(id!==map.BrowR.split(':')[1])old.sourceVertices.forEach((value,i)=>max=Math.max(max,Math.abs(value-now.sourceVertices[i])));
   assert.ok(Math.abs(old.opacity-now.opacity)<1e-6,id+' opacity changed');assert.deepEqual(old.masks,now.masks);
  }
  assert.ok(max<.06,'Existing controls moved at zero new forms: '+max);report.regressions.push({pose:regressions[j],maxSourceVertexError:max});
 }
 for(const side of ['R','L'])for(const feature of ['Eye','Brow']){
  const id=`Param${feature}${side}Form`;await neutral();const rest=await snap(),hashes=[];
  const moving=feature==='Eye'?['Eye','EyeWindow','Closed','Interior','Iris','Fold','ClosedFold'].map(n=>n+side):['Brow'+side];
  for(const value of [-1,-.5,0,.5,1]){
   await set({[id]:value});const s=await snap();
   for(const [name,target] of Object.entries(map)){
    assert.ok(s.meshes[target.split(':')[1]].vertices.every(Number.isFinite));
    if(!moving.includes(name))assert.deepEqual(mesh(s,name).vertices,mesh(rest,name).vertices,id+' changed '+name);
   }
   hashes.push(createHash('sha256').update(JSON.stringify(moving.map(n=>mesh(s,n).sourceVertices))).digest('hex'));
  }
  assert.equal(new Set(hashes).size,5);report.independence.push({id,moving});report.sweeps.push({id,distinctPoses:5});
 }
 for(const form of [-1,0,1])for(const gaze of [-1,0,1]){
  await neutral();const unformed=await snap();await set({ParamEyeRForm:form,ParamEyeLForm:-form,ParamBrowRForm:form,ParamBrowLForm:-form,ParamEyeBallX:gaze,ParamEyeBallY:-gaze});const opened=await snap();
  const envelopes={};for(const side of ['R','L']){
   const names=['Eye'+side,'EyeWindow'+side];
   envelopes[side]=fitEyeAffine(names.flatMap(n=>mesh(unformed,n).sourceVertices),names.flatMap(n=>mesh(opened,n).sourceVertices));
   assert.ok(envelopes[side].maxError<.05,'Eye envelope is not an affine transform');
   report.maxEyeAffineResidual=Math.max(report.maxEyeAffineResidual,envelopes[side].maxError);
  }
  for(const opening of [1,.75,.5,.25,.12,.05,0]){
   await set({ParamEyeROpen:opening,ParamEyeLOpen:opening,ParamMouthOpenY:1-opening,ParamMouthWidth:form,ParamMouthForm:-form});const s=await snap();
   for(const side of ['R','L']){
    const iris=mesh(s,'Iris'+side);assert.equal(iris.opacity,opening===0?0:1);assert.equal(mesh(s,'LowerLip').opacity,1);
    assert.deepEqual(iris.masks,[map['EyeWindow'+side].split(':')[1]]);
    const rest=mesh(opened,'Iris'+side).sourceVertices;assert.ok(iris.sourceVertices.every((v,i)=>Math.abs(v-rest[i])<.001),'Blink distorted iris');
    if(opening<1){const closures=[];for(const name of ['Eye'+side,'EyeWindow'+side]){
      const a=envelopes[side].inverse(mesh(opened,name).sourceVertices),b=envelopes[side].inverse(mesh(s,name).sourceVertices),k=.025+.975*opening;let sum=0;for(let i=1;i<a.length;i+=2)sum+=(b[i]-k*a[i])/(1-k);closures.push(sum/(a.length/2));
     }const separation=Math.abs(closures[0]-closures[1]);report.maxLidLashClosureSeparation=Math.max(report.maxLidLashClosureSeparation,separation);assert.ok(separation<.35,`Lash and lid paths diverged: ${side} ${form} ${opening} ${separation}`);}
   }
   report.combinations.push({form,gaze,opening});
   if(form===1&&gaze===1&&[0,.5,1].includes(opening))await capture('combination-'+opening);
  }
 }
 await neutral();await reference();report.after=await page.evaluate(()=>window.__measureSharedReference());await capture('calibrated-speaking');
 for(const roi of ['eyeR','eyeL'])assert.ok(report.after.mae[roi]<report.before.mae[roi]*.8,'Eye reference error did not improve enough');
 for(const roi of ['browR','browL'])assert.ok(report.after.mae[roi]<report.before.mae[roi],'Brow reference error worsened');
 assert.ok(Math.abs(report.after.mae.mouth-report.before.mae.mouth)<.01,'Mouth calibration changed');
 await page.locator('#audio').evaluate(a=>a.play());await page.waitForFunction(()=>window.__shared.audioDriven&&window.__shared.values.ParamMouthOpenY>.08);
 await set({ParamEyeRForm:.8,ParamBrowLForm:-.6,ParamMouthWidth:.5});assert.ok(await page.evaluate(()=>window.__shared.audioDriven));
 await page.locator('#stop').click();await wait();assert.equal((await snap()).values.ParamMouthOpenY,0);report.audioCombined=true;
 await neutral();await page.locator('#sequence').click();await page.waitForFunction(()=>Math.abs(window.__shared.values.ParamEyeRForm)>.15);report.newFormsInSequence=true;
 await page.locator('#stop').click();assert.equal((await snap()).loads,1);assert.deepEqual(report.errors,[]);
 const file=new URL('models/expression-face/original.model3.json',root),model=JSON.parse(await readFile(file,'utf8'));report.assetHashes={};
 for(const name of ['original.model3.json',model.FileReferences.Moc,...model.FileReferences.Textures])report.assetHashes[name]=createHash('sha256').update(await readFile(new URL(name,file))).digest('hex');
 report.passed=true;
}catch(error){report.failure=String(error);process.exitCode=1;}
finally{await browser.close();await writeFile(new URL('reports/g2/expression-face-results.json',root),JSON.stringify(report,null,2));}
console.log(JSON.stringify({passed:report.passed,failure:report.failure,regressions:report.regressions.length,newControls:report.independence.length,combinations:report.combinations.length,before:report.before?.mae,after:report.after?.mae},null,2));
