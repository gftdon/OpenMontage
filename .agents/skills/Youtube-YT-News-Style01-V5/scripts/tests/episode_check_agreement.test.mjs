// The engine-side check (checkEpisodeMinimal, in the composition) and the schema validator (episode_schema.mjs)
// must agree: the engine is never stricter, and it rejects every case the corpus marks engineMustReject.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadSchema, validateEpisode } from '../episode_schema.mjs';
import { loadEngine } from './_engine_bundle.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FX = path.join(HERE, 'fixtures/episodes');
const readJson = (p) => JSON.parse(fs.readFileSync(p, 'utf8'));
const list = (dir) => fs.readdirSync(path.join(FX, dir)).filter((f) => f.endsWith('.json')).sort();
const validCaptionsFor = (file) => (file === 'sample-v1.json' ? 'sample-captions.json' : 'min-captions.json');
const captions = (name) => readJson(path.join(FX, 'captions', name));

const engine = await loadEngine();

const corpus = [
  ...list('valid').map((file) => ({ file: `valid/${file}`, valid: true, ep: readJson(path.join(FX, 'valid', file)), cap: captions(validCaptionsFor(file)) })),
  ...list('invalid').map((file) => {
    const ep = readJson(path.join(FX, 'invalid', file));
    const expect = ep._expect; delete ep._expect;
    return { file: `invalid/${file}`, valid: false, ep, cap: captions(expect.captions || 'min-captions.json'), expect };
  }),
];

test('the corpus is loaded (valid + invalid)', () => {
  assert.ok(corpus.filter((c) => c.valid).length >= 3);
  assert.ok(corpus.filter((c) => !c.valid).length >= 60);
});

test('valid files pass both the schema and the engine check', () => {
  for (const c of corpus.filter((x) => x.valid)) {
    assert.deepEqual(validateEpisode(c.ep, c.cap).errors, [], `${c.file}: schema`);
    assert.deepEqual(engine.checkEpisodeMinimal(c.ep, c.cap), [], `${c.file}: engine`);
  }
});

test('the schema rejects every invalid file with its expected rule', () => {
  for (const c of corpus.filter((x) => !x.valid)) {
    const r = validateEpisode(c.ep, c.cap);
    assert.equal(r.valid, false, `${c.file} must be schema-invalid`);
    assert.ok(r.errors.some((e) => e.rule === c.expect.rule && e.path.startsWith(c.expect.path)), `${c.file}: expected ${c.expect.rule} at ${c.expect.path}`);
  }
});

test('the engine rejects every file marked engineMustReject', () => {
  const marked = corpus.filter((x) => !x.valid && x.expect.engineMustReject);
  assert.ok(marked.length >= 10);
  for (const c of marked) assert.ok(engine.checkEpisodeMinimal(c.ep, c.cap).length > 0, `${c.file}: engine accepted it`);
});

test('engine rejects => schema rejects, for every sample (the engine is never stricter)', () => {
  for (const c of corpus) {
    const engineErrors = engine.checkEpisodeMinimal(c.ep, c.cap);
    if (engineErrors.length) assert.equal(validateEpisode(c.ep, c.cap).valid, false, `${c.file}: engine says ${engineErrors[0]} but the schema accepts it`);
  }
});

test('V4_EPISODE_KEYS and V4_BEAT_KEYS equal the schema property keys (drift guard)', () => {
  const { schema } = loadSchema();
  assert.deepEqual([...engine.V4_EPISODE_KEYS].sort(), Object.keys(schema.properties).sort());
  assert.deepEqual([...engine.V4_BEAT_KEYS].sort(), Object.keys(schema.$defs.beat.properties).sort());
});

test('the caption hash is compared with captions.inputSha256', () => {
  const c = corpus.find((x) => x.file === 'valid/min-3-beat.json');
  assert.deepEqual(engine.checkEpisodeMinimal(c.ep, c.cap), []);
  assert.ok(engine.checkEpisodeMinimal(c.ep, { ...c.cap, inputSha256: '0'.repeat(64) }).some((e) => /captionsInputSha256/.test(e)));
});
