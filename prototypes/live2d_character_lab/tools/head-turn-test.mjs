import {chromium} from 'playwright';import {readFile,writeFile} from 'node:fs/promises';import {createHash} from 'node:crypto';import assert from 'node:assert/strict';
const polish=process.argv.includes('--polish');
const variant=polish?'polish':'turn';
const modelFolder=polish?'polish-face':'turn-face';
const reportPrefix=polish?'v11-':'';
const report={errors:[],regressions:0,combinations:0,maxRegressionError:0,maxShoulderDrift:0,maxBrowAttachmentChange:0,minSkinAreaRatio:1,maxSkinAreaRatio:1,qualityAccepted:false};
const fit=JSON.parse(await readFile('design/brow-tail-constraints.json','utf8'));
const browser=await chromium.launch({channel:'msedge',headless:true});
const barycentric=(mesh,point)=>{const v=mesh.sourceVertices;for(let k=0;k<mesh.indices.length;k+=3){const ids=mesh.indices.slice(k,k+3),[a,b,c]=ids.map(i=>[v[i*2],v[i*2+1]]),d=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1]);if(Math.abs(d)<1e-8)continue;const u=((b[1]-c[1])*(point[0]-c[0])+(c[0]-b[0])*(point[1]-c[1]))/d,w=((c[1]-a[1])*(point[0]-c[0])+(a[0]-c[0])*(point[1]-c[1]))/d;if(Math.min(u,w,1-u-w)>=-1e-5)return {ids,weights:[u,w,1-u-w]};}throw new Error('Landmark outside skin');};
const pointAt=(v,ids,w)=>[0,1].map(axis=>ids.reduce((sum,id,i)=>sum+v[id*2+axis]*w[i],0));
try{
 const p=await browser.newPage({viewport:{width:1420,height:1100}});await p.route('**/@vite/client',r=>r.fulfill({body:"export const createHotContext=()=>({accept(){},dispose(){},prune(){},on(){},off(){},invalidate(){},send(){},data:{}});const styles=new Map();export function updateStyle(id,content){let el=styles.get(id);if(!el){el=document.createElement('style');document.head.append(el);styles.set(id,el);}el.textContent=content;}export function removeStyle(id){styles.get(id)?.remove();styles.delete(id);}",contentType:'application/javascript'}));p.on('pageerror',e=>report.errors.push(String(e)));
 const wait=()=>p.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
 const set=async values=>{await p.evaluate(values=>{for(const [id,v] of Object.entries(values)){const input=document.getElementById(id);input.value=String(v);input.dispatchEvent(new Event('input',{bubbles:true}));}},values);await wait();};
 const snap=()=>p.evaluate(()=>window.__sharedSnapshot());
 const poses=[-1,0,1].flatMap(form=>[0,.5,1].map(open=>({ParamEyeROpen:open,ParamEyeLOpen:open,ParamMouthOpenY:1-open,ParamMouthWidth:form,ParamMouthForm:-form,ParamEyeBallX:form,ParamEyeBallY:-form,ParamEyeRForm:form,ParamEyeLForm:-form,ParamBrowRY:form,ParamBrowLY:-form,ParamBrowRAngle:-form,ParamBrowLAngle:form,ParamBrowRForm:form,ParamBrowLForm:-form})));
 await p.goto('http://127.0.0.1:5187/shared-face.html?head=1');await p.waitForFunction(()=>window.__shared?.ready);const baseline=[];
 for(const pose of poses)for(const z of [-6,0,6]){await set({...pose,ParamHeadTilt:z});baseline.push(await snap());}
 await p.goto(`http://127.0.0.1:5187/shared-face.html?${variant}=1`);await p.waitForFunction(()=>window.__shared?.ready);assert.equal(await p.locator('#controls input').count(),18);assert.equal(await p.evaluate(()=>window.__shared.drawables),20);assert.deepEqual(await p.evaluate(()=>[window.__shared.ranges.ParamAngleX,window.__shared.ranges.ParamAngleY]),[[-6,6],[-4,4]]);report.modelRangeBounded=true;
 for(let i=0;i<poses.length;i++)for(const [zi,z] of [-6,0,6].entries()){
  const base=baseline[i*3+zi];await set({...poses[i],ParamHeadTilt:z,ParamAngleX:0,ParamAngleY:0});const neutral=await snap();
  for(const [id,old] of Object.entries(base.meshes)){const now=neutral.meshes[id];assert.deepEqual(now.indices,old.indices);assert.deepEqual(now.masks,old.masks);assert.equal(now.opacity,old.opacity);const error=Math.max(...old.sourceVertices.map((v,j)=>Math.abs(v-now.sourceVertices[j])));report.maxRegressionError=Math.max(report.maxRegressionError,error);assert.ok(error<.02,'Regression '+id+': '+error);}report.regressions++;
  const tail=pointAt(base.meshes.ArtMeshEyebrowR.sourceVertices,fit.triangle,fit.weights),attachment=barycentric(base.meshes.ArtMeshFace,tail),skin=base.meshes.ArtMeshFace;
  for(const x of [-6,-3,0,3,6])for(const y of [-4,-2,0,2,4]){
   await set({ParamAngleX:x,ParamAngleY:y});const now=await snap(),current=now.meshes.ArtMeshFace;
   for(const [id,old] of Object.entries(base.meshes)){const mesh=now.meshes[id];assert.ok(Math.abs(mesh.opacity-old.opacity)<1e-5,'Opacity changed '+id);assert.deepEqual(mesh.masks,old.masks);assert.ok(mesh.sourceVertices.every(Number.isFinite));}
   for(let k=0;k<skin.sourceVertices.length;k+=2)if(baseline[i*3+1].meshes.ArtMeshFace.sourceVertices[k+1]>=800){const drift=Math.hypot(current.sourceVertices[k]-skin.sourceVertices[k],current.sourceVertices[k+1]-skin.sourceVertices[k+1]);report.maxShoulderDrift=Math.max(report.maxShoulderDrift,drift);assert.ok(drift<.15,'Shoulder drift '+JSON.stringify({x,y,z,drift}));}
   const expected=pointAt(current.sourceVertices,attachment.ids,attachment.weights),actual=pointAt(now.meshes.ArtMeshEyebrowR.sourceVertices,fit.triangle,fit.weights),gap=Math.hypot(expected[0]-actual[0],expected[1]-actual[1]);report.maxBrowAttachmentChange=Math.max(report.maxBrowAttachmentChange,gap);assert.ok(gap<.35,'Brow attachment changed: '+gap);
   for(let k=0;k<skin.indices.length;k+=3){const ids=skin.indices.slice(k,k+3),area=v=>{const [a,b,c]=ids.map(j=>[v[j*2],v[j*2+1]]);return (b[0]-a[0])*(c[1]-a[1])-(c[0]-a[0])*(b[1]-a[1]);};const a=area(skin.sourceVertices);if(Math.abs(a)<.1)continue;const ratio=area(current.sourceVertices)/a;assert.ok(ratio>0,'Skin triangle flipped');report.minSkinAreaRatio=Math.min(report.minSkinAreaRatio,ratio);report.maxSkinAreaRatio=Math.max(report.maxSkinAreaRatio,ratio);}
   report.combinations++;
  }
 }
 for(const name of ['neutral','turnLeft','turnRight','pitchUp','pitchDown','turnSpeaking']){await p.locator(`[data-preset=${name}]`).click();await wait();await writeFile(`reports/g2/${reportPrefix}turn-${name}.png`,Buffer.from((await p.locator('#avatar').evaluate(c=>c.toDataURL())).split(',')[1],'base64'));}
 for(const [id,axis] of [['slow-yaw','ParamAngleX'],['slow-pitch','ParamAngleY']]){await p.locator('#'+id).click();await p.waitForFunction(axis=>window.__shared.values[axis]>1,axis);await p.locator('#'+id).click();await wait();const paused=(await snap()).values;await p.waitForTimeout(150);assert.deepEqual((await snap()).values,paused);}report.pausePassed=true;
 await p.locator('#audio').evaluate(a=>a.play());await p.waitForFunction(()=>window.__shared.audioDriven&&window.__shared.values.ParamMouthOpenY>.08);await p.locator('#sequence').click();await p.waitForFunction(()=>Math.abs(window.__shared.values.ParamAngleX)>1);assert.ok(await p.evaluate(()=>window.__shared.audioDriven));await p.locator('#stop').click();await wait();assert.equal((await snap()).values.ParamMouthOpenY,0);report.audioCombined=true;
 assert.equal((await snap()).loads,1);assert.deepEqual(report.errors,[]);report.modelSha256=createHash('sha256').update(await readFile(`models/${modelFolder}/original.moc3`)).digest('hex');report.passed=true;
}catch(e){report.failure=String(e);process.exitCode=1;}
finally{await browser.close();await writeFile(`reports/g2/${reportPrefix}head-turn-results.json`,JSON.stringify(report,null,2));}
console.log(JSON.stringify(report,null,2));
