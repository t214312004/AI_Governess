import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
process.env.PLAYWRIGHT_BROWSERS_PATH=fileURLToPath(new URL('../.cache/playwright/',import.meta.url));
const {chromium}=await import('playwright');
const browser=await chromium.launch({channel:'msedge',headless:true});
const context=await browser.newContext({viewport:{width:900,height:900},recordVideo:{dir:fileURLToPath(new URL('../.cache/recordings/',import.meta.url)),size:{width:900,height:900}}});
const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(String(e)));
try{
 await page.goto('http://127.0.0.1:5187/shared-face.html?head=1');await page.waitForFunction(()=>window.__shared?.ready);
 await page.addStyleTag({content:'body{margin:0}main{padding:0;width:900px;max-width:none}header,aside{display:none}.workspace{display:block}.stage{width:900px;height:900px;border-radius:0;top:0!important}.badge{display:none}#record-caption{position:fixed;bottom:18px;left:24px;background:#17232ee8;color:#fff;padding:12px 18px;border-radius:9px;font:20px sans-serif;z-index:100}'});
 await page.evaluate(()=>{const el=document.createElement('div');el.id='record-caption';document.body.append(el);});
 const caption=text=>page.locator('#record-caption').evaluate((el,text)=>el.textContent=text,text);
 await caption('v9：頭頸側傾；肩部固定（無聲錄影）');await page.waitForTimeout(1500);
 await page.locator('#slow-head').evaluate(b=>b.click());await page.waitForTimeout(16000);
 await page.locator('#slow-head').evaluate(b=>b.click());
 await page.locator('[data-preset=tiltSpeaking]').evaluate(b=>b.click());await caption('側傾說話表情：慢速閉眼／睜眼');
 await page.locator('#slow-blink').evaluate(b=>b.click());await page.waitForTimeout(8000);
 await page.locator('#stop').evaluate(b=>b.click());await caption('側傾＋視線＋眉眼＋音訊驅動嘴型（錄影無聲）');
 await page.locator('#audio').evaluate(a=>a.play());await page.locator('#sequence').evaluate(b=>b.click());await page.waitForTimeout(16000);
 await page.locator('#stop').evaluate(b=>b.click());
 await page.locator('[data-preset=neutral]').evaluate(b=>b.click());await caption('回到中立；髮緣殘邊與全身手勢仍待精修');await page.waitForTimeout(1500);
 const loads=await page.evaluate(()=>window.__shared.loads);if(loads!==1)throw new Error('Model reloaded');
 await context.close();await page.video().saveAs(fileURLToPath(new URL('../reports/g2/head-neck-v9.webm',import.meta.url)));
 const hash=createHash('sha256').update(await readFile(new URL('../models/head-face/original.moc3',import.meta.url))).digest('hex');
 await writeFile(new URL('../reports/g2/head-neck-recording.json',import.meta.url),JSON.stringify({file:'head-neck-v9.webm',silent:true,modelSha256:hash,loads,errors,scope:'Head tilt +/-6 degrees, pinned shoulders, blink and audio-driven mouth; candidate awaiting visual acceptance'},null,2));
 if(errors.length)throw new Error(errors.join('\n'));console.log('Saved v9 head/neck motion recording.');
}finally{await browser.close();}
