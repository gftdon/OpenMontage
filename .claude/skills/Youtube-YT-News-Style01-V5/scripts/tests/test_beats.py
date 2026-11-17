"""lint_beats.py (V4): the `hold` rule only. Everything else the V3 version checked is owned by episode_schema.mjs
(see the module docstring of lint_beats.py for the rule -> schema rule table) and is tested there."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
VALID = Path(__file__).resolve().parent / 'fixtures' / 'episodes' / 'valid'
THRESHOLDS = {'maxHoldSeconds': 10, 'maxEndcardSeconds': 5}


def load_module():
    spec = importlib.util.spec_from_file_location('lint_beats', SCRIPTS / 'lint_beats.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BeatTests(unittest.TestCase):
    def lint(self, beats):
        return load_module().lint_beats(beats, THRESHOLDS)

    def codes(self, beats):
        return [x['code'] for x in self.lint(beats)]

    def beat(self, t=0, end=10, **kw):
        return {**dict(t=t, end=end, mode='pip', media='broll', src='desk', origin='stock', layout='stage'), **kw}

    def typo(self, t=0, end=10, **kw):
        return dict(t=t, end=end, mode='pip', media='typo', layout='stage', **kw)

    def clip(self, t=0, end=10, **kw):
        return self.beat(t, end, **{**dict(media='clip', src='yt_demo', origin='source'), **kw})

    def test_hold_over_limit(self):
        self.assertIn('hold', self.codes([self.beat(end=10.01)]))
        self.assertEqual([], self.lint([self.beat(end=10)]))
        self.assertIn('hold', self.codes([{**self.beat(end=12), 'src': 'ai_concept', 'origin': 'ai'}]))

    def test_stock_and_ai_broll_over_limit_is_an_error(self):
        for extra in [{}, {'src': 'ai_concept', 'origin': 'ai'}]:
            issues = self.lint([self.beat(end=11, **extra)])
            self.assertEqual([('hold', 'error')], [(x['code'], x['severity']) for x in issues], extra)

    def test_source_clip_run_is_not_a_hold_error(self):
        self.assertEqual([], self.lint([self.clip(end=24)]))  # the 10 s limit for clips is measured from frames (frame_checks static-hold)
        self.assertEqual([], self.lint([self.clip(end=30)]))  # exactly the layout-run limit: no warning

    def test_source_clip_layout_run_over_30s_warns(self):
        issues = self.lint([self.clip(end=31)])
        self.assertEqual([('hold-layout', 'warn')], [(x['code'], x['severity']) for x in issues])
        self.assertEqual(0, issues[0]['t'])
        # a run accumulates across consecutive beats of the same src and layout
        self.assertEqual(['hold-layout'], self.codes([self.clip(end=16), self.clip(t=16, end=32, **{'from': 16})]))
        # ... and a different layout (or src) starts a new run
        self.assertEqual([], self.lint([self.clip(end=16), self.clip(t=16, end=32, layout='wide')]))
        self.assertEqual(30, load_module().CLIP_LAYOUT_RUN_WARN_SECONDS)

    def test_runs_content(self):
        beats = [dict(t=0, end=3, mode='full'), self.clip(t=3, end=9), self.clip(t=9, end=15, **{'from': 6}),
                 self.beat(t=15, end=18, src='street'), self.typo(t=18, end=24, typo='card', cards=[{'at': 18, 'lines': ['a']}, {'at': 21, 'lines': ['b']}]),
                 dict(t=24, end=26, mode='full')]
        runs = load_module().lint_report(beats, THRESHOLDS)['runs']
        self.assertEqual([
            {'t': 3, 'end': 15, 'seconds': 12, 'kind': 'clip', 'src': 'yt_demo', 'layout': 'stage'},
            {'t': 15, 'end': 18, 'seconds': 3, 'kind': 'broll', 'src': 'street', 'layout': 'stage'},
            {'t': 18, 'end': 21, 'seconds': 3, 'kind': 'typo', 'src': None, 'layout': 'stage'},
            {'t': 21, 'end': 24, 'seconds': 3, 'kind': 'typo', 'src': None, 'layout': 'stage'},
        ], runs)

    def test_issue_shape_and_start_time(self):
        issues = self.lint([self.beat(t=3, end=15)])
        self.assertEqual(1, len(issues))
        self.assertEqual({'code', 't', 'detail', 'severity'}, set(issues[0]))
        self.assertEqual(('hold', 3), (issues[0]['code'], issues[0]['t']))

    def test_adjacent_identical_cannot_evade_hold(self):
        beats = [self.beat(end=6), self.beat(t=6, end=12)]
        issues = self.lint(beats)
        self.assertEqual(['hold'], [x['code'] for x in issues])  # reported once, not once per beat
        self.assertEqual(0, issues[0]['t'])

    def test_other_src_or_layout_or_media_resets(self):
        for other in [{'src': 'street'}, {'layout': 'wide'}, {'media': 'clip', 'origin': 'source'}]:
            self.assertEqual([], self.lint([self.beat(end=8), {**self.beat(t=8, end=16), **other}]), other)

    def test_full_beat_is_not_held_and_resets_the_tracker(self):
        # presenter-only run length belongs to lint_content `presenter-run`, not to this rule
        self.assertEqual([], self.lint([dict(t=0, end=40, mode='full')]))
        beats = [self.beat(end=6), dict(t=6, end=8, mode='full'), self.beat(t=8, end=14)]
        self.assertEqual([], self.lint(beats))
        # ... but the pip hold before the full beat is still checked up to the full beat
        self.assertIn('hold', self.codes([self.beat(end=11), dict(t=11, end=13, mode='full')]))

    def test_typo_cards_reset_only_on_real_content_change(self):
        b = self.typo(end=18, typo='card', cards=[{'at': 0, 'lines': ['Flare']}, {'at': 9, 'lines': ['Sunburst']}])
        self.assertEqual([], self.lint([b]))
        b['cards'][1]['lines'] = ['Flare']
        self.assertIn('hold', self.codes([b]))

    def test_typo_items_each_reveal_is_a_change(self):
        items = [{'at': 0, 'text': 'a'}, {'at': 6, 'text': 'b'}, {'at': 12, 'text': 'c'}]
        self.assertEqual([], self.lint([self.typo(end=18, typo='summary3', items=items)]))
        self.assertIn('hold', self.codes([self.typo(end=18, typo='summary3', items=[{'at': 15, 'text': 'a'}, {'at': 16, 'text': 'b'}, {'at': 17, 'text': 'c'}])]))

    def test_unchanged_typography_holds(self):
        self.assertIn('hold', self.codes([self.typo(end=11, typo='card', cards=[{'at': 0, 'lines': ['x']}])]))

    def test_overlays_never_reset_a_hold(self):
        overlays = [
            {'headline': 'B', 'sub': 'two', 'kicker': 'new'},
            {'stats': [{'at': 9.9, 'dur': 1, 'label': 'flash'}]},
        ]
        for extra in overlays:
            beats = [{**self.beat(end=8), 'headline': 'A', 'stats': [{'at': 1, 'dur': 2, 'label': 'one'}]}, {**self.beat(t=8, end=16), **extra}]
            self.assertIn('hold', self.codes(beats), extra)

    def test_holds_helper_reports_longest_run(self):
        runs = load_module().holds([self.beat(end=6), self.beat(t=6, end=12), self.beat(t=12, end=13, src='street')])
        self.assertEqual([12, 1], [round(r['seconds'], 6) for r in runs])


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-B', str(SCRIPTS / 'lint_beats.py'), *map(str, args)], capture_output=True, text=True)

    def episode(self, d, end, **beat):
        data = json.loads((VALID / 'min-3-beat.json').read_text())
        data['beats'][1] = {**data['beats'][1], 'mode': 'pip', 'media': 'broll', 'layout': 'stage', 'src': 'desk', 'origin': 'stock', 'headline': 'H', **beat}
        data['beats'][2]['t'] = end - 10
        data['voEndSec'] = end
        data['totalDurationSec'] = end + 4
        p = Path(d) / 'episode.json'
        p.write_text(json.dumps(data))
        return p

    def test_valid_sample_runs_and_report_shape(self):
        with tempfile.TemporaryDirectory() as d:
            report = Path(d) / 'beats.json'
            r = self.run_cli(VALID / 'sample-v1.json', '--report', report)
            self.assertIn(r.returncode, (0, 1), r.stderr)
            written = json.loads(report.read_text())
            self.assertEqual({'pass', 'issues', 'beats', 'warnings', 'runs'}, set(written))
            self.assertEqual(written, json.loads(r.stdout))
            self.assertEqual(56, written['beats'])

    def test_negative_cli_hold_exits_one(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.episode(d, 40)
            r = self.run_cli(p)
            self.assertEqual(1, r.returncode, r.stderr)
            out = json.loads(r.stdout)
            self.assertFalse(out['pass'])
            self.assertEqual({'hold'}, {i['code'] for i in out['issues']})

    def test_cli_source_clip_runs(self):
        clip = dict(media='clip', src='yt_demo', origin='source')
        with tempfile.TemporaryDirectory() as d:
            r = self.run_cli(self.episode(d, 37, **clip))  # 24 s clip run: pass, nothing to say
            self.assertEqual(0, r.returncode, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual((True, [], 0), (out['pass'], out['issues'], out['warnings']))
            self.assertEqual([(3, 24, 'clip')], [(x['t'], x['seconds'], x['kind']) for x in out['runs']])
            r = self.run_cli(self.episode(d, 44, **clip))  # 31 s: pass with one warning, exit 0
            self.assertEqual(0, r.returncode, r.stderr)
            out = json.loads(r.stdout)
            self.assertTrue(out['pass'])
            self.assertEqual(1, out['warnings'])
            self.assertEqual([('hold-layout', 'warn')], [(i['code'], i['severity']) for i in out['issues']])

    def test_cli_stock_ai_and_typo_over_limit_exit_one(self):
        cases = {'stock': {}, 'ai': dict(src='ai_concept', origin='ai'),
                 'typo': dict(media='typo', typo='card', cards=[{'at': 3, 'lines': ['x']}], src=None, origin=None, layout='stage')}
        for name, beat in cases.items():
            with tempfile.TemporaryDirectory() as d:
                p = self.episode(d, 21, **beat)  # an 11 s run
                data = json.loads(p.read_text())
                data['beats'][2]['t'] = 14
                for key in [k for k, v in data['beats'][1].items() if v is None]:
                    del data['beats'][1][key]
                p.write_text(json.dumps(data))
                r = self.run_cli(p)
                self.assertEqual(1, r.returncode, (name, r.stdout))
                out = json.loads(r.stdout)
                self.assertFalse(out['pass'], name)
                self.assertEqual([('hold', 'error')], [(i['code'], i['severity']) for i in out['issues']], name)

    def test_unreadable_or_legacy_input_exits_two(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / 'bad.json'
            bad.write_text('{not json')
            self.assertEqual(2, self.run_cli(bad).returncode)
            self.assertEqual(2, self.run_cli(Path(d) / 'missing.json').returncode)
            empty = Path(d) / 'empty.json'
            empty.write_text('{"beats": []}')
            r = self.run_cli(empty)
            self.assertEqual(2, r.returncode)
            self.assertEqual('parse', json.loads(r.stdout)['issues'][0]['code'])


if __name__ == '__main__':
    unittest.main()
