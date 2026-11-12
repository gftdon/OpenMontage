import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {checkIntegrity} from '../gate_integrity.mjs';
import {sha256Hex} from '../qc_manifest.mjs';

const execFileP = promisify(execFile);
const here = path.dirname(fileURLToPath(import.meta.url));
const worktree = path.resolve(here, '../../../../..');
const realSkill = path.resolve(here, '../..');
const GUARD = '||box.width<=0||box.height<=0';

const realRoot = await fs.readFile(path.join(worktree, 'remotion-composer/src/Root.tsx'), 'utf8');
const reference = await fs.readFile(path.join(realSkill, 'assets/YtNewsStyle01V4.reference.tsx'), 'utf8');

/** Temp composer + skill: engine identical to the reference, Root copied from the real worktree. */
async function setup({engine = reference, root = realRoot, lock} = {}) {
  const d = await fs.mkdtemp(path.join(os.tmpdir(), 'integrity-'));
  const composerDir = path.join(d, 'composer');
  const skillDir = path.join(d, 'skill');
  await fs.mkdir(path.join(composerDir, 'src'), {recursive: true});
  await fs.mkdir(path.join(skillDir, 'assets'), {recursive: true});
  await fs.mkdir(path.join(skillDir, 'scripts'), {recursive: true});
  await fs.writeFile(path.join(composerDir, 'src/YtNewsStyle01V4.tsx'), engine);
  await fs.writeFile(path.join(composerDir, 'src/Root.tsx'), root);
  await fs.writeFile(path.join(skillDir, 'assets/YtNewsStyle01V4.reference.tsx'), reference);
  await fs.writeFile(path.join(skillDir, 'scripts/locked.mjs'), 'export const locked = 1;\n');
  if (lock) await fs.writeFile(path.join(skillDir, 'scripts/gates.lock.json'), JSON.stringify(lock));
  return {d, composerDir, skillDir};
}
const ids = r => r.issues.map(i => i.id);

test('the engine guard that went missing in the V3 incident exists in the reference engine', () => {
  assert.ok(reference.includes(GUARD), 'reference engine has the box.width/height guard');
});

test('identical engine and the real Root pass; missing lock is only a warning', async () => {
  const {d, composerDir, skillDir} = await setup();
  try {
    const r = await checkIntegrity({composerDir, skillDir});
    assert.deepEqual(r.issues, []);
    assert.equal(r.ok, true);
    assert.deepEqual(r.warnings.map(w => w.id), ['gates-lock-missing']);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('removing the box.width/height guard from the engine copy is engine-drift', async () => {
  const {d, composerDir, skillDir} = await setup({engine: reference.replace(GUARD, '')});
  try {
    const r = await checkIntegrity({composerDir, skillDir});
    assert.equal(r.ok, false);
    assert.deepEqual(ids(r), ['engine-drift']);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('a one-character engine change is engine-drift; a missing engine too', async () => {
  const {d, composerDir, skillDir} = await setup({engine: reference.replace('MODE_BLEND_SEC = 0.55', 'MODE_BLEND_SEC = 0.56')});
  try {
    assert.deepEqual(ids(await checkIntegrity({composerDir, skillDir})), ['engine-drift']);
    await fs.rm(path.join(composerDir, 'src/YtNewsStyle01V4.tsx'));
    assert.deepEqual(ids(await checkIntegrity({composerDir, skillDir})), ['engine-drift']);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('Root importing the engine from a copy module is root-registration', async () => {
  const root = realRoot.replace('from "./YtNewsStyle01V4";', 'from "./YtNewsStyle01V4Copy";');
  assert.notEqual(root, realRoot);
  const {d, composerDir, skillDir} = await setup({root});
  try {
    const r = await checkIntegrity({composerDir, skillDir});
    assert.ok(ids(r).includes('root-registration'));
    // even when the legit import is kept and a second one from the copy is added
    const both = realRoot.replace('\n', '\nimport { YtNewsStyle01V4 as Copy } from "./YtNewsStyle01V4Copy";\n');
    await fs.writeFile(path.join(composerDir, 'src/Root.tsx'), both);
    assert.ok(ids(await checkIntegrity({composerDir, skillDir})).includes('root-registration'));
  } finally { await fs.rm(d, {recursive: true}); }
});

test('Root with two compositions using the engine id, or none, is root-registration', async () => {
  const line = realRoot.split('\n').find(l => l.includes('<Composition id="YtNewsStyle01V4"'));
  assert.ok(line);
  const {d, composerDir, skillDir} = await setup({root: realRoot.replace(line, line + '\n' + line)});
  try {
    assert.deepEqual([...new Set(ids(await checkIntegrity({composerDir, skillDir})))], ['root-registration']);
    await fs.writeFile(path.join(composerDir, 'src/Root.tsx'), realRoot.replace(line, ''));
    assert.deepEqual([...new Set(ids(await checkIntegrity({composerDir, skillDir})))], ['root-registration']);
    // registered without calculateMetadata
    await fs.writeFile(path.join(composerDir, 'src/Root.tsx'), realRoot.replace('calculateMetadata={calculateYtNewsStyle01V4Metadata}', ''));
    assert.ok(ids(await checkIntegrity({composerDir, skillDir})).includes('root-registration'));
  } finally { await fs.rm(d, {recursive: true}); }
});

test('a locked script that changed (or vanished) is gates-lock; unchanged passes', async () => {
  const sha = sha256Hex('export const locked = 1;\n');
  const {d, composerDir, skillDir} = await setup({lock: {files: {'scripts/locked.mjs': sha}}});
  try {
    const ok = await checkIntegrity({composerDir, skillDir});
    assert.equal(ok.ok, true);
    assert.deepEqual(ok.warnings, []);
    await fs.writeFile(path.join(skillDir, 'scripts/locked.mjs'), 'export const locked = 2;\n');
    const bad = await checkIntegrity({composerDir, skillDir});
    assert.deepEqual(ids(bad), ['gates-lock']);
    assert.match(bad.issues[0].message, /scripts\/locked\.mjs/);
    await fs.rm(path.join(skillDir, 'scripts/locked.mjs'));
    assert.deepEqual(ids(await checkIntegrity({composerDir, skillDir})), ['gates-lock']);
    // alternative list shape and an escaping path
    await fs.writeFile(path.join(skillDir, 'scripts/gates.lock.json'), JSON.stringify({files: [{path: '../../etc/hosts', sha256: 'x'}]}));
    assert.deepEqual(ids(await checkIntegrity({composerDir, skillDir})), ['gates-lock']);
    await fs.writeFile(path.join(skillDir, 'scripts/gates.lock.json'), 'not json');
    assert.deepEqual(ids(await checkIntegrity({composerDir, skillDir})), ['gates-lock']);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('CLI exit codes and --json output', async () => {
  const good = await setup();
  const bad = await setup({engine: reference + '\n// drift\n'});
  const script = path.join(realSkill, 'scripts/gate_integrity.mjs');
  try {
    const ok = await execFileP('node', [script, good.composerDir, '--skill-dir', good.skillDir, '--json']);
    assert.equal(JSON.parse(ok.stdout).ok, true);
    await assert.rejects(execFileP('node', [script, bad.composerDir, '--skill-dir', bad.skillDir]), e => e.code === 3 && /engine-drift/.test(e.stdout));
    await assert.rejects(execFileP('node', [script]), e => e.code === 2);
  } finally {
    await fs.rm(good.d, {recursive: true});
    await fs.rm(bad.d, {recursive: true});
  }
});
