import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location('srt_to_script', SCRIPTS / 'srt_to_script.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SRT = (
    "1\n00:00:00,000 --> 00:00:09,697\n"
    "ปัญญาประดิษฐ์รุ่นล่าสุดสามารถนั่งทำงานต่อเนื่องได้ข้า\n"
    "มวันโดยไม่ต้องมีมนุษย์คอยสั่งงาน\n\n"
    "2\n00:00:09,697 --> 00:00:19,648\n"
    "Google ได้เปิดตัวโมเดลใหม่ชื่อ Gemini 4\n"
    "Carbon ซึ่งถูกระบุว่าเป็นโมเดลที่ทรงพลัง\n\n"
    "3\n00:00:19,648 --> 00:00:27,389\n"
    "ผู้ทดสอบ “ได้รับ” สิทธิ์\n"
    "ผ่านระบบ Anti-gravity\n"
)
SCRIPT = (
    "Part 1:\n"
    "ปัญญาประดิษฐ์รุ่นล่าสุดสามารถนั่งทำงานต่อเนื่องได้ข้ามวันโดยไม่ต้องมีมนุษย์คอยสั่งงาน\n"
    "Google ได้เปิดตัวโมเดลใหม่ชื่อ Gemini 4 Carbon ซึ่งถูกระบุว่าเป็นโมเดลที่ทรงพลัง\n"
    "\n"
    "part 2 :\n"
    "ผู้ทดสอบ “ได้รับ” สิทธิ์ ผ่านระบบ Anti-gravity\n"
)


class JoinTests(unittest.TestCase):
    def test_thai_rows_join_without_space(self):
        m = load()
        self.assertIn('ได้ข้ามวันโดย', m.parse(SRT)[0])
        self.assertNotIn('ข้า ม', m.parse(SRT)[0])

    def test_latin_rows_join_with_space(self):
        m = load()
        self.assertIn('Gemini 4 Carbon', m.parse(SRT)[1])

    def test_thai_latin_boundary_keeps_space(self):
        m = load()
        self.assertEqual(m.join_rows(['ผ่านระบบ', 'Gemini']), 'ผ่านระบบ Gemini')
        self.assertEqual(m.join_rows(['Gemini', 'ผ่านระบบ']), 'Gemini ผ่านระบบ')
        self.assertEqual(m.join_rows(['เวอร์ชัน 4', 'ตัวใหม่']), 'เวอร์ชัน 4 ตัวใหม่')

    def test_existing_normalisations(self):
        m = load()
        out = m.parse(SRT)
        # Thai|Thai row break is joined without a space (a real phrase gap there is
        # only recoverable with --script).
        self.assertEqual(out[2], 'ผู้ทดสอบ ได้รับ สิทธิ์ผ่านระบบ Anti-gravity')
        self.assertEqual(m.parse('1\n00:00:00,000 --> 00:00:01,000\n<i>เอ</i> บี → ซี\n')[0], 'เอ บี ซี')


class ScriptAuthorityTests(unittest.TestCase):
    def test_slices_equal_original_text_and_drop_headings(self):
        m = load()
        cues = m.parse(SRT)
        lines, warning = m.align_to_script(cues, SCRIPT)
        self.assertIsNone(warning)
        self.assertEqual(len(lines), 3)
        self.assertIn('ได้ข้ามวันโดยไม่ต้อง', lines[0])
        self.assertEqual(lines[1], 'Google ได้เปิดตัวโมเดลใหม่ชื่อ Gemini 4 Carbon ซึ่งถูกระบุว่าเป็นโมเดลที่ทรงพลัง')
        self.assertEqual(lines[2], 'ผู้ทดสอบ ได้รับ สิทธิ์ ผ่านระบบ Anti-gravity')
        self.assertFalse(any('Part' in l or 'part' in l for l in lines))

    def test_slice_keeps_original_space_where_srt_row_break_was_midword(self):
        m = load()
        srt = '1\n00:00:00,000 --> 00:00:01,000\nมากก\nว่าเดิม ทำงาน\n'
        lines, warning = m.align_to_script(m.parse(srt), 'มากกว่าเดิม ทำงาน\n')
        self.assertIsNone(warning)
        self.assertEqual(lines, ['มากกว่าเดิม ทำงาน'])

    def test_original_newline_inside_cue_becomes_single_space(self):
        m = load()
        srt = '1\n00:00:00,000 --> 00:00:01,000\nเอบี ซีดี\n'
        lines, warning = m.align_to_script(m.parse(srt), 'เอบี\nซีดี\n')
        self.assertEqual(lines, ['เอบี ซีดี'])

    def test_streams_differ_gives_warning(self):
        m = load()
        lines, warning = m.align_to_script(m.parse(SRT), SCRIPT.replace('สั่งงาน', 'สั่งการ'))
        self.assertIsNone(lines)
        self.assertIn('สั่ง', warning)


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / 'srt_to_script.py'), *args],
                              capture_output=True, text=True)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        (self.d / 'a.srt').write_text(SRT, encoding='utf-8')
        (self.d / 'script.txt').write_text(SCRIPT, encoding='utf-8')
        (self.d / 'bad.txt').write_text(SCRIPT.replace('สั่งงาน', 'สั่งการ'), encoding='utf-8')

    def test_legacy_cli(self):
        r = self.run_cli('--srt', str(self.d / 'a.srt'), '--out', str(self.d / 'o.txt'))
        self.assertEqual(r.returncode, 0, r.stderr)
        out = (self.d / 'o.txt').read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(out), 3)
        self.assertIn('ได้ข้ามวันโดย', out[0])

    def test_cli_with_script(self):
        r = self.run_cli('--srt', str(self.d / 'a.srt'), '--out', str(self.d / 'o.txt'),
                         '--script', str(self.d / 'script.txt'))
        self.assertEqual(r.returncode, 0, r.stderr)
        out = (self.d / 'o.txt').read_text(encoding='utf-8').splitlines()
        self.assertEqual(out[1], 'Google ได้เปิดตัวโมเดลใหม่ชื่อ Gemini 4 Carbon ซึ่งถูกระบุว่าเป็นโมเดลที่ทรงพลัง')

    def test_cli_mismatch_warns_falls_back_exit0(self):
        r = self.run_cli('--srt', str(self.d / 'a.srt'), '--out', str(self.d / 'o.txt'),
                         '--script', str(self.d / 'bad.txt'))
        self.assertEqual(r.returncode, 0)
        self.assertIn('WARNING', r.stderr)
        out = (self.d / 'o.txt').read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(out), 3)
        self.assertIn('ได้ข้ามวันโดย', out[0])

    def test_cli_mismatch_strict_exit1(self):
        r = self.run_cli('--srt', str(self.d / 'a.srt'), '--out', str(self.d / 'o.txt'),
                         '--script', str(self.d / 'bad.txt'), '--strict')
        self.assertEqual(r.returncode, 1)
        self.assertIn('WARNING', r.stderr)


def _srt(*cues):
    return ''.join(f'{i}\n00:00:{i:02d},000 --> 00:00:{i + 1:02d},000\n{c}\n\n' for i, c in enumerate(cues, 1))


class CueMergeTests(unittest.TestCase):
    """CF-A67 fix5: a cue boundary that fails the ONE junction rule is merged into a slice of the source."""
    @classmethod
    def setUpClass(cls):
        cls.m = load()

    def lines(self, source, *cues):
        lines, warning = self.m.align_to_script(self.m.parse(_srt(*cues)), source)
        self.assertIsNone(warning)
        return lines

    def test_cue_starting_with_mai_yamok_is_merged(self):
        src = 'เริ่มจากไอเดียคร่าว ๆ แล้วระบบจะช่วยสร้างโครงงานให้ทันที\n'
        self.assertEqual(self.lines(src, 'เริ่มจากไอเดียคร่าว', 'ๆ แล้วระบบจะช่วยสร้างโครงงานให้ทันที'),
                         ['เริ่มจากไอเดียคร่าว ๆ แล้วระบบจะช่วยสร้างโครงงานให้ทันที'])

    def test_cue_cut_inside_a_word_is_merged(self):
        src = 'ระบบนี้ช่วยให้การแสดงผลบนหน้าจอลื่นไหลขึ้นมาก\n'
        self.assertEqual(self.lines(src, 'ระบบนี้ช่วยให้การแส', 'ดงผลบนหน้าจอลื่นไหลขึ้นมาก'),
                         ['ระบบนี้ช่วยให้การแสดงผลบนหน้าจอลื่นไหลขึ้นมาก'])

    def test_no_merge_at_a_source_space_or_source_line_break(self):
        for sep in (' ', '\n'):
            with self.subTest(sep=repr(sep)):
                src = 'ทีมวิจัยซึ่งบอกว่า' + sep + 'การขับรถอัตโนมัติจะมาถึงเร็ว ๆ นี้\n'
                self.assertEqual(self.lines(src, 'ทีมวิจัยซึ่งบอกว่า', 'การขับรถอัตโนมัติจะมาถึงเร็ว ๆ นี้'),
                                 ['ทีมวิจัยซึ่งบอกว่า', 'การขับรถอัตโนมัติจะมาถึงเร็ว ๆ นี้'])

    def test_same_cut_without_source_whitespace_is_merged(self):
        src = 'ทีมวิจัยซึ่งบอกว่าการขับรถอัตโนมัติจะมาถึงเร็ว ๆ นี้\n'
        self.assertEqual(len(self.lines(src, 'ทีมวิจัยซึ่งบอกว่า', 'การขับรถอัตโนมัติจะมาถึงเร็ว ๆ นี้')), 1)

    def test_cascade_merges_until_every_junction_passes(self):
        src = 'ระบบนี้ช่วยให้การแสดงผลบนหน้าจอลื่นไหลขึ้นมาก\n'
        self.assertEqual(self.lines(src, 'ระบบนี้ช่วยให้การแส', 'ด', 'งผลบนหน้าจอลื่นไหลขึ้นมาก'),
                         ['ระบบนี้ช่วยให้การแสดงผลบนหน้าจอลื่นไหลขึ้นมาก'])

    def test_real_word_boundary_between_cues_is_kept(self):
        src = 'ผู้ใช้ทดสอบระบบ\nโปรแกรมที่มันสร้างขึ้น\n'
        self.assertEqual(self.lines(src, 'ผู้ใช้ทดสอบระบบ', 'โปรแกรมที่มันสร้างขึ้น'),
                         ['ผู้ใช้ทดสอบระบบ', 'โปรแกรมที่มันสร้างขึ้น'])

    def test_output_is_a_slice_of_the_source(self):
        src = 'เริ่มจาก “ไอเดีย” คร่าว ๆ\nแล้วระบบจะช่วย\n'
        lines = self.lines(src, 'เริ่มจากไอเดียคร่าว', 'ๆ แล้วระบบจะช่วย')
        self.assertEqual(lines, ['เริ่มจาก ไอเดีย คร่าว ๆ แล้วระบบจะช่วย'])   # original spacing; quotes dropped as before
        self.assertEqual(''.join(lines).replace(' ', ''), 'เริ่มจากไอเดียคร่าวๆแล้วระบบจะช่วย')


class CueMergeCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        # Thai|Thai cue boundary that is a real word boundary: judged, so the tools are needed
        (self.d / 'a.srt').write_text(_srt('ผู้ใช้ทดสอบระบบ', 'โปรแกรมที่มันสร้างขึ้น'), encoding='utf-8')
        (self.d / 'src.txt').write_text('ผู้ใช้ทดสอบระบบ\nโปรแกรมที่มันสร้างขึ้น\n', encoding='utf-8')
        (self.d / 'one.srt').write_text(_srt('ผู้ใช้ทดสอบระบบโปรแกรม'), encoding='utf-8')
        (self.d / 'one.txt').write_text('ผู้ใช้ทดสอบระบบโปรแกรม\n', encoding='utf-8')
        (self.d / 'other.txt').write_text('คนละเรื่องกันเลย\n', encoding='utf-8')

    def run_cli(self, *args, env=None, python=None):
        e = dict(os.environ)
        e.pop('LINT_CAPTIONS_SIMULATE_MISSING', None)
        e.update(env or {})
        return subprocess.run([python or sys.executable, '-B', str(SCRIPTS / 'srt_to_script.py'), *args],
                              capture_output=True, text=True, env=e)

    def base(self, srt='a.srt', script='src.txt'):
        return ['--srt', str(self.d / srt), '--script', str(self.d / script), '--strict', '--out', str(self.d / 'o.txt')]

    def test_ok_with_tools(self):
        r = self.run_cli(*self.base())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.d / 'o.txt').read_text(encoding='utf-8'), 'ผู้ใช้ทดสอบระบบ\nโปรแกรมที่มันสร้างขึ้น\n')

    def test_judged_junction_without_tools_is_exit_4(self):
        for name, env in (('simulated node', {'LINT_CAPTIONS_SIMULATE_MISSING': 'node'}),
                          ('simulated pythainlp', {'LINT_CAPTIONS_SIMULATE_MISSING': 'pythainlp'}),
                          ('no node on PATH', {'PATH': '/usr/bin:/bin'})):
            with self.subTest(name):
                (self.d / 'o.txt').unlink(missing_ok=True)
                r = self.run_cli(*self.base(), env=env)
                self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
                self.assertIn('ERROR: required tool missing', r.stderr)
                self.assertNotIn('Traceback', r.stderr)
                self.assertFalse((self.d / 'o.txt').exists())

    def test_fallback_path_needs_no_tools(self):
        env = {'LINT_CAPTIONS_SIMULATE_MISSING': 'node,pythainlp'}
        # streams differ: fallback join, strict exit 1 (never 4)
        r = self.run_cli(*self.base(script='other.txt'), env=env)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn('WARNING', r.stderr)
        # no --script at all
        r = self.run_cli('--srt', str(self.d / 'a.srt'), '--out', str(self.d / 'o.txt'), env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        # aligned, but no judged junction (one cue): no tool needed
        r = self.run_cli(*self.base('one.srt', 'one.txt'), env=env)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_missing_shared_module_is_exit_4_not_a_traceback(self):
        alone = self.d / 'alone'
        alone.mkdir()
        (alone / 'srt_to_script.py').write_bytes((SCRIPTS / 'srt_to_script.py').read_bytes())
        r = subprocess.run([sys.executable, '-B', str(alone / 'srt_to_script.py'), '--srt', str(self.d / 'a.srt'),
                            '--out', str(self.d / 'o.txt')], capture_output=True, text=True)
        self.assertEqual(r.returncode, 4)
        self.assertIn('ERROR: required tool missing', r.stderr)
        self.assertNotIn('Traceback', r.stderr)


if __name__ == '__main__':
    unittest.main()
