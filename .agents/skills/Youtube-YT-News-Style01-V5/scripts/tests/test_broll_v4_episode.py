"""V4 episode.json input of the b-roll scripts (broll_plan loader, visible-region maths, check_broll S10, broll_ledger record).

The fixtures under fixtures/a67/broll/ carry only the fields these scripts read; they are loader-level fixtures,
not schema-valid episodes (schema validity is episode_schema.mjs' job)."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import broll_ledger as bl
import broll_plan as bp
import check_broll as cb
import score_relevance as sr

FIXTURES = Path(__file__).resolve().parent / 'fixtures/a67/broll'
VALID = Path(__file__).resolve().parent / 'fixtures/episodes/valid'


class LoaderTests(unittest.TestCase):
    def test_loads_v4_episode_fields(self):
        ep = bp.load_v4_episode(FIXTURES / 'stock-full-typo.json')
        self.assertEqual((ep['vo_end'], ep['asset_dir'], ep['broll_dur']), (6, 'a67-broll', {'stock': 3}))
        self.assertEqual([(b['t'], b['end']) for b in ep['beats']], [(0, 2), (2, 4), (4, 6)])
        self.assertEqual(len(ep['sha256']), 64)

    def test_real_valid_fixture_loads(self):
        ep = bp.load_v4_episode(VALID / 'sample-v1.json')
        self.assertEqual(len(ep['beats']), 56)
        self.assertTrue(ep['broll_dur'])

    def test_not_v4_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            for name, text in [('list.json', '[{"t":0,"mode":"full"},{"t":3,"mode":"full"}]'), ('plain.json', '{"voEndSec":9,"beats":[{"t":0,"mode":"full"}]}'),
                               ('nodur.json', '{"schema":"yt-news-v4-episode/1","assetDir":"x","voEndSec":9,"beats":[{"t":0,"mode":"full"}]}')]:
                p = Path(d) / name
                p.write_text(text)
                with self.assertRaises(ValueError, msg=name):
                    bp.load_v4_episode(p)

    def test_tsx_is_a_hard_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'Comp.tsx'
            p.write_text('const BEATS = [];')
            with self.assertRaisesRegex(ValueError, 'V4 has no per-episode TSX'):
                bp.load_v4_episode(p)

    def test_derive_usage_uses_episode_broll_dur(self):
        ep = bp.load_v4_episode(FIXTURES / 'one-stock-beat.json')
        records = {'stock': {'pixabay_id': '1', 'duration': 3}}
        uses = bp.derive_usage(ep['beats'], records, ep['vo_end'], {'stock': 3.0}, ep['broll_dur'])
        self.assertEqual([(u['src'], u['t'], u['end'], u['shown_timing']['shown_frames']) for u in uses], [('stock', 0, 2, 50)])
        with self.assertRaises(ValueError):  # actual file differs from brollDur by more than a frame
            bp.derive_usage(ep['beats'], records, ep['vo_end'], {'stock': 3.5}, ep['broll_dur'])


class VisibleRegionTests(unittest.TestCase):
    """Engine srcCropStyle (remotion-composer/src/YtNewsStyle01V4.tsx); where spec section 6 differs, the engine wins."""

    def test_no_crop_covers_the_box_with_the_whole_frame(self):
        r = sr.visible_region(None, (1138, 640))
        self.assertAlmostEqual(r['x'], 0, places=6)
        self.assertAlmostEqual(r['w'], 1920, places=6)
        self.assertAlmostEqual(r['h'], 640 / (1138 / 1920), places=6)  # 1079.78: cover (s = max), not contain
        self.assertAlmostEqual(r['y'], (1080 - r['h']) / 2, places=6)
        wide = sr.visible_region(None, (1280, 720))
        self.assertEqual((round(wide['x'], 6), round(wide['y'], 6), round(wide['w'], 6), round(wide['h'], 6)), (0, 0, 1920, 1080))

    def test_crop_is_cover_fitted_and_centred(self):
        r = sr.visible_region({'x': 320, 'y': 180, 'w': 1280, 'h': 720}, (1280, 720))
        self.assertEqual([round(r[k], 6) for k in 'xywh'], [320, 180, 1280, 720])
        # crop wider than the box: width is trimmed, height kept, centred
        r = sr.visible_region({'x': 0, 'y': 100, 'w': 1920, 'h': 720}, (1280, 720))
        self.assertAlmostEqual(r['h'], 720, places=6)
        self.assertAlmostEqual(r['w'], 1280, places=6)
        self.assertAlmostEqual(r['x'], 320, places=6)
        # crop narrower than the box (4:3): cover trims the height, centred; the region always lies inside the crop
        r = sr.visible_region({'x': 0, 'y': 0, 'w': 960, 'h': 720}, (1280, 720))
        self.assertAlmostEqual(r['w'], 960, places=6)
        self.assertAlmostEqual(r['h'], 540, places=6)
        self.assertAlmostEqual(r['y'], 90, places=6)

    def test_frame_spec_ignores_punch_and_picks_box_by_layout(self):
        beat = {'t': 10, 'end': 18, 'from': 2, 'layout': 'wide', 'origin': 'source', 'punch': [{'at': 12, 'z': 2}]}
        spec = sr.frame_spec(beat, 20)
        self.assertEqual(spec['box'], [1280, 720])
        self.assertEqual({k: round(v, 6) for k, v in spec['region'].items()}, {'x': 0, 'y': 0, 'w': 1920, 'h': 1080})
        self.assertEqual(sr.frame_spec({**beat, 'layout': 'stage'}, 20)['box'], [1138, 640])
        with self.assertRaises(ValueError):
            sr.frame_spec({**beat, 'layout': 'full'}, 20)  # V3 layout

    def test_filter_cuts_the_region_and_fails_closed_outside_the_frame(self):
        f = sr.region_filter(sr.visible_region({'x': 100, 'y': 100, 'w': 1280, 'h': 720}, (1280, 720)))
        self.assertEqual(f, 'scale=1920:1080,crop=1280.0000:720.0000:100.0000:100.0000,scale=1024:576')
        with self.assertRaises(ValueError):  # a srcCrop that S11 would have rejected
            sr.region_filter(sr.visible_region({'x': 1000, 'y': 0, 'w': 1280, 'h': 720}, (1280, 720)))


class CheckBrollReuseTests(unittest.TestCase):
    def violations(self, name):
        ep = bp.load_v4_episode(FIXTURES / name)
        with tempfile.TemporaryDirectory() as d:  # no media files: only the reuse rule is of interest here
            v, rows, _ = cb.check(ep['beats'], 'a67-broll', d, bl.empty_ledger(), 2, {}, Path(d), 'slug', asset_dirs=[ep['asset_dir']])
        return [x for x in v if 'is missing' not in x], rows

    def test_source_clip_reuse_with_disjoint_ranges_is_allowed(self):
        v, rows = self.violations('reuse-source-disjoint.json')
        self.assertEqual([x for x in v if 'used by' in x or 'overlap' in x], [])
        self.assertEqual([(r['src'], r['uses']) for r in rows], [('yt_clip', 2)])

    def test_source_clip_reuse_with_overlapping_ranges_is_a_violation(self):
        v, _ = self.violations('reuse-source-overlap.json')
        self.assertTrue(any('source ranges of `yt_clip` overlap' in x for x in v), v)

    def test_stock_reuse_is_a_violation(self):
        v, _ = self.violations('reuse-stock.json')
        self.assertTrue(any('`desk` is used by 2 beats' in x and 'not a source clip' in x for x in v), v)

    def test_presenter_and_typo_beats_are_not_cutaways(self):
        v, rows = self.violations('stock-full-typo.json')
        self.assertEqual([r['src'] for r in rows], ['stock'])
        self.assertEqual([x for x in v if 'no `src`' in x], [])

    def test_asset_dir_must_match_media_dir(self):
        ep = bp.load_v4_episode(FIXTURES / 'one-stock-beat.json')
        with tempfile.TemporaryDirectory() as d:
            v, _, _ = cb.check(ep['beats'], 'other-dir', d, bl.empty_ledger(), 2, {}, Path(d), 'slug', asset_dirs=[ep['asset_dir']])
        self.assertTrue(any('episode assetDir is `a67-broll` but --media-dir is `other-dir`' in x for x in v), v)

    def test_cli_rejects_tsx_with_clear_message(self):
        with tempfile.TemporaryDirectory() as d:
            m = Path(d) / 'projects/slug/assets/broll/_manifest.json'
            m.parent.mkdir(parents=True)
            m.write_text('{}')
            cuts = Path(d) / '_cuts.json'
            cuts.write_text('{}')
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = cb.main([str(Path(d) / 'Comp.tsx'), '--media-dir', 'x', '--manifest', str(m), '--cuts', str(cuts),
                              '--ledger', str(Path(d) / 'ledger.json'), '--public-root', d, '--projects-root', d])
            self.assertEqual(rc, 2)
            self.assertIn('V4 has no per-episode TSX; pass --episode', err.getvalue())


class LedgerRecordTests(unittest.TestCase):
    def record(self, d, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = bl.main(['record', 'a67-broll', '--ledger', str(Path(d) / 'ledger.json'), '--public-root', str(Path(d) / 'public'), *extra])
        return rc, out.getvalue(), err.getvalue()

    def test_composition_flag_is_a_hard_error(self):
        with tempfile.TemporaryDirectory() as d:
            rc, _, err = self.record(d, '--composition', 'Comp.tsx')
            self.assertEqual(rc, 2)
            self.assertIn('V4 has no per-episode TSX; pass --episode', err)
            rc, _, err = self.record(d)
            self.assertEqual(rc, 2)
            self.assertIn('--episode', err)

    def test_record_reads_episode_json_and_pins_episode_identity(self):
        with tempfile.TemporaryDirectory() as d:
            clip = Path(d) / 'public/a67-broll/broll/stock.mp4'
            clip.parent.mkdir(parents=True)
            clip.write_bytes(b'stock-bytes')
            rc, out, err = self.record(d, '--episode', str(FIXTURES / 'one-stock-beat.json'))
            self.assertEqual(rc, 0, err)
            self.assertIn('RECORD public', out)
            ledger = json.loads((Path(d) / 'ledger.json').read_text())
            self.assertEqual(ledger['episodes']['a67-broll']['comp'], 'one-stock-beat.json')
            # same mediaDir for another episode is refused
            rc, _, err = self.record(d, '--episode', str(FIXTURES / 'two-stock-beats.json'))
            self.assertEqual(rc, 1)
            self.assertIn('already recorded for episode one-stock-beat.json', err)

    def test_episode_key_is_the_project_folder(self):
        self.assertEqual(bl.episode_key('projects/v261111-001/artifacts/episode.json'), 'v261111-001')
        self.assertEqual(bl.episode_key('/x/y/episode.json'), 'episode.json')


if __name__ == '__main__':
    unittest.main()
