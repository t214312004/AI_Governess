import {chromium} from 'playwright';import {readFile,writeFile} from 'node:fs/promises';import {createHash} from 'node:crypto';import assert from 'node:assert/strict';import {fitEyeAffine} from './eye-affine.mjs';
const polish=process.argv.includes('--polish');
const variant=polish?'polish':'turn';
const modelFolder=polish?'polish-face':'turn-face';
const reportPrefix=polish?'v11-':'';
const report={samples:0,maxEnvelopeFitError:0,maxClosingPathSeparation:0,errors:[],qualityAccepted:false};
const b=await chromium.launch({channel:'msedge',headless:true});
try{
 const p=await b.newPage();await p.goto(`http://127.0.0.1:5187/shared-face.html?${variant}=1`);await p.waitForFunction(()=>window.__shared?.ready);
 const wait=()=>p.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));const set=async values=>{await p.evaluate(values=>{for(const [id,v] of Object.entries(values)){const el=document.getElementById(id);el.value=String(v);el.dispatchEvent(new Event('input',{bubbles:true}));}},values);await wait();};const snap=()=>p.evaluate(()=>window.__sharedSnapshot());
 p.on('pageerror',e=>report.errors.push(String(e)));await p.locator('[data-preset=neutral]').click();await wait();const original=await snap();
 for(const x of [-6,0,6])for(const y of [-4,0,4]){
  await set({ParamAngleX:x,ParamAngleY:y,ParamHeadTilt:4,ParamEyeROpen:1,ParamEyeLOpen:1});const opened=await snap(),maps={};
  for(const side of ['R','L']){const id='ArtMeshEyewhite'+side;maps[side]=fitEyeAffine(original.meshes[id].sourceVertices,opened.meshes[id].sourceVertices);report.maxEnvelopeFitError=Math.max(report.maxEnvelopeFitError,maps[side].maxError);assert.ok(maps[side].maxError<.5,'Eye projection too nonlinear for closure comparison');}
  for(const value of [.9,.75,.5,.25,.14,.12,.1,.08,.05,0]){
   await set({ParamEyeROpen:value,ParamEyeLOpen:value});const current=await snap();
   for(const side of ['R','L']){
    const targets=[];for(const name of ['ArtMeshEyelash','ArtMeshEyewhite']){const id=name+side,rest=maps[side].inverse(opened.meshes[id].sourceVertices),now=maps[side].inverse(current.meshes[id].sourceVertices),scale=.025+.975*value;let sum=0,n=0;for(let k=1;k<rest.length;k+=2){sum+=(now[k]-scale*rest[k])/(1-scale);n++;}targets.push(sum/n);}
    const gap=Math.abs(targets[0]-targets[1]);report.maxClosingPathSeparation=Math.max(report.maxClosingPathSeparation,gap);assert.ok(gap<.35,'Lid/lash paths separated: '+JSON.stringify({x,y,value,side,gap}));
    if(value<=.12){assert.equal(current.meshes['ArtMeshEyelash'+side].opacity,0);assert.ok(Math.abs(current.meshes['ArtMeshEyeClose'+side].opacity-1)<1e-5);}
   }report.samples++;
  }
 }
 assert.deepEqual(report.errors,[]);report.modelSha256=createHash('sha256').update(await readFile(`models/${modelFolder}/original.moc3`)).digest('hex');report.passed=true;
}catch(e){report.failure=String(e);process.exitCode=1;}
finally{await b.close();await writeFile(`reports/g2/${reportPrefix}head-turn-blink-results.json`,JSON.stringify(report,null,2));}console.log(report);
