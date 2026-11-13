"""timing_defects.py: the shared word-timing defect detectors.

Every excerpt here is SYNTHETIC (invented tokens), built with the measured numbers of the real references: the known
defects of the old chain (dry-run / wp6 pages and the raw loop) must be flagged at their times, and excerpts carrying
the extreme values of the two clean references must pass.  Each rule also has an at-the-limit / just-over pair."""
import array
import ast
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import wave

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import timing_defects as td  # noqa: E402

THAI = 'กขคฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรลวศษสหฬอฮ'


def tok(n, shift=0):
    """an invented token of n code points"""
    return ''.join(THAI[(shift + i) % len(THAI)] for i in range(n))


def pages_of(words, per_page=4):
    """[(w, s, e)] -> caption_pages.json structure (rounded like asr_align)"""
    out = []
    for i in range(0, len(words), per_page):
        ws = [{'w': w, 's': round(s, 3), 'e': round(e, 3)} for w, s, e in words[i:i + per_page]]
        out.append({'start': ws[0]['s'], 'end': ws[-1]['e'], 'words': ws})
    return out


def normal_run(t0, n, dur=0.3, gap=0.05, size=3):
    """n ordinary words from t0 -> ([(w, s, e)], end time)"""
    out, t = [], t0
    for i in range(n):
        out.append((tok(size, i), t, t + dur))
        t += dur + gap
    return out, t


def squeeze_run(t0, letters, nwords, span=0.18, zero_at=()):
    """nwords words with `letters` letters in total packed into `span` seconds from t0; words at the indexes in
    zero_at have zero length"""
    sizes = [letters // nwords + (1 if i < letters % nwords else 0) for i in range(nwords)]
    out, t = [], t0
    step = span / nwords
    for i, n in enumerate(sizes):
        d = 0.0 if i in zero_at else step
        out.append((tok(n, i), round(t, 3), round(t + d, 3)))
        t += d
    return out, t


def codes_at(defects):
    return sorted((d['code'], d['start']) for d in defects)


# ----------------------------------------------------------------- the known defects, as synthetic excerpts
def dryrun_excerpt():
    """dry-run pages @300: 297 letters / 66 words inside 0.18 s (5 single zero-length words among them) @300.543, a 6-char
    word of 8.845 s @300.725, a 2-char word of 2.50 s @309.57, a 5-char word of 6.238 s @312.066, 22 letters / 4 words
    in 0.2 s @320.826."""
    w, t = normal_run(298.0, 6)
    sq, _ = squeeze_run(300.543, 297, 66, span=0.18, zero_at=(3, 17, 30, 44, 60))
    w += sq
    w.append((tok(6, 2), 300.725, 309.57))
    w.append((tok(2, 9), 309.57, 312.066))
    w.append((tok(5, 4), 312.066, 318.304))
    more, t = normal_run(318.4, 6)
    w += more
    sq2, t = squeeze_run(320.826, 22, 4, span=0.2)
    w += sq2
    tail, _ = normal_run(t + 0.1, 4)
    return pages_of(w + tail)


def wp6_test_pages_excerpt():
    """wp6 test pages: a run of 15 zero-length words (70 letters) at 292.9"""
    w, t = normal_run(291.0, 5)
    sizes = [5, 3, 4, 3, 7, 6, 2, 6, 3, 3, 2, 8, 6, 5, 7]                # 70 letters
    w += [(tok(n, i), 292.9, 292.9) for i, n in enumerate(sizes)]
    tail, _ = normal_run(292.95, 5)
    return pages_of(w + tail)


def wp6_chunked_excerpt():
    """wp6 chunked pages: a 13-char word of 7.702 s @279.76 (0.59 s/char), 88 letters / 18 words @287.462,
    4-char 7.942 s @572.47, 5-char 9.926 s @580.412, 4-char 7.942 s @590.338"""
    w, _ = normal_run(278.0, 4)
    w.append((tok(13), 279.76, 287.462))
    sq, t = squeeze_run(287.462, 88, 18, span=0.2)
    w += sq
    more, _ = normal_run(t + 0.1, 4)
    w += more
    w.append((tok(4, 1), 572.47, 580.412))
    w.append((tok(5, 3), 580.412, 590.338))
    w.append((tok(4, 5), 590.338, 598.28))
    tail, _ = normal_run(598.3, 4)
    return pages_of(w + tail)


def spike_r0_excerpt():
    """the pinned-param R0 result at 576.9 s: a 6-char word of 7.92 s @576.72"""
    w, _ = normal_run(574.0, 6)
    w.append((tok(6), 576.72, 584.64))
    tail, _ = normal_run(584.88, 6)
    return pages_of(w + tail)


def loop_raw():
    """raw segment 294.48-319.82 with compression_ratio 36.78 (the default-param repetition loop)"""
    return {'audio': {'duration': 647.3}, 'segments': [
        {'start': 290.0, 'end': 294.48, 'text': 'ok', 'compression_ratio': 1.4, 'words': []},
        {'start': 294.48, 'end': 319.82, 'text': tok(3) * 40, 'compression_ratio': 36.78, 'words': []},
        {'start': 319.82, 'end': 325.0, 'text': 'ok', 'compression_ratio': 2.47, 'words': []}]}


KNOWN = [
    ('dry-run', dryrun_excerpt, None, [('squeeze', 300.543), ('word-slow', 300.725), ('word-too-long', 300.725),
                                       ('word-slow', 309.57), ('word-slow', 312.066), ('word-too-long', 312.066),
                                       ('squeeze', 320.826)]),
    ('wp6-test', wp6_test_pages_excerpt, None, [('squeeze', 292.9), ('zero-run', 292.9)]),
    ('wp6-chunked', wp6_chunked_excerpt, None, [('word-too-long', 279.76), ('squeeze', 287.462),
                                                ('word-slow', 572.47), ('word-too-long', 572.47),
                                                ('word-slow', 580.412), ('word-too-long', 580.412),
                                                ('word-slow', 590.338), ('word-too-long', 590.338)]),
    ('spike-R0', spike_r0_excerpt, None, [('word-slow', 576.72), ('word-too-long', 576.72)]),
    ('raw-loop', lambda: pages_of(normal_run(290.0, 8)[0]), loop_raw, [('raw-loop', 294.48)]),
]


# ----------------------------------------------------------------- the clean references' extremes
def clean_a_like():
    """clean A extremes: a 4-char word of 2.453 s (0.613 s/char), a 7-char word of 1.82 s, a run of 2 zero-length words
    + a single one, 8 letters inside a 0.25 s window"""
    w, t = normal_run(100.0, 6)
    w.append((tok(4), t, t + 2.453)); t += 2.5
    w.append((tok(7), t, t + 1.82)); t += 1.9
    w += [(tok(3, 1), t, t), (tok(2, 2), t, t)]; t += 0.05
    m, t = normal_run(t, 3)
    w += m
    w.append((tok(2, 7), t, t)); t += 0.05
    w += [(tok(4, 3), t, t + 0.1), (tok(4, 5), t + 0.1, t + 0.25)]; t += 0.4     # 8 letters in 0.25 s
    tail, _ = normal_run(t, 6)
    return pages_of(w + tail)


def clean_b_like():
    """clean B extremes: a 13-char word of 2.613 s (0.2 s/char), a 4-char word of 1.86 s (0.465 s/char), 7 letters in a
    window, no zero-length word"""
    w, t = normal_run(40.0, 5)
    w.append((tok(13), t, t + 2.613)); t += 2.7
    w.append((tok(4, 2), t, t + 1.86)); t += 1.9
    w += [(tok(3, 3), t, t + 0.12), (tok(4, 6), t + 0.12, t + 0.24)]; t += 0.3
    tail, _ = normal_run(t, 6)
    return pages_of(w + tail)


class KnownDefectTests(unittest.TestCase):
    def test_every_known_defect_location_is_flagged(self):
        for name, pages_fn, raw_fn, want in KNOWN:
            with self.subTest(name):
                got = codes_at(td.find_defects(pages_fn(), raw_fn() if raw_fn else None, [] if raw_fn else None))
                self.assertEqual(sorted(want), got)

    def test_measured_values_are_reported(self):
        d = {(x['code'], x['start']): x for x in td.find_defects(dryrun_excerpt())}
        self.assertAlmostEqual(8.845, d[('word-too-long', 300.725)]['value'], places=3)
        self.assertEqual(4.0, d[('word-too-long', 300.725)]['limit'])
        self.assertAlmostEqual(1.25, d[('word-slow', 309.57)]['value'], places=2)
        self.assertEqual(297, d[('squeeze', 300.543)]['value'])
        z = [x for x in td.find_defects(wp6_test_pages_excerpt()) if x['code'] == 'zero-run'][0]
        self.assertEqual((15, 3), (z['value'], z['limit']))
        loop = td.find_defects(pages_of(normal_run(290.0, 8)[0]), loop_raw(), [])[0]
        self.assertEqual(('raw-loop', 36.78, 3.0, 319.82), (loop['code'], loop['value'], loop['limit'], loop['end']))

    def test_clean_reference_extremes_pass(self):
        for name, fn in (('clean-A', clean_a_like), ('clean-B', clean_b_like)):
            with self.subTest(name):
                self.assertEqual([], td.find_defects(fn()))
        raw = {'audio': {'duration': 200.0}, 'segments': [{'start': 0, 'end': 9, 'text': 'x', 'compression_ratio': 2.47, 'words': []}]}
        self.assertEqual([], td.find_defects(clean_a_like(), raw, []))


class RuleLimitTests(unittest.TestCase):
    def one(self, word, s, e):
        w, t = normal_run(10.0, 3)
        tail, _ = normal_run(max(e, t) + 0.1, 3)
        return td.find_defects(pages_of(w + [(word, s, e)] + tail))

    def test_word_too_long_is_strictly_over_four_seconds(self):
        self.assertEqual([], self.one(tok(12), 11.1, 15.1))            # 4.0 s, 0.33 s/char
        self.assertEqual(['word-too-long'], [d['code'] for d in self.one(tok(12), 11.1, 15.11)])

    def test_word_slow_needs_both_duration_and_seconds_per_char(self):
        self.assertEqual([], self.one(tok(2), 11.1, 12.7))             # 1.6 s but exactly 0.8 s/char
        self.assertEqual(['word-slow'], [d['code'] for d in self.one(tok(2), 11.1, 12.72)])
        self.assertEqual([], self.one(tok(1), 11.1, 12.6))             # 1.5 s exactly, 1.5 s/char: not > 1.5 s
        self.assertEqual(['word-slow'], [d['code'] for d in self.one(tok(1), 11.1, 12.61)])

    def test_zero_run_starts_at_three(self):
        def run(n):
            w, t = normal_run(5.0, 3)
            w += [(tok(2, i), t, t) for i in range(n)]
            tail, _ = normal_run(t + 0.3, 3)
            return [d['code'] for d in td.find_defects(pages_of(w + tail))]
        self.assertEqual([], run(2))
        self.assertEqual(['zero-run'], run(3))
        w, t = normal_run(5.0, 3)                                         # 1 ms is still "zero length"
        w += [(tok(2, i), t + i * 0.001, t + (i + 1) * 0.001) for i in range(3)]
        tail, _ = normal_run(t + 0.3, 3)
        self.assertEqual(['zero-run'], [d['code'] for d in td.find_defects(pages_of(w + tail))])

    def test_squeeze_starts_at_twenty_letters_in_a_quarter_second(self):
        def run(letters, span):
            w, t = normal_run(5.0, 3)
            sq, t = squeeze_run(t, letters, 4, span=span)
            tail, _ = normal_run(t + 0.3, 3)
            return [d['code'] for d in td.find_defects(pages_of(w + sq + tail))]
        self.assertEqual([], run(19, 0.24))
        self.assertEqual(['squeeze'], run(20, 0.24))
        self.assertEqual([], run(20, 0.26))                              # the last word ends outside the window

    def test_squeeze_counts_letters_not_spaces(self):
        w, t = normal_run(5.0, 3)
        sq = [(tok(4) + '   ' + tok(1), t, t + 0.1), (tok(7) + '    ' + tok(7), t + 0.1, t + 0.2)]  # 19 letters
        tail, _ = normal_run(t + 0.5, 3)
        self.assertEqual([], td.find_defects(pages_of(w + sq + tail)))

    def test_raw_loop_is_strictly_over_three(self):
        pages = pages_of(normal_run(1.0, 6)[0])
        seg = lambda cr: {'audio': {'duration': 60.0}, 'segments': [{'start': 1.0, 'end': 4.0, 'text': 'x', 'compression_ratio': cr, 'words': []}]}
        self.assertEqual([], td.find_defects(pages, seg(3.0), []))
        self.assertEqual(['raw-loop'], [d['code'] for d in td.find_defects(pages, seg(3.01), [])])
        self.assertEqual([], td.find_defects(pages))                     # without raw the rule cannot run

    def test_order_range_and_finiteness(self):
        w, t = normal_run(1.0, 4)
        bad = w + [(tok(3), t - 0.5, t)]                                  # starts before the previous word ended
        self.assertEqual(['non-monotonic'], [d['code'] for d in td.find_defects(pages_of(bad))])
        bad = w + [(tok(3), t + 0.4, t + 0.2)]                            # ends before it starts
        self.assertEqual(['non-monotonic'], [d['code'] for d in td.find_defects(pages_of(bad))])
        bad = [(tok(3), -0.2, 0.1)] + normal_run(0.2, 3)[0]
        self.assertEqual(['out-of-range'], [d['code'] for d in td.find_defects(pages_of(bad))])
        raw = {'audio': {'duration': 2.0}, 'segments': []}
        late = normal_run(1.0, 4)[0]                                      # ends at 2.35 s; audio 2.0 s
        self.assertEqual([], td.find_defects(pages_of(late), raw, []))         # inside the 0.5 s tolerance
        later = normal_run(1.3, 4)[0]                                     # ends at 2.65 s
        self.assertEqual(['out-of-range'], [d['code'] for d in td.find_defects(pages_of(later), raw, [])])
        nan = pages_of(normal_run(1.0, 3)[0])
        nan[0]['words'][1]['e'] = float('nan')
        self.assertEqual(['non-finite'], [d['code'] for d in td.find_defects(nan)])

    def test_malformed_input_raises(self):
        for bad in ([], [{'words': []}], {'nopages': 1}, [{'words': [{'w': 'x', 's': '1', 'e': 2}]}], 'x'):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    td.find_defects(bad)

    def test_dict_with_pages_is_accepted(self):
        self.assertEqual(codes_at(td.find_defects(spike_r0_excerpt())),
                         codes_at(td.find_defects({'pages': spike_r0_excerpt()})))


def raw_with_starts(starts, duration, dur=0.4, long_word=None):
    """a raw doc whose words start at `starts` (each lasting `dur`); long_word = (index, seconds) stretches one word"""
    words = []
    for i, t in enumerate(starts):
        d = long_word[1] if long_word and long_word[0] == i else dur
        words.append({'word': ' ' + tok(3, i), 'start': t, 'end': round(t + d, 2)})
    return {'audio': {'duration': duration}, 'segments': [{'start': starts[0], 'end': starts[-1] + dur, 'text': 'x', 'compression_ratio': 1.2,
                                                           'words': words}]}


def make_tone_wav(path, spans, total, sr=16000):
    """440 Hz tone inside `spans`, digital silence elsewhere (ffmpeg silencedetect then sees exactly the gaps)"""
    buf = array.array('h', [0]) * int(total * sr)
    for a, b in spans:
        for i in range(int(a * sr), int(b * sr)):
            buf[i] = int(0.4 * 32767 * math.sin(2 * math.pi * 440 * i / sr))
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(buf.tobytes())


class RawRuleTests(unittest.TestCase):
    """raw-word-too-long and raw-gap: whisper dropouts that the page rules cannot see (the script words are interpolated over them)"""
    PAGES = pages_of(normal_run(1.0, 8)[0])

    def codes(self, raw, silences):
        return [(d['code'], d['start'], d['end'], d['value']) for d in td.find_defects(self.PAGES, raw, silences)]

    def test_raw_word_too_long_is_strictly_over_four_seconds(self):
        ok = raw_with_starts([1.0, 2.0, 3.0], 5.0, long_word=(1, 4.0))
        self.assertEqual([], self.codes(ok, []))
        bad = raw_with_starts([1.0, 2.0, 3.0], 5.0, long_word=(1, 4.01))
        (c, s, e, v), = [x for x in self.codes(bad, []) if x[0] == 'raw-word-too-long']
        self.assertEqual((2.0, 6.01, 4.01), (s, e, v))
        d = [x for x in td.find_defects(self.PAGES, bad, []) if x['code'] == 'raw-word-too-long'][0]
        self.assertEqual((tok(3, 1), 4.0), (d['token'], d['limit']))
        # the known defect: one raw token spanning 9.3 s
        known = raw_with_starts([110.0, 119.82, 129.2], 131.0, long_word=(1, 9.3))
        self.assertIn('raw-word-too-long', [x[0] for x in self.codes(known, [])])
        self.assertEqual([], [x for x in td.find_defects(self.PAGES) if x['code'].startswith('raw-')])   # no raw: rule cannot run

    def test_raw_without_silences_is_an_error_not_a_skipped_rule(self):
        raw = raw_with_starts([1.0, 12.0], 13.0, long_word=(0, 5.0))
        with self.assertRaises(ValueError) as cm:
            td.find_defects(self.PAGES, raw)                                          # N4: silences=None cannot silently skip raw-gap
        self.assertIn('silences', str(cm.exception))
        self.assertEqual({'raw-word-too-long', 'raw-gap'}, {x['code'] for x in td.find_defects(self.PAGES, raw, [])})   # [] = none, explicit

    def test_raw_gap_is_strictly_over_three_seconds_of_speech(self):
        at_limit = raw_with_starts([1.0, 2.0, 5.0, 6.0], 8.0)                         # 3.0 s between starts 2.0 and 5.0
        self.assertEqual([], self.codes(at_limit, []))
        over = raw_with_starts([1.0, 2.0, 5.02, 6.0], 8.0)
        self.assertEqual([('raw-gap', 2.0, 5.02, 3.02)], self.codes(over, []))

    def test_a_dropout_is_flagged_with_its_span_and_measured_speech(self):
        raw = raw_with_starts([36.0, 37.0, 38.0, 46.2, 47.0], 48.0)                    # nothing spoken-and-recognised for 8.2 s
        (c, s, e, v), = [x for x in self.codes(raw, [(0.0, 35.5)]) if x[0] == 'raw-gap']       # the first 35.5 s of the audio are silent
        self.assertEqual((38.0, 46.2, 8.2), (s, e, v))

    def test_a_long_legitimate_pause_is_a_silence_and_does_not_fire(self):
        raw = raw_with_starts([1.0, 2.0, 3.0, 16.0, 17.0], 18.0)                        # 13 s between starts 3.0 and 16.0
        self.assertEqual([('raw-gap', 3.0, 16.0, 13.0)], self.codes(raw, []))          # no silence known: it is speech
        self.assertEqual([], self.codes(raw, [(4.0, 15.5)]))                            # 11.5 s of silence inside: 1.5 s of speech left
        self.assertEqual([], self.codes(raw, [(0.5, 3.4), (3.6, 15.9)]))
        self.assertEqual(['raw-gap'], [x[0] for x in self.codes(raw, [(4.0, 8.0)])])    # only 4 s silent: 9 s of speech remain
        # a silence only partly inside the gap counts only for its overlap
        self.assertEqual([('raw-gap', 3.0, 16.0, 6.5)], self.codes(raw, [(2.0, 9.5)]))               # only 3.0-9.5 lies inside the gap

    def test_gap_at_the_start_and_at_the_end_of_the_audio(self):
        head = raw_with_starts([3.5, 4.5, 5.5], 8.0)                                    # nothing recognised before 3.5 s
        self.assertEqual([('raw-gap', 0.0, 3.5, 3.5)], self.codes(head, []))
        self.assertEqual([], self.codes(head, [(0.0, 3.0)]))                             # a silent intro is fine
        self.assertEqual([], self.codes(raw_with_starts([3.0, 4.0, 5.0], 8.0), []))      # 3.0 s: at the limit
        tail = raw_with_starts([1.0, 2.0, 3.0], 6.2)                                     # 3.2 s of audio after the last start
        self.assertEqual([('raw-gap', 3.0, 6.2, 3.2)], self.codes(tail, []))
        self.assertEqual([], self.codes(tail, [(4.0, 6.2)]))
        self.assertEqual([], self.codes(raw_with_starts([1.0, 2.0, 3.0], 5.9), []))

    def test_honest_raws_with_the_measured_extremes_pass(self):
        starts = [0.4, 2.04, 3.0, 4.14, 5.0]                                            # max speech gap 1.64 s, max word 1.12 s
        self.assertEqual([], self.codes(raw_with_starts(starts, 6.0, dur=1.12), []))

    def test_limits_are_in_the_rules_dict(self):
        r = td.rules()
        self.assertEqual((4.0, 3.0, -35, 0.35), (r['raw_word_max_s'], r['raw_gap_max_speech_s'], r['silence_noise_db'], r['silence_min_s']))


class EndOfAudioSilenceTests(unittest.TestCase):
    """N3: ffmpeg prints no silence_end when the audio ends inside a silence; detect_silences must close it at the duration, or the
    raw-gap rule reads the silent tail as 'speech without words' and a correct job fails with exit 5 for ever."""

    def fake_ffmpeg(self, d, stderr):
        """an ffmpeg that prints `stderr` (some ffmpeg versions print no silence_end for a silence that runs to the end of the audio;
        ffmpeg 8.1 does print it, so the real binary alone cannot show the fix)"""
        fake = Path(d) / 'ffmpeg'
        fake.write_text("#!/bin/sh\ncat >&2 <<'EOF'\n%s\nEOF\nexit 0\n" % stderr)
        fake.chmod(0o755)
        return str(fake)

    def test_a_stderr_with_no_silence_end_is_closed_at_the_duration(self):
        env = {'PATH': '/usr/bin:/bin'}
        head = '  Duration: 00:00:07.50, start: 0.000000, bitrate: 256 kb/s\n'
        with tempfile.TemporaryDirectory() as d:
            ff = self.fake_ffmpeg(d, head + '[Parsed_silencedetect_0 @ 0x1] silence_start: 3')
            self.assertEqual([(3.0, 7.5)], td.detect_silences('x.wav', ffmpeg=ff, env=env))
            ff = self.fake_ffmpeg(d, head + '[Parsed_silencedetect_0 @ 0x1] silence_start: 1\n[Parsed_silencedetect_0 @ 0x1] silence_end: 2 | '
                                  'silence_duration: 1\n[Parsed_silencedetect_0 @ 0x1] silence_start: 5.25')
            self.assertEqual([(1.0, 2.0), (5.25, 7.5)], td.detect_silences('x.wav', ffmpeg=ff, env=env))
            ff = self.fake_ffmpeg(d, '  Duration: 01:02:03.25, bitrate: 1 kb/s\n[Parsed_silencedetect_0 @ 0x1] silence_start: 3600')
            self.assertEqual([(3600.0, 3723.25)], td.detect_silences('x.wav', ffmpeg=ff, env=env))        # hours are parsed
            ff = self.fake_ffmpeg(d, head + '[Parsed_silencedetect_0 @ 0x1] silence_start: 9')                 # starts after the end: nothing to close
            self.assertEqual([], td.detect_silences('x.wav', ffmpeg=ff, env=env))
            ff = self.fake_ffmpeg(d, head + '[Parsed_silencedetect_0 @ 0x1] silence_start: -0.002\n[Parsed_silencedetect_0 @ 0x1] silence_end: 2 | x')
            self.assertEqual([(0.0, 2.0)], td.detect_silences('x.wav', ffmpeg=ff, env=env))                # a leading silence is clamped to 0

    def test_the_raw_gap_rule_with_such_an_ffmpeg_does_not_fire_on_the_silent_tail(self):
        with tempfile.TemporaryDirectory() as d:
            ff = self.fake_ffmpeg(d, '  Duration: 00:00:07.00, bitrate: 256 kb/s\n[Parsed_silencedetect_0 @ 0x1] silence_start: 3')
            sil = td.detect_silences('x.wav', ffmpeg=ff, env={'PATH': '/usr/bin:/bin'})
            raw = raw_with_starts([1.0, 2.0, 2.6], 7.0)
            self.assertEqual([], [x for x in td.find_defects(pages_of(normal_run(1.0, 4)[0]), raw, sil) if x['code'] == 'raw-gap'])

    def test_a_silent_tail_is_closed_at_the_audio_duration(self):
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / 'a.wav'
            make_tone_wav(wav, [(0.0, 3.0)], 7.0)                                      # 4 s of digital silence after the last word
            sil = td.detect_silences(wav)
            self.assertEqual(1, len(sil), sil)
            self.assertAlmostEqual(3.0, sil[0][0], delta=0.05)
            self.assertAlmostEqual(7.0, sil[0][1], delta=0.05)

    def test_no_raw_gap_after_the_last_word_when_the_tail_is_silent(self):
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / 'a.wav'
            make_tone_wav(wav, [(0.0, 3.0)], 7.0)
            raw = raw_with_starts([1.0, 2.0, 2.6], 7.0)                                 # last word starts at 2.6, then 4.4 s to the end
            pages = pages_of(normal_run(1.0, 4)[0])
            self.assertEqual([], [x for x in td.find_defects(pages, raw, td.detect_silences(wav)) if x['code'] == 'raw-gap'])
            self.assertEqual(['raw-gap'], [x['code'] for x in td.find_defects(pages, raw, [])])     # the same raw without the tail silence DOES fire

    def test_a_tail_that_is_not_silent_still_fires(self):
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / 'a.wav'
            make_tone_wav(wav, [(0.0, 7.0)], 7.0)                                       # music / effects under no words
            raw = raw_with_starts([1.0, 2.0, 2.6], 7.0)
            self.assertEqual(['raw-gap'], [x['code'] for x in td.find_defects(pages_of(normal_run(1.0, 4)[0]), raw, td.detect_silences(wav))])

    def test_silence_that_ends_normally_is_unchanged_and_a_leading_silence_is_clamped(self):
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / 'a.wav'
            make_tone_wav(wav, [(2.0, 4.0)], 4.0)                                       # silent intro, then tone to the very end
            sil = td.detect_silences(wav)
            self.assertEqual(1, len(sil), sil)
            self.assertEqual(0.0, sil[0][0])
            self.assertAlmostEqual(2.0, sil[0][1], delta=0.05)


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-B', str(SCRIPTS / 'timing_defects.py'), *args], capture_output=True, text=True)

    def test_raw_needs_wav_and_the_silences_come_from_the_wav(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            pages, raw, rep, wav = d / 'p.json', d / 'raw.json', d / 'rep.json', d / 'a.wav'
            pages.write_text(json.dumps(pages_of(normal_run(1.0, 8)[0])), encoding='utf-8')
            make_tone_wav(wav, [(0.0, 5.0), (12.0, 17.0)], 17.0)                         # silence 5-12 s
            raw.write_text(json.dumps(raw_with_starts([1.0, 2.0, 3.0, 4.0, 12.5, 13.5, 14.5, 15.5], 17.0)), encoding='utf-8')
            r = self.run_cli('--pages', str(pages), '--raw', str(raw), '--report', str(rep))
            self.assertEqual(2, r.returncode, r.stdout)                                  # raw rules cannot be skipped silently
            self.assertIn('--raw needs --wav', r.stderr)
            self.assertFalse(rep.exists())
            r = self.run_cli('--pages', str(pages), '--wav', str(wav), '--report', str(rep))
            self.assertEqual(2, r.returncode)
            r = self.run_cli('--pages', str(pages), '--raw', str(raw), '--wav', str(wav), '--report', str(rep))
            self.assertEqual(0, r.returncode, r.stdout + r.stderr)                       # 4.0 -> 12.5 holds 1.5 s of speech + 7 s silence
            data = json.loads(rep.read_text(encoding='utf-8'))
            self.assertEqual((True, 64), (data['ok'], len(data['wav_sha256'])))
            self.assertEqual(3.0, data['rules']['raw_gap_max_speech_s'])
            raw.write_text(json.dumps(raw_with_starts([1.0, 2.0, 3.0, 4.0, 12.5], 17.0)), encoding='utf-8')   # nothing after 12.5 s
            r = self.run_cli('--pages', str(pages), '--raw', str(raw), '--wav', str(wav), '--report', str(rep))
            self.assertEqual(1, r.returncode, r.stdout + r.stderr)
            self.assertIn('DEFECT raw-gap at 12.500s', r.stdout)
            self.assertIn('limit=3.0', r.stdout)
            self.assertEqual(2, self.run_cli('--pages', str(pages), '--raw', str(raw), '--wav', str(d / 'missing.wav'), '--report', str(rep)).returncode)

    def test_the_ffmpeg_list_and_silence_values_equal_those_of_the_ladder(self):
        sys.path.insert(0, str(SCRIPTS))
        sys.dont_write_bytecode = True
        text = (SCRIPTS / 'asr_transcribe.py').read_text(encoding='utf-8')
        self.assertIn('SILENCE_NOISE_DB = %d ' % td.SILENCE_NOISE_DB, text)
        self.assertIn('SILENCE_MIN_S = %s ' % td.SILENCE_MIN_S, text)

    def test_ffmpeg_candidates_are_identical_in_every_file_that_has_them(self):
        """N9: one fixed ffmpeg list for the whole chain (a mismatch would make the launcher's PATH, the ladder's silencedetect
        and the extraction use different binaries)"""
        want = list(td.FFMPEG_CANDIDATES)
        found = {}
        for name in ('asr_transcribe.py', 'asr_align.py', 'timing_defects.py', 'source_timed.py'):
            m = re.search(r'^FFMPEG_CANDIDATES = (\([^)]*\))', (SCRIPTS / name).read_text(encoding='utf-8'), re.M)
            self.assertIsNotNone(m, name)
            found[name] = list(ast.literal_eval(m.group(1)))
        for name in ('asr_run.sh', 'word_timing.sh'):
            m = re.search(r'^FFMPEG_CANDIDATES=\(([^)]*)\)', (SCRIPTS / name).read_text(encoding='utf-8'), re.M)
            self.assertIsNotNone(m, name)
            found[name] = m.group(1).split()
        for name, got in found.items():
            self.assertEqual(want, got, name)
        self.assertEqual(3, len(want))

    def test_exit_codes_report_and_lines(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            good, bad, raw, rep = d / 'good.json', d / 'bad.json', d / 'raw.json', d / 'rep.json'
            good.write_text(json.dumps(clean_a_like(), ensure_ascii=False), encoding='utf-8')
            bad.write_text(json.dumps(wp6_chunked_excerpt(), ensure_ascii=False), encoding='utf-8')
            raw.write_text(json.dumps(loop_raw()), encoding='utf-8')
            r = self.run_cli('--pages', str(good), '--report', str(rep))
            self.assertEqual(0, r.returncode, r.stdout + r.stderr)
            data = json.loads(rep.read_text(encoding='utf-8'))
            self.assertEqual((True, [], 'yt-news-v4-timing-defects'), (data['ok'], data['defects'], data['schema']))
            wav = d / 'a.wav'
            make_tone_wav(wav, [(0.0, 1.0)], 1.0)
            r = self.run_cli('--pages', str(bad), '--raw', str(raw), '--wav', str(wav), '--report', str(rep))
            self.assertEqual(1, r.returncode, r.stdout + r.stderr)
            data = json.loads(rep.read_text(encoding='utf-8'))
            self.assertEqual(9, len(data['defects']))                    # 8 word defects + the raw loop
            self.assertEqual(9, r.stdout.count('DEFECT '))
            self.assertIn('DEFECT word-too-long at 580.412s', r.stdout)
            self.assertIn('value=9.926 limit=4.0', r.stdout)
            self.assertEqual([], [p.name for p in d.iterdir() if '.tmp' in p.name])
            junk = d / 'junk.json'
            junk.write_text('{not json', encoding='utf-8')
            self.assertEqual(2, self.run_cli('--pages', str(junk), '--report', str(rep)).returncode)
            self.assertEqual(2, self.run_cli('--pages', str(d / 'missing.json'), '--report', str(rep)).returncode)
            self.assertEqual(2, self.run_cli('--pages', str(good)).returncode)


if __name__ == '__main__':
    unittest.main()
