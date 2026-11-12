"""word_timing.sh: resumable, detached, keyed alignment job. The real alignment (6 min) is never run here:
WORD_TIMING_CMD_FOR_TEST injects a fake `--wav W --script S --out O` command."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
import wave

SCRIPTS = Path(__file__).resolve().parents[1]
SH = SCRIPTS / 'word_timing.sh'

FAKE = r'''#!/bin/bash
while [ $# -gt 0 ]; do case "$1" in --wav) W="$2";; --script) S="$2";; --out) O="$2";; esac; shift 2; done
echo started >> "$(dirname "$O")/calls.log"
echo "$HF_HUB_OFFLINE $TRANSFORMERS_OFFLINE" > "$(dirname "$O")/env.txt"
sleep "${FAKE_SLEEP:-0}"
if [ "${FAKE_FAIL:-}" = 1 ]; then echo "boom: fake alignment failure" >&2; exit 3; fi
printf '[{"start":0,"end":1,"words":[{"w":"%s","s":0,"e":1}]}]' "$(shasum -a 256 "$S" | cut -c1-8)" > "$O"
'''


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class WordTimingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.audio = d / 'a.wav'
        with wave.open(str(self.audio), 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b'\x00\x00' * 16000)
        self.script = d / 'script.txt'
        self.script.write_text('line one\nline two\n', encoding='utf-8')
        self.fake = d / 'fake_align.sh'
        self.fake.write_text(FAKE)
        self.fake.chmod(0o755)
        self.out = d / 'out'

    def tearDown(self):
        self.call('--cancel')
        self.tmp.cleanup()

    def call(self, *extra, sleep='0', fail=False, env_extra=None, script=None):
        env = dict(os.environ, WORD_TIMING_CMD_FOR_TEST=str(self.fake), FAKE_SLEEP=sleep)
        if fail:
            env['FAKE_FAIL'] = '1'
        env.update(env_extra or {})
        return subprocess.run(['bash', str(SH), str(self.audio), str(script or self.script), str(self.out), *extra],
                              capture_output=True, text=True, env=env, timeout=120)

    def calls(self, wait_for=0):
        f = self.out / 'calls.log'
        deadline = time.time() + 6
        while wait_for and time.time() < deadline and not (f.exists() and len(f.read_text().split()) >= wait_for):
            time.sleep(0.1)                                        # the detached job needs a moment to reach the fake
        return len(f.read_text().split()) if f.exists() else 0

    def job(self):
        return json.loads((self.out / 'word_timing.job.json').read_text())

    def done(self):
        return json.loads((self.out / 'word_timing.done.json').read_text())

    def test_incomplete_then_resume_then_instant_done(self):
        r = self.call('--max-wait', '2', sleep='6')
        self.assertEqual(75, r.returncode, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r'WORD_TIMING INCOMPLETE job=\d+')
        job = self.job()
        self.assertTrue(alive(job['pid']))                       # detached: outlives the wrapper
        self.assertFalse((self.out / 'word_timing.done.json').exists())
        self.assertEqual(1, self.calls(wait_for=1))

        r = self.call('--max-wait', '30', sleep='6')             # same arguments: waits for the SAME job
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertEqual(1, self.calls())
        pages = self.out / 'caption_pages.json'
        self.assertIn(str(pages), r.stdout)
        self.assertTrue(pages.exists())
        self.assertEqual(job['key'], self.done()['key'])
        done = self.done()
        self.assertEqual({'key', 'output', 'output_sha256', 'wall_seconds', 'model'}, set(done) & {'key', 'output', 'output_sha256', 'wall_seconds', 'model'})
        self.assertEqual(64, len(done['output_sha256']))
        self.assertEqual('1 1', (self.out / 'env.txt').read_text().strip())   # offline env reached the job
        self.assertEqual([], [p.name for p in self.out.iterdir() if '.tmp' in p.name])

        t0 = time.time()
        r = self.call('--max-wait', '2', sleep='6')
        self.assertEqual(0, r.returncode)
        self.assertLess(time.time() - t0, 3)
        self.assertEqual(1, self.calls())                        # done file short-circuit: no new job

    def test_changed_script_is_a_new_key_and_new_job(self):
        self.assertEqual(0, self.call('--max-wait', '20').returncode)
        key1, out1 = self.done()['key'], (self.out / 'caption_pages.json').read_text()
        other = self.script.with_name('script2.txt')
        other.write_text('different text\n', encoding='utf-8')
        r = self.call('--max-wait', '20', script=other)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertNotEqual(key1, self.done()['key'])
        self.assertNotEqual(out1, (self.out / 'caption_pages.json').read_text())
        self.assertEqual(2, self.calls())

    def test_job_that_dies_without_done_file_exits_1_with_log_tail(self):
        r = self.call('--max-wait', '20', fail=True)
        self.assertEqual(1, r.returncode, r.stdout + r.stderr)
        self.assertIn('boom: fake alignment failure', r.stderr)
        self.assertFalse((self.out / 'word_timing.done.json').exists())
        self.assertFalse((self.out / 'caption_pages.json').exists())
        r = self.call('--max-wait', '20')                        # a retry starts a fresh job and succeeds
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertEqual(2, self.calls())

    def test_live_job_with_other_key_is_refused_and_cancel_only_kills_that_job(self):
        r = self.call('--max-wait', '1', sleep='30')
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

    def test_missing_venv_tool_or_model_exit_4_and_bad_args_exit_2(self):
        env = {k: v for k, v in os.environ.items() if k != 'WORD_TIMING_CMD_FOR_TEST'}
        env['KARAOKE_VENV'] = str(Path(self.tmp.name) / 'no-venv')
        r = subprocess.run(['bash', str(SH), str(self.audio), str(self.script), str(self.out)], capture_output=True, text=True, env=env)
        self.assertEqual(4, r.returncode, r.stderr)
        self.assertIn('venv', r.stderr)
        self.assertFalse((self.out / 'word_timing.job.json').exists())
        env = dict(os.environ, WHISPER_MODEL='nobody/not-cached')
        env.pop('WORD_TIMING_CMD_FOR_TEST', None)
        r = subprocess.run(['bash', str(SH), str(self.audio), str(self.script), str(self.out)], capture_output=True, text=True, env=env)
        self.assertEqual(4, r.returncode, r.stderr)
        self.assertIn('not in the local HF cache', r.stderr)
        self.assertEqual(2, subprocess.run(['bash', str(SH), str(self.audio)], capture_output=True).returncode)
        self.assertEqual(2, self.call('--max-wait', 'abc').returncode)


if __name__ == '__main__':
    unittest.main()
