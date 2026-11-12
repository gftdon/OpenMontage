"""fetch_broll.py (V4): footage mode refused by a code guard, --music is the only mode.
No network: the registry tool is a stub, sleeping/ffprobe are patched (one test uses the real ffprobe on local bytes)."""
import contextlib
import datetime
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import fetch_broll as fb  # noqa: E402

REFUSAL = 'V4: stock footage fetching is disabled (no verified relevance verdicts); only --music is available'
AUDIO = b'ID3-not-really-mp3-but-fake-tool-wrote-it' * 50


class FakeTool:
    """Stub of the registry's pixabay_music tool. `script` = list of behaviours, consumed one per execute()."""

    def __init__(self, script, status='available', data=None):
        self.script, self.calls, self.status = list(script), [], status
        self.data = data if data is not None else {'provider': 'pixabay_music', 'track_title': 'Calm Tech', 'artist': 'someone'}

    def get_status(self):
        return SimpleNamespace(value=self.status)

    def execute(self, inputs):
        self.calls.append(inputs)
        step = self.script.pop(0) if self.script else self.script_default
        if isinstance(step, Exception):
            raise step
        if step == 'ok':
            Path(inputs['output_path']).write_bytes(AUDIO)
            return SimpleNamespace(success=True, error=None, data=dict(self.data, output=inputs['output_path']))
        if step == 'empty':
            Path(inputs['output_path']).write_bytes(b'')
            return SimpleNamespace(success=True, error=None, data=dict(self.data))
        return SimpleNamespace(success=False, error=step, data={})

    script_default = 'ok'


class Env:
    """Patches the stub registry tool, ffprobe and the clock; collects what main() printed."""

    def __init__(self, tool, probe=(True, 120.0)):
        self.tool, self.probe, self.sleeps, self.now = tool, probe, [], 0.0

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s

    def run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as st:
            st.enter_context(patch.object(fb, 'get_music_tool', lambda: self.tool))
            if self.probe is not None:
                st.enter_context(patch.object(fb, 'probe_audio', lambda p: self.probe))
            st.enter_context(patch.object(fb, '_sleep', self.sleep))
            st.enter_context(patch.object(fb, '_monotonic', lambda: self.now))
            st.enter_context(contextlib.redirect_stdout(out))
            st.enter_context(contextlib.redirect_stderr(err))
            rc = fb.main(list(argv))
        return rc, out.getvalue(), err.getvalue()


class FootageGuardTests(unittest.TestCase):
    def test_every_footage_form_is_refused_with_exit_3(self):
        with tempfile.TemporaryDirectory() as d:
            q = Path(d) / 'q.json'
            q.write_text('{"a": ["query", ""]}')
            plan = Path(d) / 'plan.json'
            plan.write_text('{}')
            tool = FakeTool([])
            forms = [[str(q), d], [str(q), d, '--dry-run'], ['--dry-run', str(q), d], ['--plan', str(plan), '--context', str(plan), d],
                     ['--plan', str(plan)], [str(q)], [str(q), d, '--music', 'calm', str(Path(d) / 'bed.mp3')]]
            for argv in forms:
                rc, out, err = Env(tool).run(*argv)
                self.assertEqual(3, rc, argv)
                self.assertEqual(REFUSAL, err.strip(), argv)
            self.assertEqual([], tool.calls)  # nothing was fetched, not even the music of a mixed call
            self.assertFalse((Path(d) / 'bed.mp3').exists())

    def test_the_library_function_is_guarded_too(self):
        with self.assertRaises(fb.FootageDisabled) as cm:
            fb.fetch_videos({'a': ['q', '']}, 'projects/x/assets/broll')
        self.assertEqual(REFUSAL, str(cm.exception))


class MusicTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / 'assets/audio/bed.mp3'
        self.side = Path(str(self.out) + '.source.json')

    def leftovers(self):
        return sorted(p.name for p in self.out.parent.glob('*')) if self.out.parent.exists() else []

    def test_success_writes_mp3_and_sidecar_with_matching_sha(self):
        tool = FakeTool(['ok'])
        rc, out, err = Env(tool).run('--music', 'calm tech', str(self.out))
        self.assertEqual((0, ''), (rc, err), err)
        self.assertEqual(AUDIO, self.out.read_bytes())
        side = json.loads(self.side.read_text())
        self.assertEqual({'schema', 'provider', 'track_id', 'track_title', 'url', 'query', 'sha256', 'fetched_at'}, set(side))
        self.assertEqual(('yt-news-v4-music-source', 'pixabay_music', 'Calm Tech', 'calm tech'),
                         (side['schema'], side['provider'], side['track_title'], side['query']))
        self.assertEqual(hashlib.sha256(AUDIO).hexdigest(), side['sha256'])
        self.assertIsNone(side['track_id'])   # the provider returned none: null, never invented
        self.assertIsNone(side['url'])
        when = datetime.datetime.fromisoformat(side['fetched_at'])
        self.assertEqual(datetime.timedelta(0), when.utcoffset())
        self.assertEqual(['bed.mp3', 'bed.mp3.source.json'], self.leftovers())  # no .part left behind
        self.assertEqual(1, len(tool.calls))
        self.assertEqual('calm tech', tool.calls[0]['query'])

    def test_id_and_url_are_taken_from_the_tool_data_when_present(self):
        tool = FakeTool(['ok'], data={'track_title': 'T', 'pixabay_id': 4711, 'url': 'https://pixabay.com/music/x-4711/'})
        self.assertEqual(0, Env(tool).run('--music', 'q', str(self.out))[0])
        side = json.loads(self.side.read_text())
        self.assertEqual((4711, 'https://pixabay.com/music/x-4711/'), (side['track_id'], side['url']))

    def test_retry_then_success(self):
        tool = FakeTool(['Pixabay music search failed: HTTP Error 503: Service Unavailable', 'Pixabay music search failed: timed out', 'ok'])
        env = Env(tool)
        rc, _, err = env.run('--music', 'q', str(self.out))
        self.assertEqual(0, rc, err)
        self.assertEqual(3, len(tool.calls))
        self.assertEqual(2, len(env.sleeps))
        self.assertTrue(all(s > 0 for s in env.sleeps) and env.sleeps[1] >= env.sleeps[0])  # backoff
        self.assertTrue(self.out.exists() and self.side.exists())

    def test_exceptions_from_the_network_are_transient(self):
        tool = FakeTool([ConnectionResetError('reset'), TimeoutError('slow'), 'ok'])
        self.assertEqual(0, Env(tool).run('--music', 'q', str(self.out))[0])

    def test_retry_budget_exhausted_exits_4_with_no_files(self):
        self.assertEqual(180, fb.MUSIC_RETRY_BUDGET_SECONDS)
        tool = FakeTool([])
        tool.script_default = 'Pixabay music search failed: HTTP Error 429: Too Many Requests'
        env = Env(tool)
        rc, _, err = env.run('--music', 'q', str(self.out))
        self.assertEqual(4, rc)
        self.assertEqual(1, len(err.strip().splitlines()))
        self.assertIn('429', err)
        self.assertLessEqual(sum(env.sleeps), 180)
        self.assertGreater(len(tool.calls), 3)
        self.assertEqual([], self.leftovers())

    def test_non_transient_failure_does_not_retry(self):
        tool = FakeTool(['No music found on Pixabay for query: zzz'])
        env = Env(tool)
        rc, _, err = env.run('--music', 'zzz', str(self.out))
        self.assertEqual((4, 1, []), (rc, len(tool.calls), env.sleeps))
        self.assertIn('No music found', err)

    def test_missing_key_exits_4_immediately(self):
        tool = FakeTool([], status='unavailable')
        env = Env(tool)
        rc, _, err = env.run('--music', 'q', str(self.out))
        self.assertEqual((4, [], 1), (rc, tool.calls, len(err.strip().splitlines())))
        self.assertEqual([], env.sleeps)
        tool = FakeTool(['PIXABAY_API_KEY not set'])
        env = Env(tool)
        rc, _, err = env.run('--music', 'q', str(self.out))
        self.assertEqual((4, 1, []), (rc, len(tool.calls), env.sleeps))
        self.assertIn('API', err)
        self.assertEqual([], self.leftovers())

    def test_invalid_audio_exits_4_and_removes_partial_files(self):
        cases = [('empty', (True, 120.0)), ('ok', (False, 0)), ('ok', (True, 12.0)), ('ok', None)]
        for step, probe in cases:
            self.side.parent.mkdir(parents=True, exist_ok=True)
            tool = FakeTool([step])
            rc, _, err = Env(tool, probe=probe).run('--music', 'q', str(self.out))   # probe None: the REAL ffprobe on fake bytes
            self.assertEqual(4, rc, (step, probe, err))
            self.assertEqual(1, len(err.strip().splitlines()))
            self.assertEqual([], self.leftovers(), (step, probe))

    def test_no_overwrite_without_force(self):
        self.out.parent.mkdir(parents=True)
        self.out.write_bytes(b'previous bed')
        tool = FakeTool(['ok'])
        rc, _, err = Env(tool).run('--music', 'q', str(self.out))
        self.assertEqual(2, rc)
        self.assertIn('--force', err)
        self.assertEqual((b'previous bed', []), (self.out.read_bytes(), tool.calls))
        self.assertFalse(self.side.exists())
        rc, _, err = Env(FakeTool(['ok'])).run('--music', 'q', str(self.out), '--force')
        self.assertEqual(0, rc, err)
        self.assertEqual(AUDIO, self.out.read_bytes())
        self.assertEqual(hashlib.sha256(AUDIO).hexdigest(), json.loads(self.side.read_text())['sha256'])

    def test_force_failure_keeps_the_previous_valid_pair(self):
        self.out.parent.mkdir(parents=True)
        self.out.write_bytes(b'previous bed')
        self.side.write_text('{"keep": true}')
        rc, _, _ = Env(FakeTool(['empty'])).run('--music', 'q', str(self.out), '--force')
        self.assertEqual(4, rc)
        self.assertEqual((b'previous bed', '{"keep": true}'), (self.out.read_bytes(), self.side.read_text()))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg/ffprobe needed')
    def test_real_ffprobe_accepts_a_30s_audio_file_and_rejects_short_or_garbage(self):
        tone = Path(self.tmp.name) / 'tone.mp3'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=31', str(tone)], check=True)
        has_audio, duration = fb.probe_audio(tone)
        self.assertTrue(has_audio)
        self.assertGreaterEqual(duration, 30)
        short = Path(self.tmp.name) / 'short.mp3'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=5', str(short)], check=True)
        self.assertLess(fb.probe_audio(short)[1], 30)
        garbage = Path(self.tmp.name) / 'g.mp3'
        garbage.write_bytes(b'<html>not audio</html>')
        self.assertEqual((False, 0.0), fb.probe_audio(garbage))


if __name__ == '__main__':
    unittest.main()
