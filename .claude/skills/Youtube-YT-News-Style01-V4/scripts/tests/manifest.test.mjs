import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {canonicalJSON, manifestHash, diffManifests, writeJsonAtomic, appendInvocation, readInvocations, buildManifest, sha256Hex, sha256File, computeSourceHashes, computeBundleCodeKey, computeImportClosure, relativeSpecifiers, ENTRY_REL, entryPointOf} from '../qc_manifest.mjs';

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

test('computeSourceHashes covers data, engine, entry + closure, qc scripts; optional files are null; Root.tsx / index.tsx are not hashed', async () => {
  const d = await tmp();
  try {
    const composer = path.join(d, 'composer');
    const skill = path.join(d, 'skill');
    await fs.mkdir(path.join(composer, 'src'), {recursive: true});
    await fs.mkdir(path.join(skill, 'assets'), {recursive: true});
    await fs.mkdir(path.join(skill, 'scripts'), {recursive: true});
    const put = (f, t) => fs.writeFile(f, t);
    await put(path.join(composer, 'src/YtNewsStyle01V4.tsx'), 'engine');
    await put(path.join(composer, 'src/ytNewsStyle01V4.entry.tsx'), 'import {YtNewsStyle01V4} from "./YtNewsStyle01V4";\nimport sample from "./ytNewsStyle01V4Sample.json";\n');
    await put(path.join(composer, 'src/ytNewsStyle01V4Sample.json'), '{}');
    await put(path.join(composer, 'src/Root.tsx'), 'root');
    await put(path.join(composer, 'src/index.tsx'), 'index');
    await put(path.join(composer, 'package-lock.json'), '{}');
    await put(path.join(skill, 'assets/YtNewsStyle01V4.reference.tsx'), 'engine');
    await put(path.join(skill, 'assets/ytNewsStyle01V4.entry.reference.tsx'), 'entry');
    await put(path.join(skill, 'scripts/qc_a.mjs'), 'a');
    await put(path.join(skill, 'scripts/qc_t.json'), '{}');
    await put(path.join(skill, 'scripts/other.mjs'), 'not hashed');
    await put(path.join(d, 'e.json'), '{}');
    await put(path.join(d, 'c.json'), '[]');
    const h = await computeSourceHashes({composerDir: composer, skillDir: skill, episodePath: path.join(d, 'e.json'), captionsPath: path.join(d, 'c.json')});
    assert.deepEqual(Object.keys(h), [...Object.keys(h)].sort());
    for (const k of ['episode.json', 'captions.json', 'src/YtNewsStyle01V4.tsx', 'src/ytNewsStyle01V4.entry.tsx', 'src/ytNewsStyle01V4Sample.json', 'assets/YtNewsStyle01V4.reference.tsx', 'assets/ytNewsStyle01V4.entry.reference.tsx', 'scripts/qc_a.mjs', 'scripts/qc_t.json', 'remotion-composer/package-lock.json']) {
      assert.match(h[k], /^[0-9a-f]{64}$/, k);
    }
    assert.equal(h['scripts/other.mjs'], undefined);
    assert.equal(h['src/Root.tsx'], undefined);
    assert.equal(h['src/index.tsx'], undefined);
    assert.deepEqual(Object.keys(h).filter(k => k.startsWith('src/')), ['src/YtNewsStyle01V4.tsx', 'src/ytNewsStyle01V4.entry.tsx', 'src/ytNewsStyle01V4Sample.json']);
    assert.equal(h['scripts/gates.lock.json'], null);
    await put(path.join(skill, 'scripts/gates.lock.json'), '{}');
    const h2 = await computeSourceHashes({composerDir: composer, skillDir: skill, episodePath: path.join(d, 'e.json'), captionsPath: path.join(d, 'c.json')});
    assert.equal(diffManifests(h, h2), 'scripts/gates.lock.json');
    await put(path.join(skill, 'scripts/qc_a.mjs'), 'changed');
    const h3 = await computeSourceHashes({composerDir: composer, skillDir: skill, episodePath: path.join(d, 'e.json'), captionsPath: path.join(d, 'c.json')});
    assert.equal(diffManifests(h2, h3), 'scripts/qc_a.mjs');
  } finally { await fs.rm(d, {recursive: true}); }
});

// ---------------------------------------------------------------------------------------------
// import closure of the V4 entry (CF-A66)
// ---------------------------------------------------------------------------------------------

async function makeComposer(files) {
  const d = await tmp();
  const composer = path.join(d, 'composer');
  for (const [rel, text] of Object.entries(files)) {
    await fs.mkdir(path.dirname(path.join(composer, rel)), {recursive: true});
    await fs.writeFile(path.join(composer, rel), text);
  }
  return {d, composer};
}

test('relativeSpecifiers: static, side-effect, re-export, multi-line, dynamic and require forms; packages, comments and non-relative strings are ignored', () => {
  const text = [
    'import React from "react";',
    'import {a} from "./a";',
    'import b, {',
    '  c,',
    '  d,',
    "} from '../lib/b';",
    'import "./side";',
    'import type {T} from "./types";',
    'export {x} from "./re";',
    'export * from "./star";',
    '// import {z} from "./commented";',
    ' * import {y} from "./doc";',
    'const lazy = () => import("./lazy");',
    'const r = require("./req");',
    'const s = "from ./not-an-import";',
    'import json from "./data.json";',
  ].join('\n');
  assert.deepEqual(relativeSpecifiers(text).sort(), ['../lib/b', './a', './data.json', './lazy', './re', './req', './side', './star', './types']);
});

test('computeImportClosure follows relative imports transitively (ts, tsx, json, css, index files), sorted, and starts at the entry', async () => {
  const {d, composer} = await makeComposer({
    [ENTRY_REL]: 'import {E} from "./YtNewsStyle01V4";\nimport s from "./sample.json";\nimport "./theme.css";\nimport "./lib";\nimport "react";\n',
    'src/YtNewsStyle01V4.tsx': 'import {h} from "./helpers/h";\nexport const E = 1;\n',
    'src/helpers/h.ts': 'import {g} from "../shared/g.tsx";\nexport const h = g;\n',
    'src/shared/g.tsx': 'export const g = 1;\n',
    'src/sample.json': '{"import": "./unrelated"}',
    'src/theme.css': '@import "./other.css";',
    'src/lib/index.ts': 'export {};\n',
    'src/Root.tsx': 'import "./Explainer";\n',
    'src/Explainer.tsx': 'export {};\n',
  });
  try {
    assert.deepEqual(await computeImportClosure({composerDir: composer}), [
      ENTRY_REL, 'src/YtNewsStyle01V4.tsx', 'src/helpers/h.ts', 'src/lib/index.ts', 'src/sample.json', 'src/shared/g.tsx', 'src/theme.css',
    ].sort());
    assert.equal(entryPointOf(composer), path.join(composer, ENTRY_REL));
  } finally { await fs.rm(d, {recursive: true}); }
});

test('computeImportClosure handles import cycles, and refuses an unresolvable import or one that leaves src/ (never silently misses a file)', async () => {
  const {d, composer} = await makeComposer({
    [ENTRY_REL]: 'import "./a";\n', 'src/a.ts': 'import "./b";\n', 'src/b.ts': 'import "./a";\n',
  });
  try {
    assert.deepEqual(await computeImportClosure({composerDir: composer}), [ENTRY_REL, 'src/a.ts', 'src/b.ts'].sort());
    await fs.writeFile(path.join(composer, 'src/b.ts'), 'import "./missing";\n');
    await assert.rejects(computeImportClosure({composerDir: composer}), /"\.\/missing" in b\.ts cannot be resolved/);
    await fs.mkdir(path.join(composer, 'public'));
    await fs.writeFile(path.join(composer, 'public/x.json'), '{}');
    await fs.writeFile(path.join(composer, 'src/b.ts'), 'import "../public/x.json";\n');
    await assert.rejects(computeImportClosure({composerDir: composer}), /outside the composer src folder/);
    await fs.rm(path.join(composer, ENTRY_REL));
    await assert.rejects(computeImportClosure({composerDir: composer}), /cannot read src\/ytNewsStyle01V4\.entry\.tsx/);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('the bundle key and the source hashes ignore unrelated files under src/ (Root.tsx, other pipelines), and change when a closure file changes', async () => {
  const {d, composer} = await makeComposer({
    [ENTRY_REL]: 'import "./YtNewsStyle01V4";\nimport "./s.json";\n',
    'src/YtNewsStyle01V4.tsx': 'engine', 'src/s.json': '{}',
    'src/Root.tsx': 'root', 'src/index.tsx': 'index', 'src/Other.tsx': 'other',
    'package-lock.json': '{}',
  });
  try {
    const key = () => computeBundleCodeKey({composerDir: composer});
    const base = await key();
    assert.match(base, /^[0-9a-f]{64}$/);
    await fs.appendFile(path.join(composer, 'src/Root.tsx'), '\n// another pipeline registered a composition (((\nimport "./nope";');
    await fs.appendFile(path.join(composer, 'src/index.tsx'), '\n// edit');
    await fs.appendFile(path.join(composer, 'src/Other.tsx'), '\n// edit');
    await fs.writeFile(path.join(composer, 'src/NewPipeline.tsx'), 'new');
    await fs.rm(path.join(composer, 'src/Root.tsx'));
    assert.equal(await key(), base, 'unrelated src files do not change the key');
    for (const file of ['src/s.json', 'src/YtNewsStyle01V4.tsx', ENTRY_REL, 'package-lock.json']) {
      const before = await fs.readFile(path.join(composer, file), 'utf8');
      await fs.writeFile(path.join(composer, file), before + ' ');
      assert.notEqual(await key(), base, `${file} must change the key`);
      await fs.writeFile(path.join(composer, file), before);
      assert.equal(await key(), base);
    }
  } finally { await fs.rm(d, {recursive: true}); }
});
