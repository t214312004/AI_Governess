import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
process.env.PLAYWRIGHT_BROWSERS_PATH=fileURLToPath(new URL('../.cache/playwright/',import.meta.url));
const {chromium}=await import('playwright');
const browser=await chromium.launch({channel:'msedge',headless:true});
const context=await browser.newContext({viewport:{width:900,height:900},recordVideo:{dir:fileURLToPath(new URL('../.cache/recordings/',import.meta.url)),size:{width:900,height:900}}});
const page=await context.newPage(),errors=[];await page.route('**/@vite/client',r=>r.fulfill({body:"export const createHotContext=()=>({accept(){},dispose(){},prune(){},on(){},off(){},invalidate(){},send(){},data:{}});const styles=new Map();export function updateStyle(id,content){let el=styles.get(id);if(!el){el=document.createElement('style');document.head.append(el);styles.set(id,el);}el.textContent=content;}export function removeStyle(id){styles.get(id)?.remove();styles.delete(id);}",contentType:'application/javascript'}));page.on('pageerror',e=>errors.push(String(e)));
try{
 await page.goto('http://127.0.0.1:5187/shared-face.html?turn=1');await page.waitForFunction(()=>window.__shared?.ready);
 await page.addStyleTag({content:'body{margin:0}main{padding:0;width:900px;max-width:none}header,aside{display:none}.workspace{display:block}.stage{width:900px;height:900px;border-radius:0;top:0!important}.badge{display:none}#record-caption{position:fixed;bottom:18px;left:24px;background:#17232ee8;color:#fff;padding:12px 18px;border-radius:9px;font:20px sans-serif;z-index:100}'});
 await page.evaluate(()=>{const el=document.createElement('div');el.id='record-caption';document.body.append(el);});
 const caption=text=>page.locator('#record-caption').evaluate((el,text)=>el.textContent=text,text);
 await caption('v10：小幅轉頭／俯仰；肩部固定（無聲錄影）');await page.waitForTimeout(1500);
 await page.locator('#slow-yaw').evaluate(b=>b.click());await page.waitForTimeout(16000);await page.locator('#slow-yaw').evaluate(b=>b.click());
 await page.locator('[data-preset=neutral]').evaluate(b=>b.click());await caption('小幅俯仰：抬頭／低頭');await page.locator('#slow-pitch').evaluate(b=>b.click());await page.waitForTimeout(12000);await page.locator('#slow-pitch').evaluate(b=>b.click());
 await page.locator('[data-preset=turnSpeaking]').evaluate(b=>b.click());await caption('轉頭＋俯仰＋側傾：慢速閉眼／睜眼');await page.locator('#slow-blink').evaluate(b=>b.click());await page.waitForTimeout(8000);
 await page.locator('#stop').evaluate(b=>b.click());await caption('小幅頭部動作＋視線＋表情＋音訊嘴型（錄影無聲）');await page.locator('#audio').evaluate(a=>a.play());await page.locator('#sequence').evaluate(b=>b.click());await page.waitForTimeout(16000);
 await page.locator('#stop').evaluate(b=>b.click());await page.locator('[data-preset=neutral]').evaluate(b=>b.click());await caption('回到中立；髮緣清理與完整手勢仍待完成');await page.waitForTimeout(1500);
 const loads=await page.evaluate(()=>window.__shared.loads);if(loads!==1)throw new Error('Model reloaded');
 await context.close();await page.video().saveAs(fileURLToPath(new URL('../reports/g2/head-turn-v10.webm',import.meta.url)));
 const hash=createHash('sha256').update(await readFile(new URL('../models/turn-face/original.moc3',import.meta.url))).digest('hex');
 await writeFile(new URL('../reports/g2/head-turn-recording.json',import.meta.url),JSON.stringify({file:'head-turn-v10.webm',silent:true,modelSha256:hash,loads,errors,scope:'Small yaw/pitch with roll, fixed shoulder roots and simultaneous expressions/audio; candidate awaiting visual acceptance'},null,2));
 if(errors.length)throw new Error(errors.join('\n'));console.log('Saved v10 small head turn recording.');
}finally{await browser.close();}
