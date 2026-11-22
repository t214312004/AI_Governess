/** Fit declared model controls to fixed source ROIs. Never transforms reference art. */
import {chromium} from 'playwright';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
const gaze=process.argv.includes('--gaze');
const hash=()=>readFile(new URL(`../models/${gaze?'gaze-face':'shared-face'}/model.moc3`,import.meta.url)).then(data=>createHash('sha256').update(data).digest('hex'));
const before=await hash(),browser=await chromium.launch({channel:'msedge',headless:true}),page=await browser.newPage();
const results={modelSha256:before,scope:'Local parameter fitting only; no full-face quality acceptance',frames:{}};
try{
  await page.goto('http://127.0.0.1:5187/shared-face.html'+(gaze?'?gaze=1':''));await page.waitForFunction(()=>window.__shared?.ready);await page.getByText('與原圖校對',{exact:true}).click();
  for(const source of ['idle_listen_4','speaking_1']){
    await page.locator('#reference-state').selectOption(source);await page.waitForFunction(name=>window.__sharedReference.ready&&window.__sharedReference.source===name,source);await page.locator('#apply-reference').click();
    await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
    const baseline=await page.evaluate(()=>window.__measureSharedReference());const steps=[];
    const controls=[['ParamBrowRY','browR'],['ParamBrowRAngle','browR'],['ParamBrowLY','browL'],['ParamBrowLAngle','browL']];
    if(source==='speaking_1')controls.push(['ParamEyeROpen','eyeR'],['ParamEyeLOpen','eyeL'],['ParamMouthForm','mouth'],['ParamMouthOpenY','mouth']);
    for(const [id,roi] of controls){
      const min=Number(await page.locator('#'+id).getAttribute('min')),max=Number(await page.locator('#'+id).getAttribute('max'));
      let best=Number(await page.locator('#'+id).inputValue()),error=(await page.evaluate(()=>window.__measureSharedReference())).mae[roi];
      for(const candidates of [Array.from({length:9},(_,i)=>min+(max-min)*i/8),null,null]){
        const values=candidates??[best-.125,best-.0625,best+.0625,best+.125];
        for(const raw of values){const value=Math.max(min,Math.min(max,Math.round(raw*100)/100));
          const sample=await page.evaluate(async({id,value})=>{const input=document.getElementById(id);input.value=String(value);input.dispatchEvent(new Event('input'));await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));return window.__measureSharedReference();},{id,value});
          if(sample.mae[roi]<error){best=value;error=sample.mae[roi];}
        }
        await page.locator('#'+id).fill(String(best));await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
      }
      steps.push({id,roi,value:best,error});
    }
    const fitted=await page.evaluate(()=>window.__measureSharedReference());results.frames[source]={baseline,fitted,steps};console.log(source,JSON.stringify(fitted.mae));
    await page.locator('#stage').screenshot({path:fileURLToPath(new URL(`../reports/g2/${gaze?'gaze':'shared'}-fit-${source}.png`,import.meta.url))});
  }
  if(await hash()!==before)throw new Error('Fitting modified the frozen model');
  await writeFile(new URL(`../reports/g2/${gaze?'gaze-':''}reference-fit-candidate.json`,import.meta.url),JSON.stringify(results,null,2));
}finally{await browser.close();}
