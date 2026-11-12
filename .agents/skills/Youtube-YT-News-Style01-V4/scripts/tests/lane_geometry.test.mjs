// CF-A66 round 10: lane geometry. The four text lanes that grew (typo.content, split.headline, sub, wide.headline) must still not
// collide with anything else in their scene and must stay inside their backings. Touching edges are allowed; overlap > 0 px fails.
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadEngine } from './_engine_bundle.mjs';

const { LANES } = await loadEngine();
const KINDS = ['P', 'S', 'T', 'W'];
const overlapArea = (a, b) => Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x)) * Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));
const inside = (a, b) => a.x >= b.x && a.y >= b.y && a.x + a.w <= b.x + b.w && a.y + a.h <= b.y + b.h;
const textLanes = (kind) => Object.entries(LANES).filter(([, l]) => l.role === 'text' && l.scenes.includes(kind));
const PICTURE = { S: 'split.picture', W: 'wide.picture' };
// Pre-existing overlaps that are intended (none today). Add `${kind}: ${a} / ${b}` here with a reason, never silently.
const EXCEPTIONS = new Set([]);
// Pre-existing, unrelated to this round: in W the presenter card is hidden (see the `avatar` lane comment in the engine), so the `avatar`
// rect is not on screen there and text lanes (wide.chrome.label overlaps it by 9680 px2) are allowed to sit over it.
const PRESENTER_HIDDEN_IN = new Set(['W']);

test('per scene kind (P S T W): text lanes do not intersect each other, the picture lane or the presenter card lane', () => {
  for (const kind of KINDS) {
    const text = textLanes(kind);
    assert.ok(text.length >= 4, kind);
    for (let i = 0; i < text.length; i++) for (let j = i + 1; j < text.length; j++) {
      const key = `${kind}: ${text[i][0]} / ${text[j][0]}`;
      assert.ok(EXCEPTIONS.has(key) || overlapArea(text[i][1], text[j][1]) === 0, `${key} overlap ${overlapArea(text[i][1], text[j][1])} px2`);
    }
    const others = [];
    if (PICTURE[kind]) others.push([PICTURE[kind], LANES[PICTURE[kind]]]);
    if (LANES.avatar.scenes.includes(kind) && !PRESENTER_HIDDEN_IN.has(kind)) others.push(['avatar', LANES.avatar]); // avatar.full (P) is the whole frame and is skipped
    for (const [id, l] of text) for (const [oid, o] of others) {
      const key = `${kind}: ${id} / ${oid}`;
      assert.ok(EXCEPTIONS.has(key) || overlapArea(l, o) === 0, `${key} overlap ${overlapArea(l, o)} px2`);
    }
  }
});

test('the four lanes that grew in round 10 have the new geometry', () => {
  const r = (id) => [LANES[id].x, LANES[id].y, LANES[id].w, LANES[id].h];
  assert.deepEqual(r('typo.content'), [116, 172, 1138, 676]);
  assert.deepEqual(r('split.headline'), [112, 814, 1146, 62]);
  assert.deepEqual(r('sub'), [112, 876, 1146, 60]);
  assert.deepEqual(r('wide.headline'), [340, 874, 1240, 62]);
});

test('containment: text lanes inside their backings', () => {
  assert.ok(inside(LANES['typo.content'], LANES['typo.backing']), 'typo.content in typo.backing');
  assert.ok(inside(LANES['split.headline'], LANES['split.lower']), 'split.headline in split.lower');
  assert.ok(inside(LANES.sub, LANES['split.lower']), 'sub in split.lower (S)');
  assert.ok(inside(LANES['wide.headline'], LANES['wide.bar']), 'wide.headline in wide.bar');
  for (const id of ['split.chrome.url', 'split.chrome.label']) assert.ok(inside(LANES[id], LANES['split.chrome']), `${id} in split.chrome`);
  for (const id of ['wide.chrome.url', 'wide.chrome.label']) assert.ok(inside(LANES[id], LANES['wide.chrome']), `${id} in wide.chrome`);
});

test('the growth is side-bearing room only: the laid-out text box (lane minus 4 px each side, and 6 / 2 px above) is where it was', () => {
  const box = (id, top) => [LANES[id].x + 4, LANES[id].y + top, LANES[id].w - 8];
  assert.deepEqual(box('typo.content', 0), [120, 172, 1130]);
  assert.deepEqual(box('split.headline', 6), [116, 820, 1138]);
  assert.deepEqual(box('sub', 2), [116, 878, 1138]);
  assert.deepEqual(box('wide.headline', 6), [344, 880, 1232]);
});

// ---- Round 11: the CTA lane is as wide as the caption lane (a 40-character Thai CTA fits one line) -----------------------
test('full.cta has the caption lane x and width (96, 1728), the same 722..872 band, and touches no other P text lane', () => {
  const c = LANES['full.cta'];
  assert.deepEqual([c.x, c.y, c.w, c.h], [96, 722, 1728, 150]);
  assert.equal(c.x, LANES.caption.x); assert.equal(c.w, LANES.caption.w);
  for (const [id, l] of textLanes('P')) if (id !== 'full.cta') assert.equal(overlapArea(c, l), 0, `full.cta / ${id}`);
  assert.deepEqual([LANES['full.lowerThird'].x, LANES['full.lowerThird'].y, LANES['full.lowerThird'].w, LANES['full.lowerThird'].h], [96, 520, 960, 196]);
});
