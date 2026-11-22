import { defineConfig } from 'vite';
import { resolve } from 'node:path';
export default defineConfig({
  optimizeDeps: { entries: ['index.html'] },
  build: { rolldownOptions: { input: { main: resolve(import.meta.dirname,'index.html'), arms: resolve(import.meta.dirname,'arms.html'), fidelity: resolve(import.meta.dirname,'fidelity.html'), hands: resolve(import.meta.dirname,'hands.html'), shared: resolve(import.meta.dirname,'shared-face.html') } } },
  resolve: { alias: { '@cubism': resolve(import.meta.dirname, 'vendor/cubism/CubismSdkForWeb-5-r.5/Framework/src') } },
  server: { host: '127.0.0.1', port: 5187, strictPort: true },
});
