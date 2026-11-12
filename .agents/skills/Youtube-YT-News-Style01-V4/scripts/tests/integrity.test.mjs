import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {checkIntegrity, EXTERNAL_LOCK_FILES, V4_OWNED_FILES} from '../gate_integrity.mjs';
import {sha256Hex} from '../qc_manifest.mjs';

const execFileP = promisify(execFile);
const here = path.dirname(fileURLToPath(import.meta.url));
const worktree = path.resolve(here, '../../../../..');
const realSkill = path.resolve(here, '../..');
const GUARD = '||box.width<=0||box.height<=0';

const realRoot = await fs.readFile(path.join(worktree, 'remotion-composer/src/Root.tsx'), 'utf8');
const reference = await fs.readFile(path.join(realSkill, 'assets/YtNewsStyle01V4.reference.tsx'), 'utf8');
const entryReference = await fs.readFile(path.join(realSkill, 'assets/ytNewsStyle01V4.entry.reference.tsx'), 'utf8');
const ENTRY_PATH = 'src/ytNewsStyle01V4.entry.tsx';

/** Temp composer + skill: engine and entry identical to their references, the two sample JSONs, and a Root.tsx copied from the real worktree (V4 must not care about it). */
async function setup({engine = reference, entry = entryReference, root = realRoot, lock, repoLayout = false} = {}) {
  const d = await fs.mkdtemp(path.join(os.tmpdir(), 'integrity-'));
  // repoLayout: <d>/repo/.agents/skills/<skill> + <d>/repo/remotion-composer, so the repo root (3 levels above the skill) is <d>/repo
  const composerDir = repoLayout ? path.join(d, 'repo', 'remotion-composer') : path.join(d, 'composer');
  const skillDir = repoLayout ? path.join(d, 'repo', '.agents', 'skills', 'Youtube-YT-News-Style01-V4') : path.join(d, 'skill');
  await fs.mkdir(path.join(composerDir, 'src'), {recursive: true});
  await fs.mkdir(path.join(skillDir, 'assets'), {recursive: true});
  await fs.mkdir(path.join(skillDir, 'scripts'), {recursive: true});
  await fs.writeFile(path.join(composerDir, 'src/YtNewsStyle01V4.tsx'), engine);
  await fs.writeFile(path.join(composerDir, 'src/Root.tsx'), root);
  await fs.writeFile(path.join(composerDir, ENTRY_PATH), entry);
  await fs.writeFile(path.join(composerDir, 'src/ytNewsStyle01V4Sample.json'), '{}');
  await fs.writeFile(path.join(composerDir, 'src/ytNewsStyle01V4SampleCaptions.json'), '[]');
  await fs.writeFile(path.join(skillDir, 'assets/YtNewsStyle01V4.reference.tsx'), reference);
  await fs.writeFile(path.join(skillDir, 'assets/ytNewsStyle01V4.entry.reference.tsx'), entryReference);
  await fs.writeFile(path.join(skillDir, 'scripts/locked.mjs'), 'export const locked = 1;\n');
  if (lock) await fs.writeFile(path.join(skillDir, 'scripts/gates.lock.json'), JSON.stringify(lock));
  return {d, composerDir, skillDir, repoRoot: path.join(d, 'repo')};
}
const ids = r => r.issues.map(i => i.id);
const uniqueIdsOf = r => [...new Set(ids(r))];

test('the engine guard that went missing in the V3 incident exists in the reference engine', () => {
  assert.ok(reference.includes(GUARD), 'reference engine has the box.width/height guard');
});

test('identical engine and entry pass (Root.tsx is not looked at); missing lock is only a warning and lock.status "missing"', async () => {
  const {d, composerDir, skillDir} = await setup();
  try {
    const r = await checkIntegrity({composerDir, skillDir});
    assert.deepEqual(r.issues, []);
    assert.equal(r.ok, true);
    assert.deepEqual(r.warnings.map(w => w.id), ['gates-lock-missing']);
    assert.deepEqual(r.lock, {status: 'missing', sha256: null, files: null, external: null});
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
    // the entry cannot resolve its engine import either
    assert.deepEqual(uniqueIdsOf(await checkIntegrity({composerDir, skillDir})), ['engine-drift', 'entry-closure']);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('a broken, empty or missing Root.tsx / index.tsx does not matter to the integrity check', async () => {
  const {d, composerDir, skillDir} = await setup({root: 'export const Root = ((( broken\nimport "./does-not-exist";\n'});
  try {
    assert.deepEqual(ids(await checkIntegrity({composerDir, skillDir})), []);
    await fs.rm(path.join(composerDir, 'src/Root.tsx'));
    assert.deepEqual(ids(await checkIntegrity({composerDir, skillDir})), []);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('entry differing from its reference copy (or missing) is entry-drift', async () => {
  const {d, composerDir, skillDir} = await setup({entry: entryReference.replace('fps={25}', 'fps={30}')});
  try {
    assert.ok(ids(await checkIntegrity({composerDir, skillDir})).includes('entry-drift'));
    await fs.rm(path.join(composerDir, ENTRY_PATH));
    assert.deepEqual(ids(await checkIntegrity({composerDir, skillDir})), ['entry-drift']);
  } finally { await fs.rm(d, {recursive: true}); }
});

/** An entry that is changed together with its reference copy (so there is no drift): only the structural checks can catch it. */
async function withEntry(entry, fn) {
  const {d, composerDir, skillDir} = await setup({entry});
  try {
    await fs.writeFile(path.join(skillDir, 'assets/ytNewsStyle01V4.entry.reference.tsx'), entry);
    return await fn({composerDir, skillDir});
  } finally { await fs.rm(d, {recursive: true}); }
}
const uniqueIds = r => [...new Set(ids(r))];

test('entry registering two compositions, none, another id, or a second registerRoot is entry-registration', async () => {
  const line = entryReference.split('\n').find(l => l.includes('<Composition id="YtNewsStyle01V4"'));
  assert.ok(line);
  await withEntry(entryReference.replace(line, line + '\n' + line), async env => assert.deepEqual(uniqueIds(await checkIntegrity(env)), ['entry-registration']));
  await withEntry(entryReference.replace(line, ''), async env => assert.deepEqual(uniqueIds(await checkIntegrity(env)), ['entry-registration']));
  await withEntry(entryReference.replace('id="YtNewsStyle01V4"', 'id="YtNewsStyle01V3"'), async env => assert.deepEqual(uniqueIds(await checkIntegrity(env)), ['entry-registration']));
  await withEntry(entryReference.replace('calculateMetadata={calculateYtNewsStyle01V4Metadata}', ''), async env => assert.deepEqual(uniqueIds(await checkIntegrity(env)), ['entry-registration']));
  await withEntry(entryReference + '\nregisterRoot(YtNewsStyle01V4Root);\n', async env => assert.deepEqual(uniqueIds(await checkIntegrity(env)), ['entry-registration']));
  // a mention in a comment does not count
  await withEntry(entryReference + '\n// <Composition id="Other" registerRoot(x)\n', async env => assert.deepEqual((await checkIntegrity(env)).issues, []));
});

test('entry importing Root.tsx, index.tsx or any other pipeline file is entry-closure; an unresolvable import too', async () => {
  for (const specifier of ['./Root', './index', './YtNewsStyle01V3']) {
    const {d, composerDir, skillDir} = await setup({entry: entryReference + `\nimport "${specifier}";\n`});
    try {
      await fs.writeFile(path.join(composerDir, 'src/Root.tsx'), 'export const Root = null;\n');   // small enough to resolve
      await fs.writeFile(path.join(composerDir, 'src/index.tsx'), 'export {};\n');
      await fs.writeFile(path.join(composerDir, 'src/YtNewsStyle01V3.tsx'), 'export {};\n');
      await fs.writeFile(path.join(skillDir, 'assets/ytNewsStyle01V4.entry.reference.tsx'), entryReference + `\nimport "${specifier}";\n`);
      const r = await checkIntegrity({composerDir, skillDir});
      assert.deepEqual(uniqueIds(r), ['entry-closure'], specifier);
      assert.match(r.issues[0].message, /not V4-owned/);
    } finally { await fs.rm(d, {recursive: true}); }
  }
  await withEntry(entryReference + '\nimport "./nope";\n', async env => {
    const r = await checkIntegrity(env);
    assert.deepEqual(uniqueIds(r), ['entry-closure']);
    assert.match(r.issues[0].message, /cannot be resolved/);
  });
});

test('an import that the engine would pull in from another pipeline file is entry-closure (transitive)', async () => {
  const {d, composerDir, skillDir} = await setup({engine: reference + '\nimport "./other";\n'});
  try {
    await fs.writeFile(path.join(composerDir, 'src/other.ts'), 'export {};\n');
    await fs.writeFile(path.join(skillDir, 'assets/YtNewsStyle01V4.reference.tsx'), reference + '\nimport "./other";\n');
    const r = await checkIntegrity({composerDir, skillDir});
    assert.deepEqual(uniqueIds(r), ['entry-closure']);
    assert.match(r.issues[0].message, /src\/other\.ts/);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('EXTERNAL_LOCK_FILES = the V4-owned composer files, repo-relative; --list-external prints them one per line', async () => {
  assert.deepEqual([...EXTERNAL_LOCK_FILES], V4_OWNED_FILES.map(f => `remotion-composer/${f}`));
  assert.ok(EXTERNAL_LOCK_FILES.includes('remotion-composer/src/ytNewsStyle01V4.entry.tsx'));
  assert.ok(!EXTERNAL_LOCK_FILES.some(f => /Root\.tsx|index\.tsx/.test(f)));
  const {stdout} = await execFileP(process.execPath, [path.join(realSkill, 'scripts/gate_integrity.mjs'), '--list-external']);
  assert.equal(stdout, EXTERNAL_LOCK_FILES.join('\n') + '\n');
  for (const rel of EXTERNAL_LOCK_FILES) await fs.access(path.join(worktree, rel));
});

const LOCKED = 'export const locked = 1;\n';
const goodLock = (files = {'scripts/locked.mjs': sha256Hex(LOCKED)}) => ({schema: 'yt-news-v4-gates-lock', version: 1, skill: 'Youtube-YT-News-Style01-V4', files});
const writeLockRaw = (skillDir, text) => fs.writeFile(path.join(skillDir, 'scripts/gates.lock.json'), text);

test('lock ok: matching files pass, lock.status "ok", sha256 of the lock file and the file count', async () => {
  const lock = goodLock();
  const {d, composerDir, skillDir} = await setup({lock});
  try {
    const r = await checkIntegrity({composerDir, skillDir});
    assert.equal(r.ok, true);
    assert.deepEqual(r.issues, []);
    assert.deepEqual(r.warnings, []);
    assert.deepEqual(r.lock, {status: 'ok', sha256: sha256Hex(JSON.stringify(lock)), files: 1, external: 0});
    // requireLock does not change a good lock
    assert.equal((await checkIntegrity({composerDir, skillDir, requireLock: true})).ok, true);
    // an empty "files" object is a valid (if pointless) lock
    await writeLockRaw(skillDir, JSON.stringify(goodLock({})));
    assert.deepEqual((await checkIntegrity({composerDir, skillDir})).lock.status, 'ok');
  } finally { await fs.rm(d, {recursive: true}); }
});

test('missing lock + requireLock is the issue gates-lock-missing (no warning); without it only a warning', async () => {
  const {d, composerDir, skillDir} = await setup();
  try {
    const r = await checkIntegrity({composerDir, skillDir, requireLock: true});
    assert.equal(r.ok, false);
    assert.deepEqual(ids(r), ['gates-lock-missing']);
    assert.deepEqual(r.warnings, []);
    assert.deepEqual(r.lock, {status: 'missing', sha256: null, files: null, external: null});
    assert.equal((await checkIntegrity({composerDir, skillDir, requireLock: false})).ok, true);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('gates-lock-format: wrong schema, wrong version, wrong skill, files not an object of hex strings, unknown key, not JSON', async () => {
  const {d, composerDir, skillDir} = await setup({lock: goodLock()});
  try {
    const bads = {
      'wrong schema': {...goodLock(), schema: 'other'},
      'missing schema': (({schema, ...rest}) => rest)(goodLock()),
      'version 2': {...goodLock(), version: 2},
      'version string': {...goodLock(), version: '1'},
      'wrong skill': {...goodLock(), skill: 'Youtube-YT-News-Style01-V3'},
      'files array': {...goodLock(), files: [{path: 'scripts/locked.mjs', sha256: sha256Hex(LOCKED)}]},
      'files missing': (({files, ...rest}) => rest)(goodLock()),
      'files null': {...goodLock(), files: null},
      'value not a string': goodLock({'scripts/locked.mjs': {sha256: sha256Hex(LOCKED)}}),
      'value not hex': goodLock({'scripts/locked.mjs': 'zz'.repeat(32)}),
      'value too short': goodLock({'scripts/locked.mjs': 'abc'}),
      'value upper case': goodLock({'scripts/locked.mjs': sha256Hex(LOCKED).toUpperCase()}),
      'unknown top-level key': {...goodLock(), generatedAt: 'now'},
      'external as array': {...goodLock(), external: []},
      'external null': {...goodLock(), external: null},
      'old flat map': {'scripts/locked.mjs': sha256Hex(LOCKED)},
      'array': [],
    };
    for (const [name, lock] of Object.entries(bads)) {
      await writeLockRaw(skillDir, JSON.stringify(lock));
      const r = await checkIntegrity({composerDir, skillDir});
      assert.deepEqual(ids(r), ['gates-lock-format'], name);
      assert.equal(r.ok, false, name);
      assert.equal(r.lock.status, 'invalid', name);
      assert.equal(r.lock.sha256, sha256Hex(JSON.stringify(lock)), name);
      assert.equal(r.lock.files, null, name);
    }
    await writeLockRaw(skillDir, 'not json');
    const r = await checkIntegrity({composerDir, skillDir});
    assert.deepEqual(ids(r), ['gates-lock-format']);
    assert.equal(r.lock.status, 'invalid');
    // requireLock does not turn an invalid lock into something else
    assert.deepEqual(ids(await checkIntegrity({composerDir, skillDir, requireLock: true})), ['gates-lock-format']);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('gates-lock-format: absolute paths, paths that escape the skill folder, the lock itself and __pycache__', async () => {
  const sha = sha256Hex(LOCKED);
  const {d, composerDir, skillDir} = await setup({lock: goodLock()});
  try {
    const paths = ['/etc/hosts', '../outside.mjs', 'scripts/../../outside.mjs', '../../etc/hosts', 'scripts\\locked.mjs', '',
      'scripts/gates.lock.json', './scripts/gates.lock.json', 'scripts/__pycache__/x.pyc', '__pycache__/y.pyc'];
    for (const rel of paths) {
      await writeLockRaw(skillDir, JSON.stringify(goodLock({'scripts/locked.mjs': sha, [rel]: sha})));
      const r = await checkIntegrity({composerDir, skillDir});
      assert.deepEqual(ids(r), ['gates-lock-format'], JSON.stringify(rel));
      assert.equal(r.lock.status, 'invalid', JSON.stringify(rel));
    }
  } finally { await fs.rm(d, {recursive: true}); }
});

test('gates-lock: a changed or vanished locked file; status "mismatch" and the message lists the paths', async () => {
  const lock = goodLock();
  const {d, composerDir, skillDir} = await setup({lock});
  try {
    await fs.writeFile(path.join(skillDir, 'scripts/locked.mjs'), 'export const locked = 2;\n');
    const changed = await checkIntegrity({composerDir, skillDir});
    assert.deepEqual(ids(changed), ['gates-lock']);
    assert.match(changed.issues[0].message, /scripts\/locked\.mjs \(changed\)/);
    assert.deepEqual(changed.lock, {status: 'mismatch', sha256: sha256Hex(JSON.stringify(lock)), files: 1, external: 0});
    await fs.rm(path.join(skillDir, 'scripts/locked.mjs'));
    const gone = await checkIntegrity({composerDir, skillDir});
    assert.deepEqual(ids(gone), ['gates-lock']);
    assert.match(gone.issues[0].message, /scripts\/locked\.mjs \(missing\)/);
    assert.equal(gone.lock.status, 'mismatch');
    assert.equal(gone.ok, false);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('gates-lock: the message lists at most 10 paths, with the rest counted', async () => {
  const files = {};
  for (let i = 0; i < 13; i++) files[`scripts/gone-${String(i).padStart(2, '0')}.mjs`] = sha256Hex(`x${i}`);
  const {d, composerDir, skillDir} = await setup({lock: goodLock(files)});
  try {
    const r = await checkIntegrity({composerDir, skillDir});
    assert.deepEqual(ids(r), ['gates-lock']);
    const message = r.issues[0].message;
    assert.match(message, /^13 locked file\(s\) missing or changed/);
    assert.equal(message.match(/gone-\d\d\.mjs/g).length, 10);
    assert.match(message, /\+3 more/);
  } finally { await fs.rm(d, {recursive: true}); }
});

// ---- "external": files outside the skill folder, repo-relative (gates_lock.py always writes this key) ---------------
const ENGINE_REL = 'remotion-composer/src/YtNewsStyle01V4.tsx';
const externalLock = (external, files) => ({...goodLock(files), external});

test('external ok: engine hash matches, lock.external counts the entries, a lock written by gates_lock.py (indent=2 + newline) is accepted', async () => {
  const lock = externalLock({[ENGINE_REL]: sha256Hex(reference)});
  const {d, composerDir, skillDir} = await setup({repoLayout: true});
  try {
    const text = JSON.stringify(lock, null, 2) + '\n';
    await writeLockRaw(skillDir, text);
    const r = await checkIntegrity({composerDir, skillDir});
    assert.deepEqual(r.issues, []);
    assert.deepEqual(r.lock, {status: 'ok', sha256: sha256Hex(text), files: 1, external: 1});
    // an empty external object is fine; so is no external key at all (external: 0)
    await writeLockRaw(skillDir, JSON.stringify(externalLock({})));
    assert.deepEqual(r.lock.status === 'ok' && (await checkIntegrity({composerDir, skillDir})).lock.external, 0);
    await writeLockRaw(skillDir, JSON.stringify(goodLock()));
    const absent = await checkIntegrity({composerDir, skillDir});
    assert.deepEqual([absent.lock.status, absent.lock.files, absent.lock.external], ['ok', 1, 0]);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('external changed or missing: gates-lock with an "external:" marker, status mismatch; skill files and external entries are reported together', async () => {
  const {d, composerDir, skillDir, repoRoot} = await setup({repoLayout: true, lock: externalLock({[ENGINE_REL]: sha256Hex(reference), 'remotion-composer/src/Root.tsx': sha256Hex(realRoot)})});
  try {
    assert.equal((await checkIntegrity({composerDir, skillDir})).lock.status, 'ok');
    await fs.writeFile(path.join(repoRoot, ENGINE_REL), reference + '// changed\n');
    const changed = await checkIntegrity({composerDir, skillDir});
    assert.deepEqual(ids(changed).sort(), ['engine-drift', 'gates-lock']);
    const issue = changed.issues.find(i => i.id === 'gates-lock');
    assert.match(issue.message, /external:remotion-composer\/src\/YtNewsStyle01V4\.tsx \(changed\)/);
    assert.doesNotMatch(issue.message, /Root\.tsx/);
    assert.deepEqual([changed.lock.status, changed.lock.files, changed.lock.external], ['mismatch', 1, 2]);
    await fs.rm(path.join(repoRoot, 'remotion-composer/src/Root.tsx'));
    await fs.writeFile(path.join(skillDir, 'scripts/locked.mjs'), 'export const locked = 9;\n');
    const message = (await checkIntegrity({composerDir, skillDir})).issues.find(i => i.id === 'gates-lock').message;
    assert.match(message, /^3 locked file\(s\) missing or changed/);
    assert.match(message, /scripts\/locked\.mjs \(changed\)/);
    assert.match(message, /external:remotion-composer\/src\/Root\.tsx \(missing\)/);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('external bad shape: absolute path, ".." segment, empty path, backslash, non-hex value, non-object, extra top-level key are gates-lock-format', async () => {
  const good = sha256Hex(reference);
  const {d, composerDir, skillDir} = await setup({repoLayout: true});
  try {
    const bads = {
      absolute: externalLock({'/etc/hosts': good}),
      'dotdot first': externalLock({'../outside.tsx': good}),
      'dotdot inside': externalLock({'remotion-composer/../../outside.tsx': good}),
      'dotdot harmless': externalLock({'remotion-composer/src/../src/YtNewsStyle01V4.tsx': good}),
      empty: externalLock({'': good}),
      backslash: externalLock({'remotion-composer\\src\\x.tsx': good}),
      'value not hex': externalLock({[ENGINE_REL]: 'xyz'}),
      'value upper case': externalLock({[ENGINE_REL]: good.toUpperCase()}),
      'value object': externalLock({[ENGINE_REL]: {sha256: good}}),
      'external list': externalLock([ENGINE_REL]),
      'other key next to external': {...externalLock({[ENGINE_REL]: good}), generatedAt: 'now'},
    };
    for (const [name, lock] of Object.entries(bads)) {
      await writeLockRaw(skillDir, JSON.stringify(lock));
      const r = await checkIntegrity({composerDir, skillDir});
      assert.deepEqual(ids(r), ['gates-lock-format'], name);
      assert.deepEqual([r.lock.status, r.lock.files, r.lock.external], ['invalid', null, null], name);
    }
  } finally { await fs.rm(d, {recursive: true}); }
});

test('gates-lock: engine drift and a lock mismatch are reported together, each with its own id', async () => {
  const {d, composerDir, skillDir} = await setup({engine: reference + '\n// drift\n', lock: goodLock({'scripts/locked.mjs': sha256Hex('other')})});
  try {
    assert.deepEqual(ids(await checkIntegrity({composerDir, skillDir})).sort(), ['engine-drift', 'gates-lock']);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('CLI exit codes, --json output (with the lock block) and --require-lock', async () => {
  const good = await setup();
  const bad = await setup({engine: reference + '\n// drift\n'});
  const locked = await setup({lock: goodLock()});
  const script = path.join(realSkill, 'scripts/gate_integrity.mjs');
  try {
    const ok = JSON.parse((await execFileP('node', [script, good.composerDir, '--skill-dir', good.skillDir, '--json'])).stdout);
    assert.equal(ok.ok, true);
    assert.deepEqual(ok.lock, {status: 'missing', sha256: null, files: null, external: null});
    assert.deepEqual(ok.warnings.map(w => w.id), ['gates-lock-missing']);
    await assert.rejects(execFileP('node', [script, good.composerDir, '--skill-dir', good.skillDir, '--require-lock', '--json']), e => {
      const out = JSON.parse(e.stdout);
      return e.code === 3 && out.ok === false && out.issues[0].id === 'gates-lock-missing' && out.lock.status === 'missing';
    });
    const withLock = JSON.parse((await execFileP('node', [script, locked.composerDir, '--skill-dir', locked.skillDir, '--require-lock', '--json'])).stdout);
    assert.deepEqual([withLock.ok, withLock.lock.status, withLock.lock.files], [true, 'ok', 1]);
    await assert.rejects(execFileP('node', [script, bad.composerDir, '--skill-dir', bad.skillDir]), e => e.code === 3 && /engine-drift/.test(e.stdout));
    await assert.rejects(execFileP('node', [script]), e => e.code === 2);
  } finally {
    for (const w of [good, bad, locked]) await fs.rm(w.d, {recursive: true});
  }
});
