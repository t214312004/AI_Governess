import {chromium} from 'playwright';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
const b=await chromium.launch({channel:'msedge'});
try{
const p=await b.newPage();
const shots=[];
const errors=[];
p.on('pageerror',error=>errors.push(String(error)));
for(const variant of ['turn','polish']){
 await p.goto('http://127.0.0.1:5187/shared-face.html?'+variant+'=1');
 await p.waitForFunction(()=>window.__shared?.ready&&window.__shared.frames>3);
 shots.push(await p.locator('#avatar').evaluate(c=>c.toDataURL()));
}
const comparison=await p.evaluate(async urls=>{
 const c=document.createElement('canvas');c.width=1024;c.height=1088;const ctx=c.getContext('2d');
 for(const [i,url] of urls.entries()){
  const im=new Image();im.src=url;await im.decode();
  for(const [j,bg] of ['#f2f2e9','#282832'].entries()){
   const y=j*544;ctx.fillStyle=bg;ctx.fillRect(i*512,y,512,544);ctx.drawImage(im,i*512,y,512,512);
   ctx.fillStyle=j?'white':'#222';ctx.font='18px sans-serif';ctx.fillText(i?'v11':'v10',i*512+12,y+535);
  }
 }return c.toDataURL();
},shots);
await writeFile('reports/g2/polish-comparison.png',Buffer.from(comparison.split(',')[1],'base64'));
await p.click('#listening');
await p.waitForFunction(()=>window.__shared.values.ParamEyeBallX<-.10);
assert.ok(Math.abs(await p.evaluate(()=>window.__shared.values.ParamAngleX))<.08,'The gaze should lead the head turn');
await p.waitForFunction(()=>window.__shared.values.ParamAngleX<-.8);
await p.click('#listening');const before=await p.evaluate(()=>window.__shared.values.ParamAngleX);
await p.waitForTimeout(250);assert.equal(await p.evaluate(()=>window.__shared.values.ParamAngleX),before);
await p.click('#listening');
await p.waitForFunction(()=>window.__shared.values.ParamEyeROpen<.1&&window.__shared.values.ParamEyeLOpen<.1);
await p.waitForFunction(()=>window.__shared.values.ParamAngleY<-1);
await p.locator('#audio').evaluate(a=>a.play());await p.waitForFunction(()=>window.__shared.audioDriven&&window.__shared.values.ParamMouthOpenY>.1);
await p.click('#stop');await p.waitForFunction(()=>window.__shared.values.ParamMouthOpenY===0);assert.equal(await p.evaluate(()=>window.__shared.loads),1);
assert.deepEqual(errors,[]);
const modelSha256=createHash('sha256').update(await readFile('models/polish-face/original.moc3')).digest('hex');
const result={passed:true,modelSha256,gazeLeadsHead:true,blink:true,nod:true,pauseResume:true,audioCombined:true,loads:1,errors};
await writeFile('reports/g2/v11-listening-results.json',JSON.stringify(result,null,2));
console.log(result);
}finally{await b.close()}
