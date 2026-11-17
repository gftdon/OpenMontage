"""line_starts.py / words_by_line.py on RAW word-timing pages (word_timing.sh output: pages may straddle script lines)."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
FIX = Path(__file__).resolve().parent / 'fixtures/a67/timing'
sys.path.insert(0, str(SCRIPTS))


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ls = load('line_starts')
wbl = load('words_by_line')


def page(*words):
    """page(('ab', 1.0, 1.5), ...) -> raw page {start,end,words:[{w,s,e}]}"""
    return {'start': words[0][1], 'end': words[-1][2], 'words': [{'w': w, 's': s, 'e': e} for w, s, e in words]}


def run(*args):
    return subprocess.run([sys.executable, '-B', *map(str, args)], capture_output=True, text=True)


class MapTests(unittest.TestCase):
    def starts(self, pages, lines):
        return [(r['line'], r['start'], r['end']) for r in ls.compute_line_starts(pages, lines)]

    def test_page_straddling_two_lines(self):
        pages = [page(('ab', 0, 1), ('cd', 1, 2), ('ef', 2, 3)), page(('gh', 3, 4))]
        self.assertEqual([(1, 0, 2), (2, 2, 4)], self.starts(pages, ['abcd', 'efgh']))

    def test_whitespace_insensitive(self):
        pages = [page(('hello', 0, 1), ('wor', 1, 1.5)), page(('ld', 1.5, 2))]
        self.assertEqual([(1, 0, 2)], self.starts(pages, ['hello  world ']))

    def test_token_straddling_a_line_break_belongs_to_its_first_character_line(self):
        pages = [page(('ab', 0, 1), ('cd', 1, 2), ('ef', 2, 3))]  # 'cd' = last char of line 1 + first char of line 2
        self.assertEqual([(1, 0, 2), (2, 2, 3)], self.starts(pages, ['abc', 'def']))

    def test_line_without_a_starting_token_is_a_clear_error(self):
        pages = [page(('abcd', 0, 1), ('e', 1, 2))]  # lines 'ab', 'c', 'de': line 2 starts no token
        with self.assertRaises(ls.LineStartsError) as cm:
            ls.compute_line_starts(pages, ['ab', 'c', 'de'])
        self.assertIn('line 2', str(cm.exception))
        self.assertIn('no word', str(cm.exception))

    def test_zero_length_tokens_around_a_line_break(self):
        pages = [page(('โปรแกรม', 292.575, 292.9), ('กราฟิก', 292.9, 292.9)), page(('ทำ', 292.9, 292.9), ('ให้การ', 292.9, 293.26))]
        rows = ls.compute_line_starts(pages, ['โปรแกรมกราฟิก', 'ทำให้การ'])
        self.assertEqual([(1, 292.575), (2, 292.9)], [(r['line'], r['start']) for r in rows])
        self.assertEqual(292.9, rows[0]['end'])

    def test_character_mismatch_is_a_hard_error_with_both_snippets(self):
        pages = [page(('ab', 0, 1)), page(('xx', 1, 2))]
        with self.assertRaises(ls.LineStartsError) as cm:
            ls.compute_line_starts(pages, ['ab', 'cd'])
        msg = str(cm.exception)
        self.assertIn('line 2', msg)
        self.assertIn('mapping mismatch', msg)
        self.assertIn('cd', msg)
        self.assertIn('xx', msg)

    def test_tokens_left_over_or_script_not_covered_is_an_error(self):
        with self.assertRaises(ls.LineStartsError):
            ls.compute_line_starts([page(('ab', 0, 1), ('zz', 1, 2))], ['ab'])  # extra token
        with self.assertRaises(ls.LineStartsError):
            ls.compute_line_starts([page(('ab', 0, 1))], ['ab', 'cd'])  # line 2 has no tokens

    def test_blank_lines_are_ignored_and_numbering_counts_spoken_lines_only(self):
        pages = [page(('ab', 0, 1)), page(('cd', 1, 2))]
        self.assertEqual([(1, 0, 1), (2, 1, 2)], self.starts(pages, ['ab', '', '   ', 'cd']))

    def test_matcher_is_shared_with_words_by_line(self):
        self.assertIs(ls.map_tokens, sys.modules['words_by_line'].map_tokens)  # imported, not re-implemented
        self.assertEqual('words_by_line', ls.map_tokens.__module__)


class RealDataTests(unittest.TestCase):
    """Excerpts (<= 40 tokens) cut from the real word_timing.sh output of V261111."""

    def excerpt(self, name):
        pages = json.loads((FIX / (name + '_pages.json')).read_text())
        lines = [l for l in (FIX / (name + '_script.txt')).read_text(encoding='utf-8').splitlines() if l.strip()]
        return pages, lines

    def test_page_that_straddles_two_script_lines(self):
        pages, lines = self.excerpt('real_straddle')
        self.assertTrue({'ขั้นตอน', 'Google'} <= {w['w'] for w in pages[0]['words']})  # one raw page holds the end of line 1 AND the start of line 2
        rows = ls.compute_line_starts(pages, lines)
        self.assertEqual([(1, 7.2), (2, 9.0)], [(r['line'], r['start']) for r in rows])

    def test_zero_length_tokens_at_a_line_end(self):
        pages, lines = self.excerpt('real_zero_length')
        rows = ls.compute_line_starts(pages, lines)
        self.assertEqual([(1, 290.081), (2, 292.9)], [(r['line'], r['start']) for r in rows])

    def test_line_start_equals_words_by_line_first_word_time(self):
        for name in ('real_straddle', 'real_zero_length'):
            pages, lines = self.excerpt(name)
            rows = ls.compute_line_starts(pages, lines)
            first = {}
            for line, word, s, e in wbl.words_by_line(pages, lines):
                first.setdefault(line, s)
            self.assertEqual({r['line']: r['start'] for r in rows}, first, name)

    def test_words_by_line_stdout_is_byte_identical_to_the_pre_change_tool(self):
        for name in ('real_straddle', 'real_zero_length'):
            r = run(SCRIPTS / 'words_by_line.py', FIX / (name + '_pages.json'), FIX / (name + '_script.txt'))
            self.assertEqual(0, r.returncode, r.stderr)
            self.assertEqual((FIX / (name + '_wbl.txt')).read_text(encoding='utf-8'), r.stdout, name)


class CliTests(unittest.TestCase):
    def test_cli_output_format_and_consumers(self):
        sys.path.insert(0, str(SCRIPTS))
        import episode_data as ed
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'ls.json'
            r = run(SCRIPTS / 'line_starts.py', '--pages', FIX / 'real_zero_length_pages.json', '--script', FIX / 'real_zero_length_script.txt', '--out', out)
            self.assertEqual(0, r.returncode, r.stderr)
            rows = json.loads(out.read_text())
            self.assertEqual(['line', 'start', 'end', 'text'], list(rows[0]))
            self.assertEqual([1, 2], [x['line'] for x in rows])
            self.assertTrue(r.stdout.startswith('wrote %s: 2 lines' % out))
            self.assertEqual([1, 2], [x['line'] for x in ed.load_line_starts(out)])  # episode_data consumer
            self.assertEqual(292.9, ed.load_line_starts(out)[1]['start'])

    def test_cli_mismatch_exits_nonzero_without_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            pages, script = Path(d) / 'p.json', Path(d) / 's.txt'
            pages.write_text(json.dumps([page(('ab', 0, 1))]))
            script.write_text('cd\n')
            r = run(SCRIPTS / 'line_starts.py', '--pages', pages, '--script', script, '--out', Path(d) / 'o.json')
            self.assertNotEqual(0, r.returncode)
            self.assertIn('line 1', r.stderr)
            self.assertNotIn('Traceback', r.stderr)
            self.assertFalse((Path(d) / 'o.json').exists())

    def test_words_by_line_help_and_usage(self):
        r = run(SCRIPTS / 'words_by_line.py', '--help')
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn('caption_pages', r.stdout)
        r = run(SCRIPTS / 'words_by_line.py', FIX / 'real_straddle_pages.json', FIX / 'real_straddle_script.txt', '2')
        self.assertEqual(['L2: Google@9.0 ได้@9.4 เปิดตัว@9.5 โมเดล@9.9 ใหม่@10.3 ชื่อ@10.6'], r.stdout.splitlines())
        self.assertNotEqual(0, run(SCRIPTS / 'words_by_line.py').returncode)


if __name__ == '__main__':
    unittest.main()
