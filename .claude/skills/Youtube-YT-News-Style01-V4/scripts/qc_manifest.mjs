// Run-manifest helpers shared by the layout gate (qc_layout), the render guard (render_episode)
// and the report builder (qc_report). Pure Node 22 ESM, no dependencies.
//
// What lives here:
//   - sha256 helpers (buffer / file) and a canonical JSON serializer (sorted keys);
//   - computeSourceHashes(): one hash per input that can change a gate verdict or a render;
//   - computeBundleCodeKey(): the "code part" of the Remotion bundle key;
//   - buildManifest() / manifestHash() / diffManifests(): the run manifest and its key-by-key diff;
//   - writeJsonAtomic(): tmp file + rename, so a killed process never leaves half a JSON file;
//   - appendInvocation() / readInvocations(): invocations.jsonl (one JSON object per line).
import fs from 'node:fs/promises';
import {createReadStream} from 'node:fs';
import path from 'node:path';
import {createHash, randomBytes} from 'node:crypto';

export const COMPOSITION_ID = 'YtNewsStyle01V4';
export const MANIFEST_SCHEMA = 'yt-news-v4-run-manifest';
export const MANIFEST_VERSION = 1;

// ---------------------------------------------------------------------------------------------
// hashing
// ---------------------------------------------------------------------------------------------

export function sha256Hex(data) {
  return createHash('sha256').update(data).digest('hex');
}

/** Streaming sha256 of a file (does not load the whole file in memory). */
export function sha256File(file) {
  return new Promise((resolve, reject) => {
    const hash = createHash('sha256');
    const stream = createReadStream(file);
    stream.on('error', reject);
    stream.on('data', chunk => hash.update(chunk));
    stream.on('end', () => resolve(hash.digest('hex')));
  });
}

/**
 * Deterministic JSON: object keys sorted recursively, no whitespace.
 * `undefined` values inside objects are dropped (same as JSON.stringify); arrays keep their order.
 */
export function canonicalJSON(value) {
  if (value === null || typeof value !== 'object') {
    const text = JSON.stringify(value);
    if (text === undefined) throw new TypeError('canonicalJSON: unsupported value ' + String(value));
    return text;
  }
  if (Array.isArray(value)) return '[' + value.map(v => (v === undefined ? 'null' : canonicalJSON(v))).join(',') + ']';
  const keys = Object.keys(value).filter(k => value[k] !== undefined).sort();
  return '{' + keys.map(k => JSON.stringify(k) + ':' + canonicalJSON(value[k])).join(',') + '}';
}

/** manifestHash = sha256(canonicalJSON(manifest)). */
export function manifestHash(manifest) {
  return sha256Hex(canonicalJSON(manifest));
}

// ---------------------------------------------------------------------------------------------
// source hashes
// ---------------------------------------------------------------------------------------------

async function exists(file) {
  try { await fs.access(file); return true; } catch { return false; }
}

/**
 * Hash every input that can change a gate verdict or a render. Keys follow gate-spec section 5:
 *   episode.json, captions.json                      the two data inputs
 *   src/YtNewsStyle01V4.tsx, src/Root.tsx, src/index.tsx   (relative to the composer)
 *   assets/YtNewsStyle01V4.reference.tsx             (relative to the skill)
 *   scripts/qc_*.mjs|json, scripts/media_digest.mjs, scripts/gate_integrity.mjs,
 *   scripts/episode_schema.mjs (when present), scripts/gates.lock.json (null when absent)
 *   remotion-composer/package-lock.json
 * Required files that are missing throw; optional ones are recorded as null so that "file appeared"
 * and "file vanished" both show up as a key difference.
 */
export async function computeSourceHashes({composerDir, skillDir, episodePath, captionsPath}) {
  const out = {};
  const hashRequired = async (key, file) => { out[key] = await sha256File(file); };
  const hashOptional = async (key, file) => { out[key] = (await exists(file)) ? await sha256File(file) : null; };

  await hashRequired('episode.json', episodePath);
  await hashRequired('captions.json', captionsPath);
  await hashRequired('src/YtNewsStyle01V4.tsx', path.join(composerDir, 'src', 'YtNewsStyle01V4.tsx'));
  await hashRequired('src/Root.tsx', path.join(composerDir, 'src', 'Root.tsx'));
  await hashRequired('src/index.tsx', path.join(composerDir, 'src', 'index.tsx'));
  await hashRequired('remotion-composer/package-lock.json', path.join(composerDir, 'package-lock.json'));
  await hashRequired('assets/YtNewsStyle01V4.reference.tsx', path.join(skillDir, 'assets', 'YtNewsStyle01V4.reference.tsx'));

  const scriptsDir = path.join(skillDir, 'scripts');
  const names = (await fs.readdir(scriptsDir)).filter(f => f.startsWith('qc_') && (f.endsWith('.mjs') || f.endsWith('.json')));
  for (const name of names) await hashRequired('scripts/' + name, path.join(scriptsDir, name));
  for (const name of ['media_digest.mjs', 'gate_integrity.mjs', 'episode_schema.mjs', 'gates.lock.json']) {
    await hashOptional('scripts/' + name, path.join(scriptsDir, name));
  }
  return Object.fromEntries(Object.entries(out).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)));
}

async function walkFiles(dir, prefix = '') {
  const found = [];
  for (const entry of await fs.readdir(dir, {withFileTypes: true})) {
    const rel = prefix ? prefix + '/' + entry.name : entry.name;
    if (entry.isDirectory()) found.push(...await walkFiles(path.join(dir, entry.name), rel));
    else if (entry.isFile()) found.push(rel);
  }
  return found.sort();
}

/**
 * Code part of the bundle key: sha256 over every file under composer/src (relpath + hash),
 * the package-lock hash and the installed remotion version. Root.tsx imports every composition in
 * src, so any file in src can change the bundle.
 */
export async function computeBundleCodeKey({composerDir}) {
  const parts = [];
  for (const rel of await walkFiles(path.join(composerDir, 'src'))) {
    parts.push(`src/${rel}\t${await sha256File(path.join(composerDir, 'src', rel))}`);
  }
  const lock = path.join(composerDir, 'package-lock.json');
  parts.push(`package-lock.json\t${(await exists(lock)) ? await sha256File(lock) : 'none'}`);
  parts.push(`remotion\t${await readRemotionVersion(composerDir)}`);
  return sha256Hex(parts.join('\n'));
}

export async function readRemotionVersion(composerDir) {
  try {
    const pkg = JSON.parse(await fs.readFile(path.join(composerDir, 'node_modules', 'remotion', 'package.json'), 'utf8'));
    return String(pkg.version);
  } catch {
    return 'unknown';
  }
}

// ---------------------------------------------------------------------------------------------
// manifest
// ---------------------------------------------------------------------------------------------

/** Assemble the run manifest. Missing optional pieces are simply left out (plan info is added later). */
export function buildManifest({
  runId, compositionId = COMPOSITION_ID, sourceHashes, mediaDigest, fontsDigest, bundleKey,
  renderer, planSha256, frames, thresholdsSha256,
}) {
  const manifest = {schema: MANIFEST_SCHEMA, version: MANIFEST_VERSION, runId, compositionId, sourceHashes, mediaDigest, fontsDigest, bundleKey, renderer, planSha256, frames, thresholdsSha256};
  for (const key of Object.keys(manifest)) if (manifest[key] === undefined) delete manifest[key];
  return manifest;
}

/**
 * Compare two manifests (or any two JSON values) key by key, in sorted key order, and return the
 * path of the first mismatch ("sourceHashes.src/Root.tsx", "mediaDigest.digest", "frames", ...) or
 * null when they are identical. A key present on one side only is a mismatch. Arrays are compared
 * whole (by canonical JSON) and reported at the array's own path.
 */
export function diffManifests(a, b, prefix = '') {
  const isObject = v => v !== null && typeof v === 'object' && !Array.isArray(v);
  if (isObject(a) && isObject(b)) {
    const keys = [...new Set([...Object.keys(a), ...Object.keys(b)])].filter(k => a[k] !== undefined || b[k] !== undefined).sort();
    for (const key of keys) {
      const where = prefix ? prefix + '.' + key : key;
      if (!(key in a) || a[key] === undefined || !(key in b) || b[key] === undefined) return where;
      const inner = diffManifests(a[key], b[key], where);
      if (inner) return inner;
    }
    return null;
  }
  return canonicalJSON(a) === canonicalJSON(b) ? null : (prefix || '(root)');
}

// ---------------------------------------------------------------------------------------------
// files
// ---------------------------------------------------------------------------------------------

/** Write JSON through a unique tmp file in the same directory, then rename over the target. */
export async function writeJsonAtomic(file, value) {
  const tmp = `${file}.${process.pid}.${randomBytes(4).toString('hex')}.tmp`;
  try {
    await fs.writeFile(tmp, JSON.stringify(value, null, 2));
    await fs.rename(tmp, file);
  } catch (error) {
    await fs.rm(tmp, {force: true});
    throw error;
  }
}

export async function readJson(file) {
  return JSON.parse(await fs.readFile(file, 'utf8'));
}

export const INVOCATIONS_FILE = 'invocations.jsonl';

/** Append one invocation record (a single line; appendFile of a short line is atomic enough for one writer). */
export async function appendInvocation(dir, record) {
  await fs.appendFile(path.join(dir, INVOCATIONS_FILE), JSON.stringify(record) + '\n');
}

/** Read invocations.jsonl; a missing file is an empty list, a torn/invalid line is skipped. */
export async function readInvocations(dir) {
  let text;
  try { text = await fs.readFile(path.join(dir, INVOCATIONS_FILE), 'utf8'); } catch (error) {
    if (error.code === 'ENOENT') return [];
    throw error;
  }
  const records = [];
  for (const line of text.split('\n')) {
    if (!line.trim()) continue;
    try { records.push(JSON.parse(line)); } catch { /* torn line from a killed append: ignore */ }
  }
  return records;
}
