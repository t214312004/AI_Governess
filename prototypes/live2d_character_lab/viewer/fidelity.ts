import './style.css';
import {Avatar} from './avatar';
import catalog from '../design/feature-catalog.json';
const $=<T extends HTMLElement>(id:string)=>document.getElementById(id) as T;
const canvas=$<HTMLCanvasElement>('avatar'), reference=$<HTMLCanvasElement>('reference'), difference=$<HTMLCanvasElement>('difference');
const gl=canvas.getContext('webgl',{alpha:true,premultipliedAlpha:true,preserveDrawingBuffer:true})!;
const ctx=reference.getContext('2d',{willReadFrequently:true})!,diff=difference.getContext('2d')!;
const regions={face:{left:900,top:265,width:440,height:440},eyes:{left:925,top:300,width:380,height:380},mouth:{left:1015,top:490,width:210,height:210},whole:{left:0,top:-106,width:2236,height:2236}};
const expressionSelect=$<HTMLSelectElement>('expression');expressionSelect.replaceChildren();
for(const frame of Object.keys(catalog.frames)){
  const option=document.createElement('option');option.value=frame;option.textContent=frame;expressionSelect.append(option);
}
expressionSelect.value='idle_listen_1';
let avatar:Avatar|undefined, source:HTMLImageElement, sourceRequest=0;
const diagnostic={ready:false,error:'',loads:0,source:'',mae:0,alphaMae:0,roiMae:{} as Record<string,number>,info:{} as any,frames:0,drawables:0,parameters:[] as string[]};
(window as any).__fidelity=diagnostic;
function region(){return regions[$<HTMLSelectElement>('region').value as keyof typeof regions];}
function redrawReference(){
  if(!source)return;
  const r=region();ctx.clearRect(0,0,900,900);ctx.drawImage(source,r.left,r.top,r.width,r.height,0,0,900,900);
  avatar?.sourceViewport(r);
}
async function expression(){
  const token=++sourceRequest;
  const frame=expressionSelect.value;
  const img=new Image();img.src=`/generated/references/${frame}.png`;await img.decode();
  if(token!==sourceRequest)return;source=img;diagnostic.source=frame;redrawReference();
}
function mode(){
  const value=$<HTMLSelectElement>('mode').value;
  reference.hidden=value==='model'||value==='difference';difference.hidden=value!=='difference';
  reference.style.opacity=value==='source'?'1':$<HTMLInputElement>('opacity').value;
}
$('expression').onchange=expression;$('region').onchange=redrawReference;$('mode').onchange=mode;$('opacity').oninput=mode;
mode();expression();
Avatar.open('/generated/models/face-fidelity/original.model3.json',gl,canvas).then(model=>{
  avatar=model;model.sourceViewport(region());diagnostic.ready=true;diagnostic.loads=Avatar.loads;diagnostic.info=model.getModel().getModel().canvasinfo;
  diagnostic.drawables=model.getModel().getDrawableCount();diagnostic.parameters=Array.from(model.ids.keys());
  $('status').textContent=`官方 Core 已載入 · ${model.getModel().getDrawableCount()} 個部件`;
}).catch(e=>{diagnostic.error=String(e);$('status').textContent=String(e);});
function measure(){
  if(!avatar||!source)return;
  const model=new Uint8Array(900*900*4);gl.readPixels(0,0,900,900,gl.RGBA,gl.UNSIGNED_BYTE,model);
  const original=ctx.getImageData(0,0,900,900),heat=diff.createImageData(900,900);
  let total=0,alpha=0;
  for(let y=0;y<900;y++)for(let x=0;x<900;x++){
    const i=(y*900+x)*4,j=((899-y)*900+x)*4;
    const a=model[j+3]/255,b=original.data[i+3]/255;
    for(let c=0;c<3;c++){
      // WebGL readback is premultiplied. Compare both composited over the same matte.
      const delta=Math.abs(model[j+c]+238*(1-a)-(original.data[i+c]*b+238*(1-b)));
      total+=delta;heat.data[i+c]=Math.min(255,delta*4);
    }
    alpha+=Math.abs(model[j+3]-original.data[i+3]);heat.data[i+3]=255;
  }
  diagnostic.mae=total/(900*900*3);diagnostic.alphaMae=alpha/(900*900);
  const view=region();diagnostic.roiMae={};
  for(const [name,r] of Object.entries(catalog.regions)){
    const x0=Math.max(0,Math.ceil((r.left-view.left)/view.width*900)),x1=Math.min(900,Math.floor((r.left+r.width-view.left)/view.width*900));
    const y0=Math.max(0,Math.ceil((r.top-view.top)/view.height*900)),y1=Math.min(900,Math.floor((r.top+r.height-view.top)/view.height*900));
    let sum=0,count=0;
    for(let y=y0;y<y1;y++)for(let x=x0;x<x1;x++){
      const i=(y*900+x)*4,j=((899-y)*900+x)*4,a=model[j+3]/255,b=original.data[i+3]/255;
      for(let c=0;c<3;c++)sum+=Math.abs(model[j+c]+238*(1-a)-(original.data[i+c]*b+238*(1-b)));
      count+=3;
    }
    if(count)diagnostic.roiMae[name]=sum/count;
  }
  diff.putImageData(heat,0,0);
  $('metrics').textContent=`全區 RGB 差：${diagnostic.mae.toFixed(2)} / 255\n${Object.entries(diagnostic.roiMae).map(([k,v])=>`${({eye_r:'右眼眉',eye_l:'左眼眉',nose:'鼻子',mouth:'嘴部'} as any)[k]}：${v.toFixed(2)}`).join('\n')}\n模型載入次數：${diagnostic.loads}`;
}
(window as any).__measureFidelity=measure;
let lastMeasure=0;
function frame(now:number){
  gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);
  if(avatar){
    avatar.frame(0,0,{angle:0,tilt:0,brow:0,smile:0,parameters:{ParamBreath:0,ParamEyeLOpen:1,ParamEyeROpen:1,ParamEyesClosed:0,ParamReferenceFrame:catalog.frames[expressionSelect.value as keyof typeof catalog.frames]}},0,canvas);
    diagnostic.frames++;
    if(now-lastMeasure>500){measure();lastMeasure=now;}
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
