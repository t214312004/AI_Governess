import {chromium} from 'playwright';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
const report={errors:[],neutralRegressions:0,combinations:0,denseTiltSamples:0,neutralErrorByMesh:{},maxNeutralError:0,maxFaceRigidError:0,maxShoulderDrift:0,minNeckAreaRatio:1,maxNeckAreaRatio:1,qualityAccepted:false};
const browser=await chromium.launch({channel:'msedge',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1420,height:1100}});page.on('pageerror',e=>report.errors.push(String(e)));
 const wait=()=>page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
 const set=async values=>{await page.evaluate(values=>{for(const [id,v] of Object.entries(values)){const input=document.getElementById(id);input.value=String(v);input.dispatchEvent(new Event('input',{bubbles:true}));}},values);await wait();};
 const snap=()=>page.evaluate(()=>window.__sharedSnapshot());
 const capture=async name=>{const url=await page.locator('#avatar').evaluate(c=>c.toDataURL());await writeFile(`reports/g2/head-${name}.png`,Buffer.from(url.split(',')[1],'base64'));};
 const poses=[-1,0,1].flatMap(form=>[0,.5,1].flatMap(open=>[0,.5,1].map(mouth=>({ParamEyeBallX:form,ParamEyeBallY:-form,ParamEyeROpen:open,ParamEyeLOpen:open,ParamMouthOpenY:mouth,ParamMouthWidth:form,ParamMouthForm:-form,ParamBrowRY:form,ParamBrowLY:-form,ParamBrowRAngle:-form,ParamBrowLAngle:form,ParamBrowRForm:form,ParamBrowLForm:-form,ParamEyeRForm:form,ParamEyeLForm:-form}))));
 await page.goto('http://127.0.0.1:5187/shared-face.html?expression=1');await page.waitForFunction(()=>window.__shared?.ready);const baseline=[];
 for(const pose of poses){await set(pose);baseline.push(await snap());}
 await page.goto('http://127.0.0.1:5187/shared-face.html?head=1');await page.waitForFunction(()=>window.__shared?.ready);
 assert.equal(await page.locator('#controls input').count(),16);assert.equal(await page.evaluate(()=>window.__shared.drawables),20);
 for(let i=0;i<poses.length;i++){
  await set({...poses[i],ParamHeadTilt:0});let current=await snap();
  for(const [id,old] of Object.entries(baseline[i].meshes)){
   const now=current.meshes[id];assert.deepEqual(now.indices,old.indices);assert.deepEqual(now.masks,old.masks);assert.equal(now.opacity,old.opacity);
   const error=Math.max(...old.sourceVertices.map((v,j)=>Math.abs(v-now.sourceVertices[j])));report.maxNeutralError=Math.max(report.maxNeutralError,error);report.neutralErrorByMesh[id]=Math.max(report.neutralErrorByMesh[id]??0,error);assert.ok(error<.02,'Neutral changed '+id+': '+error);
  }report.neutralRegressions++;
  for(const tilt of [-6,-3.75,0,3.75,6]){
   await set({ParamHeadTilt:tilt});current=await snap();const angle=tilt*Math.PI/180,cos=Math.cos(angle),sin=Math.sin(angle);
   for(const [id,old] of Object.entries(baseline[i].meshes)){
    const now=current.meshes[id];assert.equal(now.opacity,old.opacity);assert.deepEqual(now.masks,old.masks);assert.ok(now.sourceVertices.every(Number.isFinite));
    for(let k=0;k<old.sourceVertices.length;k+=2){
     const x=old.sourceVertices[k],y=old.sourceVertices[k+1],nx=now.sourceVertices[k],ny=now.sourceVertices[k+1];
     if(id!=='ArtMeshFace'||y<600){const expected=[512+(x-512)*cos-(y-750)*sin,750+(x-512)*sin+(y-750)*cos],error=Math.hypot(nx-expected[0],ny-expected[1]);report.maxFaceRigidError=Math.max(report.maxFaceRigidError,error);assert.ok(error<.02,'Head feature detached: '+id+' '+error);}
     if(id==='ArtMeshFace'&&y>=800){const drift=Math.hypot(nx-x,ny-y);report.maxShoulderDrift=Math.max(report.maxShoulderDrift,drift);assert.ok(drift<.15,'Shoulder moved at '+tilt+': '+drift);}
    }
    if(id==='ArtMeshFace')for(let k=0;k<old.indices.length;k+=3){
     const ids=old.indices.slice(k,k+3),ys=ids.map(j=>old.sourceVertices[2*j+1]);if(Math.min(...ys)>850||Math.max(...ys)<600)continue;
     const area=v=>{const [a,b,c]=ids.map(j=>[v[2*j],v[2*j+1]]);return (b[0]-a[0])*(c[1]-a[1])-(c[0]-a[0])*(b[1]-a[1]);};
     const a=area(old.sourceVertices),b=area(now.sourceVertices);if(Math.abs(a)<.01)continue;const ratio=b/a;assert.ok(ratio>0,'Neck triangle flipped');report.minNeckAreaRatio=Math.min(report.minNeckAreaRatio,ratio);report.maxNeckAreaRatio=Math.max(report.maxNeckAreaRatio,ratio);
    }
   }
   report.combinations++;
  }
 }
 // Dense sweep covers every authored key and intermediate values. The rotation
 // insertion changes exported half-open lid vertices by <= 0.011 source pixels;
 // the 0.02 px neutral/face limit records this, rather than claiming exact equality.
 const oldSkin=baseline.at(-1).meshes.ArtMeshFace.sourceVertices;
 for(let tilt=-6;tilt<=6;tilt+=.25){
  await set({ParamHeadTilt:tilt});const now=(await snap()).meshes.ArtMeshFace.sourceVertices;
  for(let k=0;k<oldSkin.length;k+=2)if(oldSkin[k+1]>=800){const drift=Math.hypot(now[k]-oldSkin[k],now[k+1]-oldSkin[k+1]);report.maxShoulderDrift=Math.max(report.maxShoulderDrift,drift);assert.ok(drift<.15,'Dense sweep shoulder drift '+tilt);}
  report.denseTiltSamples++;
 }
 await page.locator('[data-preset=neutral]').click();await wait();await capture('neutral');
 for(const tilt of [-6,6]){await set({ParamHeadTilt:tilt});await capture('tilt-'+tilt);}
 await page.locator('[data-preset=tiltSpeaking]').click();await wait();await capture('speaking');
 await page.locator('#slow-head').click();await page.waitForFunction(()=>window.__shared.values.ParamHeadTilt>5.9);await page.locator('#slow-head').click();await wait();const paused=(await snap()).values;await page.waitForTimeout(150);assert.deepEqual((await snap()).values,paused);report.pausePassed=true;
 await page.locator('#audio').evaluate(a=>a.play());await page.waitForFunction(()=>window.__shared.audioDriven&&window.__shared.values.ParamMouthOpenY>.08);await set({ParamHeadTilt:-4});assert.ok(await page.evaluate(()=>window.__shared.audioDriven));await page.locator('#stop').click();await wait();assert.equal((await snap()).values.ParamMouthOpenY,0);report.audioCombined=true;
 await page.locator('#sequence').click();await page.waitForFunction(()=>Math.abs(window.__shared.values.ParamHeadTilt)>1);await page.locator('#stop').click();report.tiltInSequence=true;
 assert.equal((await snap()).loads,1);assert.deepEqual(report.errors,[]);report.modelSha256=createHash('sha256').update(await readFile('models/head-face/original.moc3')).digest('hex');report.passed=true;
}catch(e){report.failure=String(e);process.exitCode=1;}
finally{await browser.close();await writeFile('reports/g2/head-neck-results.json',JSON.stringify(report,null,2));}
console.log(JSON.stringify(report,null,2));
