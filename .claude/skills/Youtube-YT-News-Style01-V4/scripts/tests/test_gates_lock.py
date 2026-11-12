import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'gates_lock.py'
spec = importlib.util.spec_from_file_location('gates_lock_under_test', SCRIPT)
gl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gl)

NAME = 'FakeSkill'


def sh(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def make_repo(tmp, external=('engine/core.ts',)):
    repo = Path(tmp) / 'repo'
    skill = repo / '.claude' / 'skills' / NAME
    (skill / 'scripts' / 'tests').mkdir(parents=True)
    (skill / 'scripts' / '__pycache__').mkdir()
    (skill / 'references').mkdir()
    (skill / 'SKILL.md').write_text('skill\n')
    (skill / 'scripts' / 'gate.py').write_text('print(1)\n')
    (skill / 'references' / 'a.md').write_text('ref\n')
    (skill / 'scripts' / 'tests' / 'test_x.py').write_text('x\n')
    (skill / 'scripts' / '__pycache__' / 'gate.cpython-312.pyc').write_bytes(b'\0\1')
    (skill / '.DS_Store').write_bytes(b'ds')
    (repo / 'engine').mkdir()
    (repo / 'engine' / 'core.ts').write_text('export {}\n')
    sh(repo, 'git', 'init', '-q')
    sh(repo, 'git', 'config', 'user.email', 't@t')
    sh(repo, 'git', 'config', 'user.name', 't')
    sh(repo, 'git', 'config', 'commit.gpgsign', 'false')
    write_lock(repo, skill, external)
    mirror = repo / '.agents' / 'skills' / NAME
    shutil.copytree(skill, mirror)
    (repo / '.gitignore').write_text('__pycache__/\n.DS_Store\n')
    sh(repo, 'git', 'add', '-A')
    sh(repo, 'git', 'commit', '-q', '-m', 'init')
    return repo, skill, mirror


def write_lock(repo, skill, external=('engine/core.ts',)):
    lock = gl.build_lock(skill, repo, external)
    (skill / 'scripts' / 'gates.lock.json').write_bytes(gl.lock_bytes(lock))
    return lock


def codes(problems):
    return sorted({p.split(':')[0] for p in problems})


class LockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='gates-lock-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo, self.skill, self.mirror = make_repo(self.tmp)

    def verify(self):
        return gl.verify(self.skill, self.repo, [self.mirror])

    def commit(self):
        sh(self.repo, 'git', 'add', '-A')
        sh(self.repo, 'git', 'commit', '-q', '-m', 'c')

    def test_roundtrip_clean_and_excluded_paths(self):
        self.assertEqual([], self.verify())
        lock = json.loads((self.skill / 'scripts' / 'gates.lock.json').read_text())
        # tests and fixtures are locked too; only __pycache__, .DS_Store and the lock itself are excluded
        self.assertEqual(['SKILL.md', 'references/a.md', 'scripts/gate.py', 'scripts/tests/test_x.py'], list(lock['files']))
        self.assertEqual(['engine/core.ts'], list(lock['external']))
        self.assertEqual((NAME, 'yt-news-v4-gates-lock', 1), (lock['skill'], lock['schema'], lock['version']))
        for excluded in ('__pycache__', '.DS_Store', 'gates.lock.json', '.pyc'):
            self.assertFalse(any(excluded in k for k in lock['files']), excluded)
        # excluded paths may change freely
        (self.skill / 'scripts' / '__pycache__' / 'gate.cpython-312.pyc').write_bytes(b'other')
        (self.skill / 'scripts' / 'tests' / '__pycache__').mkdir()
        (self.skill / 'scripts' / 'tests' / '__pycache__' / 'x.pyc').write_bytes(b'x')
        (self.skill / '.DS_Store').write_bytes(b'ds2')
        self.assertEqual([], self.verify())

    def test_tests_and_fixtures_are_locked(self):
        (self.skill / 'scripts' / 'tests' / 'test_x.py').write_text('weakened\n')
        self.assertIn('file-changed', codes(self.verify()))
        (self.skill / 'scripts' / 'tests' / 'test_x.py').write_text('x\n')
        (self.skill / 'scripts' / 'tests' / 'test_new.py').write_text('new\n')
        self.assertIn('file-extra', codes(self.verify()))
        (self.skill / 'scripts' / 'tests' / 'test_new.py').unlink()
        (self.skill / 'scripts' / 'tests' / 'fixtures').mkdir()
        (self.skill / 'scripts' / 'tests' / 'fixtures' / 'f.json').write_text('{}')
        self.assertIn('file-extra', codes(self.verify()))

    def test_lock_is_deterministic(self):
        a = gl.lock_bytes(gl.build_lock(self.skill, self.repo, ['engine/core.ts']))
        b = gl.lock_bytes(gl.build_lock(self.skill, self.repo, ['engine/core.ts']))
        self.assertEqual(a, b)
        self.assertEqual((self.skill / 'scripts' / 'gates.lock.json').read_bytes(), a)

    def test_cli_write_and_verify(self):
        out = self.skill / 'scripts' / 'gates.lock.json'
        r = subprocess.run([sys.executable, str(SCRIPT), 'write', '--skill-dir', str(self.skill), '--repo-root', str(self.repo),
                            '--external', 'engine/core.ts', '--out', str(out)], capture_output=True, text=True)
        self.assertEqual(0, r.returncode, r.stderr)
        r = subprocess.run([sys.executable, str(SCRIPT), 'verify', '--skill-dir', str(self.skill), '--repo-root', str(self.repo),
                            '--mirror', str(self.mirror)], capture_output=True, text=True)
        self.assertEqual(0, r.returncode, r.stdout)
        (self.skill / 'scripts' / 'gate.py').write_text('print(2)\n')
        r = subprocess.run([sys.executable, str(SCRIPT), 'verify', '--skill-dir', str(self.skill), '--repo-root', str(self.repo)],
                           capture_output=True, text=True)
        self.assertEqual(1, r.returncode)
        self.assertIn('file-changed', r.stdout)

    def test_modified_file(self):
        (self.skill / 'scripts' / 'gate.py').write_text('print(2)\n')
        p = self.verify()
        self.assertIn('file-changed', codes(p))
        self.assertIn('git-dirty', codes(p))

    def test_missing_and_extra_file(self):
        (self.skill / 'scripts' / 'gate.py').unlink()
        (self.skill / 'scripts' / 'new.py').write_text('x\n')
        p = self.verify()
        self.assertIn('file-missing', codes(p))
        self.assertIn('file-extra', codes(p))

    def test_extra_pyc_outside_pycache_is_extra(self):
        (self.skill / 'scripts' / 'stray.pyc').write_bytes(b'x')
        self.assertIn('file-extra', codes(self.verify()))

    def test_symlink_is_a_problem(self):
        os.symlink(self.skill / 'SKILL.md', self.skill / 'link.md')
        self.assertIn('symlink', codes(self.verify()))

    def test_mirror_differs(self):
        (self.mirror / 'scripts' / 'gate.py').write_text('print(3)\n')
        p = self.verify()
        self.assertIn('file-changed', codes(p))
        self.assertTrue(any('[mirror' in x for x in p))

    def test_mirror_missing_or_lock_differs(self):
        shutil.rmtree(self.mirror)
        self.assertIn('mirror-missing', codes(self.verify()))

    def test_mirror_lock_differs(self):
        (self.mirror / 'scripts' / 'gates.lock.json').write_text('{}')
        self.assertIn('mirror-lock-differs', codes(self.verify()))

    def test_external_changed(self):
        (self.repo / 'engine' / 'core.ts').write_text('export const x = 1\n')
        p = self.verify()
        self.assertIn('external-changed', codes(p))
        self.assertIn('git-dirty', codes(p))

    def test_external_missing(self):
        (self.repo / 'engine' / 'core.ts').unlink()
        self.assertIn('external-missing', codes(self.verify()))

    def test_lock_missing(self):
        (self.skill / 'scripts' / 'gates.lock.json').unlink()
        self.assertEqual(['lock-missing'], codes(self.verify()))

    def test_lock_invalid(self):
        (self.skill / 'scripts' / 'gates.lock.json').write_text('{not json')
        self.assertEqual(['lock-invalid'], codes(self.verify()))

    def test_lock_regenerated_but_not_committed(self):
        (self.skill / 'scripts' / 'gate.py').write_text('print(2)\n')
        (self.mirror / 'scripts' / 'gate.py').write_text('print(2)\n')
        write_lock(self.repo, self.skill)
        shutil.copy(self.skill / 'scripts' / 'gates.lock.json', self.mirror / 'scripts' / 'gates.lock.json')
        p = self.verify()
        self.assertIn('lock-differs-from-head', codes(p))
        self.assertIn('differs-from-head', codes(p))
        self.assertNotIn('file-changed', codes(p))   # consistent with the (new) lock, but not with HEAD

    def test_untracked_locked_file(self):
        (self.skill / 'scripts' / 'gate2.py').write_text('x\n')
        write_lock(self.repo, self.skill)
        shutil.copy(self.skill / 'scripts' / 'gates.lock.json', self.mirror / 'scripts' / 'gates.lock.json')
        shutil.copy(self.skill / 'scripts' / 'gate2.py', self.mirror / 'scripts' / 'gate2.py')
        self.assertIn('not-in-head', codes(self.verify()))

    def test_committed_change_without_new_lock(self):
        (self.skill / 'scripts' / 'gate.py').write_text('print(2)\n')
        (self.mirror / 'scripts' / 'gate.py').write_text('print(2)\n')
        self.commit()
        self.assertEqual(['file-changed'], codes(self.verify()))

    def test_not_a_git_repo_fails_closed(self):
        shutil.rmtree(self.repo / '.git')
        self.assertEqual(['git-unavailable'], codes(self.verify()))

    def test_git_binary_missing_fails_closed(self):
        old = os.environ['PATH']
        os.environ['PATH'] = '/nonexistent'
        try:
            p = self.verify()
        finally:
            os.environ['PATH'] = old
        self.assertEqual(['git-unavailable'], codes(p))

    def test_skill_name_mismatch(self):
        lock = json.loads((self.skill / 'scripts' / 'gates.lock.json').read_text())
        lock['skill'] = 'Other'
        raw = (json.dumps(lock, indent=2) + '\n').encode()
        for d in (self.skill, self.mirror):
            (d / 'scripts' / 'gates.lock.json').write_bytes(raw)
        self.assertIn('skill-name-mismatch', codes(self.verify()))

    def test_repo_root_must_be_toplevel(self):
        p = gl.verify(self.skill, self.repo / '.claude', [self.mirror])
        self.assertTrue(p)


if __name__ == '__main__':
    unittest.main()
