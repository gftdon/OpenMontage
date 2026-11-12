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

// The V4 Remotion entry point. EVERY V4 tool (gate, render, stills) bundles from this file, never from Root.tsx / index.tsx.
// Paths use "/" and are relative to the composer directory.
export const ENTRY_FILE = 'ytNewsStyle01V4.entry.tsx';
export const ENTRY_REL = `src/${ENTRY_FILE}`;
export const ENTRY_REFERENCE_FILE = 'ytNewsStyle01V4.entry.reference.tsx';
export const ENGINE_REL = 'src/YtNewsStyle01V4.tsx';
export const ENGINE_REFERENCE_FILE = 'YtNewsStyle01V4.reference.tsx';
/** Absolute path of the entry point for Remotion bundle(). */
export const entryPointOf = composerDir => path.join(composerDir, ...ENTRY_REL.split('/'));
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
 *   src/ytNewsStyle01V4.entry.tsx and every file it imports (transitively, relative imports only, see computeImportClosure;
 *   today: src/YtNewsStyle01V4.tsx + the two sample JSONs)   (relative to the composer; Root.tsx / index.tsx are NOT hashed)
 *   assets/YtNewsStyle01V4.reference.tsx, assets/ytNewsStyle01V4.entry.reference.tsx   (relative to the skill)
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
  for (const rel of await computeImportClosure({composerDir})) await hashRequired(rel, path.join(composerDir, ...rel.split('/')));
  await hashRequired('remotion-composer/package-lock.json', path.join(composerDir, 'package-lock.json'));
  await hashRequired('assets/YtNewsStyle01V4.reference.tsx', path.join(skillDir, 'assets', ENGINE_REFERENCE_FILE));
  await hashRequired('assets/ytNewsStyle01V4.entry.reference.tsx', path.join(skillDir, 'assets', ENTRY_REFERENCE_FILE));

  const scriptsDir = path.join(skillDir, 'scripts');
  const names = (await fs.readdir(scriptsDir)).filter(f => f.startsWith('qc_') && (f.endsWith('.mjs') || f.endsWith('.json')));
  for (const name of names) await hashRequired('scripts/' + name, path.join(scriptsDir, name));
  for (const name of ['media_digest.mjs', 'gate_integrity.mjs', 'episode_schema.mjs', 'gates.lock.json']) {
    await hashOptional('scripts/' + name, path.join(scriptsDir, name));
  }
  return Object.fromEntries(Object.entries(out).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)));
}

// ---------------------------------------------------------------------------------------------
// import closure of the entry
// ---------------------------------------------------------------------------------------------

const RESOLVE_EXTENSIONS = ['', '.tsx', '.ts', '.jsx', '.js', '.mjs', '.json', '.css'];
const CODE_EXTENSIONS = new Set(['.tsx', '.ts', '.jsx', '.js', '.mjs']);
// import x from "./a" | import {x} from "./a" | import "./a" | export {x} from "./a" | export * from "./a"  (also across lines)
const STATIC_IMPORT_RE = /(?:^|[\n;])\s*(?:import|export)\b[^;'"`]*?\bfrom\s*(['"])(\.{1,2}\/[^'"\n]*|\.{1,2})\1|(?:^|[\n;])\s*import\s*(['"])(\.{1,2}\/[^'"\n]*)\3/g;
// import("./a") and require("./a")
const CALL_IMPORT_RE = /\b(?:import|require)\s*\(\s*(['"])(\.{1,2}\/[^'"\n]*|\.{1,2})\1\s*\)/g;

/** Relative module specifiers of one source text, in order of appearance. Lines that are only a comment are ignored. */
export function relativeSpecifiers(text) {
  const code = text.split('\n').filter(line => !/^\s*(?:\/\/|\/\*|\*)/.test(line)).join('\n');
  const found = [];
  for (const m of code.matchAll(STATIC_IMPORT_RE)) found.push(m[2] ?? m[4]);
  for (const m of code.matchAll(CALL_IMPORT_RE)) found.push(m[2]);
  return found;
}

async function resolveSpecifier(fromAbs, specifier, srcDir) {
  const base = path.resolve(path.dirname(fromAbs), specifier);
  const candidates = [];
  for (const ext of RESOLVE_EXTENSIONS) candidates.push(base + ext);
  for (const ext of RESOLVE_EXTENSIONS.slice(1)) candidates.push(path.join(base, 'index' + ext));
  for (const candidate of candidates) {
    const stat = await fs.stat(candidate).catch(() => null);
    if (!stat || !stat.isFile()) continue;
    if (!candidate.startsWith(srcDir + path.sep)) throw new Error(`import "${specifier}" in ${path.relative(srcDir, fromAbs)} resolves outside the composer src folder: ${candidate}`);
    return candidate;
  }
  throw new Error(`import "${specifier}" in ${path.relative(srcDir, fromAbs)} cannot be resolved to a file`);
}

/**
 * Every file under composer/src that the V4 entry transitively imports, plus the entry itself, as sorted
 * composer-relative paths ("src/..."). Only relative specifiers are followed (node_modules packages are covered by the
 * package-lock hash and the remotion version). A specifier that cannot be resolved, or resolves outside src/, throws:
 * the closure must never silently miss a file.
 * @returns {Promise<string[]>}
 */
export async function computeImportClosure({composerDir, entryRel = ENTRY_REL}) {
  const root = path.resolve(composerDir);
  const srcDir = path.join(root, 'src');
  const seen = new Set();
  const queue = [path.join(root, ...entryRel.split('/'))];
  while (queue.length) {
    const file = queue.pop();
    if (seen.has(file)) continue;
    let text;
    try { text = await fs.readFile(file, 'utf8'); } catch (error) { throw new Error(`cannot read ${path.relative(root, file)}: ${error.code ?? error.message}`); }
    seen.add(file);
    if (!CODE_EXTENSIONS.has(path.extname(file))) continue;
    for (const specifier of relativeSpecifiers(text)) queue.push(await resolveSpecifier(file, specifier, srcDir));
  }
  return [...seen].map(f => path.relative(root, f).split(path.sep).join('/')).sort();
}

/**
 * Code part of the bundle key: sha256 over every file of the entry's import closure (relpath + hash),
 * the package-lock hash and the installed remotion version. Files of other pipelines under src/ (Root.tsx, other
 * compositions) are not part of the V4 bundle and therefore not part of the key.
 */
export async function computeBundleCodeKey({composerDir}) {
  const parts = [];
  for (const rel of await computeImportClosure({composerDir})) {
    parts.push(`${rel}\t${await sha256File(path.join(composerDir, ...rel.split('/')))}`);
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
 * path of the first mismatch ("sourceHashes.src/YtNewsStyle01V4.tsx", "mediaDigest.digest", "frames", ...) or
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
