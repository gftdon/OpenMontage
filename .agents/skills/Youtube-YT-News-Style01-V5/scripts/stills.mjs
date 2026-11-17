// Render many QA stills with ONE bundle (10x faster than `remotion still` per frame).
//
//   node stills.mjs <CompId> <frame,frame,...> <outDir> [remotionComposerDir] [--episode <episode.json> --captions <captions.json>]
//
// --episode/--captions (both or neither) are passed as inputProps = { episode, captions }; without them the
// composition's defaultProps (the sample) are used.
// Bundles from the V4 entry (src/ytNewsStyle01V4.entry.tsx), never from Root.tsx / index.tsx.
// e.g. node .claude/skills/Youtube-YT-News-Style01-V5/scripts/stills.mjs YtNewsStyle01V4 75,388,1320 remotion-composer/out/qa remotion-composer
import fs from 'fs';
import path from 'path';
import { createRequire } from 'module';
import { entryPointOf } from './qc_manifest.mjs';
const rawArgs = process.argv.slice(2);
const flagValue = (name) => { const i = rawArgs.indexOf(name); if (i < 0) return undefined; const v = rawArgs[i + 1]; if (!v || v.startsWith('--')) { console.error(`${name} needs a file path`); process.exit(1); } return v; };
const episodeFile = flagValue('--episode');
const captionsFile = flagValue('--captions');
if ((episodeFile === undefined) !== (captionsFile === undefined)) { console.error('--episode and --captions must be given together'); process.exit(1); }
const positional = [];
for (let i = 0; i < rawArgs.length; i++) { if (rawArgs[i] === '--episode' || rawArgs[i] === '--captions') { i++; continue; } positional.push(rawArgs[i]); }
const comp = positional[0];
const frames = (positional[1] || '75').split(',').map(Number);
const outDir = path.resolve(positional[2] || 'out/qa');
const root = path.resolve(positional[3] || process.cwd());
if (!comp) { console.error('usage: node stills.mjs <CompId> <frames> <outDir> [remotionComposerDir] [--episode <episode.json> --captions <captions.json>]'); process.exit(1); }
const inputProps = episodeFile ? { episode: JSON.parse(fs.readFileSync(episodeFile, 'utf8')), captions: JSON.parse(fs.readFileSync(captionsFile, 'utf8')) } : {};
const require = createRequire(path.join(root, 'package.json'));
const { bundle } = require('@remotion/bundler');
const { renderStill, selectComposition } = require('@remotion/renderer');
const serveUrl = await bundle({ entryPoint: entryPointOf(root), onProgress: () => {} });
const composition = await selectComposition({ serveUrl, id: comp, inputProps });
for (const f of frames) {
  const out = path.join(outDir, `f${String(f).padStart(5, '0')}.png`);
  await renderStill({ composition, serveUrl, output: out, frame: f, inputProps, chromiumOptions: { gl: 'angle' } });
  console.log('still', f, out);
}
