"""word_timing.sh: resumable, detached, keyed word-timing job (asr_transcribe.py -> asr_align.py).  Whisper is never run.

Test seam (why it is acceptable): word_timing.sh has NO test hook and no environment variable changes what it does.  It starts
the chain through the launcher that sits next to itself (asr_run.sh, which verifies the interpreter / stdlib / venv against the
manifest and runs the pinned python; test_asr_run.py tests the REAL launcher).  The job-mechanics tests copy word_timing.sh into
a temp dir beside a STUB launcher, STUB sibling chain scripts and a stub manifest, and rewrite ONE line of that COPY
(`PW_HOME=...`).  The stub launcher gives the stub scripts exactly what the real one does (`env -i` + the minimal environment +
`python -I -S -B -X pycache_prefix=/var/empty`), so the tests below can still see what a job is given.  Rewriting a line of a
copy is an edit of the code under test, not an environment steer: the real script has no such lever."""
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
import wave

SCRIPTS = Path(__file__).resolve().parents[1]
SH = SCRIPTS / 'word_timing.sh'
PW_HOME = pwd.getpwuid(os.getuid()).pw_dir

STUB_TRANSCRIBE = r'''
import hashlib, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
def mode(name, default=''):
    p = os.path.join(HERE, 'stub_' + name)
    return open(p).read().strip() if os.path.exists(p) else default
args = sys.argv[1:]
if args == ['--check']:
    rc = int(mode('check_rc', '0'))
    if rc:
        print('ERROR: mlx_whisper/decoding.py sha256 does not match the pinned value (stub)', file=sys.stderr)
    sys.exit(rc)
if args == ['--fingerprint']:                    # the toolchain fingerprint seam: stub_fingerprint holds what it prints, stub_fingerprint_rc its exit
    rc = int(mode('fingerprint_rc', '0'))
    if rc:
        print('ERROR: the fingerprint could not be read (stub)', file=sys.stderr)
        sys.exit(rc)
    if mode('fingerprint_noise'):                    # a warning that differs on every call, on stderr only
        n = int(mode('fingerprint_noise_n', '0')) + 1
        open(os.path.join(HERE, 'stub_fingerprint_noise_n'), 'w').write(str(n))
        print('warning: stub noise %d at %s' % (n, time.time()), file=sys.stderr)
    print(mode('fingerprint', '{"platform": {"release": "25.6.0"}}'))
    sys.exit(0)
a = dict(zip(args[::2], args[1::2]))
out = a['--out-dir']
open(os.path.join(out, 'calls.log'), 'a').write('started\n')
json.dump({'env': dict(os.environ), 'flags': [sys.flags.isolated, sys.dont_write_bytecode, sys.pycache_prefix, sys.flags.no_site]}, open(os.path.join(out, 'env.json'), 'w'))
time.sleep(float(mode('sleep', '0')))
result = mode('result', 'ok')
if result == 'crash':
    print('boom: fake transcription failure', file=sys.stderr)
    sys.exit(3)
if result == 'rc4':
    print('ERROR: the ASR venv changed (stub)', file=sys.stderr)
    sys.exit(4)
if result == 'defective':
    json.dump({'schema': 'yt-news-v4-word-timing-failed', 'version': 1, 'rung': 'R1', 'reason': 'exhausted',
               'regions': [[573.71, 587.66]],
               'defects': [{'code': 'word-too-long', 'start': 576.72, 'end': 584.64, 'token': 'tok', 'value': 7.92, 'limit': 4.0}]},
              open(os.path.join(out, 'word_timing.failed.json'), 'w'))
    print('DEFECT word-too-long at 576.720s token="tok" value=7.92 limit=4.0')
    sys.exit(5)
sha = hashlib.sha256(open(a['--script'], 'rb').read()).hexdigest()[:8]
json.dump({'schema': 'yt-news-v4-raw-asr', 'version': 1, 'model': {'id': 'stub-model', 'snapshot': 'x'},
           'rungs': [{'rung': 'R0', 'regions': [[0.0, 1.0]], 'seconds': 1.0}], 'script8': sha, 'segments': []},
          open(os.path.join(out, 'raw_asr.json'), 'w'))
'''

STUB_ALIGN = r'''
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
a = dict(zip(sys.argv[1::2], sys.argv[2::2]))
if os.path.exists(os.path.join(HERE, 'stub_align_fail')):
    print('boom: fake alignment failure', file=sys.stderr)
    sys.exit(2)
raw = json.load(open(a['--raw']))
open(a['--out'], 'w').write(json.dumps([{'start': 0, 'end': 1, 'words': [{'w': raw['script8'], 's': 0, 'e': 1}]}]))
'''


STUB_LAUNCHER = r'''#!/bin/bash
# stub of asr_run.sh for the job-mechanics tests: logs its arguments, runs the stub chain script with the same python flags and
# the same minimal environment the real launcher uses
echo "$*" >> '%(argv_log)s'
script=$1
shift
exec /usr/bin/env -i HOME='%(home)s' PATH=/opt/homebrew/bin:/usr/bin:/bin LANG=en_US.UTF-8 TMPDIR=/var/empty '%(py)s' -I -S -B -X pycache_prefix=/var/empty "%(here)s/$script" "$@"
'''


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class WordTimingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.bin = d / 'scripts'
        self.bin.mkdir()
        shutil.copy(SH, self.bin / 'word_timing.sh')
        (self.bin / 'asr_transcribe.py').write_text(STUB_TRANSCRIBE)
        (self.bin / 'asr_align.py').write_text(STUB_ALIGN)
        (self.bin / 'timing_defects.py').write_text('# stub: only its hash enters the job key\n')
        (self.bin / 'asr_venv.manifest').write_text('# stub manifest: only its hash enters the job key\n')
        self.sh = self.bin / 'word_timing.sh'
        self.home = d / 'home'
        self.home.mkdir()
        self.set_home(self.home)
        self.argv_log = d / 'argv.log'
        (self.bin / 'asr_run.sh').write_text(STUB_LAUNCHER % {'argv_log': self.argv_log, 'home': self.home, 'py': sys.executable,
                                                              'here': self.bin})
        self.audio = d / 'a.wav'
        with wave.open(str(self.audio), 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b'\x00\x00' * 16000)
        self.script = d / 'script.txt'
        self.script.write_text('line one\nline two\n', encoding='utf-8')
        self.out = d / 'out'

    def tearDown(self):
        self.call('--cancel')
        self.tmp.cleanup()

    def stub(self, name, value):
        (self.bin / ('stub_' + name)).write_text(str(value))

    def set_home(self, home):
        """rewrite the PW_HOME line of the COPY of word_timing.sh (see the module docstring)"""
        text = SH.read_text()
        new, n = re.subn(r'^PW_HOME=.*$', lambda m: "PW_HOME='%s'" % home, text, count=1, flags=re.M)
        self.assertEqual(1, n)
        self.sh.write_text(new)

    def call(self, *extra, script=None, env_extra=None, sh=None):
        env = dict(os.environ)
        env.update(env_extra or {})
        return subprocess.run(['/bin/bash', str(sh or self.sh), str(self.audio), str(script or self.script), str(self.out), *extra],
                              capture_output=True, text=True, env=env, timeout=120)

    def calls(self, wait_for=0):
        f = self.out / 'calls.log'
        deadline = time.time() + 6
        while wait_for and time.time() < deadline and not (f.exists() and len(f.read_text().split()) >= wait_for):
            time.sleep(0.1)                                        # the detached job needs a moment to reach the stub
        return len(f.read_text().split()) if f.exists() else 0

    def job(self):
        return json.loads((self.out / 'word_timing.job.json').read_text())

    def done(self):
        return json.loads((self.out / 'word_timing.done.json').read_text())

    def test_incomplete_then_resume_then_instant_done(self):
        self.stub('sleep', 6)
        r = self.call('--max-wait', '2')
        self.assertEqual(75, r.returncode, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r'WORD_TIMING INCOMPLETE job=\d+')
        job = self.job()
        self.assertTrue(alive(job['pid']))                       # detached: outlives the wrapper
        self.assertFalse((self.out / 'word_timing.done.json').exists())
        self.assertEqual(1, self.calls(wait_for=1))

        r = self.call('--max-wait', '30')                        # same arguments: waits for the SAME job
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertEqual(1, self.calls())
        pages, raw = self.out / 'caption_pages.json', self.out / 'raw_asr.json'
        self.assertIn(str(pages), r.stdout)
        self.assertIn(str(raw), r.stdout)
        done = self.done()
        self.assertEqual(job['key'], done['key'])
        self.assertEqual(sha(pages), done['output_sha256'])
        self.assertEqual(sha(raw), done['raw_sha256'])
        self.assertEqual([{'rung': 'R0', 'regions': [[0.0, 1.0]], 'seconds': 1.0}], done['rungs'])
        self.assertEqual('stub-model', done['model'])
        self.assertIsInstance(done['wall_seconds'], int)
        seen = json.loads((self.out / 'env.json').read_text())
        keys = set(seen['env']) - {'__CF_USER_TEXT_ENCODING'}                      # macOS adds this one itself
        self.assertEqual({'HOME', 'PATH', 'LANG', 'TMPDIR'}, keys)               # nothing of the caller's environment reached the job
        self.assertEqual(str(self.home), seen['env']['HOME'])
        self.assertEqual('en_US.UTF-8', seen['env']['LANG'])
        self.assertEqual('/var/empty', seen['env']['TMPDIR'])                     # root-owned and empty: nothing is written there
        self.assertTrue(seen['env']['PATH'].endswith(':/usr/bin:/bin'))
        self.assertTrue(seen['env']['PATH'].startswith('/opt/homebrew/bin') or seen['env']['PATH'].startswith('/usr/'), seen['env']['PATH'])
        self.assertEqual([1, True, '/var/empty', 1], seen['flags'])               # isolated, no bytecode, nothing readable, no site
        self.assertEqual([], [p.name for p in self.out.iterdir() if '.tmp' in p.name or p.name == 'asr_tmp'])   # no private tmp dir any more
        argv = self.argv_log.read_text().splitlines()
        calls = [' '.join(a.split()[:2]) for a in argv]                           # every python call goes through the launcher: check (once per wrapper call), decode, align
        self.assertEqual('asr_transcribe.py --check', calls[0])
        self.assertEqual(1, calls.count('asr_transcribe.py --wav'))
        self.assertEqual(1, calls.count('asr_align.py --raw'))
        self.assertLess(calls.index('asr_transcribe.py --wav'), calls.index('asr_align.py --raw'))
        self.assertEqual({'asr_transcribe.py --check', 'asr_transcribe.py --fingerprint', 'asr_transcribe.py --wav', 'asr_align.py --raw'}, set(calls))


        t0 = time.time()
        r = self.call('--max-wait', '2')
        self.assertEqual(0, r.returncode)
        self.assertLess(time.time() - t0, 3)
        self.assertEqual(1, self.calls())                        # done file short-circuit: no new job

    def test_changed_script_or_tool_is_a_new_key_and_new_job(self):
        self.assertEqual(0, self.call('--max-wait', '20').returncode)
        key1, out1 = self.done()['key'], (self.out / 'caption_pages.json').read_text()
        other = self.script.with_name('script2.txt')
        other.write_text('different text\n', encoding='utf-8')
        r = self.call('--max-wait', '20', script=other)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        key2 = self.done()['key']
        self.assertNotEqual(key1, key2)
        self.assertNotEqual(out1, (self.out / 'caption_pages.json').read_text())
        self.assertEqual(2, self.calls())
        with open(self.bin / 'timing_defects.py', 'a') as f:     # a changed detector is a changed tool
            f.write('# v2\n')
        r = self.call('--max-wait', '20', script=other)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        key3 = self.done()['key']
        self.assertNotEqual(key2, key3)
        self.assertEqual(3, self.calls())
        with open(self.bin / 'asr_venv.manifest', 'a') as f:     # another manifest = another interpreter / stdlib / venv = another job
            f.write('# v2\n')
        r = self.call('--max-wait', '20', script=other)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        key4 = self.done()['key']
        self.assertNotEqual(key3, key4)
        self.assertEqual(4, self.calls())
        with open(self.bin / 'asr_run.sh', 'a') as f:            # and a changed launcher
            f.write('# v2\n')
        r = self.call('--max-wait', '20', script=other)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertNotEqual(key4, self.done()['key'])
        self.assertEqual(5, self.calls())

    def test_a_changed_toolchain_fingerprint_makes_the_same_command_a_new_job(self):
        """an OS / ffmpeg / mlx / venv update: the SAME arguments must re-transcribe (the old done file must not answer 'done' forever,
        finalize would keep refusing the old fingerprint); an identical fingerprint is still an instant done"""
        self.stub('fingerprint', '{"platform": {"release": "25.6.0"}}')
        self.assertEqual(0, self.call('--max-wait', '20').returncode)
        key1 = self.done()['key']
        self.assertEqual(1, self.calls())
        t0 = time.time()
        r = self.call('--max-wait', '2')                                   # identical fingerprint: done at once, no decode
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertEqual(1, self.calls())
        self.assertEqual(key1, self.done()['key'])
        self.assertLess(time.time() - t0, 3)
        (self.out / 'raw_asr.json').write_text('stale raw of the old toolchain\n')   # the re-run must replace it (done_ok looks at the pages only)
        self.stub('fingerprint', '{"platform": {"release": "25.7.0"}}')   # the OS was updated
        r = self.call('--max-wait', '20')
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertEqual(2, self.calls())                                  # re-transcribed
        key2 = self.done()['key']
        self.assertNotEqual(key1, key2)
        self.assertNotIn('stale raw', (self.out / 'raw_asr.json').read_text())
        self.assertEqual(sha(self.out / 'caption_pages.json'), self.done()['output_sha256'])
        r = self.call('--max-wait', '2')                                   # and the new fingerprint is an instant done again
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertEqual(2, self.calls())
        self.assertEqual(key2, self.done()['key'])

    def test_stderr_of_a_successful_fingerprint_never_changes_the_key(self):
        """a warning that differs on every call must not restart the job forever: only stdout is hashed"""
        self.stub('fingerprint_noise', 1)
        self.assertEqual(0, self.call('--max-wait', '20').returncode)
        key = self.done()['key']
        self.assertEqual(1, self.calls())
        for i in range(3):
            t0 = time.time()
            r = self.call('--max-wait', '2')
            self.assertEqual(0, r.returncode, r.stdout + r.stderr)
            self.assertEqual(key, self.done()['key'])
            self.assertIn('key:   %s' % key, r.stdout)
            self.assertLess(time.time() - t0, 3)
        self.assertEqual(1, self.calls())                                  # never decoded again
        self.assertGreaterEqual(int((self.bin / 'stub_fingerprint_noise_n').read_text()), 4)   # the noise really differed on each call

    def test_a_failed_fingerprint_is_exit_4_never_unchanged(self):
        self.assertEqual(0, self.call('--max-wait', '20').returncode)
        self.assertEqual(1, self.calls())
        self.stub('fingerprint_rc', 4)
        r = self.call('--max-wait', '2')                                   # a done file for the old key exists: still not an answer
        self.assertEqual(4, r.returncode, r.stdout + r.stderr)
        self.assertIn('the fingerprint could not be read (stub)', r.stderr)
        self.assertIn('toolchain fingerprint could not be read', r.stderr)
        self.assertEqual(1, self.calls())
        self.stub('fingerprint_rc', 0)
        self.stub('fingerprint', '')                                       # an empty answer is not a fingerprint either
        r = self.call('--max-wait', '2')
        self.assertEqual(4, r.returncode, r.stdout + r.stderr)
        self.assertEqual(1, self.calls())

    def test_job_that_dies_exits_1_with_log_tail_and_a_retry_runs(self):
        self.stub('result', 'crash')
        r = self.call('--max-wait', '20')
        self.assertEqual(1, r.returncode, r.stdout + r.stderr)
        self.assertIn('boom: fake transcription failure', r.stderr)
        self.assertFalse((self.out / 'word_timing.done.json').exists())
        self.assertFalse((self.out / 'caption_pages.json').exists())
        self.stub('result', 'ok')
        self.stub('align_fail', 1)
        r = self.call('--max-wait', '20')
        self.assertEqual(1, r.returncode, r.stdout + r.stderr)
        self.assertIn('boom: fake alignment failure', r.stderr)
        (self.bin / 'stub_align_fail').unlink()
        r = self.call('--max-wait', '20')                        # a retry starts a fresh job and succeeds
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertEqual(3, self.calls())

    def test_ladder_exhausted_exits_5_and_is_never_retried_automatically(self):
        self.stub('result', 'defective')
        r = self.call('--max-wait', '20')
        self.assertEqual(5, r.returncode, r.stdout + r.stderr)
        self.assertIn('DEFECT word-too-long at 576.720s token="tok" value=7.92 limit=4.0', r.stderr)
        self.assertIn('WORD_TIMING FAILED (exit 5)', r.stderr)
        failed = json.loads((self.out / 'word_timing.failed.json').read_text())
        self.assertEqual(self.job()['key'], failed['key'])
        self.assertFalse((self.out / 'word_timing.done.json').exists())
        self.assertFalse((self.out / 'caption_pages.json').exists())
        self.stub('result', 'ok')                                 # even if a retry WOULD now pass: never re-run
        t0 = time.time()
        r = self.call('--max-wait', '20')
        self.assertEqual(5, r.returncode, r.stdout + r.stderr)
        self.assertLess(time.time() - t0, 3)
        self.assertIn('DEFECT word-too-long at 576.720s', r.stderr)
        self.assertEqual(1, self.calls())
        other = self.script.with_name('script2.txt')             # new inputs = new key = a new job
        other.write_text('fixed script\n', encoding='utf-8')
        r = self.call('--max-wait', '20', script=other)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertFalse((self.out / 'word_timing.failed.json').exists())
        self.assertEqual(2, self.calls())

    def test_live_job_with_other_key_is_refused_and_cancel_only_kills_that_job(self):
        self.stub('sleep', 30)
        r = self.call('--max-wait', '1')
        self.assertEqual(75, r.returncode)
        pid = self.job()['pid']
        other = self.script.with_name('script2.txt')
        other.write_text('different text\n', encoding='utf-8')
        r = self.call('--max-wait', '1', script=other)
        self.assertEqual(3, r.returncode, r.stdout + r.stderr)
        self.assertEqual(1, self.calls(wait_for=1))
        self.assertTrue(alive(pid))
        r = self.call('--cancel')
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        deadline = time.time() + 10
        while alive(pid) and time.time() < deadline:
            time.sleep(0.2)
        self.assertFalse(alive(pid))
        self.assertTrue(alive(os.getpid()))

    def test_missing_venv_or_failed_pin_check_exit_4_and_nothing_starts(self):
        for name in ('asr_run.sh', 'asr_venv.manifest'):          # no launcher / no manifest = nothing can be verified: exit 4, nothing starts
            hidden = self.bin / (name + '.hidden')
            (self.bin / name).rename(hidden)
            r = self.call()
            self.assertEqual(4, r.returncode, r.stderr)
            self.assertIn('%s is missing' % name, r.stderr)
            hidden.rename(self.bin / name)
        self.stub('check_rc', 4)
        r = self.call()
        self.assertEqual(4, r.returncode, r.stderr)
        self.assertIn('mlx_whisper/decoding.py sha256', r.stderr)
        self.assertIn('environment check failed', r.stderr)
        self.assertFalse((self.out / 'word_timing.job.json').exists())
        self.assertEqual(0, self.calls())
        self.stub('check_rc', 0)
        (self.bin / 'asr_align.py').unlink()
        r = self.call()
        self.assertEqual(4, r.returncode, r.stderr)
        self.assertIn('asr_align.py is missing', r.stderr)

    def test_bad_arguments_exit_2_and_extra_tool_arguments_are_refused(self):
        env = dict(os.environ, HOME=str(self.home))
        self.assertEqual(2, subprocess.run(['/bin/bash', str(self.sh), str(self.audio)], capture_output=True, env=env).returncode)
        self.assertEqual(2, self.call('--max-wait', 'abc').returncode)
        for extra in (['--', '--model', 'other/model'], ['--model', 'other/model'], ['--max-words', '9']):
            with self.subTest(extra=extra):
                r = self.call(*extra)
                self.assertEqual(2, r.returncode, r.stderr)
        self.assertEqual(0, self.calls())
        r = subprocess.run(['/bin/bash', str(self.sh), str(self.audio) + '.missing', str(self.script), str(self.out)],
                           capture_output=True, text=True, env=env)
        self.assertEqual(2, r.returncode)

    def test_removed_environment_overrides_have_no_effect(self):
        src = SH.read_text()
        for name in ('KARAOKE_VENV', 'EXTRACT_TIMING', 'WHISPER_MODEL', 'WORD_TIMING_CMD_FOR_TEST', 'karaoke_subtitle_v2',
                     'extract_timing'):
            self.assertNotIn(name, src)
        r = self.call('--max-wait', '20', env_extra={'KARAOKE_VENV': '/nonexistent', 'EXTRACT_TIMING': '/bin/false',
                                                     'WHISPER_MODEL': 'nobody/x', 'WORD_TIMING_CMD_FOR_TEST': '/bin/false'})
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertEqual(1, self.calls())
        self.assertTrue(self.argv_log.read_text().strip())        # the fixed venv python ran the tools

    def test_a_failed_run_never_leaves_the_previous_runs_raw_or_pages_behind(self):
        self.assertEqual(0, self.call('--max-wait', '20').returncode)
        raw, pages = self.out / 'raw_asr.json', self.out / 'caption_pages.json'
        self.assertTrue(raw.exists() and pages.exists())
        other = self.script.with_name('script2.txt')
        other.write_text('a new script\n', encoding='utf-8')
        for mode, rc in (('crash', 1), ('rc4', 1), ('defective', 5)):                                    # a dead job = exit 1 + log tail
            with self.subTest(mode=mode):
                self.stub('result', mode)
                r = self.call('--max-wait', '20', script=other)
                self.assertEqual(rc, r.returncode, r.stdout + r.stderr)
                self.assertFalse(raw.exists(), 'raw_asr.json of the previous run survived a failed run (%s)' % mode)
                self.assertFalse(pages.exists(), 'caption_pages.json of the previous run survived a failed run (%s)' % mode)
                self.assertFalse((self.out / 'word_timing.done.json').exists())
                if mode != 'defective':
                    self.assertFalse((self.out / 'word_timing.failed.json').exists())
                other.write_text(other.read_text() + 'x\n', encoding='utf-8')                         # next mode = new key = new job
        # exit 2 of the aligner: the raw of THIS run exists, the previous run's pages do not
        self.stub('result', 'ok')
        self.assertEqual(0, self.call('--max-wait', '20', script=other).returncode)
        self.assertTrue(pages.exists())
        other.write_text(other.read_text() + 'y\n', encoding='utf-8')
        self.stub('align_fail', 1)
        r = self.call('--max-wait', '20', script=other)
        self.assertNotEqual(0, r.returncode)
        self.assertFalse(pages.exists())
        self.assertTrue(raw.exists())

    def test_same_job_still_resumes_from_its_checkpoints(self):
        """only the raw / pages / done / failed files are removed at the start of a job: asr_rung_*.json checkpoints stay"""
        self.out.mkdir(exist_ok=True)
        (self.out / 'asr_rung_R0.json').write_text('{"checkpoint": true}')
        self.assertEqual(0, self.call('--max-wait', '20').returncode)
        self.assertEqual('{"checkpoint": true}', (self.out / 'asr_rung_R0.json').read_text())

    def test_pages_edited_after_the_job_are_not_reported_done(self):
        self.assertEqual(0, self.call('--max-wait', '20').returncode)
        pages = self.out / 'caption_pages.json'
        good = pages.read_text()
        self.assertEqual(1, self.calls())
        r = self.call('--max-wait', '20')                                  # untouched: instant, no new job
        self.assertEqual(0, r.returncode)
        self.assertEqual(1, self.calls())
        pages.write_text(good.replace('"s": 0', '"s": 0.5'))              # an agent edits the word times
        self.assertNotEqual(good, pages.read_text())
        r = self.call('--max-wait', '20')
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertEqual(2, self.calls())                                  # a NEW job ran: the edit was not accepted as "done"
        self.assertEqual(good, pages.read_text())                          # and its output replaced the edited file
        self.assertEqual(sha(pages), self.done()['output_sha256'])

    def test_hostile_python_and_perl_and_path_environment_changes_nothing(self):
        marker = Path(self.tmp.name) / 'marker'
        evil = Path(self.tmp.name) / 'evil'
        evil.mkdir()
        (evil / 'sitecustomize.py').write_text('open(%r, "a").write("sitecustomize ")\n' % str(marker))
        fake_bin = Path(self.tmp.name) / 'fakebin'
        fake_bin.mkdir()
        (fake_bin / 'ffmpeg').write_text('#!/bin/sh\necho fake-ffmpeg >> %s\nexit 1\n' % marker)
        (fake_bin / 'ffmpeg').chmod(0o755)
        (evil / 'perlevil.pm').write_text('open(F, ">>%s"); print F "perl "; close F; 1;\n' % marker)
        r = self.call('--max-wait', '30', env_extra={
            'PYTHONPATH': str(evil), 'PYTHONSTARTUP': str(evil / 'sitecustomize.py'), 'PYTHONHOME': '/nonexistent',
            'PERL5OPT': '-I%s -Mperlevil' % evil, 'PERL5LIB': str(evil), 'PYTHONDONTWRITEBYTECODE': '', 'PYTHONPYCACHEPREFIX': str(evil),
            'PATH': '%s:%s' % (fake_bin, os.environ['PATH']), 'DYLD_LIBRARY_PATH': '/nonexistent', 'HF_HUB_OFFLINE': '0',
            'TMPDIR': '/nonexistent', 'HF_HOME': '/nonexistent'})
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertFalse(marker.exists(), marker.read_text() if marker.exists() else '')          # no PYTHONPATH / PERL5OPT / fake ffmpeg ran
        seen = json.loads((self.out / 'env.json').read_text())
        self.assertNotIn(str(fake_bin), seen['env']['PATH'])
        self.assertEqual({'HOME', 'PATH', 'LANG', 'TMPDIR'}, set(seen['env']) - {'__CF_USER_TEXT_ENCODING'})
        for leaked in ('PYTHONPATH', 'PYTHONHOME', 'PERL5OPT', 'HF_HOME', 'HF_HUB_OFFLINE', 'DYLD_LIBRARY_PATH'):
            self.assertNotIn(leaked, seen['env'])
        self.assertEqual('/var/empty', seen['env']['TMPDIR'])

    def test_home_variable_changes_nothing(self):
        """An UNMODIFIED copy of the real script with HOME pointing at a temp dir: the home it uses comes from the passwd entry
        (the venv / manifest / python are the launcher's business and its constants; test_asr_run.py shows it ignores $HOME)."""
        real_copy = self.bin / 'word_timing_real.sh'
        shutil.copy(SH, real_copy)
        text = real_copy.read_text()
        self.assertEqual(1, len(re.findall(r'^PW_HOME=', text, flags=re.M)))
        self.assertIn('getpwuid', text)
        self.assertNotIn(str(self.home), text)
        r = self.call('--max-wait', '60', sh=real_copy, env_extra={'HOME': str(Path(self.tmp.name) / 'no-such-home')})
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        seen = json.loads((self.out / 'env.json').read_text())
        self.assertNotEqual(str(Path(self.tmp.name) / 'no-such-home'), seen['env']['HOME'])

    def test_ffmpeg_comes_from_a_fixed_list_not_from_path(self):
        src = SH.read_text()
        self.assertIn('FFMPEG_CANDIDATES=(/opt/homebrew/bin/ffmpeg /usr/local/bin/ffmpeg /usr/bin/ffmpeg)', src)
        self.assertNotIn('command -v ffmpeg', src)
        self.assertEqual([], re.findall(r'^\s*ffmpeg ', src, flags=re.M))               # never a bare `ffmpeg` call
        self.assertNotIn('$HOME', re.sub(r'#.*', '', src))                              # never $HOME in code (comments may name it)
        for line in src.splitlines():
            if re.search(r'\bpython3\b', line) and not line.lstrip().startswith('#'):
                self.assertTrue('/usr/bin/python3 -I -B' in line or '[ -x /usr/bin/python3 ]' in line, line)   # every helper python is isolated

    def test_every_helper_is_an_absolute_path_never_found_through_PATH(self):
        """N6: no bare `python3` / `bash` / `shasum` / `perl` / `ps` / `date` ... command in word_timing.sh or asr_run.sh (shell builtins
        cd / kill excepted, text inside echo messages and heredoc bodies ignored)"""
        bare = re.compile(r'(?:^|[\s;&|(`{])(python3|bash|shasum|perl|ps|date|sleep|grep|tail|head|cut|tr|rm|mkdir|rmdir|nohup|dirname|basename|'
                          r'env|find|sort|xargs|sed|diff|wc|mv|cat|awk|ls|command)(?=\s|$|\))')
        for name in ('word_timing.sh', 'asr_run.sh'):
            heredoc, hits = None, []
            for n, line in enumerate((SCRIPTS / name).read_text(encoding='utf-8').splitlines(), 1):
                if heredoc:
                    heredoc = None if line.strip() == heredoc else heredoc
                    continue
                m = re.search(r"<<'?(\w+)'?", line)
                if not line.lstrip().startswith('#'):
                    code = re.sub(r'echo\s+"[^"]*"', 'echo', line)
                    hits += [(n, h.group(1)) for h in bare.finditer(code)]
                if m:
                    heredoc = m.group(1)
            self.assertEqual([], hits, name)
        self.assertEqual(0, len(re.findall(r'^PYBIN=|karaoke', (SCRIPTS / 'word_timing.sh').read_text(encoding='utf-8'), flags=re.M)))


if __name__ == '__main__':
    unittest.main()
