// Layout-gate runner tests. No Remotion: ensureBundle / capturePlan / prepareMeasure / openWorker / captureFrame
// are fakes injected through run(argv, deps); the clock is fake too, so budgets are deterministic.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {
  EXIT, UsageError, parseArgs, p95, shouldStartFrame, resolvePlan, pendingFrames, measureFrames, withProbeLogsSilenced, run,
} from '../qc_layout.mjs';
import {buildFramePlan} from '../qc_layout_eval.mjs';
import {stagePublicDir} from '../media_digest.mjs';
import {checkIntegrity as realCheckIntegrity} from '../gate_integrity.mjs';
import {sha256Hex} from '../qc_manifest.mjs';
import {projectCaptions} from '../episode_schema.mjs';
import {thresholds as T, PLAN, v3Field, v3Snap} from './fixtures/v3/builders.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const realScripts = path.resolve(here, '..');
const exists = f => fs.access(f).then(() => true, () => false);
const readJson = async f => JSON.parse(await fs.readFile(f, 'utf8'));
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64');

// An engine plan v2 for a 200-frame composition; frames/beats/windows are small so the frame list is short.
const ENGINE_PLAN_V2 = {...PLAN, durationInFrames: 200, voEndFrame: 180, frames: [0, 10, 50], beats: [], sweepWindows: [], sweepVersion: 'test-1'};
const PLAN_FRAMES = buildFramePlan(ENGINE_PLAN_V2, T);
const ENGINE_PLAN_V1 = {frames: [0, 5, 9], fps: 25, sweepWindows: [], sweepVersion: 'avatar-empty-backing-1'};

/** A snapshot with zero issues (schema 3), for `frame`. */
const cleanSnapshot = frame => v3Snap([
  v3Field('headline', {lane: 'split.headline', x: 128, y: 712, w: 800, h: 52}),
  v3Field('kicker', {tier: 'label', lane: 'header.kicker', x: 1546, y: 66, w: 258, h: 34}),
], {frame});
const schema2Snapshot = frame => ({...cleanSnapshot(frame), schemaVersion: 2});

const STUB_SCHEMA = `
  export function validateEpisode(e) {
    return typeof e.assetDir === 'string' && /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(e.assetDir)
      ? {valid: true, errors: [], warnings: []}
      : {valid: false, errors: [{path: 'episode.assetDir', rule: 'asset-dir', message: 'episode.assetDir must be a plain directory name'}], warnings: []};
  }
  export function projectCaptions(c) { return c; }
`;
const FIXTURES = path.join(here, 'fixtures/episodes');
const readFixture = rel => fs.readFile(path.join(FIXTURES, rel), 'utf8').then(JSON.parse);
const NO_LOCK = {status: 'missing', sha256: null, files: null, external: null};
const LOCKED_SOURCE = 'export const locked = 1;\n';
const lockOf = (files = {'scripts/locked_gate.mjs': sha256Hex(LOCKED_SOURCE)}) => ({schema: 'yt-news-v4-gates-lock', version: 1, skill: 'Youtube-YT-News-Style01-V4', files});
/** The real lock check on the world's skill dir, minus the engine/entry checks (the world's engine is a placeholder). */
const lockOnlyIntegrity = async options => {
  const r = await realCheckIntegrity(options);
  const issues = r.issues.filter(i => i.id.startsWith('gates-lock'));
  return {...r, issues, ok: issues.length === 0};
};

/**
 * A throw-away world: skill dir (real thresholds + field rules), composer dir, episode/captions files,
 * fake Remotion adapters and a fake clock. `opts` tunes the fakes; `world.deps` is what run() receives.
 */
async function makeWorld(opts = {}) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'qc-layout-run-'));
  const skillDir = path.join(root, 'skill');
  const composer = path.join(root, 'composer');
  await fs.mkdir(path.join(skillDir, 'scripts'), {recursive: true});
  await fs.mkdir(path.join(skillDir, 'assets'), {recursive: true});
  for (const name of ['qc_thresholds.json', 'qc_field_rules.json']) await fs.copyFile(path.join(realScripts, name), path.join(skillDir, 'scripts', name));
  await fs.writeFile(path.join(skillDir, 'assets', 'YtNewsStyle01V4.reference.tsx'), '// reference\n');
  await fs.writeFile(path.join(skillDir, 'assets', 'ytNewsStyle01V4.entry.reference.tsx'), '// entry reference\n');
  await fs.mkdir(path.join(composer, 'src'), {recursive: true});
  await fs.mkdir(path.join(composer, 'public', 'fonts'), {recursive: true});
  await fs.mkdir(path.join(composer, 'public', 'ep', 'broll'), {recursive: true});
  await fs.mkdir(path.join(composer, 'public', 'other-episode'), {recursive: true});
  for (const f of ['YtNewsStyle01V4.tsx', 'Root.tsx', 'index.tsx']) await fs.writeFile(path.join(composer, 'src', f), `// ${f}\n`);
  await fs.writeFile(path.join(composer, 'src', 'ytNewsStyle01V4.entry.tsx'), 'import "./YtNewsStyle01V4";\nimport "./ytNewsStyle01V4Sample.json";\n');
  await fs.writeFile(path.join(composer, 'src', 'ytNewsStyle01V4Sample.json'), '{}');
  await fs.writeFile(path.join(composer, 'package-lock.json'), '{}');
  await fs.writeFile(path.join(composer, 'public', 'fonts', 'kanit.ttf'), 'font');
  await fs.writeFile(path.join(composer, 'public', 'ep', 'broll', 'a.mp4'), 'video-a');
  await fs.writeFile(path.join(composer, 'public', 'other-episode', 'x.mp4'), 'must not be staged');
  const episodePath = path.join(root, 'episode.json');
  const captionsPath = path.join(root, 'captions.json');
  await fs.writeFile(episodePath, JSON.stringify({assetDir: 'ep', beats: []}));
  await fs.writeFile(captionsPath, JSON.stringify({pages: []}));
  const out = path.join(root, 'qc', 'layout');

  const clock = {t: 1_000_000};
  const log = {lines: [], plan: 0, bundleBuilds: 0, bundleReuses: 0, captures: [], open: 0, close: 0, inFlight: 0, maxInFlight: 0, stagedEntries: null, validate: 0};
  // opts.realSchema: a copy of the real validator + schema and the min-3-beat fixture (with its media files) instead of the permissive stub
  if (opts.realSchema) {
    await fs.copyFile(path.join(realScripts, 'episode_schema.mjs'), path.join(skillDir, 'scripts', 'episode_schema.mjs'));
    await fs.copyFile(path.join(realScripts, '..', 'assets', 'episode.schema.json'), path.join(skillDir, 'assets', 'episode.schema.json'));
    const episode = await readFixture('valid/min-3-beat.json');
    await fs.mkdir(path.join(composer, 'public', episode.assetDir, 'broll'), {recursive: true});
    await fs.writeFile(path.join(composer, 'public', episode.assetDir, episode.avatarFile), 'AVATAR');
    for (const src of Object.keys(episode.brollDur)) await fs.writeFile(path.join(composer, 'public', episode.assetDir, 'broll', `${src}.mp4`), 'B');
    await fs.writeFile(episodePath, JSON.stringify(episode));
    await fs.writeFile(captionsPath, JSON.stringify(await readFixture('captions/min-captions.json')));
  } else {
    await fs.writeFile(path.join(skillDir, 'scripts', 'episode_schema.mjs'), STUB_SCHEMA);
  }
  await fs.writeFile(path.join(skillDir, 'scripts', 'locked_gate.mjs'), LOCKED_SOURCE);
  const world = {
    root, skillDir, composer, episodePath, captionsPath, out, clock, log, opts,
    renderer: {remotion: '4.0.526', node: 'v22', chrome: 'Chrome 1'},
    argv: (...extra) => ['--episode', episodePath, '--captions', captionsPath, '--out', out, '--composer', composer, ...extra],
    status: () => log.lines.filter(l => l.startsWith('QC_LAYOUT')).at(-1),
    runDirOf: id => path.join(out, 'runs', id),
    async go(extra = [], depOverrides = {}) {
      log.lines.length = 0;
      const code = await run(world.argv(...extra), {...world.deps, ...depOverrides});
      return {code, status: world.status(), lines: [...log.lines]};
    },
    async cleanup() { await fs.rm(root, {recursive: true, force: true}); },
  };

  world.deps = {
    skillDir,
    now: () => clock.t,
    log: line => log.lines.push(line),
    newId: (() => { let n = 0; return () => `id-${++n}`; })(),
    checkIntegrity: opts.realLock ? lockOnlyIntegrity : async () => (opts.integrity ?? {ok: true, issues: [], warnings: [], lock: NO_LOCK}),
    rendererInfo: async () => ({...world.renderer}),
    async ensureBundle({runDir, rebuild, makePublicDir}) {
      const index = path.join(runDir, 'bundle', 'index.html');
      if (!rebuild && await exists(index)) { log.bundleReuses++; return {serveUrl: path.join(runDir, 'bundle'), reused: true}; }
      log.bundleBuilds++;
      const stage = await makePublicDir();
      log.stagedEntries = (await fs.readdir(stage)).filter(n => !n.startsWith('.')).sort();
      await fs.mkdir(path.join(runDir, 'bundle'), {recursive: true});
      await fs.writeFile(index, '<html></html>');
      return {serveUrl: path.join(runDir, 'bundle'), reused: false};
    },
    async capturePlan() {
      log.plan++;
      const plan = opts.plan ?? ENGINE_PLAN_V2;
      return {plan, composition: {durationInFrames: 200, fps: 25, width: 1920, height: 1080}};
    },
    async prepareMeasure() { return {composition: 'fake'}; },
    async openWorker() { log.open++; return {close: async () => { log.close++; }}; },
    async captureFrame({frame, outputPng}) {
      log.captures.push(frame);
      log.inFlight++;
      log.maxInFlight = Math.max(log.maxInFlight, log.inFlight);
      try {
        await new Promise(resolve => setImmediate(resolve));            // let the other workers start
        if (opts.failOnFrame === frame) throw new Error(`boom at ${frame}`);
        await fs.writeFile(outputPng, PNG);
        clock.t += (opts.frameSeconds ?? 1) * 1000;
        return (opts.snapshot ?? cleanSnapshot)(frame);
      } finally { log.inFlight--; }
    },
  };
  return world;
}

const withWorld = (opts, fn) => async () => {
  const w = await makeWorld(opts);
  try { await fn(w); } finally { await w.cleanup(); }
};
const runIdOf = status => /run=(\S+)/.exec(status)[1];

// ---- arguments, budget, plan ----------------------------------------------------------------------
const base = ['--episode', 'e.json', '--captions', 'c.json', '--out', 'o', '--composer', 'rc'];

test('parseArgs: defaults come from the thresholds, flags override, bad input is a UsageError', () => {
  const a = parseArgs(base);
  assert.deepEqual([a.maxSeconds, a.workers, a.runId, a.frames], [420, 4, undefined, undefined]);
  assert.equal(parseArgs(base, {maxSeconds: 300, workers: 6}).workers, 6);
  const b = parseArgs([...base, '--run-id', 'r.1', '--max-seconds', '45', '--workers', '2', '--frames', '9,3,5']);
  assert.deepEqual([b.runId, b.maxSeconds, b.workers, b.frames], ['r.1', 45, 2, [3, 5, 9]]);
  for (const bad of [['--nope'], base.slice(2), [...base, '--workers', '0'], [...base, '--max-seconds', '0'], [...base, '--run-id', '../x'],
    [...base, '--frames', '1,,2'], [...base, '--frames', '1,1'], [...base, '--frames', '-1'], [...base, '--out']]) {
    assert.throws(() => parseArgs(bad), UsageError, JSON.stringify(bad));
  }
});

test('p95 and shouldStartFrame: first frame always, then remaining >= factor x p95 with a 20 s reserve', () => {
  assert.equal(p95([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]), 10);
  assert.equal(p95([]), NaN);
  const ctx = {maxSeconds: 100, safetyFactor: 2, durations: [], startedThisInvocation: 0};
  assert.equal(shouldStartFrame({...ctx, elapsedSeconds: 500}), true, 'the first frame of an invocation is always allowed');
  // no sample yet: 3 s estimate -> need 6 s + 20 s reserve
  assert.equal(shouldStartFrame({...ctx, startedThisInvocation: 1, elapsedSeconds: 74}), true);
  assert.equal(shouldStartFrame({...ctx, startedThisInvocation: 1, elapsedSeconds: 74.5}), false);
  // measured p95 = 10 s -> need 20 s + 20 s reserve
  assert.equal(shouldStartFrame({...ctx, startedThisInvocation: 5, durations: [1, 1, 10], elapsedSeconds: 60}), true);
  assert.equal(shouldStartFrame({...ctx, startedThisInvocation: 5, durations: [1, 1, 10], elapsedSeconds: 60.1}), false);
});

test('resolvePlan: planVersion 2 uses buildFramePlan, the old plan falls back to its frames with a warning', () => {
  const v2 = resolvePlan(ENGINE_PLAN_V2, {durationInFrames: 200}, T);
  assert.deepEqual(v2.frames, PLAN_FRAMES);
  assert.deepEqual(v2.warnings, []);
  const v1 = resolvePlan(ENGINE_PLAN_V1, {durationInFrames: 200, fps: 25}, T);
  assert.deepEqual(v1.frames, [0, 5, 9]);
  assert.deepEqual(v1.warnings, ['plan-v1-fallback']);
  assert.throws(() => resolvePlan({...ENGINE_PLAN_V1, frames: [0, 200]}, {durationInFrames: 200}, T), /invalid sample plan/);
  assert.throws(() => resolvePlan({...ENGINE_PLAN_V1, frames: [0, 0]}, {durationInFrames: 200}, T), /invalid sample plan/);
  assert.throws(() => resolvePlan({...ENGINE_PLAN_V1, frames: []}, {durationInFrames: 200}, T), /missing QC plan/);
  // a v2 plan that is incomplete is an engine bug, not a reason to fall back
  assert.throws(() => resolvePlan({...ENGINE_PLAN_V2, voEndFrame: undefined}, {durationInFrames: 200}, T), /voEndFrame/);
  assert.deepEqual(resolvePlan({...ENGINE_PLAN_V2, avatarFaceBoxSource: 'default'}, {}, T).warnings, ['face-box-default']);
});

test('withProbeLogsSilenced drops probe payload lines from console.log only while active, refcounted, and restores it', async () => {
  const seen = [];
  const original = console.log;
  console.log = (...a) => seen.push(a.join(' '));
  try {
    const stub = console.log;
    await Promise.all([
      withProbeLogsSilenced(async () => { console.log('[Tab 0] __QC__{"frame":1}'); console.log('QC_PROGRESS 1/2'); console.log('\u001b[0m[Tab 0]\u001b[0m', '__QC__{"frame":2}'); await new Promise(r => setTimeout(r, 5)); }),
      withProbeLogsSilenced(async () => { await new Promise(r => setTimeout(r, 1)); console.log('__QC_PLAN__{}'); console.log('kept'); }),
    ]);
    assert.equal(console.log, stub, 'console.log is restored once the last user finishes');
    console.log('__QC__ outside is not filtered');
    assert.deepEqual(seen, ['QC_PROGRESS 1/2', 'kept', '__QC__ outside is not filtered']);
    await assert.rejects(withProbeLogsSilenced(async () => { throw new Error('x'); }), /x/);
    assert.equal(console.log, stub);
  } finally { console.log = original; }
});

// ---- the pool --------------------------------------------------------------------------------------
test('measureFrames: never more than `workers` captures at once, every worker closed, JSON written after the PNG', withWorld({}, async w => {
  const dir = path.join(w.root, 'pool');
  await fs.mkdir(dir);
  const frames = Array.from({length: 12}, (_, i) => i * 3);
  let running = 0;
  let peak = 0;
  let opened = 0;
  let closed = 0;
  const result = await measureFrames({
    pending: frames, workers: 3, runDir: dir, manifestHash: 'M', invocationId: 'I', now: () => w.clock.t,
    openWorker: async () => { opened++; return {close: async () => { closed++; }}; },
    captureFrame: async ({frame, outputPng}) => {
      running++; peak = Math.max(peak, running);
      await new Promise(r => setTimeout(r, 3));
      await fs.writeFile(outputPng, PNG);
      running--;
      return cleanSnapshot(frame);
    },
    mayStart: () => true,
  });
  assert.equal(peak, 3);
  assert.deepEqual([opened, closed], [3, 3]);
  assert.deepEqual(result.measured, frames);
  assert.equal(result.error, null);
  for (const f of frames) {
    const entry = await readJson(path.join(dir, `${f}.json`));
    assert.deepEqual([entry.manifestHash, entry.invocationId, entry.sample.frame], ['M', 'I', f]);
    assert.ok(await exists(path.join(dir, `${f}.png`)));
    assert.ok(!await exists(path.join(dir, `${f}.part.png`)));
  }
  // fewer frames than workers: only as many workers as frames
  opened = 0;
  await measureFrames({pending: [1], workers: 4, runDir: dir, manifestHash: 'M', invocationId: 'I2', openWorker: async () => { opened++; return {}; }, captureFrame: async ({frame, outputPng}) => { await fs.writeFile(outputPng, PNG); return cleanSnapshot(frame); }, mayStart: () => true});
  assert.equal(opened, 1);
}));

test('measureFrames: a probe that reports another frame fails the frame and leaves no JSON behind', withWorld({}, async w => {
  const dir = path.join(w.root, 'pool2');
  await fs.mkdir(dir);
  const result = await measureFrames({
    pending: [4], workers: 1, runDir: dir, manifestHash: 'M', invocationId: 'I',
    openWorker: async () => ({}), captureFrame: async ({outputPng}) => { await fs.writeFile(outputPng, PNG); return cleanSnapshot(5); }, mayStart: () => true,
  });
  assert.match(result.error.message, /probe reported frame 5/);
  assert.ok(!await exists(path.join(dir, '4.json')));
}));

test('pendingFrames: a frame is done only with the current manifestHash, the right frame number and a PNG', withWorld({}, async w => {
  const dir = path.join(w.root, 'pend');
  await fs.mkdir(dir);
  const write = async (frame, {hash = 'M', sampleFrame = frame, png = true, torn = false} = {}) => {
    await fs.writeFile(path.join(dir, `${frame}.json`), torn ? '{"manifestHash":' : JSON.stringify({manifestHash: hash, invocationId: 'i', sample: {frame: sampleFrame}}));
    if (png) await fs.writeFile(path.join(dir, `${frame}.png`), PNG);
  };
  await write(0);
  await write(1, {hash: 'other'});
  await write(2, {sampleFrame: 9});
  await write(3, {png: false});
  await write(4, {torn: true});
  const got = await pendingFrames(dir, [0, 1, 2, 3, 4, 5], 'M');
  assert.deepEqual(got.done.map(d => d.frame), [0]);
  assert.deepEqual(got.pending, [1, 2, 3, 4, 5]);
}));

// ---- run(): budget + resume --------------------------------------------------------------------------
test('a short budget gives INCOMPLETE (75); re-invoking with the run id continues, never re-measures a done frame, and ends COMPLETE pass', withWorld({frameSeconds: 2}, async w => {
  const total = PLAN_FRAMES.length;
  const first = await w.go(['--max-seconds', '30', '--workers', '1']);
  assert.equal(first.code, EXIT.INCOMPLETE);
  const id = runIdOf(first.status);
  const m1 = /INCOMPLETE (\d+)\/(\d+) run=/.exec(first.status);
  assert.equal(Number(m1[2]), total);
  const done1 = Number(m1[1]);
  assert.ok(done1 >= 1 && done1 < total, `partial progress, got ${done1}`);
  assert.equal(first.lines.at(-1), first.status, 'the status line is the last line');
  const afterFirst = await readJson(path.join(w.out, 'report.json'));
  assert.deepEqual([afterFirst.status, afterFirst.pass, afterFirst.complete], ['incomplete', false, false]);
  assert.equal(afterFirst.measuredCount, done1);

  let invocations = 1;
  let last = first;
  while (last.code === EXIT.INCOMPLETE) {
    last = await w.go(['--run-id', id, '--max-seconds', '30', '--workers', '1']);
    invocations++;
    assert.ok(invocations < 20, 'must converge');
  }
  assert.equal(last.code, EXIT.PASS);
  assert.equal(last.status, `QC_LAYOUT COMPLETE pass=true run=${id}`);
  assert.equal(w.log.plan, 1, 'the plan is rendered once, by the first invocation only');
  assert.equal(w.log.bundleBuilds, 1);
  assert.equal(w.log.bundleReuses, invocations - 1);
  assert.deepEqual([...w.log.captures].sort((a, b) => a - b), PLAN_FRAMES, 'every planned frame was captured exactly once');
  assert.equal(w.log.open, w.log.close);

  const report = await readJson(path.join(w.out, 'report.json'));
  assert.deepEqual([report.status, report.pass, report.complete, report.resumed, report.manifestConsistent], ['finished', true, true, true, true]);
  assert.equal(report.invocations.length, invocations);
  assert.equal(report.measuredCount, total);
  const lastRecord = report.invocations.at(-1);
  assert.equal(report.reusedFrames, total - lastRecord.measured, 'reusedFrames = frames measured by earlier invocations');
  assert.equal(report.invocations.reduce((n, i) => n + i.measured, 0), total);
  assert.deepEqual(report.invocations[0].reusedAtStart, 0);
  assert.equal(report.invocations[1].reusedAtStart, report.invocations[0].measured);
  assert.deepEqual(Object.keys(lastRecord).filter(k => !['crashed'].includes(k)).sort(),
    ['bundleKey', 'bundleReused', 'bundleSeconds', 'endedAt', 'framesPerSecond', 'invocationId', 'measured', 'reusedAtStart', 'startedAt', 'wallSeconds', 'workers'].sort());
  assert.equal(report.invocations[0].bundleReused, false);
  assert.equal(lastRecord.bundleReused, true);
  assert.equal(lastRecord.framesPerSecond, 0.5);
  const lines = (await fs.readFile(path.join(w.runDirOf(id), 'invocations.jsonl'), 'utf8')).trim().split('\n');
  assert.equal(lines.length, invocations);
  // the bundle was built from a staged public dir: fonts + the episode's assets only
  assert.deepEqual(w.log.stagedEntries, ['ep', 'fonts']);
}));

test('the first frame of an invocation is measured even when the budget is already spent', withWorld({frameSeconds: 1}, async w => {
  const r = await w.go(['--max-seconds', '1', '--workers', '1']);
  assert.equal(r.code, EXIT.INCOMPLETE);
  assert.equal(w.log.captures.length, 1);
  assert.match(r.status, new RegExp(`^QC_LAYOUT INCOMPLETE 1/${PLAN_FRAMES.length} run=`));
}));

test('a caller-chosen --run-id creates the run; INCOMPLETE then COMPLETE under that id', withWorld({}, async w => {
  const r = await w.go(['--run-id', 'my-run', '--max-seconds', '25', '--workers', '1']);
  assert.equal(r.code, EXIT.INCOMPLETE);
  assert.equal(runIdOf(r.status), 'my-run');
  assert.ok(await exists(path.join(w.runDirOf('my-run'), 'run-manifest.json')));
  const done = await w.go(['--run-id', 'my-run', '--workers', '4']);
  assert.equal(done.status, 'QC_LAYOUT COMPLETE pass=true run=my-run');
}));

test('a missing bundle directory on resume is rebuilt (bundleReused false)', withWorld({frameSeconds: 2}, async w => {
  const first = await w.go(['--run-id', 'b1', '--max-seconds', '30', '--workers', '1']);
  assert.equal(first.code, EXIT.INCOMPLETE);
  await fs.rm(path.join(w.runDirOf('b1'), 'bundle'), {recursive: true});
  const second = await w.go(['--run-id', 'b1', '--max-seconds', '30', '--workers', '1']);
  assert.equal(w.log.bundleBuilds, 2);
  const inv = (await fs.readFile(path.join(w.runDirOf('b1'), 'invocations.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse);
  assert.deepEqual(inv.map(i => i.bundleReused), [false, false]);
  assert.ok([EXIT.INCOMPLETE, EXIT.PASS].includes(second.code));
}));

test('the pool never runs more than --workers captures at once, and uses them all', withWorld({frameSeconds: 0.1}, async w => {
  const r = await w.go(['--workers', '3']);
  assert.equal(r.code, EXIT.PASS);
  assert.equal(w.log.maxInFlight, 3);
  assert.equal(w.log.open, 3);
  assert.equal(w.log.close, 3);
}));

// ---- resume refusal -----------------------------------------------------------------------------------
const firstInvocation = w => w.go(['--run-id', 'rr', '--max-seconds', '25', '--workers', '1']);
const refusedWith = async (w, field) => {
  const before = w.log.captures.length;
  const r = await w.go(['--run-id', 'rr', '--workers', '1']);
  assert.equal(r.code, EXIT.RESUME_REFUSED, r.status);
  assert.equal(r.status, `QC_LAYOUT RESUME_REFUSED ${field}`);
  assert.equal(w.log.captures.length, before, 'nothing is measured after a refused resume');
  const report = await readJson(path.join(w.out, 'report.json'));
  assert.deepEqual([report.status, report.pass], ['refused', false]);
};

test('resume refused (exit 4, field named) when the episode changed', withWorld({}, async w => {
  assert.equal((await firstInvocation(w)).code, EXIT.INCOMPLETE);
  await fs.writeFile(w.episodePath, JSON.stringify({assetDir: 'ep', beats: [], edited: true}));
  await refusedWith(w, 'sourceHashes.episode.json');
}));
test('resume refused when the captions changed', withWorld({}, async w => {
  await firstInvocation(w);
  await fs.writeFile(w.captionsPath, JSON.stringify({pages: [], edited: true}));
  await refusedWith(w, 'sourceHashes.captions.json');
}));
test('resume refused when the engine changed', withWorld({}, async w => {
  await firstInvocation(w);
  await fs.appendFile(path.join(w.composer, 'src', 'YtNewsStyle01V4.tsx'), '// edit\n');
  await refusedWith(w, 'bundleKey');   // bundleKey (hash of src/**) sorts before sourceHashes.*
}));
test('resume refused when the thresholds changed', withWorld({}, async w => {
  await firstInvocation(w);
  const file = path.join(w.skillDir, 'scripts', 'qc_thresholds.json');
  const t = await readJson(file);
  await fs.writeFile(file, JSON.stringify({...t, readFontPx: 30}, null, 2));
  await refusedWith(w, 'sourceHashes.scripts/qc_thresholds.json');
}));
test('resume refused when a media file changed (same size, different bytes)', withWorld({}, async w => {
  await firstInvocation(w);
  await fs.writeFile(path.join(w.composer, 'public', 'ep', 'broll', 'a.mp4'), 'video-B');
  await refusedWith(w, 'mediaDigest.digest');
}));
test('resume refused when a font changed', withWorld({}, async w => {
  await firstInvocation(w);
  await fs.writeFile(path.join(w.composer, 'public', 'fonts', 'kanit.ttf'), 'fonT');
  await refusedWith(w, 'fontsDigest.digest');
}));
test('resume refused when the renderer (Chrome) changed', withWorld({}, async w => {
  await firstInvocation(w);
  w.renderer.chrome = 'Chrome 2';
  await refusedWith(w, 'renderer.chrome');
}));
test('resume refused when the stored plan was altered', withWorld({}, async w => {
  await firstInvocation(w);
  await fs.writeFile(path.join(w.runDirOf('rr'), 'plan.json'), JSON.stringify({...ENGINE_PLAN_V2, fps: 30}));
  await refusedWith(w, 'plan.json');
}));
test('after a refused resume a fresh run (no --run-id) starts clean and re-measures everything', withWorld({}, async w => {
  await firstInvocation(w);
  await fs.writeFile(w.episodePath, JSON.stringify({assetDir: 'ep', beats: [], edited: true}));
  w.log.captures.length = 0;
  const r = await w.go(['--workers', '2']);
  assert.equal(r.code, EXIT.PASS);
  assert.deepEqual([...w.log.captures].sort((a, b) => a - b), PLAN_FRAMES);
}));

// ---- never trust what is on disk ------------------------------------------------------------------------
test('a frame JSON with a foreign manifestHash, a missing PNG or a torn file is measured again; the others are not', withWorld({frameSeconds: 2}, async w => {
  const first = await w.go(['--run-id', 't1', '--max-seconds', '30', '--workers', '1']);
  assert.equal(first.code, EXIT.INCOMPLETE);
  const dir = w.runDirOf('t1');
  const doneFrames = [...w.log.captures];
  assert.ok(doneFrames.length >= 3, 'need three measured frames for this test');
  const [foreign, nopng, torn, ...fine] = doneFrames;
  const fj = path.join(dir, `${foreign}.json`);
  await fs.writeFile(fj, JSON.stringify({...(await readJson(fj)), manifestHash: 'not-this-run'}));
  await fs.rm(path.join(dir, `${nopng}.png`));
  await fs.writeFile(path.join(dir, `${torn}.json`), '{"manifestHash":');
  w.log.captures.length = 0;
  const rest = await w.go(['--run-id', 't1', '--workers', '1']);
  assert.equal(rest.code, EXIT.PASS);
  for (const f of [foreign, nopng, torn]) assert.ok(w.log.captures.includes(f), `frame ${f} must be re-measured`);
  for (const f of fine) assert.ok(!w.log.captures.includes(f), `frame ${f} must be reused`);
  const report = await readJson(path.join(w.out, 'report.json'));
  assert.equal(report.manifestConsistent, true);
  assert.equal(report.reusedFrames, fine.length);
}));

// ---- verdicts ------------------------------------------------------------------------------------------
test('schema-3 snapshots with zero issues give exit 0 / pass:true; schema-2 snapshots give exit 1 / pass:false with schema issues', async () => {
  const ok = await makeWorld({});
  const bad = await makeWorld({snapshot: schema2Snapshot});
  try {
    const good = await ok.go(['--workers', '2']);
    assert.equal(good.code, EXIT.PASS);
    assert.match(good.status, /^QC_LAYOUT COMPLETE pass=true run=/);
    const goodReport = await readJson(path.join(ok.out, 'report.json'));
    assert.deepEqual([goodReport.pass, goodReport.complete, goodReport.status, goodReport.issues.length], [true, true, 'finished', 0]);
    assert.deepEqual(goodReport.fullPlanFrames, PLAN_FRAMES);
    assert.equal(goodReport.version, 3);

    const issues = await bad.go(['--workers', '2']);
    assert.equal(issues.code, EXIT.ISSUES);
    assert.match(issues.status, /^QC_LAYOUT COMPLETE pass=false run=/);
    const badReport = await readJson(path.join(bad.out, 'report.json'));
    assert.deepEqual([badReport.pass, badReport.complete, badReport.status], [false, true, 'finished']);
    assert.ok(badReport.issues.some(i => i.id === 'schema'));
    assert.equal(badReport.issues.filter(i => i.id === 'schema').length, PLAN_FRAMES.length);
  } finally { await ok.cleanup(); await bad.cleanup(); }
});

test('a plan-level defect (lane outside the safe area) fails the run even when every frame is clean', withWorld({plan: {...ENGINE_PLAN_V2, lanes: {...PLAN.lanes, stray: {x: 1900, y: 0, width: 300, height: 100}}}}, async w => {
  const r = await w.go(['--workers', '2']);
  assert.equal(r.code, EXIT.ISSUES);
  const report = await readJson(path.join(w.out, 'report.json'));
  assert.ok(report.issues.some(i => i.id === 'lane-table'));
}));

test('old plan shape: falls back to plan.frames and records the warning plan-v1-fallback; without lanes every frame fails closed (ctx-missing)', withWorld({plan: ENGINE_PLAN_V1}, async w => {
  const r = await w.go(['--workers', '2']);
  assert.equal(r.code, EXIT.ISSUES);
  assert.ok((await readJson(path.join(w.out, 'report.json'))).issues.every(i => i.id === 'ctx-missing' || i.code === 'ctx-missing'));
  assert.deepEqual([...w.log.captures].sort((a, b) => a - b), [0, 5, 9]);
  const report = await readJson(path.join(w.out, 'report.json'));
  assert.ok(report.warnings.includes('plan-v1-fallback'));
  assert.deepEqual(report.fullPlanFrames, [0, 5, 9]);
  const manifest = await readJson(path.join(w.out, report.manifestPath));
  assert.ok(manifest.planWarnings.includes('plan-v1-fallback'));
}));

test('--frames is a diagnostic run: only those frames, never pass, warning recorded, new run only', withWorld({}, async w => {
  const r = await w.go(['--frames', '50,0,10', '--workers', '2']);
  assert.equal(r.status.startsWith('QC_LAYOUT COMPLETE pass=false'), true, r.status);
  assert.match(r.status, /diagnostic=true$/);
  assert.equal(r.code, EXIT.PASS, 'a clean diagnostic exits 0 but is explicitly not a pass');
  assert.deepEqual([...w.log.captures].sort((a, b) => a - b), [0, 10, 50]);
  const report = await readJson(path.join(w.out, 'report.json'));
  assert.deepEqual([report.pass, report.complete, report.status, report.diagnosticPass], [false, false, 'finished', true]);
  assert.ok(report.warnings.includes('diagnostic-frames'));
  assert.deepEqual(report.requestedFrames, [0, 10, 50]);
  assert.deepEqual(report.fullPlanFrames, PLAN_FRAMES);
  // even a diagnostic that happens to list the whole plan cannot pass
  const whole = await w.go(['--frames', PLAN_FRAMES.join(','), '--workers', '2']);
  const wholeReport = await readJson(path.join(w.out, 'report.json'));
  assert.equal(wholeReport.pass, false);
  assert.match(whole.status, /pass=false/);
  // resuming with --frames is refused; frames outside the composition are refused
  const id = runIdOf(r.status);
  const again = await w.go(['--run-id', id, '--frames', '1,2']);
  assert.equal(again.code, EXIT.REFUSED);
  const outside = await w.go(['--frames', '5,200']);
  assert.equal(outside.code, EXIT.REFUSED);
  assert.match(outside.status, /outside the composition/);
}));

test('a diagnostic run with a schema-2 sample reports issues (exit 1) and still never passes', withWorld({snapshot: schema2Snapshot}, async w => {
  const r = await w.go(['--frames', '0,100']);
  assert.equal(r.code, EXIT.ISSUES);
  assert.match(r.status, /^QC_LAYOUT COMPLETE pass=false run=\S+ diagnostic=true$/);
}));

test('a report is never pass:true while status is not finished (incomplete, refused, failed)', async () => {
  const inc = await makeWorld({frameSeconds: 2});
  const ref = await makeWorld({integrity: {ok: false, issues: [{id: 'engine-drift', message: 'x'}], warnings: []}});
  const crash = await makeWorld({failOnFrame: 10});
  try {
    await inc.go(['--max-seconds', '25', '--workers', '1']);
    await ref.go();
    await crash.go(['--workers', '1']);
    for (const [w, status] of [[inc, 'incomplete'], [ref, 'refused'], [crash, 'failed']]) {
      const report = await readJson(path.join(w.out, 'report.json'));
      assert.equal(report.status, status);
      assert.equal(report.pass, false);
      assert.equal(report.complete, false);
    }
  } finally { await inc.cleanup(); await ref.cleanup(); await crash.cleanup(); }
});

// ---- refusals and crashes --------------------------------------------------------------------------------
test('validation failure: exit 3, REFUSED validation, nothing bundled or rendered', withWorld({}, async w => {
  await fs.writeFile(w.episodePath, JSON.stringify({assetDir: '../escape'}));
  const r = await w.go();
  assert.equal(r.code, EXIT.REFUSED);
  assert.match(r.status, /^QC_LAYOUT REFUSED validation /);
  assert.deepEqual([w.log.bundleBuilds, w.log.plan, w.log.captures.length, w.log.open], [0, 0, 0, 0]);
  assert.ok(!await exists(path.join(w.out, 'runs')));
  await fs.writeFile(w.captionsPath, 'not json');
  assert.equal((await w.go()).code, EXIT.REFUSED);
}));

test('episode_schema.mjs verdicts are honoured (`valid` only, the projected captions are the props, publicDir is <composer>/public)', withWorld({}, async w => {
  const schemaDir = path.join(w.skillDir, 'scripts');
  await fs.writeFile(path.join(schemaDir, 'episode_schema.mjs'), `
    export function validateEpisode(e, c, opts) { return opts.publicDir.endsWith('public') && e.assetDir === 'ep' ? {valid: true, errors: []} : {valid: false, errors: [{path: 'x', rule: 'R1', message: 'nope'}]}; }
    export function projectCaptions(c) { return {projected: true, pages: c.pages}; }
  `);
  const props = [];
  const r = await w.go(['--workers', '2'], {prepareMeasure: async ({inputProps}) => { props.push(inputProps); return {}; }});
  assert.equal(r.code, EXIT.PASS);
  assert.deepEqual(props[0].captions, {projected: true, pages: []});
  assert.deepEqual([props[0].qcPlan, props[0].qcMeasure], [false, true]);
  await fs.writeFile(w.episodePath, JSON.stringify({assetDir: 'other', beats: []}));
  const bad = await w.go();
  assert.equal(bad.code, EXIT.REFUSED);
  assert.match(bad.status, /validation x \[R1\]: nope/);
}));

test('a validator that reports only the old `ok` field is not valid', withWorld({}, async w => {
  await fs.writeFile(path.join(w.skillDir, 'scripts', 'episode_schema.mjs'), `
    export function validateEpisode() { return {ok: true, errors: []}; }
    export function projectCaptions(c) { return c; }
  `);
  const r = await w.go();
  assert.equal(r.code, EXIT.REFUSED);
  assert.match(r.status, /^QC_LAYOUT REFUSED validation /);
  assert.deepEqual([w.log.bundleBuilds, w.log.plan, w.log.captures.length], [0, 0, 0]);
}));

test('episode_schema.mjs missing (or without validateEpisode/projectCaptions): exit 3, no JSON-only fallback, nothing rendered', async () => {
  const gone = await makeWorld({});
  const partial = await makeWorld({});
  try {
    await fs.rm(path.join(gone.skillDir, 'scripts', 'episode_schema.mjs'));
    await fs.writeFile(path.join(partial.skillDir, 'scripts', 'episode_schema.mjs'), 'export function validateEpisode() { return {valid: true, errors: []}; }\n');
    for (const w of [gone, partial]) {
      const r = await w.go();
      assert.equal(r.code, EXIT.REFUSED);
      assert.match(r.status, /^QC_LAYOUT REFUSED validation .*\[schema-module\]/);
      assert.deepEqual([w.log.bundleBuilds, w.log.plan, w.log.captures.length, w.log.open], [0, 0, 0, 0]);
      assert.ok(!await exists(path.join(w.out, 'runs')));
    }
  } finally { await gone.cleanup(); await partial.cleanup(); }
});

test('real validator: min-3-beat passes (projected captions are the props); unknown-beat-key-captionLane is refused with its rule, nothing rendered', async () => {
  const w = await makeWorld({realSchema: true});
  try {
    const props = [];
    const ok = await w.go(['--workers', '2'], {prepareMeasure: async ({inputProps}) => { props.push(inputProps); return {}; }});
    assert.equal(ok.code, EXIT.PASS, ok.lines.join('\n'));
    assert.deepEqual(props[0].captions, projectCaptions(await readFixture('captions/min-captions.json')));
    const {_expect, ...invalid} = await readFixture('invalid/unknown-beat-key-captionLane.json');
    assert.ok(_expect);
    await fs.writeFile(w.episodePath, JSON.stringify(invalid));
    w.log.bundleBuilds = 0; w.log.plan = 0; w.log.captures.length = 0;
    const bad = await w.go();
    assert.equal(bad.code, EXIT.REFUSED);
    assert.match(bad.status, /^QC_LAYOUT REFUSED validation \/beats\/1\/captionLane \[additionalProperties\]/);
    assert.deepEqual([w.log.bundleBuilds, w.log.plan, w.log.captures.length], [0, 0, 0]);
  } finally { await w.cleanup(); }
});

test('integrity failure: exit 3 with the issue ids, nothing rendered', withWorld({integrity: {ok: false, issues: [{id: 'engine-drift', message: 'a'}, {id: 'gates-lock', message: 'b'}], warnings: [], lock: {status: 'mismatch', sha256: 'x', files: 1, external: 0}}}, async w => {
  const r = await w.go();
  assert.equal(r.code, EXIT.REFUSED);
  assert.equal(r.status, 'QC_LAYOUT REFUSED engine-drift,gates-lock');
  assert.deepEqual([w.log.bundleBuilds, w.log.plan, w.log.captures.length], [0, 0, 0]);
}));

test('integrity warnings are carried into the report warnings', withWorld({integrity: {ok: true, issues: [], warnings: [{id: 'gates-lock-missing', message: 'm'}], lock: NO_LOCK}}, async w => {
  await w.go(['--workers', '2']);
  assert.ok((await readJson(path.join(w.out, 'report.json'))).warnings.includes('gates-lock-missing'));
}));

// ---- gates lock ---------------------------------------------------------------------------------------
const lockPathOf = w => path.join(w.skillDir, 'scripts', 'gates.lock.json');

test('lock missing: warning gates-lock-missing, the run is usable, report.lock = {status: "missing", sha256: null, files: null, external: null}', withWorld({realLock: true}, async w => {
  const r = await w.go(['--workers', '2']);
  assert.equal(r.code, EXIT.PASS);
  const report = await readJson(path.join(w.out, 'report.json'));
  assert.ok(report.warnings.includes('gates-lock-missing'));
  assert.deepEqual(report.lock, NO_LOCK);
  assert.equal(report.pass, true);
}));

test('lock ok: report.lock carries status, the lock file sha256 and the file count (in both report copies); that hash is in the run manifest', withWorld({realLock: true}, async w => {
  const lock = JSON.stringify(lockOf());
  await fs.writeFile(lockPathOf(w), lock);
  const r = await w.go(['--run-id', 'lk', '--workers', '2']);
  assert.equal(r.code, EXIT.PASS, r.lines.join('\n'));
  const wanted = {status: 'ok', sha256: sha256Hex(lock), files: 1, external: 0};
  assert.deepEqual((await readJson(path.join(w.out, 'report.json'))).lock, wanted);
  assert.deepEqual((await readJson(path.join(w.runDirOf('lk'), 'report.json'))).lock, wanted);
  const manifest = await readJson(path.join(w.runDirOf('lk'), 'run-manifest.json'));
  assert.equal(manifest.sourceHashes['scripts/gates.lock.json'], sha256Hex(lock));
  assert.ok(!(await readJson(path.join(w.out, 'report.json'))).warnings.includes('gates-lock-missing'));
}));

test('an incomplete report carries lock too', withWorld({realLock: true, frameSeconds: 100}, async w => {
  await fs.writeFile(lockPathOf(w), JSON.stringify(lockOf()));
  const r = await w.go(['--max-seconds', '150', '--workers', '1']);
  assert.equal(r.code, EXIT.INCOMPLETE);
  assert.equal((await readJson(path.join(w.out, 'report.json'))).lock.status, 'ok');
}));

test('lock present but invalid or mismatching: REFUSED gates-lock..., exit 3, nothing rendered', async () => {
  const cases = {
    'gates-lock-format': w => fs.writeFile(lockPathOf(w), JSON.stringify({...lockOf(), version: 2})),
    'gates-lock-format (not json)': w => fs.writeFile(lockPathOf(w), 'nope'),
    'gates-lock': async w => { await fs.writeFile(lockPathOf(w), JSON.stringify(lockOf())); await fs.writeFile(path.join(w.skillDir, 'scripts', 'locked_gate.mjs'), 'export const locked = 2;\n'); },
    'gates-lock (file missing)': async w => { await fs.writeFile(lockPathOf(w), JSON.stringify(lockOf())); await fs.rm(path.join(w.skillDir, 'scripts', 'locked_gate.mjs')); },
  };
  for (const [name, setup] of Object.entries(cases)) {
    const w = await makeWorld({realLock: true});
    try {
      await setup(w);
      const r = await w.go();
      assert.equal(r.code, EXIT.REFUSED, name);
      assert.equal(r.status, `QC_LAYOUT REFUSED ${name.split(' ')[0]}`, name);
      assert.deepEqual([w.log.bundleBuilds, w.log.plan, w.log.captures.length], [0, 0, 0], name);
      const report = await readJson(path.join(w.out, 'report.json'));
      assert.deepEqual([report.status, report.pass], ['refused', false], name);
    } finally { await w.cleanup(); }
  }
});

test('the runner never asks for requireLock (a missing lock stays a warning for the layout gate)', withWorld({}, async w => {
  const seen = [];
  const r = await w.go(['--workers', '2'], {checkIntegrity: async options => { seen.push(options.requireLock); return {ok: true, issues: [], warnings: [], lock: NO_LOCK}; }});
  assert.equal(r.code, EXIT.PASS);
  assert.deepEqual(seen, [false]);
}));

test('resume under another lock state is refused (exit 4, sourceHashes.scripts/gates.lock.json)', withWorld({realLock: true, frameSeconds: 100}, async w => {
  const first = await w.go(['--run-id', 'lr', '--max-seconds', '150', '--workers', '1']);
  assert.equal(first.code, EXIT.INCOMPLETE);
  assert.equal(first.status.startsWith('QC_LAYOUT INCOMPLETE'), true);
  await fs.writeFile(lockPathOf(w), JSON.stringify(lockOf()));       // missing -> ok
  const second = await w.go(['--run-id', 'lr', '--max-seconds', '150', '--workers', '1']);
  assert.equal(second.code, EXIT.RESUME_REFUSED);
  assert.equal(second.status, 'QC_LAYOUT RESUME_REFUSED sourceHashes.scripts/gates.lock.json');
}));

test('usage errors: exit 2, USAGE_ERROR is the last line', withWorld({}, async w => {
  w.log.lines.length = 0;
  const code = await run(['--bogus'], w.deps);
  assert.equal(code, EXIT.CRASH);
  assert.match(w.log.lines.at(-1), /^QC_LAYOUT USAGE_ERROR unknown argument/);
}));

test('a worker crash: exit 2, the other workers are closed, frames already written stay valid and are reused on resume', withWorld({failOnFrame: 25}, async w => {
  const crashed = await w.go(['--run-id', 'cr', '--workers', '2']);
  assert.equal(crashed.code, EXIT.CRASH);
  assert.match(crashed.status, /^QC_LAYOUT CRASH .*boom at 25/);
  assert.equal(w.log.open, w.log.close, 'every browser is closed');
  const dir = w.runDirOf('cr');
  const written = (await fs.readdir(dir)).filter(n => /^\d+\.json$/.test(n)).map(n => Number(n.split('.')[0]));
  assert.ok(written.length >= 1 && !written.includes(25));
  const inv = (await fs.readFile(path.join(dir, 'invocations.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse);
  assert.equal(inv.length, 1);
  assert.match(inv[0].crashed, /boom at 25/);
  assert.equal(inv[0].measured, written.length);
  const report = await readJson(path.join(w.out, 'report.json'));
  assert.deepEqual([report.status, report.pass], ['failed', false]);

  // the engine is "fixed": resume reuses what was written and measures only the rest
  w.opts.failOnFrame = undefined;
  w.log.captures.length = 0;
  const resumed = await w.go(['--run-id', 'cr', '--workers', '2']);
  assert.equal(resumed.code, EXIT.PASS);
  for (const f of written) assert.ok(!w.log.captures.includes(f), `frame ${f} was already valid`);
  assert.equal(w.log.captures.length, PLAN_FRAMES.length - written.length);
}));

test('a crash while starting a worker closes the workers that did open', withWorld({}, async w => {
  let opened = 0;
  let closed = 0;
  const r = await w.go(['--workers', '3'], {
    openWorker: async () => {
      opened++;
      if (opened === 2) throw new Error('chrome did not start');
      return {close: async () => { closed++; }};
    },
  });
  assert.equal(r.code, EXIT.CRASH);
  assert.match(r.status, /chrome did not start/);
  assert.equal(closed, 2);
}));

test('staging really is hardlinked and holds only fonts/ and the episode asset dir', withWorld({}, async w => {
  const stageDir = path.join(w.root, 'stage');
  const staged = await stagePublicDir({composerPublic: path.join(w.composer, 'public'), assetDir: 'ep', stageDir});
  assert.deepEqual((await fs.readdir(staged.dir)).filter(n => !n.startsWith('.')).sort(), ['ep', 'fonts']);
  assert.equal(staged.copied, 0);
}));
