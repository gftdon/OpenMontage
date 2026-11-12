#!/usr/bin/env node
// Integrity checks that must hold before the layout gate, the stills or a final render run.
//
//   engine-drift       composer src/YtNewsStyle01V4.tsx must be byte-identical to the skill's reference
//   root-registration  composer src/Root.tsx must register the engine exactly once, in the expected form
//   gates-lock         every file listed in <skill>/scripts/gates.lock.json must match its recorded sha256
//                      (a missing lock file is only the warning "gates-lock-missing")
//
// (gate-spec section 7 check 3, captions-module-drift, is intentionally not implemented here.)
//
// CLI: node gate_integrity.mjs <composer-dir> [--json] [--skill-dir <dir>]
//   exit 0 ok, 3 failed, 2 usage error
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {sha256File} from './qc_manifest.mjs';

const ENGINE_FILE = 'YtNewsStyle01V4.tsx';
const REFERENCE_FILE = 'YtNewsStyle01V4.reference.tsx';
const ROOT_IMPORT_LINE = 'import { YtNewsStyle01V4, calculateYtNewsStyle01V4Metadata } from "./YtNewsStyle01V4";';
const COMPOSITION_RE = /<Composition\s+id="YtNewsStyle01V4"\s+component=\{YtNewsStyle01V4\}[^>]*calculateMetadata=\{calculateYtNewsStyle01V4Metadata\}[^>]*\/>/g;
const COMPOSITION_ID_RE = /\bid\s*=\s*\{?\s*["'`]YtNewsStyle01V4["'`]/g;
const ENGINE_SPECIFIER_RE = /["']\.\/YtNewsStyle01V4[^"']*["']/g;

const count = (text, regex) => (text.match(regex) ?? []).length;

async function checkEngine({composerDir, skillDir}) {
  const engine = path.join(composerDir, 'src', ENGINE_FILE);
  const reference = path.join(skillDir, 'assets', REFERENCE_FILE);
  const hashes = [];
  for (const file of [engine, reference]) {
    try { hashes.push(await sha256File(file)); } catch (error) {
      return [{id: 'engine-drift', message: `cannot read ${file}: ${error.code ?? error.message}`}];
    }
  }
  if (hashes[0] === hashes[1]) return [];
  return [{id: 'engine-drift', message: `${engine} differs from ${reference} (sha256 ${hashes[0].slice(0, 12)} vs ${hashes[1].slice(0, 12)})`}];
}

async function checkRoot({composerDir}) {
  const file = path.join(composerDir, 'src', 'Root.tsx');
  let text;
  try { text = await fs.readFile(file, 'utf8'); } catch (error) {
    return [{id: 'root-registration', message: `cannot read ${file}: ${error.code ?? error.message}`}];
  }
  const issues = [];
  const problem = message => issues.push({id: 'root-registration', message});

  const importLines = text.split('\n').filter(line => line.trim() === ROOT_IMPORT_LINE).length;
  if (importLines !== 1) problem(`Root.tsx must contain the engine import line exactly once (found ${importLines})`);

  // Any other mention of "./YtNewsStyle01V4*" (second import, alias, copy module, re-export, dynamic import).
  const specifiers = count(text, ENGINE_SPECIFIER_RE);
  if (specifiers !== 1) problem(`Root.tsx must reference "./YtNewsStyle01V4*" exactly once (found ${specifiers})`);

  const compositions = count(text, COMPOSITION_RE);
  if (compositions !== 1) problem(`Root.tsx must contain exactly one <Composition id="YtNewsStyle01V4" component={YtNewsStyle01V4} ... calculateMetadata={calculateYtNewsStyle01V4Metadata} /> (found ${compositions})`);

  const ids = count(text, COMPOSITION_ID_RE);
  if (ids !== 1) problem(`Root.tsx must use the id "YtNewsStyle01V4" exactly once (found ${ids})`);
  return issues;
}

/**
 * Accept the lock formats we can reasonably expect (the lock itself is produced elsewhere):
 *   {files: {"scripts/x.mjs": "<sha>"}}                    {files: {"scripts/x.mjs": {sha256: "<sha>"}}}
 *   {files: [{path, sha256}]}                              {"scripts/x.mjs": "<sha>"}   (flat map)
 * Returns [[relativePath, sha256], ...] or null when the shape is not understood.
 */
function lockEntries(lock) {
  if (!lock || typeof lock !== 'object') return null;
  const body = lock.files ?? lock.hashes ?? lock.locked ?? lock;
  if (Array.isArray(body)) {
    const list = body.map(item => [item?.path ?? item?.file, item?.sha256 ?? item?.hash]);
    return list.every(([p, h]) => typeof p === 'string' && typeof h === 'string') ? list : null;
  }
  if (typeof body !== 'object') return null;
  const list = Object.entries(body).filter(([, v]) => typeof v === 'string' || (v && typeof v === 'object' && 'sha256' in v))
    .map(([p, v]) => [p, typeof v === 'string' ? v : v.sha256]);
  const hasOnlyMeta = list.length === 0;
  return hasOnlyMeta ? null : list;
}

async function checkGatesLock({skillDir}) {
  const lockFile = path.join(skillDir, 'scripts', 'gates.lock.json');
  let raw;
  try { raw = await fs.readFile(lockFile, 'utf8'); } catch (error) {
    if (error.code === 'ENOENT') return {issues: [], warnings: [{id: 'gates-lock-missing', message: `${lockFile} does not exist yet; lock not enforced`}]};
    return {issues: [{id: 'gates-lock', message: `cannot read ${lockFile}: ${error.code ?? error.message}`}], warnings: []};
  }
  let entries;
  try { entries = lockEntries(JSON.parse(raw)); } catch { entries = null; }
  if (!entries) return {issues: [{id: 'gates-lock', message: `${lockFile} is not valid or has an unrecognised format`}], warnings: []};

  const issues = [];
  for (const [rel, expected] of entries) {
    const abs = path.resolve(skillDir, rel);
    if (!abs.startsWith(path.resolve(skillDir) + path.sep)) {
      issues.push({id: 'gates-lock', message: `locked path escapes the skill directory: ${rel}`});
      continue;
    }
    let actual;
    try { actual = await sha256File(abs); } catch {
      issues.push({id: 'gates-lock', message: `locked file missing: ${rel}`});
      continue;
    }
    if (actual !== expected) issues.push({id: 'gates-lock', message: `locked file changed: ${rel}`});
  }
  return {issues, warnings: []};
}

/**
 * Run every integrity check.
 * @returns {Promise<{ok: boolean, issues: {id: string, message: string}[], warnings: {id: string, message: string}[]}>}
 */
export async function checkIntegrity({composerDir, skillDir}) {
  const composer = path.resolve(composerDir);
  const skill = path.resolve(skillDir);
  const lock = await checkGatesLock({skillDir: skill});
  const issues = [
    ...await checkEngine({composerDir: composer, skillDir: skill}),
    ...await checkRoot({composerDir: composer}),
    ...lock.issues,
  ];
  return {ok: issues.length === 0, issues, warnings: lock.warnings};
}

const USAGE = 'usage: node gate_integrity.mjs <composer-dir> [--json] [--skill-dir <dir>]';

export async function main(argv) {
  let composer;
  let json = false;
  let skillDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--json') json = true;
    else if (argv[i] === '--skill-dir') skillDir = path.resolve(argv[++i] ?? '');
    else if (!argv[i].startsWith('--') && !composer) composer = argv[i];
    else { console.error(USAGE); return 2; }
  }
  if (!composer) { console.error(USAGE); return 2; }
  const result = await checkIntegrity({composerDir: composer, skillDir});
  if (json) console.log(JSON.stringify(result, null, 2));
  else {
    for (const w of result.warnings) console.log(`GATE_INTEGRITY WARNING ${w.id}: ${w.message}`);
    for (const i of result.issues) console.log(`GATE_INTEGRITY ISSUE ${i.id}: ${i.message}`);
    console.log(result.ok ? 'GATE_INTEGRITY OK' : `GATE_INTEGRITY FAILED ${[...new Set(result.issues.map(i => i.id))].join(',')}`);
  }
  return result.ok ? 0 : 3;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).then(code => { process.exitCode = code; }, error => { console.error(error); process.exitCode = 2; });
}
