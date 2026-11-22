import {chromium} from 'playwright';
import {writeFile} from 'node:fs/promises';
const browser=await chromium.launch({channel:'msedge',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1420,height:1100}});
 await page.goto('http://127.0.0.1:5187/shared-face.html?speech=1');await page.waitForFunction(()=>window.__shared?.ready);
 const old=await page.evaluate(()=>window.__sharedSnapshot());
 await page.goto('http://127.0.0.1:5187/shared-face.html?expression=1');await page.waitForFunction(()=>window.__shared?.ready);
 const now=await page.evaluate(()=>window.__sharedSnapshot());
 console.log(Object.fromEntries(Object.keys(old.meshes).map(id=>{
  const a=old.meshes[id].sourceVertices,b=now.meshes[id].sourceVertices;
  return [id,a.length===b.length?Math.max(...a.map((v,i)=>Math.abs(v-b[i]))):{old:a.length,new:b.length}];
 })));
 await writeFile('.cache/brow-neutral-snapshot.json',JSON.stringify(now));
 for(const name of ['neutral','curious','speaking','thoughtful']){
  await page.locator(`[data-preset=${name}]`).click();await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
  const url=await page.locator('#avatar').evaluate(c=>c.toDataURL());await writeFile(`reports/g2/brow-v8-1-${name}.png`,Buffer.from(url.split(',')[1],'base64'));
 }
}finally{await browser.close();}
