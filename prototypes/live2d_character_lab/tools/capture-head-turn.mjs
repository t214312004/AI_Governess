import {createHash} from 'node:crypto';
import {chromium} from 'playwright';import {readFile,writeFile} from 'node:fs/promises';
const b=await chromium.launch({channel:'msedge',headless:true});const keys=JSON.parse(await readFile('design/head-turn-keys.json','utf8'));
try{
const p=await b.newPage();await p.route('**/@vite/client',r=>r.fulfill({body:'',contentType:'application/javascript'}));await p.goto('http://127.0.0.1:5187/.cache/probe-v10.html');
const samples=await p.evaluate(async keys=>{
const {Avatar}=await import('/viewer/avatar.ts'),c=document.createElement('canvas');c.width=c.height=900;document.body.append(c);const gl=c.getContext('webgl');const a=await Avatar.open('/generated/models/turn-face/original.model3.json',gl,c),m=a.getModel(),info=m.getModel().canvasinfo;
const index=Array.from({length:m.getDrawableCount()},(_,i)=>i).find(i=>m.getDrawableId(i).getString()==='ArtMeshFace');
for(let i=0;i<m.getParameterCount();i++)m.setParameterValueByIndex(i,m.getParameterDefaultValue(i));
return keys.map(key=>{for(const [id,v] of Object.entries(key))a.set(id,v);m.update();return {key,vertices:Array.from(m.getDrawableVertices(index),(v,j)=>j%2?info.CanvasOriginY-v*info.PixelsPerUnit:info.CanvasOriginX+v*info.PixelsPerUnit)};});
},keys);const modelSha256=createHash('sha256').update(await readFile('models/turn-face/original.moc3')).digest('hex');const served=createHash('sha256').update(await readFile('public/generated/models/turn-face/original.moc3')).digest('hex');if(served!==modelSha256)throw new Error('Run prepare-assets before sampling');await writeFile('.cache/head-turn-samples.json',JSON.stringify({modelSha256,samples}));console.log('Captured',samples.length,'combined skin samples');
}finally{await b.close();}
