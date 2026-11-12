import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import {
  DEFAULTS,
  findDarkDips,
  isDraftName,
  extractBeatStarts,
  annotateWithBeats,
} from '../qc_final_pixels.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT = path.join(here, '..', 'qc_final_pixels.mjs');
const FIXTURE = path.join(here, 'fixtures', 'final-pixels-v261111-v3-yavg.json');
const FPS = 25;

const rep = (value, count) => Array(count).fill(value);

test('defaults are the documented thresholds', () => {
  assert.equal(DEFAULTS.darkMax, 22);
  assert.equal(DEFAULTS.dropMin, 12);
  assert.equal(DEFAULTS.minRunFrames, 2);
  assert.equal(DEFAULTS.recoverRise, 8);
  assert.equal(DEFAULTS.recoverWindowSec, 1.0);
  assert.equal(DEFAULTS.lookbackFrames, 3);
});

test('1. bright -> abrupt dark for 3 frames -> ramps back = one flash', () => {
  const y = [...rep(100, 20), 16, 16, 16, 18, 22, 28, 36, 46, 60, 80, ...rep(100, 20)];
  const dips = findDarkDips(y, { fps: FPS });
  assert.equal(dips.length, 1);
  assert.equal(dips[0].kind, 'flash');
  assert.equal(dips[0].startFrame, 20);
  assert.equal(dips[0].startSec, 0.8);
  assert.equal(dips[0].minY, 16);
  assert.equal(dips[0].beforeY, 100);
  assert.ok(dips[0].recoveredToY >= 100);
});

test('2. sustained dark scene (100 flat frames, no recovery in window) = no dip', () => {
  const y = [...rep(100, 20), ...rep(16, 100), ...rep(100, 20)];
  assert.deepEqual(findDarkDips(y, { fps: FPS }), []);
});

test('3. a single dark frame is not a dip with the default minRunFrames', () => {
  const y = [...rep(100, 20), 16, ...rep(100, 20)];
  assert.deepEqual(findDarkDips(y, { fps: FPS }), []);
  // and it IS one when the run requirement is relaxed (proves the rule is what hides it)
  assert.equal(findDarkDips(y, { fps: FPS, minRunFrames: 1 }).length, 1);
});

test('4. a dip at or after voEndSec is ignored', () => {
  const dipAt = (frame) => {
    const y = rep(100, 400);
    y.splice(frame, 6, 16, 16, 17, 20, 30, 50);
    return y;
  };
  assert.equal(findDarkDips(dipAt(100), { fps: FPS, voEndSec: 10 }).length, 1);
  assert.equal(findDarkDips(dipAt(300), { fps: FPS, voEndSec: 10 }).length, 0); // 12 s > 10 s
  assert.equal(findDarkDips(dipAt(250), { fps: FPS, voEndSec: 10 }).length, 0); // exactly at 10 s
  assert.equal(findDarkDips(dipAt(300), { fps: FPS }).length, 1); // no voEndSec: still found
});

test('5. the 157.66 pattern (19 19 19 | 17 19 21 24 27 ...) = one dark-entry', () => {
  const synthetic = [
    ...rep(60, 10),
    34, 30, 26, 23, 21, 20, // gradual fade down into the dark scene
    ...rep(19, 40),
    17, 19, 21, 24, 27, 31, 34, 37, 40, 42, 43, 44, 45, 45, ...rep(45, 20),
  ];
  const dips = findDarkDips(synthetic, { fps: FPS });
  assert.equal(dips.length, 1);
  assert.equal(dips[0].kind, 'dark-entry');
  assert.equal(dips[0].startFrame, 10 + 6 + 40);
  assert.equal(dips[0].minY, 17);
  assert.equal(dips[0].beforeY, 19);

  // same pattern with the real surrounding values from the V3 render
  const fx = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));
  const real = fx.yavg.slice(3700, 4100);
  const realDips = findDarkDips(real, { fps: FPS });
  assert.equal(realDips.length, 1, JSON.stringify(realDips));
  assert.equal(realDips[0].kind, 'dark-entry');
  assert.ok(Math.abs((3700 + realDips[0].startFrame) / FPS - 157.66) <= 0.08);
});

test('non-defects: gradual fade down into dark, and slow fade-in from sustained dark', () => {
  const fx = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));
  // 11.5 s: fade DOWN 48 -> 22 over ~8 frames, dark, then up to a bright scene
  assert.deepEqual(findDarkDips(fx.yavg.slice(270, 340), { fps: FPS }), []);
  // 414.56 s: 5.6 s of flat dark (~19) then a rise out of it, no step down first
  assert.deepEqual(findDarkDips(fx.yavg.slice(10300, 10560), { fps: FPS }), []);
  // synthetic slow fade-in from flat darkness
  const slow = [...rep(16, 80), 17, 19, 23, 28, 36, 46, 60, ...rep(60, 30)];
  assert.deepEqual(findDarkDips(slow, { fps: FPS }), []);
});

test('6. real V3 render: every one of the 15 known bad boundaries is detected, so the gate FAILS', () => {
  const fx = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));
  assert.equal(fx.fps, FPS);
  assert.equal(fx.knownBadBoundariesSec.length, 15);
  assert.ok(fx.yavg.length > 16000);
  const dips = findDarkDips(fx.yavg, { fps: fx.fps, voEndSec: fx.voEndSec });
  const list = dips.map((d) => `${d.startSec}s ${d.kind} minY=${d.minY} beforeY=${d.beforeY}`).join('; ');
  for (const known of fx.knownBadBoundariesSec) {
    const hit = dips.find((d) => Math.abs(d.startSec - known) <= 0.08);
    assert.ok(hit, `no dip within 0.08 s of known boundary ${known}s. dips: ${list}`);
  }
  // Every detection is one of the 15 (investigated: no additional dips on V3).
  assert.equal(dips.length, 15, `expected exactly the 15 known dips, got ${dips.length}: ${list}`);
  assert.ok(dips.length > 0, 'gate must fail on V3');
  assert.deepEqual(
    dips.filter((d) => d.kind === 'dark-entry').map((d) => Math.round(d.startSec)),
    [158, 519],
  );
});

test('near-miss: 515.72 s (drop 40 -> 17 then only +7.05 recovery) is deliberately NOT flagged', () => {
  // Documented near-miss: the picture drops from ~40 to 17 at a scene change but only
  // recovers to ~24 (the next scene is itself dark), +7.05 < recoverRise (8). recoverRise
  // stays at 8 by decision; a separate DOM-side rule covers that mechanism.
  const fx = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));
  const dips = findDarkDips(fx.yavg, { fps: fx.fps, voEndSec: fx.voEndSec });
  assert.ok(!dips.some((d) => Math.abs(d.startSec - 515.72) <= 0.5), '515.72 s must not be flagged');
  assert.equal(findDarkDips(fx.yavg.slice(12800, 12960), { fps: FPS }).length, 0);
});

test('7. isDraftName', () => {
  assert.equal(isDraftName('final.mp4'), false);
  assert.equal(isDraftName('visual.draft.mp4'), true);
  assert.equal(isDraftName('ep_draft.mp4'), true);
  assert.equal(isDraftName('drafting.mp4'), false);
  assert.equal(isDraftName('Draft.mp4'), true);
  assert.equal(isDraftName('ep-DRAFT-v2.mp4'), true);
});

test('beats: extraction shapes and nearBeatSec annotation', () => {
  assert.equal(extractBeatStarts({ issues: [], beats: 82, pass: true }), null);
  assert.deepEqual(extractBeatStarts([1, 2.5]), [1, 2.5]);
  // V4 episode.json shape: { ..., "beats": [ { "t": <seconds>, ... }, ... ] }
  const episode = { id: 'ep', title: 'x', beats: [{ t: 0, mode: 'full' }, { t: 19.34, layout: 'split' }, { t: 59.24 }] };
  assert.deepEqual(extractBeatStarts(episode), [0, 19.34, 59.24]);
  assert.deepEqual(
    annotateWithBeats([{ startSec: 19.36 }, { startSec: 59.24 }, { startSec: 80 }], extractBeatStarts(episode)),
    [{ startSec: 19.36, nearBeatSec: 19.34 }, { startSec: 59.24, nearBeatSec: 59.24 }, { startSec: 80 }],
  );
  assert.deepEqual(extractBeatStarts({ beats: [{ t: 0 }, { t: 19.3 }, { id: 'x' }] }), [0, 19.3]);
  const dips = [{ startSec: 19.36 }, { startSec: 100 }];
  assert.deepEqual(annotateWithBeats(dips, [0, 19.3, 30]), [{ startSec: 19.36, nearBeatSec: 19.3 }, { startSec: 100 }]);
});

test('CLI refuses a draft file (exit 2) without needing the file to exist', () => {
  const r = spawnSync(process.execPath, [SCRIPT, '/nonexistent/visual.draft.mp4', os.tmpdir()], { encoding: 'utf8' });
  assert.equal(r.status, 2);
  assert.match(r.stderr, /draft/i);
});

test('CLI usage error exits 2', () => {
  const r = spawnSync(process.execPath, [SCRIPT], { encoding: 'utf8' });
  assert.equal(r.status, 2);
});

const hasFfmpeg = spawnSync('ffmpeg', ['-version']).status === 0;
test('CLI end to end on a tiny generated clip (white -> 3 dark frames -> grey)', { skip: !hasFfmpeg }, () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'final-pixels-'));
  try {
    const video = path.join(dir, 'final.mp4');
    const gen = spawnSync(
      'ffmpeg',
      [
        '-v', 'error', '-y',
        '-f', 'lavfi', '-i', 'color=c=white:s=64x64:r=25:d=1',
        '-f', 'lavfi', '-i', 'color=c=black:s=64x64:r=25:d=0.12',
        '-f', 'lavfi', '-i', 'color=c=gray:s=64x64:r=25:d=1',
        '-filter_complex', '[0][1][2]concat=n=3:v=1:a=0',
        '-pix_fmt', 'yuv420p', '-c:v', 'libx264', video,
      ],
      { encoding: 'utf8', timeout: 60000 },
    );
    assert.equal(gen.status, 0, gen.stderr);
    const out = path.join(dir, 'out');
    const episode = path.join(dir, 'episode.json');
    fs.writeFileSync(episode, JSON.stringify({ beats: [{ t: 0 }, { t: 1.0 }] }));
    const r = spawnSync(process.execPath, [SCRIPT, video, out, '--beats', episode], { encoding: 'utf8', timeout: 120000 });
    assert.equal(r.status, 1, r.stderr + r.stdout);
    assert.match(r.stdout, /FINAL_PIXELS pass=false dips=1 report=/);
    const report = JSON.parse(fs.readFileSync(path.join(out, 'final-pixels.json'), 'utf8'));
    assert.equal(report.schema, 'yt-news-final-pixels');
    assert.equal(report.pass, false);
    assert.equal(report.draft, false);
    assert.equal(report.certified, false); // failing file is never certified
    assert.equal(report.dips[0].nearBeatSec, 1.0);
    assert.match(report.startedAt, /^\d{4}-\d\d-\d\dT/);
    assert.match(report.finishedAt, /^\d{4}-\d\d-\d\dT/);
    assert.ok(Date.parse(report.finishedAt) >= Date.parse(report.startedAt));
    assert.equal(typeof report.runtimeSec, 'number');
    assert.ok(report.runtimeSec >= 0);
    assert.equal(report.fps, 25);
    assert.equal(report.frameCount, 53);
    assert.equal(report.dips.length, 1);
    assert.equal(report.dips[0].kind, 'flash');
    assert.match(report.videoSha256, /^[0-9a-f]{64}$/);
    assert.ok(!fs.existsSync(path.join(out, 'final-pixels.json.tmp')));
    // an all-white clip passes
    const white = path.join(dir, 'white.mp4');
    const g2 = spawnSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=white:s=64x64:r=25:d=1', '-pix_fmt', 'yuv420p', '-c:v', 'libx264', white], { timeout: 60000 });
    assert.equal(g2.status, 0);
    const r2 = spawnSync(process.execPath, [SCRIPT, white, path.join(dir, 'out2')], { encoding: 'utf8', timeout: 120000 });
    assert.equal(r2.status, 0, r2.stderr);
    assert.match(r2.stdout, /pass=true dips=0/);
    const rep2 = JSON.parse(fs.readFileSync(path.join(dir, 'out2', 'final-pixels.json'), 'utf8'));
    assert.equal(rep2.certified, true);
    assert.equal(rep2.draft, false);
    // draft + --allow-draft => report, certified:false
    const draft = path.join(dir, 'x.draft.mp4');
    fs.copyFileSync(white, draft);
    const r3 = spawnSync(process.execPath, [SCRIPT, draft, path.join(dir, 'out3'), '--allow-draft'], { encoding: 'utf8', timeout: 120000 });
    assert.equal(r3.status, 0, r3.stderr);
    const rep3 = JSON.parse(fs.readFileSync(path.join(dir, 'out3', 'final-pixels.json'), 'utf8'));
    assert.equal(rep3.pass, true);
    assert.equal(rep3.draft, true);
    assert.equal(rep3.certified, false);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
