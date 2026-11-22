import { access, cp, mkdir, readdir, copyFile } from 'node:fs/promises';
import { resolve } from 'node:path';
const root = resolve(import.meta.dirname, '..');
const sdk = resolve(root, 'vendor/cubism/CubismSdkForWeb-5-r.5');
const out = resolve(root, 'public/generated');
const models = ['compatibility', 'governess', 'arm-spike-clean', 'face-fidelity',
  'shared-face', 'gaze-face', 'speech-face', 'expression-face', 'head-face',
  'turn-face', 'polish-face', 'gesture-face'];
const missing = [];
for (const asset of [
  'vendor/cubism/CubismSdkForWeb-5-r.5/Core/live2dcubismcore.min.js',
  'vendor/cubism/CubismSdkForWeb-5-r.5/Framework/Shaders/WebGL',
  'authoring/shared-face/head-original.png',
  ...models.map(model => `models/${model}`),
]) {
  try {
    await access(resolve(root, asset));
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    missing.push(asset);
  }
}
if (missing.length) {
  console.error('Local Live2D files are missing. See README.md for setup.\n' + missing.join('\n'));
  process.exit(1);
}
await mkdir(out, { recursive: true });
await copyFile(`${sdk}/Core/live2dcubismcore.min.js`, `${out}/live2dcubismcore.min.js`);
await cp(`${sdk}/Framework/Shaders/WebGL`, `${out}/shaders`, { recursive: true });
for (const model of models) {
  await mkdir(`${out}/models/${model}`, { recursive: true });
  for (const entry of await readdir(`${root}/models/${model}`, { withFileTypes: true })) {
    if (entry.isDirectory() || /\.(moc3|model3\.json|physics3\.json|motion3\.json|exp3\.json|cdi3\.json)$/.test(entry.name)) {
      await cp(`${root}/models/${model}/${entry.name}`, `${out}/models/${model}/${entry.name}`, { recursive: true });
    }
  }
}
await copyFile(resolve(root, '../../ai_voice_assistant/assets/states/layers/idle_listen_1.png'), `${out}/original.png`);
await mkdir(`${out}/references`, {recursive:true});
for(const file of await readdir(resolve(root,'../../ai_voice_assistant/assets/states/layers'))) {
  if (/^(idle_listen|collecting|sending|speaking|hot_listen)_\d+\.png$/.test(file)) await copyFile(resolve(root,'../../ai_voice_assistant/assets/states/layers',file),`${out}/references/${file}`);
}
await mkdir(`${out}/audio`, { recursive: true });
await mkdir(`${out}/hands`, {recursive:true});
await copyFile(`${root}/authoring/shared-face/head-original.png`,`${out}/shared-face-original.png`);
for(const hand of ['index','chin']) {
  try {await copyFile(`${root}/authoring/source-parts/${hand}-hand-v2.png`,`${out}/hands/${hand}.png`);} catch(e) {if(e.code!=='ENOENT')throw e;}
}
try { await cp(`${root}/fixtures/audio`, `${out}/audio`, { recursive: true }); } catch (e) { if (e.code !== 'ENOENT') throw e; }
console.log('Prepared local Core, shaders, exported models and original reference.');
