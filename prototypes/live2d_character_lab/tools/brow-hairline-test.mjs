import {chromium} from 'playwright';
import {readFile,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
const fit=JSON.parse(await readFile('design/brow-tail-constraints.json','utf8'));
const boundary=JSON.parse(await readFile('reports/g2/brow-hairline-authoring-boundary.json','utf8'));
const hairX=y=>{const i=Math.max(0,Math.min(boundary.length-2,Math.floor(y)-boundary[0][1]));const a=boundary[i],b=boundary[i+1];return a[0]+(b[0]-a[0])*(y-a[1]);};
const report={errors:[],poses:[],maxUnrelatedVertexDifference:0,maxOtherBrowDifference:0,maxTailGap:0,maxTailFitResidual:0,qualityAccepted:false};
const browser=await chromium.launch({channel:'msedge',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1420,height:1100}});page.on('pageerror',e=>report.errors.push(String(e)));
 const wait=()=>page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
 const set=async values=>{await page.evaluate(values=>{for(const [id,v] of Object.entries(values)){const input=document.getElementById(id);input.value=String(v);input.dispatchEvent(new Event('input',{bubbles:true}));}},values);await wait();};
 const snapshot=()=>page.evaluate(()=>window.__sharedSnapshot());
 const poses=[-1,-.5,0,.5,1].flatMap(y=>[-1,-.5,0,.5,1].flatMap(angle=>[-1,-.5,0,.5,1].map(form=>({ParamBrowRY:y,ParamBrowRAngle:angle,ParamBrowRForm:form}))));
 await page.route('**/generated/models/expression-face/**',route=>{const relative=new URL(route.request().url()).pathname.split('/expression-face/')[1];return route.fulfill({path:fileURLToPath(new URL('../models/expression-face-v8/'+relative,import.meta.url))});});
 await page.goto('http://127.0.0.1:5187/shared-face.html?expression=1');await page.waitForFunction(()=>window.__shared?.ready);const baseline=[];
 for(const pose of poses){await set(pose);baseline.push(await snapshot());}
 await page.locator('[data-preset=curious]').click();await wait();let url=await page.locator('#avatar').evaluate(c=>c.toDataURL());await writeFile('reports/g2/brow-v8-before-curious.png',Buffer.from(url.split(',')[1],'base64'));
 await page.unrouteAll();await page.goto('http://127.0.0.1:5187/shared-face.html?expression=1');await page.waitForFunction(()=>window.__shared?.ready);
 assert.equal(await page.evaluate(()=>window.__shared.drawables),20);
 for(let i=0;i<poses.length;i++){
  await set(poses[i]);const current=await snapshot();
  for(const [id,old] of Object.entries(baseline[i].meshes)){
   const now=current.meshes[id];assert.deepEqual(old.indices,now.indices);assert.equal(old.sourceVertices.length,now.sourceVertices.length);assert.ok(now.sourceVertices.every(Number.isFinite));
   if(id==='ArtMeshEyebrowR')continue;
   const max=Math.max(...old.sourceVertices.map((v,j)=>Math.abs(v-now.sourceVertices[j])));
   report.maxUnrelatedVertexDifference=Math.max(max,report.maxUnrelatedVertexDifference);
   if(id==='ArtMeshEyebrowL')report.maxOtherBrowDifference=Math.max(max,report.maxOtherBrowDifference);
   assert.ok(max<.001,id+' moved during hairline repair: '+max);assert.equal(old.opacity,now.opacity);assert.deepEqual(old.masks,now.masks);
  }
  const v=current.meshes.ArtMeshEyebrowR.sourceVertices;
  const tail=[0,1].map(axis=>fit.triangle.reduce((sum,index,j)=>sum+v[index*2+axis]*fit.weights[j],0));
  const gap=tail[0]-hairX(tail[1]),residual=Math.abs(gap+.25);
  report.maxTailGap=Math.max(report.maxTailGap,gap);report.maxTailFitResidual=Math.max(report.maxTailFitResidual,residual);
  report.poses.push({...poses[i],tail,gap,residual});assert.ok(residual<.65,'Tail detached from hairline: '+JSON.stringify(report.poses.at(-1)));
 }
 for(const name of ['neutral','curious','speaking','thoughtful']){
  await page.locator(`[data-preset=${name}]`).click();await wait();url=await page.locator('#avatar').evaluate(c=>c.toDataURL());await writeFile(`reports/g2/brow-v8-1-${name}.png`,Buffer.from(url.split(',')[1],'base64'));
 }
 await page.locator('#slow-brow').click();await page.waitForFunction(()=>window.__shared.values.ParamBrowRY>.3);
 await page.locator('#slow-brow').click();await wait();const paused=(await snapshot()).values;await page.waitForTimeout(150);
 assert.deepEqual((await snapshot()).values,paused);report.slowBrowPause=true;
 assert.equal((await snapshot()).loads,1);assert.deepEqual(report.errors,[]);
 report.modelSha256=createHash('sha256').update(await readFile('models/expression-face/original.moc3')).digest('hex');report.passed=true;
}catch(e){report.failure=String(e);process.exitCode=1;}
finally{await browser.close();await writeFile('reports/g2/brow-hairline-results.json',JSON.stringify(report,null,2));}
console.log(JSON.stringify({passed:report.passed,failure:report.failure,poses:report.poses.length,maxUnrelatedVertexDifference:report.maxUnrelatedVertexDifference,maxOtherBrowDifference:report.maxOtherBrowDifference,maxTailGap:report.maxTailGap,maxTailFitResidual:report.maxTailFitResidual},null,2));
