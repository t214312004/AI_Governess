import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
process.env.PLAYWRIGHT_BROWSERS_PATH=fileURLToPath(new URL('../.cache/playwright/',import.meta.url));
const {chromium}=await import('playwright');
const browser=await chromium.launch({channel:'msedge',headless:true});
const context=await browser.newContext({viewport:{width:900,height:900},recordVideo:{dir:fileURLToPath(new URL('../.cache/recordings/',import.meta.url)),size:{width:900,height:900}}});
const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(String(e)));
try{
 await page.goto('http://127.0.0.1:5187/shared-face.html?speech=1');await page.waitForFunction(()=>window.__shared?.ready);
 await page.addStyleTag({content:'body{margin:0}main{padding:0;width:900px;max-width:none}header,aside{display:none}.workspace{display:block}.stage{width:900px;height:900px;border-radius:0;top:0!important}'});
 await page.locator('#slow-mouth').evaluate(b=>b.click());
 await page.waitForFunction(()=>window.__shared.values.ParamMouthOpenY>.995,{},{timeout:15000});
 await page.waitForFunction(()=>window.__shared.values.ParamMouthOpenY<.005,{},{timeout:15000});
 await page.locator('#slow-mouth').evaluate(b=>b.click());
 await page.evaluate(async()=>{
  const set=(id,value)=>{const input=document.getElementById(id);input.value=String(value);input.dispatchEvent(new Event('input',{bubbles:true}));};
  set('ParamMouthOpenY',.65);const start=performance.now();
  await new Promise(resolve=>{function tick(now){const t=Math.min((now-start)/5000,1);set('ParamMouthWidth',Math.sin(t*2*Math.PI));if(t===1)resolve();else requestAnimationFrame(tick);}requestAnimationFrame(tick);});
  document.querySelector('[data-preset=neutral]').click();
 });
 await context.close();await page.video().saveAs(fileURLToPath(new URL('../reports/g2/speech-v7.webm',import.meta.url)));
 const hash=createHash('sha256').update(await readFile(new URL('../models/speech-face/model.moc3',import.meta.url))).digest('hex');
 await writeFile(new URL('../reports/g2/speech-recording.json',import.meta.url),JSON.stringify({file:'speech-v7.webm',silent:true,modelSha256:hash,errors,scope:'Slow mouth opening/closure and width sweep; no full-expression acceptance'},null,2));
 if(errors.length)throw new Error(errors.join('\n'));console.log('Saved silent mouth and width recording.');
}finally{await browser.close();}
