// Probe v3 / plan v2 contract of the V4 engine.
//   1. buildQcPlan  (pure)          -> the __QC_PLAN__ object the gate consumes (planVersion 2);
//   2. measureQcFrame (pure DOM fn) -> the __QC__ snapshot (schemaVersion 3). It is self-contained, so it is cut out of
//      the engine source, stripped of types by esbuild and run in a real headless Chrome on hand-written DOM fixtures
//      (no Remotion, no episode data). That is the proof that the zero-size-box guard really reports.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { loadEngine, enginePath } from './_engine_bundle.mjs';
import { buildFramePlan, evaluateLayout, evaluatePlanRules, loadFieldRules, loadThresholds, ruleProbeIssues } from '../qc_layout_eval.mjs';

const root = path.resolve(new URL('../../../../..', import.meta.url).pathname);
const sample = JSON.parse(fs.readFileSync(path.join(root, 'remotion-composer/src/ytNewsStyle01V4Sample.json'), 'utf8'));
const captions = JSON.parse(fs.readFileSync(path.join(root, 'remotion-composer/src/ytNewsStyle01V4SampleCaptions.json'), 'utf8'));
const t = loadThresholds();
const engine = await loadEngine();
const source = fs.readFileSync(enginePath, 'utf8');

// ---------------------------------------------------------------------------------------------------------------------
// 1. plan v2
// ---------------------------------------------------------------------------------------------------------------------
test('buildQcPlan emits plan v2 with every key the gate reads', () => {
  const plan = engine.buildQcPlan(sample, captions, 25);
  assert.equal(plan.planVersion, 2);
  assert.equal(plan.engine, 'YtNewsStyle01V4');
  assert.equal(typeof plan.engineVersion, 'string');
  assert.equal(plan.fps, 25);
  assert.equal(plan.durationInFrames, Math.ceil(sample.totalDurationSec * 25));
  assert.equal(plan.voEndFrame, Math.ceil(sample.voEndSec * 25), 'first end-card frame');
  assert.equal(plan.sweepVersion, 'avatar-empty-backing-2');
  assert.deepEqual(plan.avatarFaceBox, sample.avatarFaceBox);
  assert.equal(plan.avatarFaceBoxSource, 'episode');
  assert.ok(Math.abs(plan.avatarSourceAspect - 16 / 9) < 1e-9);
  assert.ok(plan.frames.length > 100 && plan.frames.every(Number.isInteger));
  assert.deepEqual(plan.frames, [...plan.frames].sort((a, b) => a - b));
  assert.equal(new Set(plan.frames).size, plan.frames.length);
  assert.ok(plan.frames.every(f => f >= 0 && f < plan.durationInFrames));
  assert.equal(plan.beats.length, sample.beats.length);
  plan.beats.forEach((b, i) => {
    assert.deepEqual(Object.keys(b), ['index', 't', 'startFrame', 'mode', 'layout', 'origin', 'media']);
    assert.equal(b.index, i); assert.equal(b.t, sample.beats[i].t); assert.equal(b.startFrame, Math.ceil(sample.beats[i].t * 25));
  });
  assert.ok(plan.sweepWindows.length > 0);
  for (const w of plan.sweepWindows) {
    assert.match(w.id, /^avatar-\d+$/);
    assert.ok(Number.isInteger(w.startFrame) && Number.isInteger(w.endFrame) && w.endFrame >= w.startFrame && w.endFrame < plan.durationInFrames);
  }
});

test('plan.lanes = exactly the text lanes of LANES, as {x,y,width,height}, and passes the static lane-table rule', () => {
  const plan = engine.buildQcPlan(sample, captions, 25);
  const expected = Object.entries(engine.LANES).filter(([, l]) => l.role === 'text').map(([id]) => id).sort();
  assert.deepEqual(Object.keys(plan.lanes).sort(), expected);
  for (const [id, r] of Object.entries(plan.lanes)) {
    const l = engine.LANES[id];
    assert.deepEqual(r, { x: l.x, y: l.y, width: l.w, height: l.h }, id);
  }
  assert.deepEqual(evaluatePlanRules(plan, t), [], 'every text lane inside the safe area');
});

test('round 11: the plan samples the first frames of EVERY beat boundary (s, s+1, s+XF_F-1, s+XF_F, s+settle-1) from the one settle definition', () => {
  const plan = engine.buildQcPlan(sample, captions, 25);
  const have = new Set(plan.frames), B = sample.beats;
  const SETTLE = { P: { P: 0, S: 14, T: 14, W: 14 }, S: { P: 14, S: 18, T: 18, W: 23 }, T: { P: 14, S: 18, T: 18, W: 23 }, W: { P: 14, S: 23, T: 23, W: 18 } };
  for (let i = 1; i < B.length; i++) {
    const s = Math.ceil(B[i].t * 25), settle = engine.transitionSettleFrames(engine.sceneKind(B[i - 1]), engine.sceneKind(B[i]));
    assert.equal(settle, SETTLE[engine.sceneKind(B[i - 1])][engine.sceneKind(B[i])], `beat ${i} settle`);
    for (const f of [s, s + 1, s + engine.XF_F - 1, s + engine.XF_F, s + settle - 1]) if (f >= 0 && f < plan.durationInFrames) assert.ok(have.has(f), `beat ${i}: frame ${f}`);
  }
  assert.ok(plan.frames.every(f => Number.isInteger(f) && f >= 0 && f < plan.durationInFrames));
});

test('the plan feeds buildFramePlan (grid + beat windows + voice-over end) without throwing', () => {
  const plan = engine.buildQcPlan(sample, captions, 25);
  const frames = buildFramePlan(plan, t);
  assert.ok(frames.length >= plan.frames.length);
  for (const f of plan.frames) assert.ok(frames.includes(f));
  for (const f of [0, 25, 50, plan.voEndFrame - 2, plan.voEndFrame + 3]) assert.ok(frames.includes(f), `frame ${f}`);
  assert.ok(frames.at(-1) < plan.durationInFrames);
});

test('a plan is JSON-round-trippable (it travels as a console line)', () => {
  const plan = engine.buildQcPlan(sample, captions, 25);
  assert.deepEqual(JSON.parse(JSON.stringify(plan)), plan);
});

// ---------------------------------------------------------------------------------------------------------------------
// 2. measureQcFrame is self-contained and keeps its guards (source level)
// ---------------------------------------------------------------------------------------------------------------------
const fnStart = source.indexOf('export async function measureQcFrame');
const fnEnd = source.indexOf('const QcProbe: React.FC');
const fnSource = source.slice(fnStart, fnEnd);

test('measureQcFrame sits in the engine and depends on nothing but its arguments', () => {
  assert.ok(fnStart > 0 && fnEnd > fnStart);
  for (const banned of ['LANES', 'BEATS', 'EPISODE', 'IN_F', 'OUT_F', 'XF_F', 'MODE_BLEND_SEC', 'layerPlan', 'sceneKind', 'ensureFonts', 'FONT', 'useVideoConfig', 'staticFile', 'NAVY', 'AMBER']) {
    assert.doesNotMatch(fnSource, new RegExp(`\\b${banned}\\b`), `measureQcFrame must not use engine-scope ${banned}`);
  }
  assert.doesNotMatch(fnSource, /(?<![\w."'])[WH](?![\w"'])/, 'no engine W / H constants (frame size comes from ctx)');
});

test('the zero-size box guard is in the probe verbatim and reports instead of skipping', () => {
  assert.ok(fnSource.includes('||box.width<=0||box.height<=0'));
  assert.equal(fnSource.split('||box.width<=0||box.height<=0').length - 1, 2, 'field guard + background guard');
  assert.match(fnSource, /id: "hidden-box"/);
  assert.match(fnSource, /id: "untagged-text"/);
  assert.match(fnSource, /id: "unsupported-transform"/);
  assert.match(fnSource, /schemaVersion: 3/);
  assert.ok(fnSource.includes('if (!avatar && frame / fps < voEndSec) throw Error("missing avatar measurement");'));
});

// ---------------------------------------------------------------------------------------------------------------------
// 3. measureQcFrame in a real browser
// ---------------------------------------------------------------------------------------------------------------------
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const esbuild = createRequire(path.join(root, 'remotion-composer/package.json'))('esbuild');
const fnJs = esbuild.transformSync(fnSource.replace('export async function', 'async function'), { loader: 'ts' }).code;

const CTX = { frame: 100, fps: 25, width: 1920, height: 1080, voEndSec: 1, beatIndex: 2, transition: false, faceBox: { x: 0.37, y: 0.05, w: 0.23, h: 0.38 }, faceBoxSource: 'episode', avatarAspect: 16 / 9, beat: { mode: 'pip', media: 'broll', layout: 'stage' } };
const FIXTURES = {
  ok: `<div data-qc-backing="solid" data-qc-backing-id="b1" data-qc-reserved="header" style="position:absolute;left:96px;top:54px;height:44px;padding:0 14px;background:rgb(11,14,23)">
         <div data-qc-field="brand" data-qc-role="label" data-qc-tier="label" data-qc-lane="header.brand" style="font:700 30px/44px sans-serif;color:#F5F1E8;white-space:nowrap">AI TECH NEWS</div></div>`,
  untagged: `<div style="position:absolute;left:100px;top:300px;font:30px sans-serif">stray words</div>`,
  hidden: `<div style="position:absolute;left:100px;top:300px"><div data-qc-field="headline" data-qc-role="read" data-qc-tier="read" data-qc-lane="split.headline" style="display:contents;font:700 40px sans-serif">hidden box</div></div>`,
  scaled: `<div style="position:absolute;left:100px;top:300px;scale:1.2"><div data-qc-field="headline" data-qc-role="read" data-qc-tier="read" data-qc-lane="split.headline" style="font:700 40px sans-serif">scaled</div></div>`,
  twoLines: `<div style="position:absolute;left:100px;top:300px;width:260px"><div data-qc-field="cta" data-qc-role="read" data-qc-tier="read" data-qc-lane="full.cta" style="font:700 40px/56px sans-serif;white-space:normal">alpha beta gamma delta epsilon zeta</div></div>`,
  nowrap: `<div style="position:absolute;left:100px;top:300px;width:100px;overflow:visible"><div data-qc-field="headline" data-qc-role="read" data-qc-tier="read" data-qc-lane="split.headline" style="font:700 40px sans-serif;white-space:nowrap;width:100px">a very long nowrap headline text</div></div>`,
  avatar: `<div data-qc-layer="avatar" data-qc-occluder="avatar" style="position:absolute;left:100px;top:100px;width:400px;height:800px;overflow:hidden;background:#0B0E17">
             <div data-qc-avatar-media style="position:absolute;left:-500px;top:0;width:1422.2222px;height:800px"></div></div>
           <div data-qc-layer="stage" data-qc-layer-id="stage-3" data-qc-scene-role="current" style="position:absolute;left:600px;top:100px;width:1000px;height:800px;opacity:.5;background:#141A2B"></div>`,
};
const withAvatarCtx = { ...CTX, voEndSec: 100 };            // frame 100 / 25 = 4 s < 100: the avatar is expected

function runInChrome(cases) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'v4-probe-'));
  const html = `<!doctype html><meta charset="utf-8"><body style="margin:0"><div id="out"></div><script>${fnJs}</script><script>
    const FIX=${JSON.stringify(FIXTURES)}, CASES=${JSON.stringify(cases)};
    (async()=>{const res={};for(const [name,fix,ctx] of CASES){
      document.querySelector('[data-qc-root]')?.remove();
      const root=document.createElement('div');root.setAttribute('data-qc-root','');root.style.cssText='position:relative;width:1920px;height:1080px';root.innerHTML=FIX[fix];document.body.appendChild(root);
      try{res[name]=await measureQcFrame(root,ctx);}catch(e){res[name]={error:String(e.message||e)};}}
      document.getElementById('out').textContent=JSON.stringify(res);document.title='done';})();</script>`;
  const file = path.join(dir, 'probe.html');
  fs.writeFileSync(file, html);
  const dom = execFileSync(CHROME, ['--headless=new', '--disable-gpu', '--no-first-run', '--virtual-time-budget=20000', '--dump-dom', pathToFileURL(file).href], { timeout: 90000, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, stdio: ['ignore', 'pipe', 'ignore'] });
  fs.rmSync(dir, { recursive: true, force: true });
  const m = dom.match(/<div id="out">([\s\S]*?)<\/div>/);
  assert.ok(m, 'the page produced no result');
  return JSON.parse(m[1].replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&'));
}

const R = runInChrome([
  ['ok', 'ok', CTX], ['untagged', 'untagged', CTX], ['hidden', 'hidden', CTX], ['scaled', 'scaled', CTX],
  ['twoLines', 'twoLines', CTX], ['nowrap', 'nowrap', CTX], ['avatar', 'avatar', withAvatarCtx], ['noAvatar', 'ok', withAvatarCtx],
]);

test('browser: a normal field yields the full schema-3 snapshot', () => {
  const s = R.ok;
  assert.equal(s.schemaVersion, 3);
  assert.equal(s.phase, 'endcard', 'frame 100 / 25 = 4 s >= voEndSec 1');
  assert.equal(s.frame, 100); assert.equal(s.t, 4); assert.equal(s.beatIndex, 2); assert.equal(s.width, 1920); assert.equal(s.height, 1080);
  assert.equal(s.captionLane, 'bottom'); assert.equal(s.transition, false); assert.equal(typeof s.fontsOk, 'boolean');
  assert.deepEqual(s.probeIssues, []);
  assert.equal(s.avatar, null);
  for (const key of ['fields', 'occluders', 'backings', 'layers']) assert.ok(Array.isArray(s[key]), key);
  assert.deepEqual(s.footage, { origin: 'endcard', layout: 'stage', credit: false, chrome: false });
  assert.deepEqual(Object.keys(s.avatarBacking), ['applicable', 'reason', 'avatar', 'candidates']);
  const f = s.fields[0];
  assert.equal(f.id, 'brand'); assert.equal(f.role, 'label'); assert.equal(f.tier, 'label'); assert.equal(f.lane, 'header.brand');
  assert.equal(f.fontSize, 30); assert.equal(f.opacity, 1); assert.equal(f.lineCount, 1); assert.equal(f.whiteSpace, 'nowrap');
  assert.equal(f.colorAlpha, 1);
  assert.ok(f.rects.length && f.inkRects.length && f.box.width > 0 && f.box.height > 0);
  assert.ok(Number.isFinite(f.scrollWidth) && Number.isFinite(f.clientWidth));
  assert.equal(f.rubric.glyph, 'latin');
  assert.ok(f.rubric.latinInkPx > 10 && f.rubric.scaleY === 1 && f.rubric.rubricPx === null);
  assert.equal(f.backing.id, 'b1'); assert.equal(f.backing.alpha, 1); assert.equal(f.backing.opacity, 1); assert.equal(f.backing.sameVisibilityAncestry, true);
  assert.match(f.backing.path, /^div:\d+$/); assert.ok(f.backing.box.width > 0);
  assert.equal(f.backed, true);
  assert.deepEqual(s.backings.map(b => [b.id, b.reserved, b.alpha, b.opacity]), [['b1', 'header', 1, 1]]);
  assert.deepEqual(s.layers, []);
});

test('browser: text without data-qc-field -> probe issue untagged-text, and the gate turns it into an issue', () => {
  assert.deepEqual(R.untagged.probeIssues.map(p => p.id), ['untagged-text']);
  const gate = ruleProbeIssues(R.untagged);
  assert.deepEqual(gate.map(i => i.id), ['untagged-text']);
});

test('browser: a field whose box is zero-size is REPORTED (hidden-box), never silently skipped', () => {
  const s = R.hidden;
  assert.deepEqual(s.probeIssues.map(p => [p.id, p.field]), [['hidden-box', 'headline']]);
  assert.equal(s.fields.length, 1, 'the field is still measured');
  assert.equal(s.fields[0].box.width, 0);
  assert.deepEqual(ruleProbeIssues(s).map(i => [i.id, i.field]), [['hidden-box', 'headline']]);
  // and the full evaluation of a frame that carries it fails (the gate cannot pass it)
  const out = evaluateLayout({ ...s, phase: 'endcard' }, t, { plan: { lanes: { 'split.headline': { x: 0, y: 0, width: 1920, height: 1080 } } }, fieldRules: loadFieldRules() });
  assert.ok(out.issues.some(i => i.id === 'hidden-box'));
});

test('browser: CSS scale on an ancestor is banned (unsupported-transform)', () => {
  assert.deepEqual(R.scaled.probeIssues.map(p => [p.id, p.field]), [['unsupported-transform', 'headline']]);
});

test('browser: lineCount counts wrapped lines; whiteSpace / scrollWidth / clientWidth are reported', () => {
  const f = R.twoLines.fields[0];
  assert.ok(f.lineCount >= 2, `lineCount ${f.lineCount}`);
  assert.equal(f.whiteSpace, 'normal');
  const n = R.nowrap.fields[0];
  assert.equal(n.whiteSpace, 'nowrap'); assert.equal(n.lineCount, 1);
  assert.ok(n.scrollWidth > n.clientWidth + 1, 'nowrap text wider than its box is measurable');
});

test('browser: presenter, face box (cover mapping incl. punch zoom), content layers', () => {
  const s = R.avatar;
  assert.equal(s.phase, 'vo');
  assert.equal(s.avatar.opacity, 1);
  assert.deepEqual(s.avatar.box, { x: 100, y: 100, width: 400, height: 800 });
  assert.equal(s.avatar.mediaBox.x, -400); assert.equal(s.avatar.mediaBox.height, 800);
  const cw = 1422.2222, fb = CTX.faceBox;
  assert.ok(Math.abs(s.avatar.faceBox.x - (-400 + fb.x * cw)) < 0.01);
  assert.ok(Math.abs(s.avatar.faceBox.y - (100 + fb.y * 800)) < 0.01);
  assert.ok(Math.abs(s.avatar.faceBox.width - fb.w * cw) < 0.01 && Math.abs(s.avatar.faceBox.height - fb.h * 800) < 0.01);
  assert.equal(s.avatar.faceBoxSource, 'episode');
  assert.deepEqual(s.layers.map(l => [l.kind, l.id, l.opacity]), [['avatar', 'avatar', 1], ['stage', 'stage-3', 0.5]]);
  assert.deepEqual(s.footage.origin, 'stock');
});

test('browser: a missing presenter before the voice-over ends is a probe failure, not a silent pass', () => {
  assert.match(R.noAvatar.error, /missing avatar measurement/);
});
