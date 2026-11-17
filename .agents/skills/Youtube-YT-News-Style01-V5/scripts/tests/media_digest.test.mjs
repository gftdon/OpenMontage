import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {digestDir, stagePublicDir, DIGEST_METHOD} from '../media_digest.mjs';
import {sha256Hex} from '../qc_manifest.mjs';

async function fixture() {
  const d = await fs.mkdtemp(path.join(os.tmpdir(), 'media-digest-'));
  const pub = path.join(d, 'public');
  await fs.mkdir(path.join(pub, 'ep', 'broll'), {recursive: true});
  await fs.mkdir(path.join(pub, 'fonts'), {recursive: true});
  await fs.mkdir(path.join(pub, 'other'), {recursive: true});
  await fs.writeFile(path.join(pub, 'ep', 'avatar_source.mp4'), 'AVATAR-BYTES');
  await fs.writeFile(path.join(pub, 'ep', 'broll', 'a.mp4'), 'BROLL-A');
  await fs.writeFile(path.join(pub, 'ep', '.DS_Store'), 'junk');
  await fs.writeFile(path.join(pub, 'fonts', 'Kanit.ttf'), 'FONT');
  await fs.writeFile(path.join(pub, 'other', 'secret.mp4'), 'OTHER EPISODE');
  return {d, pub, ep: path.join(pub, 'ep'), cache: path.join(d, 'cache', 'media-hash.json')};
}

test('digest is deterministic, ignores dotfiles and follows the documented formula', async () => {
  const {d, ep} = await fixture();
  try {
    const a = await digestDir(ep);
    const b = await digestDir(ep);
    assert.deepEqual(a, b);
    assert.equal(a.method, DIGEST_METHOD);
    assert.equal(a.method, 'sha256-per-file-v1');
    assert.equal(a.files, 2);
    assert.equal(a.bytes, 'AVATAR-BYTES'.length + 'BROLL-A'.length);
    const lines = [
      `avatar_source.mp4\t${'AVATAR-BYTES'.length}\t${sha256Hex('AVATAR-BYTES')}`,
      `broll/a.mp4\t${'BROLL-A'.length}\t${sha256Hex('BROLL-A')}`,
    ].sort();
    assert.equal(a.digest, sha256Hex(lines.join('\n')));
    // a dotfile changing does not matter
    await fs.writeFile(path.join(ep, '.DS_Store'), 'other junk');
    assert.equal((await digestDir(ep)).digest, a.digest);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('one changed byte (same size) changes the digest', async () => {
  const {d, ep, cache} = await fixture();
  try {
    const target = path.join(ep, 'broll', 'a.mp4');
    const before = await digestDir(ep);
    await fs.writeFile(target, 'BROLL-B'); // same size
    assert.notEqual((await digestDir(ep)).digest, before.digest);
    // adding, renaming or removing a file also changes it
    await fs.writeFile(path.join(ep, 'new.mp4'), 'x');
    assert.notEqual((await digestDir(ep)).digest, before.digest);
    await fs.rm(path.join(ep, 'new.mp4'));
    await fs.rename(target, path.join(ep, 'broll', 'renamed.mp4'));
    assert.notEqual((await digestDir(ep)).digest, before.digest);
    // with a cache too: the byte change is seen as soon as mtime/ino moves
    await fs.rename(path.join(ep, 'broll', 'renamed.mp4'), target);
    const cached = await digestDir(ep, {cacheFile: cache});
    const st = await fs.stat(target);
    await fs.writeFile(target, 'BROLL-C');
    await fs.utimes(target, st.atime, new Date(st.mtimeMs + 5000));
    assert.notEqual((await digestDir(ep, {cacheFile: cache})).digest, cached.digest);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('cache hit avoids re-hashing and is invalidated by size or mtime change', async () => {
  const {d, ep, cache} = await fixture();
  try {
    const hashed = [];
    const onHash = f => hashed.push(path.relative(ep, f));
    const first = await digestDir(ep, {cacheFile: cache, onHash});
    assert.deepEqual(hashed.sort(), ['avatar_source.mp4', 'broll/a.mp4']);
    hashed.length = 0;
    const second = await digestDir(ep, {cacheFile: cache, onHash});
    assert.deepEqual(hashed, []);
    assert.deepEqual(second, first);

    // size change -> re-hash that file only
    await fs.writeFile(path.join(ep, 'broll', 'a.mp4'), 'BROLL-A-LONGER');
    const third = await digestDir(ep, {cacheFile: cache, onHash});
    assert.deepEqual(hashed, ['broll/a.mp4']);
    assert.notEqual(third.digest, first.digest);

    // mtime-only change (same bytes) -> re-hash, same digest
    hashed.length = 0;
    const f = path.join(ep, 'avatar_source.mp4');
    const st = await fs.stat(f);
    await fs.utimes(f, st.atime, new Date(st.mtimeMs + 10_000));
    const fourth = await digestDir(ep, {cacheFile: cache, onHash});
    assert.deepEqual(hashed, ['avatar_source.mp4']);
    assert.equal(fourth.digest, third.digest);

    // corrupt cache is ignored, not fatal
    await fs.writeFile(cache, '{nope');
    hashed.length = 0;
    assert.equal((await digestDir(ep, {cacheFile: cache, onHash})).digest, third.digest);
    assert.equal(hashed.length, 2);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('stagePublicDir contains only fonts and the asset dir, with hardlinks when possible', async () => {
  const {d, pub, ep, cache} = await fixture();
  try {
    const stageDir = path.join(d, 'stage');
    const staged = await stagePublicDir({composerPublic: pub, assetDir: 'ep', stageDir, cacheFile: cache});
    assert.equal(staged.dir, stageDir);
    assert.deepEqual((await fs.readdir(stageDir)).filter(n => !n.startsWith('.')).sort(), ['ep', 'fonts']);
    assert.deepEqual((await fs.readdir(path.join(stageDir, 'ep'))).sort(), ['avatar_source.mp4', 'broll']);
    assert.equal(staged.copied, 0);
    assert.equal(staged.linked, 3);
    const src = await fs.stat(path.join(ep, 'avatar_source.mp4'));
    const dst = await fs.stat(path.join(stageDir, 'ep', 'avatar_source.mp4'));
    assert.equal(dst.ino, src.ino);
    assert.equal(dst.nlink >= 2, true);
    // digests of the stage equal digests of the sources, with the documented shape
    assert.equal((await digestDir(path.join(stageDir, 'ep'))).digest, staged.mediaDigest.digest);
    assert.equal((await digestDir(path.join(stageDir, 'fonts'))).digest, staged.fontsDigest.digest);
    assert.equal(staged.mediaDigest.assetDir, 'ep');
    assert.equal(staged.mediaDigest.method, 'sha256-per-file-v1');
    assert.equal(staged.mediaDigest.files, 2);
    assert.equal(staged.fontsDigest.files, 1);
    // staging again rebuilds cleanly
    const again = await stagePublicDir({composerPublic: pub, assetDir: 'ep', stageDir, cacheFile: cache});
    assert.deepEqual(again.mediaDigest, staged.mediaDigest);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('stagePublicDir falls back to copying when linking fails', async () => {
  const {d, pub} = await fixture();
  try {
    const stageDir = path.join(d, 'stage');
    const staged = await stagePublicDir({composerPublic: pub, assetDir: 'ep', stageDir, link: async () => { throw Object.assign(new Error('cross-device'), {code: 'EXDEV'}); }});
    assert.equal(staged.linked, 0);
    assert.equal(staged.copied, 3);
    assert.equal(await fs.readFile(path.join(stageDir, 'ep', 'broll', 'a.mp4'), 'utf8'), 'BROLL-A');
    assert.equal((await digestDir(path.join(stageDir, 'ep'))).digest, staged.mediaDigest.digest);
  } finally { await fs.rm(d, {recursive: true}); }
});

test('stagePublicDir refuses bad asset names, missing dirs and a non-staging target', async () => {
  const {d, pub} = await fixture();
  try {
    const stageDir = path.join(d, 'stage');
    for (const bad of ['../x', 'a/b', '', '.hidden', 'fonts']) {
      await assert.rejects(stagePublicDir({composerPublic: pub, assetDir: bad, stageDir}), /assetDir/, bad);
    }
    await assert.rejects(stagePublicDir({composerPublic: pub, assetDir: 'nope', stageDir}), /missing/);
    const precious = path.join(d, 'precious');
    await fs.mkdir(precious);
    await fs.writeFile(path.join(precious, 'keep.txt'), 'keep');
    await assert.rejects(stagePublicDir({composerPublic: pub, assetDir: 'ep', stageDir: precious}), /not a staging dir/);
    assert.equal(await fs.readFile(path.join(precious, 'keep.txt'), 'utf8'), 'keep');
  } finally { await fs.rm(d, {recursive: true}); }
});
