// CF-A66 V1 / V2: the clip-length rule (S09) includes the outgoing tail, and its settle table is derived from the engine's own layerPlan.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadEngine } from './_engine_bundle.mjs';
import { validateEpisode, settleFrames, sceneKindOf } from '../episode_schema.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FX = path.join(HERE, 'fixtures/episodes');
const readJson = (p) => JSON.parse(fs.readFileSync(p, 'utf8'));
const clone = (o) => JSON.parse(JSON.stringify(o));
const minCaptions = () => readJson(path.join(FX, 'captions/min-captions.json'));
const baseMin = () => readJson(path.join(FX, 'valid/min-3-beat.json'));
const { layerPlan, sceneKind, IN_F, XF_F, OUT_F } = await loadEngine();
const KINDS = ['P', 'S', 'T', 'W'];
const fps = 25;

// a minimal beat of each scene kind (layerPlan reads only mode / media / layout / t / punch)
const beatOf = (kind, t) => ({
  P: { t, mode: 'full' },
  S: { t, mode: 'pip', media: 'broll', layout: 'stage', src: 'a', origin: 'stock', headline: 'h' },
  T: { t, mode: 'pip', media: 'typo', layout: 'stage', typo: 'card', headline: 'h' },
  W: { t, mode: 'pip', media: 'clip', layout: 'wide', src: 'a', origin: 'source', headline: 'h' },
}[kind]);

// frames after the next beat has started during which the outgoing layer of the first beat is still in the plan
function engineSettle(prev, next) {
  const beats = [beatOf(prev, 0), beatOf(next, 4), beatOf(prev === 'P' ? 'S' : 'P', 8)];
  const start = Math.ceil(4 * fps);
  let n = 0;
  for (let f = start; f < start + 60; f++) {
    const p = layerPlan(f, beats, fps);
    if (p.index === 1 && p.layers.some((l) => l.role === 'outgoing' && l.index === 0)) n = f - start + 1;
  }
  return n;
}

test('the validator settle table equals the engine layerPlan for every ordered pair of scene kinds (no drift)', () => {
  const table = {};
  for (const a of KINDS) for (const b of KINDS) {
    table[`${a}>${b}`] = engineSettle(a, b);
    assert.equal(settleFrames(a, b), engineSettle(a, b), `${a}>${b}`);
  }
  // spot values named in the report: XF_F + OUT_F inside one frame, IN_F + OUT_F between stage and wide, IN_F towards the presenter
  assert.equal(table['S>S'], XF_F + OUT_F); assert.equal(table['S>T'], XF_F + OUT_F); assert.equal(table['W>W'], XF_F + OUT_F);
  assert.equal(table['S>W'], IN_F + OUT_F); assert.equal(table['W>S'], IN_F + OUT_F); assert.equal(table['W>T'], IN_F + OUT_F);
  assert.equal(table['S>P'], IN_F); assert.equal(table['W>P'], IN_F); assert.equal(table['T>P'], IN_F);
  for (const b of KINDS) assert.equal(table[`P>${b}`], 0, 'a presenter beat has no outgoing scene layer');
});

test('sceneKindOf agrees with the engine sceneKind for every kind of beat', () => {
  for (const k of KINDS) assert.equal(sceneKindOf(beatOf(k, 0)), sceneKind(beatOf(k, 0)), k);
});

// beat 1 of the minimal episode is a source clip on the stage (3 s .. 7 s = 100 frames) followed by a presenter beat (S>P, settle 14)
const withClip = (dur, from, origin = 'source') => {
  const ep = baseMin();
  ep.brollDur = { [origin === 'source' ? 'yt_demo' : 'demo_stock']: dur };
  const b = ep.beats[1];
  if (origin !== 'source') { b.media = 'broll'; b.origin = 'stock'; b.src = 'demo_stock'; delete b.srcCrop; } else b.src = 'yt_demo';
  if (from === undefined) delete b.from; else b.from = from;
  return ep;
};
const s09 = (r, list = 'errors') => r[list].filter((e) => e.rule === 'S09');

test('S09 tail: shown + settle > L is an ERROR for a source clip and names the beat, the clip and the seconds to cut from `from`', () => {
  // L = floor((4.7 - 0.2) * 25) - 2 = 110; shown = 100 (fits), settle S>P = 14: 114 > 110
  const r = validateEpisode(withClip(4.7, 0.2), minCaptions());
  const e = s09(r);
  assert.equal(e.length, 1, JSON.stringify(r.errors));
  assert.equal(e[0].path, '/beats/1/from');
  assert.match(e[0].message, /beat 1 clip "yt_demo"/);
  assert.match(e[0].message, /100 frames/); assert.match(e[0].message, /14 more into beat 2/); assert.match(e[0].message, /S>P/);
  assert.match(e[0].message, /lower "from" by at least 0\.16 s/); // 4 frames short = 0.16 s
  assert.match(e[0].message, /freeze on its last frame/);
});

test('S09 tail: the exact boundary shown + settle == L passes; one frame more fails (source)', () => {
  // L = floor((dur - 0) * 25) - 2 ; need L == 114  =>  dur = 4.65 (floor(116.25) - 2 = 114)
  assert.deepEqual(s09(validateEpisode(withClip(4.65, 0), minCaptions())), []);
  assert.equal(s09(validateEpisode(withClip(4.6, 0), minCaptions())).length, 1); // L = 113
});

test('S09 tail: when `from` is already 0 the message asks to shorten the beat (or use a longer clip)', () => {
  const e = s09(validateEpisode(withClip(4.5), minCaptions()));
  assert.equal(e.length, 1);
  assert.equal(e[0].path, '/beats/1/src');
  assert.match(e[0].message, /"from" cannot go below 0/); assert.match(e[0].message, /shorten the beat by at least 0\.16 s/);
});

test('S09 tail: a stock clip only gets a WARNING in the same rule family', () => {
  const r = validateEpisode(withClip(4.5, undefined, 'stock'), minCaptions());
  assert.deepEqual(s09(r), []);
  const w = s09(r, 'warnings');
  assert.equal(w.length, 1);
  assert.match(w[0].message, /wrap to its first frame/);
});

test('S09 tail: nothing is added after the last beat (settle 0), and a presenter beat after the clip is not special-cased away', () => {
  const ep = baseMin(); // move the clip to the last beat position
  ep.beats = [ep.beats[0], { ...ep.beats[1], t: 3 }];
  ep.voEndSec = 12; ep.ctaT = 10.5; ep.brollDur = { yt_demo: 9.2 }; ep.beats[1].from = 0; // shown = 225 frames, L = 228 - ... floor(9.2*25)-2 = 228
  const r = validateEpisode(ep, minCaptions());
  assert.deepEqual(s09(r), []); // the S20 error is a different rule
});

test('S09 tail: the sample episode passes with no S09 error or warning', () => {
  const ep = readJson(path.join(FX, 'valid/sample-v1.json'));
  const r = validateEpisode(ep, readJson(path.join(FX, 'captions/sample-captions.json')));
  assert.deepEqual(s09(r), []); assert.deepEqual(s09(r, 'warnings'), []);
});

test('S09 tail corpus file is rejected with S09 at /beats/1/from', () => {
  const ep = readJson(path.join(FX, 'invalid/S09-source-tail-would-freeze.json'));
  assert.deepEqual(ep._expect, { rule: 'S09', path: '/beats/1/from', engineMustReject: false });
  delete ep._expect;
  const e = s09(validateEpisode(ep, minCaptions()));
  assert.equal(e.length, 1); assert.equal(e[0].path, '/beats/1/from');
});

// ---------------------------------------------------------------------------
// S20 (V2)
// ---------------------------------------------------------------------------
const s20 = (r) => r.errors.filter((e) => e.rule === 'S20');

test('S20: the last beat must be a presenter beat', () => {
  const ep = readJson(path.join(FX, 'invalid/S20-last-beat-not-presenter.json'));
  assert.deepEqual(ep._expect, { rule: 'S20', path: '/beats/2/mode', engineMustReject: false });
  delete ep._expect;
  const e = s20(validateEpisode(ep, minCaptions()));
  assert.equal(e.length, 1, JSON.stringify(e)); assert.equal(e[0].path, '/beats/2/mode');
  assert.match(e[0].message, /full\.cta/);
});

test('S20: ctaT must not be before the start of the last beat; ctaT == last beat start is valid; ctaT < voEndSec stays S03', () => {
  const bad = readJson(path.join(FX, 'invalid/S20-cta-before-last-beat.json'));
  assert.deepEqual(bad._expect, { rule: 'S20', path: '/ctaT', engineMustReject: false });
  delete bad._expect;
  const e = s20(validateEpisode(bad, minCaptions()));
  assert.equal(e.length, 1); assert.equal(e[0].path, '/ctaT');
  const ok = readJson(path.join(FX, 'valid/cta-at-last-presenter-beat-start.json'));
  assert.equal(ok.ctaT, ok.beats[ok.beats.length - 1].t);
  assert.deepEqual(validateEpisode(ok, minCaptions()).errors, []);
  const late = clone(ok); late.ctaT = late.voEndSec; // S03, not S20
  const r = validateEpisode(late, minCaptions());
  assert.deepEqual(s20(r), []); assert.ok(r.errors.some((x) => x.rule === 'S03'));
});

test('S20: a CTA on any non-presenter last scene is rejected for every scene kind', () => {
  for (const [media, layout] of [['broll', 'stage'], ['typo', 'stage'], ['clip', 'wide']]) {
    const ep = baseMin();
    ep.brollDur.yt_demo = 20;
    ep.beats[2] = { t: 7, mode: 'pip', media, layout, headline: 'h', ...(media === 'typo' ? { typo: 'card', cards: [{ at: 7, lines: ['x'] }] } : media === 'clip' ? { src: 'yt_demo', origin: 'source' } : { src: 'yt_demo', origin: 'source' }) };
    assert.equal(s20(validateEpisode(ep, minCaptions())).length >= 1, true, `${media}/${layout}`);
  }
});

test('S20: the sample episode satisfies it (last beat full, ctaT inside it)', () => {
  const ep = readJson(path.join(FX, 'valid/sample-v1.json'));
  const last = ep.beats[ep.beats.length - 1];
  assert.equal(last.mode, 'full'); assert.ok(ep.ctaT >= last.t && ep.ctaT < ep.voEndSec);
  assert.deepEqual(s20(validateEpisode(ep, readJson(path.join(FX, 'captions/sample-captions.json')))), []);
});
