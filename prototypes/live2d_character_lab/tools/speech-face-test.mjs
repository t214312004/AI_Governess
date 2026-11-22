import {chromium} from 'playwright';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
import map from '../design/speech-face-runtime-map.json' with {type:'json'};
import acceptedMap from '../design/gaze-face-runtime-map.json' with {type:'json'};
const root=new URL('../',import.meta.url),report={errors:[],mouthCombinations:[],eyeCombinations:[],qualityAccepted:false};
const browser=await chromium.launch({channel:'msedge',headless:true}),page=await browser.newPage({viewport:{width:1420,height:1100}});
page.on('pageerror',e=>report.errors.push(String(e)));
const wait=()=>page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
const set=async values=>{for(const [id,value] of Object.entries(values))await page.locator('#'+id).fill(String(value));await wait();};
const snap=()=>page.evaluate(()=>window.__sharedSnapshot());
const mesh=(s,name,mapping=map)=>s.meshes[mapping[name].split(':')[1]];
const bounds=m=>{const x=m.sourceVertices.filter((_,i)=>i%2===0),y=m.sourceVertices.filter((_,i)=>i%2===1);return {cx:(Math.min(...x)+Math.max(...x))/2,cy:(Math.min(...y)+Math.max(...y))/2,width:Math.max(...x)-Math.min(...x),height:Math.max(...y)-Math.min(...y)};};
const capture=async name=>{const url=await page.locator('#avatar').evaluate(c=>c.toDataURL());await writeFile(new URL(`reports/g2/speech-${name}.png`,root),Buffer.from(url.split(',')[1],'base64'));};
const measure=()=>page.evaluate(()=>window.__measureSharedReference());
const reference=async source=>{
 await page.locator('#reference-state').selectOption(source);await page.waitForFunction(name=>window.__sharedReference.ready&&window.__sharedReference.source===name,source);
 await page.locator('#apply-reference').click();await wait();
};
try{
 await page.goto('http://127.0.0.1:5187/shared-face.html?gaze=1');await page.waitForFunction(()=>window.__shared?.ready);await wait();const accepted=await snap();
 await page.getByText('與原圖校對',{exact:true}).click();await reference('idle_listen_1');report.beforeClosed=await measure();await capture('v6-closed');
 await reference('speaking_1');report.beforeSpeaking=await measure();await capture('v6-open');
 await page.goto('http://127.0.0.1:5187/shared-face.html?speech=1');await page.waitForFunction(()=>window.__shared?.ready);await wait();
 assert.equal(await page.locator('#controls input').count(),11);assert.equal(await page.evaluate(()=>window.__shared.drawables),20);
 const neutral=await snap();
 for(const name of Object.keys(acceptedMap).filter(n=>!['Mouth','OpenMouth'].includes(n))){
  const a=mesh(accepted,name,acceptedMap),b=mesh(neutral,name);assert.equal(a.sourceVertices.length,b.sourceVertices.length,name+' topology');
  assert.ok(a.sourceVertices.every((v,i)=>Math.abs(v-b.sourceVertices[i])<.01),name+' changed outside mouth');
 }
 report.nonMouthGeometryPreserved=true;
 await page.getByText('與原圖校對',{exact:true}).click();await reference('idle_listen_1');report.afterClosed=await measure();await capture('neutral');
 assert.ok(Math.abs(report.afterClosed.mae.mouth-report.beforeClosed.mae.mouth)<.01,'Closed-mouth fidelity must preserve accepted v6');
 await reference('speaking_1');report.afterSpeaking=await measure();await capture('open');
 assert.ok(report.afterSpeaking.mae.mouth<report.beforeSpeaking.mae.mouth,'Speaking mouth must improve against the fixed original ROI');
 for(const width of [-1,0,1])for(const form of [-1,0,1])for(const opening of [0,.05,.15,.25,.5,.75,1]){
  await set({ParamMouthWidth:width,ParamMouthForm:form,ParamMouthOpenY:opening});const s=await snap(),lip=mesh(s,'LowerLip');
  assert.equal(lip.opacity,1,'Lower lip must not disappear or crossfade');assert.ok(bounds(lip).height>8,'Lower lip must keep thickness');
  assert.ok(Object.values(s.meshes).every(m=>m.vertices.every(Number.isFinite)));
  assert.ok(Math.abs(mesh(s,'OpenMouth').opacity-Math.min(1,opening/.15))<1e-6);assert.ok(Math.abs(mesh(s,'Mouth').opacity-Math.max(0,1-opening/.15))<1e-6);
  const b=bounds(lip);report.mouthCombinations.push({width,form,opening,lip:b});
  if(form===0&&width===0&&[0,.25,.5,.75,1].includes(opening))await capture('opening-'+opening);
 }
 const middle=report.mouthCombinations.filter(x=>x.width===0&&x.form===0);
 for(let i=1;i<middle.length;i++)assert.ok(middle[i].lip.cy>middle[i-1].lip.cy,'Lower lip must follow opening continuously');
 assert.ok(middle.at(-1).lip.cy-middle[0].lip.cy>9,'Lower lip should travel to the source open-mouth position');
 const wide=report.mouthCombinations.find(x=>x.width===1&&x.form===0&&x.opening===1),narrow=report.mouthCombinations.find(x=>x.width===-1&&x.form===0&&x.opening===1);
 assert.ok(wide.lip.width>narrow.lip.width*1.3);
 for(const gaze of [-1,0,1])for(const opening of [0,.05,.12,.25,.5,.75,1]){
  await set({ParamEyeBallX:gaze,ParamEyeBallY:-gaze,ParamEyeROpen:opening,ParamEyeLOpen:opening});const s=await snap();
  for(const side of ['R','L']){
   assert.equal(mesh(s,'Iris'+side).opacity,opening===0?0:1);assert.deepEqual(mesh(s,'Iris'+side).masks,[map['EyeWindow'+side].split(':')[1]]);
   if(opening<1){
    const centers=[];for(const name of ['Eye'+side,'EyeWindow'+side]){const a=mesh(neutral,name).sourceVertices,b=mesh(s,name).sourceVertices,k=.025+.975*opening;let sum=0;for(let i=1;i<a.length;i+=2)sum+=(b[i]-k*a[i])/(1-k);centers.push(sum/(a.length/2));}
    assert.ok(Math.abs(centers[0]-centers[1])<.35,'Shared eyelid/lash path regressed');
   }
  }report.eyeCombinations.push({gaze,opening});
 }
 await page.locator('[data-preset=neutral]').click();await page.locator('#slow-mouth').click();await page.waitForFunction(()=>window.__shared.values.ParamMouthOpenY>.2);
 await page.locator('#slow-mouth').click();const paused=(await snap()).values.ParamMouthOpenY;await page.waitForTimeout(150);assert.equal((await snap()).values.ParamMouthOpenY,paused);report.slowMouthPause=true;
 await page.locator('#audio').evaluate(a=>a.play());await page.waitForFunction(()=>window.__shared.audioDriven&&window.__shared.values.ParamMouthOpenY>.08);
 await set({ParamMouthWidth:-.5});assert.equal((await snap()).values.ParamMouthWidth,-.5);assert.ok(await page.evaluate(()=>window.__shared.audioDriven));
 await page.locator('#stop').click();await wait();assert.equal((await snap()).values.ParamMouthOpenY,0);assert.equal(mesh(await snap(),'LowerLip').opacity,1);
 report.audioWithWidth=true;assert.equal((await snap()).loads,1);assert.deepEqual(report.errors,[]);
 const file=new URL('models/speech-face/model.model3.json',root),model=JSON.parse(await readFile(file,'utf8'));report.assetHashes={};
 for(const name of ['model.model3.json',model.FileReferences.Moc,...model.FileReferences.Textures])report.assetHashes[name]=createHash('sha256').update(await readFile(new URL(name,file))).digest('hex');
 report.passed=true;
}catch(error){report.failure=String(error);process.exitCode=1;}
finally{await browser.close();await writeFile(new URL('reports/g2/speech-face-results.json',root),JSON.stringify(report,null,2));}
console.log(JSON.stringify({passed:report.passed,failure:report.failure,mouthCombinations:report.mouthCombinations.length,eyeCombinations:report.eyeCombinations.length,mouthBefore:report.beforeSpeaking?.mae.mouth,mouthAfter:report.afterSpeaking?.mae.mouth,closedBefore:report.beforeClosed?.mae.mouth,closedAfter:report.afterClosed?.mae.mouth},null,2));
