import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
FIX = Path(__file__).resolve().parent / 'fixtures' / 'a67' / 'content'
sys.path.insert(0, str(SCRIPTS))
import cue_times  # noqa: E402


def cli(*args):
    proc = subprocess.run([sys.executable, str(SCRIPTS / 'cue_times.py'), '--words', str(FIX / 'words_by_line.txt'),
                           '--script', str(FIX / 'script.txt'), *args], capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout)


class CueTimesTests(unittest.TestCase):
    def test_number_with_comma_is_found_with_line_and_start(self):
        rc, out = cli('--find', '13,000')
        self.assertEqual(0, rc)
        self.assertEqual('number', out['kind'])
        self.assertEqual([{'line': 3, 'start': 22.0, 'matched': '13,000'}], out['occurrences'])

    def test_number_without_comma_matches_commaed_script_number(self):
        rc, out = cli('--find', '13000')
        self.assertEqual(22.0, out['occurrences'][0]['start'])

    def test_number_boundary(self):
        rc, out = cli('--find', '1')   # only inside 10 / 13,000 / 65 -> never a whole number here
        self.assertEqual(1, rc)
        self.assertEqual([], out['occurrences'])

    def test_phrase_is_case_and_space_tolerant(self):
        rc, out = cli('--find', 'รอบที่65')
        self.assertEqual(0, rc)
        self.assertEqual({'line': 2, 'start': 18.0, 'matched': 'รอบที่ 65'}, out['occurrences'][0])
        rc, out = cli('--find', 'gemini')
        self.assertEqual(2.0, out['occurrences'][0]['start'])

    def test_near_picks_nearest_occurrence(self):
        with tempfile.TemporaryDirectory() as d:
            script, words = Path(d) / 's.txt', Path(d) / 'w.txt'
            script.write_text('a 5 b\nc 5 d\n')
            words.write_text('L1: a@0.0 5@1.0 b@2.0\nL2: c@50.0 5@51.0 d@52.0\n')
            proc = subprocess.run([sys.executable, str(SCRIPTS / 'cue_times.py'), '--words', str(words), '--script', str(script),
                                   '--find', '5', '--near', '49'], capture_output=True, text=True)
        out = json.loads(proc.stdout)
        self.assertEqual([1.0, 51.0], [o['start'] for o in out['occurrences']])
        self.assertEqual(51.0, out['nearest']['start'])

    def test_not_found_exit_1_and_bad_input_exit_2(self):
        rc, out = cli('--find', 'nonexistent phrase')
        self.assertEqual(1, rc)
        proc = subprocess.run([sys.executable, str(SCRIPTS / 'cue_times.py'), '--words', '/nope', '--script', str(FIX / 'script.txt'), '--find', 'x'],
                              capture_output=True, text=True)
        self.assertEqual(2, proc.returncode)


if __name__ == '__main__':
    unittest.main()
