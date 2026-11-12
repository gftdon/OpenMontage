#!/usr/bin/env node
/*
 * qc_final_pixels.mjs - "dark flash" gate on a RENDERED mp4 (CF-A66).
 *
 * Defect being caught: at a scene change the picture drops abruptly to the dark
 * navy background (mean luma ~15-17) and then fades back up. The layout QC
 * samples DOM frames, so it cannot see this; this gate measures the real
 * pixels of the final file: one mean-luma (ffmpeg signalstats YAVG) value for
 * EVERY frame, then pure functions look for dips.
 *
 * Usage:
 *   node qc_final_pixels.mjs <video.mp4> <out-dir> [--vo-end <seconds>]
 *        [--beats <beats.json>] [--allow-draft] [--dump-yavg <file.json>]
 *   exit 0 = pass, 1 = dips found, 2 = usage / IO / measurement error.
 *
 * DETECTION RULE (findDarkDips, all numbers are DEFAULTS and are overridable)
 *   y[i]        mean luma (0..255) of frame i.   dark = y <= darkMax (22).
 *   Frames are scanned in order. Frame n is a CANDIDATE when ALL hold:
 *     1. y[n] <= darkMax, n >= 1 and startSec = n/fps is before voEndSec
 *        (frames at or after the end of the voice-over are ignored: fade-out,
 *        end card).
 *     2. Let lb = the `lookbackFrames` (3) frames just before n (fewer near the
 *        file start) and beforeY = median(lb). The drop is abrupt:
 *          kind "flash":      beforeY >= y[n] + dropMin (12), or
 *          kind "dark-entry": not a flash, but the previous picture was flat
 *                             (max(lb) - min(lb) <= entryFlatMax (1.0)) and
 *                             beforeY - y[n] >= entryDropMin (1.5), i.e. a real
 *                             step down from an almost-as-dark scene (e.g.
 *                             19 19 19 | 17 19 21 24 ...).
 *        Anything else (no decrease, noise, a gradual fade DOWN into dark) is
 *        the continuation of the previous scene, not a new dip.
 *     3. The dark run starting at n (consecutive frames <= darkMax) is at
 *        least `minRunFrames` (2) long: a single dark frame is not reported.
 *     4. The picture RECOVERS: max(y[n .. n + recoverWindowSec*fps]) >=
 *        minY + recoverRise (8), minY = minimum luma of the run. A scene that
 *        stays dark (no recovery inside the 1.0 s window) is legitimate dark
 *        footage and is NOT a dip.
 *   Once frame n passes rules 1-2 the scan jumps to the end of its dark run
 *   whether or not it is reported, so one dark run yields at most one dip
 *   (overlapping detections are merged) and a long dark scene is never
 *   re-tested from the middle. A slow fade-in out of sustained darkness has no
 *   step down at its start (rule 2) and is therefore not reported.
 *   Both kinds count as failures: pass = (dips.length === 0).
 *
 * Report: <out-dir>/final-pixels.json (written atomically). Drafts are never
 * certified: a basename containing a "draft" token is refused (exit 2) unless
 * --allow-draft is given. The report has draft:<bool> (name matches the draft
 * pattern) and certified = pass && !draft, so a failing or draft file is never
 * certified. It also records startedAt / finishedAt (ISO) and runtimeSec.
 */
import fs from 'node:fs';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

export const DEFAULTS = {
  darkMax: 22,
  dropMin: 12,
  minRunFrames: 2,
  recoverRise: 8,
  recoverWindowSec: 1.0,
  lookbackFrames: 3,
  // Extensions used only by the "dark-entry" kind (see rule 2 above).
  entryDropMin: 1.5,
  entryFlatMax: 1.0,
};

const BEAT_NEAR_SEC = 0.6;
const DRAFT_RE = /(^|[._-])draft([._-]|$)/i;

export function isDraftName(basename) {
  return DRAFT_RE.test(basename);
}

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

const round2 = (v) => Math.round(v * 100) / 100;

export function findDarkDips(yavg, { fps, voEndSec, ...overrides } = {}) {
  if (!(fps > 0)) throw new Error('findDarkDips: fps must be > 0');
  const t = { ...DEFAULTS, ...overrides };
  const windowFrames = Math.round(t.recoverWindowSec * fps);
  const dips = [];
  let n = 1;
  while (n < yavg.length) {
    if (voEndSec != null && n / fps >= voEndSec) break;
    if (!(yavg[n] <= t.darkMax)) {
      n += 1;
      continue;
    }
    const lookback = yavg.slice(Math.max(0, n - t.lookbackFrames), n);
    const beforeY = median(lookback);
    const flat = Math.max(...lookback) - Math.min(...lookback) <= t.entryFlatMax;
    let kind = null;
    if (beforeY >= yavg[n] + t.dropMin) kind = 'flash';
    else if (flat && beforeY - yavg[n] >= t.entryDropMin) kind = 'dark-entry';
    if (!kind) {
      n += 1;
      continue;
    }
    let runEnd = n;
    while (runEnd < yavg.length && yavg[runEnd] <= t.darkMax) runEnd += 1;
    const runFrames = runEnd - n;
    let minY = Infinity;
    for (let i = n; i < runEnd; i += 1) minY = Math.min(minY, yavg[i]);
    let maxAfter = -Infinity;
    const windowEnd = Math.min(yavg.length - 1, n + windowFrames);
    for (let i = n; i <= windowEnd; i += 1) maxAfter = Math.max(maxAfter, yavg[i]);
    if (runFrames >= t.minRunFrames && maxAfter >= minY + t.recoverRise) {
      dips.push({
        startFrame: n,
        endFrame: runEnd - 1,
        startSec: round2(n / fps),
        runFrames,
        minY: round2(minY),
        beforeY: round2(beforeY),
        recoveredToY: round2(maxAfter),
        kind,
      });
    }
    n = runEnd;
  }
  return dips;
}

// Accepts an array of numbers, an array of objects with a start-time field,
// or an object holding such an array under beats/items/scenes/timeline.
export function extractBeatStarts(json) {
  const list = Array.isArray(json)
    ? json
    : ['beats', 'items', 'scenes', 'timeline'].map((k) => json?.[k]).find(Array.isArray);
  if (!list) return null;
  const starts = list
    .map((b) => {
      if (typeof b === 'number') return b;
      if (b && typeof b === 'object') {
        for (const k of ['t', 'start', 'startSec', 'start_sec', 'time', 'startTime']) {
          if (typeof b[k] === 'number') return b[k];
        }
      }
      return null;
    })
    .filter((v) => Number.isFinite(v));
  return starts.length ? starts : null;
}

export function annotateWithBeats(dips, beatStarts) {
  return dips.map((dip) => {
    let best = null;
    for (const b of beatStarts) {
      if (Math.abs(b - dip.startSec) <= BEAT_NEAR_SEC && (best === null || Math.abs(b - dip.startSec) < Math.abs(best - dip.startSec))) {
        best = b;
      }
    }
    return best === null ? dip : { ...dip, nearBeatSec: best };
  });
}

function probeVideo(video) {
  const r = spawnSync(
    'ffprobe',
    ['-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=nb_frames,r_frame_rate,duration', '-of', 'json', video],
    { encoding: 'utf8', timeout: 60000 },
  );
  if (r.status !== 0) throw new Error(`ffprobe failed: ${(r.stderr || r.error?.message || '').slice(0, 300)}`);
  const s = JSON.parse(r.stdout).streams?.[0];
  if (!s) throw new Error('ffprobe: no video stream');
  const [num, den] = String(s.r_frame_rate).split('/').map(Number);
  const fps = num / (den || 1);
  if (!(fps > 0)) throw new Error(`ffprobe: bad frame rate ${s.r_frame_rate}`);
  let frameCount = Number(s.nb_frames);
  if (!Number.isFinite(frameCount)) {
    const duration = Number(s.duration);
    if (!Number.isFinite(duration)) throw new Error('ffprobe: no frame count and no duration');
    frameCount = Math.round(duration * fps);
  }
  return { fps, frameCount };
}

function measureYavg(video) {
  return new Promise((resolve, reject) => {
    const args = [
      '-v', 'error', '-i', video,
      '-vf', 'signalstats,metadata=mode=print:key=lavfi.signalstats.YAVG:file=-',
      '-an', '-f', 'null', '-',
    ];
    const child = spawn('ffmpeg', args, { stdio: ['ignore', 'pipe', 'pipe'] });
    const values = [];
    let stderrTail = '';
    child.stderr.on('data', (chunk) => {
      stderrTail = (stderrTail + chunk.toString()).slice(-2000);
    });
    const rl = createInterface({ input: child.stdout });
    rl.on('line', (line) => {
      const m = /^lavfi\.signalstats\.YAVG=([0-9.eE+-]+)/.exec(line);
      if (m) values.push(Number(m[1]));
    });
    child.on('error', reject);
    child.on('close', (code) => {
      if (code !== 0) reject(new Error(`ffmpeg exited ${code}: ${stderrTail.trim()}`));
      else resolve(values);
    });
  });
}

function sha256File(file) {
  return new Promise((resolve, reject) => {
    const h = createHash('sha256');
    fs.createReadStream(file)
      .on('data', (d) => h.update(d))
      .on('error', reject)
      .on('end', () => resolve(h.digest('hex')));
  });
}

function writeJsonAtomic(file, data) {
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2));
  fs.renameSync(tmp, file);
}

function parseArgs(argv) {
  const opts = { positional: [], allowDraft: false };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--allow-draft') opts.allowDraft = true;
    else if (a === '--vo-end') opts.voEnd = argv[++i];
    else if (a === '--beats') opts.beats = argv[++i];
    else if (a === '--dump-yavg') opts.dumpYavg = argv[++i];
    else if (a.startsWith('--')) throw new Error(`unknown option ${a}`);
    else opts.positional.push(a);
  }
  if (opts.positional.length !== 2) throw new Error('expected <video.mp4> <out-dir>');
  if (opts.voEnd !== undefined) {
    opts.voEnd = Number(opts.voEnd);
    if (!Number.isFinite(opts.voEnd) || opts.voEnd <= 0) throw new Error('--vo-end must be a positive number of seconds');
  }
  return opts;
}

export async function main(argv) {
  let opts;
  try {
    opts = parseArgs(argv);
  } catch (err) {
    console.error(`qc_final_pixels: ${err.message}\nusage: node qc_final_pixels.mjs <video.mp4> <out-dir> [--vo-end <sec>] [--beats <beats.json>] [--allow-draft] [--dump-yavg <file>]`);
    return 2;
  }
  const video = path.resolve(opts.positional[0]);
  const outDir = path.resolve(opts.positional[1]);
  const draft = isDraftName(path.basename(video));
  if (draft && !opts.allowDraft) {
    console.error(`qc_final_pixels: refusing draft file "${path.basename(video)}" (drafts are never certified; pass --allow-draft for a non-certified report)`);
    return 2;
  }
  try {
    if (!fs.statSync(video).isFile()) throw new Error('not a file');
  } catch (err) {
    console.error(`qc_final_pixels: cannot read video ${video}: ${err.message}`);
    return 2;
  }
  const startedMs = Date.now();
  const startedAt = new Date(startedMs).toISOString();
  try {
    const { fps, frameCount } = probeVideo(video);
    const yavg = await measureYavg(video);
    if (Math.abs(yavg.length - frameCount) > 1) {
      console.error(`qc_final_pixels: measured ${yavg.length} YAVG samples but the file has ${frameCount} frames`);
      return 2;
    }
    const voEndSec = opts.voEnd ?? null;
    let dips = findDarkDips(yavg, { fps, voEndSec: voEndSec ?? undefined });
    if (opts.beats) {
      const starts = extractBeatStarts(JSON.parse(fs.readFileSync(opts.beats, 'utf8')));
      if (starts) dips = annotateWithBeats(dips, starts);
    }
    fs.mkdirSync(outDir, { recursive: true });
    if (opts.dumpYavg) {
      fs.writeFileSync(path.resolve(opts.dumpYavg), JSON.stringify(yavg.map((v) => Math.round(v))));
    }
    const pass = dips.length === 0;
    const report = {
      schema: 'yt-news-final-pixels',
      version: 1,
      video,
      videoSha256: await sha256File(video),
      fps,
      frameCount,
      voEndSec,
      thresholds: { ...DEFAULTS },
      draft,
      certified: pass && !draft,
      dips,
      pass,
      startedAt,
      finishedAt: new Date().toISOString(),
      runtimeSec: Math.round((Date.now() - startedMs) / 100) / 10,
    };
    const reportPath = path.join(outDir, 'final-pixels.json');
    writeJsonAtomic(reportPath, report);
    console.log(`FINAL_PIXELS pass=${pass} dips=${dips.length} report=${reportPath}`);
    return pass ? 0 : 1;
  } catch (err) {
    console.error(`qc_final_pixels: ${err.message}`);
    return 2;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main(process.argv.slice(2)).then((code) => process.exit(code));
}
