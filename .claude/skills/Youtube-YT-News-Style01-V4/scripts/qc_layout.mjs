#!/usr/bin/env node
// Layout gate for one YtNewsStyle01V4 episode: time-budgeted, resumable, parallel.
//
// Why it looks like this:
//   - every command of the automated pipeline is killed after ~10 minutes, and a full frame plan
//     (~2,800 frames) needs far longer. One invocation therefore stops starting new frames when its
//     budget (--max-seconds, default qc_thresholds.json maxSecondsDefault = 420) is nearly used,
//     persists everything and exits 75; the caller re-invokes with the same --run-id until COMPLETE;
//   - a frame measurement is only trusted when its JSON carries the manifestHash of the run it is read
//     back into (sources, media, fonts, thresholds, renderer all hashed), so a resume can never mix
//     measurements of two different worlds (a changed input makes the resume refuse, exit 4);
//   - frames are measured by N workers, each with its own Chrome (a crash kills one worker, not all).
//
// Usage:
//   node qc_layout.mjs --episode <episode.json> --captions <captions.json> --out <qc/layout dir>
//        --composer <remotion-composer dir> [--run-id <id>] [--max-seconds 420] [--workers 4]
//        [--frames a,b,c]
//
// Last stdout line (exactly one status line):
//   QC_LAYOUT COMPLETE pass=<true|false> run=<id>      exit 0 pass | 1 issues
//   QC_LAYOUT INCOMPLETE <done>/<total> run=<id>       exit 75, call again with --run-id <id>
//   QC_LAYOUT REFUSED <reason>                         exit 3 (validation / integrity / bad flag combination)
//   QC_LAYOUT RESUME_REFUSED <field>                   exit 4 (something changed since the run started)
//   QC_LAYOUT CRASH <message> | USAGE_ERROR <message>  exit 2
//
// Only the default Remotion adapters (ensureBundle, capturePlan, prepareMeasure, openWorker,
// captureFrame) load Remotion, lazily, from the composer's node_modules; everything else is plain Node
// and is unit-tested with injected fakes (see tests/qc_layout_run.test.mjs).
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {randomUUID} from 'node:crypto';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {
  COMPOSITION_ID, buildManifest, canonicalJSON, computeBundleCodeKey, computeSourceHashes, appendInvocation,
  readInvocations, readJson, readRemotionVersion, sha256File, sha256Hex, writeJsonAtomic,
} from './qc_manifest.mjs';
import {
  ResumeRefusedError, RUN_MANIFEST_FILE, beginReport, createRunDirectory, makeReport, openRunForResume,
  writeReport, writeRunManifest,
} from './qc_report.mjs';
import {STAGE_MARKER, digestDir, stagePublicDir} from './media_digest.mjs';
import {checkIntegrity} from './gate_integrity.mjs';
import {
  buildFramePlan, evaluateAvatarBackingSweep, evaluateLayout, evaluatePlanRules, loadFieldRules, loadThresholds,
  validateSamples,
} from './qc_layout_eval.mjs';

const execFileP = promisify(execFile);

export const EXIT = {PASS: 0, ISSUES: 1, CRASH: 2, REFUSED: 3, RESUME_REFUSED: 4, INCOMPLETE: 75};
export const DEFAULTS = Object.freeze({maxSeconds: 420, workers: 4, resumeSafetyFactor: 2, reserveSeconds: 20, initialFrameSeconds: 3});
const CHROME_PATH = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PLAN_FILE = 'plan.json';
const QUIET = {logLevel: 'error'};

// Remotion's default log handler prints every browser console line (our 20-50 KB probe payloads) with
// console.log whatever --logLevel says, because it filters by the message's own level. Over a whole plan
// that is >100 MB of stdout, so while a Remotion call runs console.log drops lines carrying a probe payload
// (they are still delivered to onBrowserLog). Refcounted: several workers call it at the same time.
let probeFilterUsers = 0;
let originalConsoleLog = null;
export async function withProbeLogsSilenced(fn) {
  if (probeFilterUsers++ === 0) {
    originalConsoleLog = console.log;
    console.log = (...args) => {
      if (args.some(a => typeof a === 'string' && a.includes('__QC'))) return;   // the payload is not always the first argument
      originalConsoleLog.apply(console, args);
    };
  }
  try {
    return await fn();
  } finally {
    if (--probeFilterUsers === 0) { console.log = originalConsoleLog; originalConsoleLog = null; }
  }
}

export const USAGE = `usage: qc_layout.mjs --episode <episode.json> --captions <captions.json> --out <qc/layout dir> --composer <remotion-composer dir>
         [--run-id <id>] [--max-seconds ${DEFAULTS.maxSeconds}] [--workers ${DEFAULTS.workers}] [--frames a,b,c]
  --run-id    continue that run (it is created with this id when it does not exist yet)
  --frames    diagnostic run of exactly these frames: new run only, never a pass
  exit codes  0 complete+pass | 1 complete with issues | 75 incomplete (call again with --run-id) | 3 refused | 4 resume refused | 2 crash/usage`;

export class UsageError extends Error {}
export class RefusedError extends Error {}

// ---------------------------------------------------------------------------------------------
// arguments
// ---------------------------------------------------------------------------------------------

const VALUE_FLAGS = {
  '--episode': 'episode', '--captions': 'captions', '--out': 'out', '--composer': 'composer',
  '--run-id': 'runId', '--max-seconds': 'maxSeconds', '--workers': 'workers', '--frames': 'frames',
};

/** Parse the command line. `defaults` (from qc_thresholds.json) overrides the built-ins. Throws UsageError. */
export function parseArgs(argv, defaults = {}) {
  const base = {...DEFAULTS, ...defaults};
  const args = {maxSeconds: base.maxSeconds, workers: base.workers};
  for (let i = 0; i < argv.length; i++) {
    const key = VALUE_FLAGS[argv[i]];
    if (!key) throw new UsageError(`unknown argument: ${argv[i]}`);
    const value = argv[++i];
    if (value === undefined || value.startsWith('--')) throw new UsageError(`${argv[i - 1]} needs a value`);
    args[key] = value;
  }
  for (const required of ['episode', 'captions', 'out', 'composer']) {
    if (!args[required]) throw new UsageError(`--${required} is required`);
  }
  const seconds = Number(args.maxSeconds);
  if (!Number.isFinite(seconds) || seconds <= 0) throw new UsageError('--max-seconds must be a positive number');
  args.maxSeconds = seconds;
  const workers = Number(args.workers);
  if (!Number.isInteger(workers) || workers < 1) throw new UsageError('--workers must be an integer >= 1');
  args.workers = workers;
  if (args.runId !== undefined && !/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(args.runId)) {
    throw new UsageError('--run-id may only contain letters, digits, ".", "_" and "-"');
  }
  if (args.frames !== undefined) {
    const list = args.frames.split(',').map(s => s.trim());
    const frames = list.map(Number);
    if (!list.length || frames.some((f, i) => list[i] === '' || !Number.isInteger(f) || f < 0)) {
      throw new UsageError('--frames must be a comma separated list of non-negative integers');
    }
    if (new Set(frames).size !== frames.length) throw new UsageError('--frames must not repeat a frame');
    args.frames = frames.sort((a, b) => a - b);
  }
  return args;
}

// ---------------------------------------------------------------------------------------------
// input validation
// ---------------------------------------------------------------------------------------------

/**
 * Validate episode + captions. Uses ./episode_schema.mjs (validateEpisode(episode, captions, {publicDir}))
 * when that file exists; otherwise it only checks that both files are JSON objects and that
 * episode.assetDir is a plain directory name. When the schema module exports projectCaptions, `captions`
 * in the result is the projection (what the engine gets as a prop); `rawCaptions` is what was on disk.
 * @returns {Promise<{ok: boolean, errors: object[], episode?: object, captions?: object, rawCaptions?: object}>}
 */
export async function validateInputs({episodePath, captionsPath, skillDir, composer}) {
  const errors = [];
  const load = async (file, label) => {
    try {
      const value = JSON.parse(await fs.readFile(file, 'utf8'));
      if (value === null || typeof value !== 'object' || Array.isArray(value)) errors.push({path: label, rule: 'json-object', message: `${label} must contain a JSON object`});
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
  const hasSchema = await fs.access(schemaFile).then(() => true, () => false);
  if (hasSchema) {
    const schema = await import(pathToFileURL(schemaFile).href);
    const result = schema.validateEpisode(episode, rawCaptions, {publicDir: path.join(composer, 'public')});
    const valid = result.valid ?? result.ok;          // validateEpisode reports `valid`; older stubs reported `ok`
    if (!valid) return {ok: false, errors: result.errors ?? []};
    const captions = typeof schema.projectCaptions === 'function' ? schema.projectCaptions(rawCaptions) : rawCaptions;
    return {ok: true, errors: [], episode, captions, rawCaptions};
  }
  if (typeof episode.assetDir !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(episode.assetDir)) {
    return {ok: false, errors: [{path: 'episode.assetDir', rule: 'asset-dir', message: 'episode.assetDir must be a plain directory name'}]};
  }
  return {ok: true, errors: [], episode, captions: rawCaptions, rawCaptions};
}

// ---------------------------------------------------------------------------------------------
// plan
// ---------------------------------------------------------------------------------------------

/**
 * Turn the engine's __QC_PLAN__ into the frame list of the run.
 *   planVersion >= 2  -> buildFramePlan(plan, thresholds)   (any problem throws: fail closed)
 *   older plan        -> the engine's own `frames` list, validated against the composition duration,
 *                        plus the warning "plan-v1-fallback" (the grid / beat windows are missing)
 * `composition` is {durationInFrames, fps} from selectComposition.
 * @returns {{frames: number[], warnings: string[]}}
 */
export function resolvePlan(enginePlan, composition, thresholds) {
  if (!enginePlan || typeof enginePlan !== 'object') throw new Error('missing QC plan');
  if (!Array.isArray(enginePlan.frames) || !enginePlan.frames.length) throw new Error('missing QC plan: frames');
  if (enginePlan.planVersion >= 2) return {frames: buildFramePlan(enginePlan, thresholds), warnings: warningsOfPlan(enginePlan)};

  const duration = enginePlan.durationInFrames ?? composition?.durationInFrames;
  const frames = [...enginePlan.frames].sort((a, b) => a - b);
  if (!Number.isInteger(duration) || frames.some(f => !Number.isInteger(f) || f < 0 || f >= duration) || new Set(frames).size !== frames.length) {
    throw new Error('invalid sample plan');
  }
  return {frames, warnings: ['plan-v1-fallback', ...warningsOfPlan(enginePlan)]};
}

function warningsOfPlan(plan) {
  return plan.avatarFaceBoxSource === 'default' ? ['face-box-default'] : [];
}

/**
 * Which planned frames are measured for the current manifest? A frame is done only when <frame>.json
 * parses, carries the current manifestHash and the right `frame`, and <frame>.png exists (non-empty).
 * Everything else (missing, torn, foreign manifest, missing PNG) is pending and will be measured again.
 * @returns {Promise<{done: {frame: number, manifestHash: string, invocationId: string}[], pending: number[]}>}
 */
export async function pendingFrames(runDir, frames, manifestHash) {
  const done = [];
  const pending = [];
  for (const frame of frames) {
    const entry = await readFrameResult(runDir, frame);
    const png = await fs.stat(path.join(runDir, `${frame}.png`)).catch(() => null);
    if (entry && entry.manifestHash === manifestHash && entry.sample?.frame === frame && png?.isFile() && png.size > 0) {
      done.push({frame, manifestHash: entry.manifestHash, invocationId: entry.invocationId});
    } else {
      pending.push(frame);
    }
  }
  return {done, pending};
}

async function readFrameResult(runDir, frame) {
  try {
    const entry = JSON.parse(await fs.readFile(path.join(runDir, `${frame}.json`), 'utf8'));
    return entry && typeof entry === 'object' ? entry : null;
  } catch {
    return null;                                   // missing or torn file
  }
}

// ---------------------------------------------------------------------------------------------
// time budget
// ---------------------------------------------------------------------------------------------

/** Nearest-rank 95th percentile of a list of seconds (NaN for an empty list). */
export function p95(values) {
  if (!values.length) return NaN;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.ceil(0.95 * sorted.length) - 1)];
}

/**
 * May another frame be started?
 *   - the first frame of an invocation always may (otherwise a slow start could never make progress);
 *   - otherwise  remaining >= safetyFactor x p95(frame seconds so far), where
 *     remaining = maxSeconds - elapsed - reserve (the reserve is kept for evaluation + report writing)
 *     and p95 is replaced by initialFrameSeconds until a first frame has finished.
 */
export function shouldStartFrame({elapsedSeconds, maxSeconds, durations, startedThisInvocation, safetyFactor = DEFAULTS.resumeSafetyFactor, reserveSeconds = DEFAULTS.reserveSeconds, initialFrameSeconds = DEFAULTS.initialFrameSeconds}) {
  if (startedThisInvocation === 0) return true;
  const typical = durations.length ? p95(durations) : initialFrameSeconds;
  const remaining = maxSeconds - elapsedSeconds - reserveSeconds;
  return remaining >= safetyFactor * typical;
}

// ---------------------------------------------------------------------------------------------
// worker pool
// ---------------------------------------------------------------------------------------------

/**
 * Measure `pending` frames with up to `workers` concurrent workers.
 *   openWorker(index)                                  -> {close()}   one per worker (its own browser)
 *   captureFrame({worker, frame, outputPng})           -> sample      writes the PNG, returns the probe payload
 *   mayStart({startedCount, durations})                -> boolean     the time budget (see shouldStartFrame)
 * For each frame: PNG goes to <frame>.part.png and is renamed, then <frame>.json is written atomically
 * ({manifestHash, invocationId, measuredAt, sample}) - the JSON is written last, so it never points at a
 * missing PNG. The first failure stops every worker from taking new frames; frames already written stay valid.
 * @returns {Promise<{measured: number[], durations: number[], budgetStopped: boolean, error: Error|null}>}
 */
export async function measureFrames({pending, workers, runDir, manifestHash, invocationId, openWorker, captureFrame, mayStart, now = Date.now, onFrame}) {
  const measured = [];
  const durations = [];
  let cursor = 0;
  let started = 0;
  let budgetStopped = false;
  let error = null;

  const loop = async index => {
    let worker;
    try {
      worker = await openWorker(index);
      while (!error && cursor < pending.length) {
        if (!mayStart({startedCount: started, durations})) { budgetStopped = true; break; }
        const frame = pending[cursor++];
        started++;
        const t0 = now();
        const part = path.join(runDir, `${frame}.part.png`);
        const sample = await captureFrame({worker, frame, outputPng: part});
        if (sample?.frame !== frame) throw new Error(`frame ${frame}: probe reported frame ${sample?.frame}`);
        await fs.rename(part, path.join(runDir, `${frame}.png`));
        await writeJsonAtomic(path.join(runDir, `${frame}.json`), {manifestHash, invocationId, measuredAt: new Date(now()).toISOString(), sample});
        durations.push((now() - t0) / 1000);
        measured.push(frame);
        onFrame?.(frame, measured.length);
      }
    } catch (failure) {
      error ??= failure;
    } finally {
      // Close even after a failure; a close error must not hide the real one.
      try { await worker?.close?.(); } catch (closeError) { error ??= closeError; }
    }
  };

  await Promise.all(Array.from({length: Math.min(workers, pending.length)}, (_, i) => loop(i)));
  return {measured: measured.sort((a, b) => a - b), durations, budgetStopped, error};
}

// ---------------------------------------------------------------------------------------------
// evaluation + report
// ---------------------------------------------------------------------------------------------

/**
 * All frames are measured: evaluate every sample and build the final report.
 * Samples are read back from <frame>.json and must carry the run's manifestHash (guaranteed by
 * pendingFrames, but a mismatch here would still make makeReport refuse to pass).
 * @returns {Promise<object>} the report (status "finished")
 */
export async function finalize({runDir, manifest, manifestHash, manifestPath, plan, thresholds, fieldRules, frameMeta, invocations, warnings, meta}) {
  const frames = manifest.frames;
  const diagnostic = manifest.diagnostic === true;
  const samples = [];
  for (const frame of frames) {
    const entry = await readFrameResult(runDir, frame);
    samples.push(entry?.sample);
  }

  const issues = validateSamples(frames, samples);
  const ctx = {plan, fieldRules};
  for (const s of samples) {
    if (s) for (const i of evaluateLayout(s, thresholds, ctx).issues) issues.push({frame: s.frame, ...i});
  }
  if (plan?.lanes) issues.push(...evaluatePlanRules(plan, thresholds));

  const sweepWindows = plan?.sweepWindows;
  const sweepFrames = new Set((sweepWindows ?? []).flatMap(w => Array.from({length: w.endFrame - w.startFrame + 1}, (_, i) => w.startFrame + i)));
  const temporalSweep = evaluateAvatarBackingSweep(sweepWindows, samples.filter(s => s && sweepFrames.has(s.frame)), plan?.fps, thresholds, {requireComplete: !diagnostic});
  issues.push(...temporalSweep.issues);
  const sweepPlan = {version: plan?.sweepVersion, fps: plan?.fps, windows: sweepWindows};
  const sweepPlanSha256 = sha256Hex(JSON.stringify(sweepPlan));

  const report = makeReport({
    ...meta, status: 'finished',
    fullPlanFrames: diagnostic ? manifest.fullPlanFrames : frames, requestedFrames: frames,
    issues, manifestHash, manifestPath, planSha256: manifest.planSha256, frameMeta, invocations,
    warnings, temporalSweep, sweepPlan, sweepPlanSha256,
  });
  if (diagnostic) {
    // A diagnostic run measures a hand-picked subset: it can find problems but it can never certify.
    report.complete = false;
    report.pass = false;
  }
  return report;
}

// ---------------------------------------------------------------------------------------------
// Remotion adapters (the only code that loads @remotion/*)
// ---------------------------------------------------------------------------------------------

const loadRemotion = (composer, name) => createRequire(path.join(composer, 'package.json'))(name);

async function exists(file) {
  return fs.access(file).then(() => true, () => false);
}

/**
 * Build the bundle once per run into <runDir>/bundle (reused by every later invocation of the run).
 * The public directory comes from `makePublicDir()` (a staging dir with only fonts/ + <assetDir>/) and is
 * only created when a build is needed. The bundle is built into bundle.tmp and renamed, so a killed build
 * never leaves a half bundle that a resume would trust.
 * @returns {Promise<{serveUrl: string, reused: boolean}>}
 */
export async function ensureBundle({composer, runDir, makePublicDir, rebuild = false}) {
  const outDir = path.join(runDir, 'bundle');
  if (!rebuild && await exists(path.join(outDir, 'index.html'))) return {serveUrl: outDir, reused: true};
  const {bundle} = loadRemotion(composer, '@remotion/bundler');
  const tmpDir = path.join(runDir, 'bundle.tmp');
  await fs.rm(tmpDir, {recursive: true, force: true});
  await fs.rm(outDir, {recursive: true, force: true});
  const publicDir = await makePublicDir();
  try {
    await bundle({entryPoint: path.join(composer, 'src', 'index.tsx'), publicDir, outDir: tmpDir});
  } finally {
    // The bundle holds its own copy of public/; the staging dir (hardlinks, or copies across volumes) is no longer needed.
    if (await exists(path.join(publicDir, STAGE_MARKER))) await fs.rm(publicDir, {recursive: true, force: true});
  }
  await fs.rename(tmpDir, outDir);
  return {serveUrl: outDir, reused: false};
}

/**
 * New run only: render frame 0 once with qcPlan:true to get the engine's __QC_PLAN__ log.
 * @returns {Promise<{plan: object, composition: {durationInFrames: number, fps: number, width: number, height: number}}>}
 */
export async function capturePlan({composer, serveUrl, inputProps, runDir}) {
  const {selectComposition, renderStill, openBrowser} = loadRemotion(composer, '@remotion/renderer');
  const browser = await openBrowser('chrome', {browserExecutable: CHROME_PATH, logLevel: 'error'});
  const output = path.join(runDir, 'plan-probe.part.png');
  try {
    const common = {serveUrl, inputProps, browserExecutable: CHROME_PATH, puppeteerInstance: browser, timeoutInMilliseconds: 90000, ...QUIET};
    const composition = await withProbeLogsSilenced(() => selectComposition({...common, id: COMPOSITION_ID, onBrowserLog: () => {}}));
    let plan;
    await withProbeLogsSilenced(() => renderStill({
      ...common, composition, frame: 0, output, imageFormat: 'png',
      onBrowserLog: l => { if (l.text.startsWith('__QC_PLAN__')) plan = JSON.parse(l.text.slice('__QC_PLAN__'.length)); },
    }));
    if (!plan) throw new Error('the engine did not emit __QC_PLAN__');
    const {durationInFrames, fps, width, height} = composition;
    return {plan, composition: {durationInFrames, fps, width, height}};
  } finally {
    await fs.rm(output, {force: true});
    await browser.close({silent: true});
  }
}

/** Select the composition once with the measurement props; every worker shares the result. */
export async function prepareMeasure({composer, serveUrl, inputProps}) {
  const {selectComposition} = loadRemotion(composer, '@remotion/renderer');
  const composition = await withProbeLogsSilenced(() => selectComposition({serveUrl, id: COMPOSITION_ID, inputProps, browserExecutable: CHROME_PATH, timeoutInMilliseconds: 90000, onBrowserLog: () => {}, ...QUIET}));
  return {composer, serveUrl, inputProps, composition};
}

/** One worker = one Chrome of its own (a crash cannot take the other workers down). */
export async function openWorker(context) {
  const {openBrowser} = loadRemotion(context.composer, '@remotion/renderer');
  const browser = await openBrowser('chrome', {browserExecutable: CHROME_PATH, logLevel: 'error'});
  return {browser, close: () => browser.close({silent: true})};
}

/** Render one frame to outputPng and return its probe payload (exactly one __QC__ log for that frame). */
export async function captureFrame({context, worker, frame, outputPng}) {
  const {renderStill} = loadRemotion(context.composer, '@remotion/renderer');
  const logs = [];
  await withProbeLogsSilenced(() => renderStill({
    serveUrl: context.serveUrl, inputProps: context.inputProps, composition: context.composition, frame,
    output: outputPng, imageFormat: 'png', browserExecutable: CHROME_PATH, puppeteerInstance: worker.browser,
    timeoutInMilliseconds: 90000, ...QUIET,
    onBrowserLog: l => { if (l.text.startsWith('__QC__')) logs.push(JSON.parse(l.text.slice('__QC__'.length))); },
  }));
  // renderStill may mount at frame zero and then seek; only the requested frame counts.
  const matching = logs.filter(s => s.frame === frame);
  if (matching.length !== 1) throw new Error(`frame ${frame}: expected one probe log, got ${matching.length}`);
  return matching[0];
}

async function rendererInfo(composer) {
  let chrome = null;
  try {
    chrome = (await execFileP(CHROME_PATH, ['--version'], {timeout: 15_000})).stdout.trim() || null;
  } catch { /* unknown chrome: recorded as null */ }
  return {remotion: await readRemotionVersion(composer), node: process.version, chrome};
}

const defaultDeps = {
  validateInputs, checkIntegrity, ensureBundle, capturePlan, prepareMeasure, openWorker, captureFrame, rendererInfo,
  newId: () => randomUUID(), now: () => Date.now(), log: line => console.log(line),
};

// ---------------------------------------------------------------------------------------------
// orchestration
// ---------------------------------------------------------------------------------------------

const isoAt = ms => new Date(ms).toISOString();
const round3 = n => Math.round(n * 1000) / 1000;

/**
 * Whole command. `deps` replaces the Remotion adapters, validation, clock and logger in tests.
 * @returns {Promise<number>} the exit code
 */
export async function run(argv, deps = {}) {
  const d = {...defaultDeps, ...deps};
  const log = d.log;
  const skillDir = path.resolve(d.skillDir ?? path.join(path.dirname(fileURLToPath(import.meta.url)), '..'));
  const startedMs = d.now();
  const scriptsDir = path.join(skillDir, 'scripts');

  let thresholds;
  let fieldRules;
  try {
    thresholds = loadThresholds(pathToFileURL(path.join(scriptsDir, 'qc_thresholds.json')));
    fieldRules = loadFieldRules(pathToFileURL(path.join(scriptsDir, 'qc_field_rules.json')));
  } catch (error) {
    log(`QC_LAYOUT CRASH cannot load thresholds/field rules: ${error.message}`);
    return EXIT.CRASH;
  }

  let args;
  try {
    args = parseArgs(argv, {maxSeconds: thresholds.maxSecondsDefault, workers: thresholds.workersDefault});
  } catch (error) {
    if (!(error instanceof UsageError)) throw error;
    log(USAGE);
    log(`QC_LAYOUT USAGE_ERROR ${error.message}`);
    return EXIT.CRASH;
  }

  const composer = path.resolve(args.composer);
  const out = path.resolve(args.out);
  const state = {runId: args.runId};
  const invocationId = d.newId();

  try {
    // 1. inputs and integrity
    const validation = await d.validateInputs({episodePath: path.resolve(args.episode), captionsPath: path.resolve(args.captions), skillDir, composer});
    if (!validation.ok) throw new RefusedError('validation ' + validation.errors.slice(0, 5).map(e => `${e.path}: ${e.message}`).join('; '));
    const {episode, captions} = validation;
    const integrity = await d.checkIntegrity({composerDir: composer, skillDir});
    if (!integrity.ok) throw new RefusedError([...new Set(integrity.issues.map(i => i.id))].join(','));
    const warnings = (integrity.warnings ?? []).map(w => w.id);

    // 2. source hashes, media + fonts digests (hash cache lives next to the reports)
    await fs.mkdir(out, {recursive: true});
    const cacheFile = path.join(out, 'cache', 'media-hash.json');
    const sourceHashes = await computeSourceHashes({composerDir: composer, skillDir, episodePath: path.resolve(args.episode), captionsPath: path.resolve(args.captions)});
    const mediaDigest = {...(await digestDir(path.join(composer, 'public', episode.assetDir), {cacheFile})), assetDir: episode.assetDir};
    const fontsDigest = {...(await digestDir(path.join(composer, 'public', 'fonts'), {cacheFile})), assetDir: 'fonts'};
    // bundleKey = code part only (every file under src + lockfile + remotion version); the public part of
    // the bundle is covered by mediaDigest / fontsDigest, so a media change is reported under its own name.
    const bundleKey = await computeBundleCodeKey({composerDir: composer});
    const current = {
      sourceHashes, mediaDigest, fontsDigest, bundleKey,
      thresholdsSha256: await sha256File(path.join(scriptsDir, 'qc_thresholds.json')),
      renderer: await d.rendererInfo(composer),
    };

    // 3. run directory: new, resumed, or created with a caller-chosen id
    let runDir;
    let manifest = null;
    let manifestHash = null;
    let previousInvocations = [];
    state.runId = args.runId ?? d.newId();
    const wantedDir = path.join(out, 'runs', state.runId);
    const hasManifest = await exists(path.join(wantedDir, RUN_MANIFEST_FILE));
    if (args.runId && hasManifest) {
      if (args.frames) throw new RefusedError('--frames is only allowed for a new run');
      const opened = await openRunForResume(out, state.runId, current);
      ({dir: runDir, manifest, manifestHash} = opened);
      previousInvocations = opened.invocations;
    } else if (args.runId && await exists(wantedDir)) {
      runDir = wantedDir;                         // an earlier attempt died before it wrote its manifest: start over inside it
    } else {
      runDir = await createRunDirectory(out, state.runId);
    }
    const meta = {compositionId: COMPOSITION_ID, runId: state.runId, startedAt: manifest?.createdAt ?? isoAt(startedMs), artifactDirectory: runDir};
    await beginReport(out, meta);                 // from here on any earlier "pass" on disk is invalidated

    // 4. bundle once per run
    const bundleStarted = d.now();
    const bundle = await d.ensureBundle({
      composer, runDir, rebuild: manifest === null,
      makePublicDir: async () => {
        const staged = await stagePublicDir({composerPublic: path.join(composer, 'public'), assetDir: episode.assetDir, stageDir: path.join(runDir, 'public-stage'), cacheFile});
        if (staged.mediaDigest.digest !== mediaDigest.digest || staged.fontsDigest.digest !== fontsDigest.digest) throw new RefusedError('media changed while staging');
        // copied > 0 means --out and the composer are on different volumes: every file was copied instead of hardlinked.
        log(`QC_STAGE linked=${staged.linked} copied=${staged.copied}`);
        return staged.dir;
      },
    });
    const bundleSeconds = round3((d.now() - bundleStarted) / 1000);

    // 5. new run: get the plan and write the manifest; resume: read it back
    const planFile = path.join(runDir, PLAN_FILE);
    let plan;
    let inputProps = {episode, captions, qcPlan: false, qcMeasure: true};
    if (manifest === null) {
      const planned = await d.capturePlan({composer, serveUrl: bundle.serveUrl, inputProps: {episode, captions, qcPlan: true, qcMeasure: true}, runDir});
      plan = planned.plan;
      const resolved = resolvePlan(plan, planned.composition, thresholds);
      let frames = resolved.frames;
      const planWarnings = [...resolved.warnings];
      let extra = {};
      if (args.frames) {
        const outside = args.frames.filter(f => f >= planned.composition.durationInFrames);
        if (outside.length) throw new RefusedError(`--frames outside the composition (0..${planned.composition.durationInFrames - 1}): ${outside.join(',')}`);
        extra = {diagnostic: true, fullPlanFrames: frames};
        frames = args.frames;
        planWarnings.push('diagnostic-frames');
      }
      await writeJsonAtomic(planFile, plan);
      manifest = {
        ...buildManifest({runId: state.runId, ...current, planSha256: sha256Hex(canonicalJSON(frames)), frames}),
        enginePlanSha256: sha256Hex(canonicalJSON(plan)), planWarnings, createdAt: isoAt(startedMs), ...extra,
      };
      ({manifestHash} = await writeRunManifest(runDir, manifest));
      meta.startedAt = manifest.createdAt;
    } else {
      plan = await readJson(planFile).catch(() => null);
      if (!plan || sha256Hex(canonicalJSON(plan)) !== manifest.enginePlanSha256) throw new ResumeRefusedError(PLAN_FILE);
    }
    const manifestPath = path.join(runDir, RUN_MANIFEST_FILE);
    const allWarnings = [...new Set([...warnings, ...(manifest.planWarnings ?? [])])];

    // 6. what is already measured for this manifest?
    const before = await pendingFrames(runDir, manifest.frames, manifestHash);
    const invocation = {
      invocationId, startedAt: isoAt(startedMs), endedAt: isoAt(startedMs), wallSeconds: 0, measured: 0,
      reusedAtStart: before.done.length, workers: args.workers, framesPerSecond: null,
      bundleKey, bundleReused: bundle.reused, bundleSeconds,
    };
    let outcome = {measured: [], durations: [], budgetStopped: false, error: null};
    let measureSeconds = 0;

    // 7. measure inside the time budget
    if (before.pending.length) {
      const context = await d.prepareMeasure({composer, serveUrl: bundle.serveUrl, inputProps});
      const measureStarted = d.now();
      outcome = await measureFrames({
        pending: before.pending, workers: args.workers, runDir, manifestHash, invocationId, now: d.now,
        openWorker: () => d.openWorker(context),
        captureFrame: ({worker, frame, outputPng}) => d.captureFrame({context, worker, frame, outputPng}),
        mayStart: ({startedCount, durations}) => shouldStartFrame({
          elapsedSeconds: (d.now() - startedMs) / 1000, maxSeconds: args.maxSeconds, durations, startedThisInvocation: startedCount,
          safetyFactor: thresholds.resumeSafetyFactor ?? DEFAULTS.resumeSafetyFactor,
        }),
        onFrame: (frame, count) => { if (count % 25 === 0) log(`QC_PROGRESS ${before.done.length + count}/${manifest.frames.length}`); },
      });
      measureSeconds = (d.now() - measureStarted) / 1000;
    }

    // 8. invocation record (also when a worker crashed: the frames it wrote are valid and were measured now)
    invocation.measured = outcome.measured.length;
    invocation.framesPerSecond = outcome.measured.length && measureSeconds > 0 ? round3(outcome.measured.length / measureSeconds) : null;
    invocation.endedAt = isoAt(d.now());
    invocation.wallSeconds = round3((d.now() - startedMs) / 1000);
    if (outcome.error) invocation.crashed = String(outcome.error.message ?? outcome.error);
    await appendInvocation(runDir, invocation);
    if (outcome.error) throw outcome.error;
    const invocations = [...previousInvocations, invocation];

    // 9. reports: incomplete while frames remain, otherwise evaluate everything
    const after = await pendingFrames(runDir, manifest.frames, manifestHash);
    const total = manifest.frames.length;
    const writeBoth = async report => {
      await writeReport(out, {...report, manifestPath: path.relative(out, manifestPath)});
      await writeReport(runDir, {...report, manifestPath: RUN_MANIFEST_FILE});
    };
    const reportBase = {...meta, endedAt: isoAt(d.now())};
    if (after.pending.length) {
      const fullPlanFrames = manifest.diagnostic ? manifest.fullPlanFrames : manifest.frames;
      await writeBoth(makeReport({
        ...reportBase, status: 'incomplete', fullPlanFrames, requestedFrames: manifest.frames, issues: [],
        manifestHash, manifestPath, planSha256: manifest.planSha256, frameMeta: after.done, invocations, warnings: allWarnings,
      }));
      log(`QC_LAYOUT INCOMPLETE ${after.done.length}/${total} run=${state.runId}`);
      return EXIT.INCOMPLETE;
    }
    const report = await finalize({
      runDir, manifest, manifestHash, manifestPath, plan, thresholds, fieldRules,
      frameMeta: after.done, invocations, warnings: allWarnings, meta: reportBase,
    });
    await writeBoth(report);
    log(`QC_LAYOUT COMPLETE pass=${report.pass} run=${state.runId}${manifest.diagnostic ? ' diagnostic=true' : ''}`);
    // A diagnostic run can never pass; it still exits 0 when it found nothing, so scripts can tell "clean" from "issues".
    return report.pass || (manifest.diagnostic && report.diagnosticPass) ? EXIT.PASS : EXIT.ISSUES;
  } catch (error) {
    return failWith(error, {out, state, startedMs, log, now: d.now});
  }
}

/** Map an error to a status line, an exit code and (when possible) a non-passing report on disk. */
async function failWith(error, {out, state, startedMs, log, now}) {
  const refused = error instanceof RefusedError;
  const resumeRefused = error instanceof ResumeRefusedError;
  const status = refused ? 'refused' : resumeRefused ? 'refused' : 'failed';
  try {
    await fs.mkdir(out, {recursive: true});
    await writeReport(out, {
      schema: 'yt-news-layout-report', version: 3, compositionId: COMPOSITION_ID, runId: state.runId, startedAt: isoAt(startedMs), endedAt: isoAt(now()),
      status, complete: false, pass: false, diagnosticPass: false, issues: [], error: String(error.message ?? error),
    });
  } catch { /* cannot write the report (unwritable --out): the status line and exit code still say it */ }
  if (refused) { log(`QC_LAYOUT REFUSED ${error.message}`); return EXIT.REFUSED; }
  if (resumeRefused) { log(`QC_LAYOUT RESUME_REFUSED ${error.field}`); return EXIT.RESUME_REFUSED; }
  log(`QC_LAYOUT CRASH ${String(error.stack ?? error).split('\n').slice(0, 6).join(' | ')}`);
  return EXIT.CRASH;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  run(process.argv.slice(2)).then(code => { process.exitCode = code; });
}
