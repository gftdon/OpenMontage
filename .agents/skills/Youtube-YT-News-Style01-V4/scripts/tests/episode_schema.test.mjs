import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import {
  loadSchema, assertSupportedSchema, validateAgainstSchema, validateEpisode, projectCaptions, runCli, graphemes,
} from '../episode_schema.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT = path.resolve(HERE, '../episode_schema.mjs');
const FX = path.join(HERE, 'fixtures/episodes');
const clone = (o) => JSON.parse(JSON.stringify(o));
const readJson = (p) => JSON.parse(fs.readFileSync(p, 'utf8'));
const listJson = (dir) => fs.readdirSync(path.join(FX, dir)).filter((f) => f.endsWith('.json')).sort();

// Convention shared with the other consumers of this corpus:
//   an invalid file carries "_expect": {rule, path, engineMustReject, captions?}; the captions file lives in
//   captions/ (default min-captions.json). Valid files: sample-v1.json uses sample-captions.json, all others min-captions.json.
const validCaptionsFor = (file) => (file === 'sample-v1.json' ? 'sample-captions.json' : 'min-captions.json');
const captions = (name) => readJson(path.join(FX, 'captions', name));
const minCaptions = () => captions('min-captions.json');
const baseMin = () => readJson(path.join(FX, 'valid/min-3-beat.json'));
const baseVar = () => readJson(path.join(FX, 'valid/variants-and-carryover.json'));

// ---------------------------------------------------------------------------
// Corpus
// ---------------------------------------------------------------------------

test('every valid corpus file validates with zero errors', () => {
  for (const file of listJson('valid')) {
    const r = validateEpisode(readJson(path.join(FX, 'valid', file)), captions(validCaptionsFor(file)));
    assert.deepEqual(r.errors, [], `${file}: ${JSON.stringify(r.errors)}`);
    assert.equal(r.valid, true, file);
  }
});

test('the sample episode has the expected shape and no S19 "not checked" warning', () => {
  const ep = readJson(path.join(FX, 'valid/sample-v1.json'));
  assert.equal(ep.beats.length, 56);
  assert.equal(ep.captionsInputSha256, captions('sample-captions.json').inputSha256);
  const r = validateEpisode(ep, captions('sample-captions.json'));
  assert.equal(r.warnings.some((w) => w.rule === 'S19'), false);
});

test('every invalid corpus file is rejected with its expected rule at its expected path', () => {
  const files = listJson('invalid');
  assert.ok(files.length >= 60, `expected a large invalid corpus, got ${files.length}`);
  for (const file of files) {
    const ep = readJson(path.join(FX, 'invalid', file));
    const expect = ep._expect;
    delete ep._expect;
    assert.ok(expect && expect.rule && expect.path !== undefined && typeof expect.engineMustReject === 'boolean', `${file}: bad _expect`);
    const r = validateEpisode(ep, captions(expect.captions || 'min-captions.json'));
    assert.equal(r.valid, false, `${file} should be invalid`);
    const hit = r.errors.find((e) => e.rule === expect.rule && e.path.startsWith(expect.path));
    assert.ok(hit, `${file}: wanted ${expect.rule} at ${expect.path}, got ${JSON.stringify(r.errors.map((e) => [e.rule, e.path]))}`);
  }
});

test('the invalid corpus keeps at least one proof per semantic rule', () => {
  const rules = new Set(listJson('invalid').map((f) => readJson(path.join(FX, 'invalid', f))._expect.rule));
  for (const id of ['S01', 'S02', 'S03', 'S04', 'S05', 'S06', 'S07', 'S08', 'S09', 'S10', 'S11', 'S12', 'S13', 'S14', 'S15', 'S19', 'S20']) {
    assert.ok(rules.has(id), `no invalid file for ${id}`);
  }
  // the schema-level rules named in the task
  for (const id of ['additionalProperties', 'enum', 'type', 'required', 'pattern', 'maximum']) {
    assert.ok(rules.has(id), `no invalid file for schema rule ${id}`);
  }
});

test('corpus covers the required engineMustReject cases and the punch rule change', () => {
  const must = (name) => assert.equal(readJson(path.join(FX, 'invalid', `${name}.json`))._expect.engineMustReject, true, name);
  for (const n of ['unknown-top-level-key', 'unknown-beat-key-captionLane', 'bad-enum-layout-full', 'non-finite-t', 'S01-unsorted-beats',
    'assetDir-with-slash', 'src-with-dotdot', 'S11-srcCrop-x-plus-w-over-1920', 'S14-summary3-with-4-items', 'S14-final4-with-3-items', 'S19-hash-mismatch']) must(n);
  for (const n of ['S12-punch-on-source-stage-beat', 'S12-punch-on-wide-beat']) {
    assert.equal(readJson(path.join(FX, 'invalid', `${n}.json`))._expect.rule, 'S12');
  }
  // a valid punch on a full beat stays in the valid corpus
  assert.ok(baseVar().beats.some((b) => b.mode === 'full' && b.punch));
});

test('non-finite t (1e999 in the JSON text) is a type error, not a crash', () => {
  const text = fs.readFileSync(path.join(FX, 'invalid/non-finite-t.json'), 'utf8');
  assert.match(text, /1e999/);
  const ep = JSON.parse(text);
  assert.equal(ep.beats[1].t, Infinity);
});

// ---------------------------------------------------------------------------
// The sample itself: presenter-only limits and transition coverage (test-local helpers, NOT validator rules)
// ---------------------------------------------------------------------------

const beatEnd = (ep, i) => (i + 1 < ep.beats.length ? ep.beats[i + 1].t : ep.voEndSec);
const sceneKind = (b) => (b.mode === 'full' ? 'P' : b.layout === 'wide' ? 'W' : b.media === 'typo' ? 'T' : 'S');

/** Presenter-only seconds, not counting an opening full beat of <= 10 s and the last beat. */
function presenterOnlySeconds(ep) {
  let total = 0;
  ep.beats.forEach((b, i) => {
    if (b.mode !== 'full' || i === ep.beats.length - 1) return;
    const d = beatEnd(ep, i) - b.t;
    if (i === 0 && d <= 10) return;
    total += d;
  });
  return total;
}

/** Longest run of consecutive full beats, in seconds. */
function longestFullRun(ep) {
  let run = 0;
  let max = 0;
  ep.beats.forEach((b, i) => {
    run = b.mode === 'full' ? run + (beatEnd(ep, i) - b.t) : 0;
    max = Math.max(max, run);
  });
  return max;
}

test('sample-v1: presenter-only share <= 25% of voEndSec and no full run longer than 12 s', () => {
  const ep = readJson(path.join(FX, 'valid/sample-v1.json'));
  const share = presenterOnlySeconds(ep) / ep.voEndSec;
  assert.ok(share <= 0.25, `presenter-only share is ${(share * 100).toFixed(1)}%`);
  const run = longestFullRun(ep);
  assert.ok(run <= 12, `longest full run is ${run.toFixed(2)} s`);
});

test('sample-v1: keeps the original timing values and every transition type', () => {
  const ep = readJson(path.join(FX, 'valid/sample-v1.json'));
  assert.equal(ep.voEndSec, 336.5);
  assert.equal(ep.totalDurationSec, 341.0);
  const seen = new Set();
  for (let i = 1; i < ep.beats.length; i++) seen.add(`${sceneKind(ep.beats[i - 1])}->${sceneKind(ep.beats[i])}`);
  for (const t of ['P->S', 'P->T', 'P->W', 'S->P', 'T->P', 'W->P', 'S->S', 'S->T', 'T->S', 'T->T', 'S->W', 'W->S', 'W->T', 'W->W', 'T->W', 'P->P']) {
    assert.ok(seen.has(t), `transition ${t} is no longer exercised`);
  }
});

test('sample-v1: both stat carry-overs survive (one into a T beat, one into a P beat)', () => {
  const ep = readJson(path.join(FX, 'valid/sample-v1.json'));
  const carried = new Set();
  ep.beats.forEach((b, i) => (b.stats || []).forEach((s) => {
    if (s.at + s.dur > beatEnd(ep, i) && i + 1 < ep.beats.length) carried.add(sceneKind(ep.beats[i + 1]));
  }));
  assert.deepEqual([...carried].sort(), ['P', 'T']);
});

test('sample-v1: the from offsets and both srcCrop beats are still there', () => {
  const ep = readJson(path.join(FX, 'valid/sample-v1.json'));
  assert.ok(ep.beats.some((b) => b.src === 'yt_markup_experiment' && b.from === 0.1));
  assert.ok(ep.beats.some((b) => b.src === 'yt_markup_experiment' && b.from === 3.3 && b.srcCrop));
  assert.ok(ep.beats.some((b) => b.src === 'content_editor_workflow' && b.from === 8));
  assert.ok(ep.beats.some((b) => b.src === 'yt_complexity_variants' && b.srcCrop));
});

test('S19 tolerance: last caption page may end at voEndSec + 0.25, not at + 0.26', () => {
  const ep = baseMin();
  const withEnd = (end) => { const c = minCaptions(); c.pages[1].end = end; return validateEpisode(ep, c); };
  assert.equal(withEnd(ep.voEndSec + 0.25).valid, true);
  const r = withEnd(ep.voEndSec + 0.26);
  assert.equal(r.valid, false);
  assert.ok(r.errors.some((e) => e.rule === 'S19' && e.path === '/$captions/pages/1/end'));
});

// ---------------------------------------------------------------------------
// Semantic rule details beyond the corpus
// ---------------------------------------------------------------------------

test('semantic rules do not run when the schema pass fails (no cascade)', () => {
  const ep = baseMin();
  ep.beats[1].layout = 'full'; // enum error
  ep.beats[2].t = 1; // would be S01 / S02
  const r = validateEpisode(ep, minCaptions());
  assert.deepEqual([...new Set(r.errors.map((e) => e.rule))], ['enum']);
});

test('S09: a stock beat that loops is a warning, not an error', () => {
  const ep = baseMin();
  ep.brollDur = { stock_a: 2 };
  ep.beats[1] = { t: 3, mode: 'pip', media: 'broll', layout: 'stage', src: 'stock_a', origin: 'stock', headline: 'x' };
  const r = validateEpisode(ep, minCaptions());
  assert.equal(r.valid, true, JSON.stringify(r.errors));
  assert.ok(r.warnings.some((w) => w.rule === 'S09' && w.path === '/beats/1/src'));
});

test('S10: disjoint ranges of one source clip are fine', () => {
  const ep = baseMin();
  ep.brollDur = { yt_demo: 10 };
  const c = (t, from) => ({ t, mode: 'pip', media: 'clip', layout: 'stage', src: 'yt_demo', from, origin: 'source', headline: 'x' });
  ep.beats = [{ t: 0, mode: 'full' }, c(3, 0), c(6.5, 4), { t: 10, mode: 'full' }];
  const r = validateEpisode(ep, minCaptions());
  assert.equal(r.valid, true, JSON.stringify(r.errors));
});

test('S11: aspect between 10% and 25% off 16:9 is a warning', () => {
  const ep = baseMin();
  ep.beats[1].srcCrop = { x: 0, y: 0, w: 1400, h: 900 }; // 1.556 vs 1.778 = 12.5% off
  const r = validateEpisode(ep, minCaptions());
  assert.equal(r.valid, true, JSON.stringify(r.errors));
  assert.ok(r.warnings.some((w) => w.rule === 'S11'));
});

test('S13: a stat may outlive its beat by one boundary (valid corpus file proves it)', () => {
  const ep = baseVar();
  const st = ep.beats[1].stats[0];
  assert.ok(st.at + st.dur > ep.beats[2].t);
  assert.equal(validateEpisode(ep, minCaptions()).valid, true);
});

test('S07-file: opts.publicDir checks clip files and the avatar; no filesystem access without it', () => {
  const ep = baseMin();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ep-public-'));
  try {
    assert.equal(validateEpisode(ep, minCaptions()).valid, true);
    let r = validateEpisode(ep, minCaptions(), { publicDir: dir });
    assert.deepEqual(r.errors.map((e) => [e.rule, e.path]).sort(), [['S07-file', '/avatarFile'], ['S07-file', '/beats/1/src']]);
    fs.mkdirSync(path.join(dir, ep.assetDir, 'broll'), { recursive: true });
    fs.writeFileSync(path.join(dir, ep.assetDir, 'broll', 'yt_demo.mp4'), '');
    fs.writeFileSync(path.join(dir, ep.assetDir, ep.avatarFile), '');
    r = validateEpisode(ep, minCaptions(), { publicDir: dir });
    assert.equal(r.valid, true, JSON.stringify(r.errors));
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('S17 / S18 produce warnings only and never flip valid', () => {
  const ep = baseMin();
  ep.brand = 'B'.repeat(40);
  ep.beats[1].headline = 'ก'.repeat(60);
  ep.beats[0].stats = [
    { at: 0.5, dur: 2, big: '1234567890', label: 'ABCDEFGHIJKLMNOPQR', tone: 'amber' },
    { at: 0.6, dur: 2, big: '1234567890', label: 'ABCDEFGHIJKLMNOPQR', tone: 'mint' },
    { at: 0.7, dur: 2, big: '1234567890', label: 'ABCDEFGHIJKLMNOPQR', tone: 'clay' },
  ];
  const r = validateEpisode(ep, minCaptions());
  assert.equal(r.valid, true, JSON.stringify(r.errors));
  assert.ok(r.warnings.some((w) => w.rule === 'S17' && w.path === '/brand'));
  assert.ok(r.warnings.some((w) => w.rule === 'S17' && w.path === '/beats/1/headline'));
  assert.ok(r.warnings.some((w) => w.rule === 'S18'));
});

test('S17 text-card budgets: at the budget is silent, one grapheme over warns (warnings only, valid stays true)', () => {
  // [beat index in sample-v1, path suffix, budget]
  const cases = [
    [5, 'headline', 26],                  // card title
    [5, 'cards/0/lines/0', 30],           // card line
    [24, 'headline', 28],                 // final4 title
    [24, 'sub', 40],                      // final4 sub
    [24, 'items/0/text', 14],             // final4 item
    [37, 'items/0/text', 22],             // summary3 item
    [37, 'headline', 40],                 // summary3 eyebrow
    [20, 'headline', 40],                 // vs eyebrow
    [20, 'vs/left/title', 12],            // vs side title
    [20, 'vs/right/lines/0', 16],         // vs side line
    [20, 'vs/conclusion', 38],            // vs conclusion
  ];
  const setAt = (ep, beat, suffix, value) => {
    const parts = suffix.split('/');
    let node = ep.beats[beat];
    for (const part of parts.slice(0, -1)) node = node[part];
    node[parts.at(-1)] = value;
  };
  const sample = readJson(path.join(FX, 'valid/sample-v1.json'));
  const sampleCaptions = captions('sample-captions.json');
  for (const [beat, suffix, budget] of cases) {
    const where = `/beats/${beat}/${suffix}`;
    const at = clone(sample);
    setAt(at, beat, suffix, 'x'.repeat(budget));
    const rAt = validateEpisode(at, sampleCaptions);
    assert.equal(rAt.valid, true, `${where}: ${JSON.stringify(rAt.errors)}`);
    assert.equal(rAt.warnings.some((w) => w.rule === 'S17' && w.path === where), false, `${where} at budget ${budget}`);
    const over = clone(sample);
    setAt(over, beat, suffix, 'x'.repeat(budget + 1));
    const rOver = validateEpisode(over, sampleCaptions);
    assert.equal(rOver.valid, true, `${where}: ${JSON.stringify(rOver.errors)}`);
    const warn = rOver.warnings.find((w) => w.rule === 'S17' && w.path === where);
    assert.ok(warn, `${where} one over budget ${budget}`);
    assert.match(warn.message, new RegExp(`is ${budget + 1} graphemes, budget is ${budget}`));
  }
});

test('S19 without captions is a warning "captions not checked"', () => {
  const r = validateEpisode(baseMin());
  assert.equal(r.valid, true);
  const w = r.warnings.filter((x) => x.rule === 'S19');
  assert.equal(w.length, 1);
  assert.match(w[0].message, /captions not checked/);
});

test('graphemes counts Thai clusters, not code units', () => {
  assert.equal(graphemes('สวัสดี'), 4); // 4 user-perceived characters (6 code units)
  assert.equal(graphemes('abc'), 3);
  assert.ok(graphemes('สวัสดี') < 'สวัสดี'.length);
});

test('result carries the schema sha256 and it is stable', () => {
  const { sha256 } = loadSchema();
  assert.match(sha256, /^[0-9a-f]{64}$/);
  assert.equal(validateEpisode(baseMin(), minCaptions()).schemaSha256, sha256);
});

// ---------------------------------------------------------------------------
// Interpreter unit tests (one per supported keyword)
// ---------------------------------------------------------------------------

const check = (value, schema, root = schema) => validateAgainstSchema(value, schema, root, '');
const rules = (errs) => errs.map((e) => e.rule);

test('interpreter: type (string, number, integer, boolean, object, array)', () => {
  assert.deepEqual(check('a', { type: 'string' }), []);
  assert.deepEqual(rules(check(1, { type: 'string' })), ['type']);
  assert.deepEqual(check(1.5, { type: 'number' }), []);
  assert.deepEqual(rules(check('1', { type: 'number' })), ['type']);
  assert.deepEqual(rules(check(Infinity, { type: 'number' })), ['type']); // number requires isFinite
  assert.deepEqual(rules(check(NaN, { type: 'number' })), ['type']);
  assert.deepEqual(check(3, { type: 'integer' }), []);
  assert.deepEqual(rules(check(3.5, { type: 'integer' })), ['type']);
  assert.deepEqual(check(true, { type: 'boolean' }), []);
  assert.deepEqual(rules(check(0, { type: 'boolean' })), ['type']);
  assert.deepEqual(check({}, { type: 'object' }), []);
  assert.deepEqual(rules(check([], { type: 'object' })), ['type']);
  assert.deepEqual(rules(check(null, { type: 'object' })), ['type']);
  assert.deepEqual(check([], { type: 'array' }), []);
  assert.deepEqual(rules(check({}, { type: 'array' })), ['type']);
});

test('interpreter: enum, minimum, maximum, minLength, pattern', () => {
  assert.deepEqual(check('a', { enum: ['a', 'b'] }), []);
  assert.deepEqual(rules(check('c', { enum: ['a', 'b'] })), ['enum']);
  assert.deepEqual(check(5, { type: 'number', minimum: 5, maximum: 5 }), []);
  assert.deepEqual(rules(check(4, { type: 'number', minimum: 5 })), ['minimum']);
  assert.deepEqual(rules(check(6, { type: 'number', maximum: 5 })), ['maximum']);
  assert.deepEqual(rules(check('', { type: 'string', minLength: 1 })), ['minLength']);
  assert.deepEqual(check('ab', { type: 'string', pattern: '^[a-z]+$' }), []);
  assert.deepEqual(rules(check('aB', { type: 'string', pattern: '^[a-z]+$' })), ['pattern']);
  // `u` flag: a lone astral character is one code point
  assert.deepEqual(check('😀', { type: 'string', pattern: '^.$' }), []);
});

test('interpreter: required, properties, additionalProperties (false / schema / absent)', () => {
  const s = { type: 'object', required: ['a'], properties: { a: { type: 'number' } }, additionalProperties: false };
  assert.deepEqual(check({ a: 1 }, s), []);
  const missing = check({}, s);
  assert.deepEqual(missing.map((e) => [e.rule, e.path]), [['required', '/a']]);
  const extra = check({ a: 1, b: 2 }, s);
  assert.deepEqual(extra.map((e) => [e.rule, e.path]), [['additionalProperties', '/b']]);
  const typed = check({ a: 'x' }, s);
  assert.deepEqual(typed.map((e) => [e.rule, e.path]), [['type', '/a']]);
  const sub = { type: 'object', additionalProperties: { type: 'number' } };
  assert.deepEqual(check({ x: 1, y: 2 }, sub), []);
  assert.deepEqual(check({ x: 'no' }, sub).map((e) => [e.rule, e.path]), [['type', '/x']]);
  assert.deepEqual(check({ anything: 'goes' }, { type: 'object' }), []); // absent = allowed
});

test('interpreter: propertyNames (pattern only), JSON Pointer escaping', () => {
  const s = { type: 'object', propertyNames: { pattern: '^[a-z]+$' } };
  assert.deepEqual(check({ abc: 1 }, s), []);
  assert.deepEqual(check({ 'a/b': 1 }, s).map((e) => [e.rule, e.path]), [['pattern', '/a~1b']]);
  assert.deepEqual(check({ 'a~b': 1 }, s).map((e) => e.path), ['/a~0b']);
});

test('interpreter: items, minItems, maxItems', () => {
  const s = { type: 'array', minItems: 1, maxItems: 2, items: { type: 'number' } };
  assert.deepEqual(check([1, 2], s), []);
  assert.deepEqual(rules(check([], s)), ['minItems']);
  assert.deepEqual(rules(check([1, 2, 3], s)), ['maxItems']);
  assert.deepEqual(check([1, 'x'], s).map((e) => [e.rule, e.path]), [['type', '/1']]);
});

test('interpreter: $ref to #/$defs, $defs, $id', () => {
  const root = { $id: 'x', $defs: { n: { type: 'number', minimum: 1 } }, type: 'object', properties: { a: { $ref: '#/$defs/n' } } };
  assertSupportedSchema(root);
  assert.deepEqual(check({ a: 2 }, root), []);
  assert.deepEqual(rules(check({ a: 0 }, root)), ['minimum']);
  assert.throws(() => check({ a: 1 }, { type: 'object', properties: { a: { $ref: '#/$defs/missing' } } }), /unresolved/);
});

test('interpreter: path prefix for captions-style validation', () => {
  const { schema } = loadSchema();
  const errs = validateAgainstSchema({ schema: 2 }, { $ref: '#/$defs/captions' }, schema, '/$captions');
  assert.ok(errs.length > 0 && errs.every((e) => e.path.startsWith('/$captions')));
});

test('interpreter: an unknown schema keyword THROWS (fail closed), anywhere in the schema', () => {
  assert.throws(() => assertSupportedSchema({ type: 'object', oneOf: [] }), /unsupported schema keyword "oneOf"/);
  assert.throws(() => assertSupportedSchema({ type: 'object', properties: { a: { type: 'string', format: 'uri' } } }), /"format"/);
  assert.throws(() => assertSupportedSchema({ $defs: { a: { items: { minProperties: 1 } } } }), /"minProperties"/);
  assert.throws(() => assertSupportedSchema({ additionalProperties: { description: 'x' } }), /"description"/);
  assert.throws(() => assertSupportedSchema({ propertyNames: { minLength: 1 } }), /propertyNames/);
  assert.throws(() => assertSupportedSchema({ $ref: 'http://x/y' }), /\$ref/);
  assert.throws(() => assertSupportedSchema({ type: 'null' }), /unsupported type/);
  // a property literally NAMED like a keyword is data, not a keyword
  assertSupportedSchema({ type: 'object', properties: { format: { type: 'string' }, oneOf: { type: 'string' } } });
});

test('loadSchema throws on a schema file with an unknown keyword and returns the sha256 of the file bytes', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ep-schema-'));
  try {
    const bad = path.join(dir, 'bad.schema.json');
    fs.writeFileSync(bad, JSON.stringify({ type: 'object', anyOf: [] }));
    assert.throws(() => loadSchema(bad), /unsupported schema keyword "anyOf"/);
    const good = path.join(dir, 'good.schema.json');
    const text = JSON.stringify({ type: 'object' });
    fs.writeFileSync(good, text);
    const r = loadSchema(good);
    assert.deepEqual(r.schema, { type: 'object' });
    assert.equal(r.sha256.length, 64);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('the shipped schema file only uses supported keywords', () => {
  assert.doesNotThrow(() => loadSchema());
});

// ---------------------------------------------------------------------------
// projectCaptions
// ---------------------------------------------------------------------------

test('projectCaptions keeps exactly the fields the engine reads', () => {
  const full = captions('sample-captions.json');
  full.trailingSpace = ' ';
  full.diagnostics = { x: 1 };
  const p = projectCaptions(full);
  assert.deepEqual(Object.keys(p), ['schema', 'algorithm', 'inputSha256', 'pages']);
  assert.equal(p.pages.length, full.pages.length);
  for (const page of p.pages) {
    assert.deepEqual(Object.keys(page), ['start', 'end', 'displayText', 'chunks']);
    for (const c of page.chunks) assert.deepEqual(Object.keys(c), ['text', 'displaySpaceBefore', 'displayStart', 'displayEnd']);
  }
  assert.equal(p.pages[0].chunks[0].text, full.pages[0].chunks[0].text);
  // the projection is still valid captions
  assert.equal(validateEpisode(readJson(path.join(FX, 'valid/sample-v1.json')), p).valid, true);
  // and the input is not mutated
  assert.ok('boundReason' in full.pages[0]);
});

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

const cli = (...args) => spawnSync(process.execPath, [SCRIPT, ...args], { encoding: 'utf8' });
const VALID = path.join(FX, 'valid/min-3-beat.json');
const MINCAP = path.join(FX, 'captions/min-captions.json');

test('CLI exit 0 for a valid episode, text output ends with the summary line', () => {
  const r = cli('validate', VALID, '--captions', MINCAP);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.stdout.trim(), 'EPISODE_SCHEMA valid=true errors=0 warnings=0');
  assert.equal(r.stderr, '');
});

test('CLI exit 1 for an invalid episode, one ERROR line per finding', () => {
  const bad = clone(readJson(path.join(FX, 'invalid/S02-beat-shorter-than-1s.json')));
  delete bad._expect;
  const tmp = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'ep-cli-')), 'bad.json');
  fs.writeFileSync(tmp, JSON.stringify(bad));
  try {
    const r = cli('validate', tmp, '--captions', MINCAP);
    assert.equal(r.status, 1);
    const lines = r.stdout.trim().split('\n');
    assert.match(lines[0], /^ERROR \/beats\/1\/t \[S02\] /);
    assert.match(lines.at(-1), /^EPISODE_SCHEMA valid=false errors=\d+ warnings=\d+$/);
  } finally {
    fs.rmSync(path.dirname(tmp), { recursive: true, force: true });
  }
});

test('CLI --json prints exactly one JSON object with exactly four keys and nothing else', () => {
  const r = cli('validate', VALID, '--captions', MINCAP, '--json');
  assert.equal(r.status, 0);
  assert.equal(r.stderr, '');
  assert.ok(r.stdout.endsWith('\n') && r.stdout.trim().split('\n').length === 1);
  const o = JSON.parse(r.stdout);
  assert.deepEqual(Object.keys(o), ['valid', 'errors', 'warnings', 'schemaSha256']);
  assert.equal(o.valid, true);
  assert.equal(o.schemaSha256, loadSchema().sha256);
});

test('CLI --json on an invalid file: exit 1, error objects have path / rule / message', () => {
  const file = path.join(FX, 'invalid/unknown-top-level-key.json');
  const ep = readJson(file);
  delete ep._expect;
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ep-cli-'));
  const tmp = path.join(dir, 'bad.json');
  fs.writeFileSync(tmp, JSON.stringify(ep));
  try {
    const r = cli('validate', tmp, '--json');
    assert.equal(r.status, 1);
    const o = JSON.parse(r.stdout);
    assert.deepEqual(Object.keys(o), ['valid', 'errors', 'warnings', 'schemaSha256']);
    assert.equal(o.valid, false);
    assert.deepEqual(Object.keys(o.errors[0]), ['path', 'rule', 'message']);
    assert.equal(o.errors[0].path, '/extra');
    assert.equal(o.errors[0].rule, 'additionalProperties');
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('CLI warnings do not change the exit code (no --captions gives the S19 warning)', () => {
  const r = cli('validate', VALID, '--json');
  assert.equal(r.status, 0);
  assert.equal(JSON.parse(r.stdout).warnings[0].rule, 'S19');
  const t = cli('validate', VALID);
  assert.equal(t.status, 0);
  assert.match(t.stdout, /^WARNING \/captionsInputSha256 \[S19\] captions not checked/m);
});

test('CLI --public checks files (S07-file)', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ep-cli-pub-'));
  try {
    const r = cli('validate', VALID, '--captions', MINCAP, '--public', dir, '--json');
    assert.equal(r.status, 1);
    assert.ok(JSON.parse(r.stdout).errors.every((e) => e.rule === 'S07-file'));
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('CLI exit 2: usage, missing file, bad JSON, missing captions file, missing --public dir, nothing on stdout', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ep-cli-'));
  try {
    const notJson = path.join(dir, 'x.json');
    fs.writeFileSync(notJson, '{ nope');
    const cases = [
      [],
      ['validate'],
      ['frobnicate', VALID],
      ['validate', VALID, '--bogus'],
      ['validate', VALID, '--captions'],
      ['validate', path.join(dir, 'missing.json')],
      ['validate', notJson],
      ['validate', VALID, '--captions', path.join(dir, 'missing.json'), '--json'],
      ['validate', VALID, '--public', path.join(dir, 'no-such-dir'), '--json'],
    ];
    for (const args of cases) {
      const r = cli(...args);
      assert.equal(r.status, 2, JSON.stringify(args));
      assert.equal(r.stdout, '', JSON.stringify(args));
      assert.match(r.stderr, /^episode_schema: /, JSON.stringify(args));
    }
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('runCli (in-process) matches the spawned CLI', () => {
  const a = runCli(['validate', VALID, '--captions', MINCAP, '--json']);
  const b = cli('validate', VALID, '--captions', MINCAP, '--json');
  assert.equal(a.exitCode, b.status);
  assert.equal(a.stdout, b.stdout);
});

test('importing the module has no side effects (no output, no exit code, no CLI run)', () => {
  const r = spawnSync(process.execPath, ['--input-type=module', '-e',
    `import ${JSON.stringify(SCRIPT)}; import(${JSON.stringify(SCRIPT)}).then(() => {});`], { encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.stdout, '');
  assert.equal(r.stderr, '');
});
