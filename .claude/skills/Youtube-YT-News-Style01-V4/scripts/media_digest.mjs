// Media digest (method "sha256-per-file-v1") and the staging public directory used for bundling.
//
// digestDir(dir): for every file under dir (recursive, dotfiles and dot-directories excluded) compute
// a streaming sha256; digest = sha256(join(sorted("relpath\tsize\tsha256"), "\n")).
// Hashes are cached by absolute path with {size, mtimeMs, ino, sha256}; a file is re-hashed when any
// of those three differs, so an unchanged tree costs only a stat per file.
//
// stagePublicDir(): Remotion's bundle() copies the whole public/ tree into the bundle. To avoid copying
// other episodes' media (and to key the bundle on exactly what the episode uses) the bundle is built from
// a staging directory that contains only fonts/ and <assetDir>/, made of hardlinks (copy fallback).
import fs from 'node:fs/promises';
import path from 'node:path';
import {randomBytes} from 'node:crypto';
import {sha256File, sha256Hex} from './qc_manifest.mjs';

export const DIGEST_METHOD = 'sha256-per-file-v1';
export const STAGE_MARKER = '.stage-public';

/** Recursive list of regular files (relative posix paths), skipping dotfiles/dot-directories. */
async function listFiles(dir, prefix = '') {
  const found = [];
  for (const entry of await fs.readdir(dir, {withFileTypes: true})) {
    if (entry.name.startsWith('.')) continue;
    const rel = prefix ? prefix + '/' + entry.name : entry.name;
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) found.push(...await listFiles(abs, rel));
    else if (entry.isFile()) found.push(rel);
    else if (entry.isSymbolicLink()) {
      // Follow symlinks to files only (never to directories: no cycles).
      const stat = await fs.stat(abs).catch(() => null);
      if (stat?.isFile()) found.push(rel);
    }
  }
  return found;
}

async function loadCache(cacheFile) {
  if (!cacheFile) return {files: {}};
  try {
    const parsed = JSON.parse(await fs.readFile(cacheFile, 'utf8'));
    if (parsed && parsed.version === 1 && parsed.files && typeof parsed.files === 'object') return parsed;
  } catch { /* missing or corrupt cache: start over */ }
  return {version: 1, files: {}};
}

async function saveCache(cacheFile, cache) {
  await fs.mkdir(path.dirname(cacheFile), {recursive: true});
  const tmp = `${cacheFile}.${process.pid}.${randomBytes(4).toString('hex')}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(cache));
  await fs.rename(tmp, cacheFile);
}

/**
 * Digest a directory tree.
 * @param {string} dir
 * @param {{cacheFile?: string, onHash?: (absPath: string) => void}} [options]
 *        onHash is called for every file that is really read (cache miss) - tests use it as a counter.
 * @returns {Promise<{method: string, digest: string, files: number, bytes: number}>}
 */
export async function digestDir(dir, {cacheFile, onHash} = {}) {
  const root = path.resolve(dir);
  const cache = await loadCache(cacheFile);
  cache.version = 1;
  let dirty = false;
  const lines = [];
  let bytes = 0;
  const rels = (await listFiles(root)).sort();
  for (const rel of rels) {
    const abs = path.join(root, rel);
    const stat = await fs.stat(abs);
    const hit = cache.files[abs];
    let sha;
    if (hit && hit.size === stat.size && hit.mtimeMs === stat.mtimeMs && hit.ino === stat.ino) {
      sha = hit.sha256;
    } else {
      onHash?.(abs);
      sha = await sha256File(abs);
      cache.files[abs] = {size: stat.size, mtimeMs: stat.mtimeMs, ino: stat.ino, sha256: sha};
      dirty = true;
    }
    bytes += stat.size;
    lines.push(`${rel}\t${stat.size}\t${sha}`);
  }
  if (cacheFile && dirty) await saveCache(cacheFile, cache);
  lines.sort();
  return {method: DIGEST_METHOD, digest: sha256Hex(lines.join('\n')), files: rels.length, bytes};
}

function assertSimpleName(name, what) {
  if (typeof name !== 'string' || !name || name.startsWith('.') || name.includes('/') || name.includes('\\') || name.includes('\0') || name === '..') {
    throw new Error(`${what} must be a plain directory name, got ${JSON.stringify(name)}`);
  }
}

/** Mirror srcDir into dstDir with hardlinks (copy when linking fails). Dotfiles are skipped like in digestDir. */
async function mirrorTree(srcDir, dstDir, stats, link) {
  await fs.mkdir(dstDir, {recursive: true});
  for (const entry of await fs.readdir(srcDir, {withFileTypes: true})) {
    if (entry.name.startsWith('.')) continue;
    const src = path.join(srcDir, entry.name);
    const dst = path.join(dstDir, entry.name);
    if (entry.isDirectory()) {
      await mirrorTree(src, dst, stats, link);
      continue;
    }
    const isFile = entry.isFile() || (entry.isSymbolicLink() && (await fs.stat(src).catch(() => null))?.isFile());
    if (!isFile) continue;
    try {
      await link(await fs.realpath(src), dst);
      stats.linked++;
    } catch {
      await fs.copyFile(src, dst);
      stats.copied++;
    }
  }
}

/**
 * Build <stageDir>/fonts and <stageDir>/<assetDir> from composerPublic and digest both.
 * stageDir is rebuilt from scratch on every call; it is only deleted when it is empty/absent or carries
 * our marker file, so a mistyped path never wipes a real directory.
 * @returns {Promise<{dir: string, mediaDigest: object, fontsDigest: object, linked: number, copied: number}>}
 */
export async function stagePublicDir({composerPublic, assetDir, stageDir, cacheFile, onHash, link = fs.link}) {
  assertSimpleName(assetDir, 'assetDir');
  if (assetDir === 'fonts') throw new Error('assetDir must not be "fonts"');
  const publicRoot = path.resolve(composerPublic);
  const stage = path.resolve(stageDir);
  const sources = {assets: path.join(publicRoot, assetDir), fonts: path.join(publicRoot, 'fonts')};
  for (const [label, dir] of Object.entries(sources)) {
    const stat = await fs.stat(dir).catch(() => null);
    if (!stat?.isDirectory()) throw new Error(`public ${label} directory missing: ${dir}`);
  }

  const present = await fs.readdir(stage).catch(() => null);
  if (present && present.length && !present.includes(STAGE_MARKER)) {
    throw new Error(`refusing to reuse non-empty directory that is not a staging dir: ${stage}`);
  }
  await fs.rm(stage, {recursive: true, force: true});
  await fs.mkdir(stage, {recursive: true});
  await fs.writeFile(path.join(stage, STAGE_MARKER), 'staged by media_digest.mjs\n');

  const stats = {linked: 0, copied: 0};
  await mirrorTree(sources.fonts, path.join(stage, 'fonts'), stats, link);
  await mirrorTree(sources.assets, path.join(stage, assetDir), stats, link);

  const mediaDigest = {...(await digestDir(sources.assets, {cacheFile, onHash})), assetDir};
  const fontsDigest = {...(await digestDir(sources.fonts, {cacheFile, onHash})), assetDir: 'fonts'};
  return {dir: stage, mediaDigest, fontsDigest, linked: stats.linked, copied: stats.copied};
}
