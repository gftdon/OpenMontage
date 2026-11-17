"""music_library.py: manifest validation, library lookup, CLI. Temp dirs only; never the real library."""
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import music_library as ml  # noqa: E402

BYTES_A, BYTES_B = b'bed-A' * 100, b'bed-B' * 100


def sha(b):
    return hashlib.sha256(b).hexdigest()


def track(file='a.mp3', data=BYTES_A, **kw):
    t = {'sha256': sha(data), 'file': file, 'title': 'Calm', 'license': 'owner licence', 'origin': 'purchase receipt 42',
         'approved_by': 'owner', 'approved_on': '2026-11-12', 'duration_sec': 140.5}
    t.update(kw)
    return t


def manifest(*tracks):
    return {'schema': ml.MANIFEST_SCHEMA, 'version': 1, 'tracks': list(tracks)}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.lib = self.root / 'music_library'
        self.lib.mkdir()
        env = patch.dict(os.environ)
        env.start()
        os.environ.pop('MUSIC_LIBRARY_DIR', None)
        self.addCleanup(env.stop)

    def write_manifest(self, m, name='m.json'):
        p = self.root / name
        p.write_text(json.dumps(m))
        return p


class ManifestTests(Base):
    def test_valid_manifest_loads(self):
        m = manifest(track(), track('b.mp3', BYTES_B, title=None, duration_sec=None))
        self.assertEqual(m, ml.load_manifest(self.write_manifest(m)))

    def test_empty_manifest_is_valid(self):
        self.assertEqual([], ml.load_manifest(self.write_manifest(manifest()))['tracks'])

    def bad(self, m, fragment):
        with self.assertRaises(ml.MusicLibraryError) as cm:
            ml.load_manifest(self.write_manifest(m))
        self.assertIn(fragment, str(cm.exception))

    def test_validation_failures(self):
        t = track()
        missing = {k: v for k, v in t.items() if k != 'origin'}
        self.bad(manifest(missing), 'keys must be exactly')
        self.bad(manifest(dict(t, extra=1)), 'keys must be exactly')
        self.bad(manifest(track(sha256='abc')), 'sha256')
        self.bad(manifest(track(sha256=sha(BYTES_A).upper())), 'sha256')
        self.bad(manifest(track(), track('b.mp3')), 'duplicate sha256')
        self.bad(manifest(track(), track('a.mp3', BYTES_B)), 'duplicate file')
        for f in ('x/a.mp3', '../a.mp3', 'a\\b.mp3', '.hidden.mp3'):
            self.bad(manifest(track(f)), "'file'")
        self.bad(manifest(track('a.wav')), "'file'")
        for k in ('license', 'origin', 'approved_by'):
            self.bad(manifest(track(**{k: ''})), k)
            self.bad(manifest(track(**{k: '  '})), k)
        self.bad(manifest(track(approved_on='2026-13-40')), 'approved_on')
        self.bad(manifest(track(approved_on='12/11/2026')), 'approved_on')
        self.bad(manifest(track(duration_sec=0)), 'duration_sec')
        self.bad(manifest(track(duration_sec=True)), 'duration_sec')
        for v in (float('inf'), float('-inf'), float('nan'), -3, '120'):
            self.bad(manifest(track(duration_sec=v)), 'duration_sec')     # json.dumps writes Infinity / NaN
        self.bad(manifest(track(title=5)), 'title')
        self.bad(manifest(track(title='')), 'title')
        self.bad(manifest(track(title='   ')), 'title')

    def test_top_level_failures(self):
        self.bad(dict(manifest(), schema='other'), 'schema')
        self.bad(dict(manifest(), version=2), 'version')
        self.bad(dict(manifest(), extra=1), 'keys must be exactly')
        self.bad({'schema': ml.MANIFEST_SCHEMA, 'version': 1}, 'keys must be exactly')
        self.bad([], 'JSON object')
        p = self.root / 'bad.json'
        p.write_text('{nope')
        with self.assertRaises(ml.MusicLibraryError):
            ml.load_manifest(p)
        with self.assertRaises(ml.MusicLibraryError):
            ml.load_manifest(self.root / 'absent.json')

    def test_sha_returned_with_manifest_is_of_the_bytes(self):
        p = self.write_manifest(manifest(track()))
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), ml.load_manifest_with_sha(p)[1])

    def test_the_shipped_manifest_loads_and_validates(self):
        self.assertEqual(SCRIPTS / 'music_library.json', ml.manifest_path())
        m = ml.load_manifest()
        self.assertIsInstance(m['tracks'], list)
        self.assertEqual((ml.MANIFEST_SCHEMA, 1), (m['schema'], m['version']))
        self.assertEqual('yt-news-v4-music-library', ml.MANIFEST_SCHEMA)
        self.assertEqual('music_library', ml.SIDECAR_PROVIDER)

    def test_find_track(self):
        m = manifest(track(), track('b.mp3', BYTES_B))
        self.assertEqual('b.mp3', ml.find_track(m, sha(BYTES_B))['file'])
        self.assertIsNone(ml.find_track(m, 'f' * 64))


class LibraryTests(Base):
    def test_library_dir_default_and_env_override(self):
        self.assertEqual(self.root / 'music_library', ml.library_dir(self.root))
        other = self.root / 'elsewhere'
        with patch.dict(os.environ, {'MUSIC_LIBRARY_DIR': str(other)}):
            self.assertEqual(other, ml.library_dir(self.root))
        with patch.dict(os.environ, {'MUSIC_LIBRARY_DIR': ''}):
            self.assertEqual(self.root / 'music_library', ml.library_dir(self.root))
        with patch.dict(os.environ, {'MUSIC_LIBRARY_DIR': 'relative/dir'}):
            with self.assertRaises(ml.MusicLibraryError):
                ml.library_dir(self.root)

    def test_check_library_statuses(self):
        (self.lib / 'ok.mp3').write_bytes(BYTES_A)
        (self.lib / 'bad.mp3').write_bytes(b'tampered')
        (self.root / 'real.mp3').write_bytes(BYTES_B)
        (self.lib / 'link.mp3').symlink_to(self.root / 'real.mp3')
        (self.lib / 'dir.mp3').mkdir()
        m = manifest(track('ok.mp3', BYTES_A), track('bad.mp3', BYTES_B), track('gone.mp3', b'gone'),
                     track('link.mp3', b'link'), track('dir.mp3', b'dir'))
        rows = ml.check_library(self.root, m)
        self.assertEqual(['ok.mp3', 'bad.mp3', 'gone.mp3', 'link.mp3', 'dir.mp3'], [r['file'] for r in rows])
        self.assertEqual(['ok', 'sha-mismatch', 'missing', 'missing', 'missing'], [r['status'] for r in rows])
        self.assertEqual(str(self.lib / 'ok.mp3'), rows[0]['path'])
        self.assertEqual(sha(BYTES_A), rows[0]['sha256'])

    def test_pick_track_first_ok_wins_and_skips_a_mismatch(self):
        (self.lib / 'a.mp3').write_bytes(b'tampered')
        (self.lib / 'b.mp3').write_bytes(BYTES_B)
        (self.lib / 'c.mp3').write_bytes(BYTES_A)
        m = manifest(track('a.mp3', BYTES_A), track('b.mp3', BYTES_B), track('c.mp3', BYTES_A, sha256=sha(BYTES_A + b'x')))
        t, p = ml.pick_track(self.root, m)
        self.assertEqual(('b.mp3', self.lib / 'b.mp3'), (t['file'], p))
        (self.lib / 'a.mp3').write_bytes(BYTES_A)
        self.assertEqual('a.mp3', ml.pick_track(self.root, m)[0]['file'])

    def test_pick_track_empty_and_none_ok_messages(self):
        with self.assertRaises(ml.MusicLibraryError) as cm:
            ml.pick_track(self.root, manifest())
        self.assertIn('music library is empty', str(cm.exception))
        (self.lib / 'a.mp3').write_bytes(b'tampered')
        with self.assertRaises(ml.MusicLibraryError) as cm:
            ml.pick_track(self.root, manifest(track('a.mp3', BYTES_A), track('b.mp3', BYTES_B)))
        msg = str(cm.exception)
        self.assertIn('a.mp3: sha-mismatch', msg)
        self.assertIn('b.mp3: missing', msg)
        self.assertIn(str(self.lib), msg)

    def test_pick_track_and_check_library_use_manifest_path_by_default(self):
        (self.lib / 'a.mp3').write_bytes(BYTES_A)
        p = self.write_manifest(manifest(track('a.mp3', BYTES_A)))
        with patch.object(ml, 'manifest_path', lambda: p):
            self.assertEqual('a.mp3', ml.pick_track(self.root)[0]['file'])
            self.assertEqual(['ok'], [r['status'] for r in ml.check_library(self.root)])
        p = self.write_manifest(manifest())
        with patch.object(ml, 'manifest_path', lambda: p):
            with self.assertRaises(ml.MusicLibraryError) as cm:
                ml.pick_track(self.root)
        self.assertIn('music library is empty', str(cm.exception))


class CliTests(Base):
    def run_cli(self, m, *extra):
        p = self.write_manifest(m)
        out, err = io.StringIO(), io.StringIO()
        with patch.object(ml, 'manifest_path', lambda: p), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = ml.main(['check', '--repo-root', str(self.root), *extra])
        return rc, out.getvalue(), err.getvalue()

    def test_exit_0_when_at_least_one_track_is_ok(self):
        (self.lib / 'b.mp3').write_bytes(BYTES_B)
        rc, out, _ = self.run_cli(manifest(track('a.mp3', BYTES_A), track('b.mp3', BYTES_B)))
        self.assertEqual(0, rc)
        self.assertIn(f'missing a.mp3 {sha(BYTES_A)[:12]}', out)
        self.assertIn(f'ok b.mp3 {sha(BYTES_B)[:12]}', out)
        self.assertIn('1/2', out)

    def test_exit_4_when_none_ok_empty_or_manifest_invalid(self):
        self.assertEqual(4, self.run_cli(manifest(track()))[0])
        self.assertEqual(4, self.run_cli(manifest())[0])
        rc, _, err = self.run_cli({'schema': 'x'})
        self.assertEqual(4, rc)
        self.assertIn('ERROR', err)

    def test_env_override_is_honoured_by_the_cli(self):
        other = self.root / 'other'
        other.mkdir()
        (other / 'a.mp3').write_bytes(BYTES_A)
        with patch.dict(os.environ, {'MUSIC_LIBRARY_DIR': str(other)}):
            self.assertEqual(0, self.run_cli(manifest(track()))[0])

    def test_importing_has_no_side_effects(self):
        self.assertTrue(callable(ml.main))


if __name__ == '__main__':
    unittest.main()
