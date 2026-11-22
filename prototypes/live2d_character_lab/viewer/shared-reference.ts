/** Same-coordinate source comparison. Measurements are diagnostics, not acceptance. */
export function sharedReference(model:HTMLCanvasElement,display:HTMLCanvasElement,onError:(error:unknown)=>void,view={left:300,top:265,width:440,height:440}){
  const source=document.createElement('canvas'),render=document.createElement('canvas');source.width=render.width=900;source.height=render.height=900;
  const sourceContext=source.getContext('2d',{willReadFrequently:true})!,renderContext=render.getContext('2d',{willReadFrequently:true})!,displayContext=display.getContext('2d')!;
  const state=document.getElementById('reference-state') as HTMLSelectElement,mode=document.getElementById('reference-mode') as HTMLSelectElement;
  const info={ready:false,source:'',generation:0,measurement:null as any};(window as any).__sharedReference=info;
  const regions:Record<string,[number,number,number,number]>={face:[300,265,440,440],browR:[355,350,135,45],browL:[535,350,135,45],eyeR:[355,395,130,95],eyeL:[535,395,135,95],mouth:[445,545,140,85]};
  const background=[235,238,233];let generation=0,lastPaint=0;
  function measure(){
    if(!info.ready)return null;
    renderContext.clearRect(0,0,900,900);renderContext.drawImage(model,0,0);
    const a=renderContext.getImageData(0,0,900,900),b=sourceContext.getImageData(0,0,900,900),difference=displayContext.createImageData(900,900),errors=new Float32Array(900*900);
    for(let p=0;p<errors.length;p++){
      const i=p*4,alphaA=a.data[i+3]/255,alphaB=b.data[i+3]/255;
      for(let channel=0;channel<3;channel++){
        const delta=Math.abs(a.data[i+channel]*alphaA+background[channel]*(1-alphaA)-b.data[i+channel]*alphaB-background[channel]*(1-alphaB));
        errors[p]+=delta/3;difference.data[i+channel]=Math.min(255,Math.round(delta*4));
      }
      difference.data[i+3]=255;
    }
    const mae:Record<string,number>={};
    for(const [name,[x,y,width,height]] of Object.entries(regions)){
      const left=Math.max(0,Math.floor((x-view.left)*900/view.width)),top=Math.max(0,Math.floor((y-view.top)*900/view.height)),right=Math.min(900,Math.ceil((x+width-view.left)*900/view.width)),bottom=Math.min(900,Math.ceil((y+height-view.top)*900/view.height));let sum=0;
      for(let yy=top;yy<bottom;yy++)for(let xx=left;xx<right;xx++)sum+=errors[yy*900+xx];mae[name]=sum/((right-left)*(bottom-top));
    }
    info.measurement={source:info.source,mae,parameters:{...(window as any).__shared?.values},qualityAccepted:false};
    document.getElementById('reference-metrics')!.textContent=`RGB 平均差／255：右眼 ${mae.eyeR.toFixed(2)}、左眼 ${mae.eyeL.toFixed(2)}、嘴 ${mae.mouth.toFixed(2)}。僅供定位差異，非驗收分數。`;
    if(mode.value==='difference')displayContext.putImageData(difference,0,0);
    return info.measurement;
  }
  function paint(){
    display.hidden=mode.value==='model';display.style.opacity=mode.value==='overlay'?'.5':'1';
    if(!info.ready||display.hidden)return;
    if(mode.value==='difference'){measure();return;}
    displayContext.clearRect(0,0,900,900);displayContext.drawImage(source,0,0);
  }
  async function load(){
    const ticket=++generation,name=state.value;info.ready=false;
    try{const image=new Image();image.src=`/generated/references/${name}.png`;await image.decode();if(ticket!==generation)return;
      sourceContext.clearRect(0,0,900,900);sourceContext.drawImage(image,600+view.left,view.top,view.width,view.height,0,0,900,900);
      info.source=name;info.generation=ticket;info.measurement=null;info.ready=true;paint();
    }catch(error){if(ticket===generation)onError(error);}
  }
  state.onchange=load;mode.onchange=paint;document.getElementById('measure-reference')!.onclick=measure;
  (window as any).__measureSharedReference=measure;load();
  return {frame(now:number){if(mode.value==='difference'&&now-lastPaint>250){lastPaint=now;measure();}}};
}
