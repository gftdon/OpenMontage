import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
FIX = Path(__file__).resolve().parent / 'fixtures' / 'a67' / 'timing'
sys.path.insert(0, str(SCRIPTS))
import source_timed as st  # noqa: E402


class VttTests(unittest.TestCase):
    def test_rolling_duplicates_are_removed_and_tags_stripped(self):
        segs = st.parse_vtt((FIX / 'rolling.vtt').read_text())
        self.assertEqual(['now Marlin 3 Quartz has arrived today',
                          'and every sample ran on one board',
                          'tools from Acme & others'], [s['text'] for s in segs])
        self.assertEqual([0.16, 2.24, 4.16], [s['start'] for s in segs])
        for a, b in zip(segs, segs[1:]):
            self.assertLessEqual(a['end'], b['start'] + 1e-9)     # no overlaps
        for s in segs:
            self.assertLessEqual(s['end'] - s['start'], 8.0)

    def test_same_line_twice_not_in_consecutive_cues_is_kept(self):
        vtt = ('WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nyes\n\n00:00:01.000 --> 00:00:02.000\nno\n\n'
               '00:00:02.000 --> 00:00:03.000\nyes\n')
        self.assertEqual(['yes', 'no', 'yes'], [s['text'] for s in st.parse_vtt(vtt)])

    def test_overlong_cue_is_split_to_at_most_eight_seconds(self):
        vtt = 'WEBVTT\n\n00:00:00.000 --> 00:00:30.000\n' + ' '.join(f'w{i}' for i in range(60)) + '\n'
        segs = st.parse_vtt(vtt)
        self.assertGreaterEqual(len(segs), 4)
        self.assertTrue(all(s['end'] - s['start'] <= 8.0 + 1e-6 for s in segs))
        self.assertEqual(' '.join(f'w{i}' for i in range(60)), ' '.join(s['text'] for s in segs))


class Json3Tests(unittest.TestCase):
    def test_events_segs_joined_and_rolling_repeats_dropped(self):
        segs = st.parse_json3((FIX / 'auto.json3').read_text())
        self.assertEqual(['now Marlin 3 Quartz', 'has arrived today', 'tools from Acme'], [s['text'] for s in segs])
        self.assertEqual([0.16, 2.24, 4.16], [s['start'] for s in segs])

    def test_window_definition_and_newline_events_are_skipped(self):
        data = {'events': [{'tStartMs': 0, 'dDurationMs': 5000}, {'tStartMs': 10, 'segs': [{'utf8': '\n'}]},
                           {'tStartMs': 1000, 'dDurationMs': 1000, 'segs': [{'utf8': 'hello'}]}]}
        self.assertEqual([{'start': 1.0, 'end': 2.0, 'text': 'hello'}], st.parse_json3(data))


class WhisperSplitTests(unittest.TestCase):
    def test_long_segment_is_cut_at_clause_punctuation_within_eight_seconds(self):
        words = [{'word': ' word%d%s' % (i, ',' if i == 10 else ''), 'start': i * 0.7, 'end': i * 0.7 + 0.6} for i in range(20)]
        segs = st.split_whisper_segments([{'start': 0.0, 'end': 13.9, 'text': '', 'words': words}])
        self.assertTrue(all(s['end'] - s['start'] <= 8.0 for s in segs))
        self.assertTrue(segs[0]['text'].endswith('word10,'))
        self.assertEqual(20, sum(len(s['text'].split()) for s in segs))

    def test_short_segment_kept_and_empty_dropped(self):
        segs = st.split_whisper_segments([{'start': 1.0, 'end': 3.0, 'text': ' hi there',
                                           'words': [{'word': ' hi', 'start': 1.0, 'end': 1.5}, {'word': ' there', 'start': 1.6, 'end': 2.9}]},
                                          {'start': 4.0, 'end': 5.0, 'text': ' ', 'words': []}])
        self.assertEqual([{'start': 1.0, 'end': 2.9, 'text': 'hi there'}], segs)


class MergeTests(unittest.TestCase):
    def test_merge_sorts_and_drops_identical_overlap(self):
        a = [{'start': 0.0, 'end': 5.0, 'text': 'one'}, {'start': 5.0, 'end': 9.0, 'text': 'two'}]
        b = [{'start': 8.5, 'end': 9.0, 'text': 'Two'}, {'start': 9.0, 'end': 12.0, 'text': 'three'}]
        self.assertEqual(['one', 'two', 'three'], [s['text'] for s in st.merge_parts([b, a])])


class CliTests(unittest.TestCase):
    def run_cli(self, *args, env=None):
        return subprocess.run([sys.executable, str(SCRIPTS / 'source_timed.py'), *args], capture_output=True, text=True, env=env)

    def test_from_vtt_and_from_json3_write_segment_files(self):
        with tempfile.TemporaryDirectory() as td:
            for cmd, f in (('from-vtt', 'rolling.vtt'), ('from-json3', 'auto.json3')):
                out = Path(td) / (cmd + '.json')
                proc = self.run_cli(cmd, str(FIX / f), '--out', str(out))
                self.assertEqual(0, proc.returncode, proc.stderr)
                data = json.loads(out.read_text())
                self.assertEqual({'start', 'end', 'text'}, set(data[0]))
                self.assertEqual(3, len(data))

    def test_bad_input_exit_2(self):
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / 'e.vtt'
            empty.write_text('WEBVTT\n')
            self.assertEqual(2, self.run_cli('from-vtt', str(empty), '--out', str(Path(td) / 'o.json')).returncode)
            self.assertEqual(2, self.run_cli('from-vtt', str(Path(td) / 'missing.vtt'), '--out', str(Path(td) / 'o.json')).returncode)
            self.assertEqual(2, self.run_cli('from-audio', str(Path(td) / 'missing.mp4'), '--out', str(Path(td) / 'o.json')).returncode)

    def part(self, td, name, segs):
        p = Path(td) / name
        p.write_text(json.dumps(segs))
        return p

    def assert_clean_error(self, proc, code=2):
        self.assertEqual(code, proc.returncode, proc.stderr)
        self.assertNotIn('Traceback', proc.stderr)
        self.assertEqual(1, len(proc.stderr.strip().splitlines()), proc.stderr)   # one line
        self.assertTrue(proc.stderr.startswith('ERROR: '), proc.stderr)

    def test_merge_ignores_done_markers_of_the_documented_glob(self):
        # `merge part_*.json` also matches the part_NNNN.json.done.json markers that from-audio writes next to each part
        with tempfile.TemporaryDirectory() as td:
            a = self.part(td, 'part_0001.json', [{'start': 0.0, 'end': 5.0, 'text': 'one'}])
            b = self.part(td, 'part_0002.json', [{'start': 5.0, 'end': 9.0, 'text': 'two'}])
            marks = [self.part(td, 'part_0001.json.done.json', {'key': 'k', 'segments': 1}), self.part(td, 'part_0002.json.done.json', {'key': 'k2'})]
            out = Path(td) / 'merged.json'
            proc = self.run_cli('merge', str(a), str(marks[0]), str(b), str(marks[1]), '--out', str(out))
            self.assertEqual(0, proc.returncode, proc.stderr)
            self.assertEqual(['one', 'two'], [x['text'] for x in json.loads(out.read_text())])
            only_markers = self.run_cli('merge', str(marks[0]), '--out', str(out))
            self.assert_clean_error(only_markers)

    def test_merge_rejects_anything_that_is_not_a_part_file(self):
        with tempfile.TemporaryDirectory() as td:
            good = self.part(td, 'part_0001.json', [{'start': 0.0, 'end': 5.0, 'text': 'one'}])
            out = str(Path(td) / 'o.json')
            for name, content in [('obj.json', {'key': 'k'}), ('str.json', 'text'), ('items.json', [1, 2]), ('nokeys.json', [{'text': 'x'}]),
                                  ('badtime.json', [{'start': 'a', 'end': 1, 'text': 'x'}]), ('badtext.json', [{'start': 0, 'end': 1, 'text': 5}])]:
                bad = self.part(td, name, content)
                proc = self.run_cli('merge', str(good), str(bad), '--out', out)
                self.assert_clean_error(proc)
                self.assertIn(name, proc.stderr)
            broken = Path(td) / 'broken.json'
            broken.write_text('{not json')
            self.assert_clean_error(self.run_cli('merge', str(good), str(broken), '--out', out))
            self.assert_clean_error(self.run_cli('merge', str(good), str(Path(td) / 'missing.json'), '--out', out))

    def test_malformed_input_of_other_subcommands_exits_2_without_traceback(self):
        with tempfile.TemporaryDirectory() as td:
            out = str(Path(td) / 'o.json')
            cases = [('from-json3', 'list.json3', '[1, 2]'), ('from-json3', 'str.json3', '"x"'), ('from-json3', 'ev.json3', '{"events": 5}'),
                     ('from-json3', 'evitems.json3', '{"events": [1, "a"]}'), ('from-json3', 'segs.json3', '{"events": [{"tStartMs": 0, "segs": [1]}]}'),
                     ('from-json3', 'time.json3', '{"events": [{"tStartMs": "x", "segs": [{"utf8": "a"}]}]}'),
                     ('from-json3', 'broken.json3', '{nope')]
            for cmd, name, content in cases:
                f = Path(td) / name
                f.write_text(content)
                self.assert_clean_error(self.run_cli(cmd, str(f), '--out', out))
            binary = Path(td) / 'bin.vtt'
            binary.write_bytes(b'\xff\xfe\x00\x80\x81')
            self.assert_clean_error(self.run_cli('from-vtt', str(binary), '--out', out))
            self.assertFalse(Path(out).exists())

    # Test seam: source_timed.py reads the home dir from the passwd database (pwd), NOT from $HOME, so setting HOME in a
    # test (or as an agent) changes nothing.  CLI tests therefore run a temp COPY of the script whose PW_HOME line is
    # rewritten to a temp home; in-process tests patch the module constants.  An agent can reach neither seam: it can
    # only run the real script, which has no hook and ignores every environment variable.
    @staticmethod
    def fake_home(td, venv=True, hub_models=()):
        home = Path(td) / 'home'
        if venv:
            (home / '.cache' / 'yt-news-v4' / 'asr-venv' / 'lib' / 'python3.12' / 'site-packages').mkdir(parents=True)
        (home / '.cache' / 'huggingface' / 'hub').mkdir(parents=True, exist_ok=True)
        for repo in hub_models:
            snap = home / '.cache' / 'huggingface' / 'hub' / ('models--' + repo.replace('/', '--')) / 'snapshots' / 'abc'
            snap.mkdir(parents=True)
            (snap / 'config.json').write_text('{}')
            (snap / 'weights.safetensors').write_bytes(b'x')
        return home

    @staticmethod
    def script_copy(home):
        """Temp copy of source_timed.py with PW_HOME rewritten to `home`; returns its path."""
        text = (SCRIPTS / 'source_timed.py').read_text()
        line = 'PW_HOME = pwd.getpwuid(os.getuid()).pw_dir'
        assert text.count(line) == 1
        dst = Path(home).parent / ('copy_' + Path(home).name) / 'source_timed.py'
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text.replace(line, f'PW_HOME = {str(home)!r}'))
        shutil.copy(SCRIPTS / 'asr_run.sh', dst.parent / 'asr_run.sh')      # the launcher sits next to the script it starts
        return dst

    def run_home(self, home, *args, **extra_env):
        import os
        return subprocess.run([sys.executable, str(self.script_copy(home)), *args], capture_output=True, text=True,
                              env=dict(os.environ, **extra_env))

    def test_from_audio_exit_4_when_model_or_venv_missing_and_never_downloads(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'a.wav'
            src.write_bytes(b'RIFF')
            out = Path(td) / 'o.json'
            home = self.fake_home(td)                    # venv present, hub empty
            proc = self.run_home(home, 'from-audio', str(src), '--out', str(out), '--model', 'nobody/not-a-cached-model')
            self.assertEqual(4, proc.returncode, proc.stderr)
            self.assertIn('not in the local HF cache', proc.stderr)
            nohome = self.fake_home(Path(td) / 'x', venv=False)
            proc = self.run_home(nohome, 'from-audio', str(src), '--out', str(out))
            self.assertEqual(4, proc.returncode)
            self.assertIn('is not built', proc.stderr)
            self.assertIn('setup_asr_venv.sh', proc.stderr)
            self.assertIn('do not install anything', proc.stderr)
            self.assertNotIn('KARAOKE_VENV', proc.stderr)
            self.assertFalse(out.exists())

    def test_environment_overrides_of_venv_and_model_cache_change_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'a.wav'
            src.write_bytes(b'RIFF')
            out = Path(td) / 'o.json'
            # a complete, working-looking venv + hub that the agent could point the variables at
            other = self.fake_home(Path(td) / 'other', hub_models=[st.DEFAULT_MODEL])
            fake_venv = other / '.cache' / 'yt-news-v4' / 'asr-venv'
            fake_hub = other / '.cache' / 'huggingface' / 'hub'
            self.assertTrue((fake_venv / 'lib' / 'python3.12' / 'site-packages').is_dir() and any(fake_hub.iterdir()))
            overrides = dict(KARAOKE_VENV=str(fake_venv), ASR_VENV=str(fake_venv), HF_HUB_CACHE=str(fake_hub), HF_HOME=str(fake_hub.parent), HOME=str(other))
            # (a) real home has no venv: KARAOKE_VENV (and HOME) must not rescue it
            nohome = self.fake_home(Path(td) / 'empty', venv=False)
            proc = self.run_home(nohome, 'from-audio', str(src), '--out', str(out), **overrides)
            self.assertEqual(4, proc.returncode, proc.stderr)
            self.assertIn('is not built', proc.stderr)
            # (b) home has the venv but an empty hub: HF_HUB_CACHE / HF_HOME / HOME must not supply the model
            home = self.fake_home(Path(td) / 'emptyhub')
            proc = self.run_home(home, 'from-audio', str(src), '--out', str(out), **overrides)
            self.assertEqual(4, proc.returncode, proc.stderr)
            self.assertIn('not in the local HF cache', proc.stderr)
            self.assertFalse(out.exists())

    def test_home_variable_does_not_move_the_venv_or_the_hub_constants(self):
        import os
        import pwd
        with tempfile.TemporaryDirectory() as td:
            other = self.fake_home(td, hub_models=[st.DEFAULT_MODEL])           # fake venv + fake hub under a temp HOME
            probe = 'import sys; sys.path.insert(0, %r); import source_timed as s; print(s.VENV_DIR); print(s.HF_HUB_DIR)' % str(SCRIPTS)
            proc = subprocess.run([sys.executable, '-B', '-c', probe], capture_output=True, text=True,
                                  env=dict(os.environ, HOME=str(other)))
            self.assertEqual(0, proc.returncode, proc.stderr)
            venv, hub = proc.stdout.split('\n')[:2]
            pw = pwd.getpwuid(os.getuid()).pw_dir
            self.assertEqual(os.path.join(pw, '.cache', 'yt-news-v4', 'asr-venv'), venv)
            self.assertEqual(os.path.join(pw, '.cache', 'huggingface', 'hub'), hub)
            self.assertFalse(venv.startswith(str(other)) or hub.startswith(str(other)))

    def test_model_directory_is_refused_with_exit_2(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'a.wav'
            src.write_bytes(b'RIFF')
            out = Path(td) / 'o.json'
            home = self.fake_home(td)
            snap = Path(td) / 'a-model-dir'
            snap.mkdir()
            (snap / 'config.json').write_text('{}')
            (snap / 'weights.safetensors').write_bytes(b'x')
            proc = self.run_home(home, 'from-audio', str(src), '--out', str(out), '--model', str(snap))
            self.assertEqual(2, proc.returncode, proc.stderr)
            self.assertIn('not an HF repo id', proc.stderr)
            self.assertFalse(out.exists())

    def test_model_must_be_a_plain_repo_id_wildcards_and_paths_exit_2(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'a.wav'
            src.write_bytes(b'RIFF')
            out = Path(td) / 'o.json'
            home = self.fake_home(td, hub_models=['acme/some-model'])           # a cached model a wildcard could pick
            for bad in ('*', 'acme/*', '*/some-model', 'acme/some-mod?l', 'acme/[sx]ome-model', '../acme/some-model',
                        '/abs/path/x', 'acme', 'acme/some/model', 'acme/ some', '', '.hidden/x', 'acme/-x'):
                proc = self.run_home(home, 'from-audio', str(src), '--out', str(out), '--model', bad)
                self.assertEqual(2, proc.returncode, (bad, proc.stderr))
                self.assertIn('not an HF repo id', proc.stderr, bad)
                self.assertFalse(out.exists())
            proc = self.run_home(home, 'from-audio', str(src), '--out', str(out), '--model', 'acme/some-model')
            self.assertNotIn('not an HF repo id', proc.stderr)                  # a plain repo id passes validation ...
            self.assertIn('ffmpeg could not read audio', proc.stderr)           # ... and reaches the next step (the fake wav is not audio)
            for bad in ('*', 'acme/*', '../x/y'):
                with self.assertRaises(st.BadInput):
                    st.resolve_model_dir(bad)

    def test_resolve_model_dir_finds_a_repo_id_in_the_hub_cache(self):
        from unittest import mock
        import os
        with tempfile.TemporaryDirectory() as td:
            home = self.fake_home(td, hub_models=['acme/some-model'])
            with mock.patch.object(st, 'HF_HUB_DIR', str(home / '.cache' / 'huggingface' / 'hub')), \
                    mock.patch.object(st, 'VENV_DIR', str(home / '.cache' / 'yt-news-v4' / 'asr-venv')):
                found = st.resolve_model_dir('acme/some-model')
                self.assertTrue(found and found.endswith(os.path.join('snapshots', 'abc')), found)
                self.assertIsNone(st.resolve_model_dir('acme/other-model'))

    def test_worker_invocation_is_isolated_from_the_callers_environment(self):
        import os
        from unittest import mock
        evil = Path(tempfile.mkdtemp(prefix='fakemlx_'))
        try:
            (evil / 'mlx_whisper.py').write_text('raise SystemExit("hijacked")\n')
            hostile = dict(PYTHONPATH=str(evil), PYTHONSTARTUP=str(evil / 's.py'), PYTHONHOME=str(evil), PYTHONUSERBASE=str(evil),
                           PYTHONDONTWRITEBYTECODE='', PYTHONPYCACHEPREFIX=str(evil), LD_PRELOAD='x', DYLD_INSERT_LIBRARIES='x',
                           HF_HUB_CACHE=str(evil), HF_HOME=str(evil), KARAOKE_VENV=str(evil), HF_HUB_OFFLINE='0', TRANSFORMERS_OFFLINE='0',
                           HOME=str(evil), PATH=str(evil) + ':/usr/bin')
            with mock.patch.dict(os.environ, hostile):
                argv, env = st.worker_invocation('/skill/scripts/asr_run.sh', '/opt/homebrew/bin/ffmpeg', 'a.wav', '/m', 'en', 'r.json')
            self.assertEqual(['/bin/bash', '/skill/scripts/asr_run.sh', 'source_timed.py'], argv[:3])      # through the launcher, never a python of ours
            self.assertEqual(['_whisper', 'a.wav', '/m', 'en', 'r.json'], argv[3:])
            self.assertEqual({'HOME', 'PATH', 'LANG', 'TMPDIR'}, set(env))             # the offline variables are set by the worker itself
            self.assertEqual(st.PW_HOME, env['HOME'])
            self.assertEqual('/opt/homebrew/bin:/usr/bin:/bin', env['PATH'])
            self.assertEqual('/var/empty', env['TMPDIR'])
            self.assertNotIn(str(evil), ' '.join(argv) + ' '.join(env.values()))
            # the flags really do shut the fake module out (python -I ignores PYTHONPATH and the cwd)
            probe = [sys.executable, '-I', '-S', '-B', '-c', 'import importlib.util as u; print(u.find_spec("mlx_whisper"))']
            proc = subprocess.run(probe, capture_output=True, text=True, cwd=str(evil), env=dict(os.environ, PYTHONPATH=str(evil)))
            self.assertEqual('None', proc.stdout.strip(), proc.stderr)
            proc = subprocess.run([sys.executable, '-B', '-c', 'import importlib.util as u; print(u.find_spec("mlx_whisper") is not None)'],
                                  capture_output=True, text=True, cwd=str(evil), env=dict(os.environ, PYTHONPATH=str(evil)))
            self.assertEqual('True', proc.stdout.strip(), proc.stderr)          # control: without -I the fake WOULD be found
        finally:
            import shutil
            shutil.rmtree(evil, ignore_errors=True)

    def test_from_audio_done_file_short_circuits_and_is_keyed(self):
        import os
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'a.wav'
            src.write_bytes(b'RIFF-not-really-audio')
            out = Path(td) / 'o.json'
            out.write_text('[{"start":0,"end":1,"text":"cached"}]')
            key = st.audio_job_key(str(src), st.DEFAULT_MODEL, 'en', None, None)
            Path(str(out) + '.done.json').write_text(json.dumps({'key': key, 'output': str(out)}))
            home = self.fake_home(td, venv=False)                                # no venv under this home: a real run would exit 4
            proc = self.run_home(home, 'from-audio', str(src), '--out', str(out))
            self.assertEqual(0, proc.returncode, proc.stderr)
            self.assertIn('already done', proc.stdout)
            self.assertEqual('cached', json.loads(out.read_text())[0]['text'])
            for extra in (['--lang', 'th'], ['--model', 'nobody/other'], ['--start', '5'], ['--duration', '9']):
                proc = self.run_home(home, 'from-audio', str(src), '--out', str(out), *extra)
                self.assertNotEqual(0, proc.returncode, extra)                    # other key -> not cached
            src.write_bytes(b'RIFF-different')
            proc = self.run_home(home, 'from-audio', str(src), '--out', str(out))
            self.assertEqual(4, proc.returncode)                                  # audio changed -> not cached
            out.unlink()                                                          # done file without output -> rerun
            src.write_bytes(b'RIFF-not-really-audio')
            self.assertEqual(4, self.run_home(home, 'from-audio', str(src), '--out', str(out)).returncode)

    def test_the_venv_and_ffmpeg_constants_equal_those_of_the_ladder(self):
        probe = ('import sys; sys.path.insert(0, %r); import asr_transcribe as a, source_timed as s\n'
                 'print(a.VENV_ROOT); print(a.SITE_DIR); print(list(a.FFMPEG_CANDIDATES)); print(list(s.FFMPEG_CANDIDATES))\n'
                 'print(s.VENV_DIR); print(s.SITE_DIR)' % str(SCRIPTS))
        proc = subprocess.run([sys.executable, '-B', '-c', probe], capture_output=True, text=True)
        self.assertEqual(0, proc.returncode, proc.stderr)
        a_venv, a_site, a_ff, s_ff, s_venv, s_site = proc.stdout.split('\n')[:6]
        self.assertEqual((a_venv, a_site, a_ff), (s_venv, s_site, s_ff))

    def test_the_source_has_no_shutil_which_and_no_karaoke_venv(self):
        src = (SCRIPTS / 'source_timed.py').read_text()
        self.assertNotIn('shutil.which', src)
        self.assertNotIn('karaoke-subtitle', src)
        self.assertNotIn('karaoke_python', src)

    def test_ffmpeg_is_found_in_the_fixed_list_and_runs_under_the_minimal_environment(self):
        """the extraction subprocess and the worker get a from-scratch environment; a fake ffmpeg earlier on the caller's PATH is never used"""
        import os
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:
            fakebin = Path(td) / 'bin'
            fakebin.mkdir()
            (fakebin / 'ffmpeg').write_text('#!/bin/sh\nexit 1\n')
            (fakebin / 'ffmpeg').chmod(0o755)
            src = Path(td) / 'a.wav'
            src.write_bytes(b'RIFF')
            home = self.fake_home(td, hub_models=[st.DEFAULT_MODEL])
            calls = []

            def fake_run(argv, **kw):
                calls.append((list(argv), kw.get('env')))
                if argv[0] != '/bin/bash':                                                  # the ffmpeg extraction: make the wav
                    Path(argv[-1]).write_bytes(b'wav')
                    return subprocess.CompletedProcess(argv, 0, '', '')
                Path(argv[-1]).write_text('[{"start": 0, "end": 1, "text": "x", "words": []}]')
                return subprocess.CompletedProcess(argv, 0, '', '')
            with mock.patch.dict(os.environ, {'PATH': str(fakebin) + ':' + os.environ.get('PATH', ''), 'PYTHONPATH': '/evil'}), \
                    mock.patch.object(st, 'HF_HUB_DIR', str(home / '.cache' / 'huggingface' / 'hub')), \
                    mock.patch.object(st, 'SITE_DIR', str(home / '.cache' / 'yt-news-v4' / 'asr-venv' / 'lib' / 'python3.12' / 'site-packages')), \
                    mock.patch.object(st.subprocess, 'run', fake_run):
                st.from_audio(str(src))
            (ff_argv, ff_env), (w_argv, w_env) = calls
            self.assertIn(ff_argv[0], st.FFMPEG_CANDIDATES)
            self.assertNotEqual(str(fakebin / 'ffmpeg'), ff_argv[0])
            for env in (ff_env, w_env):
                self.assertEqual({'HOME', 'PATH', 'LANG', 'TMPDIR'}, set(env))
                self.assertNotIn(str(fakebin), env['PATH'])
                self.assertNotIn('/evil', ' '.join(env.values()))
            self.assertEqual(['/bin/bash', st.LAUNCHER, 'source_timed.py', '_whisper'], w_argv[:4])

    def test_a_refusal_of_the_launcher_is_exit_4_not_a_crash(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'a.wav'
            src.write_bytes(b'RIFF')
            home = self.fake_home(td, hub_models=[st.DEFAULT_MODEL])

            def fake_run(argv, **kw):
                if argv[0] != '/bin/bash':
                    return subprocess.CompletedProcess(argv, 0, '', '')
                return subprocess.CompletedProcess(argv, 4, '', 'ERROR: the interpreter / stdlib / ASR venv differ from asr_venv.manifest')
            with mock.patch.object(st, 'HF_HUB_DIR', str(home / '.cache' / 'huggingface' / 'hub')), \
                    mock.patch.object(st, 'SITE_DIR', str(home / '.cache' / 'yt-news-v4' / 'asr-venv' / 'lib' / 'python3.12' / 'site-packages')), \
                    mock.patch.object(st.subprocess, 'run', fake_run):
                with self.assertRaises(st.ToolMissing) as cm:
                    st.from_audio(str(src))
            self.assertIn('differ from asr_venv.manifest', str(cm.exception))

    def test_the_worker_appends_the_venv_site_packages_itself_and_goes_offline(self):
        """under `python -I -S` (as asr_run.sh starts it) nothing processed site-packages: _whisper adds SITE_DIR before importing mlx_whisper"""
        with tempfile.TemporaryDirectory() as td:
            site = Path(td) / 'site'
            site.mkdir()
            (site / 'mlx_whisper.py').write_text('import os\n'
                                                 'def transcribe(wav, **kw):\n'
                                                 '    return {"segments": [{"start": 0.0, "end": 1.0, "text": " hi", "words": [{"word": " hi", "start": 0.0, "end": 1.0}], '
                                                 '"offline": os.environ.get("HF_HUB_OFFLINE") + os.environ.get("TRANSFORMERS_OFFLINE")}]}\n')
            text = (SCRIPTS / 'source_timed.py').read_text()
            line = "SITE_DIR = os.path.join(VENV_DIR, 'lib', 'python3.12', 'site-packages')"
            self.assertEqual(1, text.count(line))
            copy = Path(td) / 'source_timed.py'
            copy.write_text(text.replace(line, 'SITE_DIR = %r' % str(site)))
            out = Path(td) / 'o.json'
            proc = subprocess.run([sys.executable, '-I', '-S', '-B', str(copy), '_whisper', 'a.wav', '/m', 'en', str(out)],
                                  capture_output=True, text=True, env={'PATH': '/usr/bin:/bin'})
            self.assertEqual(0, proc.returncode, proc.stderr)
            self.assertEqual('hi', json.loads(out.read_text())[0]['text'].strip())

    def test_offline_env_is_enforced_constant(self):
        self.assertEqual('1', st.OFFLINE_ENV['HF_HUB_OFFLINE'])
        self.assertEqual('1', st.OFFLINE_ENV['TRANSFORMERS_OFFLINE'])


if __name__ == '__main__':
    unittest.main()
