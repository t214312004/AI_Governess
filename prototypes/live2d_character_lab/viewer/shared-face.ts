import {gestureG2a, type GestureTarget} from './gesture-g2a';
import {listeningPose} from './listening-pose';
import './style.css';
import {Avatar} from './avatar';
import {rmsToMouth,approachMouth} from './controller.mjs';
import sequence from '../design/expression-sequence.json';
import {sharedReference} from './shared-reference';
import referencePoses from '../design/shared-reference-poses.json';
import expressionPoses from '../design/expression-reference-poses.json';
const $=<T extends HTMLElement>(id:string)=>document.getElementById(id) as T;
const query=new URLSearchParams(location.search),gesture=query.get('gesture')==='1',polish=gesture||query.get('polish')==='1',turn=polish||query.get('turn')==='1',head=turn||query.get('head')==='1',expression=head||query.get('expression')==='1',speech=expression||query.get('speech')==='1',gaze=speech||query.get('gaze')==='1';
const canvas=$<HTMLCanvasElement>('avatar'),gl=canvas.getContext('webgl',{alpha:true,premultipliedAlpha:true,preserveDrawingBuffer:true})!;
const reference=$<HTMLCanvasElement>('reference'),audio=$<HTMLAudioElement>('audio');
const view=gesture?{left:-255,top:105,width:1540,height:1540}:head?{left:125,top:100,width:800,height:800}:{left:300,top:265,width:440,height:440};
const spec:Record<string,[string,number,number,number]>={
  ParamEyeROpen:['右眼開合（畫面左側）',0,1,1],ParamEyeLOpen:['左眼開合（畫面右側）',0,1,1],
  ParamBrowRY:['右眉高度',-1,1,0],ParamBrowLY:['左眉高度',-1,1,0],
  ParamBrowRAngle:['右眉角度',-1,1,0],ParamBrowLAngle:['左眉角度',-1,1,0],
  ParamMouthForm:['嘴形',-1,1,0],ParamMouthOpenY:['開口',0,1,0]
};
if(gaze){
  spec.ParamEyeBallX=['視線左右（正值朝畫面右側）',-1,1,0];
  spec.ParamEyeBallY=['視線上下（正值朝上）',-1,1,0];
  document.querySelector('.badge')!.textContent='v6 視線已通過 · 全模型仍待驗收';
  $('capabilities').textContent='共用臉底、獨立虹膜與眼白，小幅視線可搭配眨眼、眉毛及音訊嘴型。v5 閉眼與 v6 視線已通過；各原圖表情、頭頸、手臂與身體尚未完成。';
}
if(speech){
  spec.ParamMouthWidth=['嘴巴寬度',-1,1,0];
  document.querySelector('.badge')!.textContent='v7 嘴型已通過 · 全模型仍待驗收';
  $('capabilities').textContent='閉眼、視線與 v7 嘴型已通過。下唇隨開口移動並保留厚度，嘴寬可獨立控制。各原圖表情尚待完成；頭頸、手臂與身體尚未接入。';
}
if(expression){
  for(const side of ['R','L']){
    spec[`ParamEye${side}Form`]=[`${side==='R'?'右':'左'}眼型微調`,-1,1,0];
    spec[`ParamBrow${side}Form`]=[`${side==='R'?'右':'左'}眉形微調`,-1,1,0];
  }
  document.querySelector('.badge')!.textContent='v8.1 眉尾已通過 · 全模型仍待驗收';
  $('capabilities').textContent='畫面左側眉尾已清除髮絲碎片與底圖殘影，眉尾會隨高度、角度及眉形保持貼合髮際。左右眉毛依原圖保留差異；疑問與單眼閉合會刻意使用不同眉高。可用「雙眉慢速檢查」比較同步動作，或展開原圖疊圖校對。全表情、頭頸和手勢尚未完成。';
}
if(head){
  spec.ParamHeadTilt=['頭部側傾（頸根固定）',-6,6,0];
  document.querySelector('.badge')!.textContent='v9 頭頸側傾已通過 · 全模型仍待驗收';
  $('capabilities').textContent='頭部以頸部附近為支點小幅側傾，連續頸部形變讓肩部維持原位；可以同時眨眼、改表情與播放音訊。此輪範圍為左右各 6 度側傾，頭部轉向、抬頭低頭、完整身體與手勢尚待製作。較大的檢視範圍也會顯示仍待清理的髮梢背景殘邊。';
}
if(turn){
  spec.ParamAngleX=['小幅轉頭（正值朝畫面右側）',-6,6,0];
  spec.ParamAngleY=['小幅俯仰（正值抬頭）',-4,4,0];
  document.querySelector('.badge')!.textContent='小角度轉頭／俯仰 v10 · 質感待驗收';
  $('capabilities').textContent='以小角度轉頭、抬頭與低頭搭配已通過的側傾、眨眼和嘴型。轉頭參數限制 ±6、俯仰限制 ±4，頸根與肩部固定；可暫停慢速檢查。這些是動畫參數範圍，並非量測的人體轉角。髮緣殘色、完整手勢及全表情原圖還原仍待完成。';
}
if(polish){
  document.querySelector('.badge')!.textContent='髮緣與聆聽動作 v11';
  $('capabilities').textContent='可用深淺背景檢查髮緣。聆聽時視線稍早於頭部移動，播放語音可同時檢查嘴型。';
}
let gestureSide=0;
let gestureTarget: GestureTarget = query.get('pose') === 'chest' ? 'chest' : 'point';
const sideSelector=document.createElement('select');
const gestureTargetSelector=document.createElement('select');
if(gesture){
  spec.GestureProgress=['手勢進度',0,1,0];
  spec.GestureFlex=['食指微彎',0,1,0];
  const sideLabel=document.createElement('label');
  sideLabel.textContent='動作側';
  sideLabel.append(sideSelector);
  sideSelector.id='gesture-side';
  sideSelector.add(new Option('右手（畫面左側）','0'));
  sideSelector.add(new Option('左手（畫面右側）','1'));
  sideSelector.disabled=true;
  sideSelector.onchange=()=>{
    gestureSide=Number(sideSelector.value);
    const referenceMode=$<HTMLSelectElement>('reference-mode');
    referenceMode.value='model';
    referenceMode.dispatchEvent(new Event('change'));
  };
  $('controls').append(sideLabel);
  const targetLabel=document.createElement('label');
  targetLabel.textContent='說話手勢';
  gestureTargetSelector.id='gesture-target';
  gestureTargetSelector.add(new Option('舉食指','point'));
  gestureTargetSelector.add(new Option('手靠胸前','chest'));
  gestureTargetSelector.value=gestureTarget;
  gestureTargetSelector.disabled=true;
  gestureTargetSelector.onchange=()=>{
    stopSequence();
    gestureTarget=gestureTargetSelector.value==='chest'?'chest':'point';
    parameters.GestureProgress=0;
    $<HTMLInputElement>('GestureFlex').disabled=gestureTarget==='chest';
    const mode=$<HTMLSelectElement>('reference-mode');
    mode.value='model';
    mode.dispatchEvent(new Event('change'));
    sync();
  };
  targetLabel.append(gestureTargetSelector);
  $('controls').append(targetLabel);
  document.querySelector('.badge')!.textContent='托腮 · 舉食指 · 手靠胸前';
  $('capabilities').textContent='選擇說話手勢後可拖曳進度檢查肘腕、手掌和拇指。兩種手勢皆可搭配音訊嘴型。';
  $('apply-reference').textContent='套用對應端點';
  const referenceState=$<HTMLSelectElement>('reference-state');
  referenceState.add(new Option('托腮／手勢端點','sending_1'));
  referenceState.add(new Option('手靠胸前／說話','speaking_3'));
  referenceState.value='sending_1';
}
const defaults=Object.fromEntries(Object.entries(spec).map(([id,s])=>[id,s[3]]));let parameters={...defaults};
let cycling=false,slowBlink=false,slowMouth=false,slowBrow=false,slowHead=false,slowYaw=false,slowPitch=false,motionTime=0;
const sequenceLabel=gaze?'播放連續表情與視線':'播放連續表情與眨眼';
let listening=false, listeningTime=0, resumeListening=false;
const listeningButton=document.createElement('button');
if(polish){
  listeningButton.id='listening';
  listeningButton.textContent='播放日常聆聽';
  $('sequence').before(listeningButton);
  listeningButton.onclick=()=>{
    if(listening){
      listening=false;
      resumeListening=true;
      listeningButton.textContent='繼續日常聆聽';
      return;
    }
    if(!resumeListening){
      listeningTime=0;
      const opening=audioMode?parameters.ParamMouthOpenY:0;
      parameters={...defaults,ParamMouthOpenY:opening};
    }
    stopSequence();
    listening=true;
    listeningButton.textContent='暫停日常聆聽';
  };
}
const gestureButton=document.createElement('button');
let playingGesture=false;
if(gesture){
  gestureButton.id='gesture-motion';
  gestureButton.textContent='播放手勢過渡';
  $('sequence').before(gestureButton);
  gestureButton.onclick=()=>{
    const play=!playingGesture;
    stopSequence();
    if(!play)return;
    if(parameters.GestureProgress>=1)parameters.GestureProgress=0;
    playingGesture=true;
    gestureButton.textContent='暫停手勢過渡';
  };
}
function stopSequence(){playingGesture=false;gestureButton.textContent='播放手勢過渡';listening=false;resumeListening=false;listeningButton.textContent='播放日常聆聽';cycling=false;slowBlink=false;slowMouth=false;slowBrow=false;slowHead=false;slowYaw=false;slowPitch=false;$('sequence').textContent=sequenceLabel;$('slow-blink').textContent='慢速眨眼檢查';const button=document.getElementById('slow-mouth');if(button)button.textContent='慢速嘴型檢查';const browButton=document.getElementById('slow-brow');if(browButton)browButton.textContent='雙眉慢速檢查';const headButton=document.getElementById('slow-head');if(headButton)headButton.textContent='頭頸慢速檢查';for(const [id,label] of [['slow-yaw','慢速轉頭檢查'],['slow-pitch','慢速俯仰檢查']]){const button=document.getElementById(id);if(button)button.textContent=label;}}
$('sequence').onclick=()=>{const next=!cycling;stopSequence();cycling=next;motionTime=0;$('sequence').textContent=cycling?'暫停連續展示':sequenceLabel;};
$('slow-blink').onclick=()=>{const next=!slowBlink;stopSequence();slowBlink=next;motionTime=0;$('slow-blink').textContent=slowBlink?'暫停慢速眨眼':'慢速眨眼檢查';};
const presets:Record<string,{label:string,values:Record<string,number>}>= {
  neutral:{label:'待機',values:{}},curious:{label:'疑問',values:{ParamBrowRY:.55,ParamBrowRAngle:.5,ParamEyeLOpen:.8,ParamMouthForm:-.25}},
  thoughtful:{label:'專注',values:{ParamBrowRY:-.2,ParamBrowLY:-.2,ParamBrowRAngle:-.4,ParamBrowLAngle:.4,ParamEyeROpen:.75,ParamEyeLOpen:.75}},
  warm:{label:'溫和',values:{ParamBrowRY:.25,ParamBrowLY:.25,ParamEyeROpen:.8,ParamEyeLOpen:.8,ParamMouthForm:.6}},
  wink:{label:'單眼閉合',values:{ParamEyeLOpen:0,ParamBrowLY:.3,ParamMouthForm:.35}},
  surprised:{label:'驚訝',values:{ParamBrowRY:.7,ParamBrowLY:.7,ParamMouthOpenY:.7,ParamMouthForm:-.5}}
};
if(gaze){
  presets.lookLeft={label:'看向畫面左方',values:{ParamEyeBallX:-.8}};
  presets.lookRight={label:'看向畫面右方',values:{ParamEyeBallX:.8}};
  $('sequence').textContent='播放連續表情與視線';
}
if(speech)presets.speaking={label:'說話表情校對',values:{...referencePoses.frames.speaking_1,ParamEyeLOpen:1}};
if(expression){
  presets.speaking={label:'說話／眉眼校準後',values:{...expressionPoses.frames.speaking_1}};
  presets.speakingBefore={label:'說話／v7 參數對照',values:{...referencePoses.frames.speaking_1}};
}
if(head){
  presets.tiltLeft={label:'向畫面左側傾',values:{ParamHeadTilt:-6}};
  presets.tiltRight={label:'向畫面右側傾',values:{ParamHeadTilt:6}};
  presets.tiltSpeaking={label:'側傾說話',values:{...expressionPoses.frames.speaking_1,ParamHeadTilt:4}};
}
if(turn){
  presets.turnLeft={label:'小幅向左轉頭',values:{ParamAngleX:-6}};
  presets.turnRight={label:'小幅向右轉頭',values:{ParamAngleX:6}};
  presets.pitchUp={label:'微微抬頭',values:{ParamAngleY:4}};
  presets.pitchDown={label:'微微低頭',values:{ParamAngleY:-4}};
  presets.turnSpeaking={label:'轉頭說話',values:{...expressionPoses.frames.speaking_1,ParamAngleX:4,ParamAngleY:-2,ParamHeadTilt:3}};
}
const gazeSequence=[[0,0],[-.8,.2],[.7,.3],[0,-.7],[.5,.5],[0,0]];
const formSequence:Record<string,number>[]=[{},
  {ParamEyeRForm:.7,ParamEyeLForm:-.4,ParamBrowRForm:-.6,ParamBrowLForm:.3},
  {ParamEyeRForm:-.5,ParamEyeLForm:.4,ParamBrowRForm:.4,ParamBrowLForm:-.4},
  {ParamEyeRForm:.53,ParamEyeLForm:.44,ParamBrowRForm:.34,ParamBrowLForm:.49},
  {ParamEyeRForm:-.4,ParamEyeLForm:.6,ParamBrowRForm:.7,ParamBrowLForm:-.5},
  {ParamEyeRForm:.5,ParamEyeLForm:.5,ParamBrowRForm:-.3,ParamBrowLForm:.4}];
let avatar:Avatar|undefined,audioContext:AudioContext,analyser:AnalyserNode,samples:Float32Array,audioMode=false,mouth=0;
if(speech){
  const button=document.createElement('button');button.id='slow-mouth';button.textContent='慢速嘴型檢查';$('slow-blink').after(button);
  button.onclick=()=>{const next=!slowMouth;stopSequence();audio.pause();audioMode=false;slowMouth=next;motionTime=0;button.textContent=next?'暫停慢速嘴型':'慢速嘴型檢查';};
}
if(expression){
  const button=document.createElement('button');button.id='slow-brow';button.textContent='雙眉慢速檢查';$('slow-blink').after(button);
  button.onclick=()=>{const next=!slowBrow;stopSequence();slowBrow=next;motionTime=0;button.textContent=next?'暫停雙眉檢查':'雙眉慢速檢查';};
}
if(head){
  const button=document.createElement('button');button.id='slow-head';button.textContent='頭頸慢速檢查';$('slow-blink').before(button);
  button.onclick=()=>{const next=!slowHead;stopSequence();slowHead=next;motionTime=0;button.textContent=next?'暫停頭頸檢查':'頭頸慢速檢查';};
}
if(turn){
  for(const [id,label] of [['slow-yaw','慢速轉頭檢查'],['slow-pitch','慢速俯仰檢查']]){
    const button=document.createElement('button');button.id=id;button.textContent=label;$('slow-head').before(button);
    button.onclick=()=>{const next=id==='slow-yaw'?!slowYaw:!slowPitch;stopSequence();if(id==='slow-yaw')slowYaw=next;else slowPitch=next;motionTime=0;button.textContent=next?'暫停'+label:label;};
  }
}
const diagnostic={ready:false,error:'',loads:0,frames:0,ranges:{} as Record<string,[number,number]>,parameters:[] as string[],drawables:0,values:{} as Record<string,number>,audioDriven:false,cycling:false};
(window as any).__shared=diagnostic;
function sync(){for(const [id,value] of Object.entries(parameters)){$<HTMLInputElement>(id).value=String(value);$(id+'-value').textContent=value.toFixed(2);}}
for(const [id,[label,min,max,value]] of Object.entries(spec)){
  const node=document.createElement('label');node.textContent=label;const output=document.createElement('output');output.id=id+'-value';node.append(output);
  const input=document.createElement('input');input.type='range';input.id=id;input.min=String(min);input.max=String(max);input.step='.01';input.value=String(value);node.append(input);$('controls').append(node);
  input.oninput=()=>{stopSequence();const value=Number(input.value);if(id==='ParamMouthOpenY'){audioMode=false;audio.pause();mouth=value;}parameters[id]=value;sync();};
}
for(const [id,preset] of Object.entries(presets)){
  const button=document.createElement('button');button.textContent=preset.label;button.dataset.preset=id;
  button.onclick=()=>{stopSequence();const keepMouth=parameters.ParamMouthOpenY;parameters={...defaults,...preset.values};if(audioMode)parameters.ParamMouthOpenY=keepMouth;sync();};$('presets').append(button);
}
sync();
if(gesture)$<HTMLInputElement>('GestureFlex').disabled=gestureTarget==='chest';
$('background').onchange=()=>{$('stage').dataset.background=$<HTMLSelectElement>('background').value;};
const comparison=sharedReference(canvas,reference,e=>diagnostic.error=String(e),view);
$('apply-reference').onclick=()=>{
  $('stop').click();const source=$<HTMLSelectElement>('reference-state').value;
  const faceSource=(source==='speaking_3'?'speaking_1':source) as keyof typeof referencePoses.frames;
  parameters={...defaults,...(expression?expressionPoses:referencePoses).frames[faceSource]};
  if(gesture){
    if(source==='speaking_3'||source==='speaking_1'){
      gestureTarget=source==='speaking_3'?'chest':'point';
      gestureTargetSelector.value=gestureTarget;
      $<HTMLInputElement>('GestureFlex').disabled=gestureTarget==='chest';
    }
    parameters.GestureProgress=Number(source==='speaking_1'||source==='speaking_3');
    gestureSide=0;
    sideSelector.value='0';
  }
  sync();
};
audio.addEventListener('play',async()=>{audioMode=true;try{
  if(!audioContext){audioContext=new AudioContext();analyser=audioContext.createAnalyser();analyser.fftSize=1024;audioContext.createMediaElementSource(audio).connect(analyser);analyser.connect(audioContext.destination);samples=new Float32Array(analyser.fftSize);}
  await audioContext.resume();
}catch(e){audio.pause();diagnostic.error=String(e);}});
function close(){mouth=0;parameters.ParamMouthOpenY=0;sync();}
for(const event of ['pause','ended','emptied','error'])audio.addEventListener(event,()=>{if(audioMode)close();});
audio.addEventListener('volumechange',()=>{if(audio.muted||audio.volume===0)close();});
$('stop').onclick=()=>{stopSequence();audio.pause();audio.currentTime=0;audioMode=false;close();};
Avatar.open(`/generated/models/${gesture?'gesture-face':polish?'polish-face':turn?'turn-face':head?'head-face':expression?'expression-face':speech?'speech-face':gaze?'gaze-face':'shared-face'}/${expression?'original':'model'}.model3.json`,gl,canvas).then(model=>{
  avatar=model;model.sourceViewport(view);diagnostic.ready=true;diagnostic.loads=Avatar.loads;diagnostic.parameters=[...model.ids.keys()];const coreModel=model.getModel();for(let i=0;i<coreModel.getParameterCount();i++)diagnostic.ranges[coreModel.getParameterId(i).getString()]=[coreModel.getParameterMinimumValue(i),coreModel.getParameterMaximumValue(i)];diagnostic.drawables=model.getModel().getDrawableCount();
  sideSelector.disabled=!diagnostic.parameters.includes('ParamGestureSide');
  gestureTargetSelector.disabled=(diagnostic.ranges.ParamGestureReach?.[1]??0)<5;
  $('status').textContent=`官方 Core · 共用臉底 · ${diagnostic.drawables} 個 ArtMesh`;
}).catch(e=>{diagnostic.error=String(e);$('status').textContent=String(e);});
(window as any).__sharedSnapshot=()=>{
  if(!avatar)return null;const model=avatar.getModel();const meshes:Record<string,any>={};
  const renderOrders:Record<string,number>={};
  const orders=model.getRenderOrders();
  const info=model.getModel().canvasinfo;
  for(let i=0;i<model.getDrawableCount();i++){
    const vertices=Array.from(model.getDrawableVertices(i));
    const id=model.getDrawableId(i).getString();
    meshes[id]={vertices,indices:Array.from(model.getDrawableVertexIndices(i)),sourceVertices:vertices.map((value,index)=>index%2?info.CanvasOriginY-value*info.PixelsPerUnit:info.CanvasOriginX+value*info.PixelsPerUnit),opacity:model.getDrawableOpacity(i),masks:Array.from(model.getDrawableMasks()[i]).map(index=>model.getDrawableId(index).getString())};
    renderOrders[id]=orders[i];
  }
  return {values:{...diagnostic.values},meshes,renderOrders,loads:diagnostic.loads};
};
let last=performance.now();
function frame(now:number){
  const dt=Math.min((now-last)/1000,.1);last=now;
  if(playingGesture){
    parameters.GestureProgress=Math.min(1,parameters.GestureProgress+dt/4.8);
    if(parameters.GestureProgress===1){
      playingGesture=false;
      gestureButton.textContent='播放手勢過渡';
    }
    sync();
  }
  if(listening){
    listeningTime+=dt;
    Object.assign(parameters,listeningPose(listeningTime));
    sync();
  }
  if(cycling){
    motionTime+=dt;const position=motionTime/sequence.secondsPerTransition,index=Math.floor(position)%sequence.keyframes.length,t=position%1,smooth=t*t*(3-2*t);
    const a:Record<string,number>={...defaults,...sequence.keyframes[index]},b:Record<string,number>={...defaults,...sequence.keyframes[(index+1)%sequence.keyframes.length]};
    if(expression){Object.assign(a,formSequence[index]);Object.assign(b,formSequence[(index+1)%formSequence.length]);}
    if(head){const tilts=[0,-4,3,-2.5,4.5,0];a.ParamHeadTilt=tilts[index%tilts.length];b.ParamHeadTilt=tilts[(index+1)%tilts.length];}
    if(turn){const turns=[0,-4,4,-3,3,0],pitches=[0,-2,2,1,-2,0];a.ParamAngleX=turns[index%turns.length];b.ParamAngleX=turns[(index+1)%turns.length];a.ParamAngleY=pitches[index%pitches.length];b.ParamAngleY=pitches[(index+1)%pitches.length];}
    if(gaze){
      [a.ParamEyeBallX,a.ParamEyeBallY]=gazeSequence[index%gazeSequence.length];
      [b.ParamEyeBallX,b.ParamEyeBallY]=gazeSequence[(index+1)%gazeSequence.length];
    }
    for(const id of Object.keys(spec))parameters[id]=a[id]+(b[id]-a[id])*smooth;
    const blinkPhase=motionTime%4.3,blink=blinkPhase<.3?Math.abs(blinkPhase-.15)/.15:1;
    parameters.ParamEyeROpen*=blink;parameters.ParamEyeLOpen*=blink;sync();
  }
  diagnostic.cycling=cycling;
  if(slowBlink){motionTime+=dt;parameters.ParamEyeROpen=parameters.ParamEyeLOpen=(1+Math.cos(motionTime*Math.PI/4))/2;sync();}
  if(slowMouth){motionTime+=dt;parameters.ParamMouthOpenY=(1-Math.cos(motionTime*Math.PI/4))/2;sync();}
  if(slowYaw){motionTime+=dt;parameters.ParamAngleX=6*Math.sin(motionTime*Math.PI/8);sync();}
  if(slowPitch){motionTime+=dt;parameters.ParamAngleY=4*Math.sin(motionTime*Math.PI/6);sync();}
  if(slowHead){motionTime+=dt;parameters.ParamHeadTilt=6*Math.sin(motionTime*Math.PI/8);sync();}
  if(slowBrow){
    motionTime+=dt;const phase=motionTime*Math.PI/6;
    parameters.ParamBrowRY=parameters.ParamBrowLY=.85*Math.sin(phase);
    parameters.ParamBrowRAngle=.65*Math.sin(phase*.5);parameters.ParamBrowLAngle=-parameters.ParamBrowRAngle;
    parameters.ParamBrowRForm=parameters.ParamBrowLForm=.6*Math.sin(phase*.75);sync();
  }
  if(audioMode){
    if(analyser&&!audio.paused&&!audio.ended&&!audio.muted&&audio.volume>0&&audio.readyState>=2){analyser.getFloatTimeDomainData(samples);mouth=approachMouth(mouth,rmsToMouth(samples,audio.volume),dt);}else mouth=0;
    parameters.ParamMouthOpenY=mouth;$<HTMLInputElement>('ParamMouthOpenY').value=String(mouth);$('ParamMouthOpenY-value').textContent=mouth.toFixed(2);
  }
  gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);
  if(avatar){avatar.frame(dt,0,{angle:0,tilt:0,brow:0,smile:0,parameters:{ParamBreath:0,...parameters,...(gesture?gestureG2a(parameters.GestureProgress,parameters.GestureFlex,gestureSide,gestureTarget):{})}},parameters.ParamMouthOpenY,canvas);diagnostic.frames++;diagnostic.values={...parameters};diagnostic.audioDriven=audioMode;$('metrics').textContent=JSON.stringify({loads:diagnostic.loads,values:diagnostic.values},null,2);}
  comparison.frame(now);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
