import {chromium} from 'playwright';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import runtimeMap from '../design/shared-face-runtime-map.json' with {type:'json'};
const directory=new URL('../reports/g2/',import.meta.url);await mkdir(directory,{recursive:true});
const model=new URL('../models/shared-face/model.moc3',import.meta.url);
const digest=async()=>createHash('sha256').update(await readFile(model)).digest('hex');
const assetHashes=async()=>{const manifest=new URL('../models/shared-face/model.model3.json',import.meta.url),info=JSON.parse(await readFile(manifest,'utf8')),hashes={};for(const path of ['model.model3.json',info.FileReferences.Moc,...info.FileReferences.Textures])hashes[path]=createHash('sha256').update(await readFile(new URL(path,manifest))).digest('hex');return hashes;};
const report={modelSha256:await digest(),errors:[],requests:[],independence:[],sweeps:[],combinations:[],qualityAccepted:false};
report.assetHashes=await assetHashes();
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:1420,height:1250}});
page.on('pageerror',e=>report.errors.push(String(e)));page.on('request',r=>{if(r.url().endsWith('.moc3'))report.requests.push(r.url());});
page.on('response',r=>{if(r.status()>=400)report.errors.push(`${r.status()} ${r.url()}`);});
const wait=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
const set=async(id,value)=>{await page.locator('#'+id).fill(String(value));await wait();};
const neutral=async()=>{await page.locator('[data-preset=neutral]').click();await wait();};
const snapshot=()=>page.evaluate(()=>window.__sharedSnapshot());
const changed=(a,b,id)=>JSON.stringify(a.meshes[id])!==JSON.stringify(b.meshes[id]);
const capture=async name=>page.locator('#stage').screenshot({path:fileURLToPath(new URL(`shared-${name}.png`,directory))});
try{
  await page.goto('http://127.0.0.1:5187/shared-face.html');
  await page.waitForFunction(()=>window.__shared?.ready||window.__shared?.error);
  assert.equal(await page.evaluate(()=>window.__shared.error),'');await wait();
  const initial=await page.evaluate(()=>window.__shared);report.initial=initial;
  assert.equal(initial.drawables,17);assert.ok(!initial.parameters.includes('ParamReferenceFrame'));
  await capture('neutral');
  for(const side of ['R','L']){
    await neutral();const a=await snapshot();const id='ParamEye'+side+'Open',fold=runtimeMap['Fold'+side].split(':')[1],interior=runtimeMap['Interior'+side].split(':')[1];
    await set(id,.5);const mid=await snapshot();assert.notDeepEqual(a.meshes[fold].vertices,mid.meshes[fold].vertices,'Crease must follow the upper lid');assert.ok(mid.meshes[fold].opacity>0&&mid.meshes[fold].opacity<1);
    assert.deepEqual(a.meshes[interior].vertices,mid.meshes[interior].vertices,'Blink must not squash the iris');assert.deepEqual(mid.meshes[interior].masks,[runtimeMap['EyeWindow'+side].split(':')[1]]);
    await set(id,0);const closed=await snapshot();assert.equal(closed.meshes[fold].opacity,0,'Open-eye crease must disappear on closure');assert.equal(closed.meshes[runtimeMap['ClosedFold'+side].split(':')[1]].opacity,1);
  }
  report.creaseAndClippingPassed=true;
  for(const side of ['R','L']){
    await neutral();const id=runtimeMap['Brow'+side].split(':')[1];await set('ParamBrow'+side+'Angle',.5);const angleOnly=await snapshot();await set('ParamBrow'+side+'Y',-.6);const combined=await snapshot();
    assert.notDeepEqual(combined.meshes[id].vertices,angleOnly.meshes[id].vertices,'Height must still work with brow rotation');
    await set('ParamBrow'+side+'Angle',0);const heightOnly=await snapshot();assert.notDeepEqual(combined.meshes[id].vertices,heightOnly.meshes[id].vertices,'Rotation must still work with brow height');
  }
  report.browCombinationPassed=true;
  for(const form of [-1,-.5,0,.5,1]){
    await neutral();await set('ParamMouthForm',form);let s=await snapshot();assert.equal(s.meshes.ArtMeshMouthOpen.opacity,0,'Mouth form reopens the hidden open-mouth mesh');assert.equal(s.meshes.ArtMeshMouthClose.opacity,1);
    await set('ParamMouthOpenY',1);s=await snapshot();assert.equal(s.meshes.ArtMeshMouthClose.opacity,0,'Mouth form shows both mouth meshes');assert.equal(s.meshes.ArtMeshMouthOpen.opacity,1);
  }
  report.mouthOpacityGridPassed=true;
  const independence=[
    ['ParamBrowRAngle',1,'ArtMeshEyebrowR','ArtMeshEyebrowL'],
    ['ParamBrowRY',1,'ArtMeshEyebrowR','ArtMeshEyebrowL'],
    ['ParamEyeROpen',.35,'ArtMeshEyelashR','ArtMeshEyelashL'],
    ['ParamMouthOpenY',.7,'ArtMeshMouthOpen','ArtMeshEyebrowL'],
    ['ParamMouthForm',1,'ArtMeshMouthClose','ArtMeshEyelashR']
  ];
  for(const [id,value,moving,still] of independence){await neutral();const a=await snapshot();await set(id,value);const b=await snapshot();assert.ok(changed(a,b,moving),id+' has no effect');assert.ok(!changed(a,b,still),id+' changes unrelated feature');report.independence.push({id,moving,still,passed:true});}
  for(const id of ['ParamEyeROpen','ParamEyeLOpen','ParamBrowRY','ParamBrowLY','ParamBrowRAngle','ParamBrowLAngle','ParamMouthForm','ParamMouthOpenY']){
    await neutral();const min=Number(await page.locator('#'+id).getAttribute('min'));const states=[];
    for(const value of [min,(min*3+1)/4,(min+1)/2,(min+3)/4,1]){await set(id,value);const s=await snapshot();assert.ok(Object.values(s.meshes).every(m=>m.vertices.every(Number.isFinite)));assert.equal(s.values[id],value);states.push({value,geometryHash:createHash('sha256').update(JSON.stringify(s.meshes)).digest('hex')});}
    assert.equal(new Set(states.map(s=>s.geometryHash)).size,5,id+' lacks continuous variation');report.sweeps.push({id,states});
  }
  for(const preset of ['neutral','curious','thoughtful','warm','wink','surprised']){await page.locator(`[data-preset=${preset}]`).click();await wait();report.combinations.push({preset,...(await snapshot()).values});await capture(preset);}
  for(const [name,values] of Object.entries({halfblink:{ParamEyeROpen:.5,ParamEyeLOpen:.5},closed:{ParamEyeROpen:0,ParamEyeLOpen:0},halfopen:{ParamMouthOpenY:.5},open:{ParamMouthOpenY:1},unseen:{ParamEyeROpen:.35,ParamEyeLOpen:.85,ParamBrowRAngle:-.7,ParamBrowLY:.45,ParamMouthForm:-.6,ParamMouthOpenY:.4}})){
    await neutral();for(const [id,value] of Object.entries(values))await set(id,value);report.combinations.push({name,...(await snapshot()).values});await capture(name);
  }
  await page.getByText('與原圖校對',{exact:true}).click();report.referenceComparisons=[];
  for(const source of ['idle_listen_1','idle_listen_4','speaking_1']){
    await page.locator('#reference-state').selectOption(source);await page.waitForFunction(name=>window.__sharedReference.ready&&window.__sharedReference.source===name,source);
    await page.locator('#apply-reference').click();await wait();const measurement=await page.evaluate(()=>window.__measureSharedReference());
    assert.equal(measurement.source,source);assert.ok(Object.values(measurement.mae).every(Number.isFinite));assert.equal(measurement.qualityAccepted,false);report.referenceComparisons.push(measurement);
    for(const mode of ['overlay','difference']){await page.locator('#reference-mode').selectOption(mode);await wait();await capture(`reference-${source}-${mode}`);}
  }
  await page.locator('#reference-mode').selectOption('model');
  await page.locator('#slow-blink').click();await page.waitForFunction(()=>window.__shared.values.ParamEyeROpen<.08,{},{timeout:15000});
  await page.locator('#slow-blink').click();await wait();const held=(await snapshot()).values.ParamEyeROpen;await page.waitForTimeout(150);assert.equal((await snapshot()).values.ParamEyeROpen,held);report.slowBlinkPausePassed=true;
  await page.locator('#sequence').click();
  report.motionSamples=await page.evaluate(async()=>{const samples=[];for(let i=0;i<24;i++){await new Promise(r=>setTimeout(r,200));samples.push({...window.__shared.values});}return samples;});
  assert.ok(new Set(report.motionSamples.map(s=>s.ParamBrowRY.toFixed(3))).size>10);assert.equal(await page.evaluate(()=>window.__shared.cycling),true);
  await neutral();await page.locator('#audio').evaluate(a=>a.play());
  await page.waitForFunction(()=>window.__shared.values.ParamMouthOpenY>.05,{},{timeout:15000});
  report.audioPeakObserved=await page.evaluate(()=>window.__shared.values.ParamMouthOpenY);
  await page.locator('[data-preset=curious]').click();await wait();assert.equal(await page.evaluate(()=>window.__shared.audioDriven),true);
  await page.locator('#sequence').click();await wait();assert.equal(await page.evaluate(()=>window.__shared.cycling&&window.__shared.audioDriven),true);
  await set('ParamMouthOpenY',.4);assert.equal((await snapshot()).values.ParamMouthOpenY,.4);
  assert.equal(await page.locator('#audio').evaluate(a=>a.paused),true);
  await page.locator('#audio').evaluate(a=>{a.currentTime=0;return a.play();});await page.waitForFunction(()=>window.__shared.values.ParamMouthOpenY>.05);
  await page.locator('#audio').evaluate(a=>{a.muted=true;});await wait();assert.equal((await snapshot()).values.ParamMouthOpenY,0);
  await page.locator('#sequence').click();await page.locator('#stop').click();await wait();assert.equal((await snapshot()).values.ParamMouthOpenY,0);assert.equal(await page.evaluate(()=>window.__shared.cycling),false);
  assert.equal(await page.evaluate(()=>window.__shared.loads),1);assert.equal(report.requests.length,1);assert.deepEqual(report.errors,[]);assert.equal(await digest(),report.modelSha256);assert.deepEqual(await assetHashes(),report.assetHashes);
  report.structuralPassed=true;
}catch(error){report.failure=String(error);process.exitCode=1;}
finally{await writeFile(new URL('shared-face-results.json',directory),JSON.stringify(report,null,2));await browser.close();}
console.log(JSON.stringify({structuralPassed:report.structuralPassed,failure:report.failure,independentControls:report.independence.length,continuousSweeps:report.sweeps.length,combinations:report.combinations.length,errors:report.errors,qualityAccepted:report.qualityAccepted},null,2));
