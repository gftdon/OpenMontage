// CF-A66: every V4 tool that bundles (qc_layout, render_episode, stills) must bundle from the V4 entry, never from index.tsx / Root.tsx.
// Remotion is replaced by fakes living in a throw-away composer's node_modules; the fake bundler records the entry point it is given.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {ensureBundle as layoutEnsureBundle} from '../qc_layout.mjs';
import {ENTRY_REL, entryPointOf} from '../qc_manifest.mjs';

const execFileP = promisify(execFile);
const here = path.dirname(fileURLToPath(import.meta.url));
const scripts = path.resolve(here, '..');

async function fakeComposer() {
  const d = await fs.mkdtemp(path.join(os.tmpdir(), 'entry-bundle-'));
  const log = path.join(d, 'bundle-calls.jsonl');
  const writePkg = async (name, source) => {
    const dir = path.join(d, 'node_modules', name);
    await fs.mkdir(dir, {recursive: true});
    await fs.writeFile(path.join(dir, 'package.json'), JSON.stringify({name, main: 'index.js'}));
    await fs.writeFile(path.join(dir, 'index.js'), source);
  };
  await fs.writeFile(path.join(d, 'package.json'), '{}');
  await writePkg('@remotion/bundler', `const fs = require('fs'); exports.bundle = async o => { fs.appendFileSync(${JSON.stringify(log)}, JSON.stringify({entryPoint: o.entryPoint}) + '\\n'); if (o.outDir) fs.mkdirSync(o.outDir, {recursive: true}); return '/fake-serve-url'; };`);
  await writePkg('@remotion/renderer', `exports.selectComposition = async o => ({id: o.id, durationInFrames: 3}); exports.renderStill = async () => {};`);
  const calls = async () => (await fs.readFile(log, 'utf8').catch(() => '')).split('\n').filter(Boolean).map(l => JSON.parse(l));
  return {d, calls};
}

test('the entry path is one shared definition: <composer>/src/ytNewsStyle01V4.entry.tsx', () => {
  assert.equal(ENTRY_REL, 'src/ytNewsStyle01V4.entry.tsx');
  assert.equal(entryPointOf('/c'), '/c/src/ytNewsStyle01V4.entry.tsx');
});

test('qc_layout ensureBundle bundles from the V4 entry', async () => {
  const {d, calls} = await fakeComposer();
  try {
    const runDir = path.join(d, 'run');
    await fs.mkdir(runDir);
    await layoutEnsureBundle({composer: d, runDir, makePublicDir: async () => path.join(d, 'pub')});
    assert.deepEqual(await calls(), [{entryPoint: path.join(d, ENTRY_REL)}]);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('stills.mjs bundles from the V4 entry', async () => {
  const {d, calls} = await fakeComposer();
  try {
    await execFileP(process.execPath, [path.join(scripts, 'stills.mjs'), 'YtNewsStyle01V4', '1,2', path.join(d, 'out'), d]);
    assert.deepEqual(await calls(), [{entryPoint: path.join(d, ENTRY_REL)}]);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('no V4 script names index.tsx or Root.tsx as a bundle entry', async () => {
  for (const name of ['qc_layout.mjs', 'render_episode.mjs', 'stills.mjs', 'qc_manifest.mjs', 'gate_integrity.mjs']) {
    const text = await fs.readFile(path.join(scripts, name), 'utf8');
    const code = text.split('\n').filter(l => !/^\s*(\/\/|\/\*|\*)/.test(l)).join('\n');
    assert.doesNotMatch(code, /['"`]index\.tsx['"`]|src\/index\.tsx|['"`]Root\.tsx['"`]|src\/Root\.tsx/, name);
  }
});
