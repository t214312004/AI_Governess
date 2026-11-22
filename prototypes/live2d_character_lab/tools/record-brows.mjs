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
 await page.evaluate(()=>{const el=document.createElement('div');el.id='record-caption';document.body.append(el);});
 const caption=text=>page.locator('#record-caption').evaluate((el,text)=>el.textContent=text,text);
 await caption('v8.1：眉尾接合與左右眉毛檢查');await page.waitForTimeout(1800);
 await page.locator('[data-preset=speaking]').evaluate(b=>b.click());await caption('說話：眉尾保持連接髮際');await page.waitForTimeout(1800);
 await page.locator('[data-preset=neutral]').evaluate(b=>b.click());await caption('雙眉慢速檢查：高度、角度、眉形');
 await page.locator('#slow-brow').evaluate(b=>b.click());await page.waitForTimeout(24000);
 await page.locator('#slow-brow').evaluate(b=>b.click());
 await page.locator('[data-preset=curious]').evaluate(b=>b.click());await caption('疑問表情：刻意抬起單側眉毛');await page.waitForTimeout(2000);
 await page.locator('[data-preset=speaking]').evaluate(b=>b.click());await caption('說話表情：接合處慢速眨眼檢查');await page.locator('#slow-blink').evaluate(b=>b.click());
 await page.waitForFunction(()=>window.__shared.values.ParamEyeROpen<.005,{},{timeout:15000});
 await page.waitForFunction(()=>window.__shared.values.ParamEyeROpen>.995,{},{timeout:15000});
 await page.locator('#stop').evaluate(b=>b.click());
 const loads=await page.evaluate(()=>window.__shared.loads);if(loads!==1)throw new Error('Model reloaded');
 await context.close();await page.video().saveAs(fileURLToPath(new URL('../reports/g2/brow-v8-1.webm',import.meta.url)));
 const hash=createHash('sha256').update(await readFile(new URL('../models/expression-face/original.moc3',import.meta.url))).digest('hex');
 await writeFile(new URL('../reports/g2/brow-recording.json',import.meta.url),JSON.stringify({file:'brow-v8-1.webm',silent:true,modelSha256:hash,loads,errors,scope:'Brow-tail continuity, simultaneous eyebrow motion and blink; candidate awaiting visual acceptance'},null,2));
 if(errors.length)throw new Error(errors.join('\n'));console.log('Saved v8.1 eyebrow motion recording.');
}finally{await browser.close();}
