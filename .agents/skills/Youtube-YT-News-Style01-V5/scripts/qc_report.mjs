// Layout-gate report (schema "yt-news-layout-report", version 3) and run-directory helpers.
//
// v3 adds the run manifest + resume bookkeeping on top of the v2 keys:
//   manifestHash, manifestPath, planSha256, measuredCount, reusedFrames, resumed, invocations[],
//   wallSecondsTotal, warnings, status (running | incomplete | finished | failed | refused).
// `pass` is true only for a finished, complete run where every measured sample carries the same
// manifestHash as the run and no issue was found.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {manifestHash as hashManifest, diffManifests, readJson, readInvocations, writeJsonAtomic} from './qc_manifest.mjs';

export const REPORT_SCHEMA = 'yt-news-layout-report';
export const REPORT_VERSION = 3;
export const RUN_MANIFEST_FILE = 'run-manifest.json';

export async function hashSources(files) {
  const out = {};
  for (const f of [...new Set(files)].sort()) out[f] = createHash('sha256').update(await fs.readFile(f)).digest('hex');
  return out;
}

export async function writeReport(out, report) {
  const tmp = path.join(out, 'report.json.tmp');
  await fs.writeFile(tmp, JSON.stringify(report, null, 2));
  await fs.rename(tmp, path.join(out, 'report.json'));
}

/** Invalidate any previous success: the report on disk says "running, pass:false" until the run ends. */
export async function beginReport(out, meta) {
  await fs.mkdir(out, {recursive: true});
  await writeReport(out, {schema: REPORT_SCHEMA, version: REPORT_VERSION, ...meta, status: 'running', complete: false, pass: false, diagnosticPass: false});
}

const sameFrames = (a, b) => {
  const x = [...a].sort((p, q) => p - q);
  const y = [...b].sort((p, q) => p - q);
  return x.length === y.length && x.every((f, i) => f === y[i]);
};

/**
 * Build a v3 report.
 *   fullPlanFrames / requestedFrames   the plan and what was asked for (a strict subset is diagnostic only)
 *   issues                              evaluation issues
 *   manifestHash                        hash of the run manifest this report is about
 *   frameMeta                           [{frame, manifestHash, invocationId}] one entry per measured frame
 *   invocations                         invocation records in order (the last one is "this" invocation)
 *   status                              defaults to 'finished'; any other value can never pass
 * Remaining fields (compositionId, runId, startedAt, temporalSweep, ...) pass through unchanged.
 */
export function makeReport({
  fullPlanFrames, requestedFrames, issues, manifestHash, manifestPath, planSha256,
  frameMeta = [], invocations = [], warnings = [], status = 'finished', ...meta
}) {
  const finished = status === 'finished';
  const planMatched = fullPlanFrames.length === requestedFrames.length && sameFrames(fullPlanFrames, requestedFrames);
  const complete = finished && meta.temporalSweep?.complete !== false && planMatched;

  // Every requested frame must have been measured, and all on the manifest this report is about.
  const measured = new Map(frameMeta.map(m => [m.frame, m]));
  const measuredAll = requestedFrames.every(f => measured.has(f));
  const oneManifest = typeof manifestHash === 'string' && manifestHash.length > 0
    && frameMeta.every(m => m.manifestHash === manifestHash) && measuredAll;

  // Frames measured by an earlier invocation than the last one were reused, not re-measured.
  const lastInvocationId = invocations.length ? invocations[invocations.length - 1].invocationId : undefined;
  const reusedFrames = lastInvocationId === undefined ? 0 : frameMeta.filter(m => m.invocationId !== lastInvocationId).length;
  const wallSecondsTotal = invocations.reduce((sum, inv) => sum + (Number(inv.wallSeconds) || 0), 0);

  const diagnosticPass = finished && issues.length === 0;
  return {
    schema: REPORT_SCHEMA, version: REPORT_VERSION, ...meta,
    status,
    manifestHash, manifestPath, planSha256,
    fullPlanFrames, fullPlanCount: fullPlanFrames.length,
    requestedFrames, requestedCount: requestedFrames.length,
    measuredCount: frameMeta.length, reusedFrames, resumed: invocations.length > 1,
    invocations, wallSecondsTotal: Math.round(wallSecondsTotal * 1000) / 1000, warnings,
    manifestConsistent: oneManifest,
    complete, diagnosticPass,
    pass: finished && complete && oneManifest && issues.length === 0,
    issues, actualVideo: true,
  };
}

// ---------------------------------------------------------------------------------------------
// run directories
// ---------------------------------------------------------------------------------------------

/** A brand new, exclusive run directory (non-recursive mkdir of the leaf: an existing id is an error). */
export async function createRunDirectory(root, id) {
  const dir = path.join(root, 'runs', id);
  await fs.mkdir(path.dirname(dir), {recursive: true});
  await fs.mkdir(dir);
  return dir;
}

export class ResumeRefusedError extends Error {
  constructor(field, message) {
    super(message ?? `resume refused: ${field}`);
    this.name = 'ResumeRefusedError';
    this.code = 'RESUME_REFUSED';
    this.field = field;
  }
}

/** Manifest keys that must be identical between the stored run and the current invocation. */
export const RESUME_KEYS = ['schema', 'version', 'compositionId', 'sourceHashes', 'mediaDigest', 'fontsDigest', 'thresholdsSha256', 'bundleKey', 'renderer', 'planSha256', 'frames'];

function assertSafeRunId(id) {
  if (typeof id !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(id) || id.includes('..')) {
    throw new ResumeRefusedError('runId', `invalid run id: ${String(id)}`);
  }
}

/**
 * Re-open an existing run directory for another invocation.
 * `currentManifest` carries what the caller recomputed from disk right now (sourceHashes,
 * mediaDigest, fontsDigest, thresholdsSha256, ...). Every key of RESUME_KEYS that the caller supplies
 * is compared with the stored run-manifest.json, deeply and in sorted order; the first mismatch throws
 * ResumeRefusedError(field). Keys the caller does not know yet (planSha256/frames on a resume: the plan
 * comes from the stored manifest) are not compared.
 * Returns {dir, manifest, manifestHash, invocations}.
 */
export async function openRunForResume(root, id, currentManifest) {
  assertSafeRunId(id);
  const dir = path.join(root, 'runs', id);
  let stored;
  try {
    stored = await readJson(path.join(dir, RUN_MANIFEST_FILE));
  } catch (error) {
    if (error.code === 'ENOENT') throw new ResumeRefusedError('run-manifest.json', `no run-manifest.json in ${dir}`);
    throw new ResumeRefusedError('run-manifest.json', `unreadable run-manifest.json: ${error.message}`);
  }
  const wanted = {};
  const have = {};
  for (const key of RESUME_KEYS) {
    if (currentManifest?.[key] === undefined) continue;
    wanted[key] = currentManifest[key];
    have[key] = stored[key];
  }
  if (!Object.keys(wanted).includes('sourceHashes') || !Object.keys(wanted).includes('mediaDigest')) {
    throw new ResumeRefusedError('currentManifest', 'currentManifest must carry sourceHashes and mediaDigest');
  }
  const mismatch = diffManifests(have, wanted);
  if (mismatch) throw new ResumeRefusedError(mismatch);
  return {dir, manifest: stored, manifestHash: hashManifest(stored), invocations: await readInvocations(dir)};
}

/** Persist the run manifest atomically; returns its path and hash. */
export async function writeRunManifest(dir, manifest) {
  const file = path.join(dir, RUN_MANIFEST_FILE);
  await writeJsonAtomic(file, manifest);
  return {manifestPath: file, manifestHash: hashManifest(manifest)};
}
