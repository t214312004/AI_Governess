import {chromium} from 'playwright';
import {writeFile} from 'node:fs/promises';
import map from '../design/shared-face-runtime-map.json' with {type:'json'};
const browser=await chromium.launch({channel:'msedge',headless:true}),page=await browser.newPage();
const results={};
try{
 await page.goto('http://127.0.0.1:5187/shared-face.html');await page.waitForFunction(()=>window.__shared?.ready);
 for(const value of [1,.75,.5,.25,0]){
  for(const side of ['R','L'])await page.locator('#ParamEye'+side+'Open').fill(String(value));
  await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
  const snap=await page.evaluate(()=>window.__sharedSnapshot());results[value]={};
  for(const name of ['EyeR','EyeL','EyeWindowR','EyeWindowL']){
   const m=snap.meshes[map[name].split(':')[1]],ys=m.sourceVertices.filter((_,i)=>i%2);
   results[value][name]={min:Math.min(...ys),max:Math.max(...ys),ys};
  }
 }
 const summary={};
 for(const name of Object.keys(results[1])){const open=results[1][name],closed=results[0][name];const target=open.ys.reduce((sum,y,i)=>sum+(closed.ys[i]-.025*y)/.975,0)/open.ys.length;summary[name]={openBounds:[open.min,open.max],currentClosureY:target,normalizedPivotAt454:(454-open.min)/(open.max-open.min)};}
 await writeFile(new URL(`../reports/g2/blink-path-${process.argv.includes('--after')?'after':'before'}.json`,import.meta.url),JSON.stringify({summary,results},null,2));console.log(JSON.stringify(summary,null,2));
}finally{await browser.close();}
