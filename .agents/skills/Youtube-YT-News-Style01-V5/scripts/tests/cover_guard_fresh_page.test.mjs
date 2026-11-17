// CF-A66 round 10, Fix C: CoverGuard decides with the real font even when its frame is the FIRST frame rendered in a fresh page.
//
// The bug: CoverGuard measured its text in a layout effect before the font had loaded (a fresh page has no KanitX yet), so it used
// fallback-font widths (845.6 px instead of 882 px for the title below) and left a title visible that the presenter box had reached.
// The title's real right edge + 8 is above the presenter's rect.x at the chosen frame; the fallback-font right edge + 8 is not.
//
// This test measures ONE frame with ONE worker through the real gate (qc_layout.mjs, real Chrome + Remotion), so the frame is the
// first one that page ever renders. It needs Chrome, the composer's node_modules and the git-ignored sample media under
// remotion-composer/public/ytNewsV3BrollTest; when any is absent it is SKIPPED with a message (never a false pass).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFile } from 'node:child_process';
import { loadEngine } from './_engine_bundle.mjs';

const root = path.resolve(new URL('../../../../..', import.meta.url).pathname);
const composer = path.join(root, 'remotion-composer');
const skill = path.join(root, '.agents/skills/Youtube-YT-News-Style01-V5');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sampleEpisode = path.join(composer, 'src/ytNewsStyle01V4Sample.json');
const sampleCaptions = path.join(composer, 'src/ytNewsStyle01V4SampleCaptions.json');

const missing = [
  [fs.existsSync(CHROME), `Chrome not found at ${CHROME}`],
  [fs.existsSync(path.join(composer, 'node_modules/@remotion/renderer')), 'remotion-composer/node_modules is not installed'],
  [fs.existsSync(path.join(composer, 'public/ytNewsV3BrollTest/avatar_source.mp4')), 'sample media remotion-composer/public/ytNewsV3BrollTest is absent (git-ignored)'],
  [fs.existsSync(path.join(composer, 'public/ytNewsV3BrollTest/broll')), 'sample b-roll remotion-composer/public/ytNewsV3BrollTest/broll is absent (git-ignored)'],
].filter(([ok]) => !ok).map(([, why]) => why);

// A T card title that sits in the blind spot: real ink right edge 1001.98 px at 76 px / 800 (x from 120), fallback-font edge 965.6 px.
const TITLE = 'จากภาพแปลนสู่พื้นที่จำลอง';
const T_BEAT = 5;       // sample beat 5 is a T card, beat 6 is P (the T -> P transition)
const FRAME_AFTER = 5;  // the 5th frame after the P beat starts: presenter rect.x = 976.47
const FALLBACK_RIGHT_EDGE = 120 + 845.6, REAL_RIGHT_EDGE = 120 + 882;

const run = (args, timeout) => new Promise(resolve => {
  execFile(process.execPath, args, { timeout, maxBuffer: 64 * 1024 * 1024, cwd: root }, (error, stdout, stderr) => resolve({ code: error ? (error.code ?? 1) : 0, stdout, stderr }));
});

test('fresh page, first frame = T -> P blind-spot frame: the title the presenter reached is hidden and there is no occlusion', { skip: missing.length ? `SKIPPED: ${missing.join('; ')}` : false, timeout: 170000 }, async () => {
  const engine = await loadEngine();
  const episode = JSON.parse(fs.readFileSync(sampleEpisode, 'utf8'));
  const B = episode.beats;
  assert.equal(engine.sceneKind(B[T_BEAT]), 'T'); assert.equal(engine.sceneKind(B[T_BEAT + 1]), 'P');
  const frame = Math.ceil(B[T_BEAT + 1].t * episode.fps) + FRAME_AFTER;
  const coverX = engine.layerPlan(frame, B, episode.fps).avatar.rect.x;
  // the fixture really is in the blind spot: fallback edge + 8 does not reach the presenter, the real edge + 8 does
  assert.ok(FALLBACK_RIGHT_EDGE + 8 <= coverX, `fallback edge ${FALLBACK_RIGHT_EDGE + 8} must not reach rect.x ${coverX}`);
  assert.ok(REAL_RIGHT_EDGE + 8 > coverX, `real edge ${REAL_RIGHT_EDGE + 8} must reach rect.x ${coverX}`);

  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'cover-guard-fresh-'));
  try {
    const fixture = { ...episode, beats: B.map((b, i) => (i === T_BEAT ? { ...b, headline: TITLE } : b)) };
    const ep = path.join(tmp, 'episode.json'); fs.writeFileSync(ep, JSON.stringify(fixture));
    const out = path.join(tmp, 'out');
    const r = await run([path.join(skill, 'scripts/qc_layout.mjs'), '--episode', ep, '--captions', sampleCaptions, '--out', out, '--composer', composer, '--max-seconds', '120', '--workers', '1', '--frames', String(frame)], 160000);
    const last = r.stdout.trim().split('\n').pop();
    assert.match(last, /^QC_LAYOUT COMPLETE /, `gate did not complete: ${last}\n${r.stderr.slice(-800)}`);
    const runDir = path.join(out, 'runs', fs.readdirSync(path.join(out, 'runs'))[0]);
    const report = JSON.parse(fs.readFileSync(path.join(runDir, 'report.json'), 'utf8'));
    assert.equal(report.measuredCount, 1, 'exactly one frame measured');
    const codes = report.issues.map(i => i.code ?? i.id);
    assert.ok(!codes.includes('occlusion'), `no occlusion expected, got ${JSON.stringify(report.issues)}`);
    const sample = JSON.parse(fs.readFileSync(path.join(runDir, `${frame}.json`), 'utf8')).sample;
    const title = sample.fields.find(f => f.id === 'typo-title');
    assert.ok(title, 'typo-title is measured at the transition frame');
    const right = Math.max(...title.rects.map(x => x.x + x.width));
    assert.ok(Math.abs(right - REAL_RIGHT_EDGE) < 1, `the title was laid out with the real font (right edge ${right}, expected ${REAL_RIGHT_EDGE})`);
    assert.ok(Math.abs(sample.avatar.box.x - coverX) < 0.01, `presenter box x ${sample.avatar.box.x} vs plan ${coverX}`);
    assert.equal(title.opacity, 0, 'the title the presenter reached is hidden (not visible) for this frame');
  } finally { fs.rmSync(tmp, { recursive: true, force: true }); }
});
