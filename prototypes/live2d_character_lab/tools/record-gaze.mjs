import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
process.env.PLAYWRIGHT_BROWSERS_PATH=fileURLToPath(new URL('../.cache/playwright/',import.meta.url));
const {chromium}=await import('playwright');
const browser=await chromium.launch({channel:'msedge',headless:true});
const context=await browser.newContext({viewport:{width:900,height:900},recordVideo:{dir:fileURLToPath(new URL('../.cache/recordings/',import.meta.url)),size:{width:900,height:900}}});
const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(String(e)));
try{
 await page.goto('http://127.0.0.1:5187/shared-face.html?gaze=1');await page.waitForFunction(()=>window.__shared?.ready);
 await page.addStyleTag({content:'body{margin:0}main{padding:0;width:900px;max-width:none}header,aside{display:none}.workspace{display:block}.stage{width:900px;height:900px;border-radius:0;top:0!important}'});
 await page.evaluate(async()=>{
  const frames=[[0,0,1],[-1,0,1],[0,0,1],[1,0,1],[0,1,1],[0,-1,1],[-.7,-.5,1],[-.7,-.5,0],[-.7,-.5,1],[0,0,1]];
  const duration=1.4,start=performance.now();
  await new Promise(resolve=>{
   function tick(now){
    const position=(now-start)/1000/duration,index=Math.min(Math.floor(position),frames.length-2),f=Math.min(position-index,1),t=f*f*(3-2*f);
    const values=frames[index].map((v,i)=>v+(frames[index+1][i]-v)*t);
    for(const [id,value] of Object.entries({ParamEyeBallX:values[0],ParamEyeBallY:values[1],ParamEyeROpen:values[2],ParamEyeLOpen:values[2]})){
     const input=document.getElementById(id);input.value=String(value);input.dispatchEvent(new Event('input',{bubbles:true}));
    }
    if(position>=frames.length-1)resolve();else requestAnimationFrame(tick);
   }
   requestAnimationFrame(tick);
  });
 });
 await context.close();await page.video().saveAs(fileURLToPath(new URL('../reports/g2/gaze-v6.webm',import.meta.url)));
 const hash=createHash('sha256').update(await readFile(new URL('../models/gaze-face/model.moc3',import.meta.url))).digest('hex');
 await writeFile(new URL('../reports/g2/gaze-recording.json',import.meta.url),JSON.stringify({file:'gaze-v6.webm',silent:true,modelSha256:hash,errors,scope:'Programmatic small gaze movements and a slow blink; candidate only'},null,2));
 if(errors.length)throw new Error(errors.join('\n'));console.log('Saved silent gaze and blink recording.');
}finally{await browser.close();}
