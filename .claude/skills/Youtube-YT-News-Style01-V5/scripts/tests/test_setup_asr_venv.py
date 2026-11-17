"""setup_asr_venv.sh: the human-only script that builds the V4 chain's own ASR venv and pins it.  Nothing here installs anything.

Test seam: the script reads the home from the passwd entry (no environment override).  The tests copy it into a temp dir next to
a STUB launcher and rewrite ONE line of the copy (`PW_HOME=...`), so the target venv is a fake one in a temp dir.  The real venv
is only READ (the --verify test)."""
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
SETUP = SCRIPTS / 'setup_asr_venv.sh'
TEXT = SETUP.read_text(encoding='utf-8')
PW_HOME = pwd.getpwuid(os.getuid()).pw_dir
REAL_SITE = Path(PW_HOME) / '.cache' / 'yt-news-v4' / 'asr-venv' / 'lib' / 'python3.12' / 'site-packages'
REQUIREMENTS = re.search(r"^REQUIREMENTS='(.*?)'\n", TEXT, re.M | re.S).group(1).splitlines()
STUB_LAUNCHER = '#!/bin/bash\n[ "$1" = --verify ] && exit ${STUB_VERIFY_RC:-0}\nexit 9\n'


def norm(req):
    name, ver = req.split('==')
    return re.sub(r'[-_.]+', '_', name).lower() + '_' + ver


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.scripts = self.d / 'scripts'
        self.scripts.mkdir()
        self.home = self.d / 'home'
        self.home.mkdir()
        new, n = re.subn(r'^PW_HOME=.*$', lambda m: "PW_HOME='%s'" % self.home, TEXT, count=1, flags=re.M)
        self.assertEqual(1, n)
        self.sh = self.scripts / 'setup_asr_venv.sh'
        self.sh.write_text(new, encoding='utf-8')
        launcher = (SCRIPTS / 'asr_run.sh').read_text(encoding='utf-8')
        self.pyroot = re.search(r'^PYROOT=(.*)$', launcher, re.M).group(1)
        (self.scripts / 'asr_run.sh').write_text('PYROOT=%s\n' % self.pyroot + STUB_LAUNCHER, encoding='utf-8')     # only the PYROOT line is read
        self.target = self.home / '.cache' / 'yt-news-v4' / 'asr-venv'

    def tearDown(self):
        self.tmp.cleanup()

    def run_sh(self, *args, rc_verify=0):
        env = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent-home', 'STUB_VERIFY_RC': str(rc_verify)}
        return subprocess.run(['/bin/bash', str(self.sh), *args], capture_output=True, text=True, env=env, timeout=120)

    def fake_site(self, drop=None, extra=(), version_of=None):
        site = self.target / 'lib' / 'python3.12' / 'site-packages'
        site.mkdir(parents=True)
        for req in REQUIREMENTS:
            if req == drop:
                continue
            name, ver = req.split('==')
            if req == version_of:
                ver = ver + '.1'
            (site / ('%s-%s.dist-info' % (name.replace('-', '_'), ver))).mkdir()
        (site / 'pip-26.2.2.dist-info').mkdir()                                   # ensurepip's own distribution is allowed
        for e in extra:
            (site / (e + '.dist-info')).mkdir()
        return site

    def test_header_says_human_only_and_usage_errors_are_exit_2(self):
        self.assertIn('RUN BY A HUMAN, NEVER BY THE UNATTENDED AGENT', TEXT)
        for args in (['--nope'], ['--verify', '--verify'], ['x']):
            r = self.run_sh(*args)
            self.assertEqual(2, r.returncode, (args, r.stderr))
        r = self.run_sh('--verify')
        self.assertIn('for a HUMAN only', r.stdout)

    def test_verify_without_a_venv_is_exit_4_and_creates_nothing(self):
        r = self.run_sh('--verify')
        self.assertEqual(4, r.returncode)
        self.assertIn('does not exist', r.stderr)
        self.assertFalse((self.home / '.cache').exists())

    def test_verify_compares_every_distribution_and_the_manifest_check(self):
        self.fake_site()
        r = self.run_sh('--verify')
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn('VERIFY OK', r.stdout)
        r = self.run_sh('--verify', rc_verify=4)                                  # the launcher's manifest verification fails
        self.assertEqual(4, r.returncode)
        self.assertIn('asr_run.sh --verify reports a difference', r.stderr)
        shutil.rmtree(self.target)
        self.fake_site(drop='numpy==2.4.6')
        r = self.run_sh('--verify')
        self.assertEqual(4, r.returncode)
        self.assertIn('missing or other version: numpy_2.4.6', r.stderr)
        shutil.rmtree(self.target)
        self.fake_site(version_of='regex==2026.5.9')
        r = self.run_sh('--verify')
        self.assertEqual(4, r.returncode)
        self.assertIn('regex_2026.5.9', r.stderr)
        self.assertIn('unexpected distribution: regex_2026.5.9.1', r.stderr)
        shutil.rmtree(self.target)
        self.fake_site(extra=('torch-2.0',))
        r = self.run_sh('--verify')
        self.assertEqual(4, r.returncode)
        self.assertIn('unexpected distribution: torch_2.0', r.stderr)

    def test_an_existing_target_is_refused_and_nothing_is_deleted_or_installed(self):
        site = self.fake_site()
        keep = site / 'keep.txt'
        keep.write_text('x')
        r = self.run_sh()
        self.assertEqual(4, r.returncode)
        self.assertIn('REFUSED', r.stderr)
        self.assertIn('never deletes anything', r.stderr)
        self.assertTrue(keep.exists())

    def test_an_interpreter_that_asr_run_does_not_pin_is_refused_before_anything_is_created(self):
        (self.scripts / 'asr_run.sh').write_text('PYROOT=/somewhere/else/Versions/3.12\n' + STUB_LAUNCHER, encoding='utf-8')
        r = self.run_sh()
        self.assertEqual(4, r.returncode, r.stderr)
        self.assertIn("asr_run.sh pins PYROOT='/somewhere/else/Versions/3.12'", r.stderr)
        self.assertIn('ask the lead', r.stderr)
        self.assertFalse(self.target.exists())
        self.assertFalse((self.home / '.cache').exists())

    def test_the_install_is_pinned_binary_only_isolated_and_writes_the_manifest(self):
        for flag in ('--no-deps', '--only-binary=:all:', '--isolated', '--no-cache-dir', '--no-compile', '--index-url'):
            self.assertIn(flag, TEXT)
        self.assertIn('--write-manifest', TEXT)
        self.assertEqual([], re.findall(r'^\s*(?:sudo|brew)\b', TEXT, re.M))
        code = '\n'.join(l for l in TEXT.splitlines() if not l.lstrip().startswith('#'))
        for l in code.splitlines():
            if re.search(r'(^|[;&|] *)rm\b', l):
                self.assertRegex(l, r'^\s*rm -f "\$REQ"$')                      # the only thing it ever removes: its own temp requirements file
        self.assertEqual(26, len(REQUIREMENTS))
        for l in REQUIREMENTS:
            self.assertRegex(l, r'^[a-z0-9_-]+==\d[\w.]*$')

    @unittest.skipUnless(REAL_SITE.is_dir(), 'the V4 ASR venv is not on this machine')
    def test_the_requirements_are_exactly_the_distributions_of_the_real_venv_and_verify_is_read_only(self):
        have = sorted(re.sub(r'\.dist-info$', '', p.name).lower() for p in REAL_SITE.glob('*.dist-info'))
        have = [h for h in have if not h.startswith('pip-')]
        self.assertEqual(sorted(norm(r) for r in REQUIREMENTS), sorted(norm_dir(h) for h in have))
        manifest = SCRIPTS / 'asr_venv.manifest'
        before = (manifest.stat().st_mtime_ns, manifest.read_bytes())
        r = subprocess.run(['/bin/bash', str(SETUP), '--verify'], capture_output=True, text=True, env={'PATH': '/usr/bin:/bin'}, timeout=120)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn('VERIFY OK', r.stdout)
        self.assertEqual(before, (manifest.stat().st_mtime_ns, manifest.read_bytes()))      # --verify never writes the manifest


def norm_dir(dist_dir_name):
    """'charset_normalizer-3.4.7' -> 'charset_normalizer_3.4.7' (dist-info dir names already use underscores in the name part)"""
    name, ver = dist_dir_name.rsplit('-', 1)
    return re.sub(r'[-_.]+', '_', name) + '_' + ver


if __name__ == '__main__':
    unittest.main()
