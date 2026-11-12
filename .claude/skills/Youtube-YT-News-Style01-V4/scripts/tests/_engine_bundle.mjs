// Test helper (not a test): bundle the V4 engine for Node with esbuild so tests can import its pure exports.
// esbuild is resolved from remotion-composer/node_modules (a dependency of @remotion/bundler). 'react' and
// 'remotion' are replaced by inert stubs (the bundle lives in the OS temp dir, where the real packages cannot
// be resolved); the engine calls neither at import time.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const root = path.resolve(new URL('../../../../..', import.meta.url).pathname);
export const enginePath = path.join(root, 'remotion-composer/src/YtNewsStyle01V4.tsx');

let cached;
export async function loadEngine() {
  if (cached) return cached;
  const require = createRequire(path.join(root, 'remotion-composer/package.json'));
  const esbuild = require('esbuild');
  const stub = { name: 'stub-react-remotion', setup(b) {
    b.onResolve({ filter: /^(react|react\/jsx-runtime|remotion)$/ }, (a) => ({ path: a.path, namespace: 'stub' }));
    b.onLoad({ filter: /.*/, namespace: 'stub' }, () => ({ loader: 'js', contents: "module.exports=new Proxy({},{get:(_,k)=>k==='__esModule'?false:()=>undefined});" }));
  } };
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'v4-engine-'));
  const outfile = path.join(dir, 'engine.mjs');
  await esbuild.build({ entryPoints: [enginePath], bundle: true, platform: 'node', format: 'esm', outfile, plugins: [stub], logLevel: 'silent', jsx: 'transform' });
  cached = await import(pathToFileURL(outfile).href);
  fs.rmSync(dir, { recursive: true, force: true });
  return cached;
}
