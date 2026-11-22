import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
process.env.PLAYWRIGHT_BROWSERS_PATH=fileURLToPath(new URL('../.cache/playwright/',import.meta.url));
const {chromium}=await import('playwright');
const browser=await chromium.launch({channel:'msedge',headless:true});
const context=await browser.newContext({viewport:{width:900,height:900},recordVideo:{dir:fileURLToPath(new URL('../.cache/recordings/',import.meta.url)),size:{width:900,height:900}}});
const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(String(e)));
try{
 await page.goto('http://127.0.0.1:5187/shared-face.html?expression=1');await page.waitForFunction(()=>window.__shared?.ready);
 await page.addStyleTag({content:'body{margin:0}main{padding:0;width:900px;max-width:none}header,aside{display:none}.workspace{display:block}.stage{width:900px;height:900px;border-radius:0;top:0!important}.badge{display:none}#record-caption{position:fixed;bottom:18px;left:24px;background:#17232ee8;color:#fff;padding:12px 18px;border-radius:9px;font:20px sans-serif;z-index:100}'});
 await page.evaluate(()=>{const caption=document.createElement('div');caption.id='record-caption';document.body.append(caption);});
 const caption=text=>page.locator('#record-caption').evaluate((el,text)=>el.textContent=text,text);
 await caption('同一模型：v7 說話參數');
 await page.locator('[data-preset=speakingBefore]').evaluate(b=>b.click());
 await page.waitForTimeout(2000);
 const before=await page.evaluate(()=>({...window.__shared.values}));
 await page.locator('[data-preset=speaking]').evaluate(b=>b.click());
 await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
 const after=await page.evaluate(()=>({...window.__shared.values}));
 await page.locator('[data-preset=speakingBefore]').evaluate(b=>b.click());
 await caption('眉眼連續校準 → 更接近說話原圖');
 await page.evaluate(async({before,after})=>{
  const start=performance.now();await new Promise(resolve=>{function tick(now){
   const t=Math.min((now-start)/2000,1),smooth=t*t*(3-2*t);
   for(const id of Object.keys(after)){const input=document.getElementById(id);input.value=String(before[id]+(after[id]-before[id])*smooth);input.dispatchEvent(new Event('input',{bubbles:true}));}
   if(t===1)resolve();else requestAnimationFrame(tick);
  }requestAnimationFrame(tick);});
 },{before,after});
 await page.waitForTimeout(1800);
 await caption('校準後：慢速眨眼／眼皮與睫毛共同閉合');
 await page.locator('#slow-blink').evaluate(b=>b.click());
 await page.waitForFunction(()=>window.__shared.values.ParamEyeROpen<.005,{},{timeout:15000});
 await page.waitForFunction(()=>window.__shared.values.ParamEyeROpen>.995,{},{timeout:15000});
 await page.locator('#slow-blink').evaluate(b=>b.click());
 await caption('新組合：眉眼、視線與嘴型連續演繹');
 await page.locator('#sequence').evaluate(b=>b.click());await page.waitForTimeout(14000);
 await page.locator('#stop').evaluate(b=>b.click());
 const loads=await page.evaluate(()=>window.__shared.loads);if(loads!==1)throw new Error('Model reloaded during recording');
 await context.close();await page.video().saveAs(fileURLToPath(new URL('../reports/g2/expression-v8.webm',import.meta.url)));
 const hash=createHash('sha256').update(await readFile(new URL('../models/expression-face/original.moc3',import.meta.url))).digest('hex');
 await writeFile(new URL('../reports/g2/expression-recording.json',import.meta.url),JSON.stringify({file:'expression-v8.webm',silent:true,modelSha256:hash,loads,errors,before,after,scope:'Same-model calibration interpolation, slow blink, new expression combinations; full character not accepted'},null,2));
 if(errors.length)throw new Error(errors.join('\n'));console.log('Saved silent v8 calibration, blink and expression recording.');
}finally{await browser.close();}
