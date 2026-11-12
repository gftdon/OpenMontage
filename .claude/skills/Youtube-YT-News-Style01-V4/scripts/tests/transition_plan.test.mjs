// CF-A66 step 3: the pure layerPlan(frame, beats) must never show a frame that is emptier than both scenes.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { loadEngine } from './_engine_bundle.mjs';
const root = path.resolve(new URL('../../../../..', import.meta.url).pathname);
const episode = JSON.parse(fs.readFileSync(path.join(root, 'remotion-composer/src/ytNewsStyle01V4Sample.json'), 'utf8'));
const beats = episode.beats;
const fps = 25;
const { layerPlan, sceneKind, IN_F, XF_F, OUT_F, LANES, labelDelayFor } = await loadEngine();
const lastFrame = Math.ceil(episode.voEndSec * fps) - 1;
const startOf = (i) => Math.ceil(beats[i].t * fps);
const kinds = beats.map(sceneKind);
const Z = (k) => k === 'S' || k === 'T';
const grp = (k) => (Z(k) ? 'Z' : k);
const in01 = (x) => Number.isFinite(x) && x >= 0 && x <= 1;
const open01 = (x) => x > 0 && x < 1;
const FULL = LANES['avatar.full'], CARD = LANES.avatar;
const sameRect = (r, l) => r.x === l.x && r.y === l.y && r.w === l.w && r.h === l.h && r.r === l.r;

// §5 table, last column (labelDelay)
const expectedDelay = (p, c) => (p === null ? 0 : p === 'T' && (c === 'T' || c === 'S') ? XF_F : (Z(p) && Z(c)) || (p === 'W' && c === 'W') || (p === 'P' && c === 'P') ? 0 : IN_F);

test('constants: IN_F=14 (ceil(.55 s)), XF_F=9, OUT_F=9', () => {
  assert.deepEqual([IN_F, XF_F, OUT_F], [14, 9, 9]);
  assert.equal(Math.ceil(0.55 * fps), IN_F);
});

test('every frame before voEndSec: <=1 outgoing layer, opacities in [0,1], coverage invariant, label delay per table, no rect interpolation while faded', () => {
  let frames = 0, active = 0;
  for (let frame = 0; frame <= lastFrame; frame++) {
    const p = layerPlan(frame, beats, fps);
    frames++;
    const where = `frame ${frame}`;
    assert.ok(p.outgoingCount <= 1, `${where}: ${p.outgoingCount} outgoing layers`);
    assert.equal(p.layers.filter((l) => l.role === 'outgoing').length, p.outgoingCount, where);
    assert.ok(p.layers.filter((l) => l.role === 'current').length <= 1, where);
    for (const [n, v] of [['stage', p.stage.opacity], ['wide', p.wide.opacity], ['avatar', p.avatar.opacity], ['cropProgress', p.avatar.cropProgress], ...p.layers.map((l) => [l.key, l.opacity])]) assert.ok(in01(v), `${where}: ${n} opacity ${v} outside [0,1]`);
    // independent coverage recompute from the raw plan (not from p.coverageOk)
    const eff = (l) => l.opacity * (l.frame === 'stage' ? p.stage.opacity : p.wide.opacity);
    const cur = p.layers.find((l) => l.role === 'current'), out = p.layers.find((l) => l.role === 'outgoing');
    const incoming = p.kind === 'P' ? p.avatar.opacity : eff(cur);
    assert.ok(incoming >= 1 || (out && eff(out) >= 1), `${where} (${p.boundary}, f=${p.localFrame}): incoming ${incoming} while outgoing ${out ? eff(out) : 'none'} — a darker/emptier frame`);
    assert.equal(p.coverageOk, true, where);
    if (cur) assert.equal(cur.index, p.index, where);
    // label delay column
    assert.equal(p.labelDelayFrames, expectedDelay(p.prevKind, p.kind), `${where} ${p.boundary}`);
    assert.equal(p.labelDelayFrames, labelDelayFor(p.prevKind, p.kind));
    assert.equal(p.labelStartFrame, p.startFrame + p.labelDelayFrames);
    // outgoing labels never render; current labels do
    for (const l of p.layers) assert.equal(l.labels, l.role === 'current', where);
    // the presenter rect is interpolated only while it is fully visible
    if (p.avatar.interpolated) assert.equal(p.avatar.opacity, 1, `${where}: rect morph while opacity ${p.avatar.opacity}`);
    if (p.avatar.opacity < 1) assert.ok(sameRect(p.avatar.rect, FULL) || sameRect(p.avatar.rect, CARD), `${where}: faded presenter has an interpolated rect`);
    // at most one frame of the same kind is mounted per z; outgoing frame sits below the incoming one
    if (p.stage.mounted && p.wide.mounted) assert.notEqual(p.stage.z, p.wide.z, where);
    if (p.transitionActive) active++;
  }
  assert.ok(frames > 8000 && active > 600, `frames=${frames} active=${active}`);
});

// A complete expectation per boundary type. Each case: [boundaryType, mid frames to probe]
const firstOf = (type) => { const i = beats.findIndex((b, k) => k > 0 && `${kinds[k - 1]}>${kinds[k]}` === type); return i; };
const TYPES = ['P>S', 'P>T', 'P>W', 'S>P', 'T>P', 'W>P', 'S>S', 'S>T', 'T>S', 'T>T', 'S>W', 'W>S', 'W>T', 'W>W', 'T>W', 'P>P'];

test('the sample exercises all 16 boundary types', () => {
  for (const t of TYPES) assert.ok(firstOf(t) > 0, `sample has no ${t} boundary`);
});

const at = (type, f) => { const i = firstOf(type); return layerPlan(startOf(i) + f, beats, fps); };
const roles = (p) => p.layers.map((l) => `${l.role}:${l.kind}`);

for (const type of TYPES) {
  const [pk, ck] = type.split('>');
  test(`boundary ${type}: plan at f=0, mid and after completion`, () => {
    const p0 = at(type, 0), done = at(type, IN_F + OUT_F);
    assert.equal(p0.boundary, type);
    assert.equal(p0.labelDelayFrames, expectedDelay(pk, ck));
    // after completion: a settled plan — one current layer (none on P), no outgoing, presenter in its steady state
    assert.equal(done.transitionActive, false);
    assert.equal(done.outgoingCount, 0);
    assert.deepEqual(roles(done), ck === 'P' ? [] : [`current:${ck}`]);
    assert.equal(done.stage.mounted, Z(ck));
    assert.equal(done.wide.mounted, ck === 'W');
    assert.equal(done.avatar.opacity, ck === 'W' ? 0 : 1);
    assert.ok(sameRect(done.avatar.rect, ck === 'P' ? FULL : CARD));
    assert.equal(done.avatar.interpolated, false);
    assert.equal(done.avatar.cropProgress, ck === 'P' ? 0 : 1);
    for (const l of done.layers) assert.equal(l.opacity, 1);

    if (type === 'P>P') {
      for (const f of [0, 3, 8, 14]) { const p = at(type, f); assert.equal(p.transitionActive, false); assert.equal(p.layers.length, 0); assert.ok(sameRect(p.avatar.rect, FULL)); assert.equal(p.avatar.opacity, 1); }
      return;
    }
    const mid = at(type, Math.floor(IN_F / 2));
    if (pk === 'P' && Z(ck)) { // P->S/T: stage already at 1 under the full-bleed presenter, rect morphs full -> card
      assert.deepEqual([p0.stage.mounted, p0.stage.opacity, p0.layers.length, p0.layers[0].opacity], [true, 1, 1, 1]);
      assert.ok(sameRect(p0.avatar.rect, FULL) && p0.avatar.opacity === 1 && p0.avatar.interpolated && p0.avatar.cropProgress === 0);
      assert.ok(mid.avatar.interpolated && open01(mid.avatar.cropProgress) && mid.avatar.rect.w < 1920 && mid.avatar.rect.w > CARD.w);
      assert.equal(mid.stage.opacity, 1);
    } else if (Z(pk) && ck === 'P') { // S/T->P: outgoing stage holds under the growing presenter, unmounts at f=IN_F
      assert.deepEqual(roles(p0), ['outgoing:' + pk]);
      assert.ok(p0.stage.mounted && p0.stage.opacity === 1 && p0.layers[0].opacity === 1);
      assert.ok(sameRect(p0.avatar.rect, CARD) && p0.avatar.cropProgress === 1 && p0.avatar.interpolated);
      assert.ok(mid.avatar.interpolated && open01(mid.avatar.cropProgress) && mid.stage.opacity === 1 && mid.layers[0].opacity === 1);
      assert.equal(at(type, IN_F - 1).outgoingCount, 1);
      assert.equal(at(type, IN_F).outgoingCount, 0);
    } else if (Z(pk) && Z(ck)) { // same frame: incoming layer fades 0->1 over XF_F above a holding outgoing layer
      assert.deepEqual(roles(p0), ['outgoing:' + pk, 'current:' + ck]);
      assert.deepEqual([p0.layers[0].opacity, p0.layers[1].opacity, p0.stage.opacity], [1, 0, 1]);
      const m = at(type, 4); assert.ok(open01(m.layers[1].opacity) && m.layers[0].opacity === 1, 'mid: incoming rising, outgoing holds');
      const h = at(type, XF_F); assert.deepEqual([h.layers[0].opacity, h.layers[1].opacity], [1, 1]);
      const fo = at(type, XF_F + 4); assert.ok(open01(fo.layers[0].opacity) && fo.layers[1].opacity === 1, 'outgoing fades only after the incoming layer reached 1');
      assert.equal(at(type, XF_F + OUT_F - 1).outgoingCount, 1); assert.equal(at(type, XF_F + OUT_F).outgoingCount, 0);
      assert.ok(p0.avatar.opacity === 1 && !p0.avatar.interpolated && sameRect(p0.avatar.rect, CARD));
    } else if (Z(pk) && ck === 'W') { // wide window 0->1 above the holding stage but BELOW the presenter, who fades out while the window arrives
      assert.deepEqual([p0.wide.mounted, p0.wide.opacity, p0.stage.mounted, p0.stage.opacity, p0.avatar.opacity], [true, 0, true, 1, 1]);
      assert.ok(p0.wide.z > p0.stage.z && p0.wide.z < 20, 'incoming wide window is above the leaving stage and under the presenter (no empty window painted over her)');
      assert.deepEqual(roles(p0), ['outgoing:' + pk, 'current:W']);
      assert.ok(open01(mid.wide.opacity) && mid.stage.opacity === 1 && open01(mid.avatar.opacity), 'presenter fades while the window rises');
      const h = at(type, IN_F); assert.deepEqual([h.wide.opacity, h.stage.opacity, h.avatar.opacity], [1, 1, 0]);
      const fo = at(type, IN_F + 4); assert.ok(open01(fo.stage.opacity) && fo.avatar.opacity === 0 && fo.wide.opacity === 1);
      assert.ok(sameRect(fo.avatar.rect, CARD) && !fo.avatar.interpolated);
      assert.equal(at(type, IN_F + OUT_F - 1).stage.mounted, true); assert.equal(at(type, IN_F + OUT_F).stage.mounted, false);
    } else if (pk === 'W' && Z(ck)) { // stage + scene 0->1 above the wide window, presenter fades in, wide holds then fades
      assert.deepEqual([p0.stage.mounted, p0.stage.opacity, p0.wide.mounted, p0.wide.opacity, p0.avatar.opacity], [true, 0, true, 1, 0]);
      assert.ok(p0.stage.z > p0.wide.z);
      assert.deepEqual(roles(p0), ['outgoing:W', 'current:' + ck]);
      assert.ok(open01(mid.stage.opacity) && open01(mid.avatar.opacity) && mid.wide.opacity === 1 && sameRect(mid.avatar.rect, CARD) && !mid.avatar.interpolated);
      const h = at(type, IN_F); assert.deepEqual([h.stage.opacity, h.wide.opacity, h.avatar.opacity], [1, 1, 1]);
      const fo = at(type, IN_F + 4); assert.ok(open01(fo.wide.opacity) && fo.stage.opacity === 1);
      assert.equal(at(type, IN_F + OUT_F - 1).wide.mounted, true); assert.equal(at(type, IN_F + OUT_F).wide.mounted, false);
    } else if (pk === 'W' && ck === 'W') { // persistent wide frame; picture 0->1 over XF_F, outgoing holds then fades
      assert.deepEqual(roles(p0), ['outgoing:W', 'current:W']);
      assert.deepEqual([p0.layers[0].opacity, p0.layers[1].opacity, p0.wide.opacity, p0.wide.mounted], [1, 0, 1, true]);
      const m = at(type, 4); assert.ok(open01(m.layers[1].opacity) && m.layers[0].opacity === 1);
      const fo = at(type, XF_F + 4); assert.ok(open01(fo.layers[0].opacity) && fo.layers[1].opacity === 1);
      assert.equal(p0.avatar.opacity, 0); assert.equal(p0.stage.mounted, false);
    } else if (pk === 'P' && ck === 'W') { // wide at 1 from f=0 under the presenter, which fades 1->0 at its full rect
      assert.deepEqual([p0.wide.mounted, p0.wide.opacity, p0.layers.length, p0.layers[0].opacity], [true, 1, 1, 1]);
      assert.ok(p0.wide.z < 20, 'wide window sits under the presenter');
      assert.ok(sameRect(p0.avatar.rect, FULL) && p0.avatar.opacity === 1 && !p0.avatar.interpolated);
      assert.ok(open01(mid.avatar.opacity) && sameRect(mid.avatar.rect, FULL) && !mid.avatar.interpolated);
      assert.equal(at(type, IN_F).avatar.opacity, 0);
    } else if (pk === 'W' && ck === 'P') { // outgoing wide holds at 1 until the presenter (above) is fully in
      assert.deepEqual(roles(p0), ['outgoing:W']);
      assert.ok(p0.wide.mounted && p0.wide.opacity === 1 && p0.layers[0].opacity === 1 && p0.avatar.opacity === 0 && sameRect(p0.avatar.rect, FULL));
      assert.ok(open01(mid.avatar.opacity) && mid.wide.opacity === 1 && !mid.avatar.interpolated && sameRect(mid.avatar.rect, FULL));
      assert.equal(at(type, IN_F - 1).wide.mounted, true); assert.equal(at(type, IN_F).wide.mounted, false);
    } else assert.fail('unhandled ' + type);
  });
}

test('every boundary of the sample is one of the 16 known types and each type has a defined label delay', () => {
  for (let i = 1; i < beats.length; i++) assert.ok(TYPES.includes(`${kinds[i - 1]}>${kinds[i]}`), `beat ${i}`);
});

test('punch zoom: P>P resets instantly, a presenter-state change eases the zoom to/from 1 without a jump', () => {
  const pi = beats.findIndex((b, i) => i > 0 && b.mode === 'full' && (b.punch ?? []).length && kinds[i - 1] === 'P');
  assert.ok(pi > 0, 'sample needs a P>P beat with a punch');
  assert.equal(layerPlan(startOf(pi), beats, fps).avatar.punch.z, 1);
  // a P beat with punches followed by a non-P beat: zoom at f=0 equals the last punch, at f>=IN_F equals 1
  const i = beats.findIndex((b, k) => k + 1 < beats.length && b.mode === 'full' && (b.punch ?? []).length && kinds[k + 1] !== 'P');
  assert.ok(i >= 0, 'sample needs a punched P beat before a non-P beat');
  {
    const z0 = beats[i].punch.slice(-1)[0].z;
    assert.equal(layerPlan(startOf(i + 1), beats, fps).avatar.punch.z, z0);
    const mid = layerPlan(startOf(i + 1) + 7, beats, fps).avatar.punch.z;
    assert.ok(mid < z0 && mid > 1, `mid zoom ${mid}`);
    assert.equal(layerPlan(startOf(i + 1) + IN_F, beats, fps).avatar.punch.z, 1);
  }
});
