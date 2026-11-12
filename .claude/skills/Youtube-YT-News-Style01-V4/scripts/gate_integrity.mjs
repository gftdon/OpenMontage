#!/usr/bin/env node
// Integrity checks that must hold before the layout gate, the stills or a final render run.
//
//   engine-drift       composer src/YtNewsStyle01V4.tsx must be byte-identical to the skill's reference
//   entry-drift        composer src/ytNewsStyle01V4.entry.tsx must be byte-identical to assets/ytNewsStyle01V4.entry.reference.tsx
//   entry-registration the entry registers exactly one composition (id "YtNewsStyle01V4", the engine and its metadata function)
//   entry-closure      the entry's import closure (relative imports, transitively) contains only V4-owned files (V4_OWNED_FILES)
//   (Root.tsx / index.tsx are not looked at: V4 bundles from its own entry, so other pipelines' edits cannot change a V4 render.)
//   gates-lock-format  <skill>/scripts/gates.lock.json has the one accepted shape (see LOCK SHAPE below) or it is invalid
//   gates-lock         every file listed in the lock must exist and match its recorded sha256
//   gates-lock-missing no lock file: only a warning (lock.status "missing"), an issue with requireLock / --require-lock
//
// LOCK SHAPE (the only accepted one, written by another team):
//   {"schema":"yt-news-v4-gates-lock","version":1,"skill":"Youtube-YT-News-Style01-V4","files":{"<path relative to the skill folder>":"<sha256 hex>"},
//    "external":{"<path relative to the repo root>":"<sha256 hex>"}}        ("external" is optional; the writer, gates_lock.py, always emits it)
//   The lock file itself and anything under __pycache__ are never listed in "files". External files live outside the skill folder
//   (e.g. remotion-composer/src/YtNewsStyle01V4.tsx); the repo root is three levels above the skill folder
//   (<repo>/.agents/skills/<skill> or <repo>/.claude/skills/<skill>).
//
// Compared with gates_lock.py verify(): this check only looks at the files the lock LISTS. It does not flag files that are on disk but
// not listed ("file-extra"), symlinks, git state (dirty / differs from HEAD) or mirrors, and it requires the skill name to be
// "Youtube-YT-News-Style01-V4" instead of the directory name. It is stricter on the lock's own format (hex digests, backslash/NUL/empty paths,
// the lock file and __pycache__ not being listed, no unknown top-level key).
//

// (gate-spec section 7 check 3, captions-module-drift, is intentionally not implemented here.)
//
// checkIntegrity() returns {ok, issues, warnings, lock: {status: "ok"|"missing"|"invalid"|"mismatch", sha256, files}}.
//
// CLI: node gate_integrity.mjs <composer-dir> [--json] [--skill-dir <dir>] [--require-lock]
//      node gate_integrity.mjs --list-external      prints EXTERNAL_LOCK_FILES, one repo-relative path per line (for the lock writer)
//   exit 0 ok, 3 failed, 2 usage error
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {
  ENGINE_REFERENCE_FILE, ENGINE_REL, ENTRY_REFERENCE_FILE, ENTRY_REL, COMPOSITION_ID, computeImportClosure, sha256File, sha256Hex,
} from './qc_manifest.mjs';

const ENGINE_FILE = path.posix.basename(ENGINE_REL);

/** Composer-relative files the entry's import closure may contain: the engine, the entry itself and the two sample JSONs (its default props). */
export const V4_OWNED_FILES = Object.freeze([
  ENGINE_REL, ENTRY_REL, 'src/ytNewsStyle01V4Sample.json', 'src/ytNewsStyle01V4SampleCaptions.json',
]);

/**
 * Repo-relative paths (the repo root is three levels above the skill folder) that the gates lock must pin in its "external"
 * section: exactly the composer files a V4 render is built from. The lock writer reads this list (--list-external).
 */
export const EXTERNAL_LOCK_FILES = Object.freeze(V4_OWNED_FILES.map(rel => `remotion-composer/${rel}`));

const count = (text, regex) => (text.match(regex) ?? []).length;

async function checkCopy({id, label, file, reference}) {
  const hashes = [];
  for (const f of [file, reference]) {
    try { hashes.push(await sha256File(f)); } catch (error) {
      return [{id, message: `cannot read ${f}: ${error.code ?? error.message}`}];
    }
  }
  if (hashes[0] === hashes[1]) return [];
  return [{id, message: `${label} ${file} differs from ${reference} (sha256 ${hashes[0].slice(0, 12)} vs ${hashes[1].slice(0, 12)})`}];
}

const checkEngine = ({composerDir, skillDir}) => checkCopy({
  id: 'engine-drift', label: 'engine', file: path.join(composerDir, 'src', ENGINE_FILE), reference: path.join(skillDir, 'assets', ENGINE_REFERENCE_FILE),
});

async function checkEntry({composerDir, skillDir}) {
  const file = path.join(composerDir, ...ENTRY_REL.split('/'));
  const drift = await checkCopy({id: 'entry-drift', label: 'entry', file, reference: path.join(skillDir, 'assets', ENTRY_REFERENCE_FILE)});
  const issues = [...drift];
  let text;
  try { text = await fs.readFile(file, 'utf8'); } catch (error) {
    return drift.length ? issues : [{id: 'entry-drift', message: `cannot read ${file}: ${error.code ?? error.message}`}];
  }
  // Registration: strip whole-line comments, then count.
  const code = text.split('\n').filter(line => !/^\s*(?:\/\/|\/\*|\*)/.test(line)).join('\n');
  const problem = message => issues.push({id: 'entry-registration', message});
  const registerRoots = count(code, /\bregisterRoot\s*\(/g);
  if (registerRoots !== 1) problem(`the entry must call registerRoot exactly once (found ${registerRoots})`);
  const compositions = count(code, /<Composition\b/g);
  if (compositions !== 1) problem(`the entry must register exactly one <Composition> (found ${compositions})`);
  const ids = [...code.matchAll(/<Composition\b[^>]*?\bid\s*=\s*\{?\s*["'`]([^"'`]*)["'`]/g)].map(m => m[1]);
  if (ids.length !== 1 || ids[0] !== COMPOSITION_ID) problem(`the entry's only composition id must be "${COMPOSITION_ID}" (found ${ids.length ? ids.map(i => `"${i}"`).join(', ') : 'none'})`);
  if (count(code, /\bcomponent=\{YtNewsStyle01V4\}/g) !== 1) problem('the composition must use component={YtNewsStyle01V4}');
  if (count(code, /\bcalculateMetadata=\{calculateYtNewsStyle01V4Metadata\}/g) !== 1) problem('the composition must use calculateMetadata={calculateYtNewsStyle01V4Metadata}');

  // Closure: only V4-owned files.
  let closure;
  try { closure = await computeImportClosure({composerDir}); } catch (error) {
    issues.push({id: 'entry-closure', message: `cannot compute the entry's import closure: ${error.message}`});
    return issues;
  }
  const foreign = closure.filter(rel => !V4_OWNED_FILES.includes(rel));
  if (foreign.length) issues.push({id: 'entry-closure', message: `the entry imports files that are not V4-owned: ${listPaths(foreign, 'file(s)')} (allowed: ${V4_OWNED_FILES.join(', ')})`});
  return issues;
}

export const LOCK_SCHEMA = 'yt-news-v4-gates-lock';
export const LOCK_SKILL = 'Youtube-YT-News-Style01-V4';
export const LOCK_RELATIVE_PATH = 'scripts/gates.lock.json';
const HEX_SHA256 = /^[0-9a-f]{64}$/;
const LOCK_KEYS = ['schema', 'version', 'skill', 'files', 'external'];
const MAX_LISTED = 10;

const listPaths = (paths, noun) => {
  const shown = paths.slice(0, MAX_LISTED).join(', ');
  return `${paths.length} ${noun}: ${shown}${paths.length > MAX_LISTED ? `, ... (+${paths.length - MAX_LISTED} more)` : ''}`;
};

/** Repo root = three levels above the skill folder (<repo>/.agents/skills/<skill> or <repo>/.claude/skills/<skill>). */
const repoRootOf = skillDir => path.resolve(skillDir, '..', '..', '..');

/** Why a lock path is not acceptable, or null. Paths use "/"; `base` is the skill folder ("files") or the repo root ("external"). */
function badLockPath(rel, base, what = 'skill folder') {
  if (rel === '') return 'empty path';
  if (path.isAbsolute(rel) || path.win32.isAbsolute(rel)) return 'absolute path';
  if (rel.includes('\\') || rel.includes('\0')) return 'path contains a backslash or NUL';
  if (rel.split('/').includes('..')) return 'path contains a ".." segment';
  const abs = path.resolve(base, rel);
  if (!abs.startsWith(path.resolve(base) + path.sep)) return `path escapes the ${what}`;
  return null;
}

/** Extra rules for "files" entries. */
function badFilesPath(rel, skillDir) {
  const generic = badLockPath(rel, skillDir);
  if (generic) return generic;
  const abs = path.resolve(skillDir, rel);
  if (path.relative(skillDir, abs) === path.join('scripts', 'gates.lock.json')) return 'the lock file cannot list itself';
  if (rel.split('/').includes('__pycache__')) return '__pycache__ is never locked';
  return null;
}

/** Validate the one accepted shape. Returns a list of problems (empty = fine). */
function lockShapeProblems(lock, skillDir) {
  if (lock === null || typeof lock !== 'object' || Array.isArray(lock)) return ['the lock must be a JSON object'];
  const problems = [];
  for (const key of Object.keys(lock)) if (!LOCK_KEYS.includes(key)) problems.push(`unknown key "${key}"`);
  if (lock.schema !== LOCK_SCHEMA) problems.push(`schema must be "${LOCK_SCHEMA}"`);
  if (lock.version !== 1) problems.push('version must be 1');
  if (lock.skill !== LOCK_SKILL) problems.push(`skill must be "${LOCK_SKILL}"`);
  const files = lock.files;
  if (files === null || typeof files !== 'object' || Array.isArray(files)) {
    problems.push('files must be an object {path: sha256}');
    return problems;
  }
  for (const [rel, hash] of Object.entries(files)) {
    if (typeof hash !== 'string' || !HEX_SHA256.test(hash)) { problems.push(`${rel}: value must be a lowercase 64-character sha256 hex string`); continue; }
    const bad = badFilesPath(rel, skillDir);
    if (bad) problems.push(`${rel}: ${bad}`);
  }
  if (lock.external !== undefined) {
    const external = lock.external;
    if (external === null || typeof external !== 'object' || Array.isArray(external)) { problems.push('external must be an object {repo-relative path: sha256}'); return problems; }
    for (const [rel, hash] of Object.entries(external)) {
      if (typeof hash !== 'string' || !HEX_SHA256.test(hash)) { problems.push(`external ${rel}: value must be a lowercase 64-character sha256 hex string`); continue; }
      const bad = badLockPath(rel, repoRootOf(skillDir), 'repo');
      if (bad) problems.push(`external ${rel}: ${bad}`);
    }
  }
  return problems;
}

async function checkGatesLock({skillDir, requireLock}) {
  const lockFile = path.join(skillDir, ...LOCK_RELATIVE_PATH.split('/'));
  const result = (status, sha256, files, issues = [], warnings = [], external = null) => ({issues, warnings, lock: {status, sha256, files, external}});
  let raw;
  try { raw = await fs.readFile(lockFile); } catch (error) {
    if (error.code === 'ENOENT') {
      const message = `${lockFile} does not exist`;
      return requireLock
        ? result('missing', null, null, [{id: 'gates-lock-missing', message: `${message}; a lock is required`}])
        : result('missing', null, null, [], [{id: 'gates-lock-missing', message: `${message}; lock not enforced`}]);
    }
    return result('invalid', null, null, [{id: 'gates-lock-format', message: `cannot read ${lockFile}: ${error.code ?? error.message}`}]);
  }
  const sha256 = sha256Hex(raw);
  let lock;
  try { lock = JSON.parse(raw.toString('utf8')); } catch (error) {
    return result('invalid', sha256, null, [{id: 'gates-lock-format', message: `${lockFile} is not valid JSON: ${error.message}`}]);
  }
  const problems = lockShapeProblems(lock, skillDir);
  if (problems.length) return result('invalid', sha256, null, [{id: 'gates-lock-format', message: `${lockFile}: ${listPaths(problems, 'problem(s)')}`}]);

  const entries = Object.entries(lock.files);
  const externalEntries = Object.entries(lock.external ?? {});
  const repoRoot = repoRootOf(skillDir);
  const bad = [];
  for (const [rel, expected] of entries) {
    let actual;
    try { actual = await sha256File(path.resolve(skillDir, rel)); } catch { bad.push(`${rel} (missing)`); continue; }
    if (actual !== expected) bad.push(`${rel} (changed)`);
  }
  for (const [rel, expected] of externalEntries) {
    let actual;
    try { actual = await sha256File(path.resolve(repoRoot, rel)); } catch { bad.push(`external:${rel} (missing)`); continue; }
    if (actual !== expected) bad.push(`external:${rel} (changed)`);
  }
  if (bad.length) return result('mismatch', sha256, entries.length, [{id: 'gates-lock', message: listPaths(bad, 'locked file(s) missing or changed')}], [], externalEntries.length);
  return result('ok', sha256, entries.length, [], [], externalEntries.length);
}

/**
 * Run every integrity check.
 * @param {{composerDir: string, skillDir: string, requireLock?: boolean}} options
 *   requireLock: a missing lock file is the issue "gates-lock-missing" instead of a warning.
 * @returns {Promise<{ok: boolean, issues: {id: string, message: string}[], warnings: {id: string, message: string}[],
 *   lock: {status: 'ok'|'missing'|'invalid'|'mismatch', sha256: string|null, files: number|null, external: number|null}}>}
 *   lock.files = number of "files" entries, lock.external = number of "external" entries (0 when absent); both null when there is no usable lock.
 */
export async function checkIntegrity({composerDir, skillDir, requireLock = false}) {
  const composer = path.resolve(composerDir);
  const skill = path.resolve(skillDir);
  const lock = await checkGatesLock({skillDir: skill, requireLock});
  const issues = [
    ...await checkEngine({composerDir: composer, skillDir: skill}),
    ...await checkEntry({composerDir: composer, skillDir: skill}),
    ...lock.issues,
  ];
  return {ok: issues.length === 0, issues, warnings: lock.warnings, lock: lock.lock};
}

const USAGE = 'usage: node gate_integrity.mjs <composer-dir> [--json] [--skill-dir <dir>] [--require-lock]\n       node gate_integrity.mjs --list-external';

export async function main(argv) {
  let composer;
  let json = false;
  let requireLock = false;
  let skillDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--list-external') { console.log(EXTERNAL_LOCK_FILES.join('\n')); return 0; }
    else if (argv[i] === '--json') json = true;
    else if (argv[i] === '--require-lock') requireLock = true;
    else if (argv[i] === '--skill-dir') skillDir = path.resolve(argv[++i] ?? '');
    else if (!argv[i].startsWith('--') && !composer) composer = argv[i];
    else { console.error(USAGE); return 2; }
  }
  if (!composer) { console.error(USAGE); return 2; }
  const result = await checkIntegrity({composerDir: composer, skillDir, requireLock});
  if (json) console.log(JSON.stringify(result, null, 2));
  else {
    for (const w of result.warnings) console.log(`GATE_INTEGRITY WARNING ${w.id}: ${w.message}`);
    for (const i of result.issues) console.log(`GATE_INTEGRITY ISSUE ${i.id}: ${i.message}`);
    console.log(`GATE_INTEGRITY LOCK ${result.lock.status}`);
    console.log(result.ok ? 'GATE_INTEGRITY OK' : `GATE_INTEGRITY FAILED ${[...new Set(result.issues.map(i => i.id))].join(',')}`);
  }
  return result.ok ? 0 : 3;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).then(code => { process.exitCode = code; }, error => { console.error(error); process.exitCode = 2; });
}
