import './style.css';
import {Avatar} from './avatar';
import landmarks from '../design/hand-source-landmarks.json';
import meshMap from '../design/hand-runtime-map.json';
const $=<T extends HTMLElement>(id:string)=>document.getElementById(id) as T;
const canvas=$<HTMLCanvasElement>('avatar'),reference=$<HTMLCanvasElement>('reference'),difference=$<HTMLCanvasElement>('difference'),markers=$<HTMLCanvasElement>('landmarks');
const gl=canvas.getContext('webgl',{alpha:true,premultipliedAlpha:true,preserveDrawingBuffer:true})!;
const ctx=reference.getContext('2d')!,diff=difference.getContext('2d')!,mark=markers.getContext('2d')!;
const target=document.createElement('canvas');target.width=target.height=900;const targetCtx=target.getContext('2d',{willReadFrequently:true})!;
const views={index:{left:640,top:600,width:520,height:520},chin:{left:800,top:600,width:480,height:480}};
const data=landmarks as Record<string,any>;
const meshIds=meshMap as Record<string,string>;
let avatar:Avatar|undefined,selection='index',readySource='',generation=0;
const diagnostic={ready:false,error:'',loads:0,source:'',frames:0,visibleMeshes:[] as string[],rgbMae:0,alphaMae:0,interiorPixels:0};
(window as any).__hands=diagnostic;
function drawMarkers(){
  mark.clearRect(0,0,900,900);if(!$<HTMLInputElement>('markers').checked)return;
  const view=views[selection as keyof typeof views];
  const labels:Record<string,string>={index_tip:'食指尖',index_knuckle:'食指關節',thumb_tip:'拇指尖',thumb_web:'拇指虎口',thumb_root:'拇指根',wrist:'手腕'};
  mark.font='bold 17px Segoe UI,Microsoft JhengHei';
  for(const [name,point] of Object.entries(data[selection].landmarks)){
    const [px,py]=point as number[],x=(px-view.left)/view.width*900,y=(py-view.top)/view.height*900;
    mark.strokeStyle=name.startsWith('thumb')?'#c62f73':'#087b8c';mark.lineWidth=2;
    mark.beginPath();mark.arc(x,y,7,0,Math.PI*2);mark.moveTo(x-12,y);mark.lineTo(x+12,y);mark.moveTo(x,y-12);mark.lineTo(x,y+12);mark.stroke();
    mark.fillStyle='#ffffffed';mark.fillRect(x+13,y-20,mark.measureText(labels[name]).width+8,24);mark.fillStyle=mark.strokeStyle;mark.fillText(labels[name],x+17,y-2);
  }
}
async function select(){
  const token=++generation;selection=$<HTMLSelectElement>('gesture').value;readySource='';
  const source=new Image(),cut=new Image();source.src=`/generated/references/${data[selection].frame}.png`;cut.src=`/generated/hands/${selection}.png`;
  await Promise.all([source.decode(),cut.decode()]);if(token!==generation)return;
  const view=views[selection as keyof typeof views];
  ctx.clearRect(0,0,900,900);targetCtx.clearRect(0,0,900,900);
  ctx.drawImage(source,view.left,view.top,view.width,view.height,0,0,900,900);targetCtx.drawImage(cut,view.left,view.top,view.width,view.height,0,0,900,900);
  avatar?.sourceViewport(view);readySource=selection;diagnostic.source=data[selection].frame;drawMarkers();
}
function mode(){const mode=$<HTMLSelectElement>('mode').value;reference.hidden=mode==='model'||mode==='difference';difference.hidden=mode!=='difference';reference.style.opacity=mode==='source'?'1':$<HTMLInputElement>('opacity').value;}
$('gesture').onchange=select;$('mode').onchange=mode;$('opacity').oninput=mode;$('markers').onchange=drawMarkers;mode();select().catch(e=>diagnostic.error=String(e));
Avatar.open('/generated/models/face-fidelity/original.model3.json',gl,canvas).then(model=>{
  avatar=model;model.sourceViewport(views[selection as keyof typeof views]);diagnostic.ready=true;diagnostic.loads=Avatar.loads;
  $('status').textContent='官方 Core · 手部與五官使用相同模型檔';
}).catch(e=>{diagnostic.error=String(e);$('status').textContent=String(e);});
function measure(){
  if(!avatar||readySource!==selection)return;
  const pixels=new Uint8Array(900*900*4);gl.readPixels(0,0,900,900,gl.RGBA,gl.UNSIGNED_BYTE,pixels);
  const expected=targetCtx.getImageData(0,0,900,900),heat=diff.createImageData(900,900);let rgb=0,alpha=0,n=0;
  for(let y=0;y<900;y++)for(let x=0;x<900;x++){
    const i=(y*900+x)*4,j=((899-y)*900+x)*4,a=pixels[j+3]/255,b=expected.data[i+3]/255;
    for(let c=0;c<3;c++){
      const delta=Math.abs(pixels[j+c]+238*(1-a)-(expected.data[i+c]*b+238*(1-b)));heat.data[i+c]=Math.min(255,delta*4);
      if(a>.99&&b>.99)rgb+=delta;
    }
    if(a>.99&&b>.99)n++;alpha+=Math.abs(pixels[j+3]-expected.data[i+3]);heat.data[i+3]=255;
  }
  diagnostic.rgbMae=n?rgb/(n*3):Infinity;diagnostic.alphaMae=alpha/(900*900);diagnostic.interiorPixels=n;diff.putImageData(heat,0,0);
  $('metrics').textContent=`手部內部 RGB 差：${diagnostic.rgbMae.toFixed(2)} / 255\n匯出透明度差：${diagnostic.alphaMae.toFixed(2)} / 255\n比對像素：${n}\n模型載入：${diagnostic.loads} 次`;
}
(window as any).__measureHands=measure;
let lastMeasure=0;
function frame(now:number){
  gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);
  if(avatar&&readySource===selection){
    avatar.frame(0,0,{angle:0,tilt:0,brow:0,smile:0,parameters:{ParamBreath:0,ParamReferenceFrame:0,ParamHandIndex:selection==='index'?1:0,ParamHandChin:selection==='chin'?1:0},inspectDrawable:meshIds[selection]??'UNAUTHORED_HAND'},0,canvas);
    diagnostic.frames++;const d=avatar.getModel().getModel().drawables;diagnostic.visibleMeshes=Array.from(d.ids).filter(id=>String(id)===meshIds[selection]) as string[];
    if(now-lastMeasure>500){measure();lastMeasure=now;}
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
