#!/usr/bin/env python3
"""Integrity lock for the gate files of this skill.

gates_lock.py write  --skill-dir S [--external REPO_REL ...] --repo-root W --out S/scripts/gates.lock.json
  (always locks the files printed by `gate_integrity.mjs --list-external` too; refuses when that command fails or the skill
  tree holds a file git does not track or ignores)
gates_lock.py verify --skill-dir S --repo-root W [--mirror DIR ...] [--require-external REPO_REL ...]

verify() returns a list of problem strings ("<code>: detail"); an empty list means the skill dir (and every
mirror) matches the lock, the lock matches HEAD, and every locked file matches HEAD. Fail-closed: no git,
no lock, a symlink or an unexpected file is a problem. Every path printed by
`gate_integrity.mjs --list-external` (or of the required_external argument, which replaces it when given) must appear under the lock's "external" map ("external-not-locked") - a lock that does not cover the engine file
is refused even when everything it does list is intact.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

SCHEMA = 'yt-news-v4-gates-lock'
VERSION = 1
LOCK_REL = 'scripts/gates.lock.json'
EXCLUDED_DIR_NAMES = {'__pycache__'}
EXCLUDED_REL_DIRS = set()   # tests and fixtures are locked too (they cannot be weakened)
EXCLUDED_FILE_NAMES = {'.DS_Store'}
# The files outside the skill folder (repo-relative) that every lock must cover are NEVER typed here: they are what the
# engine team's own command prints,  node <skill>/scripts/gate_integrity.mjs <repo>/remotion-composer --list-external
# (one repo-relative path per line).  `write` always includes them (plus any extra --external); `verify` and finalize
# refuse a lock that lacks one.  When node, the script or the list is unusable everything fails closed: `write` refuses,
# `verify` reports "tool-missing: ..." (node / script / timeout: finalize exit 4) or "required-external-unavailable: ..."
# (bad or empty list: finalize exit 3).
NODE_BIN = 'node'          # finalize.py sets this to the realpath it resolved once at start
LIST_TIMEOUT = 20
GIT_BIN = 'git'            # finalize.py sets this to the realpath it resolved once at start
GIT_TIMEOUT = 20           # per git call (seconds); a verify() runs ~6 of them, all bounded by the caller's deadline


class GitUnavailable(Exception):
    pass


class RequiredListError(Exception):
    """kind 'tool': node / the script is missing or timed out (infrastructure); kind 'list': the command ran but gave no usable list."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


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


def _tracked_set(repo_root, rels, deadline=None):
    """-> (tracked, tracked_but_ignored): repo-relative posix paths among `rels` that are in the git index / ignored."""
    paths = sorted(rels)
    if not paths:
        return set(), set()
    tracked, ignored = set(), set()
    for args, target in ((('ls-files', '-z', '--cached', '--'), tracked),
                         (('ls-files', '-z', '--cached', '--ignored', '--exclude-standard', '--'), ignored)):
        r = _git(repo_root, *args, *paths, deadline=deadline)
        if r.returncode:
            raise ValueError('git ls-files failed: %s' % r.stderr.decode().strip())
        target.update(x for x in r.stdout.decode().split('\0') if x)
    return tracked, ignored


def check_tracked(skill_dir, repo_root, files, external, deadline=None):
    """A lock may only be written over files git tracks (and does not ignore): returns the offending paths."""
    skill_dir, repo_root = Path(skill_dir).resolve(), Path(repo_root).resolve()
    base = skill_dir.relative_to(repo_root).as_posix()
    rels = {base + '/' + rel: rel for rel in files}
    rels.update({rel: rel for rel in external})
    tracked, ignored = _tracked_set(repo_root, rels, deadline)
    bad = ['%s (%s)' % (p, 'ignored by git' if p in ignored else 'not tracked by git') for p in sorted(rels)
           if p not in tracked or p in ignored]
    return bad


def list_required_external(skill_dir, repo_root, deadline=None):
    """The required external files, as printed by the engine team's `gate_integrity.mjs <composer> --list-external`."""
    script = Path(skill_dir) / 'scripts' / 'gate_integrity.mjs'
    if not script.is_file():
        raise RequiredListError('tool', '%s is missing: cannot list the required external files' % script)
    timeout = LIST_TIMEOUT
    if deadline is not None:
        timeout = min(timeout, deadline - time.monotonic())
        if timeout <= 0:
            raise RequiredListError('tool', 'time budget exhausted before the required external files could be listed')
    env = {k: v for k, v in os.environ.items() if k not in ('NODE_OPTIONS', 'NODE_PATH')}
    try:
        r = subprocess.run([NODE_BIN, str(script), str(Path(repo_root) / 'remotion-composer'), '--list-external'],
                           capture_output=True, timeout=timeout, env=env, cwd=str(repo_root), stdin=subprocess.DEVNULL)
    except FileNotFoundError as e:
        raise RequiredListError('tool', 'node not found: %s' % e)
    except subprocess.TimeoutExpired:
        raise RequiredListError('tool', 'gate_integrity.mjs --list-external timed out after %.0fs' % timeout)
    except OSError as e:
        raise RequiredListError('tool', 'cannot run node: %s' % e)
    if r.returncode != 0:
        raise RequiredListError('list', 'gate_integrity.mjs --list-external exited %d: %s' % (r.returncode, r.stderr.decode(errors='replace')[-300:].strip()))
    lines = [x.strip() for x in r.stdout.decode(errors='replace').splitlines() if x.strip()]
    if not lines:
        raise RequiredListError('list', 'gate_integrity.mjs --list-external printed nothing')
    try:
        return sorted(set(_check_external_rel(x) for x in lines))
    except ValueError as e:
        raise RequiredListError('list', 'gate_integrity.mjs --list-external printed a bad path: %s' % e)


def build_lock(skill_dir, repo_root, external=(), check_git=True, deadline=None, required=None):
    """check_git: refuse (ValueError naming the files) when the skill tree - or an external file - holds a file that git
    does not track or that is ignored: a lock can never be written over junk.  Tracked means in the index (git add)."""
    skill_dir, repo_root = Path(skill_dir), Path(repo_root)
    files, problems = scan(skill_dir)
    if problems:
        raise ValueError('; '.join(problems))
    ext = {}
    # required=None -> what gate_integrity.mjs --list-external prints (fail closed); an explicit list (tests) replaces it
    if required is None:
        try:
            required = list_required_external(skill_dir, repo_root, deadline)
        except RequiredListError as e:
            raise ValueError('refusing to lock: cannot obtain the required external files: %s' % e)
    external = list(required) + list(external)
    for rel in sorted(set(_check_external_rel(e) for e in external)):
        f = repo_root / rel
        if not f.is_file() or f.is_symlink():
            raise ValueError('external file missing or not regular: %s' % rel)
        ext[rel] = sha256_file(f)
    if check_git:
        try:
            bad = check_tracked(skill_dir, repo_root, files, ext, deadline)
        except (GitUnavailable, ValueError, OSError) as e:
            raise ValueError('cannot check that git tracks every file of the skill: %s' % e)
        if bad:
            raise ValueError('refusing to lock: %d file(s) are not tracked by git or are ignored (remove them or git add them): %s'
                             % (len(bad), ', '.join(bad[:20]) + (', ...' if len(bad) > 20 else '')))
    return {'schema': SCHEMA, 'version': VERSION, 'skill': skill_dir.resolve().name, 'files': files, 'external': ext}


def lock_bytes(lock):
    return (json.dumps(lock, indent=2) + '\n').encode()


# ---------------------------------------------------------------- git helpers
def _git_env():
    """No GIT_* from the caller (GIT_DIR, GIT_INDEX_FILE, GIT_WORK_TREE, replace refs ...) except what is set here."""
    return {k: v for k, v in os.environ.items() if not k.startswith('GIT_')} | {'GIT_OPTIONAL_LOCKS': '0', 'GIT_NO_REPLACE_OBJECTS': '1'}


def _git(repo_root, *args, input_bytes=None, deadline=None):
    """deadline: absolute time.monotonic() value; every call is bounded by min(GIT_TIMEOUT, time left)."""
    timeout = GIT_TIMEOUT
    if deadline is not None:
        timeout = min(timeout, deadline - time.monotonic())
        if timeout <= 0:
            raise GitUnavailable('time budget exhausted before git could run')
    try:
        return subprocess.run([GIT_BIN, '-c', 'core.fsmonitor=false', '--literal-pathspecs', '-C', str(repo_root), *args],
                              input=input_bytes, capture_output=True, env=_git_env(), timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        raise GitUnavailable(str(e))


def git_head(repo_root, deadline=None):
    try:
        r = _git(repo_root, 'rev-parse', 'HEAD', deadline=deadline)
    except GitUnavailable:
        return None
    return r.stdout.decode().strip() if r.returncode == 0 else None


def _git_problems(repo_root, entries, deadline=None):
    """entries: {repo-relative posix path: kind} where kind in 'file','lock','external'."""
    problems = []
    try:
        top = _git(repo_root, 'rev-parse', '--show-toplevel', deadline=deadline)
        head = _git(repo_root, 'rev-parse', 'HEAD', deadline=deadline)
        if top.returncode or head.returncode:
            return ['git-unavailable: not a git repository with a HEAD commit (%s)' % (top.stderr or head.stderr).decode().strip()]
        if Path(top.stdout.decode().strip()).resolve() != Path(repo_root).resolve():
            return ['repo-root: --repo-root %s is not the git top level %s' % (repo_root, top.stdout.decode().strip())]
        paths = sorted(entries)
        st = _git(repo_root, 'status', '--porcelain', '--untracked-files=all', '-z', '--', *paths, deadline=deadline)
        if st.returncode:
            return ['git-unavailable: git status failed: %s' % st.stderr.decode().strip()]
        for rec in filter(None, st.stdout.decode().split('\0')):
            problems.append('git-dirty: %s' % rec)
        ls = _git(repo_root, 'ls-tree', '-r', '-z', 'HEAD', '--', *paths, deadline=deadline)
        if ls.returncode:
            return ['git-unavailable: git ls-tree failed: %s' % ls.stderr.decode().strip()]
        blobs = {}
        for rec in filter(None, ls.stdout.decode().split('\0')):
            meta, _, name = rec.partition('\t')
            blobs[name] = meta.split()[2]
        present = [p for p in paths if (Path(repo_root) / p).is_file()]
        hashes = {}
        if present:
            ho = _git(repo_root, 'hash-object', '--stdin-paths', input_bytes=('\n'.join(present) + '\n').encode(), deadline=deadline)
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


def verify(skill_dir, repo_root, mirror_dirs=(), required_external=None, deadline=None):
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
    if required_external is None:
        try:
            required_external = list_required_external(skill_dir, repo_root, deadline)
        except RequiredListError as e:
            problems.append('%s: %s' % ('tool-missing' if e.kind == 'tool' else 'required-external-unavailable', e))
            required_external = ()
    for rel in required_external:
        try:
            wanted = _check_external_rel(rel)
        except ValueError as e:
            problems.append('external-not-locked: %s' % e)
            continue
        if wanted not in lock['external']:
            problems.append('external-not-locked: %s is not listed under "external" in the lock' % wanted)
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
        problems += _git_problems(repo_root, entries, deadline)
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
    v.add_argument('--require-external', action='append', default=[], help='extra to the list printed by gate_integrity.mjs --list-external')
    args = ap.parse_args(argv)
    try:
        if args.cmd == 'write':
            lock = build_lock(args.skill_dir, args.repo_root, args.external)
            Path(args.out).write_bytes(lock_bytes(lock))
            print('wrote %s (%d files, %d external)' % (args.out, len(lock['files']), len(lock['external'])))
            return 0
        try:
            wanted = list_required_external(args.skill_dir, args.repo_root) + args.require_external
        except RequiredListError as e:
            print('%s: %s' % ('tool-missing' if e.kind == 'tool' else 'required-external-unavailable', e))
            print('1 problem(s)')
            return 1
        problems = verify(args.skill_dir, args.repo_root, args.mirror, wanted)
    except (ValueError, OSError) as e:
        print('error: %s' % e, file=sys.stderr)
        return 2
    for p in problems:
        print(p)
    print('OK' if not problems else '%d problem(s)' % len(problems))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
