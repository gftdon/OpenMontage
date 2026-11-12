import test from 'node:test';
import assert from 'node:assert/strict';
import { loadEngine } from './_engine_bundle.mjs';

const { LANES, sceneKind } = await loadEngine();
const KINDS = ['P', 'S', 'T', 'W', 'E'];
const textLanes = (kind) => Object.entries(LANES).filter(([, l]) => l.role === 'text' && l.scenes.includes(kind));
const overlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h; // half-open

test('no two text lanes of one scene kind overlap', () => {
  for (const kind of KINDS) {
    const lanes = textLanes(kind);
    assert.ok(lanes.length >= 4, kind);
    for (let i = 0; i < lanes.length; i++) for (let j = i + 1; j < lanes.length; j++) assert.equal(overlap(lanes[i][1], lanes[j][1]), false, `${kind}: ${lanes[i][0]} overlaps ${lanes[j][0]}`);
  }
});

test('every text lane lies inside the 5% safe area (x 96..1824, y 54..1026)', () => {
  for (const kind of KINDS) for (const [id, l] of textLanes(kind)) {
    assert.ok(l.x >= 96 && l.y >= 54 && l.x + l.w <= 1824 && l.y + l.h <= 1026, `${kind}: ${id} ${JSON.stringify([l.x, l.y, l.w, l.h])} leaves the safe area`);
  }
});

test('text lanes of S and T do not touch the presenter card', () => {
  for (const kind of ['S', 'T']) for (const [id, l] of textLanes(kind)) assert.equal(overlap(l, LANES.avatar), false, `${kind}: ${id} overlaps the presenter card`);
});

test('geometry fixed by the minimum-font decision (header lanes 44 px, card and stage start at y=100)', () => {
  const r = (id) => { const l = LANES[id]; return [l.x, l.y, l.w, l.h]; };
  assert.deepEqual(r('header.brand'), [96, 54, 480, 44]);
  assert.deepEqual(r('header.kicker'), [1344, 54, 480, 44]);
  assert.deepEqual(r('avatar'), [1362, 100, 478, 850]);
  assert.equal(LANES.avatar.r, 26);
  assert.deepEqual(r('stage'), [80, 100, 1210, 840]);
  assert.deepEqual(r('split.chrome'), [80, 100, 1210, 52]);
  assert.deepEqual(r('sub'), [112, 876, 1146, 60]);
  assert.deepEqual(r('split.headline'), [112, 814, 1146, 62]);
  assert.deepEqual(r('wide.headline'), [340, 874, 1240, 62]);
  assert.deepEqual(r('typo.content'), [116, 172, 1138, 676]);
  assert.deepEqual(r('wide.window'), [320, 100, 1280, 844]);
  assert.deepEqual(r('wide.picture'), [320, 152, 1280, 720]);
  assert.deepEqual(r('caption'), [96, 954, 1728, 72]);
});

test('layers and backings nest as designed', () => {
  const inside = (a, b) => a.x >= b.x && a.y >= b.y && a.x + a.w <= b.x + b.w && a.y + a.h <= b.y + b.h;
  for (const id of ['split.chrome', 'split.picture', 'split.lower', 'typo.backing']) assert.ok(inside(LANES[id], LANES.stage), id);
  for (const id of ['wide.chrome', 'wide.picture', 'wide.bar']) assert.ok(inside(LANES[id], LANES['wide.window']), id);
  assert.ok(inside(LANES['split.headline'], LANES['split.lower']) && inside(LANES.sub, LANES['split.lower']));
  assert.ok(inside(LANES['typo.content'], LANES['typo.backing']));
  assert.ok(inside(LANES['wide.headline'], LANES['wide.bar']));
  assert.ok(inside(LANES['split.chrome.url'], LANES['split.chrome']) && inside(LANES['split.chrome.label'], LANES['split.chrome']));
  assert.ok(inside(LANES['wide.chrome.url'], LANES['wide.chrome']) && inside(LANES['wide.chrome.label'], LANES['wide.chrome']));
});

test('sceneKind maps the beat shapes', () => {
  assert.equal(sceneKind({ t: 0, mode: 'full' }), 'P');
  assert.equal(sceneKind({ t: 1, mode: 'pip', media: 'broll', layout: 'stage' }), 'S');
  assert.equal(sceneKind({ t: 1, mode: 'pip', media: 'clip', layout: 'stage' }), 'S');
  assert.equal(sceneKind({ t: 1, mode: 'pip', media: 'typo', layout: 'stage' }), 'T');
  assert.equal(sceneKind({ t: 1, mode: 'pip', media: 'clip', layout: 'wide' }), 'W');
});
