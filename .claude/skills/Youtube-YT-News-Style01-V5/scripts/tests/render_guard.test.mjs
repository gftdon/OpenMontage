// Render guard tests. No Remotion: the Remotion adapter is replaced by fakes that encode tiny ffmpeg clips.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {
  RECEIPT_FIELDS, EXIT, parseArgs, checkNaming, checkGate, planSegments, nextAction, newSegmentRecords,
  concatSegments, verifyOutput, buildReceipt, writeReceipt, validateInputs, integrityVerdict, run, UsageError, renderSegment, ensureBundle, ENCODER,
} from '../render_episode.mjs';
import {buildManifest, manifestHash, computeSourceHashes, computeBundleCodeKey, writeJsonAtomic, sha256File} from '../qc_manifest.mjs';
import {digestDir} from '../media_digest.mjs';
import {sha256Hex} from '../qc_manifest.mjs';
import {projectCaptions} from '../episode_schema.mjs';

const execFileP = promisify(execFile);
const here = path.dirname(fileURLToPath(import.meta.url));
const worktree = path.resolve(here, '../../../../..');
const realSkill = path.resolve(here, '../..');
const reference = await fs.readFile(path.join(realSkill, 'assets/YtNewsStyle01V4.reference.tsx'), 'utf8');
const entryReference = await fs.readFile(path.join(realSkill, 'assets/ytNewsStyle01V4.entry.reference.tsx'), 'utf8');
const realRoot = await fs.readFile(path.join(worktree, 'remotion-composer/src/Root.tsx'), 'utf8');

const tmpDir = prefix => fs.mkdtemp(path.join(os.tmpdir(), prefix));
const exists = f => fs.access(f).then(() => true, () => false);

async function makeClip(file, frames, {width = 320, height = 180} = {}) {
  await execFileP('ffmpeg', ['-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i', `testsrc=size=${width}x${height}:rate=25`, '-frames:v', String(frames), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-an', file]);
}

// ---- arguments and naming -------------------------------------------------------------------
const baseArgs = ['--episode', 'e.json', '--captions', 'c.json', '--composer', 'rc', '--out', 'o/v.mp4'];

test('parseArgs: defaults, overrides and usage errors', () => {
  const a = parseArgs(baseArgs);
  assert.deepEqual([a.maxSeconds, a.segmentFrames, a.concurrency, a.draft], [420, 750, 4, false]);
  const b = parseArgs([...baseArgs, '--max-seconds', '90', '--segment-frames', '100', '--concurrency', '2', '--render-id', 'r-1', '--gate-report', 'g.json', '--draft']);
  assert.deepEqual([b.maxSeconds, b.segmentFrames, b.concurrency, b.renderId, b.gateReport, b.draft], [90, 100, 2, 'r-1', 'g.json', true]);
  assert.equal(parseArgs(baseArgs, {maxSeconds: 300, concurrency: 6}).maxSeconds, 300);
  for (const bad of [['--bogus'], baseArgs.slice(2), [...baseArgs, '--segment-frames', '0'], [...baseArgs, '--max-seconds', 'x'], [...baseArgs, '--render-id', '../x'], [...baseArgs, '--gate-report'], baseArgs.map(x => (x === 'o/v.mp4' ? 'o/v.mov' : x))]) {
    assert.throws(() => parseArgs(bad), UsageError, JSON.stringify(bad));
  }
});

test('draft naming rules', () => {
  assert.equal(checkNaming({out: 'a/v.draft.mp4', draft: true}).ok, true);
  assert.equal(checkNaming({out: 'a/v.mp4', draft: true}).ok, false); // --draft without .draft.
  assert.equal(checkNaming({out: 'a/v.draft.mp4', draft: false, gateReport: 'g.json'}).ok, false); // .draft. without --draft
  assert.equal(checkNaming({out: 'a/v.mp4', draft: false}).ok, false); // final without gate report
  assert.equal(checkNaming({out: 'a/v.mp4', draft: false, gateReport: 'g.json'}).ok, true);
  assert.equal(checkNaming({out: 'a.draft/v.mp4', draft: false, gateReport: 'g.json'}).ok, true); // only the basename counts
});

test('refusals exit 3 before touching anything', async () => {
  const d = await tmpDir('rg-names-');
  try {
    const lines = [];
    const log = l => lines.push(l);
    const common = ['--episode', path.join(d, 'e.json'), '--captions', path.join(d, 'c.json'), '--composer', path.join(d, 'rc')];
    assert.equal(await run([...common, '--out', path.join(d, 'x.mp4'), '--draft'], {log}), EXIT.REFUSED);
    assert.equal(await run([...common, '--out', path.join(d, 'x.draft.mp4')], {log}), EXIT.REFUSED);
    assert.equal(await run([...common, '--out', path.join(d, 'x.mp4')], {log}), EXIT.REFUSED);
    assert.equal(await run(['--nope'], {log}), EXIT.CRASH);
    assert.ok(lines.some(l => l.startsWith('RENDER REFUSED')));
    assert.deepEqual(await fs.readdir(d), []);
  } finally { await fs.rm(d, {recursive: true}); }
});

// ---- gate check ------------------------------------------------------------------------------
const SOURCES = () => ({
  sourceHashes: {'episode.json': 'e1', 'captions.json': 'c1', 'src/YtNewsStyle01V4.tsx': 'g1', 'scripts/qc_layout_eval.mjs': 'q1', 'scripts/gates.lock.json': null},
  mediaDigest: {method: 'sha256-per-file-v1', assetDir: 'ep', digest: 'm1', files: 2, bytes: 20},
  fontsDigest: {method: 'sha256-per-file-v1', assetDir: 'fonts', digest: 'f1', files: 1, bytes: 5},
  bundleKey: 'codekey1',
});

async function writeGate(dir, {sources = SOURCES(), report = {}, manifest = {}, bundleKey} = {}) {
  const m = buildManifest({runId: 'gate-run', ...sources, bundleKey: bundleKey ?? sources.bundleKey, thresholdsSha256: 't', planSha256: 'p', frames: [0]});
  Object.assign(m, manifest);
  await fs.mkdir(dir, {recursive: true});
  await writeJsonAtomic(path.join(dir, 'run-manifest.json'), m);
  const r = {schema: 'yt-news-layout-report', version: 3, status: 'finished', pass: true, complete: true, compositionId: 'YtNewsStyle01V4', runId: 'gate-run', manifestPath: 'run-manifest.json', manifestHash: manifestHash(m), ...report};
  await writeJsonAtomic(path.join(dir, 'report.json'), r);
  return path.join(dir, 'report.json');
}

test('checkGate accepts a finished, passing report whose manifest equals the current sources', async () => {
  const d = await tmpDir('rg-gate-');
  try {
    const reportPath = await writeGate(d);
    const r = await checkGate({reportPath, currentSources: SOURCES()});
    assert.equal(r.ok, true, r.reason);
    assert.equal(r.report.runId, 'gate-run');
    assert.match(r.reportSha256, /^[0-9a-f]{64}$/);
    // bundleKey compares its code part only
    assert.equal((await checkGate({reportPath, currentSources: {...SOURCES(), bundleKey: 'codekey1-publickey'}})).ok, true);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('checkGate refuses missing, failed, incomplete, unfinished, wrong-composition and wrong-version reports', async () => {
  const d = await tmpDir('rg-gate-');
  try {
    assert.equal((await checkGate({reportPath: path.join(d, 'none.json'), currentSources: SOURCES()})).ok, false);
    assert.equal((await checkGate({reportPath: undefined, currentSources: SOURCES()})).ok, false);
    const cases = {
      'pass:false': {pass: false}, 'complete:false': {complete: false}, 'status incomplete': {status: 'incomplete', pass: false, complete: false},
      'status running': {status: 'running'}, 'status failed': {status: 'failed'}, 'wrong composition': {compositionId: 'YtNewsStyle01V3'}, 'version 2': {version: 2},
      'manifestHash mismatch': {manifestHash: 'f'.repeat(64)},
    };
    for (const [name, report] of Object.entries(cases)) {
      const r = await checkGate({reportPath: await writeGate(path.join(d, name.replace(/\W/g, '_')), {report}), currentSources: SOURCES()});
      assert.equal(r.ok, false, name);
      assert.ok(r.reason, name);
    }
    // a manifest edited after the report was written
    const dir = path.join(d, 'edited');
    const reportPath = await writeGate(dir);
    const m = JSON.parse(await fs.readFile(path.join(dir, 'run-manifest.json'), 'utf8'));
    m.thresholdsSha256 = 'tampered';
    await fs.writeFile(path.join(dir, 'run-manifest.json'), JSON.stringify(m));
    assert.match((await checkGate({reportPath, currentSources: SOURCES()})).reason, /hash/);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('checkGate refuses any differing source key, media, fonts or bundle code key', async () => {
  const d = await tmpDir('rg-gate-');
  try {
    const reportPath = await writeGate(d);
    const mutations = {
      'sourceHashes.episode.json': s => { s.sourceHashes['episode.json'] = 'x'; },
      'sourceHashes.captions.json': s => { s.sourceHashes['captions.json'] = 'x'; },
      'sourceHashes.src/YtNewsStyle01V4.tsx': s => { s.sourceHashes['src/YtNewsStyle01V4.tsx'] = 'x'; },
      'sourceHashes.scripts/qc_layout_eval.mjs': s => { s.sourceHashes['scripts/qc_layout_eval.mjs'] = 'x'; },
      'sourceHashes.scripts/gates.lock.json': s => { s.sourceHashes['scripts/gates.lock.json'] = 'x'; },
      'mediaDigest.digest': s => { s.mediaDigest.digest = 'x'; },
      'fontsDigest.digest': s => { s.fontsDigest.digest = 'x'; },
      'sourceHashes.extra': s => { s.sourceHashes.extra = 'x'; },
      bundleKey: s => { s.bundleKey = 'otherkey'; },
    };
    for (const [field, mutate] of Object.entries(mutations)) {
      const s = SOURCES();
      mutate(s);
      const r = await checkGate({reportPath, currentSources: s});
      assert.equal(r.ok, false, field);
      assert.ok(r.reason.startsWith(field), `${field} -> ${r.reason}`);
    }
  } finally { await fs.rm(d, {recursive: true}); }
});

// ---- segments and budget --------------------------------------------------------------------
test('planSegments covers [0, dur-1] exactly once', () => {
  for (const [dur, size] of [[1, 750], [750, 750], [751, 750], [16296, 750], [100, 1], [7, 3]]) {
    const segs = planSegments(dur, size);
    const covered = segs.flatMap(s => Array.from({length: s.to - s.from + 1}, (_, i) => s.from + i));
    assert.equal(covered.length, dur, `${dur}/${size}`);
    assert.deepEqual(covered, Array.from({length: dur}, (_, i) => i));
    assert.ok(segs.every((s, i) => s.index === i && s.to - s.from + 1 <= size));
  }
  assert.equal(planSegments(16296, 750).length, 22);
  assert.throws(() => planSegments(0, 10), RangeError);
  assert.throws(() => planSegments(10, 0), RangeError);
});

const manifestWith = (statuses, seconds = 100) => ({segments: statuses.map((status, i) => ({index: i, from: i * 10, to: i * 10 + 9, file: `seg-${i}.mp4`, status, wallSeconds: status === 'done' ? seconds : null}))});

test('nextAction: render pending in order, concat when all done, stop before a segment that cannot finish', () => {
  const budget = (elapsedSeconds, renderedThisInvocation, maxSeconds = 420) => ({elapsedSeconds, maxSeconds, renderedThisInvocation});
  assert.deepEqual(nextAction(manifestWith(['done', 'done']), budget(0, 0)), {action: 'concat'});
  const a = nextAction(manifestWith(['done', 'pending', 'pending']), budget(10, 0));
  assert.equal(a.action, 'render');
  assert.equal(a.segment.index, 1);
  // 420 - 300 = 120 < 1.5 x 100 -> do not start
  const stop = nextAction(manifestWith(['done', 'pending', 'pending']), budget(300, 1));
  assert.equal(stop.action, 'incomplete');
  assert.deepEqual([stop.done, stop.total], [1, 3]);
  // 420 - 250 = 170 >= 150 -> start
  assert.equal(nextAction(manifestWith(['done', 'pending', 'pending']), budget(250, 1)).action, 'render');
  // the first segment of an invocation always starts, even over budget (no livelock)
  assert.equal(nextAction(manifestWith(['done', 'pending']), budget(1000, 0)).action, 'render');
  // out of time after progress
  assert.equal(nextAction(manifestWith(['done', 'pending'], 1), budget(421, 1)).action, 'incomplete');
  // slowest finished segment drives the estimate
  const mixed = manifestWith(['done', 'done', 'pending']);
  mixed.segments[0].wallSeconds = 10;
  mixed.segments[1].wallSeconds = 200;
  assert.equal(nextAction(mixed, budget(200, 1)).action, 'incomplete'); // 220 left < 300
});

// ---- ffmpeg: concat, verify, receipt ---------------------------------------------------------
test('3 tiny segments concat frame-exactly, verify and produce a complete receipt', async () => {
  const d = await tmpDir('rg-concat-');
  try {
    const counts = [25, 25, 13];
    const files = [];
    for (const [i, n] of counts.entries()) {
      const f = path.join(d, `seg-${i}.mp4`);
      await makeClip(f, n);
      assert.equal((await verifyOutput(f, {frames: n, fps: '25/1', width: 320, height: 180, pixelFormat: 'yuv420p', audioStreams: 0})).ok, true);
      files.push(f);
    }
    const out = path.join(d, 'joined.mp4');
    await concatSegments({segmentFiles: files, outFile: out, listFile: path.join(d, 'list.txt')});
    const total = counts.reduce((a, b) => a + b, 0);
    const v = await verifyOutput(out, {frames: total, fps: '25/1', width: 320, height: 180, pixelFormat: 'yuv420p', audioStreams: 0, codec: 'h264'});
    assert.deepEqual(v.problems, []);
    assert.equal(v.measured.frames, 63);
    // faststart: moov before mdat
    const head = await fs.readFile(out);
    assert.ok(head.indexOf('moov') < head.indexOf('mdat'), 'moov atom precedes mdat');

    // wrong expectations are reported
    const wrong = await verifyOutput(out, {frames: total + 1, width: 640, audioStreams: 1});
    assert.equal(wrong.ok, false);
    assert.equal(wrong.problems.length, 3);
    assert.equal((await verifyOutput(path.join(d, 'missing.mp4'), {frames: 1})).ok, false);

    // receipt: every contract field, nothing else
    const sourceHashes = {'episode.json': 'e', 'captions.json': 'c', 'src/YtNewsStyle01V4.tsx': 'g', 'assets/YtNewsStyle01V4.reference.tsx': 'r', 'assets/ytNewsStyle01V4.entry.reference.tsx': 'er', 'src/ytNewsStyle01V4.entry.tsx': 'entry', 'src/ytNewsStyle01V4Sample.json': 'sj', 'scripts/gates.lock.json': null};
    const renderManifest = {renderId: 'rid', draft: false, durationInFrames: total, invocations: [{startedAt: 'a', endedAt: 'b', wallSeconds: 3, segmentsRendered: 3}], segments: counts.map((n, i) => ({index: i, from: counts.slice(0, i).reduce((x, y) => x + y, 0), to: counts.slice(0, i + 1).reduce((x, y) => x + y, 0) - 1, file: `seg-${i}.mp4`, sha256: 's', frameCount: n, wallSeconds: 1}))};
    const receipt = buildReceipt({
      renderManifest, renderDir: d, outputPath: out, outputSha256: await sha256File(out), outputBytes: head.length, frameCount: total,
      sources: {sourceHashes, mediaDigest: {digest: 'm', method: 'sha256-per-file-v1'}, fontsDigest: {digest: 'f'}},
      gate: {reportPath: '/g/report.json', reportSha256: 'gs', runId: 'gr', manifestHash: 'gm', checkedAtStart: 't0', checkedAtConcat: 't1'},
      tools: {node: 'v', remotion: '4', ffmpeg: 'f', chrome: 'c'}, finishedAt: 'end', relativeTo: d,
    });
    assert.deepEqual(Object.keys(receipt).sort(), [...RECEIPT_FIELDS].sort());
    assert.equal(receipt.gateRunId, 'gr');
    assert.equal(receipt.mediaDigest, 'm');
    assert.equal(receipt.hasAudio, false);
    assert.equal(receipt.segments[2].fromFrame, 50);
    assert.equal(receipt.segments[2].toFrame, 62);
    const receiptPath = path.join(d, 'joined.mp4.receipt.json');
    await writeReceipt(receiptPath, receipt);
    const written = JSON.parse(await fs.readFile(receiptPath, 'utf8'));
    for (const field of RECEIPT_FIELDS) assert.ok(field in written, field);
    assert.deepEqual(Object.keys(written), [...RECEIPT_FIELDS]);
    await assert.rejects(writeReceipt(receiptPath, {...receipt, extraField: 1}), /fields mismatch/);
    const {schema, ...incomplete} = receipt;
    await assert.rejects(writeReceipt(receiptPath, incomplete), /fields mismatch/);
    // a draft receipt nulls the gate fields
    const draft = buildReceipt({renderManifest: {...renderManifest, draft: true}, renderDir: d, outputPath: out, outputSha256: 'x', outputBytes: 1, frameCount: total, sources: {sourceHashes, mediaDigest: {digest: 'm', method: 'x'}, fontsDigest: {digest: 'f'}}, gate: null, tools: {}, finishedAt: 'end', relativeTo: d});
    for (const k of ['gateReportPath', 'gateReportSha256', 'gateRunId', 'gateManifestHash', 'gateCheckedAtStart', 'gateCheckedAtConcat']) assert.equal(draft[k], null, k);
    assert.equal(draft.draft, true);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('a segment with the wrong frame count fails verification and a concat of it would not match the plan', async () => {
  const d = await tmpDir('rg-wrong-');
  try {
    const good = path.join(d, 'good.mp4');
    const short = path.join(d, 'short.mp4');
    await makeClip(good, 25);
    await makeClip(short, 24);
    const v = await verifyOutput(short, {frames: 25});
    assert.equal(v.ok, false);
    assert.match(v.problems[0], /frames: expected 25, got 24/);
    const out = path.join(d, 'out.mp4');
    await concatSegments({segmentFiles: [good, short], outFile: out, listFile: path.join(d, 'l.txt')});
    assert.equal((await verifyOutput(out, {frames: 50})).ok, false);
    // paths with a quote in the name are escaped
    const odd = path.join(d, "it's.mp4");
    await fs.copyFile(good, odd);
    await concatSegments({segmentFiles: [odd, good], outFile: out, listFile: path.join(d, 'l2.txt')});
    assert.equal((await verifyOutput(out, {frames: 50})).ok, true);
    await assert.rejects(concatSegments({segmentFiles: [], outFile: out, listFile: path.join(d, 'l3.txt')}));
  } finally { await fs.rm(d, {recursive: true}); }
});

// ---- the whole command with a fake Remotion ---------------------------------------------------
const DURATION = 60;
const SEG = 25; // segments: 25, 25, 10

const LOCKED_SOURCE = 'export const locked = 1;\n';
const lockOf = (files = {'scripts/locked_gate.mjs': sha256Hex(LOCKED_SOURCE)}) => ({schema: 'yt-news-v4-gates-lock', version: 1, skill: 'Youtube-YT-News-Style01-V5', files});
const STUB_SCHEMA = `
  export function validateEpisode(e) { return typeof e.assetDir === 'string' ? {valid: true, errors: [], warnings: []} : {valid: false, errors: [{path: '/assetDir', rule: 'stub', message: 'bad'}], warnings: []}; }
  export function projectCaptions(c) { return c; }
`;
const FIXTURES = path.join(here, 'fixtures/episodes');
const readFixture = async rel => JSON.parse(await fs.readFile(path.join(FIXTURES, rel), 'utf8'));

/**
 * opts.schema: 'stub' (permissive episode_schema.mjs, episode {assetDir: 'ep'}) | 'real' (a copy of the real validator + schema,
 *              episode = fixtures/valid/min-3-beat.json, captions = min-captions.json, and its media files in public/)
 * opts.lock:   'ok' (a lock over scripts/locked_gate.mjs) | 'none' (no lock file)
 */
async function makeEnv(opts = {}) {
  const {schema = 'stub', lock = 'ok'} = opts;
  const d = await tmpDir('rg-env-');
  const composer = path.join(d, 'composer');
  const skill = path.join(d, 'skill');
  for (const dir of [path.join(composer, 'src'), path.join(composer, 'public/ep/broll'), path.join(composer, 'public/fonts'), path.join(skill, 'assets'), path.join(skill, 'scripts')]) await fs.mkdir(dir, {recursive: true});
  await fs.writeFile(path.join(composer, 'src/YtNewsStyle01V4.tsx'), reference);
  await fs.writeFile(path.join(composer, 'src/ytNewsStyle01V4.entry.tsx'), entryReference);
  await fs.writeFile(path.join(composer, 'src/ytNewsStyle01V4Sample.json'), '{}');
  await fs.writeFile(path.join(composer, 'src/ytNewsStyle01V4SampleCaptions.json'), '[]');
  // other pipelines' files: V4 must not look at them (the real Root.tsx imports dozens of files that do not exist here)
  await fs.writeFile(path.join(composer, 'src/Root.tsx'), realRoot);
  await fs.writeFile(path.join(composer, 'src/index.tsx'), 'export {};\n');
  await fs.writeFile(path.join(composer, 'package-lock.json'), '{}');
  await fs.writeFile(path.join(composer, 'public/ep/avatar_source.mp4'), 'AVATAR');
  await fs.writeFile(path.join(composer, 'public/ep/broll/a.mp4'), 'A');
  await fs.writeFile(path.join(composer, 'public/fonts/Kanit.ttf'), 'FONT');
  await fs.writeFile(path.join(skill, 'assets/YtNewsStyle01V4.reference.tsx'), reference);
  await fs.writeFile(path.join(skill, 'assets/ytNewsStyle01V4.entry.reference.tsx'), entryReference);
  await fs.writeFile(path.join(skill, 'scripts/qc_thresholds.json'), JSON.stringify({maxSecondsDefault: 420}));
  await fs.writeFile(path.join(skill, 'scripts/qc_layout_eval.mjs'), '// eval\n');
  await fs.writeFile(path.join(skill, 'scripts/locked_gate.mjs'), LOCKED_SOURCE);
  if (lock === 'ok') await fs.writeFile(path.join(skill, 'scripts/gates.lock.json'), JSON.stringify(lockOf()));
  const episodePath = path.join(d, 'episode.json');
  const captionsPath = path.join(d, 'captions.json');
  if (schema === 'real') {
    await fs.copyFile(path.join(realSkill, 'scripts/episode_schema.mjs'), path.join(skill, 'scripts/episode_schema.mjs'));
    await fs.copyFile(path.join(realSkill, 'assets/episode.schema.json'), path.join(skill, 'assets/episode.schema.json'));
    const episode = await readFixture('valid/min-3-beat.json');
    await fs.mkdir(path.join(composer, 'public', episode.assetDir, 'broll'), {recursive: true});
    await fs.writeFile(path.join(composer, 'public', episode.assetDir, episode.avatarFile), 'AVATAR');
    for (const src of Object.keys(episode.brollDur)) await fs.writeFile(path.join(composer, 'public', episode.assetDir, 'broll', `${src}.mp4`), 'B');
    await fs.writeFile(episodePath, JSON.stringify(episode));
    await fs.writeFile(captionsPath, JSON.stringify(await readFixture('captions/min-captions.json')));
  } else {
    await fs.writeFile(path.join(skill, 'scripts/episode_schema.mjs'), STUB_SCHEMA);
    await fs.writeFile(episodePath, JSON.stringify({assetDir: 'ep', beats: []}));
    await fs.writeFile(captionsPath, '[]');
  }
  const outDir = path.join(d, 'out');
  const clock = {ms: 1_700_000_000_000};
  const calls = {renderSegment: [], ensureBundle: 0, selectDuration: 0, inputProps: []};
  const hooks = {afterSegment: null};
  const lines = [];
  let segmentCost = 100_000;
  let frameOffset = 0;
  const deps = {
    skillDir: skill,
    now: () => clock.ms,
    log: l => lines.push(l),
    selectDuration: async () => { calls.selectDuration++; return {durationInFrames: DURATION, fps: 25, width: 1920, height: 1080}; },
    ensureBundle: async () => { calls.ensureBundle++; return {serveUrl: 'file:///fake-bundle', reused: false}; },
    renderSegment: async ({segment, outputLocation, inputProps}) => {
      calls.renderSegment.push(segment.index);
      calls.inputProps.push(inputProps);
      clock.ms += segmentCost;
      const n = segment.to - segment.from + 1 + frameOffset;
      await execFileP('ffmpeg', ['-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=black:size=1920x1080:rate=25', '-frames:v', String(n), '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-an', outputLocation]);
      if (hooks.afterSegment) await hooks.afterSegment(segment);
    },
  };
  const argsFor = (extra = []) => ['--episode', episodePath, '--captions', captionsPath, '--composer', composer, '--out', path.join(outDir, 'v.mp4'), '--segment-frames', String(SEG), '--render-id', 'r1', ...extra];
  const draftArgs = (extra = []) => argsFor(extra).map(a => (a.endsWith('v.mp4') ? path.join(outDir, 'v.draft.mp4') : a)).concat('--draft');
  // a gate report that matches the sources of this env
  const currentSources = async () => ({
    sourceHashes: await computeSourceHashes({composerDir: composer, skillDir: skill, episodePath, captionsPath}),
    mediaDigest: {...(await digestDir(path.join(composer, 'public/ep'))), assetDir: 'ep'},
    fontsDigest: {...(await digestDir(path.join(composer, 'public/fonts'))), assetDir: 'fonts'},
    bundleKey: await computeBundleCodeKey({composerDir: composer}),
  });
  const gateDir = path.join(d, 'qc');
  const makeGate = async (report = {}) => writeGate(gateDir, {sources: await currentSources(), report});
  return {d, composer, skill, episodePath, captionsPath, outDir, clock, calls, hooks, lines, deps, argsFor, draftArgs, makeGate, gateDir, setCost: ms => { segmentCost = ms; }, setFrameOffset: n => { frameOffset = n; }, cleanup: () => fs.rm(d, {recursive: true})};
}

test('final render: gate passes, segments rendered, concat verified, receipt written', async () => {
  const env = await makeEnv();
  try {
    const gateReport = await env.makeGate();
    const code = await run(env.argsFor(['--gate-report', gateReport]), env.deps);
    assert.equal(code, EXIT.COMPLETE, env.lines.join('\n'));
    assert.deepEqual(env.calls.renderSegment, [0, 1, 2]);
    const out = path.join(env.outDir, 'v.mp4');
    assert.equal((await verifyOutput(out, {frames: DURATION, fps: '25/1', width: 1920, height: 1080, pixelFormat: 'yuv420p', audioStreams: 0})).ok, true);
    const receipt = JSON.parse(await fs.readFile(`${out}.receipt.json`, 'utf8'));
    assert.deepEqual(Object.keys(receipt), [...RECEIPT_FIELDS]);
    assert.equal(receipt.draft, false);
    assert.equal(receipt.frameCount, DURATION);
    assert.equal(receipt.outputSha256, await sha256File(out));
    assert.equal(receipt.gateRunId, 'gate-run');
    assert.equal(receipt.gatesLockSha256, await sha256File(path.join(env.skill, 'scripts/gates.lock.json')));
    assert.equal(receipt.gateReportSha256, await sha256File(gateReport));
    assert.ok(receipt.gateCheckedAtStart && receipt.gateCheckedAtConcat);
    // CF-A66: the entry and its import closure replace the Root.tsx / index.tsx hashes
    assert.equal('rootTsxSha256' in receipt, false);
    assert.equal('indexTsxSha256' in receipt, false);
    assert.equal(receipt.entrySha256, await sha256File(path.join(env.composer, 'src/ytNewsStyle01V4.entry.tsx')));
    assert.equal(receipt.entryReferenceSha256, await sha256File(path.join(env.skill, 'assets/ytNewsStyle01V4.entry.reference.tsx')));
    assert.deepEqual(Object.keys(receipt.entryClosure), ['src/YtNewsStyle01V4.tsx', 'src/ytNewsStyle01V4.entry.tsx', 'src/ytNewsStyle01V4Sample.json', 'src/ytNewsStyle01V4SampleCaptions.json']);
    assert.equal(receipt.entryClosure['src/YtNewsStyle01V4.tsx'], receipt.engineSha256);
    assert.equal(receipt.segments.length, 3);
    assert.equal(receipt.segments.at(-1).toFrame, DURATION - 1);
    assert.equal(receipt.episodeJsonSha256, await sha256File(env.episodePath));
    assert.ok(env.lines.some(l => l.startsWith('RENDER COMPLETE ') && l.includes(receipt.outputSha256)));
    assert.equal(await exists(`${out}.part`), false);
  } finally { await env.cleanup(); }
});

test('final render is refused (exit 3) with no rendering when the gate does not hold', async () => {
  const env = await makeEnv();
  try {
    const out = path.join(env.outDir, 'v.mp4');
    const check = async (gateReport, label) => {
      env.calls.renderSegment.length = 0;
      const code = await run(env.argsFor(['--gate-report', gateReport]), env.deps);
      assert.equal(code, EXIT.REFUSED, label);
      assert.deepEqual(env.calls.renderSegment, [], label);
      assert.equal(await exists(out), false, label);
      assert.equal(await exists(`${out}.receipt.json`), false, label);
    };
    await check(path.join(env.d, 'no-report.json'), 'no report');
    await check(await env.makeGate({pass: false}), 'pass:false');
    await check(await env.makeGate({complete: false}), 'complete:false');
    await check(await env.makeGate({status: 'incomplete', pass: false, complete: false}), 'incomplete');
    await check(await env.makeGate({compositionId: 'Other'}), 'wrong composition');
    await check(await env.makeGate({manifestHash: 'f'.repeat(64)}), 'manifest hash');
    // gate was computed for different sources: change a qc script afterwards
    const stale = await env.makeGate();
    await fs.appendFile(path.join(env.skill, 'scripts/qc_layout_eval.mjs'), '// edited after the gate\n');
    await check(stale, 'qc script changed');
    // an unsynced engine fails the integrity check, also exit 3
    await fs.writeFile(path.join(env.composer, 'src/YtNewsStyle01V4.tsx'), reference + '\n// drift\n');
    await check(await env.makeGate(), 'engine drift');
    assert.ok(env.lines.some(l => /integrity check failed/.test(l) && /engine-drift/.test(l)));
  } finally { await env.cleanup(); }
});

test('draft render skips the gate, completes and nulls the gate fields in the receipt', async () => {
  const env = await makeEnv();
  try {
    const code = await run(env.draftArgs(), env.deps);
    assert.equal(code, EXIT.COMPLETE, env.lines.join('\n'));
    const out = path.join(env.outDir, 'v.draft.mp4');
    const receipt = JSON.parse(await fs.readFile(`${out}.receipt.json`, 'utf8'));
    assert.equal(receipt.draft, true);
    assert.equal(receipt.gatesLockSha256, await sha256File(path.join(env.skill, 'scripts/gates.lock.json')));
    assert.equal(receipt.gateReportPath, null);
    assert.equal(receipt.gateManifestHash, null);
    assert.equal(receipt.frameCount, DURATION);
  } finally { await env.cleanup(); }
});

test('time budget stops with exit 75; re-running the same id resumes and skips finished segments', async () => {
  const env = await makeEnv();
  try {
    const gateReport = await env.makeGate();
    const args = env.argsFor(['--gate-report', gateReport, '--max-seconds', '150']);
    // each fake segment costs 100 s: after one, 50 s left < 1.5 x 100 -> INCOMPLETE
    assert.equal(await run(args, env.deps), EXIT.INCOMPLETE);
    assert.deepEqual(env.calls.renderSegment, [0]);
    assert.ok(env.lines.includes('RENDER INCOMPLETE 1/3 render=r1'));
    const out = path.join(env.outDir, 'v.mp4');
    assert.equal(await exists(out), false);

    assert.equal(await run(args, env.deps), EXIT.INCOMPLETE);
    assert.deepEqual(env.calls.renderSegment, [0, 1]); // segment 0 was not re-rendered
    assert.ok(env.lines.includes('RENDER INCOMPLETE 2/3 render=r1'));
    assert.equal(env.calls.selectDuration, 1); // duration is remembered in the render manifest

    assert.equal(await run(args, env.deps), EXIT.COMPLETE, env.lines.join('\n'));
    assert.deepEqual(env.calls.renderSegment, [0, 1, 2]);
    const receipt = JSON.parse(await fs.readFile(`${out}.receipt.json`, 'utf8'));
    assert.equal(receipt.invocations.length, 3);
    assert.deepEqual(receipt.invocations.map(i => i.segmentsRendered), [1, 1, 1]);
    assert.equal(receipt.frameCount, DURATION);
  } finally { await env.cleanup(); }
});

test('an invocation always renders at least one segment, even when the budget is already spent', async () => {
  const env = await makeEnv();
  try {
    const args = env.draftArgs(['--max-seconds', '1']);
    assert.equal(await run(args, env.deps), EXIT.INCOMPLETE);
    assert.deepEqual(env.calls.renderSegment, [0]);
    assert.equal(await run(args, env.deps), EXIT.INCOMPLETE);
    assert.deepEqual(env.calls.renderSegment, [0, 1]);
    // the last pending segment is rendered and then there is nothing left but concat
    assert.equal(await run(args, env.deps), EXIT.COMPLETE, env.lines.join('\n'));
    assert.deepEqual(env.calls.renderSegment, [0, 1, 2]);
  } finally { await env.cleanup(); }
});

test('resume is refused (exit 4) when any source changed since the render started', async () => {
  const mutations = {
    'episode.json': env => fs.writeFile(env.episodePath, JSON.stringify({assetDir: 'ep', beats: [{t: 1}]})),
    'qc script': env => fs.appendFile(path.join(env.skill, 'scripts/qc_layout_eval.mjs'), '// edit\n'),
    'media': env => fs.writeFile(path.join(env.composer, 'public/ep/broll/a.mp4'), 'B'),
    'fonts': env => fs.writeFile(path.join(env.composer, 'public/fonts/Kanit.ttf'), 'FONT2'),
    'entry': env => fs.appendFile(path.join(env.composer, 'src/ytNewsStyle01V4.entry.tsx'), '\n// edit\n'),
    'entry import (sample json)': env => fs.writeFile(path.join(env.composer, 'src/ytNewsStyle01V4Sample.json'), '{"x": 1}'),
  };
  for (const [name, mutate] of Object.entries(mutations)) {
    const env = await makeEnv();
    try {
      const args = env.draftArgs(['--max-seconds', '150']);
      assert.equal(await run(args, env.deps), EXIT.INCOMPLETE, name);
      await mutate(env);
      env.calls.renderSegment.length = 0;
      assert.equal(await run(args, env.deps), EXIT.RESUME_REFUSED, `${name}: ${env.lines.join('\n')}`);
      assert.deepEqual(env.calls.renderSegment, [], name);
      assert.ok(env.lines.some(l => l.startsWith('RENDER RESUME_REFUSED sources.')), name);
    } finally { await env.cleanup(); }
  }
  // a different segment size is a different render too
  const env = await makeEnv();
  try {
    assert.equal(await run(env.draftArgs(['--max-seconds', '150']), env.deps), EXIT.INCOMPLETE);
    assert.equal(await run(env.draftArgs(['--max-seconds', '150', '--segment-frames', '30']), env.deps), EXIT.RESUME_REFUSED);
    // and a final render cannot resume a draft render with the same id, because the gate differs
  } finally { await env.cleanup(); }
});

test('editing or breaking Root.tsx / index.tsx / another pipeline file changes nothing: same sources, gate still valid, resume allowed, receipt hashes equal', async () => {
  const env = await makeEnv();
  try {
    const gateReport = await env.makeGate();
    const args = env.argsFor(['--gate-report', gateReport, '--max-seconds', '150']);
    assert.equal(await run(args, env.deps), EXIT.INCOMPLETE);
    await fs.writeFile(path.join(env.composer, 'src/Root.tsx'), 'export const Root = ((( broken\nimport "./does-not-exist";\n');
    await fs.appendFile(path.join(env.composer, 'src/index.tsx'), '\n// edit\n');
    await fs.writeFile(path.join(env.composer, 'src/OtherPipeline.tsx'), 'export {};\n');
    assert.equal(await run(env.argsFor(['--gate-report', gateReport, '--max-seconds', '1000']), env.deps), EXIT.COMPLETE, env.lines.join('\n'));
    const receipt = JSON.parse(await fs.readFile(path.join(env.outDir, 'v.mp4.receipt.json'), 'utf8'));
    const manifest = JSON.parse(await fs.readFile(path.join(env.outDir, 'v.render', 'r1', 'render-manifest.json'), 'utf8'));
    assert.equal(Object.keys(manifest.sources.sourceHashes).some(k => /Root\.tsx|index\.tsx|OtherPipeline/.test(k)), false);
    assert.equal(receipt.gateReportSha256, await sha256File(gateReport));
  } finally { await env.cleanup(); }
});

test('a finished segment that disappeared is re-rendered on resume; a gate that fails on resume refuses', async () => {
  const env = await makeEnv();
  try {
    const gateReport = await env.makeGate();
    const args = env.argsFor(['--gate-report', gateReport, '--max-seconds', '150']);
    assert.equal(await run(args, env.deps), EXIT.INCOMPLETE);
    const renderDir = path.join(env.outDir, 'v.render', 'r1');
    await fs.rm(path.join(renderDir, 'seg-000.mp4'));
    env.calls.renderSegment.length = 0;
    assert.equal(await run(args, env.deps), EXIT.INCOMPLETE);
    assert.deepEqual(env.calls.renderSegment, [0]);
    // the gate report is invalidated between invocations
    await env.makeGate({pass: false});
    env.calls.renderSegment.length = 0;
    assert.equal(await run(args, env.deps), EXIT.REFUSED);
    assert.deepEqual(env.calls.renderSegment, []);
    assert.equal(await exists(path.join(env.outDir, 'v.mp4')), false);
  } finally { await env.cleanup(); }
});

test('a wrong frame count from the renderer is a crash (exit 2), the segment is never accepted', async () => {
  const env = await makeEnv();
  try {
    env.setFrameOffset(-1);
    assert.equal(await run(env.draftArgs(), env.deps), EXIT.CRASH);
    assert.ok(env.lines.some(l => /failed verification/.test(l)));
    const renderDir = path.join(env.outDir, 'v.draft.render', 'r1');
    assert.equal(await exists(path.join(renderDir, 'seg-000.mp4')), false);
    assert.equal(await exists(path.join(renderDir, 'seg-000.tmp.mp4')), false);
    const manifest = JSON.parse(await fs.readFile(path.join(renderDir, 'render-manifest.json'), 'utf8'));
    assert.ok(manifest.segments.every(s => s.status === 'pending'));
  } finally { await env.cleanup(); }
});

test('the media-hash cache lives under the output directory, not inside the composer', async () => {
  const env = await makeEnv();
  try {
    assert.equal(await run(env.draftArgs(), env.deps), EXIT.COMPLETE);
    assert.equal(await exists(path.join(env.outDir, 'cache', 'media-hash.json')), true);
    assert.deepEqual((await fs.readdir(env.composer)).sort(), ['package-lock.json', 'public', 'src']);
  } finally { await env.cleanup(); }
});

test('validateInputs: episode_schema.mjs is mandatory (missing or without the exports = refusal), valid is read, captions are projected', async () => {
  const d = await tmpDir('rg-valid-');
  try {
    // each variant gets its own skill folder: the module is imported by URL and Node caches it
    const skillWith = async (name, source) => {
      const skill = path.join(d, name);
      await fs.mkdir(path.join(skill, 'scripts'), {recursive: true});
      if (source !== null) await fs.writeFile(path.join(skill, 'scripts/episode_schema.mjs'), source);
      return skill;
    };
    const e = path.join(d, 'e.json');
    const c = path.join(d, 'c.json');
    await fs.writeFile(c, '{"pages": []}');
    await fs.writeFile(e, JSON.stringify({assetDir: 'ep'}));
    const check = skill => validateInputs({episodePath: e, captionsPath: c, skillDir: skill, composer: d});
    // no module at all: refused, never a lighter check
    const none = await check(await skillWith('none', null));
    assert.equal(none.ok, false);
    assert.equal(none.errors[0].rule, 'schema-module');
    // a module without projectCaptions
    assert.equal((await check(await skillWith('noproj', 'export const validateEpisode = () => ({valid: true, errors: []});\n'))).errors[0].rule, 'schema-module');
    // `valid` decides: the old `ok` field is ignored
    const bad = await check(await skillWith('okfield', `
      export function validateEpisode() { return {ok: true, errors: [{path: '/x', rule: 'R9', message: 'nope'}]}; }
      export function projectCaptions(c) { return c; }`));
    assert.equal(bad.ok, false);
    assert.equal(bad.errors[0].rule, 'R9');
    // valid: true passes; publicDir is <composer>/public; the captions prop is the projection
    const good = await check(await skillWith('good', `
      export function validateEpisode(e, c, opts) { return opts.publicDir === ${JSON.stringify(path.join(d, 'public'))} ? {valid: true, errors: [], warnings: []} : {valid: false, errors: []}; }
      export function projectCaptions(c) { return {projected: true, pages: c.pages}; }`));
    assert.equal(good.ok, true);
    assert.deepEqual(good.captions, {projected: true, pages: []});
    assert.deepEqual(good.rawCaptions, {pages: []});
    // unreadable files
    await fs.writeFile(e, '{broken');
    assert.equal((await check(await skillWith('good', null))).errors[0].rule, 'json-parse');
  } finally { await fs.rm(d, {recursive: true}); }
});

test('validateInputs with the real validator: min-3-beat passes, the unknown-beat-key fixture fails with its rule', async () => {
  const env = await makeEnv({schema: 'real'});
  try {
    const good = await validateInputs({episodePath: env.episodePath, captionsPath: env.captionsPath, skillDir: env.skill, composer: env.composer});
    assert.equal(good.ok, true, JSON.stringify(good.errors));
    assert.deepEqual(good.captions, projectCaptions(good.rawCaptions));
    const {_expect, ...invalid} = await readFixture('invalid/unknown-beat-key-captionLane.json');
    assert.ok(_expect);
    await fs.writeFile(env.episodePath, JSON.stringify(invalid));
    const bad = await validateInputs({episodePath: env.episodePath, captionsPath: env.captionsPath, skillDir: env.skill, composer: env.composer});
    assert.equal(bad.ok, false);
    assert.equal(bad.errors[0].rule, 'additionalProperties');
  } finally { await env.cleanup(); }
});

test('whole command with the real validator: a valid episode renders (projected captions are the prop), an invalid one is refused with its rule and nothing is rendered', async () => {
  const env = await makeEnv({schema: 'real'});
  try {
    assert.equal(await run(env.draftArgs(), env.deps), EXIT.COMPLETE, env.lines.join('\n'));
    assert.ok(env.calls.renderSegment.length > 0);
    const raw = JSON.parse(await fs.readFile(env.captionsPath, 'utf8'));
    assert.deepEqual(env.calls.inputProps[0].captions, projectCaptions(raw));
    assert.equal(env.calls.inputProps[0].episode.assetDir, 'cf-a66-min');
  } finally { await env.cleanup(); }
  for (const draft of [true, false]) {
    const bad = await makeEnv({schema: 'real'});
    try {
      const {_expect, ...invalid} = await readFixture('invalid/unknown-beat-key-captionLane.json');
      await fs.writeFile(bad.episodePath, JSON.stringify(invalid));
      const gate = draft ? [] : ['--gate-report', path.join(bad.d, 'none.json')];
      const code = await run(draft ? bad.draftArgs() : bad.argsFor(gate), bad.deps);
      assert.equal(code, EXIT.REFUSED, bad.lines.join('\n'));
      const status = bad.lines.at(-1);
      assert.match(status, /^RENDER REFUSED episode\/captions invalid: /);
      assert.match(status, /additionalProperties/);
      assert.deepEqual([bad.calls.renderSegment, bad.calls.selectDuration, bad.calls.ensureBundle], [[], 0, 0]);
      assert.equal(await exists(path.join(bad.outDir, draft ? 'v.draft.mp4' : 'v.mp4')), false);
      assert.equal(await exists(path.join(bad.outDir, draft ? 'v.draft.render' : 'v.render')), false);
    } finally { await bad.cleanup(); }
  }
});

test('the schema module missing from the skill refuses (exit 3) instead of a JSON-only check', async () => {
  const env = await makeEnv();
  try {
    await fs.rm(path.join(env.skill, 'scripts/episode_schema.mjs'));
    assert.equal(await run(env.draftArgs(), env.deps), EXIT.REFUSED);
    assert.match(env.lines.at(-1), /^RENDER REFUSED episode\/captions invalid: .*schema-module/);
    assert.deepEqual(env.calls.renderSegment, []);
  } finally { await env.cleanup(); }
});

// ---- gates lock: final vs draft ----------------------------------------------------------------------
const lockFileOf = env => path.join(env.skill, 'scripts/gates.lock.json');
const readRenderManifest = (env, draft) => fs.readFile(path.join(env.outDir, draft ? 'v.draft.render' : 'v.render', 'r1', 'render-manifest.json'), 'utf8').then(JSON.parse);
const LOCK_STATES = {
  missing: env => fs.rm(lockFileOf(env)),
  'invalid (wrong schema)': env => fs.writeFile(lockFileOf(env), JSON.stringify({...lockOf(), schema: 'other'})),
  'invalid (not json)': env => fs.writeFile(lockFileOf(env), 'nope'),
  'invalid (escaping path)': env => fs.writeFile(lockFileOf(env), JSON.stringify(lockOf({'../x.mjs': sha256Hex('x')}))),
  mismatch: env => fs.writeFile(path.join(env.skill, 'scripts/locked_gate.mjs'), 'export const locked = 2;\n'),
  'listed file missing': env => fs.rm(path.join(env.skill, 'scripts/locked_gate.mjs')),
};

test('FINAL render: a missing, invalid or mismatching lock is refused (exit 3, nothing rendered)', async () => {
  for (const [name, mutate] of Object.entries(LOCK_STATES)) {
    const env = await makeEnv();
    try {
      await mutate(env);
      const gateReport = await env.makeGate();
      const code = await run(env.argsFor(['--gate-report', gateReport]), env.deps);
      assert.equal(code, EXIT.REFUSED, `${name}: ${env.lines.join('\n')}`);
      const status = env.lines.at(-1);
      assert.match(status, /^RENDER REFUSED integrity check failed: gates-lock/, name);
      assert.match(status, name === 'missing' ? /gates-lock-missing/ : name.startsWith('invalid') ? /gates-lock-format/ : /gates-lock: /, name);
      assert.deepEqual(env.calls.renderSegment, [], name);
      assert.equal(await exists(path.join(env.outDir, 'v.mp4')), false, name);
      assert.equal(await exists(path.join(env.outDir, 'v.mp4.receipt.json')), false, name);
    } finally { await env.cleanup(); }
  }
});

test('FINAL render: the lock is checked again before the concat (a locked file edited during the render refuses, nothing published)', async () => {
  const env = await makeEnv();
  try {
    const gateReport = await env.makeGate();
    env.hooks.afterSegment = async seg => { if (seg.index === 2) await fs.writeFile(path.join(env.skill, 'scripts/locked_gate.mjs'), 'export const locked = 3;\n'); };
    const code = await run(env.argsFor(['--gate-report', gateReport]), env.deps);
    assert.equal(code, EXIT.REFUSED, env.lines.join('\n'));
    assert.match(env.lines.at(-1), /^RENDER REFUSED integrity check failed: gates-lock: .*locked_gate\.mjs \(changed\)/);
    assert.deepEqual(env.calls.renderSegment, [0, 1, 2]);
    assert.equal(await exists(path.join(env.outDir, 'v.mp4')), false);
    assert.equal(await exists(path.join(env.outDir, 'v.mp4.receipt.json')), false);
  } finally { await env.cleanup(); }
});

test('DRAFT render: lock problems and engine drift are warnings recorded in the render manifest, the receipt keeps its fields', async () => {
  const states = {
    ...LOCK_STATES,
    'engine drift': env => fs.writeFile(path.join(env.composer, 'src/YtNewsStyle01V4.tsx'), reference + '\n// drift\n'),
  };
  const expectedId = {missing: 'gates-lock-missing', 'invalid (wrong schema)': 'gates-lock-format', 'invalid (not json)': 'gates-lock-format',
    'invalid (escaping path)': 'gates-lock-format', mismatch: 'gates-lock', 'listed file missing': 'gates-lock', 'engine drift': 'engine-drift'};
  for (const [name, mutate] of Object.entries(states)) {
    const env = await makeEnv();
    try {
      await mutate(env);
      const code = await run(env.draftArgs(), env.deps);
      assert.equal(code, EXIT.COMPLETE, `${name}: ${env.lines.join('\n')}`);
      assert.ok(env.lines.some(l => l.startsWith(`RENDER WARNING ${expectedId[name]}:`)), name);
      const manifest = await readRenderManifest(env, true);
      assert.equal(manifest.integrity.draft, true, name);
      assert.ok(manifest.integrity.warnings.some(w => w.id === expectedId[name]), name);
      const out = path.join(env.outDir, 'v.draft.mp4');
      const receipt = JSON.parse(await fs.readFile(`${out}.receipt.json`, 'utf8'));
      assert.deepEqual(Object.keys(receipt), [...RECEIPT_FIELDS], name);
      assert.equal(receipt.draft, true, name);
      const lockExists = await exists(lockFileOf(env));
      assert.equal(receipt.gatesLockSha256, lockExists ? await sha256File(lockFileOf(env)) : null, name);
      if (name === 'missing') assert.equal(manifest.integrity.lock.status, 'missing');
      if (name === 'mismatch') assert.equal(manifest.integrity.lock.status, 'mismatch');
    } finally { await env.cleanup(); }
  }
});

test('DRAFT render with a good lock records no warnings and lock.status "ok"; a draft without any lock still renders', async () => {
  const env = await makeEnv();
  try {
    assert.equal(await run(env.draftArgs(), env.deps), EXIT.COMPLETE, env.lines.join('\n'));
    const manifest = await readRenderManifest(env, true);
    assert.deepEqual(manifest.integrity.warnings, []);
    assert.deepEqual([manifest.integrity.lock.status, manifest.integrity.lock.files], ['ok', 1]);
    assert.ok(!env.lines.some(l => l.startsWith('RENDER WARNING')));
  } finally { await env.cleanup(); }
  const none = await makeEnv({lock: 'none'});
  try {
    assert.equal(await run(none.draftArgs(), none.deps), EXIT.COMPLETE, none.lines.join('\n'));
    const receipt = JSON.parse(await fs.readFile(path.join(none.outDir, 'v.draft.mp4.receipt.json'), 'utf8'));
    assert.equal(receipt.gatesLockSha256, null);
  } finally { await none.cleanup(); }
});

test('DRAFT render: entry-registration still refuses (exit 3), and a lock change during the render is a changed source', async () => {
  const env = await makeEnv();
  try {
    await fs.writeFile(path.join(env.composer, 'src/ytNewsStyle01V4.entry.tsx'), entryReference.replace('id="YtNewsStyle01V4"', 'id="YtNewsStyle01V3"'));
    assert.equal(await run(env.draftArgs(), env.deps), EXIT.REFUSED);
    assert.match(env.lines.at(-1), /^RENDER REFUSED integrity check failed: entry-registration/);
    assert.deepEqual(env.calls.renderSegment, []);
  } finally { await env.cleanup(); }
  const env2 = await makeEnv();
  try {
    env2.hooks.afterSegment = async seg => { if (seg.index === 2) await fs.rm(lockFileOf(env2)); };
    assert.equal(await run(env2.draftArgs(), env2.deps), EXIT.REFUSED, env2.lines.join('\n'));
    assert.match(env2.lines.at(-1), /sources changed during the render: sourceHashes\.scripts\/gates\.lock\.json/);
  } finally { await env2.cleanup(); }
});

test('integrityVerdict: final refuses every issue (requireLock), draft only refuses what it cannot tolerate', async () => {
  const seen = [];
  const check = async opts => {
    seen.push(opts.requireLock);
    return {ok: false, issues: [{id: 'engine-drift', message: 'e'}, {id: 'entry-drift', message: 'd'}, {id: 'gates-lock', message: 'l'}, {id: 'entry-registration', message: 'r'}, {id: 'entry-closure', message: 'c'}], warnings: [{id: 'w', message: 'w'}], lock: {status: 'mismatch', sha256: 'x', files: 1}};
  };
  const fin = await integrityVerdict({composer: 'c', skillDir: 's', draft: false, check});
  assert.deepEqual(fin.refusals.map(i => i.id), ['engine-drift', 'entry-drift', 'gates-lock', 'entry-registration', 'entry-closure']);
  const dr = await integrityVerdict({composer: 'c', skillDir: 's', draft: true, check});
  assert.deepEqual(dr.refusals.map(i => i.id), ['entry-registration', 'entry-closure']);
  assert.deepEqual(dr.warnings.map(i => i.id), ['w', 'engine-drift', 'entry-drift', 'gates-lock']);
  assert.deepEqual(seen, [true, false]);
});

test('renderSegment hands Remotion the encoder contract: bt709 (otherwise ffmpeg writes full-range yuvj420p), muted, h264/yuv420p, the segment as frameRange', async () => {
  // first real run of the Remotion path: the output was yuvj420p and verifyOutput refused it. Fake @remotion/renderer in a throw-away composer.
  const d = await tmpDir('rg-remotion-');
  try {
    const pkg = path.join(d, 'node_modules/@remotion/renderer');
    await fs.mkdir(pkg, {recursive: true});
    await fs.writeFile(path.join(d, 'package.json'), '{}');
    await fs.writeFile(path.join(pkg, 'package.json'), '{"name":"@remotion/renderer","main":"index.js"}');
    await fs.writeFile(path.join(pkg, 'index.js'), 'exports.selectComposition = async o => ({id: o.id, durationInFrames: 9});\nexports.renderMedia = async o => { globalThis.__renderMediaOptions = o; };');
    await renderSegment({composer: d, serveUrl: '/bundle', inputProps: {a: 1}, segment: {index: 2, from: 500, to: 634}, outputLocation: '/o.mp4', concurrency: 2});
    const o = globalThis.__renderMediaOptions;
    assert.equal(o.colorSpace, 'bt709');
    assert.equal(o.pixelFormat, 'yuv420p');
    assert.equal(o.codec, 'h264');
    assert.equal(o.muted, true);
    assert.deepEqual(o.frameRange, [500, 634]);
    assert.equal(o.concurrency, 2);
    assert.equal(ENCODER.colorSpace, 'bt709');
  } finally { delete globalThis.__renderMediaOptions; await fs.rm(d, {recursive: true}); }
});

test('ensureBundle bundles from the V4 entry (never index.tsx / Root.tsx) and reuses the bundle for the same key', async () => {
  const d = await tmpDir('rg-bundle-');
  try {
    const pkg = path.join(d, 'composer/node_modules/@remotion/bundler');
    await fs.mkdir(pkg, {recursive: true});
    await fs.writeFile(path.join(d, 'composer/package.json'), '{}');
    await fs.writeFile(path.join(pkg, 'package.json'), '{"name":"@remotion/bundler","main":"index.js"}');
    await fs.writeFile(path.join(pkg, 'index.js'), "exports.bundle = async o => { (globalThis.__bundleCalls ??= []).push(o); await require('fs').promises.mkdir(o.outDir, {recursive: true}); return o.outDir; };");
    const renderDir = path.join(d, 'render');
    await fs.mkdir(renderDir);
    const options = {composer: path.join(d, 'composer'), renderDir, publicDir: '/pub', key: {codeKey: 'k', media: 'm', fonts: 'f'}};
    assert.equal((await ensureBundle(options)).reused, false);
    assert.equal(globalThis.__bundleCalls.length, 1);
    assert.equal(globalThis.__bundleCalls[0].entryPoint, path.join(d, 'composer/src/ytNewsStyle01V4.entry.tsx'));
    assert.equal((await ensureBundle(options)).reused, true);
    assert.equal(globalThis.__bundleCalls.length, 1);
  } finally { delete globalThis.__bundleCalls; await fs.rm(d, {recursive: true}); }
});

test('newSegmentRecords names files seg-NNN.mp4 and starts pending', () => {
  const r = newSegmentRecords(60, 25);
  assert.deepEqual(r.map(s => s.file), ['seg-000.mp4', 'seg-001.mp4', 'seg-002.mp4']);
  assert.ok(r.every(s => s.status === 'pending' && s.sha256 === null));
});
