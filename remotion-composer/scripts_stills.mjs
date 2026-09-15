import { bundle } from '@remotion/bundler';
import { renderStill, selectComposition } from '@remotion/renderer';
import path from 'path';
const comp = process.argv[2] || 'FableNewsYT';
const frames = (process.argv[3] || '75').split(',').map(Number);
const outDir = process.argv[4] || 'out/fable-qa';
const serveUrl = await bundle({ entryPoint: path.resolve('src/index.tsx'), onProgress: () => {} });
const composition = await selectComposition({ serveUrl, id: comp, inputProps: {} });
for (const f of frames) {
  const out = path.join(outDir, `f${String(f).padStart(5, '0')}.png`);
  await renderStill({ composition, serveUrl, output: out, frame: f, inputProps: {}, chromiumOptions: { gl: 'angle' } });
  console.log('still', f, out);
}
