// Typo cards (CF-A66 step 3): rows / chips keep their own staggered entrance but never start before the scene's labelDelay.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { loadEngine } from './_engine_bundle.mjs';
const root = path.resolve(new URL('../../../../..', import.meta.url).pathname);
const source = fs.readFileSync(path.join(root, 'remotion-composer/src/YtNewsStyle01V4.tsx'), 'utf8');
const sampleBeats = JSON.parse(fs.readFileSync(path.join(root, 'remotion-composer/src/ytNewsStyle01V4Sample.json'), 'utf8')).beats;
const fps = 25;
const { layerPlan, sceneKind, IN_F, XF_F, entranceStartSec } = await loadEngine();
const startOf = (i) => Math.ceil(sampleBeats[i].t * fps);
const typoIdx = sampleBeats.map((b, i) => (b.media === 'typo' ? i : -1)).filter((i) => i >= 0);

test('constants and engine wiring: MODE_BLEND_SEC stays .55, IN_F covers it, typo content uses the shared label entrance', () => {
  assert.match(source, /const MODE_BLEND_SEC = 0\.55;/);
  assert.ok(IN_F / fps >= 0.55 && (IN_F - 1) / fps < 0.55);
  assert.ok(source.includes('chipEntrance(labels.t, Math.max(item.at, labels.startSec), labels.fps)'), 'chips wait for the label start');
  assert.ok(source.includes('...enter(labels, card?.at ?? beat.t)'), 'card rows wait for the label start');
});

test('the frames that failed before (1870, 2870, 3594) land on a typo beat that follows a presenter and are still inside the label delay', () => {
  for (const frame of [1870, 2870, 3594]) {
    const p = layerPlan(frame, sampleBeats, fps);
    assert.equal(sampleBeats[p.index].media, 'typo');
    assert.equal(p.prevKind, 'P');
    assert.equal(p.labelDelayFrames, IN_F);
    assert.ok(frame < p.labelStartFrame, `frame ${frame} must precede label start ${p.labelStartFrame}`);
  }
});

test('every typo card, chip and row starts no earlier than the beat labelDelay; later ones keep their own time (no replayed delay)', () => {
  let later = 0, first = 0;
  for (const i of typoIdx) {
    const b = sampleBeats[i], p = layerPlan(startOf(i), sampleBeats, fps), ls = p.labelStartFrame / fps;
    const timed = b.typo === 'vs' ? [b.t] : [...(b.cards ?? []).map((c) => c.at), ...(b.items ?? []).map((it) => it.at)]; // vs has no per-row times: the whole card enters at the beat start
    assert.ok(timed.length, `typo beat ${b.t} has no timed content`);
    for (const at of timed) {
      const s = entranceStartSec(at, p, fps);
      assert.ok(s >= ls && s >= at, `beat ${b.t}: entrance ${s} before label start ${ls}`);
      if (at >= ls) { assert.equal(s, at); later++; } else { assert.equal(s, ls); first++; }
    }
  }
  assert.ok(first >= 10 && later >= 8, `first=${first} later=${later}`);
});

test('multi-card and multi-item beats: the 2nd+ entries come from cards[].at / items[].at and are not delayed again', () => {
  const multi = typoIdx.filter((i) => (sampleBeats[i].cards?.length ?? 0) >= 2 || (sampleBeats[i].items?.length ?? 0) >= 2);
  assert.ok(multi.length >= 6);
  for (const i of multi) {
    const b = sampleBeats[i], p = layerPlan(startOf(i), sampleBeats, fps);
    const list = b.cards ?? b.items;
    assert.ok(list[0].at >= b.t - 1e-9);
    for (const entry of list.slice(1)) { assert.ok(entry.at > list[0].at, `beat ${b.t}: entries are increasing`); assert.equal(entranceStartSec(entry.at, p, fps), entry.at, `beat ${b.t}: entry at ${entry.at}`); }
  }
});

test('a T beat that follows a T beat waits XF_F (the new card is opaque first); one that follows S starts immediately; one that follows P / W waits IN_F', () => {
  for (const i of typoIdx) {
    if (i === 0) continue;
    const p = layerPlan(startOf(i), sampleBeats, fps), prev = sceneKind(sampleBeats[i - 1]);
    assert.equal(p.labelDelayFrames, prev === 'T' ? XF_F : prev === 'S' ? 0 : IN_F, `beat ${i} after ${prev}`);
  }
});
