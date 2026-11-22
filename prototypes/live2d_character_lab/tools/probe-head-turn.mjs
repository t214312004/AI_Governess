import {chromium} from 'playwright';import {writeFile} from 'node:fs/promises';
const b=await chromium.launch({channel:'msedge',headless:true});
try{
const p=await b.newPage();await p.goto('http://127.0.0.1:5187/.cache/probe-v10.html');
await p.evaluate(async()=>{const {Avatar}=await import('/viewer/avatar.ts');const c=document.createElement('canvas');c.width=c.height=900;document.body.append(c);const gl=c.getContext('webgl',{alpha:true,premultipliedAlpha:true,preserveDrawingBuffer:true});const a=await Avatar.open('/generated/models/head-face/original.model3.json',gl,c);a.sourceViewport({left:125,top:100,width:800,height:800});window.probe={a,c,gl};});
const results={};for(const [name,x,y] of [['neutral',0,0],['left',-6,0],['right',6,0],['down',0,-4],['up',0,4],['corner',6,4]]){
const values={ParamAngleX:x,ParamAngleY:y,ParamAngleZ:0,ParamHeadTilt:0,ParamBodyAngleX:0,ParamBodyAngleZ:0,ParamBreath:0,ParamEyeROpen:1,ParamEyeLOpen:1,ParamMouthOpenY:0,ParamMouthForm:0};
await p.evaluate(values=>{const {a,c,gl}=window.probe;gl.clear(gl.COLOR_BUFFER_BIT);a.frame(0,0,{angle:0,tilt:0,brow:0,smile:0,parameters:values},0,c);},values);await p.waitForTimeout(100);
const data=await p.evaluate(values=>{const {a,c,gl}=window.probe;gl.clear(gl.COLOR_BUFFER_BIT);a.frame(0,0,{angle:0,tilt:0,brow:0,smile:0,parameters:values},0,c);const m=a.getModel(),info=m.getModel().canvasinfo;return {png:c.toDataURL(),meshes:Object.fromEntries(Array.from({length:m.getDrawableCount()},(_,i)=>[m.getDrawableId(i).getString(),Array.from(m.getDrawableVertices(i),(v,j)=>j%2?info.CanvasOriginY-v*info.PixelsPerUnit:info.CanvasOriginX+v*info.PixelsPerUnit)]))};},values);
await writeFile('.cache/turn-probe-'+name+'.png',Buffer.from(data.png.split(',')[1],'base64'));results[name]={x,y,meshes:data.meshes};
}await writeFile('.cache/head-turn-probe.json',JSON.stringify(results));console.log('Saved six generated-rig turn/pitch probes');
}finally{await b.close();}
