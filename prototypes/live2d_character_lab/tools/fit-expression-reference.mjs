/** Fit only declared semantic controls. Source crop and pixels stay fixed. */
import {chromium} from 'playwright';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
const root=new URL('../',import.meta.url),model=new URL('models/expression-face/original.moc3',root);
const hash=async()=>createHash('sha256').update(await readFile(model)).digest('hex');
const report={modelSha256:await hash(),steps:[],qualityAccepted:false};
const browser=await chromium.launch({channel:'msedge',headless:true}),page=await browser.newPage({viewport:{width:1420,height:1100}});
const wait=()=>page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
const measure=()=>page.evaluate(()=>window.__measureSharedReference());
const score=(m,roi)=>roi==='eyes'?m.mae.eyeR+m.mae.eyeL:m.mae[roi];
const set=async(id,value)=>page.evaluate(async({id,value})=>{const input=document.getElementById(id);input.value=String(value);input.dispatchEvent(new Event('input'));await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));return window.__measureSharedReference();},{id,value});
const capture=async name=>{const url=await page.locator('#avatar').evaluate(c=>c.toDataURL());await writeFile(new URL(`reports/g2/expression-${name}.png`,root),Buffer.from(url.split(',')[1],'base64'));};
async function reference(){await page.getByText('與原圖校對',{exact:true}).click();await page.locator('#reference-state').selectOption('speaking_1');await page.waitForFunction(()=>window.__sharedReference?.ready&&window.__sharedReference.source==='speaking_1');await page.locator('#apply-reference').click();await wait();}
try{
 await page.goto('http://127.0.0.1:5187/shared-face.html?speech=1');await page.waitForFunction(()=>window.__shared?.ready);await wait();const old=await page.evaluate(()=>window.__sharedSnapshot());
 await reference();report.before=await measure();await capture('v7-speaking');
 await page.goto('http://127.0.0.1:5187/shared-face.html?expression=1');await page.waitForFunction(()=>window.__shared?.ready);await wait();const now=await page.evaluate(()=>window.__sharedSnapshot());
 let max=0;for(const [id,mesh] of Object.entries(old.meshes)){assert.equal(mesh.sourceVertices.length,now.meshes[id].sourceVertices.length);mesh.sourceVertices.forEach((v,i)=>max=Math.max(max,Math.abs(v-now.meshes[id].sourceVertices[i])));}
 report.neutralGeometryMaxSourceError=max;assert.ok(max<.05,'New envelopes must preserve neutral v7 geometry');await capture('neutral');
 await reference();report.seed=await measure();
 const controls=[['ParamEyeRForm','eyeR'],['ParamEyeLForm','eyeL'],['ParamEyeROpen','eyeR'],['ParamEyeLOpen','eyeL'],['ParamEyeBallX','eyes'],['ParamEyeBallY','eyes'],['ParamBrowRForm','browR'],['ParamBrowRY','browR'],['ParamBrowRAngle','browR'],['ParamBrowLForm','browL'],['ParamBrowLY','browL'],['ParamBrowLAngle','browL']];
 for(let pass=0;pass<2;pass++)for(const [id,roi] of controls){
  const min=Number(await page.locator('#'+id).getAttribute('min')),max=Number(await page.locator('#'+id).getAttribute('max'));
  let best=Number(await page.locator('#'+id).inputValue()),error=score(await measure(),roi);
  const coarse=pass===0?Array.from({length:9},(_,i)=>min+(max-min)*i/8):[best-.2,best-.1,best,best+.1,best+.2];
  for(const candidates of [coarse,null])for(const raw of candidates??[best-.06,best-.03,best+.03,best+.06]){
   const value=Math.max(min,Math.min(max,Math.round(raw*100)/100)),m=await set(id,value),cost=score(m,roi);
   if(cost<error){best=value;error=cost;}
  }
  await set(id,best);report.steps.push({pass,id,roi,value:best,error});console.log(pass,id,best,error.toFixed(3));
 }
 report.after=await measure();await capture('fitted-speaking');assert.equal(await hash(),report.modelSha256);report.completed=true;
}catch(error){report.failure=String(error);process.exitCode=1;}
finally{await browser.close();await writeFile(new URL('reports/g2/expression-reference-fit.json',root),JSON.stringify(report,null,2));}
console.log(JSON.stringify({completed:report.completed,failure:report.failure,neutralGeometryMaxSourceError:report.neutralGeometryMaxSourceError,before:report.before?.mae,after:report.after?.mae},null,2));
