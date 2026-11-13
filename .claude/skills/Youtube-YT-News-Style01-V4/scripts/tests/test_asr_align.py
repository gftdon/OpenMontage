"""asr_align.py: raw ASR words + exact script -> caption pages in the old extract_timing.py format, deterministic.
All inputs are synthetic.  Runs with any python that has pythainlp (the project .venv has it)."""
import ast
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import asr_align as aa  # noqa: E402

FIXTURES = SCRIPTS / 'tests' / 'fixtures' / 'a67' / 'timing'
# how the chain is started (asr_align.py refuses otherwise): the Cellar python that asr_run.sh pins, directly (these tests are not
# about the launcher; test_asr_run.py is), with the four flags the launcher adds
PYROOT = re.search(r'^PYROOT=(.*)$', (SCRIPTS / 'asr_run.sh').read_text(encoding='utf-8'), re.M).group(1)
PYBIN = Path(PYROOT) / 'bin' / 'python3.12'
RUN = [str(PYBIN), '-I', '-S', '-B', '-X', 'pycache_prefix=/var/empty']
HAVE_CHAIN = PYBIN.exists() and (Path(aa.SITE_DIR) / 'pythainlp').is_dir()          # the real V4 venv (the script appends it itself)


def chain_pythainlp_version():
    """the pythainlp the CHAIN will see = the V4 venv's (its dist-info), never the test runner's interpreter: the launcher runs the chain
    from the V4 venv, and asr_align.py exits 4 when raw_asr.json was written with another tokenizer version"""
    found = sorted(Path(aa.SITE_DIR).glob('pythainlp-*.dist-info'))
    if len(found) == 1:
        return found[0].name[len('pythainlp-'):-len('.dist-info')]
    import pythainlp
    return pythainlp.__version__                                                  # no V4 venv here: the CLI tests are skipped anyway


CHAIN_PYTHAINLP = chain_pythainlp_version()
# read-only reference of the vendored code (optional: the live comparison below skips when it is absent or changed; the frozen
# fixture test next to it always runs)
REF_DIR = Path.home() / '.claude' / 'skills' / 'karaoke-subtitle' / 'scripts'
REF_SHA = {'make_karaoke_sub.py': '2c9da476ae0fdb488f46c1183556c2b77c804d7e095fbdcf6fb0c75520c41ab4',
           'karaoke_lib.py': 'a299e346ab6bc4d7fdf1af32ec2edb22f4207b69d2074e6f916ab3188a184831'}


def raw_of(words, version=None, script_sha='0' * 64):
    """[(word, start, end)] -> a raw_asr v1 document (one segment per 6 words, whisper-style leading spaces)"""
    segs = []
    for i in range(0, len(words), 6):
        ws = [{'word': ' ' + w, 'start': s, 'end': e} for w, s, e in words[i:i + 6]]
        segs.append({'start': ws[0]['start'], 'end': ws[-1]['end'], 'text': ''.join(w['word'] for w in ws),
                     'compression_ratio': 1.2, 'avg_logprob': -0.2, 'no_speech_prob': 0.01, 'rung': 'R0', 'words': ws})
    return {'schema': 'yt-news-v4-raw-asr', 'version': 1, 'audio': {'wav_sha256': '0' * 64, 'duration': 99.0},
            'script_sha256': script_sha, 'model': {'id': 'm', 'snapshot': 's'}, 'mlx_whisper': {'version': 'x', 'files': {}},
            'tokenizer': {'pythainlp': version or CHAIN_PYTHAINLP}, 'params': {}, 'rungs': [], 'segments': segs}


def timed(text_words, t0=0.5, dur=0.31, gap=0.07):
    out, t = [], t0
    for w in text_words:
        out.append((w, round(t, 2), round(t + dur, 2)))
        t += dur + gap
    return out


LATIN = 'alpha beta gamma delta epsilon zeta eta theta iota kappa'.split()
THAI_LINES = ['วันนี้ ทีมงาน ทดสอบ ระบบ ใหม่', 'ราคา 700-10,000 บาท ต่อ เดือน', 'สอน AI 10 ตัว ภายใน หนึ่ง วัน']


THAI_SCRIPT_SHA = hashlib.sha256(('\n'.join(THAI_LINES) + '\n').encode('utf-8')).hexdigest()     # what CliTests writes to script.txt


def thai_raw(misspell=False):
    words = []
    for line in THAI_LINES:
        for w in line.split():
            words.append(w.replace('ทีมงาน', 'ทีมงาร') if misspell else w)
    return raw_of(timed(words, dur=0.4, gap=0.12), script_sha=THAI_SCRIPT_SHA)


class FormatTests(unittest.TestCase):
    def test_pages_format_rounding_and_bytes(self):
        raw = raw_of(timed(LATIN, t0=0.123456, dur=0.333333))
        pages, anchors = aa.align(raw, [' '.join(LATIN[:5]), ' '.join(LATIN[5:])])
        self.assertEqual(LATIN, [w['w'] for p in pages for w in p['words']])
        for p in pages:
            self.assertEqual(['start', 'end', 'words'], list(p))
            self.assertLessEqual(len(p['words']), aa.MAX_WORDS)
            self.assertEqual((p['words'][0]['s'], p['words'][-1]['e']), (p['start'], p['end']))
            for w in p['words']:
                self.assertEqual(['w', 's', 'e'], list(w))
                for v in (w['s'], w['e']):
                    self.assertEqual(round(v, 3), v)
        text = aa.pages_text(pages)
        self.assertEqual(json.dumps(pages, ensure_ascii=False, indent=1), text)
        self.assertFalse(text.endswith('\n'))
        self.assertTrue(text.startswith('[\n {\n  "start": '))
        self.assertEqual([1.0] * len(LATIN), anchors)

    def test_script_wording_wins_over_asr_spelling_and_thai_is_not_escaped(self):
        pages, anchors = aa.align(thai_raw(misspell=True), THAI_LINES)
        words = [w['w'] for p in pages for w in p['words']]
        self.assertIn('ทีมงาน', ''.join(words))
        self.assertNotIn('ทีมงาร', ''.join(words))
        self.assertIn('700-10,000', words)                               # _merge_adjacent joins the non-Thai crumbs
        self.assertIn('ทีม', aa.pages_text(pages))
        self.assertLess(min(a for a in anchors if a is not None), 1.0)   # the misspelt letter was interpolated
        flat = [w for p in pages for w in p['words']]
        for a, b in zip(flat, flat[1:]):
            self.assertLessEqual(a['e'], b['s'])

    def test_anchored_flags_mark_interpolated_characters(self):
        raw = raw_of(timed(['abc', 'def', 'ghi']))
        res, anchored = aa.apply_script({'segments': raw['segments']}, ['abc xyz ghi'])
        self.assertEqual([True] * 3 + [False] * 3 + [True] * 3, anchored)
        self.assertEqual(['abc', 'xyz', 'ghi'], ''.join(w['word'] for w in res['segments'][0]['words']).split(' '))
        self.assertEqual((raw, None), aa.apply_script(raw, []))

    def test_same_input_same_bytes(self):
        raw = thai_raw()
        a = aa.pages_text(aa.align(json.loads(json.dumps(raw)), THAI_LINES)[0])
        b = aa.pages_text(aa.align(json.loads(json.dumps(raw)), THAI_LINES)[0])
        self.assertEqual(a, b)


class FrozenEquivalenceTests(unittest.TestCase):
    """raw + script -> pages bytes, produced ONCE with the reference chain (make_karaoke_sub.apply_script + karaoke_lib.build_chunks
    + extract_timing's page format; fixtures/a67/timing/vendored_equiv_*, synthetic text).  Runs on every machine, so the fidelity of
    the vendored copies does not depend on the read-only reference files being present."""
    def test_vendored_chain_writes_the_frozen_reference_bytes(self):
        raw = json.loads((FIXTURES / 'vendored_equiv_raw.json').read_text(encoding='utf-8'))
        lines = aa.read_script_lines(str(FIXTURES / 'vendored_equiv_script.txt'))
        pages, _ = aa.align(raw, lines)
        expected = (FIXTURES / 'vendored_equiv_pages.json').read_bytes()
        self.assertEqual(expected, aa.pages_text(pages).encode('utf-8'))
        self.assertGreater(len(pages), 10)                                    # not a trivial fixture: pauses, merges, interpolation
        self.assertEqual(hashlib.sha256((FIXTURES / 'vendored_equiv_script.txt').read_bytes()).hexdigest(), raw['script_sha256'])

    def test_a_changed_vendored_function_would_break_the_fixture(self):
        raw = json.loads((FIXTURES / 'vendored_equiv_raw.json').read_text(encoding='utf-8'))
        lines = aa.read_script_lines(str(FIXTURES / 'vendored_equiv_script.txt'))
        keep = aa.MAX_WORDS
        aa.MAX_WORDS = 3                                                      # any behavioural drift of the pagination shows
        try:
            pages, _ = aa.align(raw, lines)
        finally:
            aa.MAX_WORDS = keep
        self.assertTrue((FIXTURES / 'vendored_equiv_pages.json').read_bytes() != aa.pages_text(pages).encode('utf-8'))

    def test_a_changed_alignment_logic_would_break_the_fixture_too(self):
        """N9: not only the pagination constants: the pause rule, the page width and the character timeline that the script is aligned onto are covered too"""
        raw = json.loads((FIXTURES / 'vendored_equiv_raw.json').read_text(encoding='utf-8'))
        lines = aa.read_script_lines(str(FIXTURES / 'vendored_equiv_script.txt'))
        frozen = (FIXTURES / 'vendored_equiv_pages.json').read_bytes()
        self.assertEqual(frozen, aa.pages_text(aa.align(json.loads(json.dumps(raw)), lines)[0]).encode('utf-8'))      # the control: unmutated = equal
        orig_timeline = aa._asr_char_timeline
        mutants = {
            'PAUSE': ('PAUSE', 0.0),
            'MAX_CHARS': ('MAX_CHARS', aa.MAX_CHARS - 6),
            'char timeline shifted': ('_asr_char_timeline', lambda result: [(c, a + 0.05, b + 0.05) for c, a, b in orig_timeline(result)]),
            'char timeline loses its last character': ('_asr_char_timeline', lambda result: orig_timeline(result)[:-1]),
        }
        for name, (attr, value) in mutants.items():
            with self.subTest(mutant=name):
                keep = getattr(aa, attr)
                setattr(aa, attr, value)
                try:
                    pages, _ = aa.align(json.loads(json.dumps(raw)), lines)
                finally:
                    setattr(aa, attr, keep)
                self.assertNotEqual(frozen, aa.pages_text(pages).encode('utf-8'), 'the mutation of %s did not change the pages' % name)


@unittest.skipUnless(all((REF_DIR / n).is_file() and hashlib.sha256((REF_DIR / n).read_bytes()).hexdigest() == h
                         for n, h in REF_SHA.items()), 'read-only reference of the vendored code not present / changed')
class VendoredEquivalenceTests(unittest.TestCase):
    """The vendored functions must produce exactly what the reference produced (extract_timing.py's pipeline)."""
    @classmethod
    def setUpClass(cls):
        keep = sys.dont_write_bytecode
        sys.dont_write_bytecode = True                                    # never write into the reference dir
        sys.path.insert(0, str(REF_DIR))
        try:
            import make_karaoke_sub as mk
            import karaoke_lib as kl
        except ImportError as e:                                          # the reference needs PIL, which only the old karaoke venv has
            raise unittest.SkipTest('the read-only reference code cannot be imported here: %s' % e)
        finally:
            sys.path.remove(str(REF_DIR))
            sys.dont_write_bytecode = keep
        cls.mk, cls.kl = mk, kl

    def old_text(self, raw, lines):
        res = self.mk.apply_script({'segments': raw['segments']}, lines)
        return aa.pages_text(aa.chunks_to_pages(self.kl.build_chunks(res, max_words=4, max_chars=24, pause=0.42)))

    def test_same_bytes_as_the_reference_chain(self):
        cases = [(thai_raw(), THAI_LINES), (thai_raw(misspell=True), THAI_LINES),
                 (raw_of(timed(LATIN, dur=0.2, gap=0.5)), [' '.join(LATIN)]),            # pause breaks
                 (raw_of(timed(['abc', 'def', 'ghi'])), ['abc xyz ghi', 'jkl'])]           # interpolation + clamp at the end
        for raw, lines in cases:
            with self.subTest(lines=lines[0]):
                self.assertEqual(self.old_text(raw, lines), aa.pages_text(aa.align(raw, lines)[0]))


@unittest.skipUnless(HAVE_CHAIN, 'the pinned python / the V4 ASR venv are not on this machine')
class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.script = self.d / 'script.txt'
        self.script.write_text('\n'.join(THAI_LINES) + '\n', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, doc):
        p = self.d / name
        p.write_text(doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False), encoding='utf-8')
        return p

    def run_cli(self, raw, script=None, out=None):
        out = out or self.d / 'pages.json'
        return subprocess.run([*RUN, str(SCRIPTS / 'asr_align.py'), '--raw', str(raw), '--script',
                               str(script or self.script), '--out', str(out)], capture_output=True, text=True), out

    def test_writes_pages_twice_identically_and_atomically(self):
        raw = self.put('raw.json', thai_raw())
        r, out = self.run_cli(raw)
        self.assertEqual(0, r.returncode, r.stderr)
        first = out.read_bytes()
        r, out = self.run_cli(raw)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(first, out.read_bytes())
        self.assertEqual(aa.pages_text(aa.align(thai_raw(), THAI_LINES)[0]).encode('utf-8'), first)
        self.assertEqual([], [p.name for p in self.d.iterdir() if '.tmp' in p.name])

    def test_other_tokenizer_version_is_exit_4(self):
        raw = self.put('raw.json', thai_raw() | {'tokenizer': {'pythainlp': '0.0.1'}})
        r, out = self.run_cli(raw)
        self.assertEqual(4, r.returncode, r.stderr)
        self.assertIn('pythainlp', r.stderr)
        self.assertFalse(out.exists())

    def test_bad_input_is_exit_2(self):
        empty_script = self.put('empty.txt', '\n  \n')
        no_words = thai_raw()
        for seg in no_words['segments']:
            seg['words'] = []
        bad_word = thai_raw()
        bad_word['segments'][0]['words'][0]['start'] = 'x'
        cases = [self.put('junk.json', '{nope'), self.put('schema.json', thai_raw() | {'schema': 'other'}),
                 self.put('nowords.json', no_words), self.put('badword.json', bad_word), self.d / 'missing.json']
        for raw in cases:
            with self.subTest(raw=raw.name):
                r, out = self.run_cli(raw)
                self.assertEqual(2, r.returncode, r.stderr)
                self.assertFalse(out.exists())
        r, _ = self.run_cli(self.put('raw.json', thai_raw()), script=empty_script)
        self.assertEqual(2, r.returncode, r.stderr)
        r, _ = self.run_cli(self.put('raw.json', thai_raw()), script=self.d / 'nope.txt')
        self.assertEqual(2, r.returncode, r.stderr)

    def test_raw_decoded_for_another_script_is_exit_2(self):
        raw = self.put('raw.json', thai_raw() | {'script_sha256': 'f' * 64})
        r, out = self.run_cli(raw)
        self.assertEqual(2, r.returncode, r.stderr)
        self.assertIn('another script', r.stderr)
        self.assertFalse(out.exists())
        r, out = self.run_cli(self.put('raw2.json', {k: v for k, v in thai_raw().items() if k != 'script_sha256'}))
        self.assertEqual(2, r.returncode, r.stderr)                           # a raw without the binding is refused too
        self.script.write_text('\n'.join(THAI_LINES) + '\n\n', encoding='utf-8')   # the script changed after the decode
        r, out = self.run_cli(self.put('raw3.json', thai_raw()))
        self.assertEqual(2, r.returncode, r.stderr)

    def test_a_failed_run_never_leaves_the_previous_pages_behind(self):
        raw = self.put('raw.json', thai_raw())
        r, out = self.run_cli(raw)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertTrue(out.exists())
        for bad, code in ((self.put('bad.json', thai_raw() | {'script_sha256': 'f' * 64}), 2),
                          (self.put('tok.json', thai_raw() | {'tokenizer': {'pythainlp': '0.0.1'}}), 4)):
            out.write_text('[stale]', encoding='utf-8')
            r, _ = self.run_cli(bad, out=out)
            self.assertEqual(code, r.returncode, r.stderr)
            self.assertFalse(out.exists(), 'the old pages file survived a failed run')

    def test_refuses_without_isolation_no_bytecode_and_pycache_prefix(self):
        raw = self.put('raw.json', thai_raw())
        out = self.d / 'pages.json'
        base = [str(SCRIPTS / 'asr_align.py'), '--raw', str(raw), '--script', str(self.script), '--out', str(out)]
        for flags in ([], ['-B'], ['-I'], ['-I', '-B'], ['-I', '-B', '-X', 'pycache_prefix=/tmp'], ['-B', '-X', 'pycache_prefix=/var/empty'],
                      ['-I', '-B', '-X', 'pycache_prefix=/var/empty'],          # everything but -S: site processing would run sitecustomize / .pth
                      ['-I', '-S', '-X', 'pycache_prefix=/var/empty'],
                      ['-I', '-S', '-B', '-X', 'pycache_prefix=/tmp'], ['-S', '-B', '-X', 'pycache_prefix=/var/empty']):
            with self.subTest(flags=flags):
                r = subprocess.run([str(PYBIN), *flags, *base], capture_output=True, text=True)
                self.assertEqual(4, r.returncode, r.stderr)
                self.assertIn('without site processing (-S)', r.stderr)
                self.assertIn('asr_run.sh', r.stderr)
                self.assertFalse(out.exists())
        self.assertEqual(0, subprocess.run([*RUN, *base], capture_output=True, text=True).returncode)

    def test_the_caller_environment_does_not_reach_the_run(self):
        """HOME / PYTHON* / pythainlp data dir / NUMBA_* variables are dropped: the run re-executes under HOME = passwd entry
        (DYLD_* is already acted on by the loader before python starts: word_timing.sh starts the chain under `env -i`)"""
        raw = self.put('raw.json', thai_raw())
        out = self.d / 'pages.json'
        env = dict(os.environ, HOME='/nonexistent-home', PYTHONPATH=str(self.d), PYTHAINLP_DATA_DIR='/nonexistent', NUMBA_CACHE_DIR='/x',
                   MLX_ANYTHING='1', PATH='/nonexistent')
        r = subprocess.run([*RUN, str(SCRIPTS / 'asr_align.py'), '--raw', str(raw), '--script', str(self.script), '--out', str(out)],
                           capture_output=True, text=True, env=env)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(aa.pages_text(aa.align(thai_raw(), THAI_LINES)[0]).encode('utf-8'), out.read_bytes())
        # the guard's environment rule itself (what the re-exec compares against)
        home = pwd.getpwuid(os.getuid()).pw_dir
        mini = aa.minimal_env()
        self.assertEqual({'HOME': home, 'LANG': 'en_US.UTF-8', 'TMPDIR': '/var/empty'}, {k: v for k, v in mini.items() if k != 'PATH'})
        self.assertTrue(mini['PATH'].endswith('/usr/bin:/bin'))
        self.assertTrue(aa.env_is_minimal(mini))
        self.assertTrue(aa.env_is_minimal(dict(mini, __CF_USER_TEXT_ENCODING='0x1F5:0x0:0x0')))
        for bad in (dict(mini, HOME='/elsewhere'), dict(mini, DYLD_INSERT_LIBRARIES='x'), {k: v for k, v in mini.items() if k != 'TMPDIR'},
                    dict(mini, LANG='C'), dict(mini, PYTHONPATH='/x'),
                    dict(mini, TMPDIR='/x'),                                   # N5: TMPDIR is compared
                    dict(mini, PATH='/usr/bin:/bin:/evil'), dict(mini, PATH='/evil:' + mini['PATH'])):   # N5: PATH is compared
            self.assertFalse(aa.env_is_minimal(bad), bad)
        self.assertEqual(home, aa.USER_HOME)

    def test_a_second_environment_mismatch_after_the_restart_is_exit_4_not_a_loop(self):
        """N5: at most ONE re-exec (-X asr_reexec=1 marks it); the environment is still not minimal -> exit 4"""
        raw = self.put('raw.json', thai_raw())
        out = self.d / 'pages.json'
        cmd = [*RUN, '-X', 'asr_reexec=1', str(SCRIPTS / 'asr_align.py'), '--raw', str(raw), '--script', str(self.script), '--out', str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ, PATH='/nonexistent'))
        self.assertEqual(4, r.returncode, r.stderr)
        self.assertIn('still not the minimal one', r.stderr)
        self.assertFalse(out.exists())
        r = subprocess.run(cmd, capture_output=True, text=True, env=aa.minimal_env())            # the same marker with a clean environment runs
        self.assertEqual(0, r.returncode, r.stderr)

    def test_the_site_dir_is_the_v4_venv_and_equals_the_ladders(self):
        self.assertEqual(os.path.join(pwd.getpwuid(os.getuid()).pw_dir, '.cache', 'yt-news-v4', 'asr-venv', 'lib', 'python3.12', 'site-packages'),
                         aa.SITE_DIR)

    def test_no_use_of_the_environment_or_home_in_the_aligner(self):
        src = (SCRIPTS / 'asr_align.py').read_text(encoding='utf-8')
        sites = [ast.get_source_segment(src, n) for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Attribute) and n.attr in ('environ', 'getenv', 'expanduser', 'home')]
        self.assertEqual(['os.environ'], sites)                               # only the argument of the re-exec test


if __name__ == '__main__':
    unittest.main()
