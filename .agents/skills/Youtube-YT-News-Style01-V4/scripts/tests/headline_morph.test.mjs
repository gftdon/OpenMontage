// Label timing across scene changes (CF-A66 step 3): labels wait while the presenter morphs / the window fades in.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { loadEngine } from './_engine_bundle.mjs';
const root = path.resolve(new URL('../../../../..', import.meta.url).pathname);
const source = fs.readFileSync(path.join(root, 'remotion-composer/src/YtNewsStyle01V4.tsx'), 'utf8');
const episode = JSON.parse(fs.readFileSync(path.join(root, 'remotion-composer/src/ytNewsStyle01V4Sample.json'), 'utf8'));
const beats = episode.beats, fps = 25;
const { layerPlan, sceneKind, IN_F, LANES, entranceStartSec } = await loadEngine();
const kinds = beats.map(sceneKind);
const Z = (k) => k === 'S' || k === 'T';
const startOf = (i) => Math.ceil(beats[i].t * fps);
const block = (name) => { const a = source.indexOf(`const ${name}:`); assert.ok(a >= 0, name); const b = source.indexOf('\nconst ', a + 10); return source.slice(a, b < 0 ? undefined : b); };

test('labels of every P/W -> S/T/W and S/T -> P/W boundary wait IN_F (.55 s) after the beat starts; S/T->S/T and W->W do not wait', () => {
  let delayed = 0, immediate = 0;
  for (let i = 1; i < beats.length; i++) {
    const p = layerPlan(startOf(i), beats, fps);
    const [a, b] = [kinds[i - 1], kinds[i]];
    const wait = (Z(a) && Z(b)) || (a === 'W' && b === 'W') || (a === 'P' && b === 'P') ? 0 : IN_F;
    assert.equal(p.labelDelayFrames, wait, `beat ${i} ${a}>${b}`);
    assert.equal(p.labelStartFrame, startOf(i) + wait);
    if (wait) { delayed++; assert.ok(p.labelStartFrame / fps > beats[i].t + 0.5); } else immediate++;
  }
  assert.ok(delayed >= 30 && immediate >= 15, `delayed=${delayed} immediate=${immediate}`);
  // the full-to-pip morph in particular: every P -> S/T boundary of the sample
  const pz = beats.filter((b, i) => i && kinds[i - 1] === 'P' && Z(kinds[i]));
  assert.ok(pz.length >= 12);
});

test('the delay covers the whole transition: no label starts while the outgoing layer or presenter is still moving in at full strength', () => {
  for (let i = 1; i < beats.length; i++) {
    const p0 = layerPlan(startOf(i), beats, fps);
    if (!p0.labelDelayFrames) continue;
    const settled = layerPlan(p0.labelStartFrame, beats, fps);
    // when labels may start, the presenter morph / incoming window fade is complete (outgoing layers may still be fading underneath)
    assert.ok(settled.incomingOpacity >= 1, `beat ${i} ${p0.boundary}: incoming ${settled.incomingOpacity} at labelStart`);
    assert.equal(settled.avatar.interpolated, false);
  }
});

test('outgoing layers never carry labels; only the current layer does (headline, description, chrome text, credit unmount at f = 0)', () => {
  for (let i = 1; i < beats.length; i++) {
    const p = layerPlan(startOf(i), beats, fps);
    for (const l of p.layers) assert.equal(l.labels, l.role === 'current');
    assert.equal(p.layers.filter((l) => l.labels).length, p.kind === 'P' ? 0 : 1);
  }
  for (const comp of ['MuseumScene', 'WideScene', 'TypoScene']) assert.match(block(comp), /current &&|\{current \&\&|current\b/, comp + ' must gate its text on `current`');
  assert.ok(block('MuseumScene').includes('{current && <div'), 'museum headline/description gated');
  assert.ok(block('WideScene').includes('{current && <div'), 'wide headline gated');
  assert.ok(block('TypoScene').includes('{current && <div'), 'typo content gated');
  // footage is tagged for the probe on the current layer only
  assert.equal((source.match(/data-qc-footage=\{current \? beat\.src : undefined\}/g) ?? []).length, 2);
});

test('chrome: the bar is persistent, its URL pill and credit enter with the labels, and their lanes stay inside the bar', () => {
  const chrome = block('BrowserChrome');
  const barLine = chrome.split('\n').find((l) => l.includes('<Backing id={chromeId}')) ?? '';
  assert.ok(barLine && !barLine.includes('enter('), 'the bar backing itself must not wait');
  assert.equal((chrome.match(/\.\.\.enter\(labels\)/g) ?? []).length, 2, 'URL pill and credit/AI label use the label entrance');
  for (const pre of ['split', 'wide']) {
    const bar = LANES[`${pre}.chrome`], url = LANES[`${pre}.chrome.url`], lab = LANES[`${pre}.chrome.label`];
    for (const l of [url, lab]) assert.ok(l.x >= bar.x && l.x + l.w <= bar.x + bar.w && l.y >= bar.y && l.y + l.h <= bar.y + bar.h, `${pre} lane inside the chrome bar`);
    assert.ok(url.x + url.w <= lab.x, `${pre} URL and credit lanes do not overlap`);
  }
});

test('stats rail and captions never take part in transitions (no plan, no label delay)', () => {
  for (const name of ['StatRail', 'CaptionLane']) { const b = block(name); assert.ok(!/layerPlan|labelStart|labelDelay|entranceStartSec/.test(b), name); }
  // a chip carried across a boundary keeps its own entrance time
  for (const [i, b] of beats.entries()) for (const st of b.stats ?? []) {
    const p = layerPlan(startOf(i), beats, fps);
    if (st.at >= p.labelStartFrame / fps) assert.equal(entranceStartSec(st.at, p, fps), st.at);
  }
});

test('lower third and CTA wait for the label delay of their beat but not beyond their own time', () => {
  const lowerBeats = beats.map((b, i) => [b, i]).filter(([b]) => b.lower);
  assert.ok(lowerBeats.length);
  for (const [b, i] of lowerBeats) { const p = layerPlan(startOf(i), beats, fps); const s = entranceStartSec(b.lower.at, p, fps); assert.ok(s >= b.lower.at && s >= p.labelStartFrame / fps); }
  const ci = beats.findIndex((b, i) => b.t <= episode.ctaT && (beats[i + 1]?.t ?? 1e9) > episode.ctaT);
  const pc = layerPlan(startOf(ci), beats, fps);
  assert.equal(entranceStartSec(episode.ctaT, pc, fps), Math.max(episode.ctaT, pc.labelStartFrame / fps));
});
