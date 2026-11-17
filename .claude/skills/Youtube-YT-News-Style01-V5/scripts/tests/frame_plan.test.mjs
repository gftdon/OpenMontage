import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import { buildFramePlan } from '../qc_layout_eval.mjs';
import { thresholds } from './fixtures/v3/builders.mjs';

// A threshold set without the grid (stride larger than any plan) isolates the windows under test.
const NO_GRID = { ...thresholds, gridStrideFrames: 1_000_000 };
const range = (a, b) => Array.from({ length: b - a + 1 }, (_, i) => a + i);
const plan = (over = {}) => ({
  planVersion: 2, fps: 25, durationInFrames: 1000, voEndFrame: 900, frames: [], sweepWindows: [], beats: [], ...over,
});
const beat = (index, t, startFrame = Math.round(t * 25)) => ({ index, t, startFrame, mode: 'full', layout: 'full', origin: 'stock', media: 'x' });

test('thresholds carry the frame-plan keys', () => {
  for (const [k, v] of Object.entries({ gridStrideFrames: 25, beatWindowPreFrames: 2, beatWindowPostSec: 0.55, beatWindowPostExtraFrames: 3 })) assert.equal(thresholds[k], v);
});

test('result is sorted and de-duplicated across engine frames, sweep windows, grid and beat windows', () => {
  const p = plan({ frames: [500, 3, 500, 3, 250], sweepWindows: [{ id: 'w', beatT: 8, startFrame: 198, endFrame: 204 }], beats: [beat(0, 0), beat(1, 8)] });
  const out = buildFramePlan(p, thresholds);
  assert.deepEqual(out, [...new Set(out)].sort((a, b) => a - b));
  for (const f of [3, 250, 500, ...range(198, 204)]) assert.ok(out.includes(f), `frame ${f}`);
});

test('grid: every multiple of gridStrideFrames below the duration, none at or above it', () => {
  const out = buildFramePlan(plan({ durationInFrames: 101, voEndFrame: 50 }), { ...thresholds, gridStrideFrames: 25 });
  for (const f of [0, 25, 50, 75, 100]) assert.ok(out.includes(f));
  assert.ok(!out.includes(26) && !out.includes(60));
  // voEndFrame far beyond the video clamps onto the last frame (99); grid multiples of 40 below 100 are 0, 40, 80
  assert.deepEqual(buildFramePlan(plan({ durationInFrames: 100, voEndFrame: 10_000 }), { ...NO_GRID, gridStrideFrames: 40 }), [0, 40, 80, 99]);
});

test('a window around every beat boundary i>=1: [start-2, ceil((t+0.55)*fps)+3]; beat 0 gets none', () => {
  const p = plan({ beats: [beat(0, 0, 0), beat(1, 4, 100), beat(2, 10.2, 255)], voEndFrame: 900 });
  const out = buildFramePlan(p, NO_GRID);
  const w1 = range(98, Math.ceil(4.55 * 25) + 3);                  // 98..117
  const w2 = range(253, Math.ceil(10.75 * 25) + 3);                // 253..272 (ceil(268.75)=269 -> 272)
  assert.deepEqual(w1, range(98, 117)); assert.deepEqual(w2, range(253, 272));
  for (const f of [...w1, ...w2]) assert.ok(out.includes(f), `frame ${f}`);
  for (const f of [97, 118, 252, 273]) assert.ok(!out.includes(f), `frame ${f} must be outside`);
  assert.ok(!out.includes(1) && !out.includes(5), 'beat 0 gets no window (only frame 0 from the grid)');
  assert.deepEqual(out.filter(f => f < 98), [0]);
});

test('beat window upper bound is stable against float error (1.45 + 0.55 -> 2.0 s -> frame 50 + 3)', () => {
  const out = buildFramePlan(plan({ beats: [beat(1, 1.45, 36)], voEndFrame: 900 }), NO_GRID);
  assert.ok(out.includes(53)); assert.ok(!out.includes(54));
});

test('VO-end window [voEndFrame-2, voEndFrame+3]', () => {
  const out = buildFramePlan(plan({ voEndFrame: 777 }), NO_GRID);
  for (const f of range(775, 780)) assert.ok(out.includes(f));
  assert.ok(!out.includes(774) && !out.includes(781));
});

test('everything is clamped to [0, durationInFrames-1]', () => {
  const p = plan({
    durationInFrames: 100, voEndFrame: 98, frames: [-7, 5000],
    sweepWindows: [{ id: 'w', beatT: 0, startFrame: -5, endFrame: 3 }],
    beats: [beat(1, 0.04, 1), beat(2, 3.8, 95)],
  });
  const out = buildFramePlan(p, NO_GRID);
  assert.equal(Math.min(...out), 0); assert.equal(Math.max(...out), 99);
  assert.ok(out.every(f => Number.isInteger(f) && f >= 0 && f <= 99));
  for (const f of [0, 1, 2, 3, 93, 94, 95, 96, 97, 98, 99]) assert.ok(out.includes(f), `frame ${f}`);
  // a VO end past the last frame cannot add frames beyond it
  assert.ok(Math.max(...buildFramePlan(plan({ durationInFrames: 100, voEndFrame: 150 }), NO_GRID)) <= 99);
});

test('deterministic: same plan -> identical output, input never mutated, beat order irrelevant', () => {
  const p = plan({ frames: [10, 5], beats: [beat(2, 10.2, 255), beat(1, 4, 100)], sweepWindows: [{ id: 'w', startFrame: 1, endFrame: 4 }] });
  const frozen = JSON.parse(JSON.stringify(p));
  const a = buildFramePlan(p, thresholds), b = buildFramePlan(JSON.parse(JSON.stringify(p)), thresholds);
  assert.deepEqual(a, b);
  assert.deepEqual(p, frozen);
  assert.deepEqual(buildFramePlan({ ...p, beats: [...p.beats].reverse() }, thresholds), a);
  const sha = x => crypto.createHash('sha256').update(JSON.stringify(x)).digest('hex');
  assert.equal(sha(a), sha(b));
});

test('V261111-sized plan: 16,296 frames, 75 beats -> grid + windows, all in range', () => {
  const beats = Array.from({ length: 75 }, (_, i) => beat(i, i * 8.6, Math.round(i * 8.6 * 25)));
  const out = buildFramePlan(plan({ durationInFrames: 16296, voEndFrame: 16183, beats, frames: [0, 16295] }), thresholds);
  assert.ok(out.length >= Math.ceil(16296 / 25));                  // at least the 652 grid frames
  assert.ok(out.length < 16296 / 4);
  assert.ok(out.every(f => f >= 0 && f <= 16295));
  for (const b of beats.slice(1)) for (const f of [b.startFrame - 2, b.startFrame + 10]) assert.ok(out.includes(f));
  assert.ok(out.includes(16181) && out.includes(16186));
});

test('malformed plans fail closed (throw)', () => {
  for (const bad of [null, plan({ durationInFrames: 0 }), plan({ fps: 0 }), plan({ voEndFrame: 1.5 }), plan({ frames: [1.5] }),
    plan({ frames: 'x' }), plan({ beats: [{ index: 1, t: 2 }] }), plan({ sweepWindows: [{ id: 'w', startFrame: 1 }] })]) {
    assert.throws(() => buildFramePlan(bad, thresholds), TypeError);
  }
  assert.throws(() => buildFramePlan(plan(), { ...thresholds, gridStrideFrames: undefined }), TypeError);
  assert.throws(() => buildFramePlan(plan(), { ...thresholds, gridStrideFrames: 0 }), TypeError);
});
