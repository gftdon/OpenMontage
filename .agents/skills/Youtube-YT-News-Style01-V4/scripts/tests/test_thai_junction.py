"""CF-A67 fix5: the shared junction rule (thai_junction.py), and the real text chain end to end with no ASR:
srt_to_script.py --strict -> caption_join.mjs -> lint_captions.py --source-script."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
# finalize.GATE_BOOT (finalize.py:134-140): the python gates run as `<py> -I -S -B -c GATE_BOOT <site dirs> <script> <args>`
GATE_BOOT = ("import runpy,sys;a=sys.argv;sys.path[:0]=[a[2].rpartition('/')[0]];sys.path+=[p for p in a[1].split(':') if p];"
             "sys.argv=a[2:];runpy.run_path(a[2],run_name='__main__')")


def load_tj():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location('thai_junction', SCRIPTS / 'thai_junction.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def srt(*cues):
    return ''.join(f'{i}\n00:00:{i:02d},000 --> 00:00:{i + 1:02d},000\n{c}\n\n' for i, c in enumerate(cues, 1))


def gate_cmd(script_name):
    """The command finalize.exe_for builds for a python gate."""
    site = ':'.join(sorted({sysconfig.get_paths()['purelib'], sysconfig.get_paths()['platlib']}))
    return [sys.executable, '-I', '-S', '-B', '-c', GATE_BOOT, site, str(SCRIPTS / script_name)]


class BreakProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tj = load_tj()

    def test_same_text_pair_gives_the_same_strings_whatever_surrounds_the_junction(self):
        a = self.tj.break_probe('ระบบนี้ช่วยให้การแส', 'ดงผลบนหน้าจอ')
        for left, right in (('ระบบนี้ช่วยให้การแส \\n'.replace('\\n', '\n'), '\n  ดงผลบนหน้าจอ'),
                            ('ระบบนี้ช่วยให้การแส​', '﻿​ดงผลบนหน้าจอ'),
                            ('ระบบนี้ช่วยให้การแส\n\n', 'ดงผลบนหน้าจอ')):
            with self.subTest(left=repr(left)):
                self.assertEqual(self.tj.break_probe(left, right), a)

    def test_windowing(self):
        left, right = 'ก' * 40, 'ข' * 40
        l, r = self.tj.break_probe(left, right)
        self.assertEqual((len(l), len(r)), (self.tj.WINDOW, self.tj.WINDOW))

    def test_judged_only_when_thai_thai_or_mai_yamok(self):
        self.assertIsNone(self.tj.break_probe('Gemini 4', 'ตัวใหม่'))
        self.assertIsNone(self.tj.break_probe('ตัวใหม่', 'Gemini 4'))
        self.assertIsNone(self.tj.break_probe('', 'ตัวใหม่'))
        self.assertIsNone(self.tj.break_probe('ตัวใหม่', ' ​'))
        self.assertIsNotNone(self.tj.break_probe('Gemini 4', 'ๆ แล้ว'))
        self.assertIsNotNone(self.tj.break_probe('ตัวใหม่', 'ตัวเก่า'))

    def test_cf_is_whitespace_for_finding_junctions_but_not_in_the_streams(self):
        self.assertEqual(self.tj.junction_gaps('ระ​บบ'), [(2, 3, 'space')])
        self.assertEqual(self.tj.thai_gaps('ระ​บบ'), [(2, 3)])
        self.assertEqual(self.tj.junction_gaps('​ๆ แล้ว')[0], (0, 1, 'break'))
        # the character streams compared with the source / SRT are untouched: Cf stays a kept character
        self.assertEqual(''.join(c for c, _ in self.tj.kept('ก​ข ค')), 'ก​ขค')


class ChainTests(unittest.TestCase):
    """The real chain on text only: SRT cues -> script.txt -> caption pages -> lint."""
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')
        if not cls.node:
            raise unittest.SkipTest('node is required for caption_join.mjs')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def run_py(self, script, *args, env=None):
        e = dict(os.environ)
        e.pop('LINT_CAPTIONS_SIMULATE_MISSING', None)
        e.update(env or {})
        return subprocess.run([sys.executable, '-B', str(SCRIPTS / script), *args], capture_output=True, text=True, env=e)

    def chain(self, source, cues):
        d = self.d
        (d / 'source_script.txt').write_text(source, encoding='utf-8')
        (d / 'avatar.srt').write_text(srt(*cues), encoding='utf-8')
        r1 = self.run_py('srt_to_script.py', '--srt', str(d / 'avatar.srt'), '--script', str(d / 'source_script.txt'),
                         '--strict', '--out', str(d / 'script.txt'))
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
        lines = (d / 'script.txt').read_text(encoding='utf-8').splitlines()
        from pythainlp.tokenize import word_tokenize
        words = [w for w in word_tokenize((d / 'script.txt').read_text(encoding='utf-8'), engine='newmm',
                                          keep_whitespace=False) if w.strip()]
        toks = [{'w': w, 's': round(i * 0.4, 2), 'e': round(i * 0.4 + 0.3, 2)} for i, w in enumerate(words)]
        (d / 'tokens.json').write_text(json.dumps([{'words': toks}], ensure_ascii=False), encoding='utf-8')
        (d / 'options.json').write_text(json.dumps({'endTime': round(len(words) * 0.4 + 0.2, 2)}), encoding='utf-8')
        r2 = subprocess.run([self.node, str(SCRIPTS / 'caption_join.mjs'), '--tokens', str(d / 'tokens.json'), '--script',
                             str(d / 'script.txt'), '--options', str(d / 'options.json'), '--out', str(d / 'captions.json')],
                            capture_output=True, text=True)
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        pages = json.loads((d / 'captions.json').read_text(encoding='utf-8'))['pages']
        r3 = self.run_py('lint_captions.py', '--script', str(d / 'script.txt'), '--pages', str(d / 'captions.json'),
                         '--source-script', str(d / 'source_script.txt'), '--report', str(d / 'lint.json'))
        report = json.loads((d / 'lint.json').read_text(encoding='utf-8')) if (d / 'lint.json').exists() else {}
        return lines, pages, r3, report

    def assert_clean(self, lines, pages, r3, report):
        self.assertEqual(r3.returncode, 0, json.dumps(report.get('issues'), ensure_ascii=False, indent=1))
        self.assertTrue(all(not l.lstrip().startswith('ๆ') for l in lines), lines)
        self.assertTrue(all(not p['text'].lstrip().startswith('ๆ') for p in pages), [p['text'] for p in pages])

    # 1. a cue that starts with ๆ
    def test_e2e_cue_starting_with_mai_yamok(self):
        source = 'เริ่มจากไอเดียคร่าว ๆ แล้วระบบจะช่วยสร้างโครงงานให้ทันที\n'
        # the first boundary of the 3-cue text (ไอเดีย|คร่าว) is a real word boundary and stays; only the ๆ one merges
        for cues, expected in ((['เริ่มจากไอเดียคร่าว', 'ๆ แล้วระบบจะช่วยสร้างโครงงานให้ทันที'],
                                ['เริ่มจากไอเดียคร่าว ๆ แล้วระบบจะช่วยสร้างโครงงานให้ทันที']),
                               (['เริ่มจากไอเดีย', 'คร่าว', 'ๆ แล้วระบบจะช่วยสร้างโครงงานให้ทันที'],
                                ['เริ่มจากไอเดีย', 'คร่าว ๆ แล้วระบบจะช่วยสร้างโครงงานให้ทันที'])):
            with self.subTest(cues=cues):
                lines, pages, r3, report = self.chain(source, cues)
                self.assertEqual(lines, expected)
                self.assert_clean(lines, pages, r3, report)

    # 2. a cue cut inside a word
    def test_e2e_cue_cut_inside_a_word(self):
        source = 'ระบบนี้ช่วยให้การแสดงผลบนหน้าจอลื่นไหลขึ้นมาก\n'
        lines, pages, r3, report = self.chain(source, ['ระบบนี้ช่วยให้การแส', 'ดงผลบนหน้าจอลื่นไหลขึ้นมาก'])
        self.assertFalse(any(l.endswith('การแส') for l in lines), lines)
        self.assertEqual(lines, ['ระบบนี้ช่วยให้การแสดงผลบนหน้าจอลื่นไหลขึ้นมาก'])
        self.assertFalse(any(p['text'].rstrip().endswith('แส') for p in pages), [p['text'] for p in pages])
        self.assert_clean(lines, pages, r3, report)

    # 3. no merge at a correct junction (a source space / a source line break between two dictionary words)
    def test_e2e_no_merge_at_a_source_space_or_line_break(self):
        for sep in (' ', '\n'):
            with self.subTest(sep=repr(sep)):
                source = 'ทีมวิจัยซึ่งบอกว่า' + sep + 'การขับรถอัตโนมัติจะมาถึงเร็ว ๆ นี้\n'
                lines, pages, r3, report = self.chain(source, ['ทีมวิจัยซึ่งบอกว่า', 'การขับรถอัตโนมัติจะมาถึงเร็ว ๆ นี้'])
                self.assertEqual(len(lines), 2, lines)
                self.assert_clean(lines, pages, r3, report)

    # 4. cascade
    def test_e2e_cascade(self):
        source = 'ระบบนี้ช่วยให้การแสดงผลบนหน้าจอลื่นไหลขึ้นมาก\n'
        lines, pages, r3, report = self.chain(source, ['ระบบนี้ช่วยให้การแส', 'ด', 'งผลบนหน้าจอลื่นไหลขึ้นมาก'])
        self.assertEqual(lines, ['ระบบนี้ช่วยให้การแสดงผลบนหน้าจอลื่นไหลขึ้นมาก'])
        self.assert_clean(lines, pages, r3, report)

    # lint on hand-made (unmerged) lines: proves the page break inside the word is reported, not skipped
    def test_unmerged_lines_are_reported_by_the_lint_chain(self):
        d = self.d
        source = 'ระบบนี้ช่วยให้การแสดงผลบนหน้าจอลื่นไหลขึ้นมาก\n'
        (d / 'source_script.txt').write_text(source, encoding='utf-8')
        (d / 'script.txt').write_text('ระบบนี้ช่วยให้การแส\nดงผลบนหน้าจอลื่นไหลขึ้นมาก\n', encoding='utf-8')
        toks = [{'w': w, 's': i * 0.4, 'e': i * 0.4 + 0.3} for i, w in
                enumerate(['ระบบ', 'นี้', 'ช่วย', 'ให้', 'การ', 'แส', 'ดงผล', 'บน', 'หน้าจอ', 'ลื่นไหล', 'ขึ้น', 'มาก'])]
        (d / 'tokens.json').write_text(json.dumps([{'words': toks}], ensure_ascii=False), encoding='utf-8')
        (d / 'options.json').write_text(json.dumps({'endTime': 5.2}), encoding='utf-8')
        r2 = subprocess.run([self.node, str(SCRIPTS / 'caption_join.mjs'), '--tokens', str(d / 'tokens.json'), '--script',
                             str(d / 'script.txt'), '--options', str(d / 'options.json'), '--out', str(d / 'captions.json')],
                            capture_output=True, text=True)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        r3 = self.run_py('lint_captions.py', '--script', str(d / 'script.txt'), '--pages', str(d / 'captions.json'),
                         '--source-script', str(d / 'source_script.txt'), '--report', str(d / 'lint.json'))
        self.assertEqual(r3.returncode, 1)
        counts = json.loads((d / 'lint.json').read_text(encoding='utf-8'))['counts']
        self.assertEqual(counts['midword-space'], 1)
        self.assertGreaterEqual(counts['midword-page-break'], 1)

    # 9. the python gates run under finalize's GATE_BOOT (-I -S -B -c): the shared module must import there too
    def test_gate_boot_run_gives_the_same_bytes(self):
        d = self.d
        source = 'ระบบนี้ช่วยให้การแสดงผลบนหน้าจอลื่นไหลขึ้นมาก\n'
        (d / 'source_script.txt').write_text(source, encoding='utf-8')
        (d / 'avatar.srt').write_text(srt('ระบบนี้ช่วยให้การแส', 'ดงผลบนหน้าจอลื่นไหลขึ้นมาก'), encoding='utf-8')
        env = dict(os.environ)
        env.pop('LINT_CAPTIONS_SIMULATE_MISSING', None)
        args = ['--srt', str(d / 'avatar.srt'), '--script', str(d / 'source_script.txt'), '--strict']
        r_n = self.run_py('srt_to_script.py', *args, '--out', str(d / 'normal.txt'))
        r_g = subprocess.run(gate_cmd('srt_to_script.py') + args + ['--out', str(d / 'gate.txt')], capture_output=True,
                             text=True, env=env, cwd=str(d))
        self.assertEqual((r_n.returncode, r_g.returncode), (0, 0), r_g.stderr)
        self.assertEqual((d / 'normal.txt').read_bytes(), (d / 'gate.txt').read_bytes())
        lint_args = ['--script', str(d / 'normal.txt'), '--pages', str(SCRIPTS / 'tests' / 'fixtures' / 'a67' / 'captions' /
                                                                         'pages_clean.json')]
        r_n = self.run_py('lint_captions.py', *lint_args, '--report', str(d / 'n.json'))
        r_g = subprocess.run(gate_cmd('lint_captions.py') + lint_args + ['--report', str(d / 'g.json')], capture_output=True,
                             text=True, env=env, cwd=str(d))
        self.assertEqual(r_g.returncode, r_n.returncode, r_g.stderr)
        self.assertEqual((d / 'n.json').read_bytes(), (d / 'g.json').read_bytes())
        self.assertEqual(r_n.stdout, r_g.stdout)

    def test_lint_without_the_shared_module_is_exit_4(self):
        alone = self.d / 'alone'
        alone.mkdir()
        (alone / 'lint_captions.py').write_bytes((SCRIPTS / 'lint_captions.py').read_bytes())
        r = subprocess.run([sys.executable, '-B', str(alone / 'lint_captions.py'), '--script', 'x', '--pages', 'y',
                            '--report', 'z'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 4)
        self.assertIn('ERROR: required tool missing', r.stderr)
        self.assertNotIn('Traceback', r.stderr)


if __name__ == '__main__':
    unittest.main()
