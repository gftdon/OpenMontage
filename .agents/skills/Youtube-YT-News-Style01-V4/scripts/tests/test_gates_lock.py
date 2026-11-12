import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / 'gates_lock.py'
spec = importlib.util.spec_from_file_location('gates_lock_under_test', SCRIPT)
gl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gl)

NODE = shutil.which('node')
if NODE:
    gl.NODE_BIN = NODE
NAME = 'FakeSkill'
ENGINE = 'remotion-composer/src/YtNewsStyle01V4.tsx'
REAL_INTEGRITY = SCRIPT.parent / 'gate_integrity.mjs'
# a stand-in for the engine team's `gate_integrity.mjs <composer> --list-external`: prints FAKE_EXTERNAL_LIST (default: the engine file)
FAKE_INTEGRITY = '''import process from 'node:process';
if (process.argv.includes('--list-external')) {
  const exit = Number(process.env.FAKE_LIST_EXIT || 0);
  if (exit) { process.stderr.write('boom\\n'); process.exit(exit); }
  const list = process.env.FAKE_EXTERNAL_LIST ?? 'remotion-composer/src/YtNewsStyle01V4.tsx';
  process.stdout.write(list ? list + '\\n' : '');
  process.exit(0);
}
process.exit(2);
'''


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
    (skill / 'scripts' / 'gate_integrity.mjs').write_text(FAKE_INTEGRITY)
    (skill / 'references' / 'a.md').write_text('ref\n')
    (skill / 'scripts' / 'tests' / 'test_x.py').write_text('x\n')
    (skill / 'scripts' / '__pycache__' / 'gate.cpython-312.pyc').write_bytes(b'\0\1')
    (skill / '.DS_Store').write_bytes(b'ds')
    (repo / 'engine').mkdir()
    (repo / 'engine' / 'core.ts').write_text('export {}\n')
    (repo / 'remotion-composer' / 'src').mkdir(parents=True)
    (repo / 'remotion-composer' / 'src' / 'YtNewsStyle01V4.tsx').write_text('export const E = 1;\n')     # printed by the fake --list-external
    sh(repo, 'git', 'init', '-q')
    sh(repo, 'git', 'config', 'user.email', 't@t')
    sh(repo, 'git', 'config', 'user.name', 't')
    sh(repo, 'git', 'config', 'commit.gpgsign', 'false')
    (repo / '.gitignore').write_text('__pycache__/\n.DS_Store\nprojects/\n')
    sh(repo, 'git', 'add', '-A')               # a lock is only written over files git tracks
    write_lock(repo, skill, external)
    mirror = repo / '.agents' / 'skills' / NAME
    shutil.copytree(skill, mirror)
    sh(repo, 'git', 'add', '-A')
    sh(repo, 'git', 'commit', '-q', '-m', 'init')
    return repo, skill, mirror


def write_lock(repo, skill, external=('engine/core.ts',), required=None, check_git=True):
    lock = gl.build_lock(skill, repo, external, required=required, check_git=check_git)
    (skill / 'scripts' / 'gates.lock.json').write_bytes(gl.lock_bytes(lock))
    return lock


def codes(problems):
    return sorted({p.split(':')[0] for p in problems})


@unittest.skipUnless(NODE, 'node required')
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
        self.assertEqual(['SKILL.md', 'references/a.md', 'scripts/gate.py', 'scripts/gate_integrity.mjs', 'scripts/tests/test_x.py'],
                         list(lock['files']))
        self.assertEqual(['engine/core.ts', ENGINE], list(lock['external']))      # what --list-external printed is always locked
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

    def test_a_new_file_anywhere_in_the_skill_or_its_mirror_is_file_extra(self):
        for root, label in ((self.skill, ''), (self.mirror, 'mirror')):
            for sub in ('scripts', 'scripts/tests', 'assets', 'references', '.'):
                (root / sub).mkdir(parents=True, exist_ok=True)
                f = root / sub / 'added.txt'
                f.write_text('x\n')
                p = [x for x in self.verify() if x.startswith('file-extra')]
                self.assertTrue(p, (label, sub))
                self.assertTrue(any('added.txt' in x for x in p), (label, sub, p))
                if label:
                    self.assertTrue(any('[mirror' in x for x in p), (label, sub, p))
                f.unlink()
        self.assertEqual([], [x for x in self.verify() if x.startswith('file-extra')])

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

    # ---- a lock is never written over junk
    def junk(self, rel, ignored=False):
        f = self.skill / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('junk\n')
        return f

    def test_build_lock_refuses_an_untracked_file_in_the_skill_tree_naming_it(self):
        self.junk('scripts/tests/leaked/check.json')
        with self.assertRaises(ValueError) as cm:
            gl.build_lock(self.skill, self.repo, [])
        msg = str(cm.exception)
        self.assertIn('scripts/tests/leaked/check.json', msg)
        self.assertIn('not tracked by git', msg)
        self.junk('SECOND.md')
        with self.assertRaises(ValueError) as cm:
            gl.build_lock(self.skill, self.repo, [])
        self.assertIn('SECOND.md', str(cm.exception))

    def test_build_lock_refuses_a_gitignored_file_in_the_skill_tree(self):
        self.junk('scripts/tests/projects/p1/qc/finalize/check.json')        # exactly the stray that once leaked (ignored by projects/)
        with self.assertRaises(ValueError) as cm:
            gl.build_lock(self.skill, self.repo, [])
        self.assertIn('scripts/tests/projects/p1/qc/finalize/check.json', str(cm.exception))
        # verify() keeps reporting such files as extras
        self.assertIn('file-extra', codes(self.verify()))

    def test_build_lock_refuses_a_tracked_but_ignored_file(self):
        f = self.junk('scripts/tests/projects/forced.json')
        sh(self.repo, 'git', 'add', '-f', str(f))
        with self.assertRaises(ValueError) as cm:
            gl.build_lock(self.skill, self.repo, [])
        self.assertIn('ignored by git', str(cm.exception))

    def test_build_lock_refuses_an_untracked_external(self):
        (self.repo / 'engine' / 'new.ts').write_text('x\n')
        with self.assertRaises(ValueError) as cm:
            gl.build_lock(self.skill, self.repo, ['engine/new.ts'])
        self.assertIn('engine/new.ts', str(cm.exception))

    def test_build_lock_accepts_staged_files_and_modified_tracked_files(self):
        f = self.junk('scripts/new_gate.py')
        sh(self.repo, 'git', 'add', str(f))                      # staged is enough: the lock is written before the commit
        (self.skill / 'scripts' / 'gate.py').write_text('print(3)\n')
        self.assertIn('scripts/new_gate.py', gl.build_lock(self.skill, self.repo, [])['files'])

    def test_write_cli_refuses_with_exit_2_and_a_message(self):
        self.junk('scripts/tests/projects/x.json')
        out = Path(self.tmp) / 'lock.json'
        r = subprocess.run([sys.executable, '-B', str(SCRIPT), 'write', '--skill-dir', str(self.skill), '--repo-root', str(self.repo),
                            '--out', str(out)], capture_output=True, text=True)
        self.assertEqual(2, r.returncode)
        self.assertIn('scripts/tests/projects/x.json', r.stderr)
        self.assertFalse(out.exists())

    # ---- the lock and the receipt stay valid when git moves for unrelated reasons
    def test_unrelated_commit_and_unrelated_dirty_or_untracked_files_do_not_matter(self):
        self.assertEqual([], self.verify())
        (self.repo / 'unrelated.txt').write_text('1\n')
        self.commit()
        self.assertEqual([], self.verify())
        (self.repo / 'unrelated.txt').write_text('modified, uncommitted\n')
        (self.repo / 'engine' / 'untracked.ts').write_text('x\n')
        (self.repo / 'other-skill').mkdir()
        (self.repo / 'other-skill' / 'f.py').write_text('x\n')
        self.assertEqual([], self.verify())

    # ---- git hygiene
    def test_git_is_called_with_a_clean_environment_and_no_fsmonitor_and_replace_objects_off(self):
        calls = []
        real = subprocess.run

        def spy(cmd, *a, **k):
            if cmd[0] == gl.GIT_BIN:
                calls.append((cmd, k.get('env')))
            return real(cmd, *a, **k)
        bogus = str(Path(self.tmp) / 'nope')
        with mock.patch.object(gl.subprocess, 'run', side_effect=spy), \
                mock.patch.dict(os.environ, {'GIT_DIR': bogus, 'GIT_WORK_TREE': bogus, 'GIT_INDEX_FILE': bogus}):
            self.assertEqual([], self.verify())
        self.assertTrue(calls)
        for cmd, env in calls:
            self.assertIn('core.fsmonitor=false', cmd)
            self.assertEqual('1', env['GIT_NO_REPLACE_OBJECTS'])
            self.assertEqual({'GIT_OPTIONAL_LOCKS', 'GIT_NO_REPLACE_OBJECTS'}, {k for k in env if k.startswith('GIT_')})

    def test_git_binary_path_is_the_one_finalize_resolved(self):
        old = gl.GIT_BIN
        self.addCleanup(setattr, gl, 'GIT_BIN', old)
        gl.GIT_BIN = str(Path(self.tmp) / 'no-such-git')
        self.assertIn('git-unavailable', codes(self.verify()))

    def test_every_git_call_is_bounded_by_the_deadline(self):
        import time as _t
        p = gl.verify(self.skill, self.repo, [self.mirror], deadline=_t.monotonic() - 1)
        self.assertIn('git-unavailable', codes(p))

    # ---- the required externals come from the engine's own command, never from this module
    def test_no_required_list_is_typed_in_the_module(self):
        text = SCRIPT.read_text()
        self.assertFalse(hasattr(gl, 'REQUIRED_EXTERNAL'))
        self.assertNotIn('YtNewsStyle01V4', text)
        self.assertNotIn('ytNewsStyle01V4', text)

    def run_cli(self, *args, **env):
        e = dict(os.environ, **env)
        return subprocess.run([sys.executable, '-B', str(SCRIPT), *args], capture_output=True, text=True, env=e)

    def test_the_list_follows_the_command_output(self):
        listed = '\n'.join([ENGINE, 'engine/core.ts', ENGINE])           # unsorted + duplicated: normalised
        with mock.patch.dict(os.environ, {'FAKE_EXTERNAL_LIST': listed}):
            self.assertEqual(['engine/core.ts', ENGINE], gl.list_required_external(self.skill, self.repo))

    def test_the_command_is_run_against_repo_remotion_composer_with_list_external(self):
        calls = []
        real = subprocess.run

        def spy(cmd, *a, **k):
            if cmd[0] == gl.NODE_BIN:
                calls.append(cmd)
            return real(cmd, *a, **k)
        with mock.patch.object(gl.subprocess, 'run', side_effect=spy):
            gl.list_required_external(self.skill, self.repo)
        self.assertEqual([[gl.NODE_BIN, str(self.skill / 'scripts' / 'gate_integrity.mjs'), str(self.repo / 'remotion-composer'),
                           '--list-external']], calls)

    def test_a_path_printed_by_the_command_that_the_lock_lacks_fails_verify(self):
        with mock.patch.dict(os.environ, {'FAKE_EXTERNAL_LIST': '\n'.join([ENGINE, 'remotion-composer/src/new.tsx'])}):
            p = self.verify()
        self.assertEqual(['external-not-locked'], codes(p))
        self.assertIn('remotion-composer/src/new.tsx', p[0])

    def test_write_refuses_when_the_list_is_unusable_and_writes_nothing(self):
        out = Path(self.tmp) / 'lock.json'
        cases = {'empty': {'FAKE_EXTERNAL_LIST': ''}, 'exit': {'FAKE_LIST_EXIT': '3'}, 'absolute': {'FAKE_EXTERNAL_LIST': '/etc/passwd'},
                 'escape': {'FAKE_EXTERNAL_LIST': '../x.tsx'}, 'missing-file': {'FAKE_EXTERNAL_LIST': 'remotion-composer/src/none.tsx'}}
        for label, env in cases.items():
            r = self.run_cli('write', '--skill-dir', str(self.skill), '--repo-root', str(self.repo), '--out', str(out), **env)
            self.assertEqual(2, r.returncode, (label, r.stdout, r.stderr))
            self.assertFalse(out.exists(), label)
        r = self.run_cli('write', '--skill-dir', str(self.skill), '--repo-root', str(self.repo), '--out', str(out), FAKE_LIST_EXIT='3')
        self.assertIn('cannot obtain the required external files', r.stderr)

    def test_write_refuses_when_the_script_is_missing(self):
        (self.skill / 'scripts' / 'gate_integrity.mjs').unlink()
        with self.assertRaises(ValueError) as cm:
            gl.build_lock(self.skill, self.repo, [])
        self.assertIn('gate_integrity.mjs is missing', str(cm.exception))

    def test_verify_problem_codes_tool_missing_versus_unavailable_list(self):
        (self.skill / 'scripts' / 'gate_integrity.mjs').unlink()
        self.assertIn('tool-missing', codes(self.verify()))                  # finalize: class 4
        (self.skill / 'scripts' / 'gate_integrity.mjs').write_text(FAKE_INTEGRITY)
        with mock.patch.dict(os.environ, {'FAKE_EXTERNAL_LIST': ''}):
            self.assertIn('required-external-unavailable', codes(self.verify()))      # finalize: class 3
        with mock.patch.dict(os.environ, {'FAKE_LIST_EXIT': '2'}):
            p = self.verify()
        self.assertIn('required-external-unavailable', codes(p))
        self.assertTrue(any('exited 2' in x for x in p))

    def test_node_missing_is_tool_missing(self):
        old = gl.NODE_BIN
        self.addCleanup(setattr, gl, 'NODE_BIN', old)
        gl.NODE_BIN = str(Path(self.tmp) / 'no-such-node')
        self.assertIn('tool-missing', codes(self.verify()))

    def test_the_command_is_bounded_by_the_deadline(self):
        import time as _t
        with self.assertRaises(gl.RequiredListError) as cm:
            gl.list_required_external(self.skill, self.repo, deadline=_t.monotonic() - 1)
        self.assertEqual('tool', cm.exception.kind)

    def test_cli_verify_reports_an_unusable_list_with_exit_1(self):
        r = self.run_cli('verify', '--skill-dir', str(self.skill), '--repo-root', str(self.repo), FAKE_EXTERNAL_LIST='')
        self.assertEqual(1, r.returncode)
        self.assertIn('required-external-unavailable', r.stdout)

    def test_write_cli_without_external_includes_every_printed_path(self):
        out = self.skill / 'scripts' / 'gates.lock.json'
        r = self.run_cli('write', '--skill-dir', str(self.skill), '--repo-root', str(self.repo), '--out', str(out))
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertEqual([ENGINE], list(json.loads(out.read_text())['external']))

    @unittest.skipUnless(REAL_INTEGRITY.is_file(), 'real gate_integrity.mjs required')
    def test_the_real_script_prints_a_usable_list(self):
        real_skill = SCRIPT.parent.parent
        r = subprocess.run([NODE, str(REAL_INTEGRITY), str(self.repo / 'remotion-composer'), '--list-external'], capture_output=True, text=True)
        self.assertEqual(0, r.returncode, r.stderr)
        printed = sorted(x for x in r.stdout.split('\n') if x)
        self.assertGreaterEqual(len(printed), 4)
        self.assertEqual(printed, gl.list_required_external(real_skill, self.repo))

    def test_required_external_must_be_listed_in_the_lock(self):
        self.assertEqual([], gl.verify(self.skill, self.repo, [self.mirror], ['engine/core.ts']))
        p = gl.verify(self.skill, self.repo, [self.mirror], ['engine/core.ts', 'engine/other.ts'])
        self.assertEqual(['external-not-locked'], codes(p))
        self.assertIn('engine/other.ts', p[0])

    def test_required_external_missing_when_lock_has_no_externals(self):
        write_lock(self.repo, self.skill, (), required=())
        shutil.copy(self.skill / 'scripts' / 'gates.lock.json', self.mirror / 'scripts' / 'gates.lock.json')
        self.commit()
        self.assertEqual([], gl.verify(self.skill, self.repo, [self.mirror], required_external=()))      # fine without the requirement
        self.assertEqual(['external-not-locked'], codes(self.verify()))                              # the command's list
        p = gl.verify(self.skill, self.repo, [self.mirror], ['engine/core.ts'])
        self.assertEqual(['external-not-locked'], codes(p))

    def test_required_external_bad_path_is_refused(self):
        for bad in ('/etc/passwd', '../x', ''):
            self.assertIn('external-not-locked', codes(gl.verify(self.skill, self.repo, [self.mirror], [bad])), bad)

    def test_cli_require_external(self):
        base = [sys.executable, str(SCRIPT), 'verify', '--skill-dir', str(self.skill), '--repo-root', str(self.repo),
                '--mirror', str(self.mirror)]
        self.assertEqual(0, subprocess.run(base + ['--require-external', 'engine/core.ts'], capture_output=True, text=True).returncode)
        r = subprocess.run(base + ['--require-external', 'engine/nope.ts'], capture_output=True, text=True)
        self.assertEqual(1, r.returncode)
        self.assertIn('external-not-locked', r.stdout)

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
        write_lock(self.repo, self.skill, check_git=False)         # build_lock itself refuses this; verify() must still catch it
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
