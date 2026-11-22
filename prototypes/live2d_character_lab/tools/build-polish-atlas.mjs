import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {resolve} from 'node:path';
import utils from 'playwright-core/lib/utilsBundle';
const root=resolve(import.meta.dirname,'..');
const folder=resolve(root,'authoring/polish-v11');
const input=await readFile(resolve(root,'models/turn-face/original.4096/texture_01.png'));
const sourceHash='c82edeca8c22da5509a31a219cbca471b34fedb873eea4d422329fd64c5a5c39';
if(createHash('sha256').update(input).digest('hex')!==sourceHash)throw Error('Unexpected v10 atlas layout');
const atlas=utils.PNG.sync.read(input);
const patch=JSON.parse(await readFile(resolve(folder,'hair-edge-patch.json'),'utf8'));
for(const [x,y,alpha,ink] of patch){
  const index=((1030+y)*atlas.width+2+x)*4;
  atlas.data[index+3]=Math.min(alpha,atlas.data[index+3]);
  if(ink)atlas.data.set([39,29,30],index);
}
await writeFile(resolve(folder,'texture_01.png'),utils.PNG.sync.write(atlas));
