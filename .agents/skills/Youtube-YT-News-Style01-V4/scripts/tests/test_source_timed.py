import json
from pathlib import Path
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
        self.assertEqual(['so Gemini 4 Carbon is finally here',
                          'and this is one of the strongest',
                          'models from Google & more'], [s['text'] for s in segs])
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
        self.assertEqual(['so Gemini 4 Carbon', 'is finally here', 'models from Google'], [s['text'] for s in segs])
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

    def test_from_audio_exit_4_when_model_or_venv_missing_and_never_downloads(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'a.wav'
            src.write_bytes(b'RIFF')
            out = Path(td) / 'o.json'
            proc = self.run_cli('from-audio', str(src), '--out', str(out), '--model', 'nobody/not-a-cached-model')
            self.assertEqual(4, proc.returncode, proc.stderr)
            self.assertIn('not in the local HF cache', proc.stderr)
            import os
            env = dict(os.environ, KARAOKE_VENV=str(Path(td) / 'no-venv'))
            proc = self.run_cli('from-audio', str(src), '--out', str(out), env=env)
            self.assertEqual(4, proc.returncode)
            self.assertIn('venv', proc.stderr)
            self.assertFalse(out.exists())

    def test_from_audio_done_file_short_circuits_and_is_keyed(self):
        import os
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'a.wav'
            src.write_bytes(b'RIFF-not-really-audio')
            out = Path(td) / 'o.json'
            out.write_text('[{"start":0,"end":1,"text":"cached"}]')
            key = st.audio_job_key(str(src), st.DEFAULT_MODEL, 'en', None, None)
            Path(str(out) + '.done.json').write_text(json.dumps({'key': key, 'output': str(out)}))
            env = dict(os.environ, KARAOKE_VENV=str(Path(td) / 'no-venv'))      # a real run would exit 4
            proc = self.run_cli('from-audio', str(src), '--out', str(out), env=env)
            self.assertEqual(0, proc.returncode, proc.stderr)
            self.assertIn('already done', proc.stdout)
            self.assertEqual('cached', json.loads(out.read_text())[0]['text'])
            for extra in (['--lang', 'th'], ['--model', 'nobody/other'], ['--start', '5'], ['--duration', '9']):
                proc = self.run_cli('from-audio', str(src), '--out', str(out), *extra, env=env)
                self.assertNotEqual(0, proc.returncode, extra)                    # other key -> not cached
            src.write_bytes(b'RIFF-different')
            proc = self.run_cli('from-audio', str(src), '--out', str(out), env=env)
            self.assertEqual(4, proc.returncode)                                  # audio changed -> not cached
            out.unlink()                                                          # done file without output -> rerun
            src.write_bytes(b'RIFF-not-really-audio')
            self.assertEqual(4, self.run_cli('from-audio', str(src), '--out', str(out), env=env).returncode)

    def test_offline_env_is_enforced_constant(self):
        self.assertEqual('1', st.OFFLINE_ENV['HF_HUB_OFFLINE'])
        self.assertEqual('1', st.OFFLINE_ENV['TRANSFORMERS_OFFLINE'])


if __name__ == '__main__':
    unittest.main()
