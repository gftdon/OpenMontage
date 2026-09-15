#!/usr/bin/env node
// Render thumbnail variants from the episode's thumbnail composition (one bundle, N stills).
//   node thumbs.mjs <remotionComposerDir> <outDir> <ThumbCompId> [variants=A,B,C] [avatarSec=3.0]
// Output: <outDir>/thumb_<variant>.png (1920x1080). Downscale to 1280x720 JPEG for YouTube with PIL/ffmpeg.
import path from "path";
import fs from "fs";
import { createRequire } from "module";
const root = path.resolve(process.argv[2] || "remotion-composer");
const outDir = path.resolve(process.argv[3] || "out/thumbs");
const compId = process.argv[4] || "FableNewsThumb";
const variants = (process.argv[5] || "A,B,C").split(",");
const avatarSec = Number(process.argv[6] || "3.0");
const require = createRequire(path.join(root, "package.json"));
const { bundle } = require("@remotion/bundler");
const { renderStill, selectComposition } = require("@remotion/renderer");
fs.mkdirSync(outDir, { recursive: true });
const serveUrl = await bundle({ entryPoint: path.join(root, "src/index.tsx"), onProgress: () => {} });
for (const v of variants) {
  const inputProps = { variant: v, avatarSec };
  const composition = await selectComposition({ serveUrl, id: compId, inputProps });
  const out = path.join(outDir, `thumb_${v}.png`);
  await renderStill({ composition, serveUrl, output: out, frame: 0, inputProps, chromiumOptions: { gl: "angle" } });
  console.log("thumb", v, out);
}
