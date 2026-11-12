import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {canonicalJSON, manifestHash, diffManifests, writeJsonAtomic, appendInvocation, readInvocations, buildManifest, sha256Hex, sha256File, computeSourceHashes} from '../qc_manifest.mjs';

const tmp = () => fs.mkdtemp(path.join(os.tmpdir(), 'qc-manifest-'));

test('canonicalJSON is stable under key order, at every depth', () => {
  const a = {b: 1, a: {y: [1, {q: 1, p: 2}], x: null}, c: 'z'};
  const b = {c: 'z', a: {x: null, y: [1, {p: 2, q: 1}]}, b: 1};
  assert.equal(canonicalJSON(a), canonicalJSON(b));
  assert.equal(canonicalJSON(a), '{"a":{"x":null,"y":[1,{"p":2,"q":1}]},"b":1,"c":"z"}');
  assert.equal(manifestHash(a), manifestHash(b));
  assert.notEqual(manifestHash(a), manifestHash({...a, b: 2}));
  // array order is significant
  assert.notEqual(canonicalJSON({k: [1, 2]}), canonicalJSON({k: [2, 1]}));
  // undefined is dropped like JSON.stringify
  assert.equal(canonicalJSON({a: 1, b: undefined}), '{"a":1}');
});

test('diffManifests returns null when equal and names the first differing key', () => {
  const base = buildManifest({runId: 'r', sourceHashes: {'a.ts': '1', 'b.ts': '2'}, mediaDigest: {digest: 'd', files: 2}, thresholdsSha256: 't', planSha256: 'p'});
  assert.equal(diffManifests(base, structuredClone(base)), null);
  assert.equal(diffManifests({...base, sourceHashes: {'a.ts': '1', 'b.ts': 'X'}}, base), 'sourceHashes.b.ts');
  assert.equal(diffManifests({...base, mediaDigest: {digest: 'd2', files: 2}}, base), 'mediaDigest.digest');
  assert.equal(diffManifests({...base, thresholdsSha256: 'zz'}, base), 'thresholdsSha256');
  // first in sorted order wins: mediaDigest < sourceHashes
  assert.equal(diffManifests({...base, mediaDigest: {digest: 'q', files: 2}, sourceHashes: {'a.ts': 'q', 'b.ts': '2'}}, base), 'mediaDigest.digest');
  // key present on one side only
  assert.equal(diffManifests({...base, sourceHashes: {...base.sourceHashes, 'c.ts': '3'}}, base), 'sourceHashes.c.ts');
  assert.equal(diffManifests(base, {...base, sourceHashes: {'a.ts': '1'}}), 'sourceHashes.b.ts');
  // arrays are reported at their own path
  assert.equal(diffManifests({frames: [1, 2]}, {frames: [1, 3]}), 'frames');
});

test('writeJsonAtomic writes a complete file and leaves no tmp file behind', async () => {
  const d = await tmp();
  try {
    const file = path.join(d, 'm.json');
    await writeJsonAtomic(file, {a: 1});
    await writeJsonAtomic(file, {a: 2, b: [1]});
    assert.deepEqual(JSON.parse(await fs.readFile(file, 'utf8')), {a: 2, b: [1]});
    assert.deepEqual(await fs.readdir(d), ['m.json']);
    // a failing write (target directory does not exist) rejects and leaves nothing
    await assert.rejects(writeJsonAtomic(path.join(d, 'missing', 'x.json'), {}));
    assert.deepEqual(await fs.readdir(d), ['m.json']);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('invocations.jsonl round trip; missing file is empty; torn last line is skipped', async () => {
  const d = await tmp();
  try {
    assert.deepEqual(await readInvocations(d), []);
    await appendInvocation(d, {invocationId: 'a', measured: 3});
    await appendInvocation(d, {invocationId: 'b', measured: 0});
    assert.deepEqual(await readInvocations(d), [{invocationId: 'a', measured: 3}, {invocationId: 'b', measured: 0}]);
    await fs.appendFile(path.join(d, 'invocations.jsonl'), '{"invocationId":"c","meas');
    assert.equal((await readInvocations(d)).length, 2);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('sha256File streams the same digest as sha256Hex', async () => {
  const d = await tmp();
  try {
    const f = path.join(d, 'x');
    await fs.writeFile(f, 'hello');
    assert.equal(await sha256File(f), sha256Hex('hello'));
  } finally { await fs.rm(d, {recursive: true}); }
});

test('computeSourceHashes covers data, engine, root, index, qc scripts; optional files are null', async () => {
  const d = await tmp();
  try {
    const composer = path.join(d, 'composer');
    const skill = path.join(d, 'skill');
    await fs.mkdir(path.join(composer, 'src'), {recursive: true});
    await fs.mkdir(path.join(skill, 'assets'), {recursive: true});
    await fs.mkdir(path.join(skill, 'scripts'), {recursive: true});
    const put = (f, t) => fs.writeFile(f, t);
    await put(path.join(composer, 'src/YtNewsStyle01V4.tsx'), 'engine');
    await put(path.join(composer, 'src/Root.tsx'), 'root');
    await put(path.join(composer, 'src/index.tsx'), 'index');
    await put(path.join(composer, 'package-lock.json'), '{}');
    await put(path.join(skill, 'assets/YtNewsStyle01V4.reference.tsx'), 'engine');
    await put(path.join(skill, 'scripts/qc_a.mjs'), 'a');
    await put(path.join(skill, 'scripts/qc_t.json'), '{}');
    await put(path.join(skill, 'scripts/other.mjs'), 'not hashed');
    await put(path.join(d, 'e.json'), '{}');
    await put(path.join(d, 'c.json'), '[]');
    const h = await computeSourceHashes({composerDir: composer, skillDir: skill, episodePath: path.join(d, 'e.json'), captionsPath: path.join(d, 'c.json')});
    assert.deepEqual(Object.keys(h), [...Object.keys(h)].sort());
    for (const k of ['episode.json', 'captions.json', 'src/YtNewsStyle01V4.tsx', 'src/Root.tsx', 'src/index.tsx', 'assets/YtNewsStyle01V4.reference.tsx', 'scripts/qc_a.mjs', 'scripts/qc_t.json', 'remotion-composer/package-lock.json']) {
      assert.match(h[k], /^[0-9a-f]{64}$/, k);
    }
    assert.equal(h['scripts/other.mjs'], undefined);
    assert.equal(h['scripts/gates.lock.json'], null);
    await put(path.join(skill, 'scripts/gates.lock.json'), '{}');
    const h2 = await computeSourceHashes({composerDir: composer, skillDir: skill, episodePath: path.join(d, 'e.json'), captionsPath: path.join(d, 'c.json')});
    assert.equal(diffManifests(h, h2), 'scripts/gates.lock.json');
    await put(path.join(skill, 'scripts/qc_a.mjs'), 'changed');
    const h3 = await computeSourceHashes({composerDir: composer, skillDir: skill, episodePath: path.join(d, 'e.json'), captionsPath: path.join(d, 'c.json')});
    assert.equal(diffManifests(h2, h3), 'scripts/qc_a.mjs');
  } finally { await fs.rm(d, {recursive: true}); }
});
