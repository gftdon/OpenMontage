import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { evaluateLayout, ruleOverlap, validateSamples, backingPresent } from '../qc_layout_eval.mjs';
import { thresholds, v3Field as field, v3Snap, backingFor, permissiveCtx } from './fixtures/v3/builders.mjs';

// Fields keep their V2 test ids; the permissive ctx lets only the rule under test fire.
const f = (id, x, y, extra) => field(id, { x, y, ...extra });
const snap = (fields = [field('headline'), f('chip', 100, 170)], over = {}) => v3Snap(fields, over);
const issuesOf = s => evaluateLayout(s, thresholds, permissiveCtx(s)).issues;
const codes = s => issuesOf(s).map(i => i.code);

test('actual legacy Q1 snapshot (V2 shape) fails overlap', () => {
  const snapshot = JSON.parse(fs.readFileSync(new URL('./fixtures/q1-legacy-225.json', import.meta.url)));
  assert.ok(ruleOverlap(snapshot, thresholds).some(i => i.code === 'overlap'));
});
test('V2 snapshot fails closed with a single schema issue', () => {
  const v2 = { ...snap(), schemaVersion: 2 };
  const out = evaluateLayout(v2, thresholds, permissiveCtx(v2)).issues;
  assert.equal(out.length, 1);
  assert.equal(out[0].id, 'schema');
});
test('missing ctx fails closed', () => assert.deepEqual(evaluateLayout(snap(), thresholds, {}).issues.map(i => i.id), ['ctx-missing']));
test('issues carry id, code, frame, field and message', () => {
  const i = issuesOf(snap([f('headline', 100, 100), f('chip', 110, 110)])).find(x => x.code === 'overlap');
  assert.equal(i.id, 'overlap'); assert.equal(i.frame, 225); assert.ok(i.message); assert.equal(i.detail, 'headline/chip');
});

test('separated rows pass', () => assert.deepEqual(codes(snap()), []));
test('old Q1 chip overlapping headline fails', () => assert.ok(codes(snap([field('headline'), f('chip', 110, 110)])).includes('overlap')));
test('outside safe area fails', () => assert.ok(codes(snap([f('edge', 90, 100)])).includes('safe')));
test('read font: 35 fails, 36 passes', () => {
  assert.ok(codes(snap([field('small', { fontSize: 35 })])).includes('font'));
  assert.ok(!codes(snap([field('small', { fontSize: 36 })])).includes('font'));
});
test('label font: 27 fails, 28 passes', () => {
  assert.ok(codes(snap([field('label', { tier: 'label', fontSize: 27 })])).includes('font'));
  assert.deepEqual(codes(snap([field('label', { tier: 'label', fontSize: 28 })])), []);
});
test('clipping fails', () => assert.ok(codes(snap([field('clip', { clipped: true })])).includes('clip')));
test('missing fonts/log and invalid geometry fail closed', () => {
  for (const s of [null, { ...snap(), fontsOk: false }, { ...snap(), fields: [] }, snap([field('bad', { x: NaN })])]) {
    assert.ok(s === null ? evaluateLayout(s, thresholds, {}).issues.length : issuesOf(s).length);
  }
});
test('source needs credit and stock rejects chrome or credit', () => {
  let s = snap(); s.footage = { origin: 'source', src: 'yt_demo', credit: false, chrome: true };
  assert.ok(codes(s).includes('credit'));
  s = snap(); s.footage.chrome = true; assert.ok(codes(s).includes('stock-chrome'));
});
test('nested logical field fragments are not compared against themselves', () => {
  const r = [{ x: 100, y: 100, width: 200, height: 40 }, { x: 120, y: 100, width: 50, height: 40 }];
  assert.deepEqual(codes(snap([field('caption', { rects: r })])), []);
});
test('transition exemptions are limited to old/new versions of the same field', () => {
  const a = field('headline', { layer: 'previous' }), b = field('headline');
  assert.deepEqual(codes({ ...snap([a, b]), transition: true }), []);
  assert.ok(codes({ ...snap([a, field('chip')]), transition: true }).includes('overlap'));
});
test('opaque container hides headline without text intersection including pointer-events none image', () => {
  for (const kind of ['pill', 'image']) {
    const s = snap([field('headline')]);
    s.occluders = [{ id: 'cover', kind, box: { x: 110, y: 100, width: 200, height: 40 }, opacity: 1, frontOf: ['headline'], pointerEvents: 'none' }];
    assert.ok(codes(s).includes('occlusion'));
  }
});
test('Thai ink outside Range is clipped and missing ink fails closed', () => {
  const s = snap([field('thai', { inkRects: [{ x: 100, y: 90, width: 200, height: 55 }], clipBoxes: [{ x: 100, y: 100, width: 200, height: 40 }] })]);
  assert.ok(codes(s).includes('clip'));
  const m = field('missing'); delete m.inkRects; assert.ok(codes(snap([m])).includes('geometry'));
});
test('hidden or occluded source credit fails and stock URL detected without chrome attribute', () => {
  for (const opacity of [0, 0.01]) {
    const s = snap([field('source-credit', { opacity })]); s.footage = { origin: 'source', src: 'yt_demo', credit: true, chrome: false };
    assert.ok(codes(s).includes('credit'));
  }
  const s = snap([field('source-credit')]); s.footage = { origin: 'source', src: 'yt_demo', credit: true };
  s.occluders = [{ id: 'cover', box: { x: 100, y: 100, width: 200, height: 40 }, opacity: 1, frontOf: ['source-credit'] }];
  assert.ok(codes(s).includes('credit'));
  assert.ok(codes(snap([field('source-url')])).includes('stock-chrome'));
});
test('full footage text requires an effective backing and top caption lane is enforced', () => {
  const s = snap([f('caption', 100, 950)]); s.footage.layout = 'full'; s.captionLane = 'top';
  assert.ok(codes(s).includes('backing')); assert.ok(codes(s).includes('caption-lane'));
  const cap = f('caption', 100, 250); cap.backing = backingFor(cap);
  s.fields = [cap]; assert.deepEqual(codes(s), []);
  s.captionLane = 'bottom'; assert.ok(codes(s).includes('caption-lane'));
});
test('missing duplicate wrong frame samples fail closed', () => {
  assert.ok(validateSamples([225, 226], [snap()]).length);
  assert.ok(validateSamples([225], [snap(), snap()]).length);
  assert.ok(validateSamples([226], [snap()]).length);
  assert.deepEqual(validateSamples([225], [snap()]), []);
});

// ---- backing presence: effective alpha = alpha * opacity (V2 accepted a shared fade, V4 rejects it) ----
const ink = [{ x: 100, y: 100, width: 100, height: 40 }];
const good = { alpha: 1, opacity: 1, sameVisibilityAncestry: true, box: { x: 90, y: 90, width: 130, height: 70 } };
test('shared fade is rejected now: alpha .92 * opacity .45 = .414 < .9', () => {
  assert.equal(backingPresent({ ...good, alpha: 0.92, opacity: 0.45 }, ink, thresholds), false);
});
test('effective alpha boundary: 0.90 passes, 0.899 fails (by alpha and by opacity)', () => {
  assert.equal(backingPresent({ ...good, alpha: 0.9 }, ink, thresholds), true);
  assert.equal(backingPresent({ ...good, alpha: 0.899 }, ink, thresholds), false);
  assert.equal(backingPresent({ ...good, alpha: 1, opacity: 0.9 }, ink, thresholds), true);
  assert.equal(backingPresent({ ...good, alpha: 1, opacity: 0.899 }, ink, thresholds), false);
});
test('backing presence rejects missing/invisible/uncovered backing', () => {
  assert.equal(backingPresent(good, ink, thresholds), true);
  for (const bad of [null, { ...good, alpha: 0 }, { ...good, opacity: 0 }, { ...good, sameVisibilityAncestry: false }, { ...good, box: { x: 100, y: 110, width: 100, height: 20 } }]) {
    assert.equal(backingPresent(bad, ink, thresholds), false);
  }
});
test('actual headline ink overhang is rejected until layout padding contains it', () => {
  const field = JSON.parse(fs.readFileSync(new URL('./fixtures/headline-overhang.json', import.meta.url)));
  assert.equal(backingPresent(field.backing, field.inkRects, thresholds), false);
});
test('actual padded headline backing contains measured ink', () => {
  const field = JSON.parse(fs.readFileSync(new URL('./fixtures/headline-padded.json', import.meta.url)));
  assert.equal(backingPresent(field.backing, field.inkRects, thresholds), true);
});
