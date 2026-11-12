#!/usr/bin/env python3
"""Integrity lock for the gate files of this skill.

gates_lock.py write  --skill-dir S [--external REPO_REL ...] --repo-root W --out S/scripts/gates.lock.json
gates_lock.py verify --skill-dir S --repo-root W [--mirror DIR ...]

verify() returns a list of problem strings ("<code>: detail"); an empty list means the skill dir (and every
mirror) matches the lock, the lock matches HEAD, and every locked file matches HEAD. Fail-closed: no git,
no lock, a symlink or an unexpected file is a problem.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

SCHEMA = 'yt-news-v4-gates-lock'
VERSION = 1
LOCK_REL = 'scripts/gates.lock.json'
EXCLUDED_DIR_NAMES = {'__pycache__'}
EXCLUDED_REL_DIRS = set()   # tests and fixtures are locked too (they cannot be weakened)
EXCLUDED_FILE_NAMES = {'.DS_Store'}


class GitUnavailable(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def scan(skill_dir):
    """Return ({posix rel path: sha256}, problems) for every non-excluded regular file."""
    root = Path(skill_dir)
    files, problems = {}, []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        keep = []
        for d in sorted(dirnames):
            rel = d if rel_dir == '.' else rel_dir + '/' + d
            if d in EXCLUDED_DIR_NAMES or rel in EXCLUDED_REL_DIRS:
                continue
            if os.path.islink(os.path.join(dirpath, d)):
                problems.append('symlink: %s' % rel)
                continue
            keep.append(d)
        dirnames[:] = keep
        for name in sorted(filenames):
            rel = name if rel_dir == '.' else rel_dir + '/' + name
            full = os.path.join(dirpath, name)
            if name in EXCLUDED_FILE_NAMES or rel == LOCK_REL:
                continue
            if os.path.islink(full) or not os.path.isfile(full):
                problems.append('symlink: %s (not a regular file)' % rel)
                continue
            files[rel] = sha256_file(full)
    return dict(sorted(files.items())), problems


def _check_external_rel(rel):
    p = Path(rel)
    if p.is_absolute() or '..' in p.parts or not rel:
        raise ValueError('external path must be repo-relative without "..": %s' % rel)
    return p.as_posix()


def build_lock(skill_dir, repo_root, external=()):
    skill_dir, repo_root = Path(skill_dir), Path(repo_root)
    files, problems = scan(skill_dir)
    if problems:
        raise ValueError('; '.join(problems))
    ext = {}
    for rel in sorted(set(_check_external_rel(e) for e in external)):
        f = repo_root / rel
        if not f.is_file() or f.is_symlink():
            raise ValueError('external file missing or not regular: %s' % rel)
        ext[rel] = sha256_file(f)
    return {'schema': SCHEMA, 'version': VERSION, 'skill': skill_dir.resolve().name, 'files': files, 'external': ext}


def lock_bytes(lock):
    return (json.dumps(lock, indent=2) + '\n').encode()


# ---------------------------------------------------------------- git helpers
def _git_env():
    return {k: v for k, v in os.environ.items() if not k.startswith('GIT_')} | {'GIT_OPTIONAL_LOCKS': '0'}


def _git(repo_root, *args, input_bytes=None):
    try:
        return subprocess.run(['git', '--literal-pathspecs', '-C', str(repo_root), *args], input=input_bytes,
                              capture_output=True, env=_git_env(), timeout=120)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        raise GitUnavailable(str(e))


def git_head(repo_root):
    try:
        r = _git(repo_root, 'rev-parse', 'HEAD')
    except GitUnavailable:
        return None
    return r.stdout.decode().strip() if r.returncode == 0 else None


def _git_problems(repo_root, entries):
    """entries: {repo-relative posix path: kind} where kind in 'file','lock','external'."""
    problems = []
    try:
        top = _git(repo_root, 'rev-parse', '--show-toplevel')
        head = _git(repo_root, 'rev-parse', 'HEAD')
        if top.returncode or head.returncode:
            return ['git-unavailable: not a git repository with a HEAD commit (%s)' % (top.stderr or head.stderr).decode().strip()]
        if Path(top.stdout.decode().strip()).resolve() != Path(repo_root).resolve():
            return ['repo-root: --repo-root %s is not the git top level %s' % (repo_root, top.stdout.decode().strip())]
        paths = sorted(entries)
        st = _git(repo_root, 'status', '--porcelain', '--untracked-files=all', '-z', '--', *paths)
        if st.returncode:
            return ['git-unavailable: git status failed: %s' % st.stderr.decode().strip()]
        for rec in filter(None, st.stdout.decode().split('\0')):
            problems.append('git-dirty: %s' % rec)
        ls = _git(repo_root, 'ls-tree', '-r', '-z', 'HEAD', '--', *paths)
        if ls.returncode:
            return ['git-unavailable: git ls-tree failed: %s' % ls.stderr.decode().strip()]
        blobs = {}
        for rec in filter(None, ls.stdout.decode().split('\0')):
            meta, _, name = rec.partition('\t')
            blobs[name] = meta.split()[2]
        present = [p for p in paths if (Path(repo_root) / p).is_file()]
        hashes = {}
        if present:
            ho = _git(repo_root, 'hash-object', '--stdin-paths', input_bytes=('\n'.join(present) + '\n').encode())
            if ho.returncode:
                return ['git-unavailable: git hash-object failed: %s' % ho.stderr.decode().strip()]
            out = ho.stdout.decode().split()
            if len(out) != len(present):
                return ['git-unavailable: unexpected hash-object output']
            hashes = dict(zip(present, out))
        for p in paths:
            kind = entries[p]
            if p not in blobs:
                problems.append(('lock-not-in-head: %s' if kind == 'lock' else 'not-in-head: %s') % p)
            elif p in hashes and hashes[p] != blobs[p]:
                problems.append(('lock-differs-from-head: %s' if kind == 'lock' else 'differs-from-head: %s') % p)
    except GitUnavailable as e:
        problems.append('git-unavailable: %s' % e)
    return problems


def _compare(label, skill_dir, lock):
    problems = []
    files, scan_problems = scan(skill_dir)
    problems += ['%s%s' % (label, p) for p in scan_problems]
    locked = lock['files']
    for rel in sorted(set(locked) | set(files)):
        if rel not in files:
            problems.append('file-missing: %s%s' % (label, rel))
        elif rel not in locked:
            problems.append('file-extra: %s%s' % (label, rel))
        elif files[rel] != locked[rel]:
            problems.append('file-changed: %s%s' % (label, rel))
    return problems


def verify(skill_dir, repo_root, mirror_dirs=()):
    skill_dir, repo_root = Path(skill_dir).resolve(), Path(repo_root).resolve()
    mirror_dirs = [Path(m).resolve() for m in mirror_dirs]
    lock_path = skill_dir / LOCK_REL
    if not lock_path.is_file() or lock_path.is_symlink():
        return ['lock-missing: %s' % lock_path]
    raw = lock_path.read_bytes()
    try:
        lock = json.loads(raw)
        if (lock.get('schema'), lock.get('version')) != (SCHEMA, VERSION) or not isinstance(lock.get('files'), dict) \
                or not isinstance(lock.get('external'), dict):
            raise ValueError('wrong schema/shape')
        for rel in lock['external']:
            _check_external_rel(rel)
        for rel in lock['files']:
            if Path(rel).is_absolute() or '..' in Path(rel).parts:
                raise ValueError('bad path ' + rel)
    except (ValueError, AttributeError) as e:
        return ['lock-invalid: %s' % e]
    problems = []
    if lock.get('skill') != skill_dir.name:
        problems.append('skill-name-mismatch: lock says %r, directory is %r' % (lock.get('skill'), skill_dir.name))
    problems += _compare('', skill_dir, lock)
    for m in mirror_dirs:
        label = '[mirror %s] ' % m
        if not m.is_dir():
            problems.append('mirror-missing: %s' % m)
            continue
        ml = m / LOCK_REL
        if not ml.is_file() or ml.is_symlink() or ml.read_bytes() != raw:
            problems.append('mirror-lock-differs: %s' % ml)
        problems += _compare(label, m, lock)
    for rel, digest in lock['external'].items():
        f = repo_root / rel
        if not f.is_file() or f.is_symlink():
            problems.append('external-missing: %s' % rel)
        elif sha256_file(f) != digest:
            problems.append('external-changed: %s' % rel)
    entries = {}
    for d in [skill_dir] + mirror_dirs:
        try:
            base = d.relative_to(repo_root).as_posix()
        except ValueError:
            problems.append('repo-root: %s is outside --repo-root %s' % (d, repo_root))
            continue
        entries[base + '/' + LOCK_REL] = 'lock'
        for rel in lock['files']:
            entries[base + '/' + rel] = 'file'
    for rel in lock['external']:
        entries[rel] = 'external'
    if entries:
        problems += _git_problems(repo_root, entries)
    return problems


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    w = sub.add_parser('write')
    w.add_argument('--skill-dir', required=True)
    w.add_argument('--repo-root', required=True)
    w.add_argument('--external', action='append', default=[])
    w.add_argument('--out', required=True)
    v = sub.add_parser('verify')
    v.add_argument('--skill-dir', required=True)
    v.add_argument('--repo-root', required=True)
    v.add_argument('--mirror', action='append', default=[])
    args = ap.parse_args(argv)
    try:
        if args.cmd == 'write':
            lock = build_lock(args.skill_dir, args.repo_root, args.external)
            Path(args.out).write_bytes(lock_bytes(lock))
            print('wrote %s (%d files, %d external)' % (args.out, len(lock['files']), len(lock['external'])))
            return 0
        problems = verify(args.skill_dir, args.repo_root, args.mirror)
    except (ValueError, OSError) as e:
        print('error: %s' % e, file=sys.stderr)
        return 2
    for p in problems:
        print(p)
    print('OK' if not problems else '%d problem(s)' % len(problems))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
