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


def make_inputs(lines, source='', source_all=None, cuts=None, relevance=None, relevance_given=None):
    """lines: [[(word, start_time), ...], ...]; each script line is its words joined by spaces."""
    script, tokens, starts = [], [], []
    for n, words in enumerate(lines, 1):
        script.append(' '.join(w for w, _ in words))
        for w, t in words:
            tokens.append({'text': w, 'start': t, 'end': None, 'line': n})
        starts.append({'line': n, 'start': words[0][1], 'end': words[-1][1] + 1.0, 'text': script[-1]})
    return lc.Inputs(script, tokens, starts, cuts or {}, {'numbers': source, 'all': source_all if source_all is not None else source},
                     relevance, relevance_given if relevance_given is not None else relevance is not None)


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
        issues = self.lint('เป้า 8/10')
        self.assertIn('provenance-number', codes(issues, 'error'))

    def test_fraction_passes_via_source_within_40_chars(self):
        self.assertNotIn('provenance-number', codes(self.lint('เป้า 8/10', source='a score of 8 out of 10 overall')))

    def test_number_commas_thai_digits_and_missing(self):
        self.assertNotIn('provenance-number', codes(self.lint('13,000 บรรทัด')))
        self.assertNotIn('provenance-number', codes(self.lint('๑๓,๐๐๐ บรรทัด')))
        self.assertIn('provenance-number', codes(self.lint('500,000 บรรทัด')))

    def test_number_boundary_five_is_not_inside_fifteen(self):
        self.assertIn('provenance-number', codes(self.lint('5 บรรทัด')))

    def test_number_found_only_in_source_passes(self):
        self.assertIn('provenance-number', codes(self.lint('217 คะแนน')))
        self.assertNotIn('provenance-number', codes(self.lint('217 คะแนน', source='scores 217 per game')))

    def test_number_outside_beat_window_not_accepted(self):
        far = make_inputs([at_time(0, ['a', '1']), at_time(10, ['b']), at_time(20, ['c']), at_time(30, ['d', '77'])])
        beat = pip(0, headline='77')
        issues, _ = lc.lint_content(episode([beat, dict(t=8, mode='full')], 100), far, {})
        self.assertIn('provenance-number', codes(issues))

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


class TimingFarTests(unittest.TestCase):
    def test_lone_number_spoken_far_away_is_left_to_provenance_unless_cap_is_lifted(self):
        inp = make_inputs([at_time(0, ['a']), at_time(300, ['ใช้', '3', 'ครั้ง'])], source='3D demo')
        beats = [dict(t=0, mode='full'), pip(50.0, headline='3 มิติ'), dict(t=60.0, mode='full')]
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


class PresenterTests(unittest.TestCase):
    def pr(self, spans, vo=100.0, **th):
        """spans: list of (t, has_media). Returns (issues, metrics['presenter'])."""
        beats = [pip(t) if media else dict(t=t, mode='full') for t, media in spans]
        inp = make_inputs([at_time(0, ['x'])])
        issues, m = run(beats, inp, vo, **th)
        return [i for i in issues if i['code'].startswith('presenter')], m['presenter']

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
        self.assertEqual([15.0], [r['seconds'] for r in p['runsAtLeastReportMin']])

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
        self.assertEqual(1, len(p['runsAtLeastReportMin']))

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

    def typo(self, **kw):
        return [dict(t=0, mode='full'), dict(t=5, mode='pip', media='typo', src='typo_a', origin='stock', layout='stage', chrome=False, **kw), dict(t=50, mode='full')]

    def test_typo_without_kind_fails_with_kind_and_items_passes(self):
        self.assertIn('typo-kind', codes(self.lint(self.typo(items=['a']))))
        self.assertIn('typo-kind', codes(self.lint(self.typo(cardKind='summary3'))))   # no items
        self.assertIn('typo-kind', codes(self.lint(self.typo(cardKind='weird', items=['a']))))
        self.assertNotIn('typo-kind', codes(self.lint(self.typo(cardKind='summary3', items=['a']))))

    def test_typo_kind_adapter_accepts_card_and_typo_paths_and_dict_items(self):
        self.assertNotIn('typo-kind', codes(self.lint(self.typo(card={'kind': 'vs', 'items': [{'text': 'a'}]}))))
        self.assertNotIn('typo-kind', codes(self.lint(self.typo(typo={'kind': 'final4', 'items': ['a', 'b']}))))

    def test_typo_kind_can_be_disabled_for_legacy_data(self):
        self.assertNotIn('typo-kind', codes(self.lint(self.typo(items=['a']), requireTypoKind=False)))
        self.assertNotIn('typo-kind', codes(self.lint(self.typo(), requireTypoKind=False)))

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


class LoaderTests(unittest.TestCase):
    def test_object_json_with_at_dur_is_primary(self):
        ep = ed.load_episode(FIX / 'episode_object.json')
        self.assertEqual('json-object', ep['format'])
        self.assertEqual(30.0, ep['vo_end'])
        self.assertEqual(4.5, ep['end_card_seconds'])
        self.assertEqual(['ติดตามช่องไว้นะ'], [ed.episode_cta(ep)])
        self.assertEqual([0, 5, 12, 20, 28], [b['t'] for b in ep['beats']])
        self.assertEqual([5, 12, 20, 28, 30], [b['end'] for b in ep['beats']])
        self.assertEqual({'x': 0, 'y': 0, 'w': 1280, 'h': 720}, ep['beats'][1]['srcCrop'])  # passed through
        self.assertEqual(4, ep['beats'][3]['from'])
        fields = {f[0]: f for f in ed.text_fields(ep['beats'][3])}
        self.assertEqual((21.0, 25.0, 'timed'), fields['stats[0].big'][2:])      # at/dur window, not cut at beat end
        self.assertEqual((20, 28, 'beat'), fields['headline'][2:])
        typo = {f[0]: f for f in ed.text_fields(ep['beats'][2])}
        self.assertEqual((12, 20, 'beat'), typo['items[0]'][2:])
        self.assertEqual((17.5, 20.5, 'timed'), typo['items[1]'][2:])
        self.assertEqual({'kind': 'summary3', 'items': ep['beats'][2]['items']}, ed.typo_card(ep['beats'][2]))

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


class CliTests(unittest.TestCase):
    def run_cli(self, *extra, beats='episode_object.json', drop=()):
        with tempfile.TemporaryDirectory() as d:
            report = Path(d) / 'r.json'
            args = {'--beats': FIX / beats, '--script': FIX / 'script.txt', '--words': FIX / 'words_by_line.txt',
                    '--line-starts': FIX / 'line_starts.json', '--cuts': FIX / 'cuts.json',
                    '--source-transcript': FIX / 'source_transcript.txt', '--source-meta': FIX / 'source_meta.json'}
            argv = [sys.executable, str(SCRIPTS / 'lint_content.py')]
            for k, v in args.items():
                if k not in drop:
                    argv += [k, str(v)]
            proc = subprocess.run(argv + list(extra) + ['--report', str(report)], capture_output=True, text=True)
            return proc, json.loads(report.read_text()) if report.exists() else None

    def test_clean_episode_passes_and_report_shape(self):
        proc, rep = self.run_cli()
        self.assertEqual(0, proc.returncode, proc.stdout)
        self.assertEqual(rep, json.loads(proc.stdout))
        self.assertEqual('yt-news-v4-content-lint', rep['schema'])
        self.assertEqual(1, rep['version'])
        self.assertTrue(rep['pass'])
        self.assertEqual({'issues', 'metrics', 'thresholds', 'inputs', 'schema', 'version', 'pass'}, set(rep))
        self.assertEqual(64, len(rep['inputs'][str(FIX / 'script.txt')]))
        self.assertIn('presenter', rep['metrics'])

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
        proc, rep = self.run_cli('--vo-end', '30', '--legacy', beats='episode_list.json')
        self.assertEqual(0, proc.returncode, proc.stdout)
        proc, rep = self.run_cli('--vo-end', '30', beats='episode_list.json')
        self.assertEqual(1, proc.returncode)
        self.assertIn('typo-kind', [i['code'] for i in rep['issues']])

    def test_tsx_via_cli(self):
        proc, rep = self.run_cli(beats='episode_mini.tsx')
        self.assertEqual(0, proc.returncode, proc.stdout)
        self.assertEqual('tsx', rep['metrics']['episodeFormat'])


if __name__ == '__main__':
    unittest.main()
