import {chromium} from 'playwright';
import {writeFile,readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import map from '../design/shared-face-runtime-map.json' with {type:'json'};
const browser=await chromium.launch({channel:'msedge',headless:true}),page=await browser.newPage({viewport:{width:1420,height:1100}});
const report={samples:[],errors:[],qualityAccepted:false,modelSha256:createHash('sha256').update(await readFile(new URL('../models/shared-face/model.moc3',import.meta.url))).digest('hex')};
page.on('pageerror',error=>report.errors.push(String(error)));
const set=async value=>{for(const side of ['R','L'])await page.locator('#ParamEye'+side+'Open').fill(String(value));await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));};
try{
 await page.goto('http://127.0.0.1:5187/shared-face.html');await page.waitForFunction(()=>window.__shared?.ready);await set(1);const opened=await page.evaluate(()=>window.__sharedSnapshot());
 for(const value of [.9,.75,.5,.25,.14,.12,.1,.08,.05,0]){
  await set(value);const snapshot=await page.evaluate(()=>window.__sharedSnapshot());const sample={value,sides:{}};report.samples.push(sample);
  for(const side of ['R','L']){
   if(value>=.05)assert.equal(snapshot.meshes[map['Interior'+side].split(':')[1]].opacity,1,'Iris must be occluded by the lid, not faded gray');
   if(value>0&&value<=.12){assert.equal(snapshot.meshes[map['Eye'+side].split(':')[1]].opacity,0);assert.equal(snapshot.meshes[map['Closed'+side].split(':')[1]].opacity,1);}
   const targets={};
   for(const name of ['Eye'+side,'EyeWindow'+side]){
    const id=map[name].split(':')[1],rest=opened.meshes[id].sourceVertices,now=snapshot.meshes[id].sourceVertices,scale=.025+.975*value;
    let sum=0,count=0;for(let i=1;i<rest.length;i+=2){sum+=(now[i]-scale*rest[i])/(1-scale);count++;}targets[name]=sum/count;
   }
   const separation=Math.abs(targets['Eye'+side]-targets['EyeWindow'+side]);assert.ok(separation<.35,`${side} lid/lash closing paths diverge: ${separation} source pixels`);
   sample.sides[side]={impliedClosure:targets,separationSourcePixels:separation};
  }
  if(value>=.25&&value<=.75){
   sample.skinGap=await page.evaluate(()=>{
    const canvas=document.getElementById('avatar'),copy=document.createElement('canvas');copy.width=copy.height=900;const ctx=copy.getContext('2d');ctx.drawImage(canvas,0,0);const data=ctx.getImageData(0,0,900,900).data;const results={};
    const meshes=window.__sharedSnapshot().meshes;
    for(const [side,x] of [['R',420],['R',430],['R',440],['L',580],['L',590],['L',600]]){
     const mask=meshes['ArtMeshEyewhite'+side],v=mask.sourceVertices,indices=mask.indices;let maskY=Infinity;
     for(let t=0;t<indices.length;t+=3)for(let edge=0;edge<3;edge++){
      const a=indices[t+edge]*2,b=indices[t+(edge+1)%3]*2;
      if(v[a]!==v[b]&&x>=Math.min(v[a],v[b])&&x<=Math.max(v[a],v[b]))maskY=Math.min(maskY,v[a+1]+(x-v[a])/(v[b]-v[a])*(v[b+1]-v[a+1]));
     }
     const column=Math.round((x-300)*900/440),bottom=Math.ceil((maskY-265)*900/440),top=bottom-Math.round(18*900/440),dark=[];
     for(let y=top;y<=bottom;y++){const i=(y*900+column)*4;if(data[i]<100&&data[i+1]<80&&data[i+2]<80)dark.push(y);}
     let run=0,longest=0,end=0;
     // Only inspect the boundary after the upper lash, never the pink iris highlight.
     for(let y=dark.at(-1)+1;y<=bottom;y++){const i=(y*900+column)*4;const skin=data[i]>225&&data[i+1]>175&&data[i+1]<235&&data[i+2]>145;run=skin?run+1:0;if(run>longest){longest=run;end=y;}}
     results[side+'-'+x]={maskY,darkSamples:dark.length,longestSkinRunSourcePixels:longest*440/900,skinRunEndY:265+end*440/900};
    }return results;
   });
   for(const result of Object.values(sample.skinGap)){assert.ok(result.darkSamples>3,'No measurable lash/iris column');assert.ok(result.longestSkinRunSourcePixels<1,'Skin band separates lash from iris');}
  }
  await page.locator('#stage').screenshot({path:fileURLToPath(new URL(`../reports/g2/blink-v5-${Math.round(value*100)}.png`,import.meta.url))});
 }
 assert.deepEqual(report.errors,[]);report.passed=true;
}catch(error){report.failure=String(error);await page.locator('#stage').screenshot({path:fileURLToPath(new URL('../reports/g2/blink-failed.png',import.meta.url))});process.exitCode=1;}
finally{await writeFile(new URL('../reports/g2/blink-continuity-results.json',import.meta.url),JSON.stringify(report,null,2));await browser.close();}
console.log(JSON.stringify({passed:report.passed,failure:report.failure,samples:report.samples.length},null,2));
