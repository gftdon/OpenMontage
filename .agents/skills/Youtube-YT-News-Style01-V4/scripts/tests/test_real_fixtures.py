"""Our loader and our schema step against the engine team's REAL V4 fixtures (CF-A67).

The fixtures under fixtures/episodes/ (valid/, invalid/, captions/) belong to the engine workstream and are read-only here.
fixtures/a67/content/v261111_v4_episode.json is a snapshot of the hand-annotated V4 episode of the news video V261111.
"""
import collections
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
FX = Path(__file__).resolve().parent / 'fixtures'
EP_FX = FX / 'episodes'
V261111 = FX / 'a67' / 'content' / 'v261111_v4_episode.json'
SCHEMA_JSON = SCRIPTS.parent / 'assets' / 'episode.schema.json'
sys.path.insert(0, str(SCRIPTS))
import episode_data as ed  # noqa: E402
import lint_content as lc  # noqa: E402

VALIDATOR = SCRIPTS / 'episode_schema.mjs'
HAVE_NODE = shutil.which('node') is not None
NO_NODE = 'node is not installed: the real episode_schema.mjs cannot run'


def captions_for_valid(name):
    # same mapping as the engine's own test (episode_schema.test.mjs): sample-v1 has its own captions, the rest share the minimal one
    return EP_FX / 'captions' / ('sample-captions.json' if name == 'sample-v1.json' else 'min-captions.json')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def schema_step(episode, captions):
    """The lint's own schema step (lint_content.run_schema with the default validator)."""
    return lc.run_schema(episode, captions, VALIDATOR)


@unittest.skipUnless(HAVE_NODE, NO_NODE)
class ValidFixtures(unittest.TestCase):
    def test_every_valid_fixture_loads_and_passes_the_schema_step(self):
        files = sorted((EP_FX / 'valid').glob('*.json'))
        self.assertGreaterEqual(len(files), 4)
        for f in files:
            with self.subTest(f.name):
                ep = ed.load_episode(f)                      # no EpisodeFormatError
                self.assertEqual('json-object', ep['format'])
                self.assertEqual(len(read(f)['beats']), len(ep['beats']))
                issues, summary = schema_step(f, captions_for_valid(f.name))
                self.assertEqual([], [i for i in issues if i['severity'] == 'error'], issues)
                self.assertTrue(summary['valid'])

    def test_missing_captions_are_only_a_warning(self):
        f = EP_FX / 'valid' / 'min-3-beat.json'
        issues, summary = schema_step(f, None)
        self.assertTrue(summary['valid'])
        self.assertEqual([], [i for i in issues if i['severity'] == 'error'])
        self.assertTrue(any(i['severity'] == 'warn' and i['rule'] == 'S19' for i in issues))

    def test_v261111_snapshot_loads(self):
        ep = ed.load_episode(V261111)
        self.assertEqual(78, len(ep['beats']))
        self.assertAlmostEqual(647.32, ep['vo_end'])
        self.assertAlmostEqual(637.7, ep['cta_t'])


@unittest.skipUnless(HAVE_NODE, NO_NODE)
class InvalidFixtures(unittest.TestCase):
    def test_every_invalid_fixture_is_a_schema_issue_with_the_expected_rule(self):
        files = sorted((EP_FX / 'invalid').glob('*.json'))
        self.assertGreaterEqual(len(files), 80)
        with tempfile.TemporaryDirectory() as tmp:
            for f in files:
                with self.subTest(f.name):
                    text = f.read_text(encoding='utf-8')
                    expect = json.loads(text)['_expect']
                    self.assertIn('rule', expect)
                    # The hint is not part of the format (additionalProperties would hide the rule). Strip it from the TEXT, never
                    # re-serialise: non-finite-t.json carries a literal 1e999 that json.dumps would turn into invalid `Infinity`.
                    body, n = re.subn(r'^  "_expect": \{.*?^  \},\n', '', text, count=1, flags=re.S | re.M)
                    self.assertEqual(1, n)
                    copy = Path(tmp) / f.name
                    copy.write_text(body, encoding='utf-8')
                    captions = EP_FX / 'captions' / expect.get('captions', 'min-captions.json')
                    issues, summary = schema_step(copy, captions)
                    schema_errors = [i for i in issues if i['code'] == 'schema' and i['severity'] == 'error']
                    self.assertTrue(schema_errors, 'no schema error reported')
                    self.assertFalse(summary['valid'])
                    self.assertIn(expect['rule'], {i['rule'] for i in schema_errors}, [(i['rule'], i['path']) for i in schema_errors])
                    self.assertIn(expect['path'], {i['path'] for i in schema_errors if i['rule'] == expect['rule']})


@unittest.skipUnless(HAVE_NODE, NO_NODE)
class DefaultValidator(unittest.TestCase):
    """lint_content.py without --schema-validator uses the real episode_schema.mjs next to it and forwards --captions."""
    CONTENT = FX / 'a67' / 'content'

    def run_cli(self, episode, *extra):
        with tempfile.TemporaryDirectory() as d:
            report = Path(d) / 'r.json'
            argv = [sys.executable, str(SCRIPTS / 'lint_content.py'), '--beats', str(episode), '--script', str(self.CONTENT / 'script.txt'),
                    '--words', str(self.CONTENT / 'words_by_line.txt'), '--line-starts', str(self.CONTENT / 'line_starts.json'),
                    '--cuts', str(self.CONTENT / 'cuts.json'), '--report', str(report), *extra]
            proc = subprocess.run(argv, capture_output=True, text=True)
            return proc, json.loads(report.read_text())

    def test_default_is_the_real_validator_and_captions_are_forwarded(self):
        ep = EP_FX / 'valid' / 'min-3-beat.json'
        proc, rep = self.run_cli(ep, '--captions', str(EP_FX / 'captions' / 'bad-chunk-times.json'))
        self.assertIn(str(VALIDATOR), rep['inputs'])
        self.assertTrue(rep['metrics']['schema']['ran'])
        self.assertEqual(64, len(rep['metrics']['schema']['schemaSha256']))
        rules = {(i['rule'], i['path']) for i in rep['issues'] if i['code'] == 'schema' and i['severity'] == 'error'}
        self.assertTrue(any(r == 'S19' and p.startswith('/$captions') for r, p in rules), rules)   # captions reached the validator
        self.assertNotEqual(0, proc.returncode)

    def test_valid_episode_has_no_schema_issue(self):
        proc, rep = self.run_cli(EP_FX / 'valid' / 'min-3-beat.json', '--captions', str(EP_FX / 'captions' / 'min-captions.json'))
        self.assertEqual([], [i for i in rep['issues'] if i['code'] in ('schema', 'schema-validator-missing') and i['severity'] == 'error'])
        self.assertTrue(rep['metrics']['schema']['valid'])


# ----------------------- 2c / 2d: the loader covers every on-screen text field -------------------------------------

BEAT_NON_TEXT = {'mode', 'media', 'layout', 'src', 'origin', 'typo', 'tone', 'icon'}      # enums / ids / glyphs, not text
TOP_NON_TEXT = {'schema', 'assetDir', 'avatarFile', 'captionsInputSha256'}


def string_leaves(obj, skip, key=None):
    """Every string leaf (as text) under obj, ignoring dict keys listed in `skip`."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k not in skip:
                yield from string_leaves(v, skip, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from string_leaves(v, skip)


def schema_text_keys():
    """Keys that the SCHEMA types as on-screen text ($defs/text), independent of the sample data."""
    sc = read(SCHEMA_JSON)
    found = set()

    def walk(node, name):
        if isinstance(node, dict):
            if node.get('$ref') == '#/$defs/text':
                found.add(name)
            for k, v in node.items():
                walk(v, k if k not in ('properties', 'items', 'additionalProperties') else name)
    walk(sc, '')
    return found


class LoaderCoversEveryTextField(unittest.TestCase):
    def episodes(self):
        out = [('sample-v1', EP_FX / 'valid' / 'sample-v1.json'), ('variants-and-carryover', EP_FX / 'valid' / 'variants-and-carryover.json')]
        if V261111.exists():
            out.append(('v261111', V261111))
        return out

    def test_schema_text_keys_are_the_ones_this_test_knows(self):
        # a new `$defs/text` field in the schema must be added to the loader and to this list on purpose
        self.assertEqual({'badge', 'big', 'brand', 'breakingLabel', 'conclusion', 'cta', 'dateLabel', 'eyebrow', 'headline', 'kicker', 'label',
                          'lines', 'officialTag', 'sub', 'text', 'title', 'titleA', 'titleB'}, schema_text_keys())

    def test_beat_text_is_returned_by_text_fields_and_beat_items(self):
        for name, f in self.episodes():
            ep = ed.load_episode(f)
            raw_beats = read(f)['beats']
            n_text = 0
            for i, (b, raw) in enumerate(zip(ep['beats'], raw_beats)):
                with self.subTest('%s beat %d' % (name, i)):
                    want = collections.Counter(s.strip() for s in string_leaves(raw, BEAT_NON_TEXT | {'t'}))
                    got = collections.Counter(txt for _, txt, _, _, _ in ed.text_fields(b))
                    self.assertEqual(want, got)
                    n_text += sum(want.values())
                    if raw.get('items'):                       # beat_items: the typography items of summary3 / final4
                        self.assertEqual([x['text'] for x in raw['items']], [ed._item_text(x) for x in ed.beat_items(b)])
            self.assertGreater(n_text, 20, name)

    def test_top_level_text_is_returned_by_episode_text_fields(self):
        for name, f in self.episodes():
            with self.subTest(name):
                ep = ed.load_episode(f)
                raw = read(f)
                want = collections.Counter(s.strip() for k, v in raw.items() if k not in TOP_NON_TEXT | {'beats'} and k != 'brollDur'
                                           for s in string_leaves(v, set()))
                got = collections.Counter(txt for _, txt, _, _, _ in ed.episode_text_fields(ep))
                self.assertEqual(want, got)
                self.assertEqual(raw['cta'], ed.episode_cta(ep))

    def test_every_field_kind_occurs_in_the_samples(self):
        """Guards the guard: the samples really contain every text-bearing field family."""
        seen = set()
        for _, f in self.episodes():
            ep = ed.load_episode(f)
            for b in ep['beats']:
                for fld, _, _, _, _ in ed.text_fields(b):
                    seen.add(fld.split('.')[0].split('[')[0] if not fld.startswith(('lower.', 'vs.')) else fld.split('.')[0])
        self.assertTrue({'kicker', 'headline', 'sub', 'stats', 'cards', 'items', 'vs', 'lower'} <= seen, seen)


class LoaderWindowsMatchSchemaSemantics(unittest.TestCase):
    """Windows of timed text vs. episode_schema.mjs S13 (stat [at, at+dur)), S14 (cards / items) and S15 (lower [at, at+dur))."""

    def check(self, f):
        ep = ed.load_episode(f)
        raw = read(f)['beats']
        checked = collections.Counter()
        for i, (b, rb) in enumerate(zip(ep['beats'], raw)):
            end = ep['beats'][i + 1]['t'] if i + 1 < len(raw) else ep['vo_end']
            tf = {fld: (s, e, k) for fld, _, s, e, k in ed.text_fields(b)}
            for j, st in enumerate(rb.get('stats', [])):
                for k in ('big', 'label'):
                    if k in st:
                        s, e, kind = tf['stats[%d].%s' % (j, k)]
                        self.assertAlmostEqual(st['at'], s, places=6)
                        self.assertAlmostEqual(st['at'] + st['dur'], e, places=6)       # NOT cut at the beat end (carry-over allowed)
                        self.assertEqual('timed', kind)
                        checked['stats'] += 1
            for j, c in enumerate(rb.get('cards', [])):
                nxt = rb['cards'][j + 1]['at'] if j + 1 < len(rb['cards']) else end
                for m in range(len(c['lines'])):
                    s, e, kind = tf['cards[%d].lines[%d]' % (j, m)]
                    self.assertAlmostEqual(c['at'], s, places=6)
                    self.assertAlmostEqual(nxt, e, places=6)
                    checked['cards'] += 1
            for j, it in enumerate(rb.get('items', [])):
                s, e, kind = tf['items[%d]' % j]
                self.assertAlmostEqual(it['at'], s, places=6)
                self.assertAlmostEqual(end, e, places=6)                   # S14: item at lies inside [t, end), shown to the beat end
                checked['items'] += 1
            lo = rb.get('lower')
            if lo:
                for k in ('title', 'sub'):
                    s, e, kind = tf['lower.' + k]
                    self.assertAlmostEqual(lo['at'], s, places=6)
                    self.assertAlmostEqual(lo['at'] + lo['dur'], e, places=6)
                    checked['lower'] += 1
            for fld in ('kicker', 'headline', 'sub'):
                if fld in rb:
                    s, e, kind = tf[fld]
                    self.assertAlmostEqual(rb['t'], s, places=6)
                    self.assertAlmostEqual(end, e, places=6)
                    checked['beat-text'] += 1
        return checked

    def test_sample_v1(self):
        c = self.check(EP_FX / 'valid' / 'sample-v1.json')
        for k in ('stats', 'cards', 'items', 'lower', 'beat-text'):
            self.assertGreater(c[k], 0, k)

    def test_variants_and_carryover(self):
        c = self.check(EP_FX / 'valid' / 'variants-and-carryover.json')
        self.assertGreater(c['stats'], 0)

    def test_v261111(self):
        c = self.check(V261111)
        for k in ('stats', 'cards', 'items', 'lower'):
            self.assertGreater(c[k], 0, k)

    def test_top_level_windows(self):
        f = V261111
        ep = ed.load_episode(f)
        raw = read(f)
        got = {fld: (s, e, k) for fld, _, s, e, k in ed.episode_text_fields(ep)}
        self.assertEqual((raw['ctaT'], raw['voEndSec'], 'timed'), got['cta'])
        self.assertEqual((raw['voEndSec'], raw['totalDurationSec'], 'beat'), got['endcard.titleA'])
        self.assertEqual((0.0, raw['voEndSec'], 'chrome'), got['brand'])


class VisibleRegionTests(unittest.TestCase):
    """episode_data.visible_region is the single implementation; it must agree with score_relevance.visible_region (same engine
    srcCropStyle formula) on a grid. Importing score_relevance is offline and has no side effects, so the real function is compared."""
    CROPS = [None, {'x': 0, 'y': 0, 'w': 1920, 'h': 1080}, {'x': 100, 'y': 140, 'w': 1529, 'h': 860}, {'x': 120, 'y': 136, 'w': 1678, 'h': 944},
             {'x': 142, 'y': 136, 'w': 1678, 'h': 944}, {'x': 100, 'y': 212, 'w': 1404, 'h': 790}, {'x': 1280, 'y': 720, 'w': 640, 'h': 360},
             {'x': 0, 'y': 0, 'w': 640, 'h': 1080}, {'x': 10, 'y': 20, 'w': 1900, 'h': 400}]

    def test_agrees_with_score_relevance_on_a_grid(self):
        import score_relevance as sr
        n = 0
        for layout, box in sr.PICTURE_BOX.items():
            self.assertEqual(box, ed.PICTURE_BOX[layout])
            for crop in self.CROPS:
                want = sr.visible_region(crop, box)
                got = ed.visible_region(layout, 1920, 1080, crop)
                for k, v in zip('xywh', got):
                    self.assertAlmostEqual(want[k], v, places=6, msg=(layout, crop, k))
                n += 1
        self.assertGreaterEqual(n, 18)

    def test_picture_boxes_are_read_from_the_engine_lanes_file(self):
        lanes = read(SCRIPTS.parent / 'assets' / 'yt-news-v4-lanes.json')
        for layout, scene in (('stage', 'S'), ('wide', 'W')):
            lane = lanes['lanes'][lanes['pictureLaneByScene'][scene]]
            self.assertEqual((lane['w'], lane['h']), tuple(ed.PICTURE_BOX[layout]))
        self.assertEqual((1138, 640), tuple(ed.PICTURE_BOX['stage']))          # today's values
        self.assertEqual((1280, 720), tuple(ed.PICTURE_BOX['wide']))
        self.assertEqual({'stage', 'wide'}, set(ed.PICTURE_BOX))
        self.assertIn('stage', ed.PICTURE_BOX)
        self.assertNotIn('flat', ed.PICTURE_BOX)
        self.assertIsNone(ed.PICTURE_BOX.get('flat'))

    def with_lanes(self, content):
        """Run a block with episode_data.LANES_PATH pointing at a temp file holding `content` (None = missing file)."""
        import contextlib

        @contextlib.contextmanager
        def cm():
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / 'lanes.json'
                if content is not None:
                    p.write_text(content if isinstance(content, str) else json.dumps(content), encoding='utf-8')
                old = ed.LANES_PATH
                ed.LANES_PATH = p
                try:
                    yield
                finally:
                    ed.LANES_PATH = old
        return cm()

    def test_a_broken_lanes_file_fails_closed(self):
        good = read(SCRIPTS.parent / 'assets' / 'yt-news-v4-lanes.json')

        def mutate(fn):
            d = json.loads(json.dumps(good))
            fn(d)
            return d
        broken = {
            'not json': 'nope {',
            'not an object': '[]',
            'wrong schema': mutate(lambda d: d.update(schema='other')),
            'wrong version': mutate(lambda d: d.update(version=2)),
            'no lanes': mutate(lambda d: d.pop('lanes')),
            'no pictureLaneByScene': mutate(lambda d: d.pop('pictureLaneByScene')),
            'S missing': mutate(lambda d: d['pictureLaneByScene'].pop('S')),
            'S is null': mutate(lambda d: d['pictureLaneByScene'].update(S=None)),
            'W names an unknown lane': mutate(lambda d: d['pictureLaneByScene'].update(W='nope')),
            'W lane has no h': mutate(lambda d: d['lanes']['wide.picture'].pop('h')),
            'S lane width 0': mutate(lambda d: d['lanes']['split.picture'].update(w=0)),
            'S lane width a string': mutate(lambda d: d['lanes']['split.picture'].update(w='1138')),
            'S lane width negative': mutate(lambda d: d['lanes']['split.picture'].update(w=-5)),
        }
        for name, content in broken.items():
            with self.subTest(name), self.with_lanes(content):
                for layout in ('stage', 'wide'):          # the file is validated as a whole: one bad entry fails both layouts
                    with self.assertRaises(ValueError):
                        ed.visible_region(layout, 1920, 1080, None)
                    with self.assertRaises(ValueError):
                        ed.PICTURE_BOX[layout]

    def test_a_missing_lanes_file_is_a_distinct_error(self):
        with self.with_lanes(None):
            with self.assertRaises(ed.LanesFileMissing):
                ed.picture_boxes()
            with self.assertRaises(ValueError):                    # still a ValueError for every caller's fail-closed path
                ed.visible_region('stage', 1920, 1080, None)
        self.assertTrue(issubclass(ed.LanesFileMissing, ed.LanesFileError))
        self.assertTrue(issubclass(ed.LanesFileError, ValueError))

    def test_the_file_is_reread_when_it_changes(self):
        good = read(SCRIPTS.parent / 'assets' / 'yt-news-v4-lanes.json')
        good['lanes']['split.picture']['w'], good['lanes']['split.picture']['h'] = 1000, 500
        with self.with_lanes(good):
            self.assertEqual((1000, 500), tuple(ed.PICTURE_BOX['stage']))
            self.assertEqual((1280, 720), tuple(ed.PICTURE_BOX['wide']))
        self.assertEqual((1138, 640), tuple(ed.PICTURE_BOX['stage']))

    def test_hard_coded_values_without_score_relevance(self):
        # stage 1138x640, crop 120,136,1678x944: s = max(0.67818, 0.67797) -> region 1678 x 943.7..., centred
        x, y, w, h = ed.visible_region('stage', 1920, 1080, {'x': 120, 'y': 136, 'w': 1678, 'h': 944})
        self.assertAlmostEqual(1678.0, w, places=3)
        self.assertAlmostEqual(1678 * 640 / 1138, h, places=3)
        self.assertAlmostEqual(120.0, x, places=3)
        self.assertAlmostEqual(136 + (944 - h) / 2, y, places=3)
        # no crop, wide: 1280x720 is exactly 16:9, so the whole frame is visible
        self.assertEqual((0.0, 0.0, 1920.0, 1080.0), tuple(round(v, 6) for v in ed.visible_region('wide', 1920, 1080, None)))
        # no crop, stage (1138x640 is a little wider than 16:9): full width, slightly cropped height, centred
        x, y, w, h = ed.visible_region('stage', 1920, 1080, None)
        self.assertAlmostEqual(1920.0, w, places=6)
        self.assertAlmostEqual(1920 * 640 / 1138, h, places=6)
        self.assertAlmostEqual((1080 - h) / 2, y, places=6)

    def test_result_is_in_file_pixels(self):
        full = ed.visible_region('stage', 1920, 1080, {'x': 120, 'y': 136, 'w': 1678, 'h': 944})
        half = ed.visible_region('stage', 960, 540, {'x': 120, 'y': 136, 'w': 1678, 'h': 944})
        for a, b in zip(full, half):
            self.assertAlmostEqual(a / 2, b, places=6)
        sx = ed.visible_region('wide', 1280, 720, None)
        self.assertEqual((0.0, 0.0, 1280.0, 720.0), tuple(round(v, 6) for v in sx))

    def test_fails_closed(self):
        bad = [('flat', 1920, 1080, None), (None, 1920, 1080, None), ('stage', 0, 1080, None), ('stage', 1920, -1, None), ('stage', None, 1080, None),
               ('stage', float('nan'), 1080, None), ('stage', True, 1080, None),
               ('stage', 1920, 1080, {'x': 0, 'y': 0, 'w': 1921, 'h': 1080}), ('stage', 1920, 1080, {'x': 1281, 'y': 0, 'w': 640, 'h': 360}),
               ('stage', 1920, 1080, {'x': 0, 'y': 800, 'w': 640, 'h': 360}), ('stage', 1920, 1080, {'x': -1, 'y': 0, 'w': 640, 'h': 360}),
               ('stage', 1920, 1080, {'x': 0, 'y': 0, 'w': 0, 'h': 360}), ('stage', 1920, 1080, {'x': 0, 'y': 0, 'w': 640}),
               ('stage', 1920, 1080, 'junk'), ('stage', 1920, 1080, {'x': 0, 'y': 0, 'w': float('inf'), 'h': 360})]
        for args in bad:
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    ed.visible_region(*args)

    def test_every_v261111_crop_stays_inside_the_frame(self):
        for b in read(V261111)['beats']:
            if b.get('srcCrop'):
                x, y, w, h = ed.visible_region(b['layout'], 1920, 1080, b['srcCrop'])
                self.assertGreaterEqual(x, -1e-6)
                self.assertGreaterEqual(y, -1e-6)
                self.assertLessEqual(x + w, 1920 + 1e-6)
                self.assertLessEqual(y + h, 1080 + 1e-6)


if __name__ == '__main__':
    unittest.main()
