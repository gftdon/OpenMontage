import importlib.util
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


if __name__ == '__main__':
    unittest.main()
