import { CubismFramework, Option, LogLevel } from '@cubism/live2dcubismframework';
import { CubismUserModel } from '@cubism/model/cubismusermodel';
import { CubismMatrix44 } from '@cubism/math/cubismmatrix44';
const options = new Option();
options.logFunction = (message: string) => console.info(message);
options.loggingLevel = LogLevel.LogLevel_Warning;
CubismFramework.startUp(options);
CubismFramework.initialize();
async function checked(url: string) { const response = await fetch(url); if (!response.ok) throw new Error(`${response.status}: ${url}`); return response; }
export class Avatar extends CubismUserModel {
  ids = new Map<string, any>();
  textures: WebGLTexture[] = [];
  static loads = 0;
  static async open(url: string, gl: WebGLRenderingContext, canvas: HTMLCanvasElement) {
    const avatar = new Avatar();
    try {
      const info = await (await checked(url)).json();
      const base = new URL('.', new URL(url, location.href));
      const path = (p: string) => new URL(p, base).href;
      const moc = await (await checked(path(info.FileReferences.Moc))).arrayBuffer();
      avatar.loadModel(moc, true);
      if (!avatar.getModel()) throw new Error('Core 無法載入此 moc3，或一致性檢查失敗');
      Avatar.loads++;
      const model = avatar.getModel();
      for (let i = 0; i < model.getParameterCount(); i++) {
        const id = model.getParameterId(i);
        avatar.ids.set(id.getString(), id);
      }
      if (info.FileReferences.Physics) {
        const data = await (await checked(path(info.FileReferences.Physics))).arrayBuffer();
        avatar.loadPhysics(data, data.byteLength);
      }
      // Fit actual exported vertices: exporters can use different canvas origins.
      let left = Infinity, right = -Infinity, bottom = Infinity, top = -Infinity;
      for (let i = 0; i < model.getDrawableCount(); i++) {
        const vertices = model.getDrawableVertices(i);
        for (let v = 0; v < vertices.length; v += 2) {
          left = Math.min(left, vertices[v]); right = Math.max(right, vertices[v]);
          bottom = Math.min(bottom, vertices[v + 1]); top = Math.max(top, vertices[v + 1]);
        }
      }
      const scale = 1.75 / Math.max(right - left, top - bottom);
      const transform = avatar.getModelMatrix().getArray();
      avatar.getModelMatrix().loadIdentity();
      transform[0] = scale; transform[5] = scale;
      transform[12] = -(left + right) * scale / 2;
      transform[13] = -(bottom + top) * scale / 2;
      avatar.createRenderer(canvas.width, canvas.height);
      avatar.getRenderer().startUp(gl);
      avatar.getRenderer().setIsPremultipliedAlpha(true);
      for (const [index, file] of info.FileReferences.Textures.entries()) {
        const bitmap = await createImageBitmap(await (await checked(path(file))).blob());
        const texture = gl.createTexture()!;
        avatar.textures.push(texture);
        gl.bindTexture(gl.TEXTURE_2D, texture);
        // ImageBitmap ignores UNPACK_PREMULTIPLY_ALPHA_WEBGL; use premultiplied bitmap explicitly.
        const premultiplied = await createImageBitmap(bitmap, { premultiplyAlpha: 'premultiply' });
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, premultiplied);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        avatar.getRenderer().bindTexture(index, texture);
        bitmap.close(); premultiplied.close();
      }
      return avatar;
    } catch (error) { avatar.dispose(gl); throw error; }
  }
  set(id: string, value: number) { const handle = this.ids.get(id); if (handle) this.getModel().setParameterValueById(handle, value); }
  sourceViewport(rect: {left:number,top:number,width:number,height:number}) {
    const info=this.getModel().getModel().canvasinfo;
    const matrix=this.getModelMatrix(); matrix.loadIdentity(); const a=matrix.getArray();
    const scale=2*info.PixelsPerUnit/rect.height;
    a[0]=scale;a[5]=scale;
    a[12]=-(rect.left+rect.width/2-info.CanvasOriginX)*scale/info.PixelsPerUnit;
    a[13]=-(info.CanvasOriginY-rect.top-rect.height/2)*scale/info.PixelsPerUnit;
  }
  mouthValue() { const id = this.ids.get('ParamMouthOpenY'); return id ? this.getModel().getParameterValueById(id) : null; }
  mouthVertices() {
    const result: number[] = [];
    const model = this.getModel();
    for (let i = 0; i < model.getDrawableCount(); i++) {
      if (/mouth/i.test(model.getDrawableId(i).getString())) result.push(...model.getDrawableVertices(i));
    }
    return result;
  }
  probeMouth() {
    // Synchronous Core evaluations keep every other parameter identical.
    const saved = this.mouthValue() ?? 0;
    this.set('ParamMouthOpenY', 0); this.getModel().update(); const closed = this.mouthVertices();
    this.set('ParamMouthOpenY', 1); this.getModel().update(); const open = this.mouthVertices();
    this.set('ParamMouthOpenY', saved); this.getModel().update();
    return { count: closed.length / 2, maxDelta: Math.max(...closed.map((x, i) => Math.abs(x - open[i]))) };
  }
  frame(dt: number, time: number, controls: any, mouth: number, canvas: HTMLCanvasElement) {
    this.set('ParamAngleX', controls.angle + Math.sin(time * 0.7) * 1.5);
    this.set('ParamAngleY', Math.sin(time * 0.5));
    this.set('ParamAngleZ', controls.tilt);
    this.set('ParamBodyAngleX', controls.angle * 0.25);
    this.set('ParamBodyAngleZ', Math.sin(time * 0.5) * 0.6);
    this.set('ParamBreath', (Math.sin(time * 1.7) + 1) * 0.5);
    const blinkPhase = time % 4.3;
    const blink = blinkPhase < 0.18 ? Math.abs(blinkPhase - 0.09) / 0.09 : 1;
    this.set('ParamEyeLOpen', blink); this.set('ParamEyeROpen', blink);
    this.set('ParamBrowLY', controls.brow); this.set('ParamBrowRY', controls.brow);
    this.set('ParamMouthForm', controls.smile);
    this._physics?.evaluate(this.getModel(), dt);
    this.set('ParamMouthOpenY', mouth);
    for (const [id,value] of Object.entries(controls.parameters ?? {})) this.set(id, Number(value));
    this.getModel().update();
    // Authoring inspection only: isolate original hand meshes without moving them.
    // Restore Core's values after rendering so normal playback remains unaffected.
    const drawables=this.getModel().getModel().drawables;
    const savedOpacity=controls.inspectDrawable ? drawables.opacities.slice() : undefined;
    if(savedOpacity) for(let i=0;i<drawables.count;i++) {
      if(String(drawables.ids[i])!==controls.inspectDrawable) drawables.opacities[i]=0;
    }
    const matrix = new CubismMatrix44();
    matrix.scale(canvas.height / canvas.width, 1);
    matrix.multiplyByMatrix(this.getModelMatrix());
    const renderer = this.getRenderer();
    renderer.setMvpMatrix(matrix);
    renderer.setRenderState(null, [0, 0, canvas.width, canvas.height]);
    renderer.drawModel('/generated/shaders/');
    if(savedOpacity) drawables.opacities.set(savedOpacity);
  }
  dispose(gl: WebGLRenderingContext) {
    this.release();
    for (const texture of this.textures) gl.deleteTexture(texture);
    this.textures = [];
  }
}
