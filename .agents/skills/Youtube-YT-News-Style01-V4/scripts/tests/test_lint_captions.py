import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
FIX = Path(__file__).resolve().parent / 'fixtures' / 'a67' / 'captions'


def load():
    spec = importlib.util.spec_from_file_location('lint_captions', SCRIPTS / 'lint_captions.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def codes(issues):
    return [i['code'] for i in issues]


class ScriptLintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load()

    def lint(self, lines, source=None):
        return self.m.lint_script(lines, source_text=source)

    def test_flagged_midword_spaces(self):
        for line in ['ได้ข้า มวันโดยไม่ต้อง', 'ตรวจสอบการเคลื่อนไห วของมันเอง', 'สร้างภา พสามมิติ', 'มากก ว่าเดิม']:
            with self.subTest(line=line):
                issues = self.lint([line])
                self.assertEqual(codes(issues), ['midword-space'])
                self.assertEqual(issues[0]['line'], 1)
                self.assertIn(' ', issues[0]['context'])

    def test_controls_not_flagged(self):
        for line in ['ทำงาน ข้ามวัน ได้', 'ทำได้ ดี', 'โมเดล Gemini 4 ตัวใหม่', 'ราคา 20 บาท',
                     'ใช้ Three.js สร้างภาพ', 'เวอร์ชัน 4 ตัวใหม่']:
            with self.subTest(line=line):
                self.assertEqual(self.lint([line]), [])

    def test_line_numbers(self):
        issues = self.lint(['สะอาดดี', 'ทำงาน ข้ามวัน', 'มากก ว่าเดิม'])
        self.assertEqual([i['line'] for i in issues], [3])

    def test_space_not_in_source(self):
        # whitespace-legit per oracle ("ทำได้ ดี") but the source has none there
        issues = self.lint(['ทำได้ ดี'], source='Part 1:\nทำได้ดี\n')
        self.assertEqual(codes(issues), ['space-not-in-source'])
        # same space exists in source -> clean
        self.assertEqual(self.lint(['ทำได้ ดี'], source='ทำได้ ดี\n'), [])

    def test_source_space_next_to_quote_counts_as_space(self):
        self.assertEqual(self.lint(['ผู้ทดสอบ ได้รับ'], source='ผู้ทดสอบ \u201cได้รับ\u201d\n'), [])

    def test_source_stream_mismatch_reported_not_skipped(self):
        issues = self.lint(['ทำได้ ดี'], source='ทำได้ดีมาก\n')
        self.assertIn('source-stream-mismatch', codes(issues))


class PageLintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load()

    def pages(self, name):
        return self.m.load_pages(FIX / name)

    def test_page_break_midword_flagged(self):
        issues = self.m.lint_pages(self.pages('pages_midword.json'))
        self.assertEqual(codes(issues), ['midword-page-break'])
        self.assertEqual(issues[0]['page'], 2)
        self.assertAlmostEqual(issues[0]['t'], 103.34)

    def test_clean_page_break_not_flagged(self):
        self.assertEqual(self.m.lint_pages(self.pages('pages_clean.json')), [])

    def test_script_line_break_between_pages_not_flagged(self):
        self.assertEqual(self.m.lint_pages(self.pages('pages_newline.json')), [])

    def test_whitespace_between_pages_still_tested(self):
        issues = self.m.lint_pages(self.pages('pages_midword_spaced.json'))
        self.assertEqual(codes(issues), ['midword-page-break'])

    def test_display_text_inner_break_flagged(self):
        issues = self.m.lint_pages(self.pages('pages_display_break.json'))
        self.assertEqual(codes(issues), ['midword-page-break'])
        self.assertIn('displayText', issues[0]['detail'])

    def test_load_pages_accepts_dict_and_list(self):
        self.assertEqual(len(self.pages('pages_midword.json')), 3)
        self.assertEqual(len(self.pages('pages_clean.json')), 4)

    def test_load_pages_rejects_bad_shape(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'x.json'
            p.write_text('{"nope": 1}')
            with self.assertRaises(self.m.BadInput):
                self.m.load_pages(p)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        (self.d / 'bad.txt').write_text('ได้ข้า มวันโดยไม่ต้อง\nทำงาน ข้ามวัน ได้\n', encoding='utf-8')
        (self.d / 'good.txt').write_text('ได้ข้ามวันโดยไม่ต้อง\nทำงาน ข้ามวัน ได้\n', encoding='utf-8')

    def run_cli(self, *args, env=None):
        e = dict(os.environ)
        e.pop('LINT_CAPTIONS_SIMULATE_MISSING', None)
        e.update(env or {})
        return subprocess.run([sys.executable, str(SCRIPTS / 'lint_captions.py'), *args],
                              capture_output=True, text=True, env=e)

    def test_exit1_and_report_schema(self):
        rep = self.d / 'r.json'
        r = self.run_cli('--script', str(self.d / 'bad.txt'), '--pages', str(FIX / 'pages_clean.json'),
                         '--report', str(rep))
        self.assertEqual(r.returncode, 1, r.stderr)
        report = json.loads(rep.read_text(encoding='utf-8'))
        self.assertEqual(json.loads(r.stdout), report)
        self.assertEqual(report['schema'], 'yt-news-v4-captions-lint')
        self.assertEqual(report['version'], 1)
        self.assertFalse(report['pass'])
        self.assertEqual(report['counts']['midword-space'], 1)
        self.assertEqual(len(report['issues']), 1)
        self.assertEqual(len(report['inputs']), 2)
        for sha in report['inputs'].values():
            self.assertRegex(sha, r'^[0-9a-f]{64}$')
        self.assertIn('icu', report['tools'])
        self.assertIn('pythainlp', report['tools'])

    def test_exit0_pass(self):
        rep = self.d / 'r.json'
        r = self.run_cli('--script', str(self.d / 'good.txt'), '--pages', str(FIX / 'pages_clean.json'),
                         '--report', str(rep))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(rep.read_text())['pass'])

    def test_exit2_missing_input(self):
        r = self.run_cli('--script', str(self.d / 'nope.txt'), '--pages', str(FIX / 'pages_clean.json'),
                         '--report', str(self.d / 'r.json'))
        self.assertEqual(r.returncode, 2)

    def test_exit2_bad_pages_json(self):
        (self.d / 'p.json').write_text('{not json')
        r = self.run_cli('--script', str(self.d / 'good.txt'), '--pages', str(self.d / 'p.json'),
                         '--report', str(self.d / 'r.json'))
        self.assertEqual(r.returncode, 2)

    def test_exit4_pythainlp_missing(self):
        r = self.run_cli('--script', str(self.d / 'good.txt'), '--pages', str(FIX / 'pages_clean.json'),
                         '--report', str(self.d / 'r.json'), env={'LINT_CAPTIONS_SIMULATE_MISSING': 'pythainlp'})
        self.assertEqual(r.returncode, 4)
        self.assertIn('pythainlp', r.stderr)

    def test_exit4_node_missing(self):
        r = self.run_cli('--script', str(self.d / 'good.txt'), '--pages', str(FIX / 'pages_clean.json'),
                         '--report', str(self.d / 'r.json'), env={'LINT_CAPTIONS_SIMULATE_MISSING': 'node'})
        self.assertEqual(r.returncode, 4)
        self.assertIn('node', r.stderr)

    def test_check_tools_raises(self):
        m = load()
        os.environ['LINT_CAPTIONS_SIMULATE_MISSING'] = 'node'
        try:
            with self.assertRaises(m.ToolMissing):
                m.check_tools()
        finally:
            del os.environ['LINT_CAPTIONS_SIMULATE_MISSING']


if __name__ == '__main__':
    unittest.main()
