// CF-A66 review round: E1 outgoing text card keeps its text, E2 continuous browser chrome, E4 description entrance, E5 one check per props.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { loadEngine } from './_engine_bundle.mjs';
const root = path.resolve(new URL('../../../../..', import.meta.url).pathname);
const source = fs.readFileSync(path.join(root, 'remotion-composer/src/YtNewsStyle01V4.tsx'), 'utf8');
const episode = JSON.parse(fs.readFileSync(path.join(root, 'remotion-composer/src/ytNewsStyle01V4Sample.json'), 'utf8'));
const beats = episode.beats, fps = 25;
const { layerPlan, sceneKind, IN_F, XF_F, OUT_F, labelDelayFor, chromeContinuous, chromeKey, lastStatEnd } = await loadEngine();
const startOf = (i) => Math.ceil(beats[i].t * fps);

const KIND_BEATS = {
  P: (t) => ({ t, mode: 'full' }),
  S: (t) => ({ t, mode: 'pip', media: 'broll', layout: 'stage', src: 'a', origin: 'stock', headline: 'h' }),
  T: (t) => ({ t, mode: 'pip', media: 'typo', layout: 'stage', typo: 'card', headline: 'h' }),
  W: (t) => ({ t, mode: 'pip', media: 'clip', layout: 'wide', src: 'a', origin: 'source', headline: 'h' }),
};
const beatOf = (kind, t, extra = {}) => ({ ...KIND_BEATS[kind](t), ...extra });

// ---- E1 ---------------------------------------------------------------------------------------------------------------
test('E1: an outgoing T layer is `finished` (keeps its text) exactly while the incoming picture has not covered it; other outgoing layers never are', () => {
  const expectedFinishedFrames = { 'T>T': XF_F, 'T>S': XF_F, 'T>W': IN_F + OUT_F, 'T>P': IN_F };
  for (const prev of ['P', 'S', 'T', 'W']) for (const next of ['P', 'S', 'T', 'W']) {
    const bs = [beatOf(prev, 0), beatOf(next, 4), beatOf('P', 8)];
    const start = 100;
    let finishedFrames = 0, lastOutgoing = -1;
    for (let f = start; f < start + 40; f++) {
      const p = layerPlan(f, bs, fps);
      if (p.index !== 1) continue;
      for (const l of p.layers) {
        if (l.role !== 'outgoing') { assert.equal(l.finished, false, `${prev}>${next} current layer`); continue; }
        lastOutgoing = f - start;
        if (l.kind !== 'T') assert.equal(l.finished, false, `${prev}>${next} f=${f - start}: only a T card keeps its text`);
        else if (l.finished) { finishedFrames++; assert.equal(finishedFrames, f - start + 1, `${prev}>${next}: finished is one contiguous run from f=0`); }
      }
    }
    const key = `${prev}>${next}`;
    assert.equal(finishedFrames, expectedFinishedFrames[key] ?? 0, key);
  }
});

test('E1: in the sample, every outgoing T card starts its transition finished (text visible at f = 0) and is never `finished` once covered', () => {
  let n = 0;
  for (let i = 1; i < beats.length; i++) {
    if (sceneKind(beats[i - 1]) !== 'T') continue;
    n++;
    const p0 = layerPlan(startOf(i), beats, fps), out0 = p0.layers.find((l) => l.role === 'outgoing');
    assert.ok(out0 && out0.kind === 'T' && out0.finished, `beat ${i}: outgoing T card at f=0`);
    const cover = { T: XF_F, S: XF_F, W: IN_F + OUT_F, P: IN_F }[sceneKind(beats[i])];
    const pc = layerPlan(startOf(i) + cover, beats, fps), outC = pc.layers.find((l) => l.role === 'outgoing');
    assert.ok(!outC || !outC.finished, `beat ${i}: covered at f=${cover}`);
  }
  assert.ok(n >= 14, `sample has ${n} T beats followed by a beat`);
});

test('R1 (round 11): at a T->W boundary the outgoing T layer keeps its text (finished === true) for every f in 0..22, in the sample and in a synthetic pair', () => {
  const check = (bs, i, label) => {
    const start = Math.ceil(bs[i].t * fps);
    for (let f = 0; f < IN_F + OUT_F; f++) {
      const p = layerPlan(start + f, bs, fps), out = p.layers.find((l) => l.role === 'outgoing' && l.kind === 'T');
      assert.ok(out, `${label} f=${f}: outgoing T layer present`);
      assert.equal(out.finished, true, `${label} f=${f}: outgoing T layer keeps its text`);
    }
    const gone = layerPlan(start + IN_F + OUT_F, bs, fps);
    assert.ok(!gone.layers.some((l) => l.role === 'outgoing'), `${label}: outgoing layer unmounted at f=23`);
  };
  let n = 0;
  for (let i = 1; i < beats.length; i++) if (sceneKind(beats[i - 1]) === 'T' && sceneKind(beats[i]) === 'W') { n++; check(beats, i, `sample beat ${i}`); }
  assert.ok(n >= 1, 'the sample has a T->W boundary');
  check([beatOf('P', 0), beatOf('T', 4), beatOf('W', 9), beatOf('P', 14)], 2, 'synthetic T>W');
});

test('E1: T->T and T->S wait XF_F (>= the cross-fade) before the incoming text enters, so old text is never visible through new text', () => {
  assert.equal(labelDelayFor('T', 'T'), XF_F); assert.equal(labelDelayFor('T', 'S'), XF_F);
  for (let i = 1; i < beats.length; i++) {
    const a = sceneKind(beats[i - 1]), b = sceneKind(beats[i]);
    if (a !== 'T' || (b !== 'T' && b !== 'S')) continue;
    const p0 = layerPlan(startOf(i), beats, fps);
    assert.ok(p0.labelDelayFrames >= XF_F);
    // by the time the new text may enter (f = labelDelay) the incoming layer is opaque and the old text is already gone
    const pl = layerPlan(p0.labelStartFrame, beats, fps), outL = pl.layers.find((l) => l.role === 'outgoing');
    assert.equal(pl.incomingOpacity, 1); assert.ok(!outL || !outL.finished);
  }
});

test('E1: the engine renders an outgoing T card with a finished labels object (startSec far in the past) and hides only fields the presenter reached (T->P)', () => {
  assert.match(source, /const finishedLabels:Labels=\{\.\.\.labels,startSec:-1e6\};/);
  assert.match(source, /<TypoScene beat=\{b\} labels=\{cur\?labels:finishedLabels\} content=\{cur\|\|l\.finished\} cover=\{!cur&&plan\.kind==="P"&&plan\.avatar\.opacity>0\?plan\.avatar\.rect:null\}\/>/);
  assert.ok(source.includes('{content && <CoverGuard cover={cover}>'));
  // the guard only toggles visibility on [data-qc-field] elements; it never removes the card or its backing
  const guard = source.slice(source.indexOf('const CoverGuard'), source.indexOf('const TypoScene'));
  assert.ok(guard.includes('querySelectorAll<HTMLElement>("[data-qc-field]")') && guard.includes('el.style.visibility = hide ? "hidden" : ""'));
});

// ---- E2 ---------------------------------------------------------------------------------------------------------------
const src = (layout, origin, media = 'clip') => ({ mode: 'pip', media, layout, origin, src: 'x', headline: 'h' });
test('E2: chrome is continuous for S->S and W->W with the same source / ai origin only', () => {
  assert.equal(chromeContinuous(src('stage', 'source'), src('stage', 'source')), true);
  assert.equal(chromeContinuous(src('wide', 'source'), src('wide', 'source')), true);
  assert.equal(chromeContinuous(src('stage', 'ai', 'broll'), src('stage', 'ai', 'broll')), true);
  assert.equal(chromeContinuous(src('stage', 'source'), src('stage', 'ai', 'broll')), false, 'origin changes: new chrome');
  assert.equal(chromeContinuous(src('stage', 'source'), src('wide', 'source')), false, 'stage -> wide is a different window');
  assert.equal(chromeContinuous(src('stage', 'stock', 'broll'), src('stage', 'stock', 'broll')), false, 'stock shows no pill / credit');
  assert.equal(chromeContinuous(beatOf('T', 0), src('stage', 'source')), false);
  assert.equal(chromeContinuous(beatOf('P', 0), src('stage', 'source')), false);
  assert.equal(chromeContinuous(null, src('stage', 'source')), false);
  assert.equal(chromeKey(beatOf('T', 0)), null);
});

test('E2: the sample W->W boundary (beats 29 -> 30, same clip) is continuous; the engine feeds the chrome a labels object that has already started', () => {
  assert.equal(sceneKind(beats[29]), 'W'); assert.equal(sceneKind(beats[30]), 'W');
  assert.equal(chromeContinuous(beats[29], beats[30]), true);
  assert.match(source, /const chromeLabels:Labels=chromeContinuous\(plan\.prevIndex===null\?null:BEATS\[plan\.prevIndex\],beat\)\?\{\.\.\.labels,startSec:-1e6\}:labels;/);
  assert.equal((source.match(/episode=\{EPISODE\} labels=\{chromeLabels\}>/g) ?? []).length, 2, 'stage and wide frame both use chromeLabels');
});

// ---- E4 ---------------------------------------------------------------------------------------------------------------
test('E4: lastStatEnd is the latest chip end at or before t; the description re-enters from it', () => {
  const bs = [{ t: 0, mode: 'full' }, { ...beatOf('S', 5), stats: [{ at: 6, dur: 2, label: 'a' }, { at: 7, dur: 4, label: 'b' }] }, beatOf('S', 20)];
  assert.equal(lastStatEnd(bs, 5.5), 0); assert.equal(lastStatEnd(bs, 8), 8); assert.equal(lastStatEnd(bs, 10.99), 8); assert.equal(lastStatEnd(bs, 11), 11); assert.equal(lastStatEnd(bs, 30), 11);
  assert.match(source, /const descLabels:Labels=\{\.\.\.labels,startSec:Math\.max\(labels\.startSec,lastStatEnd\(BEATS,t\)\)\};/);
  const museum = source.slice(source.indexOf('const MuseumScene'), source.indexOf('const WideScene'));
  assert.ok(museum.includes('id="description"') && museum.includes('...enter(descLabels)'), 'the description uses the shifted labels');
  // a chip that ended before this beat began changes nothing (max with labelStartSec)
  for (const [i, b] of beats.entries()) {
    if (sceneKind(b) !== 'S' || !b.sub) continue;
    const p = layerPlan(startOf(i), beats, fps);
    assert.ok(Math.max(p.labelStartFrame / fps, lastStatEnd(beats, b.t)) <= b.t + 1, `beat ${i}`); // chips of earlier beats ended at most ~a beat before
  }
});

// ---- E5 ---------------------------------------------------------------------------------------------------------------
test('E5: checkEpisodeMinimal runs once per props (useMemo), not once per frame', () => {
  const comp = source.slice(source.indexOf('export const YtNewsStyle01V4: React.FC'));
  assert.match(comp, /const errs = useMemo\(\(\) => checkEpisodeMinimal\(props\.episode, props\.captions\), \[props\.episode, props\.captions\]\);/);
  assert.equal((comp.match(/checkEpisodeMinimal\(/g) ?? []).length, 1);
  assert.ok(source.indexOf('useMemo(') < source.indexOf('useThaiFonts();', source.indexOf('export const YtNewsStyle01V4: React.FC')), 'hook order is fixed: useMemo is the first hook');
});

// ---- Round 10: CoverGuard font race tripwire --------------------------------------------------------------------------
test('CoverGuard holds the frame until the font is loaded (delayRender + a single continueRender after measuring)', () => {
  const start = source.indexOf('const CoverGuard');
  const guard = source.slice(start, source.indexOf('const TypoScene'));
  assert.match(guard, /delayRender\(/, 'CoverGuard must hold the frame while the font loads');
  assert.match(guard, /continueRender\(/, 'CoverGuard must release the frame after measuring with the real font');
  assert.match(guard, /fontsLoaded/, 'a guard mounted after the font loaded must not hold the frame');
  assert.match(source, /\.then\(\(\) => \{ fontsLoaded = true; \}\)/, 'ensureFonts() sets the module flag when it resolves');
});
