// Rule-level tests for the v3 layout gate (G8: every new rule fails on V3 data / synthetic defects and
// passes on the corrected counterpart). Real V3 frames live in fixtures/v3 (see README.md there).
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  evaluateLayout, evaluatePlanRules, resolveFieldRule, rubricSize,
  ruleBacking, ruleContentPresence, rulePresenterTextBacking, ruleFace, ruleFont, ruleFontRubric, ruleTier,
  ruleTextAlpha, ruleProbeIssues, ruleLane, ruleReservedIntersect, ruleLineCount, ruleNowrapOverflow, ruleLaneTable, ruleSchema,
} from '../qc_layout_eval.mjs';
import {
  thresholds as t, fieldRules, PLAN, PLAN_WITH_HEADER, CTX, CTX_HEADER, v3Field, v3Snap, backingFor, loadRaw, RAW, augmentDark, withHeldStage,
  augmentPresenter, mapFaceBox, inkBox, clone,
} from './fixtures/v3/builders.mjs';

const ids = issues => issues.map(i => i.id);
const near = (a, b, tol = 1e-3) => assert.ok(Math.abs(a - b) <= tol, `${a} != ${b} (±${tol})`);
const field = (s, id) => s.fields.find(f => f.id === id);

// ======================================================================================
// Real V3 frames (V2-shaped probe output, augmented where the spec says so)
// ======================================================================================

test('content-presence: dark frames 6940/6941/6942 fail on V3 (only a faded avatar layer), pass with a held stage layer', () => {
  const expected = { 6940: [0, 1e-9], 6941: [0.00208, 2e-4], 6942: [0.00903, 2e-4] };
  for (const n of [6940, 6941, 6942]) {
    const dark = augmentDark(loadRaw(RAW[n]));
    const out = ruleContentPresence(dark, t);
    assert.deepEqual(ids(out), ['content-presence'], `frame ${n}`);
    near(out[0].coverage, expected[n][0], expected[n][1]);
    assert.equal(out[0].needed, 0.25);
    assert.deepEqual(ruleContentPresence(withHeldStage(dark), t), [], `frame ${n} with the outgoing stage held`);
  }
});
test('content-presence: only the voice-over phase is checked; a missing layers array is a schema issue', () => {
  const dark = augmentDark(loadRaw(RAW[6940]));
  assert.deepEqual(ruleContentPresence({ ...dark, phase: 'endcard' }, t), []);
  const { layers, ...noLayers } = dark;
  assert.deepEqual(ids(ruleContentPresence(noLayers, t)), ['schema']);
});
test('content-presence: coverage threshold boundary (layer opacity .25 passes, .249 fails)', () => {
  const s = v3Snap([], { layers: [{ kind: 'stage', id: 's', opacity: 0.25, box: { x: 0, y: 0, width: 1920, height: 1080 } }] });
  assert.deepEqual(ruleContentPresence(s, t), []);
  s.layers[0].opacity = 0.249;
  assert.deepEqual(ids(ruleContentPresence(s, t)), ['content-presence']);
});
test('content-presence: a layer is clipped to the frame', () => {
  const s = v3Snap([], { layers: [{ kind: 'stage', id: 's', opacity: 1, box: { x: 1920, y: 0, width: 1920, height: 1080 } }] });
  assert.deepEqual(ids(ruleContentPresence(s, t)), ['content-presence']);
});

test('backing: headline on 1875 (backing alpha .95 * opacity .6226 = .59) fails as-is, passes with backing.opacity = 1', () => {
  const raw = loadRaw(RAW[1875]);
  const out = ruleBacking(raw, t);
  assert.deepEqual(out.map(i => [i.id, i.field]), [['backing', 'headline']]);
  near(out[0].effAlpha, 0.95 * 0.622585, 1e-3);
  const fixed = clone(raw);
  field(fixed, 'headline').backing.opacity = 1;
  assert.deepEqual(ruleBacking(fixed, t), []);
});
test('backing: effective-alpha boundary 0.90 passes, 0.899 fails; sameVisibilityAncestry and containment are required', () => {
  const mk = over => {
    const f = v3Field('headline', { x: 128, y: 712 });
    f.backing = backingFor(f, over);
    return v3Snap([f], { footage: { origin: 'source', layout: 'full', src: 'yt_x' } });
  };
  assert.deepEqual(ruleBacking(mk({ alpha: 0.9 }), t), []);
  assert.deepEqual(ids(ruleBacking(mk({ alpha: 0.899 }), t)), ['backing']);
  assert.deepEqual(ruleBacking(mk({ alpha: 1, opacity: 0.9 }), t), []);
  assert.deepEqual(ids(ruleBacking(mk({ alpha: 1, opacity: 0.899 }), t)), ['backing']);
  assert.deepEqual(ids(ruleBacking(mk({ sameVisibilityAncestry: false }), t)), ['backing']);
  assert.deepEqual(ids(ruleBacking(mk({ box: { x: 128, y: 712, width: 50, height: 10 } }), t)), ['backing']);
  const noFull = mk({ alpha: 0 }); noFull.footage.layout = 'split';
  assert.deepEqual(ruleBacking(noFull, t), [], 'rule applies only to full layouts');
});

test('presenter-text-backing: source-url on 1860 (effAlpha .29 over the presenter) fails; caption .92 and credit .90 pass at the boundary', () => {
  const raw = augmentPresenter(loadRaw(RAW[1860]));
  const out = rulePresenterTextBacking(raw, t);
  assert.deepEqual(out.map(i => [i.id, i.field]), [['presenter-text-backing', 'source-url']]);
  near(out[0].effAlpha, 0.2857, 1e-3);
  near(raw.avatar.mediaBox.x, 351.0, 0.2);                         // spec: the URL starts at x≈351 over the card
  // V4 delayed chrome: the URL (and its backing) is not shown yet while the presenter is up.
  const fixed = clone(raw);
  const url = field(fixed, 'source-url'); url.opacity = 0; url.backing.opacity = 0;
  assert.deepEqual(rulePresenterTextBacking(fixed, t), []);
});
test('presenter-text-backing: cta on 16035 (backing null, avatar opacity 1) fails; a solid backing that contains the ink passes', () => {
  const raw = augmentPresenter(loadRaw(RAW[16035]));
  assert.equal(raw.avatar.opacity, 1);
  const out = rulePresenterTextBacking(raw, t);
  assert.deepEqual(out.map(i => [i.id, i.field]), [['presenter-text-backing', 'cta']]);
  assert.equal(out[0].effAlpha, 0);
  const fixed = clone(raw);
  const cta = field(fixed, 'cta');
  const b = inkBox(cta);
  cta.backing = { id: 'cta-backing', path: 'div:cta', alpha: 1, opacity: 1, sameVisibilityAncestry: true, box: { x: b.x - 16, y: b.y - 8, width: b.width + 32, height: b.height + 16 } };
  assert.deepEqual(rulePresenterTextBacking(fixed, t), []);
});
test('presenter-text-backing: avatar opacity .3 applies, .29 does not; endcard phase never applies; no avatar = no rule', () => {
  const raw = augmentPresenter(loadRaw(RAW[16035]));
  const withOpacity = o => ({ ...raw, avatar: { ...raw.avatar, opacity: o } });
  assert.equal(ids(rulePresenterTextBacking(withOpacity(0.3), t)).length, 1);
  assert.deepEqual(rulePresenterTextBacking(withOpacity(0.29), t), []);
  assert.deepEqual(rulePresenterTextBacking({ ...raw, phase: 'endcard' }, t), []);
  assert.deepEqual(rulePresenterTextBacking({ ...raw, avatar: null }, t), []);
});

// Face rules: no natural V3 failure, so they are synthetic on top of the augmented 1860 frame.
function faceFrame1860() {
  const s = augmentPresenter(loadRaw(RAW[1860]));
  // normalised reference face from the spec (presenter measured off 1860.png), mapped exactly like the probe
  s.avatar.faceBox = mapFaceBox({ x: 0.37, y: 0.12, w: 0.19, h: 0.36 }, s.avatar.mediaBox, 16 / 9);
  s.avatar.faceBoxSource = 'episode';
  s.backings = s.occluders.filter(o => o.id !== 'avatar').map(o => ({ id: o.id, path: `div:${o.id}`, reserved: null, alpha: 1, opacity: o.opacity, box: o.box }));
  return s;
}
test('face rules: unshifted 1860 (caption, credit and URL left of the face) passes', () => {
  const s = faceFrame1860();
  near(s.avatar.faceBox.x, 837.6, 1); near(s.avatar.faceBox.y, 216.8, 1);
  assert.deepEqual(ruleFace(s, t), []);
});
test('face-text: caption ink shifted +500 px onto the face fails', () => {
  const s = faceFrame1860();
  const cap = field(s, 'caption');
  for (const r of [...cap.inkRects, ...cap.rects]) r.x += 500;
  const out = ruleFace(s, t);
  assert.deepEqual(out.map(i => [i.id, i.field]), [['face-text', 'caption']]);
});
test('face-backing: a visible backing box over the face fails; the same backing at opacity .04 does not', () => {
  const s = faceFrame1860();
  s.backings.push({ id: 'face-cover', path: 'div:9', reserved: null, alpha: 1, opacity: 1, box: { x: 800, y: 200, width: 300, height: 300 } });
  assert.deepEqual(ruleFace(s, t).map(i => [i.id, i.detail]), [['face-backing', 'face-cover']]);
  s.backings.at(-1).opacity = 0.04;
  assert.deepEqual(ruleFace(s, t), []);
});
test('face-backing: a backing the probe measured UNDER the presenter does not cover the face; true / null / missing count', () => {
  const s = faceFrame1860();
  const cover = { id: 'face-cover', path: 'div:9', reserved: null, alpha: 1, opacity: 1, box: { x: 800, y: 200, width: 300, height: 300 } };
  s.backings.push(cover);
  for (const v of [undefined, null, true]) { cover.aboveAvatarAtFace = v; assert.deepEqual(ruleFace(s, t).map(i => i.id), ['face-backing'], String(v)); }
  cover.aboveAvatarAtFace = false;
  assert.deepEqual(ruleFace(s, t), [], 'painted below the presenter (e.g. the leaving wide window)');
  // text over the face is unaffected by the paint-order exemption
  const cap = field(s, 'caption');
  for (const r of [...cap.inkRects, ...cap.rects]) r.x += 500;
  assert.deepEqual(ruleFace(s, t).map(i => i.id), ['face-text']);
});
test('face rules: missing faceBox / backings while the presenter is visible fail closed', () => {
  const s = faceFrame1860();
  assert.deepEqual(ids(ruleFace({ ...s, avatar: { ...s.avatar, faceBox: undefined } }, t)), ['schema']);
  assert.deepEqual(ids(ruleFace({ ...s, backings: undefined }, t)), ['schema']);
});
test('mapFaceBox follows the spec cover mapping (wide media, tall media)', () => {
  const fb = { x: 0.25, y: 0.03, w: 0.5, h: 0.62 };
  assert.deepEqual(mapFaceBox(fb, { x: 0, y: 0, width: 1600, height: 900 }, 16 / 9), { x: 400, y: 27, width: 800, height: 558 });
  const tall = mapFaceBox({ x: 0, y: 0, w: 1, h: 1 }, { x: 0, y: 0, width: 900, height: 900 }, 16 / 9);   // cover crops the sides
  assert.equal(tall.height, 900); near(tall.width, 1600, 1e-6); near(tall.x, -350, 1e-6);
});

// ======================================================================================
// Synthetic: typography
// ======================================================================================

test('font: CSS floors 36 (read) / 28 (label) from the thresholds file', () => {
  assert.equal(t.readFontPx, 36); assert.equal(t.labelFontPx, 28);
  const fire = (tier, size) => ids(ruleFont(v3Snap([v3Field('x', { tier, fontSize: size })]), t));
  assert.deepEqual(fire('read', 35), ['font']); assert.deepEqual(fire('read', 36), []);
  assert.deepEqual(fire('label', 27), ['font']); assert.deepEqual(fire('label', 28), []);
  assert.deepEqual(ids(ruleFont(v3Snap([v3Field('x', { fontSize: 20, opacity: 0.04 })]), t)), [], 'invisible fields are skipped');
});

test('font-rubric: Thai 15 px ink / 0.7 = 21.4 < 28 fails; 19.8 / 0.7 = 28.3 passes (read)', () => {
  const run = (glyph, ink, tier = 'read') => {
    const rubric = { glyph, thaiInkPx: glyph === 'latin' ? null : ink, latinInkPx: glyph === 'thai' ? null : ink, scaleY: 1, rubricPx: null };
    return ruleFontRubric(v3Snap([v3Field('x', { tier, rubric })]), t);
  };
  const bad = run('thai', 15);
  assert.deepEqual(ids(bad), ['font-rubric']);
  near(bad[0].rubricPx, 21.429, 1e-2); assert.equal(bad[0].floor, 28);
  assert.deepEqual(run('thai', 19.8), []);
  assert.deepEqual(ids(run('thai', 19.5)), ['font-rubric']); assert.deepEqual(run('thai', 19.7), []);
  // label floor 22: ink 15.4 / 0.7 = 22
  assert.deepEqual(ids(run('thai', 15.2, 'label')), ['font-rubric']); assert.deepEqual(run('thai', 15.5, 'label'), []);
  assert.deepEqual(run('latin', 20), []);
  assert.deepEqual(ids(run('latin', 18)), ['font-rubric']);
});
test('font-rubric: mixed text uses the smaller ink; scaleY scales it; glyph none is skipped; unmeasurable fails closed', () => {
  const f = rubric => ruleFontRubric(v3Snap([v3Field('x', { rubric })]), t);
  assert.deepEqual(ids(f({ glyph: 'mixed', thaiInkPx: 25, latinInkPx: 15, scaleY: 1, rubricPx: null })), ['font-rubric']);
  assert.deepEqual(f({ glyph: 'mixed', thaiInkPx: 25, latinInkPx: 21, scaleY: 1, rubricPx: null }), []);
  assert.deepEqual(f({ glyph: 'thai', thaiInkPx: 10, latinInkPx: null, scaleY: 2.5, rubricPx: null }), [], 'ink 10 * scale 2.5 / .7 = 35.7');
  assert.deepEqual(ids(f({ glyph: 'thai', thaiInkPx: 10, latinInkPx: null, scaleY: 1.5, rubricPx: null })), ['font-rubric']);
  assert.deepEqual(f({ glyph: 'none', thaiInkPx: null, latinInkPx: null, scaleY: 1, rubricPx: null }), []);
  assert.deepEqual(ids(f({ glyph: 'thai', thaiInkPx: null, latinInkPx: null, scaleY: 1, rubricPx: null })), ['font-rubric']);
  assert.deepEqual(ids(ruleFontRubric(v3Snap([v3Field('x', { rubric: undefined })]), t)), ['font-rubric']);
  assert.deepEqual(f({ glyph: 'thai', thaiInkPx: null, latinInkPx: null, scaleY: 1, rubricPx: 30 }), [], 'falls back to the probe rubricPx when no ink data');
  assert.equal(rubricSize({ glyph: 'thai', thaiInkPx: 14, latinInkPx: null, scaleY: 1, rubricPx: null }, { rubricInkDivisor: 0.7 }), 20);
});

test('text-alpha: read text drawn with a translucent colour (alpha < .85) fails (V3 CREAM_DIM .62); a fade (opacity) is not text-alpha; labels are exempt', () => {
  const run = (over, tier = 'read') => ruleTextAlpha(v3Snap([v3Field('description', { tier, ...over })]), t);
  const bad = run({ colorAlpha: 0.62 });
  assert.deepEqual(ids(bad), ['text-alpha']); near(bad[0].alpha, 0.62);
  assert.deepEqual(run({ colorAlpha: 0.85 }), []);
  assert.deepEqual(ids(run({ colorAlpha: 0.84 })), ['text-alpha']);
  assert.deepEqual(run({ colorAlpha: 1, opacity: 0.4 }), [], 'an entrance / exit fade inside an opaque backing is not a translucent colour');
  assert.deepEqual(ids(run({ colorAlpha: 0.62, opacity: 0.4 })), ['text-alpha'], 'a translucent colour fails at any opacity');
  assert.deepEqual(run({ colorAlpha: 0.62 }, 'label'), []);
  assert.deepEqual(ids(run({ colorAlpha: undefined })), ['text-alpha'], 'missing colorAlpha fails closed');
});

test('tier-missing / tier-mismatch / unknown-field (fail closed)', () => {
  const run = (...fs) => ruleTier(v3Snap(fs), t, CTX);
  assert.deepEqual(run(v3Field('headline'), v3Field('kicker', { tier: 'label' })), []);
  assert.deepEqual(run(v3Field('headline', { tier: null, role: 'read' })).map(i => i.id), ['tier-missing']);
  assert.deepEqual(run(v3Field('headline', { tier: undefined, role: 'read' })).map(i => i.id), ['tier-missing']);
  const mis = run(v3Field('headline', { tier: 'label' }));
  assert.deepEqual(ids(mis), ['tier-mismatch']); assert.equal(mis[0].expected, 'read');
  assert.deepEqual(run(v3Field('mystery')).map(i => [i.id, i.field]), [['unknown-field', 'mystery']]);
  assert.deepEqual(ids(run(v3Field('_status'))), ['unknown-field'], '_status is metadata, not a field');
  assert.deepEqual(ids(run(v3Field('typo-headline-extra'), v3Field('stat-big-1-2'), v3Field('stat-label-1-2', { tier: 'label' }))), []);
  assert.deepEqual(ids(run(v3Field('typo-x', { tier: 'label' }))), ['tier-mismatch']);
  assert.deepEqual(ids(run(v3Field('stat-big-1-2', { tier: 'label' }), v3Field('stat-label-1-2'))), ['tier-mismatch', 'tier-mismatch'], 'big = read, label = label');
  assert.deepEqual(ids(run(v3Field('stat-5', { tier: 'label' }))), ['unknown-field'], 'the old stat-N ids are gone');
  assert.deepEqual(ids(run(v3Field('typo'))), ['unknown-field'], '"typo" alone does not match the typo-* pattern');
  assert.deepEqual(ids(ruleTier(v3Snap([v3Field('headline')]), t, {})), ['ctx-missing']);
});
test('resolveFieldRule: exact beats prefix, longest prefix wins, underscore keys ignored', () => {
  const rules = { _status: 'x', 'a-*': { tier: 'read' }, 'a-b-*': { tier: 'label' }, 'a-b-c': { tier: 'read', exact: true } };
  assert.equal(resolveFieldRule(rules, 'a-z').tier, 'read');
  assert.equal(resolveFieldRule(rules, 'a-b-z').tier, 'label');
  assert.equal(resolveFieldRule(rules, 'a-b-c').exact, true);
  assert.equal(resolveFieldRule(rules, '_status'), null);
  assert.equal(resolveFieldRule(rules, 'nope'), null);
});
test('qc_field_rules.json carries the engine table (ids, tiers, engine lane ids)', () => {
  assert.doesNotMatch(fieldRules._status, /^provisional/);
  const keys = Object.keys(fieldRules).filter(k => !k.startsWith('_'));
  assert.equal(keys.length, 23);
  assert.deepEqual(fieldRules['typo-*'], { tier: 'read', lanes: ['typo.content'], maxLines: 2 });
  assert.deepEqual(fieldRules['stat-big-*'], { tier: 'read', lanes: ['sub'], maxLines: 1 });
  assert.deepEqual(fieldRules['stat-label-*'], { tier: 'label', lanes: ['sub'], maxLines: 1 });
  assert.deepEqual(fieldRules.caption, { tier: 'read', lanes: ['caption'], maxLines: 1 });
  assert.deepEqual(fieldRules['end-cta'], { tier: 'read', lanes: ['end.cta'], maxLines: 2 });
  assert.deepEqual(fieldRules.brand.lanes, ['header.brand']);
  assert.deepEqual(fieldRules.kicker.lanes, ['header.kicker']);
});

test('line-count: more lines than maxLines fails (headline 1, caption 1, typo-* 2, cta 2)', () => {
  const run = (id, n) => ruleLineCount(v3Snap([v3Field(id, { lineCount: n })]), t, CTX);
  assert.deepEqual(run('headline', 1), []);
  const bad = run('headline', 2);
  assert.deepEqual(ids(bad), ['line-count']); assert.equal(bad[0].maxLines, 1); assert.equal(bad[0].lineCount, 2);
  assert.deepEqual(run('caption', 1), []); assert.deepEqual(ids(run('caption', 2)), ['line-count']);
  assert.deepEqual(run('cta', 2), []); assert.deepEqual(ids(run('cta', 3)), ['line-count']);
  assert.deepEqual(run('typo-line-1', 2), []);
  assert.deepEqual(ids(run('typo-big', 3)), ['line-count']);
  assert.deepEqual(ids(run('headline', undefined)), ['line-count'], 'missing lineCount fails closed');
  assert.deepEqual(run('mystery', 9), [], 'unknown fields are reported by ruleTier');
});

test('nowrap-overflow: scrollWidth > clientWidth + 1 fails for nowrap/pre only', () => {
  const run = over => ruleNowrapOverflow(v3Snap([v3Field('x', over)]), t);
  assert.deepEqual(run({ whiteSpace: 'nowrap', scrollWidth: 201, clientWidth: 200 }), []);
  assert.deepEqual(ids(run({ whiteSpace: 'nowrap', scrollWidth: 201.5, clientWidth: 200 })), ['nowrap-overflow']);
  assert.deepEqual(ids(run({ whiteSpace: 'pre', scrollWidth: 400, clientWidth: 200 })), ['nowrap-overflow']);
  assert.deepEqual(run({ whiteSpace: 'normal', scrollWidth: 400, clientWidth: 200 }), []);
  assert.deepEqual(ids(run({ whiteSpace: 'nowrap', scrollWidth: undefined })), ['nowrap-overflow']);
});

// ======================================================================================
// Synthetic: lanes and reserved areas
// ======================================================================================

test('lane-missing / lane-forbidden / lane-overflow', () => {
  const inLane = (id, lane, extra = {}) => {
    const L = PLAN.lanes[lane] ?? PLAN.lanes['header.brand'];
    return v3Field(id, { lane, x: L.x + 10, y: L.y + 5, w: 100, h: 30, ...extra });
  };
  const run = (...fs) => ruleLane(v3Snap(fs), t, CTX);
  assert.deepEqual(run(inLane('headline', 'split.headline'), inLane('headline', 'wide.headline'), inLane('brand', 'header.brand', { tier: 'label' })), []);
  assert.deepEqual(run(v3Field('headline', { lane: null })).map(i => i.id), ['lane-missing']);
  const forb = run(inLane('headline', 'header.brand'));
  assert.deepEqual(ids(forb), ['lane-forbidden']); assert.equal(forb[0].lane, 'header.brand');
  assert.deepEqual(ids(run(inLane('headline', 'full.cta'))), ['lane-forbidden']);
  assert.deepEqual(ids(run(inLane('brand', 'header.kicker', { tier: 'label' }))), ['lane-forbidden'], 'brand may not sit in the kicker lane');
  // overflow: ink 1 px outside passes (lanePadPx = 1), 2 px outside fails
  const L = PLAN.lanes['split.headline'];
  const at = dx => v3Field('headline', { lane: 'split.headline', x: L.x + L.width - 100 + dx, y: L.y + 5, w: 100, h: 30 });
  assert.deepEqual(run(at(1)), []);
  assert.deepEqual(ids(run(at(2))), ['lane-overflow']);
  const up = v3Field('headline', { lane: 'split.headline', x: L.x + 5, y: L.y - 2, w: 100, h: 30 });
  assert.deepEqual(ids(run(up)), ['lane-overflow']);
  assert.deepEqual(ids(run(inLane('headline', 'split.headline', { inkRects: [{ x: L.x + 5, y: L.y + 5, width: 100, height: 30 }, { x: L.x + 5, y: L.y + 5, width: 100, height: 200 }] }))), ['lane-overflow']);
  assert.deepEqual(ids(run(v3Field('headline', { lane: 'no-such-lane' }))).sort(), ['lane-forbidden', 'lane-overflow']);
  assert.deepEqual(ids(ruleLane(v3Snap([]), t, { fieldRules })), ['ctx-missing']);
});
test('lane rules ignore invisible fields', () => {
  assert.deepEqual(ruleLane(v3Snap([v3Field('headline', { lane: null, opacity: 0.04 })]), t, CTX), []);
});

const bk = (id, path, box, over = {}) => ({ id, path, reserved: null, alpha: 1, opacity: 1, box, ...over });
const HEADER_BACKING = bk('header', 'div:1/div:2', { x: 116, y: 58, width: 1688, height: 48 }, { reserved: 'header' });
const CHROME_BACKING = bk('chrome', 'div:1/div:5', { x: 116, y: 112, width: 476, height: 52 }, { reserved: 'chrome' });
test('reserved-intersect: a backing that overlaps the header lane or visible reserved chrome fails', () => {
  const run = (...bs) => ruleReservedIntersect(v3Snap([], { backings: [HEADER_BACKING, CHROME_BACKING, ...bs] }), t, CTX_HEADER);
  assert.deepEqual(run(bk('pill', 'div:1/div:7', { x: 700, y: 900, width: 400, height: 60 })), []);
  const hit = run(bk('panel', 'div:1/div:8', { x: 116, y: 90, width: 600, height: 40 }));
  // zones hit: the header lane, the visible header backing and the visible chrome backing
  assert.deepEqual(hit.map(i => i.zone).sort(), ['lane:header', 'reserved:chrome', 'reserved:header']);
  assert.deepEqual(ids(run(bk('under-chrome', 'div:1/div:9', { x: 130, y: 120, width: 100, height: 30 }))), ['reserved-intersect']);
});
test('reserved-intersect: reserved backings, their ancestors/descendants, hidden backings and touching edges are exempt', () => {
  const run = (...bs) => ruleReservedIntersect(v3Snap([], { backings: [HEADER_BACKING, CHROME_BACKING, ...bs] }), t, CTX_HEADER);
  assert.deepEqual(run(bk('child', 'div:1/div:2/div:3', { x: 120, y: 60, width: 100, height: 30 })), [], 'descendant of the header backing');
  assert.deepEqual(run(bk('parent', 'div:1', { x: 100, y: 40, width: 1700, height: 100 })), [], 'ancestor of the header backing');
  assert.deepEqual(run(bk('chrome-child', 'div:1/div:5/div:6', { x: 130, y: 120, width: 100, height: 30 })), [], 'descendant of the chrome backing');
  assert.deepEqual(ids(run(bk('chrome-sibling', 'div:1/div:55', { x: 130, y: 120, width: 100, height: 30 }))), ['reserved-intersect'], '"div:5" is not a path prefix of "div:55"');
  assert.deepEqual(run(bk('hidden', 'div:1/div:8', { x: 116, y: 90, width: 600, height: 40 }, { opacity: 0.04 })), []);
  assert.deepEqual(run(bk('touch', 'div:1/div:8', { x: 116, y: 106, width: 600, height: 6 })), [], 'edges that merely touch are not an intersection');
  const hiddenChrome = bk('chrome', 'div:1/div:5', CHROME_BACKING.box, { reserved: 'chrome', opacity: 0.04 });
  assert.deepEqual(ruleReservedIntersect(v3Snap([], { backings: [HEADER_BACKING, hiddenChrome, bk('p', 'div:1/div:9', { x: 130, y: 120, width: 100, height: 30 })] }), t, CTX_HEADER), [], 'invisible chrome is not a reserved zone');
  assert.deepEqual(ids(ruleReservedIntersect(v3Snap([], { backings: undefined }), t, CTX_HEADER)), ['schema']);
  // the engine plan has no `header` lane: the reserved header backings still protect the header
  const noHeader = ruleReservedIntersect(v3Snap([], { backings: [HEADER_BACKING, bk('panel', 'div:1/div:8', { x: 116, y: 90, width: 600, height: 40 })] }), t, CTX);
  assert.deepEqual(noHeader.map(i => i.zone), ['reserved:header']);
});

test('lane-table: lanes outside the safe area or intersecting the header fail; the test plan passes', () => {
  assert.deepEqual(evaluatePlanRules(PLAN, t), []);
  assert.deepEqual(evaluatePlanRules(PLAN_WITH_HEADER, t), []);
  const withLane = (name, r) => ({ ...PLAN_WITH_HEADER, lanes: { ...PLAN_WITH_HEADER.lanes, [name]: r } });
  const outside = evaluatePlanRules(withLane('bad', { x: 50, y: 300, width: 200, height: 100 }), t);
  assert.deepEqual(outside.map(i => [i.id, i.lane]), [['lane-table', 'bad']]);
  assert.deepEqual(ids(evaluatePlanRules(withLane('bad', { x: 300, y: 1000, width: 200, height: 60 }), t)), ['lane-table']);
  const hits = evaluatePlanRules(withLane('bad', { x: 300, y: 80, width: 200, height: 60 }), t);
  assert.deepEqual(hits.map(i => i.lane), ['bad']);
  assert.deepEqual(evaluatePlanRules(withLane('header', { x: 120, y: 58, width: 1600, height: 40 }), t), [], 'the header lane itself may overlap itself');
  assert.deepEqual(ids(evaluatePlanRules(withLane('bad', { x: 300, y: 300, width: 0, height: 10 }), t)), ['lane-table']);
  assert.deepEqual(ids(ruleLaneTable(undefined, t, {})), ['ctx-missing']);
  // boundaries: right edge of the safe area is 1824, bottom 1026
  assert.deepEqual(evaluatePlanRules(withLane('edge', { x: 1624, y: 826, width: 200, height: 200 }), t), []);
  assert.deepEqual(ids(evaluatePlanRules(withLane('edge', { x: 1626, y: 826, width: 200, height: 200 }), t)), ['lane-table']);
});

// ======================================================================================
// evaluateLayout end to end
// ======================================================================================

function validSnapshot() {
  const headline = v3Field('headline', { lane: 'split.headline', x: 128, y: 712, w: 800, h: 52 });
  const kicker = v3Field('kicker', { tier: 'label', lane: 'header.kicker', x: 1546, y: 66, w: 258, h: 34 });
  return v3Snap([headline, kicker]);
}
test('evaluateLayout: a fully valid schema-3 snapshot with the real field rules passes', () => {
  assert.deepEqual(evaluateLayout(validSnapshot(), t, CTX).issues, []);
});
test('evaluateLayout: a V2-shaped snapshot is a single schema issue (fail closed)', () => {
  const out = evaluateLayout({ ...validSnapshot(), schemaVersion: 2 }, t, CTX).issues;
  assert.deepEqual(ids(out), ['schema']);
  assert.deepEqual(ids(evaluateLayout(loadRaw(RAW[1875]), t, CTX).issues), ['schema']);
  assert.deepEqual(ids(ruleSchema({ ...validSnapshot(), layers: undefined }, t, CTX)), ['schema']);
  assert.deepEqual(ids(ruleSchema({ ...validSnapshot(), phase: 'later' }, t, CTX)), ['schema']);
});
test('evaluateLayout: every new defect class is reported through the full rule list', () => {
  const s = validSnapshot();
  field(s, 'headline').lane = null;                  // lane-missing
  field(s, 'headline').colorAlpha = 0.5;             // text-alpha
  field(s, 'headline').fontSize = 30;                // font
  s.fields.push(v3Field('mystery', { lane: 'full.cta', x: 130, y: 820 }));   // unknown-field
  s.layers = [];                                     // content-presence
  const got = new Set(ids(evaluateLayout(s, t, CTX).issues));
  for (const id of ['lane-missing', 'text-alpha', 'font', 'unknown-field', 'content-presence']) assert.ok(got.has(id), `${id} missing from ${[...got]}`);
});
test('probe-issues: snapshot.probeIssues surface as gate issues with the same ids; absent or empty is clean', () => {
  const s = validSnapshot();
  assert.deepEqual(ruleProbeIssues(s), []);
  assert.deepEqual(ruleProbeIssues({ ...s, probeIssues: [] }), []);
  s.probeIssues = [{ id: 'untagged-text', field: 'mystery', message: 'text without data-qc-field' }, { id: 'unsupported-transform', message: 'zoom on ancestor' }];
  const out = ruleProbeIssues(s);
  assert.deepEqual(out.map(i => [i.id, i.field]), [['untagged-text', 'mystery'], ['unsupported-transform', undefined]]);
  assert.ok(out.every(i => i.frame === s.frame && i.message));
  assert.deepEqual(ids(evaluateLayout(s, t, CTX).issues).filter(id => id !== 'content-presence').sort(), ['unsupported-transform', 'untagged-text']);
  assert.deepEqual(ids(ruleProbeIssues({ ...s, probeIssues: 'bad' })), ['probe-issues']);
  assert.deepEqual(evaluateLayout(validSnapshot(), t, CTX).issues, []);
});
test('evaluateLayout: lane-less V3-style fields all fail lane-missing (fail-closed proof)', () => {
  const s = validSnapshot();
  for (const f of s.fields) f.lane = null;
  const out = evaluateLayout(s, t, CTX).issues.filter(i => i.id === 'lane-missing');
  assert.equal(out.length, s.fields.length);
});
