#!/usr/bin/env node
// Final render of one YtNewsStyle01V4 episode: guarded, resumable, time-budgeted.
//
// Why it looks like this:
//   - every command of the automated pipeline is killed after ~10 minutes, so the render is cut into
//     segments and one invocation never runs longer than --max-seconds (default 420). Exit 75 means
//     "call me again with the same --render-id";
//   - a final (non-draft) render is only allowed when the layout gate passed for exactly these sources
//     (episode, captions, engine, entry + its import closure, qc scripts, media, fonts), checked at start and again before concat;
//   - nothing is renamed silently: a `.draft.` file name is a draft, a draft is never a final.
//
// Usage:
//   node render_episode.mjs --episode <episode.json> --captions <captions.json> --composer <remotion-composer>
//        --out <file.mp4> [--gate-report <qc/layout/report.json>] [--render-id <id>] [--max-seconds 420]
//        [--segment-frames 750] [--concurrency 4] [--draft]
//
// Exit codes: 0 complete | 75 incomplete, call again | 3 refused (gate / draft rule / integrity incl. gates lock / validation)
//             4 resume refused (sources changed since the render started) | 2 crash or usage error
//
// Only renderSegment(), selectDuration() and ensureBundle() touch Remotion (loaded lazily from the
// composer's node_modules); everything else is plain Node + ffmpeg/ffprobe and is unit-tested.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {randomUUID} from 'node:crypto';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {
  COMPOSITION_ID, MANIFEST_SCHEMA, canonicalJSON, computeBundleCodeKey, computeSourceHashes, diffManifests, entryPointOf, ENTRY_REL,
  manifestHash as hashManifest, readJson, readRemotionVersion, sha256File, writeJsonAtomic,
} from './qc_manifest.mjs';
import {digestDir, stagePublicDir} from './media_digest.mjs';
import {checkIntegrity} from './gate_integrity.mjs';

const execFileP = promisify(execFile);

export const FPS = 25;
export const WIDTH = 1920;
export const HEIGHT = 1080;
export const EXIT = {COMPLETE: 0, CRASH: 2, REFUSED: 3, RESUME_REFUSED: 4, INCOMPLETE: 75};
export const RENDER_MANIFEST_SCHEMA = 'yt-news-v4-render-manifest';
export const RECEIPT_SCHEMA = 'yt-news-v4-render-receipt';
// colorSpace 'bt709': with Remotion's default colour space the encoder is not told the range and ffmpeg writes a full-range
// "yuvj420p" file from the JPEG frames, which is not the yuv420p this contract (and every player/uploader) expects.
export const ENCODER = Object.freeze({codec: 'h264', crf: 20, pixelFormat: 'yuv420p', x264Preset: 'medium', colorSpace: 'bt709', muted: true});
export const DEFAULTS = Object.freeze({maxSeconds: 420, segmentFrames: 750, concurrency: 4, renderSafetyFactor: 1.5});
const CHROME_PATH = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

/**
 * The receipt field names are a contract with the team that consumes receipts. Do not rename.
 * CF-A66: V4 bundles from its own entry, so rootTsxSha256 / indexTsxSha256 (hashes of Root.tsx / index.tsx) are gone and
 * entrySha256 (the entry file), entryReferenceSha256 and entryClosure ({"src/<file>": sha256} of the entry and every file it imports) took their place.
 */
export const RECEIPT_FIELDS = Object.freeze([
  'schema', 'schemaVersion', 'compositionId',
  'renderId', 'draft', 'outputPath', 'outputFileName', 'outputSha256', 'outputBytes',
  'frameCount', 'durationInFrames', 'fps', 'width', 'height', 'codec', 'pixelFormat', 'hasAudio',
  'episodeJsonSha256', 'captionsJsonSha256', 'engineSha256', 'engineReferenceSha256', 'entrySha256', 'entryReferenceSha256', 'entryClosure',
  'fontsDigest', 'mediaDigest', 'mediaDigestMethod', 'gatesLockSha256',
  'gateReportPath', 'gateReportSha256', 'gateRunId', 'gateManifestHash', 'gateCheckedAtStart', 'gateCheckedAtConcat',
  'segments', 'tools', 'startedAt', 'finishedAt', 'wallSecondsTotal', 'invocations',
]);

export const USAGE = `usage: render_episode.mjs --episode <episode.json> --captions <captions.json> --composer <remotion-composer-dir> --out <file.mp4>
         [--gate-report <qc/layout/report.json>] [--render-id <id>] [--max-seconds ${DEFAULTS.maxSeconds}]
         [--segment-frames ${DEFAULTS.segmentFrames}] [--concurrency ${DEFAULTS.concurrency}] [--draft]
  final render : --gate-report is required, the file name must not contain ".draft.", and scripts/gates.lock.json must exist,
                 be valid and match (checked at start and before the concat)
  draft render : --draft is required, the file name must contain ".draft.", the gate is skipped; engine drift and gates-lock
                 problems are only warnings (recorded in render-manifest.json), entry registration / closure problems still refuse
  exit codes   : 0 complete | 75 incomplete (re-run with the same --render-id) | 3 refused | 4 resume refused | 2 crash/usage`;

export class UsageError extends Error {}
export class RefusedError extends Error {}
export class ResumeRefusedError extends Error {
  constructor(field) { super(`resume refused: ${field}`); this.field = field; }
}

// ---------------------------------------------------------------------------------------------
// arguments and naming rules
// ---------------------------------------------------------------------------------------------

const VALUE_FLAGS = {
  '--episode': 'episode', '--captions': 'captions', '--composer': 'composer', '--out': 'out',
  '--gate-report': 'gateReport', '--render-id': 'renderId', '--max-seconds': 'maxSeconds',
  '--segment-frames': 'segmentFrames', '--concurrency': 'concurrency',
};

/** Parse the command line. Throws UsageError. `defaults` lets thresholds override the built-ins. */
export function parseArgs(argv, defaults = {}) {
  const base = {...DEFAULTS, ...defaults};
  const args = {draft: false, maxSeconds: base.maxSeconds, segmentFrames: base.segmentFrames, concurrency: base.concurrency};
  for (let i = 0; i < argv.length; i++) {
    const flag = argv[i];
    if (flag === '--draft') { args.draft = true; continue; }
    const key = VALUE_FLAGS[flag];
    if (!key) throw new UsageError(`unknown argument: ${flag}`);
    const value = argv[++i];
    if (value === undefined || value.startsWith('--')) throw new UsageError(`${flag} needs a value`);
    args[key] = value;
  }
  for (const required of ['episode', 'captions', 'composer', 'out']) {
    if (!args[required]) throw new UsageError(`--${required} is required`);
  }
  if (!/\.mp4$/i.test(args.out)) throw new UsageError('--out must end in .mp4');
  const intOf = (name, value, min) => {
    const n = Number(value);
    if (!Number.isInteger(n) || n < min) throw new UsageError(`${name} must be an integer >= ${min}`);
    return n;
  };
  args.segmentFrames = intOf('--segment-frames', args.segmentFrames, 1);
  args.concurrency = intOf('--concurrency', args.concurrency, 1);
  const seconds = Number(args.maxSeconds);
  if (!Number.isFinite(seconds) || seconds <= 0) throw new UsageError('--max-seconds must be a positive number');
  args.maxSeconds = seconds;
  if (args.renderId !== undefined && !/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(args.renderId)) throw new UsageError('--render-id may only contain letters, digits, ".", "_" and "-"');
  return args;
}

/** Draft/final naming rules. Refusals map to exit 3; nothing is ever renamed silently. */
export function checkNaming({out, draft, gateReport}) {
  const hasDraftMarker = path.basename(out).includes('.draft.');
  if (draft && !hasDraftMarker) return {ok: false, reason: '--draft requires ".draft." in the output file name'};
  if (!draft && hasDraftMarker) return {ok: false, reason: 'a ".draft." file name is only allowed together with --draft'};
  if (!draft && !gateReport) return {ok: false, reason: 'a final render requires --gate-report'};
  return {ok: true, reason: null};
}

// ---------------------------------------------------------------------------------------------
// input validation (mandatory: episode_schema.mjs decides)
// ---------------------------------------------------------------------------------------------

/** One line per validation error: `<path> [<rule>]: <message>` (the rule name is what the caller greps for). */
export const describeErrors = (errors, max = 5) => errors.slice(0, max).map(e => `${e.path}${e.rule ? ` [${e.rule}]` : ''}: ${e.message}`).join('; ');

/**
 * Validate episode + captions through ./episode_schema.mjs: validateEpisode(episode, captions, {publicDir})
 * -> {valid, errors:[{path, rule, message}], warnings, schemaSha256}. The module is required: when it cannot be
 * imported (or lacks validateEpisode / projectCaptions) the result is a refusal, never a lighter check.
 * `captions` in the result is projectCaptions(rawCaptions): the prop the engine gets (qc_layout.mjs does the same).
 * @returns {Promise<{ok: boolean, errors: object[], warnings?: object[], episode?: object, captions?: object, rawCaptions?: object}>}
 */
export async function validateInputs({episodePath, captionsPath, skillDir, composer}) {
  const errors = [];
  const load = async (file, label) => {
    try {
      const value = JSON.parse(await fs.readFile(file, 'utf8'));
      if (value === null || typeof value !== 'object') errors.push({path: label, rule: 'json-object', message: `${label} must contain a JSON object or array`});
      return value;
    } catch (error) {
      errors.push({path: label, rule: 'json-parse', message: `${label} unreadable: ${error.message}`});
      return undefined;
    }
  };
  const episode = await load(episodePath, 'episode');
  const rawCaptions = await load(captionsPath, 'captions');
  if (errors.length) return {ok: false, errors};

  const schemaFile = path.join(skillDir, 'scripts', 'episode_schema.mjs');
  let schema;
  try { schema = await import(pathToFileURL(schemaFile).href); } catch (error) {
    return {ok: false, errors: [{path: 'episode_schema.mjs', rule: 'schema-module', message: `cannot import ${schemaFile}: ${error.code ?? error.message}`}]};
  }
  if (typeof schema.validateEpisode !== 'function' || typeof schema.projectCaptions !== 'function') {
    return {ok: false, errors: [{path: 'episode_schema.mjs', rule: 'schema-module', message: `${schemaFile} must export validateEpisode and projectCaptions`}]};
  }
  const result = schema.validateEpisode(episode, rawCaptions, {publicDir: composer ? path.join(path.resolve(composer), 'public') : undefined});
  if (result.valid !== true) return {ok: false, errors: result.errors ?? [{path: 'episode', rule: 'validate', message: 'validateEpisode did not report valid: true'}]};
  return {ok: true, errors: [], warnings: result.warnings ?? [], episode, captions: schema.projectCaptions(rawCaptions), rawCaptions};
}

// ---------------------------------------------------------------------------------------------
// integrity (engine copy, Root registration, gates lock)
// ---------------------------------------------------------------------------------------------

/** Issues a DRAFT render tolerates (recorded as warnings): the engine, its entry and the lock are still being developed. */
export const DRAFT_TOLERATED = Object.freeze(['engine-drift', 'entry-drift', 'gates-lock', 'gates-lock-format', 'gates-lock-missing']);

/**
 * Integrity verdict for a render.
 *   final : requireLock, every issue refuses.
 *   draft : engine drift and every lock problem become warnings; anything else (entry-registration, entry-closure) refuses.
 * @returns {Promise<{refusals: object[], warnings: object[], lock: object}>}
 */
export async function integrityVerdict({composer, skillDir, draft, check = checkIntegrity}) {
  const result = await check({composerDir: composer, skillDir, requireLock: !draft});
  if (!draft) return {refusals: result.issues, warnings: result.warnings ?? [], lock: result.lock};
  const tolerated = i => DRAFT_TOLERATED.includes(i.id);
  return {
    refusals: result.issues.filter(i => !tolerated(i)),
    warnings: [...(result.warnings ?? []), ...result.issues.filter(tolerated)],
    lock: result.lock,
  };
}

const refuseOnIntegrity = verdict => {
  if (verdict.refusals.length) throw new RefusedError('integrity check failed: ' + verdict.refusals.map(i => `${i.id}: ${i.message}`).join('; '));
};

// ---------------------------------------------------------------------------------------------
// gate check
// ---------------------------------------------------------------------------------------------

const codePart = key => String(key ?? '').split('-')[0];

/**
 * Decide whether a final render is allowed for the current sources.
 * currentSources = {sourceHashes, mediaDigest, fontsDigest, bundleKey}.
 * The report must be finished/pass/complete v3 for YtNewsStyle01V4, its manifest (report.manifestPath)
 * must hash (canonical JSON) to report.manifestHash, and every source/media/fonts/bundle key of that
 * manifest must equal the current one, key by key.
 * @returns {Promise<{ok: boolean, reason: string|null, report?: object, manifest?: object, reportSha256?: string}>}
 */
export async function checkGate({reportPath, currentSources}) {
  const refuse = reason => ({ok: false, reason});
  if (!reportPath) return refuse('no gate report given');
  const reportFile = path.resolve(reportPath);
  let report;
  let reportSha256;
  try {
    reportSha256 = await sha256File(reportFile);
    report = JSON.parse(await fs.readFile(reportFile, 'utf8'));
  } catch (error) {
    return refuse(`gate report unreadable: ${error.code ?? error.message}`);
  }
  if (!report || typeof report !== 'object') return refuse('gate report is not a JSON object');
  if (report.version !== 3) return refuse(`gate report version is ${report.version}, expected 3`);
  if (report.status !== 'finished') return refuse(`gate report status is ${JSON.stringify(report.status)}, expected "finished"`);
  if (report.pass !== true) return refuse('gate report did not pass');
  if (report.complete !== true) return refuse('gate report is not complete');
  if (report.compositionId !== COMPOSITION_ID) return refuse(`gate report compositionId is ${JSON.stringify(report.compositionId)}`);
  if (typeof report.manifestHash !== 'string' || !report.manifestPath) return refuse('gate report has no manifestHash/manifestPath');

  let manifest;
  try {
    manifest = JSON.parse(await fs.readFile(path.resolve(path.dirname(reportFile), report.manifestPath), 'utf8'));
  } catch (error) {
    return refuse(`gate manifest unreadable: ${error.code ?? error.message}`);
  }
  if (hashManifest(manifest) !== report.manifestHash) return refuse('gate manifest hash does not match report.manifestHash');
  if (manifest.schema !== MANIFEST_SCHEMA) return refuse(`gate manifest schema is ${JSON.stringify(manifest.schema)}`);
  if (manifest.compositionId !== COMPOSITION_ID) return refuse(`gate manifest compositionId is ${JSON.stringify(manifest.compositionId)}`);
  if (report.runId !== undefined && manifest.runId !== report.runId) return refuse('gate report runId differs from its manifest');

  const pick = s => ({sourceHashes: s.sourceHashes, mediaDigest: s.mediaDigest, fontsDigest: s.fontsDigest});
  const mismatch = diffManifests(pick(manifest), pick(currentSources));
  if (mismatch) return refuse(`${mismatch} differs from the gated manifest`);
  if (!manifest.bundleKey || codePart(manifest.bundleKey) !== codePart(currentSources.bundleKey)) return refuse('bundleKey differs from the gated manifest');
  return {ok: true, reason: null, report, manifest, reportSha256};
}

// ---------------------------------------------------------------------------------------------
// segments
// ---------------------------------------------------------------------------------------------

/** Split [0, durationInFrames-1] into consecutive segments of at most segmentFrames frames. */
export function planSegments(durationInFrames, segmentFrames) {
  if (!Number.isInteger(durationInFrames) || durationInFrames < 1) throw new RangeError('durationInFrames must be a positive integer');
  if (!Number.isInteger(segmentFrames) || segmentFrames < 1) throw new RangeError('segmentFrames must be a positive integer');
  const segments = [];
  for (let from = 0, index = 0; from < durationInFrames; from += segmentFrames, index++) {
    segments.push({index, from, to: Math.min(durationInFrames, from + segmentFrames) - 1});
  }
  return segments;
}

const segmentName = index => `seg-${String(index).padStart(3, '0')}.mp4`;

export function newSegmentRecords(durationInFrames, segmentFrames) {
  return planSegments(durationInFrames, segmentFrames).map(s => ({
    ...s, file: segmentName(s.index), status: 'pending', frameCount: null, sha256: null, wallSeconds: null,
  }));
}

/**
 * Decide what the invocation does next.
 * budget = {elapsedSeconds, maxSeconds, renderedThisInvocation, safetyFactor?}.
 * A segment is only started when remaining time >= safetyFactor x the slowest finished segment, except
 * that every invocation may always start its first segment (otherwise a slow start could never progress).
 * @returns {{action: 'render', segment: object} | {action: 'concat'} | {action: 'incomplete', done: number, total: number, reason: string}}
 */
export function nextAction(renderManifest, budget) {
  const {segments} = renderManifest;
  const pending = segments.filter(s => s.status !== 'done');
  if (pending.length === 0) return {action: 'concat'};
  const done = segments.length - pending.length;
  const factor = budget.safetyFactor ?? DEFAULTS.renderSafetyFactor;
  const slowest = Math.max(0, ...segments.filter(s => s.status === 'done').map(s => Number(s.wallSeconds) || 0));
  const remaining = budget.maxSeconds - budget.elapsedSeconds;
  if (budget.renderedThisInvocation > 0) {
    if (remaining <= 0) return {action: 'incomplete', done, total: segments.length, reason: 'time budget used up'};
    if (remaining < factor * slowest) return {action: 'incomplete', done, total: segments.length, reason: `${remaining.toFixed(0)}s left < ${factor} x slowest segment (${slowest.toFixed(0)}s)`};
  }
  return {action: 'render', segment: pending[0]};
}

// ---------------------------------------------------------------------------------------------
// ffmpeg / ffprobe
// ---------------------------------------------------------------------------------------------

async function ffprobeJson(args, file, timeout = 600_000) {
  const {stdout} = await execFileP('ffprobe', ['-v', 'error', ...args, '-of', 'json', file], {timeout, maxBuffer: 16 * 1024 * 1024});
  return JSON.parse(stdout);
}

/**
 * Check a video file with ffprobe -count_frames.
 * expected = {frames, fps ('25/1'), width, height, pixelFormat, audioStreams}; only given keys are checked.
 * @returns {Promise<{ok: boolean, problems: string[], measured: object}>}
 */
export async function verifyOutput(file, expected) {
  const problems = [];
  let video;
  let audio;
  try {
    video = (await ffprobeJson(['-count_frames', '-select_streams', 'v:0', '-show_entries', 'stream=nb_read_frames,r_frame_rate,width,height,pix_fmt,codec_name'], file)).streams?.[0];
    audio = (await ffprobeJson(['-select_streams', 'a', '-show_entries', 'stream=index'], file)).streams ?? [];
  } catch (error) {
    return {ok: false, problems: [`ffprobe failed: ${error.message.split('\n')[0]}`], measured: {}};
  }
  if (!video) return {ok: false, problems: ['no video stream'], measured: {}};
  const measured = {
    frames: Number(video.nb_read_frames), fps: video.r_frame_rate, width: video.width, height: video.height,
    pixelFormat: video.pix_fmt, codec: video.codec_name, audioStreams: audio.length,
  };
  for (const key of ['frames', 'fps', 'width', 'height', 'pixelFormat', 'audioStreams']) {
    if (expected[key] !== undefined && measured[key] !== expected[key]) problems.push(`${key}: expected ${expected[key]}, got ${measured[key]}`);
  }
  if (expected.codec !== undefined && measured.codec !== expected.codec) problems.push(`codec: expected ${expected.codec}, got ${measured.codec}`);
  return {ok: problems.length === 0, problems, measured};
}

/**
 * Join segment files without re-encoding: ffmpeg concat demuxer, -c copy, +faststart.
 * Writes outFile (use a temp name and rename after verification). Throws when ffmpeg fails.
 */
export async function concatSegments({segmentFiles, outFile, listFile, ffmpeg = 'ffmpeg'}) {
  if (!segmentFiles.length) throw new Error('no segments to concatenate');
  const quote = p => `'${path.resolve(p).replaceAll("'", "'\\''")}'`;
  await fs.writeFile(listFile, segmentFiles.map(f => `file ${quote(f)}`).join('\n') + '\n');
  await fs.rm(outFile, {force: true});
  await execFileP(ffmpeg, ['-nostdin', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', listFile, '-c', 'copy', '-movflags', '+faststart', '-f', 'mp4', outFile], {timeout: 600_000, maxBuffer: 16 * 1024 * 1024});
}

// ---------------------------------------------------------------------------------------------
// receipt
// ---------------------------------------------------------------------------------------------

/**
 * Assemble the receipt. Gate fields are null for a draft. `mediaDigest` / `fontsDigest` are the hex
 * digests (the method is in mediaDigestMethod).
 */
export function buildReceipt({renderManifest, renderDir, outputPath, outputSha256, outputBytes, frameCount, sources, gate, tools, finishedAt, relativeTo}) {
  const {sourceHashes, mediaDigest, fontsDigest} = sources;
  const invocations = renderManifest.invocations;
  const draft = renderManifest.draft;
  const receipt = {
    schema: RECEIPT_SCHEMA, schemaVersion: 1, compositionId: COMPOSITION_ID,
    renderId: renderManifest.renderId, draft,
    outputPath, outputFileName: path.basename(outputPath), outputSha256, outputBytes,
    frameCount, durationInFrames: renderManifest.durationInFrames, fps: FPS, width: WIDTH, height: HEIGHT,
    codec: ENCODER.codec, pixelFormat: ENCODER.pixelFormat, hasAudio: false,
    episodeJsonSha256: sourceHashes['episode.json'], captionsJsonSha256: sourceHashes['captions.json'],
    engineSha256: sourceHashes['src/YtNewsStyle01V4.tsx'], engineReferenceSha256: sourceHashes['assets/YtNewsStyle01V4.reference.tsx'],
    entrySha256: sourceHashes[ENTRY_REL], entryReferenceSha256: sourceHashes['assets/ytNewsStyle01V4.entry.reference.tsx'],
    entryClosure: Object.fromEntries(Object.entries(sourceHashes).filter(([key]) => key.startsWith('src/'))),
    fontsDigest: fontsDigest.digest, mediaDigest: mediaDigest.digest, mediaDigestMethod: mediaDigest.method,
    gatesLockSha256: sourceHashes['scripts/gates.lock.json'] ?? null,
    gateReportPath: draft ? null : gate.reportPath, gateReportSha256: draft ? null : gate.reportSha256,
    gateRunId: draft ? null : gate.runId, gateManifestHash: draft ? null : gate.manifestHash,
    gateCheckedAtStart: draft ? null : gate.checkedAtStart, gateCheckedAtConcat: draft ? null : gate.checkedAtConcat,
    segments: renderManifest.segments.map(s => ({
      index: s.index, fromFrame: s.from, toFrame: s.to, file: path.relative(relativeTo, path.join(renderDir, s.file)),
      sha256: s.sha256, frameCount: s.frameCount, wallSeconds: s.wallSeconds,
    })),
    tools, startedAt: invocations[0]?.startedAt ?? finishedAt, finishedAt,
    wallSecondsTotal: Math.round(invocations.reduce((sum, inv) => sum + (Number(inv.wallSeconds) || 0), 0) * 1000) / 1000,
    invocations: invocations.map(i => ({startedAt: i.startedAt, endedAt: i.endedAt, wallSeconds: i.wallSeconds, segmentsRendered: i.segmentsRendered})),
  };
  return receipt;
}

/** Write `<out>.receipt.json` atomically; the key set must be exactly RECEIPT_FIELDS. */
export async function writeReceipt(receiptPath, receipt) {
  const keys = Object.keys(receipt);
  const missing = RECEIPT_FIELDS.filter(k => !keys.includes(k));
  const extra = keys.filter(k => !RECEIPT_FIELDS.includes(k));
  if (missing.length || extra.length) throw new Error(`receipt fields mismatch (missing: ${missing.join(',') || '-'}; extra: ${extra.join(',') || '-'})`);
  const ordered = Object.fromEntries(RECEIPT_FIELDS.map(k => [k, receipt[k]]));
  await writeJsonAtomic(receiptPath, ordered);
}

async function firstLineOf(cmd, args) {
  try {
    const {stdout} = await execFileP(cmd, args, {timeout: 10_000});
    return stdout.split('\n')[0].trim() || null;
  } catch { return null; }
}

async function collectTools(composer) {
  return {
    node: process.version,
    remotion: await readRemotionVersion(composer),
    ffmpeg: await firstLineOf('ffmpeg', ['-version']),
    chrome: await firstLineOf(CHROME_PATH, ['--version']),
  };
}

// ---------------------------------------------------------------------------------------------
// Remotion adapter (the only code that loads @remotion/*)
// ---------------------------------------------------------------------------------------------

function loadRemotion(composer, name) {
  return createRequire(path.join(composer, 'package.json'))(name);
}

const browserExecutable = () => CHROME_PATH;

/** Build (or reuse) the bundle inside the render directory. `key` identifies code + media + fonts. */
export async function ensureBundle({composer, renderDir, publicDir, key}) {
  const outDir = path.join(renderDir, 'bundle');
  const metaFile = path.join(renderDir, 'bundle.meta.json');
  const wanted = canonicalJSON(key);
  const existing = await fs.readFile(metaFile, 'utf8').catch(() => null);
  if (existing === wanted && await fs.access(outDir).then(() => true, () => false)) return {serveUrl: outDir, reused: true};
  const {bundle} = loadRemotion(composer, '@remotion/bundler');
  const tmpDir = path.join(renderDir, 'bundle.tmp');
  await fs.rm(tmpDir, {recursive: true, force: true});
  await fs.rm(outDir, {recursive: true, force: true});
  await fs.rm(metaFile, {force: true});
  await bundle({entryPoint: entryPointOf(composer), publicDir, outDir: tmpDir});
  await fs.rename(tmpDir, outDir);
  await fs.writeFile(metaFile, wanted);
  return {serveUrl: outDir, reused: false};
}

/** Ask the composition for its metadata (duration comes from calculateMetadata reading the episode). */
export async function selectDuration({composer, serveUrl, inputProps}) {
  const {selectComposition} = loadRemotion(composer, '@remotion/renderer');
  const c = await selectComposition({serveUrl, id: COMPOSITION_ID, inputProps, browserExecutable: browserExecutable()});
  return {durationInFrames: c.durationInFrames, fps: c.fps, width: c.width, height: c.height};
}

/** Render frames [segment.from, segment.to] to outputLocation (one self-contained h264 encode, no audio). */
export async function renderSegment({composer, serveUrl, inputProps, segment, outputLocation, concurrency, encoder = ENCODER, onProgress}) {
  const {selectComposition, renderMedia} = loadRemotion(composer, '@remotion/renderer');
  const composition = await selectComposition({serveUrl, id: COMPOSITION_ID, inputProps, browserExecutable: browserExecutable()});
  await renderMedia({
    composition, serveUrl, inputProps, browserExecutable: browserExecutable(),
    codec: encoder.codec, crf: encoder.crf, pixelFormat: encoder.pixelFormat, x264Preset: encoder.x264Preset, colorSpace: encoder.colorSpace, muted: encoder.muted,
    concurrency, frameRange: [segment.from, segment.to], outputLocation, overwrite: true, onProgress,
  });
}

const defaultDeps = {renderSegment, selectDuration, ensureBundle, checkIntegrity, now: () => Date.now(), log: line => console.log(line)};

// ---------------------------------------------------------------------------------------------
// orchestration
// ---------------------------------------------------------------------------------------------

async function readThresholds(skillDir) {
  try { return JSON.parse(await fs.readFile(path.join(skillDir, 'scripts', 'qc_thresholds.json'), 'utf8')); } catch { return {}; }
}

const isoAt = ms => new Date(ms).toISOString();
const round3 = n => Math.round(n * 1000) / 1000;

/**
 * Whole command. `deps` replaces the Remotion adapter and clock in tests:
 *   {renderSegment, selectDuration, ensureBundle, checkIntegrity, now, log, skillDir}
 * @returns {Promise<number>} the exit code
 */
export async function run(argv, deps = {}) {
  const d = {...defaultDeps, ...deps};
  const log = d.log;
  const skillDir = path.resolve(d.skillDir ?? path.join(path.dirname(fileURLToPath(import.meta.url)), '..'));
  const startedMs = d.now();
  const thresholds = await readThresholds(skillDir);

  let args;
  try {
    args = parseArgs(argv, {
      maxSeconds: thresholds.maxSecondsDefault ?? DEFAULTS.maxSeconds,
      concurrency: thresholds.workersDefault ?? DEFAULTS.concurrency,
      renderSafetyFactor: thresholds.renderSafetyFactor ?? DEFAULTS.renderSafetyFactor,
    });
  } catch (error) {
    if (!(error instanceof UsageError)) throw error;
    log(`RENDER USAGE_ERROR ${error.message}`);
    log(USAGE);
    return EXIT.CRASH;
  }
  const safetyFactor = thresholds.renderSafetyFactor ?? DEFAULTS.renderSafetyFactor;

  try {
    const naming = checkNaming(args);
    if (!naming.ok) throw new RefusedError(naming.reason);

    const composer = path.resolve(args.composer);
    const out = path.resolve(args.out);
    const outDir = path.dirname(out);
    const episodePath = path.resolve(args.episode);
    const captionsPath = path.resolve(args.captions);
    const renderId = args.renderId ?? randomUUID();
    const renderDir = path.join(outDir, `${path.basename(out, path.extname(out))}.render`, renderId);
    const receiptPath = `${out}.receipt.json`;
    const manifestFile = path.join(renderDir, 'render-manifest.json');

    // 1. inputs and integrity (a draft skips the gate and tolerates engine drift / lock problems, not the input validation)
    const validation = await validateInputs({episodePath, captionsPath, skillDir, composer});
    if (!validation.ok) throw new RefusedError('episode/captions invalid: ' + describeErrors(validation.errors));
    const integrityAtStart = await integrityVerdict({composer, skillDir, draft: args.draft, check: d.checkIntegrity});
    refuseOnIntegrity(integrityAtStart);
    for (const w of integrityAtStart.warnings) log(`RENDER WARNING ${w.id}: ${w.message}`);
    const integrityRecord = verdict => ({draft: args.draft, lock: verdict.lock, warnings: verdict.warnings});
    const {episode, captions} = validation;     // captions = projectCaptions(...), the engine's prop
    const inputProps = {episode, captions};

    // 2. sources, media digest and the staging public directory
    await fs.mkdir(renderDir, {recursive: true});
    const cacheFile = path.join(outDir, 'cache', 'media-hash.json');
    const staged = await stagePublicDir({composerPublic: path.join(composer, 'public'), assetDir: episode.assetDir, stageDir: path.join(renderDir, 'public-stage'), cacheFile});
    const gatherSources = async () => ({
      sourceHashes: await computeSourceHashes({composerDir: composer, skillDir, episodePath, captionsPath}),
      mediaDigest: {...(await digestDir(path.join(composer, 'public', episode.assetDir), {cacheFile})), assetDir: episode.assetDir},
      fontsDigest: {...(await digestDir(path.join(composer, 'public', 'fonts'), {cacheFile})), assetDir: 'fonts'},
      bundleKey: await computeBundleCodeKey({composerDir: composer}),
    });
    const sources = await gatherSources();
    if (sources.mediaDigest.digest !== staged.mediaDigest.digest) throw new RefusedError('media changed while staging');

    // 3. gate at start
    let gate = null;
    if (!args.draft) {
      const check = await checkGate({reportPath: args.gateReport, currentSources: sources});
      if (!check.ok) throw new RefusedError('gate: ' + check.reason);
      gate = {reportPath: path.resolve(args.gateReport), runId: check.report.runId ?? check.manifest.runId, manifestHash: check.report.manifestHash, reportSha256: check.reportSha256, checkedAtStart: isoAt(d.now())};
    }

    // 4. open (resume) or create the render manifest
    const encoder = {...ENCODER};
    const identity = m => ({draft: m.draft, compositionId: m.compositionId, sources: m.sources, encoder: m.encoder, gateManifestHash: m.gate ? m.gate.manifestHash : null});
    let manifest;
    const stored = await readJson(manifestFile).catch(() => null);
    let bundle;
    const getBundle = async () => {
      bundle ??= await d.ensureBundle({composer, renderDir, publicDir: staged.dir, key: {codeKey: codePart(sources.bundleKey), media: sources.mediaDigest.digest, fonts: sources.fontsDigest.digest}});
      return bundle;
    };
    if (stored) {
      const wantIdentity = identity({draft: args.draft, compositionId: COMPOSITION_ID, sources, encoder, gate});
      const mismatch = diffManifests(identity(stored), wantIdentity);
      if (mismatch) throw new ResumeRefusedError(mismatch);
      if (stored.segmentFrames !== args.segmentFrames) throw new ResumeRefusedError('segmentFrames');
      manifest = stored;
      manifest.integrity = integrityRecord(integrityAtStart);
      if (gate) manifest.gate = {...gate, checkedAtStart: stored.gate?.checkedAtStart ?? gate.checkedAtStart};
    } else {
      const meta = await d.selectDuration({composer, serveUrl: (await getBundle()).serveUrl, inputProps});
      if (meta.fps !== FPS || meta.width !== WIDTH || meta.height !== HEIGHT) throw new RefusedError(`composition is ${meta.width}x${meta.height}@${meta.fps}, expected ${WIDTH}x${HEIGHT}@${FPS}`);
      manifest = {
        schema: RENDER_MANIFEST_SCHEMA, version: 1, renderId, draft: args.draft, compositionId: COMPOSITION_ID, sources, gate,
        durationInFrames: meta.durationInFrames, fps: FPS, width: WIDTH, height: HEIGHT, segmentFrames: args.segmentFrames, encoder,
        integrity: integrityRecord(integrityAtStart),
        createdAt: isoAt(startedMs), segments: newSegmentRecords(meta.durationInFrames, args.segmentFrames), invocations: [],
      };
    }
    const invocation = {startedAt: isoAt(startedMs), endedAt: isoAt(startedMs), wallSeconds: 0, segmentsRendered: 0};
    manifest.invocations.push(invocation);
    const save = async () => {
      invocation.endedAt = isoAt(d.now());
      invocation.wallSeconds = round3((d.now() - startedMs) / 1000);
      await writeJsonAtomic(manifestFile, manifest);
    };
    await save();

    // Segments marked done must still be on disk and unchanged.
    for (const s of manifest.segments.filter(x => x.status === 'done')) {
      const actual = await sha256File(path.join(renderDir, s.file)).catch(() => null);
      if (actual !== s.sha256) { Object.assign(s, {status: 'pending', frameCount: null, sha256: null, wallSeconds: null}); log(`RENDER segment ${s.index} missing or changed, will re-render`); }
    }

    // 5. render segments inside the time budget
    for (;;) {
      const action = nextAction(manifest, {elapsedSeconds: (d.now() - startedMs) / 1000, maxSeconds: args.maxSeconds, renderedThisInvocation: invocation.segmentsRendered, safetyFactor});
      if (action.action === 'incomplete') {
        await save();
        log(`RENDER INCOMPLETE ${action.done}/${action.total} render=${renderId}`);
        return EXIT.INCOMPLETE;
      }
      if (action.action === 'concat') break;

      const seg = action.segment;
      const tmp = path.join(renderDir, `seg-${String(seg.index).padStart(3, '0')}.tmp.mp4`);
      const final = path.join(renderDir, seg.file);
      const t0 = d.now();
      await fs.rm(tmp, {force: true});
      await d.renderSegment({composer, serveUrl: (await getBundle()).serveUrl, inputProps, segment: seg, outputLocation: tmp, concurrency: args.concurrency, encoder});
      const frames = seg.to - seg.from + 1;
      const verdict = await verifyOutput(tmp, {frames, fps: `${FPS}/1`, width: WIDTH, height: HEIGHT, pixelFormat: ENCODER.pixelFormat, audioStreams: 0});
      if (!verdict.ok) {
        await fs.rm(tmp, {force: true});
        throw new Error(`segment ${seg.index} failed verification: ${verdict.problems.join('; ')}`);
      }
      await fs.rename(tmp, final);
      Object.assign(seg, {status: 'done', frameCount: verdict.measured.frames, sha256: await sha256File(final), wallSeconds: round3((d.now() - t0) / 1000)});
      invocation.segmentsRendered++;
      await save();
      log(`RENDER SEGMENT ${seg.index + 1}/${manifest.segments.length} frames ${seg.from}-${seg.to} ${seg.wallSeconds}s`);
    }

    // 6. concat -> verify -> second gate check -> publish
    const stillCurrent = async () => {
      const fresh = await gatherSources();
      const mismatch = diffManifests(manifest.sources, fresh);
      if (mismatch) throw new RefusedError(`sources changed during the render: ${mismatch}`);
      const verdict = await integrityVerdict({composer, skillDir, draft: args.draft, check: d.checkIntegrity});
      refuseOnIntegrity(verdict);
      manifest.integrity = integrityRecord(verdict);
      if (gate) {
        const check = await checkGate({reportPath: args.gateReport, currentSources: fresh});
        if (!check.ok) throw new RefusedError('gate: ' + check.reason);
        gate.reportSha256 = check.reportSha256;
        gate.checkedAtConcat = isoAt(d.now());
        manifest.gate = {...manifest.gate, ...gate};
      }
    };
    await stillCurrent();
    const sum = manifest.segments.reduce((n, s) => n + s.frameCount, 0);
    if (sum !== manifest.durationInFrames) throw new Error(`segment frame counts sum to ${sum}, expected ${manifest.durationInFrames}`);
    const part = `${out}.part`;
    await concatSegments({segmentFiles: manifest.segments.map(s => path.join(renderDir, s.file)), outFile: part, listFile: path.join(renderDir, 'concat-list.txt')});
    const verdict = await verifyOutput(part, {frames: manifest.durationInFrames, fps: `${FPS}/1`, width: WIDTH, height: HEIGHT, pixelFormat: ENCODER.pixelFormat, audioStreams: 0});
    if (!verdict.ok) {
      await fs.rm(part, {force: true});
      throw new Error('concatenated video failed verification: ' + verdict.problems.join('; '));
    }
    await stillCurrent();
    await fs.rm(receiptPath, {force: true});
    await fs.rename(part, out);
    const outputSha256 = await sha256File(out);
    const outputBytes = (await fs.stat(out)).size;
    await save();
    const receipt = buildReceipt({
      renderManifest: manifest, renderDir, outputPath: out, outputSha256, outputBytes, frameCount: verdict.measured.frames,
      sources: manifest.sources, gate, tools: await collectTools(composer), finishedAt: isoAt(d.now()), relativeTo: outDir,
    });
    await writeReceipt(receiptPath, receipt);
    log(`RENDER COMPLETE ${out} sha256=${outputSha256}`);
    return EXIT.COMPLETE;
  } catch (error) {
    if (error instanceof RefusedError) { log(`RENDER REFUSED ${error.message}`); return EXIT.REFUSED; }
    if (error instanceof ResumeRefusedError) { log(`RENDER RESUME_REFUSED ${error.field}`); return EXIT.RESUME_REFUSED; }
    log(`RENDER CRASH ${error.stack ?? error}`);
    return EXIT.CRASH;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  run(process.argv.slice(2)).then(code => { process.exitCode = code; });
}
