import './style.css';
import { Avatar } from './avatar';
import poses from '../design/arm-poses.json';
const canvas=document.querySelector('canvas')!;
const gl=canvas.getContext('webgl',{alpha:true,premultipliedAlpha:true,preserveDrawingBuffer:true})!;
const slider=document.querySelector<HTMLInputElement>('#transition')!;
let avatar:Avatar|undefined, last=performance.now();
const params={...poses.neutral}; let target={...poses.neutral};
const diagnostic={ready:false,loads:0,error:'',parameters:params,meshBounds:{} as Record<string,number[]>};
(window as any).__armLab=diagnostic;
const mix=(a:any,b:any,t:number)=>Object.fromEntries(Object.keys(a).map(k=>[k,a[k]+(b[k]-a[k])*t])) as typeof params;
slider.oninput=()=>{
  const t=Number(slider.value);
  target=t<=.5?mix(poses.chin,poses.neutral,t*2):mix(poses.neutral,poses.raised,t*2-1);
};
document.querySelectorAll<HTMLButtonElement>('[data-pose]').forEach(button=>button.onclick=()=>{
  const pose=button.dataset.pose as keyof typeof poses; target={...poses[pose]}; slider.value=String(pose==='chin'?0:pose==='raised'?1:.5);
});
document.querySelector('#background')!.addEventListener('change',e=>{document.querySelector<HTMLElement>('#stage')!.dataset.background=(e.target as HTMLSelectElement).value;});
Avatar.open('/generated/models/arm-spike-clean/arm-segments.model3.json',gl,canvas).then(model=>{
  avatar=model; diagnostic.ready=true; diagnostic.loads=Avatar.loads;
  document.querySelector('#status')!.textContent=`Core 載入成功 · ${model.getModel().getDrawableCount()} 個部件 · 同一模型`;
}).catch(error=>{diagnostic.error=String(error);document.querySelector('#status')!.textContent=String(error);});
function frame(now:number){
  const dt=Math.min((now-last)/1000,.1);last=now;
  for(const k of Object.keys(params) as (keyof typeof params)[])params[k]+=(target[k]-params[k])*(1-Math.exp(-dt/.15));
  gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);
  if(avatar){
    avatar.frame(dt,0,{angle:0,tilt:0,brow:0,smile:0,parameters:params},0,canvas);
    const model=avatar.getModel();
    for(let i=0;i<model.getDrawableCount();i++){
      const id=model.getDrawableId(i).getString();
      if(!['ArtMeshHandwearR','ArtMeshLayerR2','ArtMeshLayerR'].includes(id))continue;
      const v=model.getDrawableVertices(i);let l=Infinity,r=-Infinity,b=Infinity,t=-Infinity;
      for(let j=0;j<v.length;j+=2){l=Math.min(l,v[j]);r=Math.max(r,v[j]);b=Math.min(b,v[j+1]);t=Math.max(t,v[j+1]);}
      diagnostic.meshBounds[id]=[l,b,r,t];
    }
  }
  document.querySelector('#diagnostics')!.textContent=JSON.stringify(diagnostic,null,2);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
