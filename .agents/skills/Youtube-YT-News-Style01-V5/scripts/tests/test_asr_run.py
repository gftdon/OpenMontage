"""asr_run.sh: the launcher that verifies the interpreter / stdlib / venv OUTSIDE python (manifest) and then runs the pinned python.

Test seam (why it is acceptable): asr_run.sh has no hook and no environment variable changes what it verifies or runs.  The
falsification tests work in a COPY: the Cellar python tree and the V4 venv's site-packages are cloned (`cp -c`, APFS clone: cheap)
into a temp dir, a copy of the launcher gets its two constants (PYROOT, VENV_ROOT) rewritten to that temp tree and writes its
own manifest there (the human step, done by the test), and the chain scripts of the copy are PROBES that report what python was
given.  The real interpreter, the real venv and the HF cache are never written.  (A cloned interpreter still loads the ORIGINAL
stdlib through its dylib, so these tests show what the launcher REFUSES; they do not execute tampered code.)

Every refusal test also has a mutant that removes the protection (see the 'mutants' tests at the end): the refusal test must
fail when the verification is removed.
"""
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
LAUNCHER_SRC = (SCRIPTS / 'asr_run.sh').read_text(encoding='utf-8')
PYROOT = re.search(r'^PYROOT=(.*)$', LAUNCHER_SRC, re.M).group(1)
PW_HOME = pwd.getpwuid(os.getuid()).pw_dir
REAL_VENV = Path(PW_HOME) / '.cache' / 'yt-news-v4' / 'asr-venv'
REAL_SITE = REAL_VENV / 'lib' / 'python3.12' / 'site-packages'
HAVE_CHAIN = (Path(PYROOT) / 'bin' / 'python3.12').exists() and REAL_SITE.is_dir() and (SCRIPTS / 'asr_venv.manifest').exists()
BASH = '/bin/bash'

PROBE = r'''
import json, os, sys
doc = {'flags': {'isolated': sys.flags.isolated, 'no_site': sys.flags.no_site, 'dont_write_bytecode': sys.dont_write_bytecode,
                 'pycache_prefix': sys.pycache_prefix},
       'env': dict(os.environ), 'argv': sys.argv, 'executable': sys.executable, 'xoptions': dict(sys._xoptions), 'path': sys.path,
       'site_loaded': 'site' in sys.modules, 'sitecustomize_loaded': 'sitecustomize' in sys.modules, 'cwd': os.getcwd(),
       'prefix': sys.prefix, 'mods': {}, 'values': {}}
args, i = sys.argv[1:], 0
while i < len(args):
    if args[i] == '--path':
        sys.path.append(args[i + 1])
        i += 2
    elif args[i] == '--import':
        m = __import__(args[i + 1])
        doc['mods'][args[i + 1]] = getattr(m, '__file__', None)
        doc['values'][args[i + 1]] = getattr(m, 'VALUE', None)
        i += 2
    else:
        i += 1
print(json.dumps(doc))
'''


def clean_env(**extra):
    env = {'PATH': '/usr/bin:/bin', 'HOME': PW_HOME}
    env.update(extra)
    return env


def make_launcher(text, tree, scripts):
    """a copy of the launcher whose PYROOT / VENV_ROOT point at the cloned tree"""
    out, n1 = re.subn(r'^PYROOT=.*$', lambda m: 'PYROOT=%s' % (tree / 'py'), text, count=1, flags=re.M)
    out, n2 = re.subn(r'^VENV_ROOT=.*$', lambda m: 'VENV_ROOT=%s' % (tree / 'venv'), out, count=1, flags=re.M)
    assert (n1, n2) == (1, 1)
    path = scripts / 'asr_run.sh'
    path.write_text(out, encoding='utf-8')
    return path


@unittest.skipUnless(HAVE_CHAIN, 'the pinned python / the V4 ASR venv / the manifest are not on this machine')
class TreeCase(unittest.TestCase):
    """one cloned interpreter tree + venv + launcher copy per class"""
    mutate_launcher = None

    @classmethod
    def build(cls, launcher_text=None):
        cls.tmp = os.path.realpath(tempfile.mkdtemp(prefix='asr_run_tree_'))             # the launcher resolves its own dir with pwd -P
        t = Path(cls.tmp)
        cls.t = t
        subprocess.run(['/bin/cp', '-c', '-R', PYROOT, str(t / 'py')], check=True)
        (t / 'venv' / 'lib' / 'python3.12').mkdir(parents=True)
        subprocess.run(['/bin/cp', '-c', '-R', str(REAL_SITE), str(t / 'venv' / 'lib' / 'python3.12' / 'site-packages')], check=True)
        (t / 'venv' / 'bin').mkdir()
        os.symlink(t / 'py' / 'bin' / 'python3.12', t / 'venv' / 'bin' / 'python')          # like a venv's python
        cls.scripts = t / 'scripts'
        cls.scripts.mkdir()
        for name in ('asr_transcribe.py', 'asr_align.py', 'source_timed.py'):
            (cls.scripts / name).write_text(PROBE, encoding='utf-8')
        cls.launcher = make_launcher(launcher_text or LAUNCHER_SRC, t, cls.scripts)
        cls.site = t / 'venv' / 'lib' / 'python3.12' / 'site-packages'
        cls.stdlib = t / 'py' / 'lib' / 'python3.12'
        r = subprocess.run([BASH, str(cls.launcher), '--write-manifest'], capture_output=True, text=True, env=clean_env())      # the human step
        assert r.returncode == 0, r.stderr
        cls.manifest = cls.scripts / 'asr_venv.manifest'

    @classmethod
    def setUpClass(cls):
        cls.build()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_launcher(self, *args, env=None, cwd=None):
        return subprocess.run([BASH, str(self.launcher), *args], capture_output=True, text=True, env=env or clean_env(), cwd=cwd, timeout=300)

    def probe(self, *args, env=None, cwd=None):
        r = self.run_launcher('asr_transcribe.py', *args, env=env, cwd=cwd)
        self.assertEqual(0, r.returncode, r.stderr)
        return json.loads(r.stdout)

    # tamper helpers: every one restores the tree, whatever the test does
    def tampered(self, path, new_bytes):
        path = Path(path)
        old = path.read_bytes() if path.exists() else None

        def restore():
            if old is None:
                if path.exists() or path.is_symlink():
                    path.unlink()
            else:
                path.write_bytes(old)
        self.addCleanup(restore)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(new_bytes)

    def assertRefused(self, r, *names):
        self.assertEqual(4, r.returncode, r.stdout + r.stderr)
        self.assertEqual('', r.stdout, 'the probe ran although the launcher refused')
        self.assertIn('differ from', r.stderr)
        for n in names:
            self.assertIn(n, r.stderr)
        self.assertIn('setup_asr_venv.sh', r.stderr)
        self.assertIn('a human, not the agent', r.stderr)


class LaunchTests(TreeCase):
    def test_verify_and_run_the_probe_under_the_pinned_flags_and_the_minimal_environment(self):
        r = self.run_launcher('--verify')
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn('ok:', r.stdout)
        doc = self.probe('--x')
        self.assertEqual({'isolated': 1, 'no_site': 1, 'dont_write_bytecode': True, 'pycache_prefix': '/var/empty'}, doc['flags'])
        self.assertFalse(doc['site_loaded'])
        self.assertFalse(doc['sitecustomize_loaded'])
        env = {k: v for k, v in doc['env'].items() if k != '__CF_USER_TEXT_ENCODING'}
        self.assertEqual({'HOME', 'PATH', 'LANG', 'TMPDIR'}, set(env))
        self.assertEqual((PW_HOME, 'en_US.UTF-8', '/var/empty'), (env['HOME'], env['LANG'], env['TMPDIR']))
        self.assertTrue(env['PATH'].endswith('/usr/bin:/bin'))
        self.assertEqual(['%s/asr_transcribe.py' % self.scripts, '--x'], doc['argv'])           # the script path and its arguments, unchanged
        self.assertEqual(str(self.t / 'py' / 'bin' / 'python3.12'), doc['executable'])          # the interpreter tree, never the venv's python
        msha = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        self.assertEqual(msha, doc['xoptions']['asr_manifest_sha256'])                           # the manifest it verified
        self.assertNotIn('', doc['path'])
        self.assertNotIn(os.getcwd(), [os.path.realpath(p) for p in doc['path'] if p])

    def test_the_callers_environment_and_cwd_never_reach_python(self):
        marker = self.t / 'marker'
        evil = self.t / 'evil'
        evil.mkdir(exist_ok=True)
        (evil / 'sitecustomize.py').write_text('open(%r, "a").write("sitecustomize ")\n' % str(marker))
        (evil / 'perlevil.pm').write_text('open(F, ">>%s"); print F "perl "; close F; 1;\n' % marker)
        (evil / 'csv.py').write_text('open(%r, "a").write("cwd-module ")\n' % str(marker))
        hostile = {'PATH': '/nonexistent', 'HOME': '/nonexistent-home', 'PYTHONPATH': str(evil), 'PYTHONSTARTUP': str(evil / 'sitecustomize.py'),
                   'PYTHONHOME': '/nonexistent', 'PYTHONPYCACHEPREFIX': str(evil), 'PYTHONUSERBASE': str(evil), 'PERL5OPT': '-I%s -Mperlevil' % evil,
                   'PERL5LIB': str(evil), 'HF_HOME': str(evil), 'HF_HUB_CACHE': str(evil), 'HF_HUB_OFFLINE': '0', 'TMPDIR': str(evil),
                   'DYLD_LIBRARY_PATH': '/nonexistent', 'LANG': 'C', 'LC_ALL': 'C', 'NUMBA_CACHE_DIR': str(evil), 'MLX_X': '1'}
        doc = self.probe('--import', 'csv', env=hostile, cwd=str(evil))
        self.assertFalse(marker.exists(), marker.read_text() if marker.exists() else '')
        env = {k: v for k, v in doc['env'].items() if k != '__CF_USER_TEXT_ENCODING'}
        self.assertEqual({'HOME', 'PATH', 'LANG', 'TMPDIR'}, set(env))
        self.assertEqual((PW_HOME, '/var/empty', 'en_US.UTF-8'), (env['HOME'], env['TMPDIR'], env['LANG']))      # the passwd home, never $HOME
        self.assertNotIn('evil', json.dumps(doc['path']))
        self.assertTrue(doc['mods']['csv'].startswith(PYROOT), doc['mods'])                     # the stdlib's csv, not the one in the cwd

    def test_a_planted_pyc_is_never_read(self):
        """__pycache__ is outside the manifest (bytecode is never read: -B + pycache_prefix=/var/empty): a planted pyc next to a module
        that python can import must not win over the source"""
        import py_compile
        plant = self.t / 'plant'
        (plant / '__pycache__').mkdir(parents=True)
        (plant / 'planted.py').write_text('VALUE = "source"\n')
        evil = self.t / 'evil_planted.py'
        evil.write_text('VALUE = "planted pyc"\n')
        py_compile.compile(str(evil), cfile=str(plant / '__pycache__' / ('planted.%s.pyc' % sys.implementation.cache_tag)),
                           invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
        control = subprocess.run([str(Path(PYROOT) / 'bin' / 'python3.12'), '-I', '-c', 'import sys; sys.path.append(%r); import planted; print(planted.VALUE)' % str(plant)],
                                 capture_output=True, text=True)
        self.assertEqual('planted pyc', control.stdout.strip(), 'without the flags the planted pyc was NOT read: the test proves nothing')
        site_pyc = self.site / 'numpy' / '__pycache__' / 'junk.cpython-312.pyc'
        self.tampered(site_pyc, b'junk')
        self.assertEqual(0, self.run_launcher('--verify').returncode)                           # __pycache__ is not part of the manifest: not refused ...
        doc = self.probe('--path', str(plant), '--import', 'planted')
        self.assertEqual('source', doc['values']['planted'])                                    # ... and never read

    def test_usage_and_non_chain_scripts_are_exit_2_and_nothing_runs(self):
        self.assertEqual(2, self.run_launcher().returncode)
        self.assertEqual(2, self.run_launcher('--bogus').returncode)
        evil = self.scripts / 'evil.py'
        evil.write_text(PROBE)
        r = self.run_launcher('evil.py')
        self.assertEqual(2, r.returncode)
        self.assertIn('not a chain script', r.stderr)
        r = self.run_launcher('../scripts/asr_transcribe.py')                                   # no path tricks either
        self.assertEqual(2, r.returncode)

    def test_the_launcher_ignores_the_current_directory_and_works_from_anywhere(self):
        doc = self.probe(cwd='/')
        self.assertEqual('/', doc['cwd'])


class FalsificationTests(TreeCase):
    def test_a_wrapper_for_the_venv_python_is_never_run(self):
        """(a) venv/bin/python replaced by a wrapper that would hook the checks: the launcher execs the interpreter tree directly,
        so the wrapper never runs - and the verification is not even asked about it"""
        marker = self.t / 'wrapper_marker'
        wrapper = self.t / 'venv' / 'bin' / 'python'
        old_target = os.readlink(wrapper)
        wrapper.unlink()
        wrapper.write_text('#!/bin/sh\necho "wrapper ran" >> %s\nexec %s "$@"\n' % (marker, self.t / 'py' / 'bin' / 'python3.12'))
        wrapper.chmod(0o755)

        def restore():
            wrapper.unlink()
            os.symlink(old_target, wrapper)
        self.addCleanup(restore)
        doc = self.probe()
        self.assertFalse(marker.exists(), 'the launcher ran venv/bin/python')
        self.assertEqual(str(self.t / 'py' / 'bin' / 'python3.12'), doc['executable'])
        self.assertEqual(0, self.run_launcher('--verify').returncode)
        # the launcher does not even name the venv's python or pyvenv.cfg as something to run
        code = '\n'.join(l for l in LAUNCHER_SRC.splitlines() if not l.lstrip().startswith('#'))
        self.assertNotIn('bin/python"', code.replace('bin/python3.12', ''))
        self.assertNotIn('$VENV_ROOT/bin', code)

    def test_sitecustomize_and_a_pth_line_are_refused_and_not_executed_under_dash_S_even_if_the_manifest_were_stale(self):
        """(b)"""
        marker = self.t / 'site_marker'
        self.tampered(self.site / 'sitecustomize.py', ('open(%r, "a").write("sitecustomize ")\n' % str(marker)).encode())
        r = self.run_launcher('asr_transcribe.py')
        self.assertRefused(r, 'sitecustomize.py')
        self.assertFalse(marker.exists())
        pth = self.site / 'distutils-precedence.pth'
        self.assertTrue(pth.exists())
        self.tampered(self.site / 'sitecustomize.py', b'')
        (self.site / 'sitecustomize.py').unlink()
        self.tampered(pth, pth.read_bytes() + ('\nimport os; open(%r, "a").write("pth ")\n' % str(marker)).encode())
        r = self.run_launcher('asr_transcribe.py')
        self.assertRefused(r, 'distutils-precedence.pth')
        self.assertFalse(marker.exists())
        # a STALE manifest: re-pin the tampered tree (what a human would do after a rebuild) and start python anyway -
        # python -S never processes sitecustomize / .pth, so nothing runs even then
        self.tampered(self.site / 'sitecustomize.py', ('open(%r, "a").write("sitecustomize ")\n' % str(marker)).encode())
        saved = self.manifest.read_bytes()
        self.addCleanup(lambda: self.manifest.write_bytes(saved))
        self.assertEqual(0, subprocess.run([BASH, str(self.launcher), '--write-manifest'], capture_output=True, env=clean_env()).returncode)
        doc = self.probe()
        self.assertFalse(marker.exists(), 'sitecustomize / the .pth line ran although python was started with -S')
        self.assertFalse(doc['site_loaded'] or doc['sitecustomize_loaded'])

    def test_one_modified_stdlib_file_is_refused(self):
        """(c)"""
        for name in ('difflib.py', 'csv.py'):
            with self.subTest(name=name):
                f = self.stdlib / name
                self.tampered(f, f.read_bytes() + b'\n# tampered\n')
                r = self.run_launcher('asr_transcribe.py')
                self.assertRefused(r, 'lib/python3.12/%s' % name)
                self.assertEqual(4, self.run_launcher('--verify').returncode)

    def test_added_removed_and_replaced_files_of_the_interpreter_and_the_venv_are_refused(self):
        cases = []
        py = self.t / 'py'
        # the interpreter binary, the framework binary, libpython
        for rel in ('bin/python3.12', 'Python', 'Resources/Python.app/Contents/MacOS/Python'):
            f = py / rel
            self.tampered(f, f.read_bytes() + b'\x00')
            r = self.run_launcher('asr_transcribe.py')
            self.assertRefused(r, rel)
            self.tampered(f, f.read_bytes()[:-1])
        # a new stdlib module, a new compiled-less module in site-packages, a sourceless pyc, a new .so
        for f in (self.stdlib / 'brand_new_module.py', self.site / 'numpy' / 'extra.py', self.site / 'sourceless.pyc',
                  self.site / 'numpy' / 'extra.cpython-312-darwin.so'):
            self.tampered(f, b'x = 1\n')
            r = self.run_launcher('asr_transcribe.py')
            self.assertRefused(r, f.name)
            f.unlink()
        # a removed file (an installed module deleted so another one earlier on the path could be found)
        victim = self.site / 'pythainlp' / '__init__.py'
        saved = victim.read_bytes()
        victim.unlink()
        self.addCleanup(lambda: victim.write_bytes(saved))
        r = self.run_launcher('asr_transcribe.py')
        self.assertRefused(r, 'pythainlp/__init__.py')
        victim.write_bytes(saved)
        # a changed distribution file
        f = self.site / 'regex' / '__init__.py'
        self.tampered(f, f.read_bytes() + b'\n# tampered\n')
        self.assertRefused(self.run_launcher('asr_transcribe.py'), 'regex/__init__.py')

    def test_installer_files_and_bytecode_caches_are_not_part_of_the_pin(self):
        """RECORD / REQUESTED / INSTALLER / direct_url.json are written by the installer and never executed; __pycache__ is never read"""
        dist = next(self.site.glob('numpy-*.dist-info'))
        for name in ('RECORD', 'INSTALLER', 'REQUESTED', 'direct_url.json'):
            f = dist / name
            self.tampered(f, (f.read_bytes() if f.exists() else b'') + b'# changed\n')
        self.tampered(self.site / 'numpy' / '__pycache__' / 'junk.cpython-312.pyc', b'junk')
        self.tampered(self.site / '.DS_Store', b'finder')
        self.assertEqual(0, self.run_launcher('--verify').returncode)
        # but METADATA and the rest of the dist-info are pinned
        f = dist / 'METADATA'
        self.tampered(f, f.read_bytes() + b'# changed\n')
        self.assertEqual(4, self.run_launcher('--verify').returncode)

    def test_a_pyvenv_cfg_next_to_the_interpreter_is_refused(self):
        for rel in ('bin/pyvenv.cfg', 'pyvenv.cfg'):
            f = self.t / 'py' / rel
            self.tampered(f, b'home = /elsewhere\n')
            r = self.run_launcher('asr_transcribe.py')
            self.assertEqual(4, r.returncode)
            self.assertEqual('', r.stdout)
            self.assertIn('pyvenv.cfg', r.stderr)
            f.unlink()

    def test_a_python312_zip_is_refused_even_a_dangling_symlink(self):
        """(ค) python imports from <prefix>/lib/python312.zip when it exists; the manifest lists files, not zips: the launcher refuses any entry there"""
        zipf = self.t / 'py' / 'lib' / 'python312.zip'
        self.assertFalse(os.path.lexists(zipf))
        for kind in ('file', 'dangling symlink', 'directory'):
            with self.subTest(kind=kind):
                if kind == 'file':
                    zipf.write_bytes(b'PK\x05\x06' + b'\x00' * 18)                        # an empty but valid zip
                elif kind == 'dangling symlink':
                    os.symlink(self.t / 'nowhere.zip', zipf)
                else:
                    zipf.mkdir()
                self.addCleanup(lambda: shutil.rmtree(zipf) if zipf.is_dir() and not zipf.is_symlink() else (zipf.unlink() if os.path.lexists(zipf) else None))
                r = self.run_launcher('asr_transcribe.py')
                self.assertEqual((4, ''), (r.returncode, r.stdout), r.stderr)
                self.assertIn('python312.zip exists', r.stderr)
                self.assertIn(str(zipf), r.stderr)
                self.assertEqual(4, self.run_launcher('--verify').returncode)
                if kind == 'directory':
                    shutil.rmtree(zipf)
                else:
                    zipf.unlink()
        self.assertEqual(0, self.run_launcher('--verify').returncode)                      # removed again: fine

    def test_missing_manifest_python_or_venv_is_exit_4_with_the_setup_hint(self):
        saved = self.manifest.read_bytes()
        self.manifest.unlink()
        self.addCleanup(lambda: self.manifest.write_bytes(saved))
        r = self.run_launcher('asr_transcribe.py')
        self.assertEqual((4, ''), (r.returncode, r.stdout))
        self.assertIn('asr_venv.manifest is missing', r.stderr)
        self.assertIn('a human, not the agent', r.stderr)
        self.manifest.write_bytes(saved)
        site = self.t / 'venv' / 'lib' / 'python3.12' / 'site-packages'
        hidden = self.t / 'venv' / 'lib' / 'python3.12' / 'hidden'
        site.rename(hidden)
        self.addCleanup(lambda: hidden.rename(site) if hidden.exists() else None)
        r = self.run_launcher('asr_transcribe.py')
        self.assertEqual((4, ''), (r.returncode, r.stdout))
        self.assertIn('is not there', r.stderr)
        hidden.rename(site)

    def test_write_manifest_is_sorted_complete_and_lists_no_environment_specific_files(self):
        lines = [l for l in self.manifest.read_text(encoding='utf-8').splitlines() if not l.startswith('#')]
        paths = [l.split('  ', 1)[1] for l in lines]
        self.assertEqual(paths, sorted(set(paths)))
        self.assertTrue(all(re.fullmatch(r'[0-9a-f]{64}  @(PY|VENV)@/.+', l) for l in lines))
        self.assertIn('@PY@/bin/python3.12', paths)
        self.assertIn('@PY@/Python', paths)
        self.assertIn('@PY@/Resources/Python.app/Contents/MacOS/Python', paths)
        self.assertIn('@PY@/lib/python3.12/csv.py', paths)
        self.assertIn('@VENV@/lib/python3.12/site-packages/numpy/__init__.py', paths)
        for p in paths:
            self.assertNotRegex(p, r'__pycache__|\.dist-info/(RECORD|REQUESTED|INSTALLER|direct_url\.json)$|\.DS_Store')
            self.assertNotIn('/lib/python3.12/site-packages/', p.replace('@VENV@/lib/python3.12/site-packages/', ''))   # the interpreter's own site-packages is not on the path
        self.assertGreater(len(lines), 5000)
        self.assertNotIn(PW_HOME, self.manifest.read_text(encoding='utf-8').replace(PYROOT, ''))      # no user name in the committed file


@unittest.skipUnless(HAVE_CHAIN, 'the pinned python / the V4 ASR venv / the manifest are not on this machine')
class RealLauncherTests(unittest.TestCase):
    """the real launcher against the real tree (read-only): the committed manifest matches this machine"""

    def test_the_committed_manifest_matches_the_real_interpreter_stdlib_and_venv(self):
        t0 = time.time()
        r = subprocess.run([BASH, str(SCRIPTS / 'asr_run.sh'), '--verify'], capture_output=True, text=True, env=clean_env(HOME='/nonexistent-home'))
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertLess(time.time() - t0, 60)

    def test_the_real_launcher_runs_the_check_under_a_hostile_environment(self):
        hostile = {'PATH': '/nonexistent', 'HOME': '/nonexistent-home', 'PYTHONPATH': '/nonexistent', 'HF_HOME': '/nonexistent',
                   'PYTHONHOME': '/nonexistent', 'DYLD_LIBRARY_PATH': '/nonexistent', 'LANG': 'C', 'MLX_X': '1'}
        r = subprocess.run([BASH, str(SCRIPTS / 'asr_run.sh'), 'asr_transcribe.py', '--check'], capture_output=True, text=True, env=hostile)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn('pinned by manifest', r.stdout)

    def test_the_launcher_constants_and_the_setup_script_agree(self):
        setup = (SCRIPTS / 'setup_asr_venv.sh').read_text(encoding='utf-8')
        self.assertIn("/.cache/yt-news-v4/asr-venv", setup)
        self.assertIn('.cache/yt-news-v4/asr-venv', LAUNCHER_SRC)
        self.assertIn("pinned_pyroot", setup)                                                    # the setup script reads PYROOT from this launcher
        self.assertEqual(1, len(re.findall(r'^PYROOT=', LAUNCHER_SRC, re.M)))


class MutantTests(unittest.TestCase):
    """the refusal tests must FAIL when the protection is removed: build the cloned tree with a launcher that lacks it and show that
    the tamper is then NOT refused (so a refusal test would fail)"""

    @classmethod
    def mutant(cls, text):
        class M(TreeCase):
            pass
        M.build(text)
        return M

    @unittest.skipUnless(HAVE_CHAIN, 'chain not present')
    def test_without_the_manifest_check_a_tampered_stdlib_file_and_a_sitecustomize_are_accepted(self):
        text = LAUNCHER_SRC.replace('\nverify_manifest\nMSHA=', '\ntrue\nMSHA=')
        self.assertNotEqual(text, LAUNCHER_SRC)
        M = self.mutant(text)
        try:
            f = M.stdlib / 'difflib.py'
            f.write_bytes(f.read_bytes() + b'\n# tampered\n')
            (M.site / 'sitecustomize.py').write_text('x = 1\n')
            r = subprocess.run([BASH, str(M.launcher), 'asr_transcribe.py'], capture_output=True, text=True, env=clean_env())
            self.assertEqual(0, r.returncode, 'the mutant should have accepted the tampered tree: %s' % r.stderr)
        finally:
            shutil.rmtree(M.tmp, ignore_errors=True)

    @unittest.skipUnless(HAVE_CHAIN, 'chain not present')
    def test_without_the_zip_check_a_planted_python312_zip_is_accepted(self):
        text = LAUNCHER_SRC.replace('if [ -e "$PYROOT/lib/python312.zip" ] || [ -L "$PYROOT/lib/python312.zip" ]; then', 'if false; then')
        self.assertNotEqual(text, LAUNCHER_SRC)
        M = self.mutant(text)
        try:
            (M.t / 'py' / 'lib' / 'python312.zip').write_bytes(b'PK\x05\x06' + b'\x00' * 18)
            r = subprocess.run([BASH, str(M.launcher), 'asr_transcribe.py'], capture_output=True, text=True, env=clean_env())
            self.assertEqual(0, r.returncode, 'the mutant should have accepted the planted zip: %s' % r.stderr)
        finally:
            shutil.rmtree(M.tmp, ignore_errors=True)

    @unittest.skipUnless(HAVE_CHAIN, 'chain not present')
    def test_without_dash_S_a_sitecustomize_runs(self):
        text = LAUNCHER_SRC.replace('-I -S -B -X pycache_prefix=/var/empty', '-I -B -X pycache_prefix=/var/empty')
        self.assertNotEqual(text, LAUNCHER_SRC)
        M = self.mutant(text)
        try:
            doc = json.loads(subprocess.run([BASH, str(M.launcher), 'asr_transcribe.py'], capture_output=True, text=True, env=clean_env()).stdout)
            self.assertEqual(0, doc['flags']['no_site'])                                         # the probe sees that site processing is on
        finally:
            shutil.rmtree(M.tmp, ignore_errors=True)

    @unittest.skipUnless(HAVE_CHAIN, 'chain not present')
    def test_a_launcher_that_execs_the_venv_python_runs_the_wrapper(self):
        text = LAUNCHER_SRC.replace('    "$PYBIN" -I -S -B', '    "$VENV_ROOT/bin/python" -I -S -B')
        self.assertNotEqual(text, LAUNCHER_SRC)
        M = self.mutant(text)
        try:
            marker = M.t / 'wrapper_marker'
            wrapper = M.t / 'venv' / 'bin' / 'python'
            wrapper.unlink()
            wrapper.write_text('#!/bin/sh\necho "wrapper ran" >> %s\nexec %s "$@"\n' % (marker, M.t / 'py' / 'bin' / 'python3.12'))
            wrapper.chmod(0o755)
            subprocess.run([BASH, str(M.launcher), 'asr_transcribe.py'], capture_output=True, text=True, env=clean_env())
            self.assertTrue(marker.exists(), 'the mutant should have run the wrapper (so the wrapper test would fail)')
        finally:
            shutil.rmtree(M.tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
