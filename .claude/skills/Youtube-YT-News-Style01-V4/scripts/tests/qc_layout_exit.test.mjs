// CF-A66 Q1: qc_layout.mjs must exit promptly after its status line. Cause found in a real run: the bundler's esbuild service
// (`esbuild --service --ping`, a child process) stays alive after bundle() returns; the process then lingered until the wrapper killed it.
// Fix: stop esbuild right after the bundle is built (also when the build fails) + an unref'd safety timer that ends the process
// a few seconds after the status line whatever is still alive.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureBundle, scheduleExit, stopEsbuild} from '../qc_layout.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const QC = path.resolve(here, '..', 'qc_layout.mjs');

async function fakeComposer({bundleFails = false, withEsbuild = true} = {}) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'qc-exit-'));
  const log = path.join(dir, 'calls.log');
  await fs.writeFile(path.join(dir, 'package.json'), '{"name":"fake-composer"}');
  await fs.mkdir(path.join(dir, 'src'), {recursive: true});
  const mod = (name, body) => fs.mkdir(path.join(dir, 'node_modules', ...name.split('/')), {recursive: true})
    .then(() => fs.writeFile(path.join(dir, 'node_modules', ...name.split('/'), 'index.js'), body));
  await mod('@remotion/bundler', `const fs=require('fs');exports.bundle=async({outDir})=>{fs.appendFileSync(${JSON.stringify(log)},'bundle\\n');${bundleFails ? "throw new Error('build failed');" : "fs.mkdirSync(outDir,{recursive:true});fs.writeFileSync(outDir+'/index.html','x');"}};`);
  if (withEsbuild) await mod('esbuild', `const fs=require('fs');exports.stop=async()=>{fs.appendFileSync(${JSON.stringify(log)},'esbuild.stop\\n');};`);
  return {dir, calls: async () => (await fs.readFile(log, 'utf8').catch(() => '')).trim().split('\n').filter(Boolean)};
}

test('ensureBundle stops the esbuild service after the bundle is built (the child that kept the process alive)', async () => {
  const c = await fakeComposer(), runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'qc-run-'));
  const staged = await fs.mkdtemp(path.join(os.tmpdir(), 'qc-pub-'));
  const r = await ensureBundle({composer: c.dir, runDir, rebuild: true, makePublicDir: async () => staged});
  assert.equal(r.reused, false);
  assert.deepEqual(await c.calls(), ['bundle', 'esbuild.stop']);
});

test('ensureBundle stops esbuild when the build fails too, and the failure is still reported', async () => {
  const c = await fakeComposer({bundleFails: true}), runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'qc-run-'));
  const staged = await fs.mkdtemp(path.join(os.tmpdir(), 'qc-pub-'));
  await assert.rejects(ensureBundle({composer: c.dir, runDir, rebuild: true, makePublicDir: async () => staged}), /build failed/);
  assert.deepEqual(await c.calls(), ['bundle', 'esbuild.stop']);
});

test('ensureBundle does not start (or stop) anything when the bundle of the run is reused', async () => {
  const c = await fakeComposer(), runDir = await fs.mkdtemp(path.join(os.tmpdir(), 'qc-run-'));
  await fs.mkdir(path.join(runDir, 'bundle'), {recursive: true}); await fs.writeFile(path.join(runDir, 'bundle', 'index.html'), 'x');
  const r = await ensureBundle({composer: c.dir, runDir, makePublicDir: async () => { throw new Error('must not stage'); }});
  assert.equal(r.reused, true); assert.deepEqual(await c.calls(), []);
});

test('stopEsbuild is best effort: a composer without esbuild, or an esbuild without stop(), is not an error', async () => {
  const c = await fakeComposer({withEsbuild: false});
  assert.equal(await stopEsbuild(c.dir), false);
  assert.equal(await stopEsbuild(c.dir, () => ({})), false);
  assert.equal(await stopEsbuild(c.dir, () => ({stop: async () => { throw new Error('boom'); }})), false);
  assert.equal(await stopEsbuild(c.dir, () => ({stop: async () => {}})), true);
});

test('scheduleExit sets the exit code, never keeps a healthy process alive (unref) and ends a lingering one with that code and a note', async () => {
  const saved = process.exitCode;
  try {
    const calls = [], notes = [];
    const timer = scheduleExit(75, {graceMs: 15, exit: code => calls.push(code), warn: l => notes.push(l), resources: () => ['Timeout', 'ChildProcess', 'Pipe']});
    assert.equal(process.exitCode, 75);
    assert.equal(timer.hasRef(), false, 'the safety timer is unref\'d');
    await new Promise(r => setTimeout(r, 80));
    assert.deepEqual(calls, [75]);
    assert.equal(notes.length, 1); assert.match(notes[0], /ChildProcess,Pipe/); assert.match(notes[0], /code 75/);
  } finally { process.exitCode = saved; }
});

// A real process: the same wiring as the CLI's main guard, with a handle that never closes (what the esbuild child did).
function runChild(body) {
  const script = `import {scheduleExit} from ${JSON.stringify(pathToFileURL(QC).href)};\n${body}`;
  return new Promise(resolve => {
    const child = spawn(process.execPath, ['--input-type=module', '-e', script], {stdio: ['ignore', 'pipe', 'pipe']});
    let out = '', err = '', statusAt = null;
    child.stdout.on('data', d => { out += d; if (statusAt === null && out.includes('QC_LAYOUT')) statusAt = Date.now(); });
    child.stderr.on('data', d => { err += d; });
    const kill = setTimeout(() => child.kill('SIGKILL'), 15_000);
    child.on('exit', (code, signal) => { clearTimeout(kill); resolve({code, signal, out, err, afterStatusMs: statusAt === null ? null : Date.now() - statusAt}); });
  });
}

test('a process with a handle that never closes exits with the documented code within seconds of the status line', async () => {
  for (const code of [0, 1, 75]) {
    const r = await runChild(`setInterval(() => {}, 1000);\nconsole.log('QC_LAYOUT COMPLETE pass=${code === 0} run=x');\nscheduleExit(${code}, {graceMs: 400});`);
    assert.equal(r.signal, null);
    assert.equal(r.code, code);
    assert.ok(r.afterStatusMs !== null && r.afterStatusMs < 4000, `exited ${r.afterStatusMs} ms after the status line`);
    assert.match(r.err, /QC_LAYOUT NOTE the process was still alive 400 ms after the result/);
    assert.equal(r.out.trim().split('\n').pop(), `QC_LAYOUT COMPLETE pass=${code === 0} run=x`, 'stdout keeps exactly the status line');
  }
});

test('a clean process exits by itself, immediately, with no note', async () => {
  const r = await runChild(`console.log('QC_LAYOUT COMPLETE pass=true run=x');\nscheduleExit(0, {graceMs: 5000});`);
  assert.equal(r.code, 0); assert.equal(r.err, ''); assert.ok(r.afterStatusMs < 2000, `${r.afterStatusMs} ms`);
});
