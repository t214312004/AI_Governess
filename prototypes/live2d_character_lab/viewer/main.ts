import './style.css';
import { Avatar } from './avatar';
import { STATES, StateController, rmsToMouth, approachMouth } from './controller.mjs';
const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const canvas = $<HTMLCanvasElement>('avatar');
const gl = canvas.getContext('webgl', { alpha: true, premultipliedAlpha: true, preserveDrawingBuffer: true });
if (!gl) throw new Error('WebGL 無法使用');
const controller = new StateController();
const audio = $<HTMLAudioElement>('audio');
const mouthSlider = $<HTMLInputElement>('mouth');
let avatar: Avatar | undefined, request = 0, mouth = 0, audioMode = false;
let audioContext: AudioContext, analyser: AnalyserNode, samples: Float32Array;
let audioUrl: string | undefined;
let last = performance.now(), started = last, frames = 0, fps = 0, fpsStart = last;
const diagnostics = { ready: false, loads: 0, state: controller.state, mouth: 0, modelMouth: null as number | null, mouthVertices: [] as number[], parameters: [] as string[], drawables: 0, frames: 0, fps: 0, error: '' };
(window as any).__lab = diagnostics;
(window as any).__labProbeMouth = () => avatar?.probeMouth();
function state(name: string) {
  controller.set(name); diagnostics.state = name;
  $('pose-note').textContent = STATES[name].pose;
  document.querySelectorAll('[data-state]').forEach(el => el.classList.toggle('active', (el as HTMLElement).dataset.state === name));
}
for (const [id, config] of Object.entries(STATES)) {
  const button = document.createElement('button'); button.textContent = (config as any).label; button.dataset.state = id;
  button.onclick = () => state(id); $('states').append(button);
}
state('IDLE_LISTEN');
async function loadModel() {
  const token = ++request;
  diagnostics.ready = false; diagnostics.error = ''; $('status').textContent = '正在進行 Core 一致性檢查與載入…';
  const select = $<HTMLSelectElement>('model'); select.disabled = true;
  // Release before creating another model; state switching never reaches this path.
  avatar?.dispose(gl!); avatar = undefined;
  const name = select.value;
  const file = name === 'governess' ? 'seethrough_output' : 'tml';
  try {
    const loaded = await Avatar.open(`/generated/models/${name}/${file}.model3.json`, gl!, canvas);
    if (request !== token) { loaded.dispose(gl!); return; }
    avatar = loaded;
    diagnostics.loads = Avatar.loads; diagnostics.parameters = [...loaded.ids.keys()]; diagnostics.drawables = loaded.getModel().getDrawableCount(); diagnostics.ready = true;
    $('model-label').textContent = name === 'governess' ? '愛管家' : '官方測試案例';
    $('status').textContent = `Core 載入成功 · ${diagnostics.drawables} 個 ArtMesh · ${diagnostics.parameters.length} 個參數`;
  } catch (error) { diagnostics.error = String(error); $('status').textContent = `載入失敗：${error}`; console.error(error); }
  finally { if (request === token) select.disabled = false; }
}
$('model').addEventListener('change', loadModel);
$('compare').addEventListener('change', event => { $('original').hidden = !(event.target as HTMLInputElement).checked; });
$('background').addEventListener('change', event => { $('stage').dataset.background = (event.target as HTMLSelectElement).value; });
function closeMouth() { mouth = 0; diagnostics.mouth = 0; }
audio.addEventListener('play', async () => {
  audioMode = true; mouthSlider.value = '0';
  try {
    if (!audioContext) {
      audioContext = new AudioContext(); analyser = audioContext.createAnalyser(); analyser.fftSize = 1024;
      audioContext.createMediaElementSource(audio).connect(analyser); analyser.connect(audioContext.destination);
      samples = new Float32Array(analyser.fftSize);
    }
    await audioContext.resume(); state('SPEAKING');
  } catch (error) { audio.pause(); $('status').textContent = `音訊初始化失敗：${error}`; }
});
for (const event of ['pause', 'ended', 'emptied', 'error']) audio.addEventListener(event, closeMouth);
audio.addEventListener('volumechange', () => { if (audio.muted || audio.volume === 0) closeMouth(); });
$('stop').onclick = () => { audio.pause(); audio.currentTime = 0; audioMode = true; mouthSlider.value = '0'; closeMouth(); };
mouthSlider.oninput = () => { audio.pause(); audioMode = false; mouth = Number(mouthSlider.value); };
$('audio-file').addEventListener('change', event => {
  const file = (event.target as HTMLInputElement).files?.[0]; if (!file) return;
  audio.pause(); if (audioUrl) URL.revokeObjectURL(audioUrl);
  audioUrl = URL.createObjectURL(file); audio.src = audioUrl; audioMode = true; closeMouth();
});
function frame(now: number) {
  const dt = Math.min((now - last) / 1000, 0.1); last = now;
  if (audioMode) {
    if (analyser && !audio.paused && !audio.ended && !audio.muted && audio.volume > 0 && audio.readyState >= 2) {
      analyser.getFloatTimeDomainData(samples); mouth = approachMouth(mouth, rmsToMouth(samples, audio.volume), dt);
    } else mouth = 0;
  }
  gl!.clearColor(0, 0, 0, 0); gl!.clear(gl!.COLOR_BUFFER_BIT);
  try { avatar?.frame(dt, (now - started) / 1000, controller.tick(dt), mouth, canvas); }
  catch (error) { diagnostics.error = String(error); diagnostics.ready = false; $('status').textContent = String(error); console.error(error); return; }
  frames++; if (now - fpsStart >= 1000) { fps = Math.round(frames * 1000 / (now - fpsStart)); frames = 0; fpsStart = now; }
  diagnostics.mouth = mouth; diagnostics.frames++; diagnostics.fps = fps;
  diagnostics.modelMouth = avatar?.mouthValue() ?? null;
  diagnostics.mouthVertices = avatar?.mouthVertices() ?? [];
  $('mouth-value').textContent = mouth.toFixed(2);
  $('diagnostics').textContent = JSON.stringify({ ...diagnostics, mouthVertices: `${diagnostics.mouthVertices.length / 2} vertices` }, null, 2);
  requestAnimationFrame(frame);
}
canvas.addEventListener('webglcontextlost', event => { event.preventDefault(); diagnostics.ready = false; $('status').textContent = 'WebGL context 中斷，請重新整理此頁。'; });
loadModel(); requestAnimationFrame(frame);
