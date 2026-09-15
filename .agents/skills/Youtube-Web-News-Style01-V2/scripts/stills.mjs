// Render many QA stills with ONE bundle (10x faster than `remotion still` per frame).
//
//   node stills.mjs <CompId> <frame,frame,...> <outDir> [remotionComposerDir]
//
// e.g. node .claude/skills/Youtube-Web-News-Style01-V2/scripts/stills.mjs FableNewsYTV2 12,62,112 remotion-composer/out/qa remotion-composer
import path from 'path';
import { createRequire } from 'module';
const comp = process.argv[2];
const frames = (process.argv[3] || '75').split(',').map(Number);
const outDir = path.resolve(process.argv[4] || 'out/qa');
const root = path.resolve(process.argv[5] || process.cwd());
if (!comp) { console.error('usage: node stills.mjs <CompId> <frames> <outDir> [remotionComposerDir]'); process.exit(1); }
const require = createRequire(path.join(root, 'package.json'));
const { bundle } = require('@remotion/bundler');
const { renderStill, selectComposition } = require('@remotion/renderer');
const serveUrl = await bundle({ entryPoint: path.join(root, 'src/index.tsx'), onProgress: () => {} });
const composition = await selectComposition({ serveUrl, id: comp, inputProps: {} });
for (const f of frames) {
  const out = path.join(outDir, `f${String(f).padStart(5, '0')}.png`);
  await renderStill({ composition, serveUrl, output: out, frame: f, inputProps: {}, chromiumOptions: { gl: 'angle' } });
  console.log('still', f, out);
}
