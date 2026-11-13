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

    def test_space_before_mai_yamok_is_legal(self):
        for line in ['เริ่มจากไอเดียคร่าว ๆ แล้วระบบ', 'ค่อย ๆ ทำไปทีละขั้น', 'ทำแบบง่าย ๆ ก็พอ']:
            with self.subTest(line=line):
                self.assertEqual(self.lint([line]), [])

    def test_space_after_mai_yamok_is_normal_boundary(self):
        self.assertEqual(self.lint(['คร่าวๆ แล้วระบบ', 'คร่าว ๆ แล้วระบบ']), [])

    def test_space_after_mai_yamok_before_any_word_is_boundary(self):
        # real jobs: oracle has no boundary at ๆ|บ once the space is removed, but a space after ๆ is always a boundary
        for line in ['กำลังมาแรงมาก ๆ บน GitHub', 'ดีสุด ๆ บนโลก', 'เริ่มจากไอเดียคร่าว ๆ บนระบบ']:
            with self.subTest(line=line):
                self.assertEqual(self.lint([line]), [])

    def test_script_line_starting_with_mai_yamok_flagged(self):
        issues = self.lint(['เริ่มจากไอเดียคร่าว', 'ๆ แล้วระบบ'])
        self.assertEqual(codes(issues), ['midword-space'])
        self.assertEqual(issues[0]['line'], 2)
        self.assertIn('ๆ', issues[0]['detail'])
        issues = self.lint(['  ๆ แล้วระบบ'])
        self.assertEqual(codes(issues), ['midword-space'])

    def test_real_split_still_flagged_with_mai_yamok_nearby(self):
        for line in ['ตรวจสอบระ บบ', 'เริ่มจากไอเดียคร่าว ๆ ระ บบ']:
            with self.subTest(line=line):
                self.assertEqual(codes(self.lint([line])), ['midword-space'])

    def test_space_before_other_thai_marks_not_exempt(self):
        # only ๆ is exempt; ฯ keeps the old oracle verdict
        self.assertEqual(codes(self.lint(['ท่านผู้ว่า ฯ ได้กล่าว'])), ['midword-space'])

    def test_mai_yamok_space_must_still_match_source(self):
        issues = self.lint(['คร่าว ๆ แล้ว'], source='คร่าวๆ แล้ว\n')
        self.assertEqual(codes(issues), ['space-not-in-source'])
        self.assertEqual(self.lint(['คร่าว ๆ แล้ว'], source='คร่าว ๆ แล้ว\n'), [])


# (left, right): a Thai|Thai junction that is legal Thai spacing (rule 1/2: around ๆ; rule 4: two dictionary words)
LEGAL = [('เริ่มจากไอเดียคร่าว ๆ', 'แล้วระบบ'), ('กำลังมาแรงมาก ๆ', 'บน GitHub'), ('ซึ่งบอกว่า', 'การขับรถ'),
         ('ผู้ใช้คาดว่า', 'การสร้างไฟล์'), ('พร้อมแล้ว', 'ไปเริ่ม'), ('คนเรียกว่า', 'การสร้าง'), ('ทั้งวัน', 'ตัวนี้')]
# real split: left is a word but the right token is not a dictionary word
SPLIT = ('ตรวจสอบระ', 'บบ')
# neither side qualifies: the token touching the junction is a single character / not in the dictionary
NOT_WORDS = [('ได้ข้ามวันโดยไม่ต้อ', 'ง'), ('ทำงานอัตโนมั', 'ติ'), ('ตรวจสอบการเคลื่อนไห', 'วของมันเอง'), ('สร้างภา', 'พสามมิติ')]


class JunctionRuleTests(unittest.TestCase):
    """thai_junction_ok(): the ONE rule behind midword-space and midword-page-break."""
    @classmethod
    def setUpClass(cls):
        cls.m = load()

    @staticmethod
    def page(text, start=0.0, display=None, lead=None):
        p = {'start': start, 'text': text, 'displayText': text.strip() if display is None else display}
        if lead is not None:
            p['leadingWhitespace'] = lead
        return p

    def test_legal_junction_as_script_line_space(self):
        for left, right in LEGAL:
            with self.subTest(left=left, right=right):
                self.assertEqual(self.m.lint_script([f'{left} {right}'], f'{left} {right}\n'), [])

    def test_legal_junction_inside_page_space(self):
        for left, right in LEGAL:
            with self.subTest(left=left, right=right):
                self.assertEqual(self.m.lint_pages([self.page(f'{left} {right}')], f'{left} {right}\n'), [])

    def test_legal_junction_as_page_break(self):
        for left, right in LEGAL:
            with self.subTest(left=left, right=right):
                pages = [self.page(left), self.page(' ' + right, 2.0, display=right, lead=' ')]
                self.assertEqual(self.m.lint_pages(pages, f'{left} {right}\n'), [])

    def test_inside_page_line_break_between_words_is_legal(self):
        self.assertEqual(self.m.lint_pages([self.page('พร้อมแล้ว\nไปเริ่ม')], 'พร้อมแล้ว ไปเริ่ม\n'), [])

    def test_rule4_needs_a_source(self):
        # without --source-script rule 4 is not available: stricter, not looser
        self.assertEqual(codes(self.m.lint_script(['บอกว่า การขับรถ'])), ['midword-space'])
        self.assertEqual(codes(self.m.lint_pages([self.page('บอกว่า การขับรถ')])), ['midword-page-break'])

    def test_rule4_accepted_risk_typo_in_the_source_passes(self):
        # ACCEPTED RISK: a typo IN THE SOURCE whose halves are both words ("แส ดง") passes; that is the script
        # step's fault, the edit step cannot change the source.
        self.assertEqual(self.m.lint_script(['การแส ดงผล'], 'การแส ดงผล\n'), [])
        self.assertEqual(self.m.lint_pages([self.page('การแส ดงผล')], 'การแส ดงผล\n'), [])

    def test_rule4_page_break_without_source_whitespace_fails(self):
        # the engine breaks a page mid-word where the source has no space: only rules 1-3 apply
        src = 'การแสดงผล\n'
        for ws in ('', ' '):
            with self.subTest(ws=ws):
                pages = [self.page('การแส'), self.page(ws + 'ดงผล', 2.0, display='ดงผล', lead=ws)]
                issues = self.m.lint_pages(pages, src)
                self.assertEqual(codes(issues), ['midword-page-break'])
                self.assertEqual(issues[0]['page'], 2)
        self.assertEqual(codes(self.m.lint_pages([self.page('การแส ดงผล')], src)), ['midword-page-break'])

    def test_rule4_page_break_at_source_space_passes_but_not_at_other_space(self):
        src = 'ซึ่งบอกว่า การขับรถ\n'
        pages = [self.page('ซึ่งบอกว่า'), self.page(' การขับรถ', 2.0, display='การขับรถ', lead=' ')]
        self.assertEqual(self.m.lint_pages(pages, src), [])
        self.assertEqual(self.m.lint_pages([self.page('ซึ่งบอกว่า การขับรถ')], src), [])
        # same words, but the source has NO space there: rule 4 is not available
        src2 = 'ซึ่งบอกว่าการขับรถ\n'
        self.assertEqual(codes(self.m.lint_pages(pages, src2)), ['midword-page-break'])
        self.assertEqual(codes(self.m.lint_script(['ซึ่งบอกว่า การขับรถ'], src2)),
                         ['midword-space', 'space-not-in-source'])

    def test_rule4_pages_must_match_the_source_stream(self):
        # pages whose characters differ from the source cannot be mapped: rule 4 off
        pages = [self.page('ซึ่งบอกว่า การขับรถ')]
        self.assertEqual(codes(self.m.lint_pages(pages, 'อย่างอื่นเลย\n')), ['midword-page-break'])

    def test_real_split_fails_as_space_and_as_break(self):
        # with the space present in the source, rule 4 is a candidate, but "บบ" is not a dictionary word
        left, right = SPLIT
        for src in (None, f'{left} {right}\n'):
            with self.subTest(source=src):
                self.assertEqual(codes(self.m.lint_script([f'{left} {right}'], src))[:1], ['midword-space'])
                self.assertEqual(codes(self.m.lint_pages([self.page(f'{left} {right}')], src)), ['midword-page-break'])
                self.assertEqual(codes(self.m.lint_pages([self.page(f'{left}\n{right}')], src)), ['midword-page-break'])
                for ws in ('', ' '):
                    pages = [self.page(left), self.page(ws + right, 2.0, display=right, lead=ws)]
                    issues = self.m.lint_pages(pages, src)
                    self.assertEqual(codes(issues), ['midword-page-break'])
                    self.assertEqual(issues[0]['page'], 2)

    def test_single_char_or_non_dictionary_token_fails(self):
        for left, right in NOT_WORDS:
            for src in (None, f'{left} {right}\n'):
                with self.subTest(left=left, right=right, source=src):
                    self.assertEqual(codes(self.m.lint_script([f'{left} {right}'], src))[:1], ['midword-space'])
                    self.assertEqual(codes(self.m.lint_pages([self.page(f'{left} {right}')], src)), ['midword-page-break'])

    def test_one_side_being_a_word_is_not_enough(self):
        # SPLIT covers "left is a word, right is not"; here the mirror: left token "มั" is not a word, right "ติดตั้ง" is
        text = 'ตรวจสอบอัตโนมั ติดตั้ง'
        for src in (None, text + '\n'):
            with self.subTest(source=src):
                self.assertEqual(codes(self.m.lint_script([text], src))[:1], ['midword-space'])
                self.assertEqual(codes(self.m.lint_pages([self.page(text)], src)), ['midword-page-break'])

    def test_extra_split_with_single_character_right_token_fails(self):
        # new extra test: right token "ง" is a single character, so it fails even when the source has the space
        text = 'ข้อมูลที่ถูกต้อ งการ'
        for src in (None, text + '\n'):
            with self.subTest(source=src):
                self.assertEqual(codes(self.m.lint_script([text], src))[:1], ['midword-space'])

    def test_function_contract(self):
        f = self.m.thai_junction_ok
        self.assertTrue(f('คร่าว', 'ๆ', 'space'))
        self.assertFalse(f('คร่าว', 'ๆ', 'break'))
        self.assertFalse(f('', 'ๆ แล้ว', 'break'))
        self.assertTrue(f('มาก ๆ', 'บน', 'break'))
        self.assertTrue(f('มาก ๆ', 'บน', 'space'))
        self.assertFalse(f('บอกว่า', 'การขับรถ', 'space'))   # rule 4 needs src_ok
        self.assertTrue(f('บอกว่า', 'การขับรถ', 'space', src_ok=True))
        self.assertTrue(f('บอกว่า', 'การขับรถ', 'break', src_ok=True))
        self.assertFalse(f('ตรวจสอบระ', 'บบ', 'space', src_ok=True))
        self.assertFalse(f('ตรวจสอบระ', 'บบ', 'space'))
        self.assertFalse(f('ตรวจสอบระ', 'บบ', 'break'))


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

    @staticmethod
    def page(text, start=0.0, display=None, lead=None):
        p = {'start': start, 'text': text, 'displayText': text.strip() if display is None else display}
        if lead is not None:
            p['leadingWhitespace'] = lead
        return p

    def test_space_before_mai_yamok_inside_page_legal(self):
        for body in ['เริ่มจากไอเดียคร่าว ๆ', 'คร่าว ๆ', 'เริ่มจากไอเดียคร่าว ๆ แล้วระบบ']:
            with self.subTest(body=body):
                self.assertEqual(self.m.lint_pages([self.page(body)]), [])

    def test_page_starting_with_mai_yamok_flagged(self):
        for first, lead, second in [('เริ่มจากไอเดียคร่าว', ' ', ' ๆ แล้ว'), ('เริ่มจากไอเดียคร่าว', '', 'ๆ แล้ว'),
                                    ('เริ่มจากไอเดียคร่าว\n', '', 'ๆ แล้ว')]:
            with self.subTest(first=first, lead=lead, second=second):
                pages = [self.page(first), self.page(second, 2.0, display=second.strip(),
                                                      lead=(second[:len(second) - len(second.lstrip())]))]
                issues = self.m.lint_pages(pages)
                self.assertEqual(codes(issues), ['midword-page-break'])
                self.assertEqual(issues[0]['page'], 2)
                self.assertIn('ๆ', issues[0]['detail'])

    def test_first_page_starting_with_mai_yamok_flagged(self):
        issues = self.m.lint_pages([self.page('ๆ แล้ว')])
        self.assertEqual(codes(issues), ['midword-page-break'])

    def test_display_line_starting_with_mai_yamok_flagged(self):
        issues = self.m.lint_pages([self.page('เริ่มจากไอเดียคร่าว\nๆ แล้ว')])
        self.assertEqual(codes(issues), ['midword-page-break'])
        self.assertIn('ๆ', issues[0]['detail'])
        issues = self.m.lint_pages([self.page('เริ่มจากไอเดียคร่าว \n ๆ แล้ว')])
        self.assertEqual(codes(issues), ['midword-page-break'])

    def test_space_after_mai_yamok_page_break_ok(self):
        pages = [self.page('เริ่มจากไอเดียคร่าว ๆ'), self.page(' แล้วระบบ', 2.0, display='แล้วระบบ', lead=' ')]
        self.assertEqual(self.m.lint_pages(pages), [])

    def test_space_before_other_thai_marks_not_exempt_in_page(self):
        self.assertEqual(codes(self.m.lint_pages([self.page('ท่านผู้ว่า ฯ ได้กล่าว')])), ['midword-page-break'])

    def test_space_after_mai_yamok_before_any_word_is_boundary_in_page(self):
        self.assertEqual(self.m.lint_pages([self.page('กำลังมาแรงมาก ๆ บน GitHub')]), [])

    def test_page_break_across_space_after_mai_yamok_is_boundary(self):
        pages = [self.page('กำลังมาแรงมาก ๆ'), self.page(' บน GitHub', 2.0, display='บน GitHub', lead=' ')]
        self.assertEqual(self.m.lint_pages(pages), [])

    def test_real_page_split_still_flagged(self):
        pages = [self.page('ทำงานของระ'), self.page('บบอัตโนมัติ', 2.0)]
        issues = self.m.lint_pages(pages)
        self.assertEqual(codes(issues), ['midword-page-break'])
        self.assertEqual(issues[0]['page'], 2)
        self.assertEqual(codes(self.m.lint_pages([self.page('ทำงานของระ บบอัตโนมัติ')])), ['midword-page-break'])

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

    def test_source_script_enables_rule4_end_to_end(self):
        (self.d / 'phrase.txt').write_text('ซึ่งบอกว่า การขับรถ\n', encoding='utf-8')
        (self.d / 'pages.json').write_text(json.dumps({'pages': [
            {'start': 0.0, 'text': 'ซึ่งบอกว่า', 'displayText': 'ซึ่งบอกว่า', 'leadingWhitespace': ''},
            {'start': 1.0, 'text': ' การขับรถ', 'displayText': 'การขับรถ', 'leadingWhitespace': ' '}]}, ensure_ascii=False),
            encoding='utf-8')
        base = ['--script', str(self.d / 'phrase.txt'), '--pages', str(self.d / 'pages.json'), '--report', str(self.d / 'r.json')]
        r = self.run_cli(*base, '--source-script', str(self.d / 'phrase.txt'))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.run_cli(*base).returncode, 1)

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
