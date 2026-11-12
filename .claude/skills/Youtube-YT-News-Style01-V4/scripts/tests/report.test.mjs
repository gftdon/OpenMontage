import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {makeReport, beginReport, writeReport, hashSources, createRunDirectory, openRunForResume, writeRunManifest, ResumeRefusedError} from '../qc_report.mjs';
import {buildManifest, manifestHash, appendInvocation} from '../qc_manifest.mjs';

const H = 'a'.repeat(64);
const metaFor = (frames, manifestHash = H, invocationId = 'inv-1') => frames.map(frame => ({frame, manifestHash, invocationId}));
const base = (over = {}) => {
  const frames = over.requestedFrames ?? [0, 1];
  return {fullPlanFrames: [0, 1], requestedFrames: frames, issues: [], manifestHash: H, manifestPath: 'run-manifest.json', planSha256: 'p', frameMeta: metaFor(frames), invocations: [{invocationId: 'inv-1', wallSeconds: 2}], ...over};
};

test('subset is diagnostic never acceptance', () => {
  const r = makeReport(base({requestedFrames: [0]}));
  assert.equal(r.complete, false);
  assert.equal(r.pass, false);
  assert.equal(r.diagnosticPass, true);
});
test('exact complete plan accepted', () => {
  const r = makeReport(base());
  assert.equal(r.version, 3);
  assert.equal(r.pass, true);
  assert.equal(r.complete, true);
  assert.equal(r.status, 'finished');
  assert.equal(r.measuredCount, 2);
  assert.equal(r.manifestHash, H);
  assert.equal(r.planSha256, 'p');
});
test('issues, missing manifestHash and unmeasured frames block pass', () => {
  assert.equal(makeReport(base({issues: [{id: 'x'}]})).pass, false);
  assert.equal(makeReport(base({issues: [{id: 'x'}]})).diagnosticPass, false);
  assert.equal(makeReport(base({manifestHash: undefined})).pass, false);
  assert.equal(makeReport(base({frameMeta: metaFor([0])})).pass, false); // frame 1 never measured
  assert.equal(makeReport(base({temporalSweep: {complete: false}})).pass, false);
});
test('incomplete never passes, whatever else is true', () => {
  const r = makeReport(base({status: 'incomplete'}));
  assert.equal(r.status, 'incomplete');
  assert.equal(r.pass, false);
  assert.equal(r.complete, false);
  assert.equal(r.diagnosticPass, false);
  for (const status of ['running', 'failed', 'refused']) assert.equal(makeReport(base({status})).pass, false, status);
});
test('mixed manifestHash across samples is not a pass', () => {
  const frameMeta = [{frame: 0, manifestHash: H, invocationId: 'inv-1'}, {frame: 1, manifestHash: 'b'.repeat(64), invocationId: 'inv-1'}];
  const r = makeReport(base({frameMeta}));
  assert.equal(r.manifestConsistent, false);
  assert.equal(r.pass, false);
  assert.equal(r.diagnosticPass, true);
});
test('reusedFrames counts frames measured by an earlier invocation than the last one', () => {
  const frameMeta = [
    {frame: 0, manifestHash: H, invocationId: 'inv-1'},
    {frame: 1, manifestHash: H, invocationId: 'inv-2'},
    {frame: 2, manifestHash: H, invocationId: 'inv-3'},
    {frame: 3, manifestHash: H, invocationId: 'inv-3'},
  ];
  const invocations = [{invocationId: 'inv-1', wallSeconds: 10}, {invocationId: 'inv-2', wallSeconds: 5.5}, {invocationId: 'inv-3', wallSeconds: 1}];
  const r = makeReport({fullPlanFrames: [0, 1, 2, 3], requestedFrames: [0, 1, 2, 3], issues: [], manifestHash: H, frameMeta, invocations});
  assert.equal(r.reusedFrames, 2);
  assert.equal(r.resumed, true);
  assert.equal(r.measuredCount, 4);
  assert.equal(r.wallSecondsTotal, 16.5);
  assert.equal(r.pass, true);
  const single = makeReport(base());
  assert.equal(single.reusedFrames, 0);
  assert.equal(single.resumed, false);
  assert.deepEqual(single.warnings, []);
});
test('warnings are carried through and do not fail the run', () => {
  const r = makeReport(base({warnings: ['face-box-default']}));
  assert.deepEqual(r.warnings, ['face-box-default']);
  assert.equal(r.pass, true);
});

test('source hash changes and stale success invalidated before crash', async () => {
  const d = await fs.mkdtemp(path.join(os.tmpdir(), 'qc-report-'));
  try {
    const src = path.join(d, 'source');
    await fs.writeFile(src, 'A');
    const a = await hashSources([src]);
    await fs.writeFile(src, 'B');
    assert.notDeepEqual(a, await hashSources([src]));
    await writeReport(d, {pass: true});
    await beginReport(d, {runId: 'new'});
    const r = JSON.parse(await fs.readFile(path.join(d, 'report.json')));
    assert.equal(r.pass, false);
    assert.equal(r.status, 'running');
    assert.equal(r.runId, 'new');
    assert.equal(r.version, 3);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('each run gets a new empty artifact directory', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'qc-runs-'));
  try {
    const a = await createRunDirectory(root, 'a');
    await fs.writeFile(path.join(a, 'old.png'), 'old');
    const b = await createRunDirectory(root, 'b');
    assert.deepEqual(await fs.readdir(b), []);
    await assert.rejects(createRunDirectory(root, 'a'));
  } finally { await fs.rm(root, {recursive: true}); }
});

// ---- openRunForResume -------------------------------------------------------------------------
const makeCurrent = () => ({
  compositionId: 'YtNewsStyle01V4',
  sourceHashes: {'episode.json': 'e1', 'captions.json': 'c1', 'src/YtNewsStyle01V4.tsx': 'g1', 'scripts/qc_layout_eval.mjs': 'q1', 'scripts/gates.lock.json': null},
  mediaDigest: {method: 'sha256-per-file-v1', assetDir: 'ep', digest: 'm1', files: 3, bytes: 30},
  fontsDigest: {method: 'sha256-per-file-v1', assetDir: 'fonts', digest: 'f1', files: 1, bytes: 10},
  thresholdsSha256: 't1', bundleKey: 'k1', renderer: {remotion: '4.0.1', node: 'v22'},
});

async function storedRun() {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'qc-resume-'));
  const dir = await createRunDirectory(root, 'run1');
  const current = makeCurrent();
  const manifest = buildManifest({runId: 'run1', ...current, planSha256: 'plan1', frames: [0, 25, 50]});
  const written = await writeRunManifest(dir, manifest);
  return {root, dir, current, manifest, written};
}

test('openRunForResume accepts an exact match (plan unknown to the caller is not compared)', async () => {
  const {root, manifest, written, current} = await storedRun();
  try {
    await appendInvocation(path.join(root, 'runs', 'run1'), {invocationId: 'i1'});
    const run = await openRunForResume(root, 'run1', current);
    assert.equal(run.manifestHash, manifestHash(manifest));
    assert.equal(run.manifestHash, written.manifestHash);
    assert.deepEqual(run.manifest.frames, [0, 25, 50]);
    assert.deepEqual(run.invocations, [{invocationId: 'i1'}]);
    // supplying the right plan is also fine
    await openRunForResume(root, 'run1', {...current, planSha256: 'plan1'});
  } finally { await fs.rm(root, {recursive: true}); }
});

test('openRunForResume refuses each mismatched manifest key and names it', async () => {
  const {root, current} = await storedRun();
  try {
    const cases = {
      'sourceHashes.episode.json': c => { c.sourceHashes['episode.json'] = 'CHANGED'; },
      'sourceHashes.captions.json': c => { c.sourceHashes['captions.json'] = 'CHANGED'; },
      'sourceHashes.src/YtNewsStyle01V4.tsx': c => { c.sourceHashes['src/YtNewsStyle01V4.tsx'] = 'CHANGED'; },
      'sourceHashes.scripts/qc_layout_eval.mjs': c => { c.sourceHashes['scripts/qc_layout_eval.mjs'] = 'CHANGED'; },
      thresholdsSha256: c => { c.thresholdsSha256 = 'CHANGED'; },
      'mediaDigest.digest': c => { c.mediaDigest.digest = 'CHANGED'; },
      'fontsDigest.digest': c => { c.fontsDigest.digest = 'CHANGED'; },
      bundleKey: c => { c.bundleKey = 'CHANGED'; },
      'renderer.remotion': c => { c.renderer.remotion = '4.0.2'; },
      planSha256: c => { c.planSha256 = 'otherplan'; },
      compositionId: c => { c.compositionId = 'Other'; },
    };
    for (const [field, mutate] of Object.entries(cases)) {
      const changed = structuredClone(current);
      mutate(changed);
      await assert.rejects(openRunForResume(root, 'run1', changed), e => e instanceof ResumeRefusedError && e.field === field && e.code === 'RESUME_REFUSED', field);
    }
    // a hash key that appears or disappears
    const extra = structuredClone(current);
    extra.sourceHashes['scripts/gates.lock.json'] = 'newlock';
    await assert.rejects(openRunForResume(root, 'run1', extra), e => e.field === 'sourceHashes.scripts/gates.lock.json');
    const dropped = structuredClone(current);
    delete dropped.sourceHashes['captions.json'];
    await assert.rejects(openRunForResume(root, 'run1', dropped), e => e.field === 'sourceHashes.captions.json');
  } finally { await fs.rm(root, {recursive: true}); }
});

test('openRunForResume refuses unknown run, unsafe id and a caller without hashes', async () => {
  const {root, current} = await storedRun();
  try {
    await assert.rejects(openRunForResume(root, 'nope', current), e => e.field === 'run-manifest.json');
    await assert.rejects(openRunForResume(root, '../run1', current), e => e.field === 'runId');
    await assert.rejects(openRunForResume(root, 'run1', {compositionId: 'YtNewsStyle01V4'}), e => e.field === 'currentManifest');
    await fs.writeFile(path.join(root, 'runs', 'run1', 'run-manifest.json'), '{broken');
    await assert.rejects(openRunForResume(root, 'run1', current), e => e.field === 'run-manifest.json');
  } finally { await fs.rm(root, {recursive: true}); }
});
