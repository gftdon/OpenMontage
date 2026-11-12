import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
FIX = Path(__file__).resolve().parent / 'fixtures' / 'a67' / 'content'
sys.path.insert(0, str(SCRIPTS))
import episode_data as ed  # noqa: E402
import lint_content as lc  # noqa: E402


def make_inputs(lines, source='', source_all=None, cuts=None, relevance=None, relevance_given=None, legacy=True, join=' ', **extra):
    """lines: [[(word, start_time), ...], ...]; each script line is its words joined by spaces."""
    script, tokens, starts = [], [], []
    for n, words in enumerate(lines, 1):
        script.append(join.join(w for w, _ in words))
        for w, t in words:
            tokens.append({'text': w, 'start': t, 'end': None, 'line': n})
        starts.append({'line': n, 'start': words[0][1], 'end': words[-1][1] + 1.0, 'text': script[-1]})
    return lc.Inputs(script, tokens, starts, cuts or {}, {'numbers': source, 'all': source_all if source_all is not None else source, 'title': extra.pop('title', ''), 'meta': extra.pop('meta', '')},
                     relevance, relevance_given if relevance_given is not None else relevance is not None, legacy=legacy, **extra)


def episode(beats, vo_end=100.0):
    return ed._finish(beats, {}, 'test', vo_end, None)


def pip(t, **kw):
    return {**dict(t=t, mode='pip', media='clip', src='yt_a', origin='source', layout='stage', chrome=True), **kw}


def run(beats, inp, vo_end=100.0, **th):
    return lc.lint_content(episode(beats, vo_end), inp, th)


def codes(issues, sev=None):
    return [i['code'] for i in issues if sev is None or i['severity'] == sev]


def at_time(t0, words):
    return [(w, t0 + k * 0.5) for k, w in enumerate(words)]


class ProvenanceTests(unittest.TestCase):
    def inputs(self, **kw):
        return make_inputs([
            at_time(0, ['คะแนนเริ่มต้นจาก', '3', 'เต็ม', '10']),
            at_time(10, ['ถึง', 'รอบที่', '65', 'ประมาณ', '8']),
            at_time(20, ['โค้ด', '13000', 'บรรทัด']),
        ], **kw)

    def lint(self, text, field='headline', t=5.0, end=15.0, source='', **kw):
        beat = pip(t, **{field: text})
        return run([dict(t=0, mode='full'), beat, dict(t=end, mode='full')], self.inputs(source=source, **kw))[0]

    def test_ordinal_missing_flagged_present_passes(self):
        self.assertIn('provenance-ordinal', codes(self.lint('รอบที่ 1')))
        self.assertNotIn('provenance-ordinal', codes(self.lint('รอบที่ 65')))

    def test_ordinal_number_not_double_reported_as_number(self):
        self.assertNotIn('provenance-number', codes(self.lint('รอบที่ 1')))

    def test_english_ordinal_may_come_from_source(self):
        self.assertIn('provenance-ordinal', codes(self.lint('Round 7')))
        self.assertNotIn('provenance-ordinal', codes(self.lint('Round 7', source='in Round 7 we saw')))

    def test_fraction_passes_via_thai_phrase_in_one_line(self):
        self.assertEqual([], [c for c in codes(self.lint('คะแนน 3/10')) if c.startswith('provenance-number')])

    def test_fraction_fails_when_line_has_only_numerator(self):
        # the real V261111 script: "5 เต็ม 10 ..." (long line) then "... ประมาณ 8 คะแนน" on the NEXT line, 96 characters apart
        far = make_inputs([at_time(0, ['คะแนนเริ่มต้นจาก', '3', 'เต็ม', '10'] + ['ซึ่งเป็นเพียงรูปทรงทึบหยาบๆ'] * 4), at_time(10, ['โดยระดับภาพถูกกำหนดไว้ที่ประมาณ', '8', 'คะแนน'])])
        beat = pip(5.0, headline='เป้า 8/10')
        issues = run([dict(t=0, mode='full'), beat, dict(t=15.0, mode='full')], far)[0]
        self.assertIn('provenance-number', codes(issues, 'error'))
        self.assertIn('fraction 8/10', [i['detail'] for i in issues if i['code'] == 'provenance-number'][0])

    def test_fraction_in_two_adjacent_lines_passes_when_close_fails_when_far(self):
        # ProvenanceTests.inputs: line 1 ends "3 เต็ม 10", line 2 is "ถึง รอบที่ 65 ประมาณ 8": 8 is ~27 characters after the 10
        self.assertNotIn('provenance-number', codes(self.lint('เป้า 8/10')))
        self.assertNotIn('provenance-number', codes(self.lint('เป้า 8 เต็ม 10')))
        # non-adjacent lines never count (line 3 is far from line 1 anyway)
        self.assertIn('provenance-number', codes(self.lint('เป้า 13000/10', end=15.0), 'error'))

    def test_fractions_in_words_are_one_construct(self):
        for text in ('8 จาก 10', '8 ใน 10', '8 เต็ม 10', '8 of 10', '8 out of 10', '8/10'):
            with self.subTest(text=text):
                tk = lc.numeric_tokens(text)
                self.assertEqual([('8', '10')], [(a, c) for a, c, _ in tk['fractions']])
                self.assertEqual([], tk['numbers'])
        self.assertEqual([], lc.numeric_tokens('8 office 10')['fractions'])
        self.assertEqual([], lc.numeric_tokens('ราคา 8 บาท 10')['fractions'])

    def test_unsaid_fraction_in_words_is_reported_like_8_slash_10(self):
        for text in ('คะแนน 7 จาก 9', 'คะแนน 7 ใน 9', 'คะแนน 7 เต็ม 9', 'score 7 of 9', 'score 7 out of 9'):
            with self.subTest(text=text):
                self.assertIn('fraction 7/9', [i['detail'] for i in self.lint(text) if i['code'] == 'provenance-number' and i['severity'] == 'error'][0])

    def test_stat_big_plus_label_forms_one_fraction(self):
        def lint(big, label):
            return [i for i in self.lint_stat(big, label) if i['code'] == 'provenance-number']
        bad = lint('7', '/9')
        self.assertEqual(['stats[0]'], [i['field'] for i in bad])
        self.assertEqual(1, len(bad), bad)                                    # not once more per number
        self.assertEqual('error', bad[0]['severity'])
        self.assertEqual(1, len(lint('7', 'จาก 9 รอบ')))
        self.assertEqual(1, len(lint('7', 'of 9')))
        self.assertEqual([], lint('8', '/10'))                                  # said (adjacent lines, 27 characters)
        self.assertEqual([], lint('8', 'เต็ม 10'))
        self.assertEqual([], lint('13,000', 'บรรทัด'))                         # not a fraction

    def lint_stat(self, big, label):
        beat = pip(5.0, stats=[{'at': 5.0, 'dur': 3.0, 'big': big, 'label': label}])
        return run([dict(t=0, mode='full'), beat, dict(t=15.0, mode='full')], self.inputs())[0]

    def test_breaking_label_and_official_tag_numbers_need_provenance_but_not_words(self):
        def lint(**top):
            ep = ed._finish([dict(t=0, mode='full'), pip(5.0, headline='x')], {'vo_end': 100.0, 'end_card_seconds': 4.0, 'top': {**top}}, 'test', 100.0, None)
            return lc.lint_content(ep, self.inputs(), {})[0]
        got = lint(breakingLabel='BREAKING 2027', officialTag='GEMINI 777 ZEBRA')
        self.assertEqual({('breakingLabel', '2027'), ('officialTag', '777')},
                         {(i['field'], i['detail'].split()[1]) for i in got if i['code'] == 'provenance-number'})
        self.assertEqual([], [i for i in got if i['code'] in ('provenance-latin', 'provenance-thai')])      # words stay exempt
        self.assertEqual([], [i for i in lint(breakingLabel='BREAKING', officialTag='PROMPT ENGINEERING') if i['code'].startswith('provenance')])
        # dateLabel / brand / page.* stay completely exempt chrome
        self.assertEqual([], [i for i in lint(dateLabel='11 พ.ย. 2027', brand='AI 999', page={'domain': 'x.com', 'path': '/777'}) if i['code'].startswith('provenance')])

    def test_fraction_passes_via_source_within_40_chars(self):
        self.assertNotIn('provenance-number', codes(self.lint('เป้า 8/10', source='a score of 8 out of 10 overall')))

    def test_number_commas_thai_digits_and_missing(self):
        self.assertNotIn('provenance-number', codes(self.lint('13,000 บรรทัด')))
        self.assertNotIn('provenance-number', codes(self.lint('๑๓,๐๐๐ บรรทัด')))
        self.assertIn('provenance-number', codes(self.lint('500,000 บรรทัด')))

    # ---- dateLabel numbers are known provenance for endcard.* ONLY ----
    def lint_endcard(self, eyebrow, date_label='11 พ.ย. 2026', beat_text=None):
        beat = pip(5.0, **{'headline': 'x', **(beat_text or {})})
        ep = ed._finish([dict(t=0, mode='full'), beat, dict(t=15.0, mode='full')],
                        {'vo_end': 100.0, 'end_card_seconds': 4.0,
                         'top': {'dateLabel': date_label, 'endcard': {'eyebrow': eyebrow, 'titleA': 'A', 'titleB': 'B', 'cta': 'C'}}},
                        'test', 100.0, None)
        return lc.lint_content(ep, self.inputs(), {})[0]

    def number_issues(self, issues, field=None):
        return [i for i in issues if i['code'] == 'provenance-number' and (field is None or i['field'].startswith(field))]

    def test_endcard_number_from_datelabel_is_known(self):
        self.assertEqual([], self.number_issues(self.lint_endcard('AI TECH NEWS · NOVEMBER 2026'), 'endcard.'))

    def test_endcard_number_not_in_datelabel_or_script_is_still_reported(self):
        got = self.number_issues(self.lint_endcard('AI TECH NEWS · 2027'), 'endcard.')
        self.assertEqual(['endcard.eyebrow'], [i['field'] for i in got])
        self.assertIn('2027', got[0]['detail'])

    def test_datelabel_does_not_help_beats(self):
        for key, val in (('kicker', 'ปี 2026'), ('headline', 'ปี 2026'), ('stats', [{'at': 6.0, 'dur': 3.0, 'big': '2026', 'label': 'x'}])):
            with self.subTest(key=key):
                issues = self.lint_endcard('AI TECH NEWS', beat_text={key: val})
                self.assertTrue(self.number_issues(issues, key), key)

    def test_datelabel_does_not_help_cta(self):
        ep = ed._finish([dict(t=0, mode='full'), pip(5.0, headline='x'), dict(t=15.0, mode='full')],
                        {'vo_end': 100.0, 'end_card_seconds': 4.0, 'cta': 'ปี 2026', 'cta_t': 90.0, 'top': {'dateLabel': '11 พ.ย. 2026'}}, 'test', 100.0, None)
        issues = lc.lint_content(ep, self.inputs(), {})[0]
        self.assertTrue(self.number_issues(issues, 'cta'))

    def test_datelabel_thai_digits_are_normalised(self):
        self.assertEqual([], self.number_issues(self.lint_endcard('NOVEMBER 2026', date_label='๑๑ พ.ย. ๒๐๒๖'), 'endcard.'))
        self.assertEqual([], self.number_issues(self.lint_endcard('NOVEMBER ๒๐๒๖', date_label='11 พ.ย. 2026'), 'endcard.'))
        self.assertTrue(self.number_issues(self.lint_endcard('NOVEMBER ๒๐๒๗', date_label='๑๑ พ.ย. ๒๐๒๖'), 'endcard.'))

    def test_number_boundary_five_is_not_inside_fifteen(self):
        self.assertIn('provenance-number', codes(self.lint('5 บรรทัด')))

    def test_number_found_only_in_source_passes(self):
        self.assertIn('provenance-number', codes(self.lint('217 คะแนน')))
        self.assertNotIn('provenance-number', codes(self.lint('217 คะแนน', source='scores 217 per game')))

    def test_number_is_searched_in_the_whole_script_not_a_line_window(self):
        far = make_inputs([at_time(0, ['a', '1']), at_time(10, ['b']), at_time(20, ['c']), at_time(30, ['d', '77'])])
        beat = pip(0, headline='77 รอบ')
        issues, _ = lc.lint_content(episode([beat, dict(t=8, mode='full')], 100), far, {})
        self.assertNotIn('provenance-number', codes(issues))
        beat = pip(0, headline='78 รอบ')
        issues, _ = lc.lint_content(episode([beat, dict(t=8, mode='full')], 100), far, {})
        self.assertIn('provenance-number', codes(issues, 'error'))

    def test_single_digit_with_unit_is_error_only_when_the_unit_noun_is_in_the_script(self):
        def sev(text):
            return [i['severity'] for i in self.lint(text, source='nothing') if i['code'] == 'provenance-number']
        self.assertEqual(['warn'], sev('RULE 7'))                  # bare single digit
        self.assertEqual(['warn'], sev('7 จุดเปลี่ยน'))            # unit noun not in the script: editorial count of items
        self.assertEqual(['error'], sev('7 บรรทัด'))               # "บรรทัด" is said in the script: the count is unsupported
        self.assertEqual(['error'], sev('คะแนน 25'))               # >= 2 significant digits
        self.assertEqual(['error'], sev('3.5'))                    # contains .
        self.assertEqual(['error'], sev('9%'))                     # contains %

    def test_leading_zero_enumeration_label_is_warn(self):
        def sev(text):
            return [i['severity'] for i in self.lint(text, source='nothing') if i['code'] == 'provenance-number']
        self.assertEqual(['warn'], sev('DEMO 01'))
        self.assertEqual(['warn'], sev('02 บรรทัด'))              # even with a unit that is in the script
        self.assertEqual(['error'], sev('0.5 บรรทัด'))            # a decimal is not an enumeration label
        self.assertEqual(['error'], sev('99 DEMO'))               # two significant digits

    def test_latin_unspoken_flagged_source_word_and_allowlist_pass(self):
        src = 'the SCORE keeps going'
        self.assertIn('provenance-latin', codes(self.lint('TARGET SCORE', field='kicker', source=src)))
        flagged = [i['word'] for i in self.lint('TARGET SCORE', field='kicker', source=src) if i['code'] == 'provenance-latin']
        self.assertEqual(['TARGET'], flagged)
        self.assertNotIn('provenance-latin', codes(self.lint('SCORE', field='kicker', source=src)))
        self.assertNotIn('provenance-latin', codes(self.lint('BREAKING NEWS AI', field='kicker')))

    def test_latin_short_words_ignored(self):
        self.assertNotIn('provenance-latin', codes(self.lint('JS UI', field='kicker')))

    def test_thai_share_is_a_warning_only(self):
        issues = self.lint('ภาพสวยงามน่าประทับใจมากมาย', field='sub')
        self.assertIn('provenance-thai', codes(issues, 'warn'))
        self.assertNotIn('provenance-thai', codes(issues, 'error'))
        self.assertNotIn('provenance-thai', codes(self.lint('คะแนนเริ่มต้นจาก', field='sub')))


class TimingTests(unittest.TestCase):
    def inputs(self):
        return make_inputs([
            at_time(190, ['ใช้', 'โค้ด', 'ใหญ่']),
            at_time(200, ['เกือบ', '13000', 'บรรทัด']),
        ])

    def lint(self, beat, vo_end=210.0):
        return run([dict(t=0, mode='full'), beat, dict(t=beat['end_hint'] if 'end_hint' in beat else 205, mode='full')], self.inputs(), vo_end)[0]

    def test_stat_gone_before_spoken(self):
        # spoken at 200.5; stat visible 194.5 until the beat ends at 199.32
        beat = pip(190.0, stats=[{'t': 194.5, 'big': '13,000', 'label': 'บรรทัด'}], end_hint=199.32)
        issues = self.lint(beat)
        hit = [i for i in issues if i['code'] == 'card-timing-gone-before-spoken']
        self.assertTrue(hit)
        self.assertEqual(200.5, hit[0]['spoken'])
        self.assertEqual(194.5, hit[0]['start'])
        self.assertEqual(199.32, hit[0]['end'])
        self.assertAlmostEqual(1.18, hit[0]['error'], places=2)

    def test_headline_number_spoken_while_visible_passes(self):
        beat = pip(190.0, headline='เกือบ 13,000 บรรทัด', end_hint=205)
        self.assertEqual([], [c for c in codes(self.lint(beat)) if c.startswith('card-timing')])

    def test_headline_gone_before_spoken(self):
        beat = pip(190.0, headline='โค้ด 13,000 บรรทัด', end_hint=199.0)
        self.assertIn('card-timing-gone-before-spoken', codes(self.lint(beat)))

    def test_timed_card_three_seconds_early_is_early_but_headline_is_not(self):
        beat = pip(190.0, stats=[{'t': 197.0, 'big': '13,000', 'label': 'x'}], end_hint=205)
        self.assertIn('card-timing-early', codes(self.lint(beat)))
        beat = pip(190.0, headline='13,000 บรรทัด', end_hint=205)
        self.assertNotIn('card-timing-early', codes(self.lint(beat)))

    def test_within_tolerance_passes(self):
        beat = pip(190.0, stats=[{'t': 198.8, 'big': '13,000', 'label': 'x'}], end_hint=205)
        self.assertEqual([], [c for c in codes(self.lint(beat)) if c.startswith('card-timing')])

    def test_card_appears_too_late(self):
        beat = pip(190.0, stats=[{'t': 204.0, 'big': '13,000', 'label': 'x'}], end_hint=207)
        self.assertIn('card-timing-late', codes(self.lint(beat, 210)))

    def test_v4_at_dur_window_is_not_cut_at_beat_end(self):
        # beat ends 195 but the stat lives 199-204 -> covers the 200.5 mention
        beat = pip(190.0, stats=[{'at': 199.0, 'dur': 5.0, 'big': '13,000', 'label': 'x'}], end_hint=195.0)
        self.assertEqual([], [c for c in codes(self.lint(beat)) if c.startswith('card-timing')])
        # the same item with legacy `t` is cut at the beat end -> gone before spoken
        legacy = pip(190.0, stats=[{'t': 199.0, 'big': '13,000', 'label': 'x'}], end_hint=195.0)
        windows = [f for f in ed.text_fields(episode([legacy, dict(t=195.0, mode='full')], 210)['beats'][0]) if f[0].endswith('.big')]
        self.assertEqual(195.0, windows[0][3])

    def test_v4_at_dur_too_short_is_gone(self):
        beat = pip(190.0, stats=[{'at': 195.0, 'dur': 2.0, 'big': '13,000', 'label': 'x'}], end_hint=205)
        self.assertIn('card-timing-gone-before-spoken', codes(self.lint(beat)))

    def test_number_never_spoken_is_skipped_by_timing(self):
        beat = pip(190.0, headline='999', end_hint=205)
        issues = self.lint(beat)
        self.assertFalse([c for c in codes(issues) if c.startswith('card-timing')])
        self.assertIn('provenance-number', codes(issues))

    def test_nearest_occurrence_to_window_is_used(self):
        inp = make_inputs([at_time(10, ['รอบ', '5', 'และ']), at_time(100, ['แล้ว', '5', 'อีก'])])
        beat = pip(95.0, headline='5 รอบ')
        issues, _ = lc.lint_content(episode([dict(t=0, mode='full'), beat, dict(t=104.0, mode='full')], 110), inp, {})
        self.assertFalse([c for c in codes(issues) if c.startswith('card-timing')])


class TimingFarErrorTests(unittest.TestCase):
    """A number on a timed item (stat / card / item) that is spoken only far from its window is card-timing-far (error)."""

    def lint(self, beat, words=None, **th):
        inp = make_inputs(words or [at_time(0, ['a']), at_time(300, ['ใช้', '777', 'ครั้ง', 'และ', '8', 'จาก', '10'])], source='777 8 10')
        beats = [dict(t=0, mode='full'), beat, dict(t=60.0, mode='full'), dict(t=95.0, mode='full')]
        return lc.lint_content(episode(beats, 400), inp, th)

    def far(self, issues):
        return [i for i in issues if i['code'] == 'card-timing-far']

    def test_timed_items_spoken_only_far_away_are_errors(self):
        for name, fields in (('stat', dict(stats=[{'at': 50.0, 'dur': 5.0, 'big': '777', 'label': 'x'}])),
                             ('card', dict(media='typo', typo='card', cards=[{'at': 50.0, 'lines': ['ก']}, {'at': 52.0, 'lines': ['ใช้ 777 ครั้ง']}], src=None, origin=None)),     # cards[0] is a label: use the 2nd card
                             ('lower', dict(lower={'at': 50.0, 'dur': 3.0, 'title': 'ใช้ 777', 'sub': 'x'}))):
            with self.subTest(name):
                issues, m = self.lint(pip(50.0, **fields))
                got = self.far(issues)
                self.assertEqual(1, len(got), [(i['code'], i['field']) for i in issues])
                self.assertEqual('error', got[0]['severity'])
                self.assertIn('777', got[0]['anchor'])
                self.assertEqual(300.5, got[0]['spoken'])
                self.assertEqual(1, m['timing']['farErrors'])

    def test_recap_beats_and_whole_beat_labels_are_exempt(self):
        far_item = {'at': 50.0, 'text': 'ใช้ 777 ครั้ง'}
        recap = dict(media='typo', typo='summary3', src=None, origin=None, items=[far_item, {'at': 52.0, 'text': 'ก'}, {'at': 54.0, 'text': 'ข'}])
        self.assertEqual([], self.far(self.lint(pip(50.0, **recap))[0]))
        recap4 = dict(media='typo', typo='final4', src=None, origin=None, sub='s', items=[far_item] + [{'at': 51.0 + k, 'text': 'ก'} for k in range(3)])
        self.assertEqual([], self.far(self.lint(pip(50.0, **recap4))[0]))
        self.assertEqual([], self.far(self.lint(pip(50.0, headline='ใช้ 777 ครั้ง'))[0]))                  # whole-beat label
        self.assertEqual([], self.far(self.lint(pip(50.0, media='typo', typo='vs', src=None, origin=None, vs={'left': {'title': '777', 'badge': 'b', 'lines': ['l']},
                                                                                                           'right': {'title': 't', 'badge': 'b', 'lines': ['l']}, 'conclusion': 'c'}))[0]))

    def test_the_final_beat_is_label_like(self):
        inp = make_inputs([at_time(0, ['a']), at_time(300, ['ใช้', '777'])], source='777')
        beats = [dict(t=0, mode='full'), pip(50.0, stats=[{'at': 55.0, 'dur': 3.0, 'big': '777', 'label': 'x'}])]
        self.assertEqual([], self.far(lc.lint_content(episode(beats, 400), inp, {})[0]))

    def test_number_within_30_s_or_never_spoken_is_not_far(self):
        words = [at_time(0, ['a']), at_time(70, ['ใช้', '777', 'ครั้ง'])]
        self.assertEqual([], self.far(self.lint(pip(50.0, stats=[{'at': 50.0, 'dur': 5.0, 'big': '777', 'label': 'x'}]), words)[0]))      # 20 s away
        self.assertEqual([], self.far(self.lint(pip(50.0, stats=[{'at': 50.0, 'dur': 5.0, 'big': '999', 'label': 'x'}]))[0]))               # never spoken: provenance
        self.assertEqual(1, len(self.far(self.lint(pip(50.0, stats=[{'at': 50.0, 'dur': 5.0, 'big': '777', 'label': 'x'}]), None)[0])))

    def test_fractions_are_anchored_for_timing(self):
        issues, _ = self.lint(pip(50.0, stats=[{'at': 50.0, 'dur': 5.0, 'big': '8', 'label': 'จาก 10 คะแนน'}]))
        self.assertEqual(['8/10'], [i['anchor'] for i in self.far(issues)])
        issues, _ = self.lint(pip(50.0, stats=[{'at': 50.0, 'dur': 5.0, 'big': '8/10', 'label': 'x'}]))
        self.assertEqual(['8/10'], [i['anchor'] for i in self.far(issues)])
        # a fraction spoken while it is shown is fine, and the numerator alone (denominator not next to it) is not the fraction
        words = [at_time(0, ['a']), at_time(52, ['ได้', '8', 'จาก', '10'])]
        self.assertEqual([], [i for i in self.lint(pip(50.0, stats=[{'at': 52.0, 'dur': 5.0, 'big': '8/10', 'label': 'x'}]), words)[0] if i['code'].startswith('card-timing')])
        late = self.lint(pip(50.0, stats=[{'at': 58.0, 'dur': 3.0, 'big': '8/10', 'label': 'x'}]), words)[0]      # fractions get late / gone like any number
        self.assertTrue({'card-timing-late', 'card-timing-gone-before-spoken'} & set(codes(late)))
        words = [at_time(0, ['a']), at_time(52, ['ได้', '8', 'คน', 'แล้วยาวไปไกลมากมาย' * 6, '10'])]
        issues = self.lint(pip(50.0, stats=[{'at': 50.0, 'dur': 5.0, 'big': '8/10', 'label': 'x'}]), words)[0]
        self.assertEqual([], [i for i in issues if i['code'].startswith('card-timing')])         # not spoken as a fraction: skipped, left to provenance

    def test_lifting_the_cap_restores_the_old_nearest_rule(self):
        issues, _ = self.lint(pip(50.0, stats=[{'at': 50.0, 'dur': 5.0, 'big': '777', 'label': 'x'}]), timingMaxDistanceSeconds=1e9)
        self.assertEqual([], self.far(issues))
        self.assertIn('card-timing-gone-before-spoken', codes(issues))


class FirstCardTests(unittest.TestCase):
    """Schema S14: a typo `card` beat's first card starts exactly at the beat start, so it cannot follow the "+-2 s of the spoken
    word" rule. cards[0] is treated like a whole-beat label (gone-before-spoken only); cards[1..] keep early / late / far."""

    def lint(self, spoken_at, first_text='ใช้ 777 ครั้ง', second_text='ก', beat_t=10.0, second_at=20.0, end=30.0, words=None):
        inp = make_inputs(words or [at_time(0, ['a']), at_time(spoken_at, ['ใช้', '777', 'ครั้ง'])], source='777')
        beat = dict(t=beat_t, mode='pip', media='typo', typo='card', layout='stage',
                    cards=[{'at': beat_t, 'lines': [first_text]}, {'at': second_at, 'lines': [second_text]}])
        return lc.lint_content(episode([dict(t=0, mode='full'), beat, dict(t=end, mode='full')], 400), inp, {})[0]

    def timing(self, issues, field_prefix):
        return [i['code'] for i in issues if i['code'].startswith('card-timing') and i['field'].startswith(field_prefix)]

    def test_first_card_spoken_while_visible_is_never_early_or_late(self):
        for spoken in (10.5, 12.0, 15.5, 19.0):          # 15.5 is 5.5 s after the card appeared: -early for any other timed item
            with self.subTest(spoken=spoken):
                self.assertEqual([], self.timing(self.lint(spoken), 'cards[0]'))

    def test_first_card_number_spoken_before_the_beat_is_not_late(self):
        self.assertEqual([], self.timing(self.lint(4.0), 'cards[0]'))

    def test_first_card_must_still_be_on_screen_when_the_number_is_spoken(self):
        got = self.timing(self.lint(25.0), 'cards[0]')                 # card 2 replaces card 1 at 20; spoken at 25.5
        self.assertEqual(['card-timing-gone-before-spoken'], got)

    def test_first_card_is_exempt_from_far(self):
        words = [at_time(0, ['a']), at_time(300, ['ใช้', '777', 'ครั้ง'])]
        self.assertEqual([], self.timing(self.lint(0, words=words), 'cards[0]'))

    def test_later_cards_keep_the_two_second_rule_and_far(self):
        # card 2 appears at 20, its number is spoken at 25.5: 5.5 s after it appeared is "early"
        self.assertEqual(['card-timing-early'], self.timing(self.lint(25.0, first_text='ก', second_text='ใช้ 777 ครั้ง'), 'cards[1]'))
        self.assertEqual([], self.timing(self.lint(20.5, first_text='ก', second_text='ใช้ 777 ครั้ง'), 'cards[1]'))
        far = self.lint(0, first_text='ก', second_text='ใช้ 777 ครั้ง', words=[at_time(0, ['a']), at_time(300, ['ใช้', '777', 'ครั้ง'])])
        self.assertEqual(['card-timing-far'], self.timing(far, 'cards[1]'))
        late = self.lint(0, first_text='ก', second_text='ใช้ 777 ครั้ง', words=[at_time(0, ['a']), at_time(10.0, ['ใช้', '777', 'ครั้ง'])])
        self.assertEqual(['card-timing-late'], self.timing(late, 'cards[1]'))

    def test_items_and_stats_keep_the_rule(self):
        inp = make_inputs([at_time(0, ['a']), at_time(25, ['ใช้', '777', 'ครั้ง'])], source='777')
        stat = pip(10.0, stats=[{'at': 10.0, 'dur': 12.0, 'big': '777', 'label': 'x'}])
        issues = lc.lint_content(episode([dict(t=0, mode='full'), stat, dict(t=30.0, mode='full')], 400), inp, {})[0]
        self.assertIn('card-timing-gone-before-spoken', codes(issues))     # stat window 10-22, spoken at 25.5
        stat = pip(10.0, stats=[{'at': 10.0, 'dur': 12.0, 'big': '777', 'label': 'x'}])
        inp = make_inputs([at_time(0, ['a']), at_time(16, ['ใช้', '777', 'ครั้ง'])], source='777')
        self.assertIn('card-timing-early', codes(lc.lint_content(episode([dict(t=0, mode='full'), stat, dict(t=30.0, mode='full')], 400), inp, {})[0]))


class TypoFillerTests(unittest.TestCase):
    SCRIPT = [at_time(0, ['คำพูดจริงในสคริปต์', 'เครื่องยนต์เจ็ต', 'ภาพตัดขวาง'])]

    def lint(self, texts, extra_beats=(), **th):
        lines = [t for t in texts]
        beat = pip(10.0, media='typo', typo='card', src=None, origin=None, layout='stage',
                   cards=[{'at': 10.0 + k * 1.0, 'lines': [t]} for k, t in enumerate(lines)])
        beats = [dict(t=0, mode='full'), beat, *extra_beats, dict(t=10.0 + len(lines) + 5, mode='full')]
        return lc.lint_content(episode(beats, 100), make_inputs(self.SCRIPT), th)

    OK, BAD = 'เครื่องยนต์เจ็ต', 'ข้อความอวดอ้างสรรพคุณเกินจริง'

    def test_more_than_30_percent_unsupported_is_an_error_but_each_text_stays_a_warning(self):
        issues, m = self.lint([self.OK, self.BAD, self.BAD])
        self.assertIn('typo-filler', codes(issues, 'error'))
        self.assertEqual({'warn'}, {i['severity'] for i in issues if i['code'] == 'provenance-thai'})
        self.assertEqual(2, codes(issues).count('provenance-thai'))
        self.assertEqual({'texts': 3, 'unsupported': 2, 'share': 0.6667, 'maxShare': 0.3}, m['typoFiller'])

    def test_30_percent_or_less_passes(self):
        issues, m = self.lint([self.OK] * 7 + [self.BAD] * 3)                  # exactly 30 %: not "more than"
        self.assertNotIn('typo-filler', codes(issues))
        self.assertEqual(0.3, m['typoFiller']['share'])
        self.assertIn('typo-filler', codes(self.lint([self.OK] * 6 + [self.BAD] * 4)[0]))
        self.assertNotIn('typo-filler', codes(self.lint([self.OK, self.OK, self.OK])[0]))

    def test_only_typo_beats_count(self):
        # unsupported Thai text on a source clip beat's stat / headline is the provenance warning only
        clip = pip(5.0, headline=self.BAD, stats=[{'at': 5.0, 'dur': 3.0, 'big': '1', 'label': self.BAD}], src='yt_a')
        issues, m = lc.lint_content(episode([dict(t=0, mode='full'), clip, dict(t=20.0, mode='full')], 100), make_inputs(self.SCRIPT), {})
        self.assertNotIn('typo-filler', codes(issues))
        self.assertEqual(0, m['typoFiller']['texts'])

    def test_items_and_vs_texts_count_too(self):
        beat = pip(10.0, media='typo', typo='summary3', src=None, origin=None, layout='stage',
                   items=[{'at': 10.0, 'text': self.BAD}, {'at': 11.0, 'text': self.BAD}, {'at': 12.0, 'text': self.OK}])
        issues, m = lc.lint_content(episode([dict(t=0, mode='full'), beat, dict(t=20.0, mode='full')], 100), make_inputs(self.SCRIPT), {})
        self.assertIn('typo-filler', codes(issues, 'error'))
        self.assertEqual(3, m['typoFiller']['texts'])

    def test_the_share_is_a_named_threshold(self):
        self.assertEqual(0.30, lc.THRESHOLDS['typoFillerMaxShare'])
        self.assertNotIn('typo-filler', codes(self.lint([self.OK, self.BAD, self.BAD], typoFillerMaxShare=0.9)[0]))


class TimingFarTests(unittest.TestCase):
    def test_lone_number_spoken_far_away_is_left_to_provenance_unless_cap_is_lifted(self):
        inp = make_inputs([at_time(0, ['a']), at_time(300, ['ใช้', '777', 'ครั้ง'])], source='777')
        beats = [dict(t=0, mode='full'), pip(50.0, headline='777 มิติ'), dict(t=60.0, mode='full')]
        issues, m = lc.lint_content(episode(beats, 400), inp, {})
        self.assertFalse([c for c in codes(issues) if c.startswith('card-timing')])
        self.assertEqual(1, m['timing']['anchorsOnlySpokenFar'])
        issues, _ = lc.lint_content(episode(beats, 400), inp, {'timingMaxDistanceSeconds': 1e9})
        self.assertIn('card-timing-gone-before-spoken', codes(issues))

    def test_big_stat_reported_once_not_twice(self):
        inp = make_inputs([at_time(200, ['เกือบ', '13000', 'บรรทัด'])])
        beat = pip(190.0, stats=[{'t': 194.5, 'big': '13,000', 'label': 'x'}])
        issues, _ = lc.lint_content(episode([dict(t=0, mode='full'), beat, dict(t=199.32, mode='full')], 210), inp, {})
        self.assertEqual(1, codes(issues).count('card-timing-gone-before-spoken'))


class AnchorTests(unittest.TestCase):
    """Specific anchors only: (a) >=3 digits or , . %, (b) number + unit word, (c) non-numeric big >= 4 chars."""
    TH = lc.THRESHOLDS

    def anchors(self, text, field='headline'):
        return lc.anchors(field, text, self.TH)

    def test_long_or_punctuated_numbers_are_anchors(self):
        for text in ('217 คะแนน', '13,000 บรรทัด', '3.5 เท่า', '20% ของงาน'):
            with self.subTest(text=text):
                anc, amb = self.anchors(text)
                self.assertEqual(1, len(anc), anc)
                self.assertEqual(0, amb)

    def test_short_number_without_unit_is_ambiguous(self):
        anc, amb = self.anchors('RULES 3 & 4')
        self.assertEqual(([], 2), (anc, amb))
        anc, amb = self.anchors('คะแนน 5/10')
        self.assertEqual(([('5/10', ('frac', '10'))], 0), ([(a[0], a[2]) for a in anc], amb))      # a fraction anchors on its numerator next to the denominator

    def test_short_number_with_unit_word_is_an_anchor_with_unit(self):
        anc, amb = self.anchors('ใช้เวลา 20 ชั่วโมง')
        self.assertEqual(0, amb)
        self.assertEqual([('20 ชั่วโมง', 'ชั่วโมง')], [(a[0], a[2]) for a in anc])
        anc, amb = self.anchors('15 PASSES')
        self.assertEqual([('15 PASSES', 'PASSES')], [(a[0], a[2]) for a in anc])

    def test_non_numeric_big_of_four_chars_is_anchor_three_is_not(self):
        self.assertEqual(1, len(self.anchors('THREE.JS', 'stats[0].big')[0]))
        self.assertEqual(([], 0), self.anchors('SDF', 'stats[0].big'))
        self.assertEqual(([], 0), self.anchors('THREE.JS', 'headline'))    # only stat `big`

    def test_ordinal_phrase_is_an_anchor(self):
        anc, amb = self.anchors('รอบที่ 65')
        self.assertEqual(([('รอบที่ 65', None)], 0), ([(a[0], a[2]) for a in anc], amb))

    def inputs(self):
        return make_inputs([at_time(190, ['ใช้', 'โค้ด']), at_time(200, ['ทำงาน', '20', 'ชั่วโมง', 'แล้ว', '4', 'คน'])])

    def lint(self, **fields):
        beat = pip(190.0, **fields)
        issues, m = lc.lint_content(episode([dict(t=0, mode='full'), beat, dict(t=199.0, mode='full')], 210), self.inputs(), {})
        return [i for i in issues if i['code'].startswith('card-timing')], m['timing']

    def test_unit_must_also_follow_the_number_in_the_script(self):
        issues, t = self.lint(headline='ใช้ 20 ชั่วโมง')           # "20 ชั่วโมง" spoken at 200.5 > beat end 199 -> gone
        self.assertEqual(['card-timing-gone-before-spoken'], codes(issues))
        issues, t = self.lint(headline='ใช้ 20 วัน')              # script has 20 followed by ชั่วโมง, not วัน -> never spoken as that unit
        self.assertEqual([], codes(issues))
        self.assertEqual(1, t['anchorsNeverSpoken'])

    def test_ambiguous_numbers_are_counted_not_timed(self):
        issues, t = self.lint(headline='มี 4 คน และ 3')
        self.assertEqual(1, t['ambiguousAnchors'])                  # bare 3 is ambiguous; "4 คน" anchors (and is spoken after the beat)
        self.assertEqual(['card-timing-gone-before-spoken'], codes(issues))
        issues, t = self.lint(kicker='RULES 3 & 4')
        self.assertEqual(([], 2), (codes(issues), t['ambiguousAnchors']))


class PresenterTests(unittest.TestCase):
    def pr(self, spans, vo=100.0, **th):
        """spans: list of (t, has_media). Returns (issues, metrics['presenter'])."""
        beats = [pip(t) if media else dict(t=t, mode='full') for t, media in spans]
        inp = make_inputs([at_time(0, ['x'])])
        issues, m = run(beats, inp, vo, **th)
        return [i for i in issues if i['code'].startswith('presenter')], m['presenter']

    def test_locked_defaults(self):
        # locked by lead 2026-11-12
        th = lc.THRESHOLDS
        self.assertEqual((0.25, 12.0, 10.0), (th['maxPresenterShare'], th['maxPresenterRun'], th['coldOpenSeconds']))

    def test_punch_does_not_reset_a_presenter_run(self):
        beats = [dict(t=0, mode='full'), pip(10), dict(t=20, mode='full', punch=[{'at': 22, 'z': 1.2}]), dict(t=30, mode='full', punch=[{'at': 33, 'z': 1.3}]), pip(40), dict(t=90, mode='full')]
        issues, m = lc.lint_content(episode(beats, 100), make_inputs([at_time(0, ['x'])]), {})
        self.assertEqual([20.0], [i['t'] for i in issues if i['code'] == 'presenter-run'])   # 20-40 = 20 s despite two punches

    def test_cold_open_and_final_beat_excluded(self):
        # presenter 0-9 (cold open), media 9-90, presenter 90-100 (final)
        issues, p = self.pr([(0, False), (9, True), (90, False)])
        self.assertEqual([], issues)
        self.assertEqual(0, p['presenterSeconds'])
        self.assertEqual(9.0, p['coldOpenExcludedSeconds'])
        self.assertTrue(p['finalBeatExcluded'])

    def test_cold_open_longer_than_ten_counts_only_the_excess(self):
        issues, p = self.pr([(0, False), (14, True), (90, True)])
        self.assertEqual(4.0, p['presenterSeconds'])
        self.assertEqual([], issues)

    def test_run_over_limit_is_one_issue_per_run(self):
        issues, p = self.pr([(0, False), (10, True), (20, False), (35, True), (50, False), (55, True), (95, False)])
        self.assertEqual(['presenter-run'], [i['code'] for i in issues])
        self.assertEqual(20.0, issues[0]['t'])
        self.assertEqual([15.0], [r['seconds'] for r in p['runsOver7']])

    def test_adjacent_presenter_beats_merge(self):
        issues, p = self.pr([(0, False), (10, True), (20, False), (27, False), (34, True), (95, False)])
        self.assertEqual(['presenter-run'], [i['code'] for i in issues])  # 20-34 = 14 s > 12
        self.assertEqual(14.0, issues[0]['seconds'])

    def test_total_share_over_limit(self):
        spans = [(0, False), (10, True), (20, False), (30, True), (40, False), (50, True), (60, False), (70, True), (80, False), (88, True)]
        issues, p = self.pr(spans, vo=100.0)
        self.assertIn('presenter-share', [i['code'] for i in issues])
        self.assertGreater(p['share'], 0.25)
        self.assertEqual(['presenter-share'], [i['code'] for i in issues])

    def test_threshold_override_and_runs_report_lists_seven_seconds(self):
        issues, p = self.pr([(0, False), (10, True), (20, False), (28, True), (95, False)], maxPresenterRun=5.0, maxPresenterShare=1.0)
        self.assertEqual(['presenter-run'], [i['code'] for i in issues])
        self.assertEqual(1, len(p['runsOver7']))

    def test_presenter_only_final_beat_with_media_is_not_excluded(self):
        issues, p = self.pr([(0, False), (10, True), (50, True)])
        self.assertFalse(p['finalBeatExcluded'])


class SimpleCheckTests(unittest.TestCase):
    inp = None

    def setUp(self):
        self.inp = make_inputs([at_time(0, ['x'])])

    def lint(self, beats, ep_meta=None, inp=None, **th):
        ep = ed._finish(beats, ep_meta or {}, 'test', 100.0, None)
        return lc.lint_content(ep, inp or self.inp, th)[0]

    def test_cta_length(self):
        body = [dict(t=0, mode='full'), pip(10)]
        self.assertIn('cta-length', codes(self.lint(body, {'cta': 'ก' * 41})))
        self.assertNotIn('cta-length', codes(self.lint(body, {'cta': 'ก' * 40})))
        self.assertNotIn('cta-length', codes(self.lint(body, {'cta': 'ก' * 30 + ' ' * 20 + 'ก' * 10})))  # spaces not counted

    def test_punch_on_source_beat_and_final_beat_fail_presenter_passes(self):
        punch = [{'t': 12, 'z': 1.2}]
        self.assertIn('punch-forbidden', codes(self.lint([dict(t=0, mode='full'), pip(10, punch=punch), dict(t=50, mode='full')])))
        self.assertIn('punch-forbidden', codes(self.lint([dict(t=0, mode='full'), pip(10), dict(t=50, mode='full', punch=[{'t': 60, 'z': 1.2}])])))
        self.assertNotIn('punch-forbidden', codes(self.lint([dict(t=0, mode='full', punch=[{'t': 3, 'z': 1.2}]), pip(10), dict(t=50, mode='full')])))

    def test_there_is_no_typo_kind_check_any_more(self):
        beats = [dict(t=0, mode='full'), dict(t=5, mode='pip', media='typo', headline='x'), dict(t=50, mode='full')]
        self.assertNotIn('typo-kind', codes(self.lint(beats)))

    def test_punch_only_on_presenter_full_beats_and_never_after_ctaT(self):
        def lint(beats, cta_t=None):
            ep = ed._finish(beats, {'cta_t': cta_t}, 'test', 100.0, None)
            return lc.lint_content(ep, self.inp, {})[0]
        punch = [{'at': 12, 'z': 1.2}]
        # pip beats: source, stock, stage, wide -> all forbidden
        for extra in (dict(origin='source'), dict(origin='stock', media='broll'), dict(layout='wide')):
            with self.subTest(extra=extra):
                self.assertIn('punch-forbidden', codes(lint([dict(t=0, mode='full'), pip(10, punch=punch, **extra), dict(t=50, mode='full')], 90.0)))
        # full beat before ctaT passes, at/after ctaT fails
        beats = [dict(t=0, mode='full', punch=[{'at': 5, 'z': 1.2}]), pip(10), dict(t=50, mode='full', punch=[{'at': 60, 'z': 1.2}])]
        self.assertNotIn('punch-forbidden', codes(lint(beats, 90.0)))
        self.assertIn('punch-forbidden', codes(lint(beats, 60.0)))                 # at == ctaT
        self.assertIn('punch-forbidden', codes(lint(beats, 55.0)))                 # after
        self.assertIn('punch-forbidden', codes(lint(beats, None)))                 # legacy: final beat
        # legacy `t` key is honoured
        legacy = [dict(t=0, mode='full'), pip(10), dict(t=50, mode='full', punch=[{'t': 70, 'z': 1.2}])]
        self.assertIn('punch-forbidden', codes(lint(legacy, 65.0)))

    def test_punch_copy_is_off_for_v4_objects_because_the_schema_owns_it(self):
        """V4 object episodes: S12 (episode_schema.mjs, code `schema`) is the only punch rule; legacy data keeps punch-forbidden."""
        beats = [dict(t=0, mode='full'), pip(10, punch=[{'at': 12, 'z': 1.2}]), dict(t=50, mode='full')]
        for fmt, legacy, expect in (('json-object', False, False), ('json-object', True, True), ('json-list', False, True), ('test', False, True)):
            with self.subTest(fmt=fmt, legacy=legacy):
                ep = ed._finish(beats, {'cta_t': 60.0}, fmt, 100.0, None)
                inp = make_inputs([at_time(0, ['x'])], legacy=legacy)
                self.assertEqual(expect, 'punch-forbidden' in codes(lc.lint_content(ep, inp, {})[0]))

    def stock(self, origin='stock', src='desk', t=10):
        return [dict(t=0, mode='full'), dict(t=t, mode='pip', media='broll', src=src, origin=origin, layout='stage', chrome=False), dict(t=50, mode='full')]

    def test_stock_without_relevance_fails_closed(self):
        self.assertIn('stock-unverified', codes(self.lint(self.stock())))
        self.assertIn('stock-unverified', codes(self.lint(self.stock('ai', 'ai_x'))))
        inp = make_inputs([at_time(0, ['x'])], relevance=[], relevance_given=True)
        self.assertIn('stock-unverified', codes(self.lint(self.stock(), inp=inp)))

    def test_stock_with_passing_verdict_by_src_or_time(self):
        by_src = make_inputs([at_time(0, ['x'])], relevance=[{'src': 'desk', 'score': 2}])
        self.assertNotIn('stock-unverified', codes(self.lint(self.stock(), inp=by_src)))
        by_t = make_inputs([at_time(0, ['x'])], relevance=[{'beat': 'b2', 't': 10.0, 'end': 50.0, 'score': 1, 'reason': 'ok'}])
        self.assertNotIn('stock-unverified', codes(self.lint(self.stock(), inp=by_t)))

    def test_stock_failing_or_stale_label_verdicts_fail(self):
        for row in ({'src': 'desk', 'score': 0}, {'src': 'desk', 'score': None}, {'src': 'desk', 'score': 2, 'pending_zero': True},
                    {'src': 'desk', 'score': 0, 'verification_status': 'verified'}):
            with self.subTest(row=row):
                inp = make_inputs([at_time(0, ['x'])], relevance=[row])
                self.assertIn('stock-unverified', codes(self.lint(self.stock(), inp=inp)))

    def test_ai_needs_readable_text_false(self):
        ai = make_inputs([at_time(0, ['x'])], relevance=[{'src': 'ai_x', 'score': 2}])
        self.assertIn('stock-unverified', codes(self.lint(self.stock('ai', 'ai_x'), inp=ai)))
        ok = make_inputs([at_time(0, ['x'])], relevance=[{'src': 'ai_x', 'score': 2, 'readable_text': False}])
        self.assertNotIn('stock-unverified', codes(self.lint(self.stock('ai', 'ai_x'), inp=ok)))

    def test_relevance_report_format_from_batch_relevance(self):
        report = {'schema': 'a44-native-batch-1', 'results': [{'beat': 'x', 't': 10.0, 'end': 50.0, 'score': 2, 'verification_status': 'verified'}]}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'report.json'
            p.write_text(json.dumps(report))
            rows = lc.load_relevance(p)
            p.write_text(json.dumps({'desk': {'score': 2}}))
            rows_map = lc.load_relevance(p)
        self.assertEqual(1, len(rows))
        self.assertEqual('desk', rows_map[0]['src'])

    def test_agrees_with_score_relevance_verification_status(self):
        import score_relevance as sr
        for row, origin in (({'score': 1}, 'stock'), ({'score': 0}, 'stock'), ({'score': 2, 'readable_text': True}, 'ai'), ({'score': 2, 'readable_text': False}, 'ai')):
            inp = make_inputs([at_time(0, ['x'])], relevance=[{**row, 'src': 'desk'}])
            failed = 'stock-unverified' in codes(self.lint(self.stock(origin), inp=inp))
            self.assertEqual(sr.verification_status(row, origin) != 'verified', failed)

    def source_beats(self, gap, from2=0, src2='yt_b'):
        return [dict(t=0, mode='full'), pip(10, src='yt_a'), pip(10 + gap, src=src2, **{'from': from2}), dict(t=10 + gap + 8, mode='full')]

    CUTS = {'yt_a': {'source_in': 475.0, 'source_out': 500.0}, 'yt_b': {'source_in': 480.0, 'source_out': 510.0}}

    def test_source_reuse_overlap_42s_apart_fails_70s_apart_passes(self):
        inp = make_inputs([at_time(0, ['x'])], cuts=self.CUTS)
        self.assertIn('source-reuse', codes(self.lint(self.source_beats(42), inp=inp)))
        self.assertNotIn('source-reuse', codes(self.lint(self.source_beats(70), inp=inp)))

    def test_source_reuse_respects_from_offset_and_identical_clip(self):
        inp = make_inputs([at_time(0, ['x'])], cuts=self.CUTS)
        # yt_a shows 475-483 (beat 10..42 is 32 s but capped by source_out 500 -> 475-500); yt_b from 25 starts at 505 -> no overlap
        self.assertNotIn('source-reuse', codes(self.lint(self.source_beats(42, from2=25), inp=inp)))
        same = [dict(t=0, mode='full'), pip(10, src='yt_a'), pip(40, src='yt_a'), dict(t=48, mode='full')]
        self.assertIn('source-reuse', codes(self.lint(same, inp=inp)))
        shifted = [dict(t=0, mode='full'), pip(10, src='yt_a'), dict(t=20, mode='full'), pip(40, src='yt_a', **{'from': 12}), dict(t=48, mode='full')]
        self.assertNotIn('source-reuse', codes(self.lint(shifted, inp=inp)))

    def test_source_clip_missing_from_cuts_is_an_error(self):
        self.assertIn('source-reuse-unknown-clip', codes(self.lint(self.source_beats(42))))

    def test_non_source_beats_do_not_count_for_reuse(self):
        inp = make_inputs([at_time(0, ['x'])], cuts=self.CUTS, relevance=[{'src': 'yt_b', 'score': 2}])
        beats = [dict(t=0, mode='full'), pip(10, src='yt_a'), dict(t=20, mode='pip', media='broll', src='yt_b', origin='stock', layout='stage', chrome=False), dict(t=40, mode='full')]
        self.assertNotIn('source-reuse', codes(self.lint(beats, inp=inp)))


class CropTrimsSourceTests(unittest.TestCase):
    """crop-trims-source: warning-only, a srcCrop that trims an edge by more than 2 % of that side of the 1920x1080 frame."""

    def lint(self, crop, asset_dir='demo', **kw):
        beat = pip(5.0, **kw)
        if crop is not None:
            beat['srcCrop'] = crop
        inp = make_inputs([at_time(0, ['คำพูด', 'ทดสอบ'])])
        ep = episode([dict(t=0, mode='full'), beat, dict(t=15.0, mode='full')])
        if asset_dir is not None:
            ep['assetDir'] = asset_dir
        return lc.lint_content(ep, inp, {})[0]

    def hits(self, crop, **kw):
        return [i for i in self.lint(crop, **kw) if i['code'] == 'crop-trims-source']

    def test_command_uses_public_clip_path_and_falls_back_without_asset_dir(self):
        crop = {'x': 60, 'y': 120, 'w': 1440, 'h': 810}
        self.assertIn('-i remotion-composer/public/demo/broll/yt_a.mp4 ', self.hits(crop)[0]['detail'])
        for bad in (None, 5, ''):
            with self.subTest(asset_dir=bad):
                msg = self.hits(crop, asset_dir=bad)[0]['detail']
                self.assertIn('-i yt_a.mp4 ', msg)
                self.assertNotIn('remotion-composer', msg)

    def test_trimmed_crop_warns_with_percentages_and_command(self):
        crop = {'x': 60, 'y': 120, 'w': 1440, 'h': 810}
        got = self.hits(crop)
        self.assertEqual(1, len(got), got)
        self.assertEqual('warn', got[0]['severity'])
        self.assertEqual(5.0, got[0]['t'])
        msg = got[0]['detail']
        for part in ('left 3.1%', 'right 21.9%', 'top 11.1%', 'bottom 13.9%', 'yt_a', 'drawbox=x=60:y=120:w=1440:h=810', 'beat 1', 't=5.00', 'no gate can tell'):
            self.assertIn(part, msg)
        self.assertIn('ffmpeg -ss 5.0 -i remotion-composer/public/demo/broll/yt_a.mp4 -frames:v 1', msg)
        self.assertIn('-frames:v 1', msg)
        self.assertIn('crop_check.jpg', msg)
        self.assertNotIn('\n', msg)

    def test_warning_never_changes_errors_or_pass(self):
        with_crop = self.lint({'x': 60, 'y': 120, 'w': 1440, 'h': 810})
        without = self.lint(None)
        errs = lambda issues: sorted(i['code'] for i in issues if i['severity'] == 'error')
        self.assertEqual(errs(without), errs(with_crop))
        self.assertEqual([], [i for i in with_crop if i['code'] == 'crop-trims-source' and i['severity'] != 'warn'])

    def test_full_frame_crop_does_not_warn(self):
        self.assertEqual([], self.hits({'x': 0, 'y': 0, 'w': 1920, 'h': 1080}))

    def test_threshold_is_strictly_greater_than_two_percent(self):
        self.assertEqual([], self.hits({'x': 38, 'y': 0, 'w': 1882, 'h': 1080}))        # 1.98 % left
        self.assertEqual(1, len(self.hits({'x': 39, 'y': 0, 'w': 1881, 'h': 1080})))    # 2.03 % left

    def test_beat_without_src_crop_does_not_warn(self):
        self.assertEqual([], self.hits(None))

    def test_malformed_src_crop_is_skipped_without_exception(self):
        for crop in ({'x': 'a'}, {'x': 0, 'y': 0, 'w': 1920}, {'x': 0, 'y': 0, 'w': 'b', 'h': 1080}, 'oops', [1, 2, 3, 4], {'x': True, 'y': 0, 'w': 1920, 'h': 1080}):
            with self.subTest(crop=crop):
                self.assertEqual([], self.hits(crop))


class LoaderTests(unittest.TestCase):
    def test_v4_object_json_is_primary(self):
        ep = ed.load_episode(FIX / 'episode_object.json')
        self.assertEqual('json-object', ep['format'])
        self.assertEqual(30.0, ep['vo_end'])
        self.assertEqual(26.0, ep['cta_t'])
        self.assertEqual(4.5, ep['end_card_seconds'])
        self.assertEqual('ติดตามช่องไว้นะ', ed.episode_cta(ep))
        self.assertEqual([0, 5, 12, 20, 28], [b['t'] for b in ep['beats']])
        self.assertEqual([5, 12, 20, 28, 30], [b['end'] for b in ep['beats']])
        self.assertEqual({'x': 0, 'y': 0, 'w': 1280, 'h': 720}, ep['beats'][1]['srcCrop'])  # passed through
        self.assertEqual(4, ep['beats'][3]['from'])
        fields = {f[0]: f for f in ed.text_fields(ep['beats'][3])}
        self.assertEqual((21.0, 25.0, 'timed'), fields['stats[0].big'][2:])      # [at, at+dur), not cut at beat end
        self.assertEqual((20, 28, 'beat'), fields['headline'][2:])
        full = {f[0]: f for f in ed.text_fields(ep['beats'][0])}
        self.assertEqual((1, 4, 'timed'), full['lower.title'][2:])
        items = {f[0]: f for f in ed.text_fields(ep['beats'][2])}
        self.assertEqual((13, 20, 'timed'), items['items[0]'][2:])               # visible from `at` to beat end
        self.assertEqual((19, 20, 'timed'), items['items[2]'][2:])

    def test_episode_level_fields_cta_endcard_chrome(self):
        ep = ed.load_episode(FIX / 'episode_object.json')
        top = {f[0]: f for f in ed.episode_text_fields(ep)}
        self.assertEqual((26.0, 30.0, 'timed'), top['cta'][2:])                    # [ctaT, voEndSec]
        self.assertEqual((30.0, 34.5, 'beat'), top['endcard.titleB'][2:])
        self.assertEqual({'endcard.eyebrow', 'endcard.titleA', 'endcard.titleB', 'endcard.cta'}, {k for k in top if k.startswith('endcard.')})
        for k in ('brand', 'dateLabel', 'breakingLabel', 'officialTag', 'page.domain', 'page.path'):
            self.assertEqual('chrome', top[k][4])

    def test_vs_cards_and_items_text_fields(self):
        beat = {'t': 10.0, 'end': 30.0, 'mode': 'pip', 'media': 'typo', 'typo': 'vs', 'headline': 'H',
                'vs': {'left': {'title': 'A', 'badge': 'OLD', 'lines': ['l1', 'l2']}, 'right': {'title': 'B', 'badge': 'NEW', 'lines': ['r1']}, 'conclusion': 'C'},
                'cards': [{'at': 10, 'lines': ['c1', 'c2']}, {'at': 18, 'lines': ['c3']}]}
        f = {x[0]: x for x in ed.text_fields(beat)}
        for k in ('vs.left.title', 'vs.left.badge', 'vs.left.lines[1]', 'vs.right.title', 'vs.right.badge', 'vs.right.lines[0]', 'vs.conclusion'):
            self.assertEqual((10.0, 30.0, 'beat'), f[k][2:], k)               # whole beat
        self.assertEqual((10, 18, 'timed'), f['cards[0].lines[1]'][2:])        # until the next card
        self.assertEqual((18, 30.0, 'timed'), f['cards[1].lines[0]'][2:])      # until beat end

    def test_legacy_list_json(self):
        ep = ed.load_episode(FIX / 'episode_list.json', vo_end=30.0)
        self.assertEqual('json-list', ep['format'])
        self.assertEqual(30.0, ep['vo_end'])
        beat = ep['beats'][2]
        cards = {f[0]: f for f in ed.text_fields(beat)}
        self.assertEqual((13, 17.5, 'timed'), cards['cards[0].lines[0]'][2:])    # to the next card
        self.assertEqual((17.5, 20, 'timed'), cards['cards[1].lines[0]'][2:])    # to beat end
        stat = {f[0]: f for f in ed.text_fields(ep['beats'][3])}
        self.assertEqual((21.0, 28, 'timed'), stat['stats[0].big'][2:])          # legacy stat: until beat end

    def test_list_json_needs_vo_end(self):
        with self.assertRaises(ed.EpisodeFormatError):
            ed.load_episode(FIX / 'episode_list.json')
        self.assertEqual(33.0, ed.load_episode(FIX / 'episode_list.json', fallback_vo_end=33.0)['vo_end'])

    def test_legacy_tsx(self):
        ep = ed.load_episode(FIX / 'episode_mini.tsx')
        self.assertEqual('tsx', ep['format'])
        self.assertEqual(30.0, ep['vo_end'])
        self.assertAlmostEqual(4.5, ep['end_card_seconds'])
        self.assertEqual([0.0, 5.0, 28.0], [b['t'] for b in ep['beats']])
        self.assertIs(ep['beats'][1]['chrome'], True)
        fields = {f[0]: f for f in ed.text_fields(ep['beats'][1])}
        self.assertEqual((5.5, 28.0, 'timed'), fields['stats[0].big'][2:])

    def test_bad_inputs_raise(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'bad.json'
            p.write_text('{"nope": 1}')
            with self.assertRaises(ed.EpisodeFormatError):
                ed.load_episode(p)
            p.write_text('not json')
            with self.assertRaises(ed.EpisodeFormatError):
                ed.load_episode(p)
            with self.assertRaises(ed.EpisodeFormatError):
                ed.load_episode(Path(d) / 'missing.json')

    def test_words_formats_and_clock(self):
        tokens = ed.load_words(FIX / 'words_by_line.txt')
        tok = next(t for t in tokens if t['text'] == '13,000')
        self.assertEqual((22.0, 3), (tok['start'], tok['line']))
        clock = ed.ScriptClock(ed.load_script_lines(FIX / 'script.txt'), tokens)
        self.assertEqual([], clock.misaligned_lines)
        occ = clock.occurrences(ed.number_regex('13000'))
        self.assertEqual([(22.0, 3)], [(o[2], o[3]) for o in occ])
        with tempfile.TemporaryDirectory() as d:
            pages = Path(d) / 'caption_pages_final.json'
            pages.write_text(json.dumps([{'words': [{'w': 'Google', 's': 0.0, 'e': 1.0}, {'w': 'เปิดตัว', 's': 1.0, 'e': 2.0}]},
                                         {'chunks': [{'tokens': [{'w': 'Gemini', 's': 2.0, 'e': 3.0}]}]}]))
            toks = ed.load_words(pages)
            self.assertEqual(['Google', 'เปิดตัว', 'Gemini'], [t['text'] for t in toks])
            flat = ed.ScriptClock(['Google เปิดตัว Gemini'], toks)
            self.assertEqual(2.0, flat.time_at(flat.stream.index('Gemini')))


class EvidenceTests(unittest.TestCase):
    """Shown-vs-said checks on source clip beats."""
    CUTS = {'yt_jet_engine': {'source_in': 590.0, 'source_out': 610.0}}

    def inputs(self, evidence=None, frames=None, timed=None, chapters=None, legacy=False, title=''):
        return make_inputs([at_time(390, ['x', 'y']), at_time(400, ['z'])], cuts=self.CUTS, legacy=legacy, evidence=evidence,
                           frames=frames, timed=timed, chapters=chapters, title=title)

    def beats(self, **kw):
        return [dict(t=0, mode='full'), pip(399.0, src='yt_jet_engine', **{'headline': 'สร้างภาพตัดขวางเครื่องยนต์', **kw}), dict(t=408.0, mode='full')]

    def run_(self, inp, **kw):
        return lc.lint_content(episode(self.beats(**kw), 420), inp, {})[0]

    ENTRY = {'t': 399.0, 'src': 'yt_jet_engine', 'cue_line': 2, 'subject_terms': ['jet engine'], 'seen': 'engine cutaway drawing'}
    TIMED = [{'start': 592.0, 'end': 598.0, 'text': 'now the jet engines are rebuilt'}]

    def test_evidence_missing_fails_closed_and_is_skipped_under_legacy(self):
        self.assertIn('evidence-missing', codes(self.run_(self.inputs())))
        self.assertNotIn('evidence-missing', codes(self.run_(self.inputs(legacy=True, timed=self.TIMED))))

    def test_clean_beat_with_evidence_passes(self):
        issues = self.run_(self.inputs(evidence=[self.ENTRY], timed=self.TIMED))
        self.assertEqual([], [c for c in codes(issues) if c in ('evidence-missing', 'cue-mismatch', 'window-evidence-unavailable', 'subject-not-in-window', 'label-latin-not-in-window')])

    def test_cue_line_must_overlap_the_beat(self):
        # line 1 spans 390-?, line 2 400-401; beat is 399-408; line 1 ends at 392 -> no overlap
        bad = {**self.ENTRY, 'cue_line': 1}
        self.assertIn('cue-mismatch', codes(self.run_(self.inputs(evidence=[bad], timed=self.TIMED))))
        self.assertIn('cue-mismatch', codes(self.run_(self.inputs(evidence=[{**self.ENTRY, 'cue_line': 99}], timed=self.TIMED))))

    def test_window_unavailable_when_no_transcript_or_ocr(self):
        self.assertIn('window-evidence-unavailable', codes(self.run_(self.inputs(evidence=[self.ENTRY]))))

    def test_subject_must_occur_in_window_from_transcript_or_ocr_never_from_a_chapter(self):
        wrong = [{'start': 592.0, 'end': 598.0, 'text': 'the fort is shown from above'}]
        self.assertIn('subject-not-in-window', codes(self.run_(self.inputs(evidence=[self.ENTRY], timed=wrong))))
        # the two sources that can carry it
        self.assertNotIn('subject-not-in-window', codes(self.run_(self.inputs(evidence=[self.ENTRY], timed=wrong, frames={(399.0, 'yt_jet_engine'): ['Jet Engine cutaway']}))))
        self.assertNotIn('subject-not-in-window', codes(self.run_(self.inputs(evidence=[self.ENTRY], timed=self.TIMED))))
        # a chapter title is NOT evidence of what is on screen
        chapters = [{'start': 580.0, 'end': 612.0, 'title': 'Jet engines'}]
        self.assertIn('subject-not-in-window', codes(self.run_(self.inputs(evidence=[self.ENTRY], timed=wrong, chapters=chapters))))
        self.assertIn('window-evidence-unavailable', codes(self.run_(self.inputs(evidence=[self.ENTRY], chapters=chapters))))

    def test_weak_subject_terms_are_evidence_weak(self):
        timed = [{'start': 592.0, 'end': 598.0, 'text': 'the very thing that you have in 2026 with 4 jets'}]
        for terms in (['the'], ['this', 'that'], ['jet'], ['4'], ['2026'], ['4 2026'], ['with from'], ['things'], ['really'], []):
            with self.subTest(terms=terms):
                got = codes(self.run_(self.inputs(evidence=[{**self.ENTRY, 'subject_terms': terms}], timed=timed)))
                self.assertIn('evidence-weak', got)
                self.assertNotIn('subject-not-in-window', got)
        # one qualifying term is enough, and a short / stopword word inside a term does not matter
        ok = self.run_(self.inputs(evidence=[{**self.ENTRY, 'subject_terms': ['the', 'jet engines 4']}], timed=[{'start': 592.0, 'end': 598.0, 'text': 'new jet engine parts'}]))
        self.assertNotIn('evidence-weak', codes(ok))
        self.assertNotIn('subject-not-in-window', codes(ok))

    def test_stopword_list_is_the_explicit_one(self):
        th = lc.THRESHOLDS
        for w in ('this', 'that', 'with', 'from', 'have', 'will', 'very', 'about', 'there', 'their', 'which', 'would', 'could', 'should', 'these', 'those',
                  'into', 'over', 'also', 'just', 'like', 'then', 'than', 'when', 'what', 'your', 'they', 'them', 'here', 'more', 'most', 'some', 'such',
                  'only', 'really', 'going', 'thing', 'things'):
            self.assertIn(w, th['subjectStopwords'])
            self.assertEqual([], lc.qualifying_tokens(w.upper(), th))
        self.assertEqual(['engine'], lc.qualifying_tokens('Jet engine 4 the', th))
        self.assertEqual(4, th['subjectTokenMinLetters'])

    def test_seen_must_be_a_real_description(self):
        for seen in (None, '', '   ', 'engine', 'a' * 14, 5, ['x' * 20]):
            with self.subTest(seen=seen):
                entry = {**self.ENTRY, 'seen': seen}
                self.assertIn('evidence-weak', codes(self.run_(self.inputs(evidence=[entry], timed=self.TIMED))))
        entry = {**self.ENTRY, 'seen': 'x' * 15}
        self.assertNotIn('evidence-weak', codes(self.run_(self.inputs(evidence=[entry], timed=self.TIMED))))
        entry = {k: v for k, v in self.ENTRY.items() if k != 'seen'}
        self.assertIn('evidence-weak', codes(self.run_(self.inputs(evidence=[entry], timed=self.TIMED))))

    def test_with_a_frames_report_every_entry_needs_frames_in_it(self):
        inp = self.inputs(evidence=[self.ENTRY], timed=self.TIMED)
        inp.frames_given = True
        inp.frame_counts = {}                                           # report given, but it has nothing for this beat
        self.assertIn('evidence-missing', codes(self.run_(inp)))
        inp.frame_counts = {(399.0, 'yt_jet_engine'): 0}
        self.assertIn('evidence-missing', codes(self.run_(inp)))
        inp.frame_counts = {(399.0, 'yt_other'): 5}
        self.assertIn('evidence-missing', codes(self.run_(inp)))
        inp.frame_counts = {(399.0, 'yt_jet_engine'): 5}
        self.assertNotIn('evidence-missing', codes(self.run_(inp)))
        # without a frames report nothing is demanded
        self.assertNotIn('evidence-missing', codes(self.run_(self.inputs(evidence=[self.ENTRY], timed=self.TIMED))))

    def test_report_names_which_source_matched_each_word(self):
        inp = self.inputs(evidence=[{**self.ENTRY, 'subject_terms': ['jet engine']}], timed=[{'start': 592.0, 'end': 598.0, 'text': 'a jet is shown'}],
                          frames={(399.0, 'yt_jet_engine'): ['Engine cutaway']})
        issues, m = lc.lint_content(episode(self.beats(), 420), inp, {})
        self.assertNotIn('subject-not-in-window', codes(issues))
        term = m['evidence']['matches'][0]['terms'][0]
        self.assertEqual({'term': 'jet engine', 'tokens': {'engine': ['ocr']}, 'matched': True}, term)
        both = self.inputs(evidence=[self.ENTRY], timed=self.TIMED, frames={(399.0, 'yt_jet_engine'): ['JET ENGINES']})
        self.assertEqual({'engine': ['transcript', 'ocr']}, lc.lint_content(episode(self.beats(), 420), both, {})[1]['evidence']['matches'][0]['terms'][0]['tokens'])

    def test_frames_report_loader_counts_frames(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'f.json'
            p.write_text(json.dumps({'beats': [{'t': 399.0, 'src': 'yt_jet_engine', 'frames': [{'ocr': ['x']}, {'ocr': []}]}, {'t': 5, 'src': 'a', 'frames': []}]}))
            self.assertEqual({(399.0, 'yt_jet_engine'): 2, (5.0, 'a'): 0}, ed.load_frame_counts(p))

    def test_window_is_the_original_video_range_padded_three_seconds(self):
        shown = 590.0   # beat 399-408 -> original 590-599 (capped at source_out 610)
        other = {'start': 591.0, 'end': 592.0, 'text': 'something else'}
        late = [other, {'start': 603.0, 'end': 606.0, 'text': 'jet engine'}]      # starts 4 s after the shown end (599)
        near = [other, {'start': 601.5, 'end': 606.0, 'text': 'jet engine'}]      # starts 2.5 s after -> inside the +3 s pad
        self.assertIn('subject-not-in-window', codes(self.run_(self.inputs(evidence=[self.ENTRY], timed=late))))
        self.assertNotIn('subject-not-in-window', codes(self.run_(self.inputs(evidence=[self.ENTRY], timed=near))))

    def test_chapters_are_still_loadable_but_never_part_of_the_window(self):
        straddle = [{'start': 500.0, 'end': 595.0, 'title': 'Jet engine'}, {'start': 595.0, 'end': 700.0, 'title': 'Other'}]
        self.assertIn('window-evidence-unavailable', codes(self.run_(self.inputs(evidence=[self.ENTRY], chapters=straddle))))

    def test_stem_rule_plural_and_suffix_insensitive(self):
        self.assertEqual(lc.stem('engines'), lc.stem('engine'))
        self.assertEqual(lc.stem('rendering'), lc.stem('rendered'))
        self.assertEqual(lc.stem('Satellites'), lc.stem('satellite'))
        self.assertNotEqual(lc.stem('fort'), lc.stem('forest'))

    def test_legacy_derives_subject_terms_from_slug(self):
        both = [{'start': 592.0, 'end': 598.0, 'text': 'a jet engine appears'}]
        self.assertNotIn('subject-not-in-window', codes(self.run_(self.inputs(legacy=True, timed=both))))
        only_one = [{'start': 592.0, 'end': 598.0, 'text': 'a jet appears'}]       # the slug is ONE term: all its words must occur
        self.assertIn('subject-not-in-window', codes(self.run_(self.inputs(legacy=True, timed=only_one))))
        self.assertIn('subject-not-in-window', codes(self.run_(self.inputs(legacy=True, timed=[{'start': 592.0, 'end': 598.0, 'text': 'something else'}]))))
        self.assertEqual(['jet engine'], lc.slug_terms('yt_jet_engine'))
        self.assertEqual(['fort mid pass'], lc.slug_terms('yt_fort_mid_pass'))
        self.assertEqual(['gemini'], lc.slug_terms('yt_ab_gemini'))          # < 3 letters dropped
        self.assertEqual([], lc.slug_terms('yt_ab'))

    def test_subject_term_needs_all_tokens_but_any_one_term_passes(self):
        entry = {**self.ENTRY, 'subject_terms': ['jet engine', 'fort']}
        timed = [{'start': 592.0, 'end': 598.0, 'text': 'the fort and a jet'}]
        self.assertNotIn('subject-not-in-window', codes(self.run_(self.inputs(evidence=[entry], timed=timed))))   # 'fort' alone matches
        entry = {**self.ENTRY, 'subject_terms': ['jet engine']}
        self.assertIn('subject-not-in-window', codes(self.run_(self.inputs(evidence=[entry], timed=timed))))

    def test_label_latin_not_in_window(self):
        inp = self.inputs(evidence=[self.ENTRY], timed=self.TIMED, title='Gemini Is Here')
        self.assertIn('label-latin-not-in-window', codes(self.run_(inp, headline='เครื่องยนต์ Carbon')))
        # in the window (stem-insensitive), in the source title, allowlisted or < 4 letters -> fine
        for headline in ('เครื่อง Engines', 'เครื่อง Gemini', 'เครื่อง NEWS', 'เครื่อง GPU'):
            with self.subTest(headline=headline):
                self.assertNotIn('label-latin-not-in-window', codes(self.run_(inp, headline=headline)))

    def test_only_source_clip_beats_are_checked(self):
        beats = [dict(t=0, mode='full'), dict(t=5, mode='pip', media='broll', src='desk', origin='stock', layout='stage', headline='Carbon'), dict(t=50, mode='full')]
        issues = lc.lint_content(episode(beats, 60), self.inputs(), {})[0]
        self.assertFalse([c for c in codes(issues) if c in ('evidence-missing', 'subject-not-in-window', 'label-latin-not-in-window')])


class LatinSeverityTests(unittest.TestCase):
    def lint(self, **fields):
        inp = make_inputs([at_time(0, ['คำ', 'พูด'])])
        beat = {**pip(5.0, media='typo', src=None, origin=None), **fields}
        return lc.lint_content(episode([dict(t=0, mode='full'), beat, dict(t=50, mode='full')], 60), inp, {})

    def test_provenance_latin_is_always_a_warn(self):
        for fields in (dict(kicker='ZEBRA'), dict(headline='ZEBRA'), dict(sub='ZEBRA'),
                       dict(stats=[{'at': 6, 'dur': 3, 'big': 'ZEBRA', 'label': 'x'}]), dict(stats=[{'at': 6, 'dur': 3, 'label': 'ZEBRA'}]),
                       dict(cards=[{'at': 5, 'lines': ['ZEBRA']}]), dict(items=[{'at': 5, 'text': 'ZEBRA'}]),
                       dict(vs={'left': {'title': 'ZEBRA', 'badge': 'b', 'lines': ['l']}, 'right': {'title': 't', 'badge': 'b', 'lines': ['l']}, 'conclusion': 'c'}),
                       dict(lower={'at': 5, 'dur': 3, 'title': 'ZEBRA', 'sub': 's'})):
            with self.subTest(fields=list(fields)):
                issues, m = self.lint(**fields)
                self.assertEqual(['warn'], [i['severity'] for i in issues if i['code'] == 'provenance-latin'])

    def test_metric_splits_editorial_from_data_bearing(self):
        issues, m = self.lint(kicker='UNSPOKEN', items=[{'at': 5, 'text': 'ZEBRA'}])
        self.assertEqual({'editorial': 1, 'dataBearing': 1, 'warn': 2, 'error': 0}, m['latin'])

    def test_cta_and_endcard_latin_are_warns_in_the_data_bearing_count(self):
        inp = make_inputs([at_time(0, ['คำ', 'พูด'])])
        ep = ed._finish([dict(t=0, mode='full'), pip(5.0)], {'cta': 'ZEBRA', 'cta_t': 20.0, 'top': {'cta': 'ZEBRA', 'endcard': {'eyebrow': 'GIRAFFE', 'titleA': 'ok', 'titleB': 'ok', 'cta': 'x'}}}, 'test', 30.0, None)
        issues, m = lc.lint_content(ep, inp, {})
        hits = {(i['field'], i['severity']) for i in issues if i['code'] == 'provenance-latin'}
        self.assertEqual({('cta', 'warn'), ('endcard.eyebrow', 'warn')}, hits)
        self.assertEqual(2, m['latin']['dataBearing'])


class ThaiNumberTests(unittest.TestCase):
    """Scripts that spell numbers as Thai words must satisfy digit numbers on screen."""

    def test_runs(self):
        runs = lambda line: [(line[s:e], v) for s, e, v in ed.thai_number_runs(line)]
        self.assertEqual([('สิบ', '10'), ('หนึ่ง', '1')], runs('ใช้เวลาสิบวินาที ไม่ถึงหนึ่งนาที'))
        self.assertEqual([('หนึ่งหมื่นสามพัน', '13000')], runs('มีหนึ่งหมื่นสามพันบรรทัด'))
        self.assertEqual([('ยี่สิบเอ็ด', '21'), ('ห้าสิบ', '50'), ('หนึ่งร้อยยี่สิบ', '120')], runs('ยี่สิบเอ็ดคน ห้าสิบ หนึ่งร้อยยี่สิบ'))
        self.assertEqual([('สามจุดห้า', '3.5')], runs('สามจุดห้าเท่า'))
        self.assertEqual([('สี่', '4')], runs('ขั้นตอนที่สี่'))                              # ordinal marker "ที่" stripped
        # words that merely contain number syllables are not numbers; ill-formed runs are skipped
        self.assertEqual([], runs('เขาสามารถวาดสี่เหลี่ยมได้ จุดเปลี่ยน ห้างสรรพสินค้า'))
        self.assertEqual([], runs('สองสามครั้ง'))

    def inputs(self, words):
        return make_inputs([words], join='')      # real Thai scripts have no spaces inside a number

    def lint(self, inp, **fields):
        beat = pip(0.0, **fields)
        return lc.lint_content(episode([beat, dict(t=20.0, mode='full')], 30.0), inp, {})

    def test_sip_winati_matches_digit_ten_and_keeps_the_run_start_time(self):
        inp = self.inputs([('ใช้เวลา', 1.0), ('สิบ', 2.0), ('วินาที', 3.0)])
        issues, m = self.lint(inp, kicker='10 SEC', headline='ใช้เวลา 10 วินาที', stats=[{'at': 0.0, 'dur': 20.0, 'big': '10', 'label': 'x'}])
        self.assertNotIn('provenance-number', codes(issues))
        self.assertEqual(1, m['timing']['thaiNumberRunsInScript'])
        # "10 วินาที" is an anchor (unit word also follows in the script): spoken at the run's first token, 2.0
        hit = lc.lint_content(episode([pip(10.0, headline='ใช้เวลา 10 วินาที'), dict(t=20.0, mode='full')], 30.0), inp, {})[0]
        gone = [i for i in hit if i['code'] == 'card-timing-gone-before-spoken']
        self.assertEqual([], gone)       # visible 10-20, spoken at 2: whole-beat label, late is not an error
        gone = lc.lint_content(episode([pip(0.0, headline='ใช้เวลา 10 วินาที'), dict(t=1.5, mode='full'), pip(5.0)], 30.0), inp, {})[0]
        self.assertEqual([2.0], [i['spoken'] for i in gone if i['code'] == 'card-timing-gone-before-spoken'])

    def test_thirteen_thousand_in_words_matches_and_is_timed(self):
        inp = self.inputs([('เกือบ', 1.0), ('หนึ่ง', 2.0), ('หมื่น', 2.4), ('สาม', 2.8), ('พัน', 3.2), ('บรรทัด', 3.6)])
        issues, m = self.lint(inp, headline='13,000 บรรทัด')
        self.assertNotIn('provenance-number', codes(issues))
        beats = [dict(t=0, mode='full'), pip(0.5, stats=[{'at': 0.5, 'dur': 1.0, 'big': '13,000', 'label': 'x'}]), dict(t=5.0, mode='full')]
        issues, _ = lc.lint_content(episode(beats, 30.0), inp, {})
        hit = [i for i in issues if i['code'] == 'card-timing-gone-before-spoken'][0]
        self.assertEqual(2.0, hit['spoken'])                                         # time of the run's first token

    def test_thai_ordinal_in_words_satisfies_digit_ordinal(self):
        inp = self.inputs([('ขั้นตอน', 1.0), ('ที่', 2.0), ('สี่', 3.0)])
        issues, _ = self.lint(inp, kicker='ขั้นตอนที่ 4', sub='ขั้นตอนที่ 5')
        ords = [(i['field'], i['severity']) for i in issues if i['code'] == 'provenance-ordinal']
        self.assertEqual([('sub', 'error')], ords)

    def test_english_ordinal_translation_of_thai_ordinal_is_a_warn(self):
        inp = self.inputs([('ขั้นตอน', 1.0), ('ที่', 2.0), ('สี่', 3.0)])
        issues, _ = self.lint(inp, kicker='STEP 4')
        self.assertEqual([('provenance-ordinal', 'warn')], [(i['code'], i['severity']) for i in issues if i['code'] == 'provenance-ordinal'])
        issues, _ = self.lint(inp, kicker='STEP 9')
        self.assertEqual(['error'], [i['severity'] for i in issues if i['code'] == 'provenance-ordinal'])
        issues, _ = lc.lint_content(episode([pip(0.0, kicker='STEP 4'), dict(t=20.0, mode='full')], 30.0),
                                    make_inputs([at_time(0, ['say', 'Step', '4'])]), {})
        self.assertNotIn('provenance-ordinal', codes(issues))                     # said in English -> nothing

    def test_decimal_in_words(self):
        inp = self.inputs([('สาม', 1.0), ('จุด', 1.5), ('ห้า', 2.0), ('เท่า', 2.5)])
        issues, _ = self.lint(inp, headline='3.5 เท่า')
        self.assertNotIn('provenance-number', codes(issues))

    def test_cue_times_finds_a_number_spelled_in_words(self):
        clock = ed.ScriptClock(['ใช้เวลาสิบวินาที'], [{'text': t, 'start': s, 'end': None, 'line': 1} for t, s in (('ใช้เวลา', 0.0), ('สิบ', 1.0), ('วินาที', 2.0))])
        import cue_times
        kind, occ = cue_times.find(clock, '10')
        self.assertEqual([{'line': 1, 'start': 1.0, 'matched': 'สิบ'}], occ)


class ProductNameAnchorTests(unittest.TestCase):
    """A number that is part of a product/version name is not a timing anchor."""
    TH = lc.THRESHOLDS

    def anchors(self, text, inp, field='stats[0].big'):
        counts = {}
        anc, amb = lc.anchors(field, text, self.TH, inp, counts)
        return [a[0] for a in anc], amb, counts.get('product', 0)

    def inp(self, **kw):
        return make_inputs([at_time(0, ['พูด', 'ถึง', 'Opus', '5.5', 'และ', 'Opus', '5.5', 'กับ', 'Opus', '5.5'])], **kw)

    def test_name_in_source_title_or_description(self):
        inp = self.inp(meta='Gemini 4 Carbon Is Finally Here')
        self.assertEqual(([], 0, 1), self.anchors('GEMINI 4 CARBON', inp))        # left word "Gemini" + 4 -> "gemini4" in the title
        self.assertEqual(([], 0, 1), self.anchors('4 Carbon', inp))              # number + right word
        self.assertEqual((['217'], 0, 0), self.anchors('217 Carbon', inp))      # "217carbon" is not a name

    def test_name_said_three_times_in_the_script(self):
        self.assertEqual(([], 0, 1), self.anchors('OPUS 5.5', self.inp()))       # "opus5.5" x3 in the script
        inp = make_inputs([at_time(0, ['Opus', '5.5', 'และ', 'Opus', '5.5'])])  # only twice
        self.assertEqual((['5.5'], 0, 0), self.anchors('OPUS 5.5', inp))

    def test_hyphens_and_case_are_ignored(self):
        inp = self.inp(meta='GPT-Image-2.6: Faster image generation')
        self.assertEqual(([], 0, 1), self.anchors('gpt image 2.6', inp))
        self.assertEqual(([], 0, 1), self.anchors('GPT-Image-2.6', inp))

    def test_counted_in_metrics_and_no_timing_issue(self):
        inp = make_inputs([at_time(100, ['Gemini', '4', 'Carbon', 'ออก'])], meta='Gemini 4 Carbon Is Here')
        beat = pip(0.0, headline='x', **{'lower': None})
        beats = [{'t': 0, 'mode': 'full', 'lower': {'at': 1.0, 'dur': 3.0, 'title': 'GEMINI 4 CARBON', 'sub': 'รุ่นใหม่'}}, pip(10.0), dict(t=20.0, mode='full')]
        issues, m = lc.lint_content(episode(beats, 200.0), inp, {})
        self.assertEqual([], [c for c in codes(issues) if c.startswith('card-timing')])
        self.assertEqual(1, m['timing']['productNameAnchors'])


class LabelTimingTests(unittest.TestCase):
    """Whole-beat labels can only be gone-before-spoken; timed items keep early/late."""

    def inputs(self):
        return make_inputs([at_time(100, ['เกือบ', '13000', 'บรรทัด']), at_time(10, ['x'])])

    def issues(self, beats, vo=200.0):
        return [c for c in codes(lc.lint_content(episode(beats, vo), self.inputs(), {})[0]) if c.startswith('card-timing')]

    def test_label_never_late_or_early(self):
        beats = [dict(t=0, mode='full'), pip(150.0, headline='เกือบ 13,000 บรรทัด', kicker='13,000'), dict(t=190.0, mode='full')]   # spoken at ~100.5
        self.assertEqual([], self.issues(beats))
        beats = [dict(t=0, mode='full'), pip(95.0, headline='13,000 บรรทัด'), dict(t=100.0, mode='full')]
        self.assertEqual(['card-timing-gone-before-spoken'], self.issues(beats))

    def test_timed_item_still_late_and_early(self):
        late = [dict(t=0, mode='full'), pip(125.0, stats=[{'at': 125.0, 'dur': 5.0, 'big': '13,000', 'label': 'x'}]), dict(t=190.0, mode='full')]
        self.assertEqual(['card-timing-late'], self.issues(late))
        early = [dict(t=0, mode='full'), pip(90.0, stats=[{'at': 90.0, 'dur': 15.0, 'big': '13,000', 'label': 'x'}]), dict(t=190.0, mode='full')]
        self.assertEqual(['card-timing-early'], self.issues(early))

    def test_vs_and_items_without_at_are_labels(self):
        beats = [dict(t=0, mode='full'), pip(150.0, media='typo', src=None, origin=None, vs={'left': {'title': 'a', 'badge': 'b', 'lines': ['13,000 บรรทัด']},
                                                                                         'right': {'title': 'a', 'badge': 'b', 'lines': ['l']}, 'conclusion': 'c'}), dict(t=190.0, mode='full')]
        self.assertEqual([], self.issues(beats))

    def test_final_beat_texts_are_label_like(self):
        beats = [dict(t=0, mode='full'), pip(150.0, stats=[{'at': 150.0, 'dur': 5.0, 'big': '13,000', 'label': 'x'}])]
        self.assertEqual([], self.issues(beats))          # last beat: no late


class SchemaStepTests(unittest.TestCase):
    def run_cli(self, *extra, beats='episode_object.json', evidence=True, validator='schema_stub_valid.mjs', legacy=False, drop=()):
        with tempfile.TemporaryDirectory() as d:
            report = Path(d) / 'r.json'
            args = {'--beats': FIX / beats, '--script': FIX / 'script.txt', '--words': FIX / 'words_by_line.txt',
                    '--line-starts': FIX / 'line_starts.json', '--cuts': FIX / 'cuts.json',
                    '--source-transcript': FIX / 'source_transcript.txt', '--source-meta': FIX / 'source_meta.json',
                    '--source-timed': FIX / 'source_timed.json'}
            if evidence:
                args['--evidence'] = FIX / 'visual_evidence.json'
            if validator:
                args['--schema-validator'] = FIX / validator
            argv = [sys.executable, str(SCRIPTS / 'lint_content.py')]
            for k, v in args.items():
                if k not in drop:
                    argv += [k, str(v)]
            if legacy:
                argv.append('--legacy')
            proc = subprocess.run(argv + list(extra) + ['--report', str(report)], capture_output=True, text=True)
            return proc, json.loads(report.read_text()) if report.exists() else None

    def test_valid_stub_passes_and_forwards_captions(self):
        proc, rep = self.run_cli('--captions', str(FIX / 'script.txt'))
        self.assertEqual(0, proc.returncode, proc.stdout)
        self.assertTrue(rep['metrics']['schema']['ran'])
        self.assertTrue(rep['metrics']['schema']['valid'])
        self.assertEqual('stub', rep['metrics']['schema']['schemaSha256'])

    def test_validator_args_are_validate_episode_captions_json(self):
        issues, summary = lc.run_schema(FIX / 'episode_object.json', FIX / 'script.txt', FIX / 'schema_stub_valid.mjs')
        self.assertEqual([], issues)
        # the stub echoes its argv
        out = subprocess.run(['node', str(FIX / 'schema_stub_valid.mjs'), 'validate', 'e.json', '--captions', 'c.json', '--json'], capture_output=True, text=True)
        self.assertEqual(['validate', 'e.json', '--captions', 'c.json', '--json'], json.loads(out.stdout)['args'])

    def test_errors_become_schema_issues_with_path_rule_message(self):
        proc, rep = self.run_cli(validator='schema_stub_invalid.mjs')
        self.assertEqual(1, proc.returncode)
        schema = [i for i in rep['issues'] if i['code'] == 'schema']
        err = [i for i in schema if i['severity'] == 'error'][0]
        self.assertEqual(('/beats/1/from', 'S09', 'shown frames exceed loop length'), (err['path'], err['rule'], err['detail']))
        self.assertEqual(['warn'], [i['severity'] for i in schema if i['rule'] == 'S11'])
        self.assertFalse(rep['metrics']['schema']['valid'])

    def test_validator_exit_2_makes_lint_exit_2(self):
        proc, rep = self.run_cli(validator='schema_stub_exit2.mjs')
        self.assertEqual(2, proc.returncode)
        self.assertEqual('input', rep['issues'][0]['code'])

    def test_missing_validator_is_an_error_unless_legacy(self):
        proc, rep = self.run_cli(validator='does_not_exist.mjs')
        self.assertEqual(1, proc.returncode)
        self.assertIn('schema-validator-missing', [i['code'] for i in rep['issues']])
        proc, rep = self.run_cli(validator='does_not_exist.mjs', legacy=True)
        self.assertNotIn('schema-validator-missing', [i['code'] for i in rep['issues']])

    def test_evidence_missing_via_cli_unless_legacy(self):
        proc, rep = self.run_cli(evidence=False)
        self.assertEqual(1, proc.returncode)
        self.assertEqual(2, [i['code'] for i in rep['issues']].count('evidence-missing'))
        proc, rep = self.run_cli(evidence=False, legacy=True)
        self.assertNotIn('evidence-missing', [i['code'] for i in rep['issues']])


class CliTests(unittest.TestCase):
    run_cli = SchemaStepTests.run_cli

    def test_clean_v4_episode_passes_and_report_shape(self):
        proc, rep = self.run_cli()
        self.assertEqual(0, proc.returncode, proc.stdout)
        self.assertEqual(rep, json.loads(proc.stdout))
        self.assertEqual('yt-news-v4-content-lint', rep['schema'])
        self.assertEqual(1, rep['version'])
        self.assertTrue(rep['pass'])
        self.assertEqual({'issues', 'metrics', 'thresholds', 'inputs', 'schema', 'version', 'pass'}, set(rep))
        self.assertEqual(64, len(rep['inputs'][str(FIX / 'script.txt')]))
        self.assertIn('presenter', rep['metrics'])
        self.assertEqual({'editorial': 0, 'dataBearing': 0, 'warn': 0, 'error': 0}, rep['metrics']['latin'])
        self.assertEqual(0, rep['metrics']['evidence']['windowUnavailable'])

    def test_cli_crop_warning_reads_asset_dir_from_episode_file(self):
        proc, rep = self.run_cli()
        msgs = [i['detail'] for i in rep['issues'] if i['code'] == 'crop-trims-source']
        self.assertTrue(msgs)
        self.assertIn('-i remotion-composer/public/mini/broll/', msgs[0])
        self.assertTrue(all(i['severity'] == 'warn' for i in rep['issues'] if i['code'] == 'crop-trims-source'))

    def test_errors_exit_1_and_warn_alone_passes(self):
        proc, rep = self.run_cli('--set', 'maxCtaChars=3')
        self.assertEqual(1, proc.returncode)
        self.assertIn('cta-length', [i['code'] for i in rep['issues']])
        self.assertFalse(rep['pass'])

    def test_missing_and_bad_input_exit_2(self):
        proc, rep = self.run_cli(beats='nope.json')
        self.assertEqual(2, proc.returncode)
        self.assertEqual('input', rep['issues'][0]['code'])
        proc, rep = self.run_cli('--set', 'bogus=1')
        self.assertEqual(2, proc.returncode)

    def test_legacy_list_with_vo_end(self):
        proc, rep = self.run_cli('--vo-end', '30', evidence=False, legacy=True, beats='episode_list.json')
        self.assertEqual(0, proc.returncode, proc.stdout)
        self.assertEqual('json-list', rep['metrics']['episodeFormat'])
        proc, rep = self.run_cli('--vo-end', '30', evidence=False, beats='episode_list.json')     # without --legacy: not a V4 episode
        self.assertEqual(1, proc.returncode)
        self.assertIn('schema', [i['code'] for i in rep['issues']])

    def test_legacy_tsx_via_cli(self):
        proc, rep = self.run_cli(beats='episode_mini.tsx', evidence=False, legacy=True)
        self.assertEqual(0, proc.returncode, proc.stdout)
        self.assertEqual('tsx', rep['metrics']['episodeFormat'])


if __name__ == '__main__':
    unittest.main()
