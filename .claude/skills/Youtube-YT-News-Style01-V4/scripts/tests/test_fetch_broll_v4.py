"""fetch_broll.py (V4): footage mode refused by a code guard, --music is the only mode.
No network: the registry tool is a stub, sleeping/ffprobe are patched (one test uses the real ffprobe on local bytes)."""
import contextlib
import datetime
import hashlib
import io
import json
import os
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
import music_library as ml  # noqa: E402

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


_EMPTY_DIR = tempfile.TemporaryDirectory()
EMPTY_MANIFEST = Path(_EMPTY_DIR.name) / 'music_library.json'
EMPTY_MANIFEST.write_text(json.dumps({'schema': 'yt-news-v4-music-library', 'version': 1, 'tracks': []}) + '\n')


class Env:
    """Patches the stub registry tool, ffprobe and the clock; collects what main() printed."""

    def __init__(self, tool, probe=(True, 120.0), manifest=None, library=None):
        self.tool, self.probe, self.sleeps, self.now = tool, probe, [], 0.0
        # manifest: path of a temp music_library.json (default: an EMPTY one, never the shipped list); library: absolute dir
        self.manifest, self.library = manifest or EMPTY_MANIFEST, library

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
            st.enter_context(patch.dict(os.environ))
            os.environ.pop('MUSIC_LIBRARY_DIR', None)
            if self.library is not None:
                os.environ['MUSIC_LIBRARY_DIR'] = str(self.library)
            st.enter_context(patch.object(ml, 'manifest_path', lambda: self.manifest))
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
        self.assertIn('music provider refused the request (HTTP 401/403: blocked or not authorised; this tool uses no API key)', err)
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


LIB_A, LIB_B = b'approved-bed-A' * 400, b'approved-bed-B' * 400
PIXABAY_403 = 'Pixabay music search failed: 403 Client Error: Forbidden for url: https://pixabay.com/api/music/'
NOT_TRIED = 'Pixabay is not tried because the approved list is not empty'


def lib_sha(b):
    return hashlib.sha256(b).hexdigest()


def lib_track(file, data, **kw):
    t = {'sha256': lib_sha(data), 'file': file, 'title': f'Approved {file}', 'license': 'owner licence',
         'origin': 'purchase receipt #42', 'approved_by': 'owner', 'approved_on': '2026-11-12', 'duration_sec': 150}
    t.update(kw)
    return t


class LibraryFirstTests(unittest.TestCase):
    """The approved list decides: non-empty = library only (Pixabay never called); empty = Pixabay."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / 'assets/audio/bed.mp3'
        self.side = Path(str(self.out) + '.source.json')
        self.lib = self.root / 'lib'
        self.lib.mkdir()

    def manifest(self, *tracks):
        p = self.root / 'music_library.json'
        p.write_text(json.dumps({'schema': ml.MANIFEST_SCHEMA, 'version': 1, 'tracks': list(tracks)}, indent=2) + '\n')
        return p

    def run_fb(self, tool, manifest, *extra, library=None):
        return Env(tool, manifest=manifest, library=library or self.lib).run('--music', 'calm tech', str(self.out), *extra)

    def leftovers(self):
        return sorted(p.name for p in self.out.parent.glob('*')) if self.out.parent.exists() else []

    def assert_exit4_clean(self, rc, out, err, *reasons):
        self.assertEqual(4, rc, (out, err))
        self.assertEqual(1, len(err.strip().splitlines()), err)
        self.assertTrue(err.startswith('ERROR:'), err)
        self.assertTrue(err.strip().endswith('no music bed was written'), err)
        for r in reasons:
            self.assertIn(r, err)
        self.assertEqual([], self.leftovers())
        self.assertFalse(self.out.exists() or self.side.exists())

    # ---- non-empty list: library only
    def test_non_empty_list_uses_the_library_and_never_calls_pixabay(self):
        (self.lib / 'a.mp3').write_bytes(LIB_A)
        m = self.manifest(lib_track('a.mp3', LIB_A))
        before = ((self.lib / 'a.mp3').stat().st_mtime_ns, lib_sha(LIB_A))
        tool = FakeTool(['ok'])           # would succeed, must not be asked
        rc, out, err = self.run_fb(tool, m)
        self.assertEqual((0, ''), (rc, err), err)
        self.assertEqual([], tool.calls)
        self.assertEqual(LIB_A, self.out.read_bytes())
        side = json.loads(self.side.read_text())
        self.assertEqual({'schema', 'provider', 'track_id', 'track_title', 'url', 'query', 'sha256', 'fetched_at', 'library_file',
                          'license', 'origin', 'approved_by', 'approved_on', 'manifest_sha256'}, set(side))
        self.assertNotIn('fallback_reason', side)
        self.assertEqual(('yt-news-v4-music-source', 'music_library', 'calm tech', lib_sha(LIB_A)),
                         (side['schema'], side['provider'], side['query'], side['sha256']))
        self.assertEqual(('a.mp3', 'Approved a.mp3', 'owner licence', 'purchase receipt #42', 'owner', '2026-11-12'),
                         (side['library_file'], side['track_title'], side['license'], side['origin'], side['approved_by'], side['approved_on']))
        self.assertIsNone(side['track_id'])
        self.assertIsNone(side['url'])
        self.assertEqual(hashlib.sha256(m.read_bytes()).hexdigest(), side['manifest_sha256'])
        self.assertEqual(datetime.timedelta(0), datetime.datetime.fromisoformat(side['fetched_at']).utcoffset())
        lines = out.strip().splitlines()
        self.assertEqual(1, len(lines), out)
        self.assertEqual(f"music OK library track a.mp3 (Approved a.mp3) sha256={lib_sha(LIB_A)[:12]} -> {self.out} (+ .source.json)", lines[0])
        self.assertEqual(['bed.mp3', 'bed.mp3.source.json'], self.leftovers())
        # the library file itself is never modified or moved
        self.assertEqual(before, ((self.lib / 'a.mp3').stat().st_mtime_ns, lib_sha((self.lib / 'a.mp3').read_bytes())))
        self.assertEqual(['a.mp3'], sorted(p.name for p in self.lib.iterdir()))

    def test_non_empty_list_file_missing_exits_4_without_trying_pixabay(self):
        tool = FakeTool(['ok'])
        rc, out, err = self.run_fb(tool, self.manifest(lib_track('a.mp3', LIB_A)))
        self.assert_exit4_clean(rc, out, err, 'music library:', 'a.mp3: missing', NOT_TRIED)
        self.assertEqual([], tool.calls)

    def test_non_empty_list_sha_mismatch_exits_4_without_trying_pixabay(self):
        (self.lib / 'a.mp3').write_bytes(b'someone replaced me')
        tool = FakeTool(['ok'])
        rc, out, err = self.run_fb(tool, self.manifest(lib_track('a.mp3', LIB_A)))
        self.assert_exit4_clean(rc, out, err, 'music library:', 'a.mp3: sha-mismatch', NOT_TRIED)
        self.assertEqual([], tool.calls)
        self.assertEqual(b'someone replaced me', (self.lib / 'a.mp3').read_bytes())

    def test_first_track_unusable_second_usable_second_is_used(self):
        (self.lib / 'a.mp3').write_bytes(b'tampered')
        (self.lib / 'b.mp3').write_bytes(LIB_B)
        tool = FakeTool(['ok'])
        rc, out, err = self.run_fb(tool, self.manifest(lib_track('a.mp3', LIB_A), lib_track('b.mp3', LIB_B)))
        self.assertEqual(0, rc, err)
        self.assertEqual(([], LIB_B), (tool.calls, self.out.read_bytes()))
        self.assertEqual('b.mp3', json.loads(self.side.read_text())['library_file'])

    def test_first_usable_track_in_list_order_wins(self):
        (self.lib / 'a.mp3').write_bytes(LIB_A)
        (self.lib / 'b.mp3').write_bytes(LIB_B)
        rc, _, err = self.run_fb(FakeTool([]), self.manifest(lib_track('b.mp3', LIB_B), lib_track('a.mp3', LIB_A)))
        self.assertEqual((0, LIB_B), (rc, self.out.read_bytes()), err)

    def test_the_copy_is_verified_and_a_mismatch_removes_it(self):
        (self.lib / 'a.mp3').write_bytes(LIB_A)
        m = self.manifest(lib_track('a.mp3', LIB_A))
        real = ml.sha256_file
        calls = []

        def flaky(path):          # the pick sees the true file, the check of the delivered copy sees a corrupted one
            calls.append(path)
            return real(path) if len(calls) == 1 else 'f' * 64
        tool = FakeTool(['ok'])
        with patch.object(ml, 'sha256_file', flaky):
            rc, out, err = self.run_fb(tool, m)
        self.assert_exit4_clean(rc, out, err, 'music library:', 'sha256', NOT_TRIED)
        self.assertEqual([], tool.calls)

    # ---- invalid list / directory: stop before anything is fetched
    def test_invalid_manifest_exits_4_and_pixabay_is_not_called(self):
        bad = self.root / 'bad.json'
        bad.write_text('{"schema": "nope"}')
        tool = FakeTool(['ok'])
        rc, out, err = self.run_fb(tool, bad)
        self.assert_exit4_clean(rc, out, err, 'ERROR: music library: ', 'keys must be exactly')
        self.assertEqual([], tool.calls)
        for broken in (self.root / 'absent.json',):
            rc, out, err = self.run_fb(tool, broken)
            self.assert_exit4_clean(rc, out, err, 'ERROR: music library: ')
        self.assertEqual([], tool.calls)

    def test_invalid_music_library_dir_exits_4_and_pixabay_is_not_called(self):
        for m in (self.manifest(lib_track('a.mp3', LIB_A)), self.manifest()):
            tool = FakeTool(['ok'])
            rc, out, err = Env(tool, manifest=m, library='relative/dir').run('--music', 'q', str(self.out))
            self.assert_exit4_clean(rc, out, err, 'ERROR: music library: ', 'MUSIC_LIBRARY_DIR')
            self.assertEqual([], tool.calls)

    # ---- empty list: Pixabay as before
    def test_empty_list_and_pixabay_ok_gives_the_pixabay_sidecar(self):
        tool = FakeTool(['ok'])
        rc, out, err = self.run_fb(tool, self.manifest())
        self.assertEqual((0, ''), (rc, err), err)
        self.assertEqual(1, len(tool.calls))
        side = json.loads(self.side.read_text())
        self.assertEqual('pixabay_music', side['provider'])
        self.assertNotIn('library_file', side)
        self.assertEqual(AUDIO, self.out.read_bytes())

    def test_empty_list_and_pixabay_fails_exits_4_with_both_reasons(self):
        rc, out, err = self.run_fb(FakeTool([PIXABAY_403]), self.manifest())
        self.assert_exit4_clean(rc, out, err, 'ERROR: Pixabay: ', '403', 'HTTP 401/403: blocked or not authorised; this tool uses no API key',
                                '; music library: music library is empty')
        self.assertNotIn('API key missing', err)

    def test_empty_list_pixabay_retries_then_exits_4(self):
        tool = FakeTool([])
        tool.script_default = 'Pixabay music search failed: timed out'
        rc, out, err = self.run_fb(tool, self.manifest())
        self.assert_exit4_clean(rc, out, err, 'timed out', 'music library is empty')
        self.assertGreater(len(tool.calls), 3)

    # ---- directory selection and seam
    def test_music_library_dir_override_is_used(self):
        other = self.root / 'other-lib'
        other.mkdir()
        (other / 'a.mp3').write_bytes(LIB_A)
        m = self.manifest(lib_track('a.mp3', LIB_A))
        rc, _, err = self.run_fb(FakeTool([]), m, library=other)
        self.assertEqual(0, rc, err)
        self.assertEqual(LIB_A, self.out.read_bytes())

    def test_default_library_dir_is_music_library_under_the_cwd_repo_root(self):
        (self.root / 'music_library').mkdir()
        (self.root / 'music_library' / 'a.mp3').write_bytes(LIB_A)
        env = Env(FakeTool([]), manifest=self.manifest(lib_track('a.mp3', LIB_A)))
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            rc, _, err = env.run('--music', 'q', str(self.out))
        finally:
            os.chdir(cwd)
        self.assertEqual(0, rc, err)
        self.assertEqual(LIB_A, self.out.read_bytes())

    def test_function_seam_takes_manifest_path_and_repo_root(self):
        (self.root / 'music_library').mkdir()
        (self.root / 'music_library' / 'a.mp3').write_bytes(LIB_A)
        m = self.manifest(lib_track('a.mp3', LIB_A))
        tool = FakeTool([])
        with contextlib.ExitStack() as st:
            st.enter_context(patch.object(fb, 'get_music_tool', lambda: tool))
            st.enter_context(patch.dict(os.environ))
            os.environ.pop('MUSIC_LIBRARY_DIR', None)
            st.enter_context(contextlib.redirect_stdout(io.StringIO()))
            side = fb.fetch_music('q', self.out, manifest_path=m, repo_root=self.root)
        self.assertEqual(('music_library', lib_sha(LIB_A)), (side['provider'], side['sha256']))

    # ---- --force / no-overwrite unchanged
    def test_force_replaces_the_previous_pair_with_the_library_bed_and_a_failed_force_keeps_it(self):
        self.out.parent.mkdir(parents=True)
        self.out.write_bytes(b'previous bed')
        self.side.write_text('{"keep": true}')
        rc, _, _ = self.run_fb(FakeTool([]), self.manifest(lib_track('a.mp3', LIB_A)), '--force')   # file missing
        self.assertEqual(4, rc)
        self.assertEqual((b'previous bed', '{"keep": true}'), (self.out.read_bytes(), self.side.read_text()))
        self.assertEqual(['bed.mp3', 'bed.mp3.source.json'], self.leftovers())
        (self.lib / 'a.mp3').write_bytes(LIB_A)
        rc, _, err = self.run_fb(FakeTool([]), self.manifest(lib_track('a.mp3', LIB_A)), '--force')
        self.assertEqual(0, rc, err)
        self.assertEqual(LIB_A, self.out.read_bytes())
        self.assertEqual('music_library', json.loads(self.side.read_text())['provider'])

    def test_sidecar_replace_failure_leaves_nothing_usable_at_out(self):
        real = os.replace

        def failing(src, dst):
            if str(dst).endswith('.source.json'):
                raise OSError('disk full')
            return real(src, dst)
        (self.lib / 'a.mp3').write_bytes(LIB_A)
        for label, manifest, tool in (('library', self.manifest(lib_track('a.mp3', LIB_A)), FakeTool([])),
                                      ('pixabay', self.manifest(), FakeTool(['ok']))):
            for previous in (False, True):
                self.out.parent.mkdir(parents=True, exist_ok=True)
                for f in self.out.parent.glob('*'):
                    f.unlink()
                if previous:
                    self.out.write_bytes(b'previous bed')
                    self.side.write_text('{"keep": true}')
                with patch.object(fb.os, 'replace', failing):
                    rc, out, err = self.run_fb(tool if not previous else type(tool)([] if label == 'library' else ['ok']),
                                               manifest, *(['--force'] if previous else []))
                self.assertEqual(4, rc, (label, previous, err))
                self.assertEqual(1, len(err.strip().splitlines()), err)
                self.assertIn('disk full', err)
                self.assertEqual([], self.leftovers(), (label, previous))   # neither mp3 nor sidecar nor temp file

    def test_no_overwrite_without_force_still_refuses_before_any_fetch(self):
        (self.lib / 'a.mp3').write_bytes(LIB_A)
        self.out.parent.mkdir(parents=True)
        self.out.write_bytes(b'previous bed')
        tool = FakeTool(['ok'])
        rc, _, err = self.run_fb(tool, self.manifest(lib_track('a.mp3', LIB_A)))
        self.assertEqual((2, [], b'previous bed'), (rc, tool.calls, self.out.read_bytes()))
        self.assertIn('--force', err)


if __name__ == '__main__':
    unittest.main()
