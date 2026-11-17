import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import wave

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import timing_check as tc  # noqa: E402

BURST, PERIOD = 1.4, 2.6                           # 1.4 s tone burst + 1.2 s silence
ONSETS = [1.0 + PERIOD * k for k in range(14)]
# 20 irregular token offsets inside a burst (no even spacing, all inside the burst)
OFFS = (0.05, 0.12, 0.31, 0.38, 0.52, 0.61, 0.68, 0.83, 0.91, 0.99, 1.04, 1.1, 1.13, 1.17, 1.2, 1.23, 1.26, 1.28, 1.3, 1.33)


def write_wav(path, onsets, burst=BURST, total=None, rate=16000):
    total = total or onsets[-1] + burst + 1.0
    n = int(total * rate)
    samples = [0] * n
    for o in onsets:
        for i in range(int(o * rate), int((o + burst) * rate)):
            samples[i] = int(0.5 * 32767 * math.sin(2 * math.pi * 440 * i / rate))
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack('<%dh' % n, *samples))


def burst_tokens(onsets=ONSETS, shift=0.0, offs=OFFS):
    """[[ (name, time) ... ] per line]"""
    return [[(f'w{k}_{j}', round(o + d + shift, 2)) for j, d in enumerate(offs)] for k, o in enumerate(onsets, 1)]


def render(lines):
    return '\n'.join(f'L{k}: ' + ' '.join(f'{w}@{t:.2f}' for w, t in row) for k, row in enumerate(lines, 1)) + '\n'


def words_txt(onsets=ONSETS, shift=0.0, offs=OFFS):
    return render(burst_tokens(onsets, shift, offs))


def srt(starts):
    return '\n'.join(f'{i}\n00:00:{s:06.3f}'.replace('.', ',') + f' --> 00:00:{s + 1:06.3f}'.replace('.', ',') + '\nx\n'
                     for i, s in enumerate(starts, 1))


class TimingCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.wav = cls.dir / 'a.wav'
        write_wav(cls.wav, ONSETS)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_check(self, words_text, srt_text=None, name='w.txt'):
        wf = self.dir / name
        wf.write_text(words_text, encoding='utf-8')
        report = self.dir / 'report.json'
        if report.exists():
            report.unlink()
        args = [sys.executable, str(SCRIPTS / 'timing_check.py'), '--audio', str(self.wav), '--words', str(wf),
                '--report', str(report)]
        if srt_text is not None:
            sf = self.dir / 'a.srt'
            sf.write_text(srt_text, encoding='utf-8')
            args += ['--srt', str(sf)]
        proc = subprocess.run(args, capture_output=True, text=True)
        rep = json.loads(report.read_text()) if report.exists() else None
        return proc.returncode, rep, proc

    def codes(self, rep):
        return sorted(e['code'] for e in rep['errors'])

    def warn_codes(self, rep):
        return sorted(w['code'] for w in rep['warnings'])

    def test_matching_timing_passes_and_writes_sync_record(self):
        rc, rep, proc = self.run_check(words_txt())
        self.assertEqual(0, rc, proc.stdout + proc.stderr)
        self.assertTrue(rep['pass'])
        self.assertEqual('accepted', rep['status'])
        self.assertEqual('yt-news-v4-timing-check', rep['schema'])
        self.assertEqual(1, rep['version'])
        self.assertEqual([], rep['errors'])
        self.assertEqual([], rep['warnings'])
        ins = rep['metrics']['inSilence']
        self.assertEqual((0, 0.0, 280), (ins['count'], ins['share'], ins['tokens_total']))
        self.assertGreaterEqual(ins['silences'], 14)
        self.assertEqual(13, rep['metrics']['phrase_starts'])             # informational onset metrics stay
        self.assertEqual(1.0, rep['metrics']['onset_matched_ratio'])
        self.assertIn('maxInSilenceShare', rep['thresholds'])
        self.assertEqual(2, len(rep['inputs']))                            # audio + words
        self.assertTrue(all(len(v) == 64 for v in rep['inputs'].values()))

    def test_words_shifted_by_minus_two_seconds_are_tokens_in_silence(self):
        for shift in (-2.0, -1.0):
            rc, rep, _ = self.run_check(words_txt(shift=shift))
            self.assertEqual(1, rc, shift)
            self.assertEqual(['tokens-in-silence'], self.codes(rep), shift)
            self.assertEqual('rejected', rep['status'])
            self.assertFalse(rep['pass'])
            ins = rep['metrics']['inSilence']
            self.assertGreater(ins['share'], 0.005)
            self.assertLessEqual(len(ins['tokens']), 30)
            self.assertEqual({'t', 'w', 'index'}, set(ins['tokens'][0]))

    def test_onset_mismatch_is_only_a_warning_now(self):
        rc, rep, _ = self.run_check(words_txt(shift=-2.0))
        self.assertIn('onset-mismatch', self.warn_codes(rep))
        self.assertLess(rep['metrics']['onset_matched_ratio'], 0.9)
        self.assertEqual(10, len(rep['metrics']['worst_anchors']))
        # a pure onset miss (tokens never inside a silence interior) does not fail the check
        rc, rep, _ = self.run_check(words_txt(shift=-0.4))
        self.assertEqual(0, rc)
        self.assertIn('onset-mismatch', self.warn_codes(rep))
        self.assertEqual([], rep['errors'])

    def test_small_jitter_within_tolerance_still_passes(self):
        rc, rep, _ = self.run_check(words_txt(shift=-0.2))
        self.assertEqual(0, rc)
        self.assertAlmostEqual(0.15, rep['metrics']['onset_abs_error_median_s'], places=2)   # first word 0.05 s after the onset

    def test_one_token_moved_into_a_silence_is_a_warning_only(self):
        lines = burst_tokens()
        lines[3][-1] = (lines[3][-1][0], round(ONSETS[3] + BURST + 0.6, 2))       # middle of the silence after burst 4
        rc, rep, proc = self.run_check(render(lines))
        self.assertEqual(0, rc, proc.stdout)
        self.assertTrue(rep['pass'])
        self.assertEqual('accepted', rep['status'])
        self.assertEqual(['tokens-in-silence-few'], self.warn_codes(rep))
        ins = rep['metrics']['inSilence']
        self.assertEqual(1, ins['count'])
        self.assertEqual('w4_19', ins['tokens'][0]['w'])
        self.assertEqual(round(ONSETS[3] + BURST + 0.6, 2), ins['tokens'][0]['t'])
        self.assertEqual(ins['tokens'], rep['warnings'][0]['tokens'])

    def test_three_tokens_moved_into_one_silence_fail(self):
        lines = burst_tokens()
        for j, dt in zip((-3, -2, -1), (0.4, 0.6, 0.8)):
            lines[3][j] = (lines[3][j][0], round(ONSETS[3] + BURST + dt, 2))
        rc, rep, _ = self.run_check(render(lines))
        self.assertEqual(1, rc)
        self.assertEqual(['tokens-in-silence'], self.codes(rep))
        self.assertEqual(3, rep['metrics']['inSilence']['count'])

    def test_window_rule_fails_even_when_the_share_is_tiny(self):
        silences = [(100 + 40 * i, 103 + 40 * i) for i in range(12)]
        grid = [round(i * 0.6 + (i * i % 11) * 0.017, 3) for i in range(1000)]
        interiors = [(a + 0.1, b - 0.4) for a, b in silences]
        base = [t for t in grid if not any(lo <= t <= hi for lo, hi in interiors)]
        mk = lambda ts: [{'w': 'x', 's': t, 'e': None, 'line': None} for t in sorted(ts)]
        three_close = base + [101.0, 101.5, 102.0]                             # one silence: 3 in 30 s
        errs, _w, m = tc.analyse(mk(three_close), silences)
        self.assertLessEqual(m['inSilence']['share'], 0.005)
        self.assertEqual(['tokens-in-silence'], [e['code'] for e in errs])
        self.assertIn('window', errs[[e['code'] for e in errs].index('tokens-in-silence')]['message'])
        three_apart = base + [101.0, 141.0, 181.0]                             # three silences, 40 s apart
        errs, _w, m = tc.analyse(mk(three_apart), silences)
        self.assertEqual(3, m['inSilence']['count'])
        self.assertEqual([], [e['code'] for e in errs])
        self.assertEqual('tokens-in-silence-few', m['inSilence']['verdict'])

    def test_silence_interior_bounds(self):
        sil = [(10.0, 12.0)]
        toks = lambda *ts: [{'w': 'x', 's': t, 'e': None, 'line': None} for t in ts]
        self.assertEqual([], tc.tokens_in_silence(toks(10.05, 10.09, 11.65, 11.7, 12.2), sil))   # margins: +0.10 / -0.40
        self.assertEqual([1, 2], [i for i, _ in tc.tokens_in_silence(toks(10.05, 10.11, 11.59, 11.7), sil)])

    def test_timing_copied_from_srt_is_flagged(self):
        starts = [o + 0.05 for o in ONSETS]
        rc, rep, _ = self.run_check(words_txt(), srt_text=srt(starts))
        self.assertEqual(1, rc)
        self.assertEqual(['srt-copied'], self.codes(rep))
        self.assertEqual(1.0, rep['metrics']['srt']['within_tolerance_ratio'])

    def test_drifting_srt_is_not_copied_and_offsets_are_reported(self):
        starts = [max(0.0, o - 4.4 * k / 13) for k, o in enumerate(ONSETS)]
        rc, rep, _ = self.run_check(words_txt(), srt_text=srt(starts))
        self.assertEqual(0, rc)
        off = rep['metrics']['srt']['offset_words_minus_srt_s']
        self.assertLess(off['min'], off['median'] + 1e-9)
        self.assertLessEqual(off['median'], off['max'])
        self.assertGreater(off['max'], 3.0)

    def test_evenly_spaced_fabricated_run_is_flat_run(self):
        lines = burst_tokens()
        o = ONSETS[-1]
        lines[-1] = [(f'f{j}', round(o + 0.05 + 0.22 * j, 2)) for j in range(6)]
        rc, rep, _ = self.run_check(render(lines))
        self.assertEqual(1, rc)
        self.assertEqual(['flat-run'], self.codes(rep))
        run = rep['errors'][0]['runs'][0]
        self.assertEqual(6, run['tokens'])
        self.assertEqual(0.22, run['spacing'])

    def test_four_even_tokens_or_short_span_are_not_flat(self):
        toks = [{'s': 0.0 + 0.3 * i} for i in range(4)]
        self.assertEqual([], tc.find_flat_runs(toks))
        toks = [{'s': 0.1 * i} for i in range(5)]       # 5 tokens but spans only 0.4 s
        self.assertEqual([], tc.find_flat_runs(toks))
        toks = [{'s': 5.0} for _ in range(8)]          # identical starts are not an even spacing
        self.assertEqual([], tc.find_flat_runs(toks))

    def test_coarse_tenth_second_grid_needs_a_longer_run(self):
        five = [{'s': round(10 + 0.3 * i, 1)} for i in range(5)]             # 0.1 s grid: chance-level
        self.assertTrue(tc.is_coarse(five))
        self.assertEqual([], tc.find_flat_runs(five))
        twelve = [{'s': round(324.0 + 0.4 * i, 1)} for i in range(12)]      # the 12-token overwrite case
        runs = tc.find_flat_runs(twelve)
        self.assertEqual([(0, 11, 12)], [(r['first_index'], r['last_index'], r['tokens']) for r in runs])
        fine_even = [{'s': 10.013 + 0.3 * i} for i in range(5)]               # 3-decimal data: 5 tokens suffice
        self.assertFalse(tc.is_coarse(fine_even))
        self.assertEqual(1, len(tc.find_flat_runs(fine_even)))
        fine_real = [{'s': 10.013 + x} for x in (0, 0.31, 0.58, 0.93, 1.21)]  # real speech: gaps differ by > 0.01 s
        self.assertEqual([], tc.find_flat_runs(fine_real))

    def test_start_going_backwards_is_non_monotonic(self):
        lines = burst_tokens()
        lines[5][10] = (lines[5][10][0], round(ONSETS[5] + 0.5, 2))       # token 11 jumps back before token 10
        rc, rep, _ = self.run_check(render(lines))
        self.assertEqual(1, rc)
        self.assertIn('non-monotonic', self.codes(rep))

    def test_too_few_tokens_or_silences_cannot_verify(self):
        rc, rep, _ = self.run_check(words_txt(ONSETS[:6]))                 # 120 tokens < 200
        self.assertEqual(1, rc)
        self.assertEqual(['too-few-anchors'], self.codes(rep))
        self.assertIn('200 tokens', rep['errors'][0]['message'])
        toks = [{'w': 'x', 's': i * 0.6 + (i * i % 11) * 0.017, 'e': None, 'line': None} for i in range(300)]
        errs, _w, m = tc.analyse(toks, [(1000 + 5 * i, 1003 + 5 * i) for i in range(9)])     # 9 silences < 10
        self.assertEqual(['too-few-anchors'], [e['code'] for e in errs])
        self.assertIn('10 detected silences', errs[0]['message'])

    def test_ends_with_real_gaps_define_phrase_starts(self):
        toks = [{'w': 'a', 's': 0.0, 'e': 0.3, 'line': None}, {'w': 'b', 's': 0.4, 'e': 0.7, 'line': None},
                {'w': 'c', 's': 1.4, 'e': 1.7, 'line': None}]
        idx, mode = tc.phrase_starts(toks)
        self.assertEqual(('ends', [2]), (mode, idx))
        contiguous = [{'w': 'a', 's': 0.0, 'e': 0.4, 'line': None}, {'w': 'b', 's': 0.4, 'e': 1.4, 'line': None},
                      {'w': 'c', 's': 1.4, 'e': 1.7, 'line': None}]
        idx, mode = tc.phrase_starts(contiguous)
        self.assertEqual(('starts', []), (mode, idx))   # ends == next start carry no pause info; start gaps 0.4, 1.0 < 1.2

    def test_caption_pages_final_and_pages_json_loaders(self):
        final = [{'chunks': [{'sourceTokens': [{'w': 'x', 's': 1, 'e': 1.5}], 'tokens': [{'w': 'x', 's': 1, 'e': 2}]}]}]
        self.assertEqual([('x', 1.0, 1.5)], [(t['w'], t['s'], t['e']) for t in tc.parse_words_json(final)])
        pages = [{'start': 0, 'end': 1, 'words': [{'w': 'a', 's': 0, 'e': 0.5}, {'w': 'b', 's': 0.5, 'e': 1}]}]
        self.assertEqual(['a', 'b'], [t['w'] for t in tc.parse_words_json(pages)])
        with self.assertRaises(tc.BadInput):
            tc.parse_words_json([{'w': 'a'}])

    def test_words_with_spaces_and_srt_parse(self):
        toks = tc.parse_words_txt('L1: Marlin 3 Quartz@11.0 ซึ่ง@12.5\nL2: ok@13.0\n')
        self.assertEqual([('Marlin 3 Quartz', 11.0, 1), ('ซึ่ง', 12.5, 1), ('ok', 13.0, 2)],
                         [(t['w'], t['s'], t['line']) for t in toks])
        self.assertEqual([0.0, 9.697], tc.parse_srt_starts('1\n00:00:00,000 --> 00:00:09,697\nx\n\n2\n00:00:09,697 --> 00:00:19,648\ny\n')[:1] + [9.697])

    def test_bad_input_exit_2(self):
        proc = subprocess.run([sys.executable, str(SCRIPTS / 'timing_check.py'), '--audio', str(self.dir / 'nope.wav'),
                               '--words', str(self.dir / 'nope.txt'), '--report', str(self.dir / 'r.json')],
                              capture_output=True, text=True)
        self.assertEqual(2, proc.returncode)
        empty = self.dir / 'empty.txt'
        empty.write_text('nothing here\n')
        proc = subprocess.run([sys.executable, str(SCRIPTS / 'timing_check.py'), '--audio', str(self.wav),
                               '--words', str(empty), '--report', str(self.dir / 'r.json')], capture_output=True, text=True)
        self.assertEqual(2, proc.returncode)

    def test_ffmpeg_missing_exit_4(self):
        wf = self.dir / 'w4.txt'
        wf.write_text(words_txt(ONSETS), encoding='utf-8')
        proc = subprocess.run([sys.executable, str(SCRIPTS / 'timing_check.py'), '--audio', str(self.wav), '--words',
                               str(wf), '--report', str(self.dir / 'r.json')],
                              capture_output=True, text=True, env={'PATH': '/nonexistent'})
        self.assertEqual(4, proc.returncode)


class PagesTimingTests(unittest.TestCase):
    def test_v5_documentation_requires_pages_and_keeps_threshold_literal(self):
        import ast
        skill = SCRIPTS.parent
        self.assertIn('name: Youtube-YT-News-Style01-V5', (skill / 'SKILL.md').read_text())
        command = next(l for l in (skill / 'SKILL.md').read_text().splitlines() if 'timing_check.py"' in l)
        self.assertIn('--pages $P/artifacts/word_timing/caption_pages.json', command)
        self.assertIn('references/v5-contract.md', (skill / 'SKILL.md').read_text())
        contract = (skill / 'references/v5-contract.md').read_text()
        self.assertIn('timing-source-mismatch', contract)
        self.assertIn('flat_min_tokens_used', contract)
        self.assertTrue(contract.startswith('# V5 authoring contract\n'))
        for name in ('yt-source.md', 'format-spec.md', 'broll-freshness.md'):
            reference = (skill / 'references' / name).read_text()
            self.assertNotIn('v4-contract.md', reference, name)
            self.assertIn('v5-contract.md', reference, name)
        assignment = next(n for n in ast.parse((SCRIPTS / 'timing_check.py').read_text()).body
                          if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', None) == 'THRESHOLDS')
        self.assertEqual(tc.THRESHOLDS, ast.literal_eval(assignment.value))

    def pair(self, starts):
        pages = [{'words': [{'w': f'w{i}', 's': s, 'e': s + 0.1} for i, s in enumerate(starts)]}]
        words = tc.parse_words_txt('L1: ' + ' '.join(f'{t["w"]}@{t["s"]:.1f}' for t in pages[0]['words']))
        return words, tc.parse_words_json(pages)

    def analyse_pair(self, starts):
        words, pages = self.pair(starts)
        return tc.analyse(words, [], pages=pages)

    def test_real_eight_offsets_use_precision_only_for_flat_runs(self):
        words, pages = self.pair([10 + d for d in (0, .22, .42, .60, .82, 1.02, 1.16, 1.36)])
        old_errors, old_warnings, old_metrics = tc.analyse(words, [], [8.0], {1: 10.0})
        errors, warnings, metrics = tc.analyse(words, [], [8.0], {1: 10.0}, pages=pages)
        self.assertIn('flat-run', [e['code'] for e in old_errors])
        self.assertNotIn('flat-run', [e['code'] for e in errors])
        self.assertEqual('pages', metrics['flat_run_basis'])
        self.assertEqual(5, metrics['flat_min_tokens_used'])
        for key in set(old_metrics) - {'flat_runs', 'flat_run_basis', 'flat_min_tokens_used'}:
            self.assertEqual(old_metrics[key], metrics[key], key)
        self.assertEqual(old_warnings, warnings)
        self.assertEqual('words', old_metrics['flat_run_basis'])
        self.assertEqual(8, old_metrics['flat_min_tokens_used'])

    def test_fabricated_pages_still_fail_with_actual_threshold(self):
        for starts, threshold in [([10.013 + .22 * i for i in range(6)], 5),
                                  ([10 + .4 * i for i in range(12)], 8),
                                  ([10 + .2 * i for i in range(8)], 8)]:
            with self.subTest(starts=starts):
                errors, _, metrics = self.analyse_pair(starts)
                flat = next(e for e in errors if e['code'] == 'flat-run')
                self.assertIn(f'>= {threshold} tokens', flat['message'])
                self.assertEqual(threshold, metrics['flat_min_tokens_used'])
        errors, _, _ = self.analyse_pair([10 + .2 * i for i in range(7)])
        self.assertNotIn('flat-run', [e['code'] for e in errors])

    def test_binding_rejects_count_text_order_and_rounded_start(self):
        for change, field, index in [('count', 'count', 7), ('text', 'w', 2), ('order', 'w', 2), ('start', 's', 2)]:
            words, pages = self.pair([10 + d for d in (0, .22, .42, .60, .82, 1.02, 1.16, 1.36)])
            if change == 'count':
                pages.pop()
            elif change == 'text':
                pages[2]['w'] = 'different'
            elif change == 'order':
                pages[2], pages[3] = pages[3], pages[2]
            else:
                pages[2]['s'] += .1
            errors, _, _ = tc.analyse(words, [], pages=pages)
            mismatch = next(e for e in errors if e['code'] == 'timing-source-mismatch')
            self.assertIn(field, mismatch['fields'])
            self.assertEqual(index, mismatch['index'])

    def test_real_straddle_and_zero_length_bind_without_line_assumptions(self):
        fixtures = SCRIPTS / 'tests/fixtures/a67/timing'
        for name in ('real_straddle', 'real_zero_length'):
            words = tc.load_words(fixtures / (name + '_wbl.txt'))
            pages = tc.load_pages(fixtures / (name + '_pages.json'))
            errors, _, _ = tc.analyse(words, [], pages=pages)
            self.assertNotIn('timing-source-mismatch', [e['code'] for e in errors])

    def test_requested_pages_bad_input_cannot_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio, words, pages = root / 'a.wav', root / 'words.txt', root / 'pages.json'
            audio.write_bytes(b'not decoded: pages must fail before ffmpeg')
            words.write_text('L1: x@1.0\n')
            invalid = [None, '{', '[]', '{}', '[{"words": []}]', '[{"w":"x","s":1}]',
                       '[{"words": [{"w":"x","s":"1","e":2}]}]',
                       '[{"words": [{"w":"x","s":NaN,"e":2}]}]',
                       '[{"words": [{"w":4,"s":1,"e":2}]}]',
                       '[{"words": [{"w":"x","s":' + '9' * 400 + ',"e":2}]}]',
                       '[' * 20000 + '0' + ']' * 20000,
                       '[{"words": [{"w":"x","s":-1,"e":2}]}]',
                       '[{"words": [{"w":"x","s":2,"e":1}]}]',
                       '[{"words": [{"w":"x","s":Infinity,"e":2}]}]',
                       '[{"words": [{"w":"x","s":1,"e":Infinity}]}]',
                       '[{"words": [{"w":"x","s":true,"e":2}]}]',
                       '[{"words": [{"w":"x","s":1,"e":false}]}]',
                       '[{"words": [{"w":"","s":1,"e":2}]}]']
            for text in invalid:
                with self.subTest(text=text):
                    if text is not None:
                        pages.write_text(text)
                    elif pages.exists():
                        pages.unlink()
                    report = root / 'r.json'
                    proc = subprocess.run([sys.executable, str(SCRIPTS / 'timing_check.py'), '--audio', str(audio),
                                           '--words', str(words), '--pages', str(pages), '--report', str(report)],
                                          capture_output=True, text=True)
                    self.assertEqual(2, proc.returncode, proc.stdout + proc.stderr)
                    self.assertIn('pages', proc.stderr)
                    self.assertNotIn('ffmpeg', proc.stderr)
                    self.assertFalse(report.exists())
            pages.unlink()
            pages.mkdir()
            proc = subprocess.run([sys.executable, str(SCRIPTS / 'timing_check.py'), '--audio', str(audio),
                                   '--words', str(words), '--pages', str(pages), '--report', str(report)],
                                  capture_output=True, text=True)
            self.assertEqual(2, proc.returncode, proc.stdout + proc.stderr)
            self.assertIn('pages', proc.stderr)
            self.assertNotIn('Traceback', proc.stderr)
            self.assertFalse(report.exists())

    def test_pages_cli_hashes_input_and_legacy_metrics_stay_equal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wav, wf, pf = root / 'a.wav', root / 'w.txt', root / 'pages.json'
            write_wav(wav, ONSETS)
            pages = [{'words': [{'w': w, 's': t, 'e': t} for w, t in row]} for row in burst_tokens()]
            wf.write_text('\n'.join(f'L{i}: ' + ' '.join(f'{t["w"]}@{t["s"]:.1f}' for t in p['words'])
                                    for i, p in enumerate(pages, 1)))
            pf.write_text(json.dumps(pages))
            args = [sys.executable, str(SCRIPTS / 'timing_check.py'), '--audio', str(wav), '--words', str(wf)]
            rp = root / 'r.json'
            proc = subprocess.run(args + ['--pages', str(pf), '--report', str(rp)], capture_output=True, text=True)
            self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
            report = json.loads(rp.read_text())
            self.assertEqual(tc._sha256(pf), report['inputs'][str(pf)])
            self.assertEqual('pages', report['metrics']['flat_run_basis'])


if __name__ == '__main__':
    unittest.main()
