"""finalize.py, CF-A67 W3 phase A: what --check decides is recomputed from primary inputs, never from files the agent wrote.

face-box (A2), cuts (A3), receipt v2 (A4), layout hashes recomputed without a cache (A6), the clean-checkout check (A7),
mux-audio (A8) and the --check budget (A9).  The fixture repo / project / stubs are the ones of test_finalize.py (imported).
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_finalize as tf                      # noqa: E402  (fixtures: make_repo, write_receipts, the stubs, the real mux audio)
from test_finalize import FinalizeBase, SCRIPTS, sha, ffmpeg, write_receipts, final_with_audio  # noqa: E402


def setUpModule():
    # test_finalize's module fixture (env stand-ins, the project template, the real mux audio).  Cleared first: pytest may already
    # have run (and torn down) test_finalize's own module in this session.
    tf.AVATAR_FILE.clear()
    tf.MUXED.clear()
    tf.setUpModule()


def tearDownModule():
    tf.tearDownModule()


def tree_state(root):
    """Every file and directory under root -> {relative path: (kind, size, mtime_ns, sha256)}."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for d in dirnames:
            p = Path(dirpath) / d
            out[str(p.relative_to(root))] = ('dir',)
        for f in filenames:
            p = Path(dirpath) / f
            st = p.lstat()
            out[str(p.relative_to(root))] = ('file', st.st_size, st.st_mtime_ns, sha(p) if p.is_file() else None)
    return out


class Base(FinalizeBase):
    def run_argv(self, argv, patch=None):
        m = self.module()
        if patch:
            patch(m)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = m.main([str(a) for a in argv])
        self.out = buf.getvalue()
        return code

    def gate_rec(self, name, doc=None):
        doc = doc or (self.receipt() if self.deliver.exists() else self.failed())
        return self.gate(doc, name)

    def rebind(self, **kw):
        """Re-write the layout / render / mux receipts for the current files (as the agent's tools would)."""
        write_receipts(self.repo, name=self.name, **kw)


# ------------------------------------------------------------------------------------------------------------- A2 face-box
class FaceBoxGateTests(Base):
    def test_pass_measures_the_avatar_the_episode_uses_against_its_box(self):
        self.assertEqual(0, self.run_fin(), self.out)
        g = self.gate_rec('face-box')
        self.assertEqual('pass', g['status'])
        avatar = self.repo / 'remotion-composer' / 'public' / 'ep1' / 'avatar.mp4'
        self.assertEqual(['check', '--avatar', str(avatar), '--episode', str(self.proj / 'artifacts' / 'episode.json'), '--report',
                          str(self.rdir / 'face-box.json')], self.argv_of('face_box'))
        self.assertEqual(0.97, g['min_share'])
        self.assertIn('projects/p1/qc/finalize/face-box.json', g['inputs'])

    def test_a_failed_check_is_a_quality_failure_exit_1_with_the_fix(self):
        self.behavior(face_box={'pass': False})
        self.assertExit(1, 'fail', 'face-box')
        g = self.gate_rec('face-box')
        self.assertTrue(g['reason'].startswith('face-box FAIL'), g['reason'])
        self.assertIn('fix: replace avatarFaceBox', ' '.join(g['issues']))

    def test_cannot_measure_is_never_a_pass(self):
        for beh, code, status in (({'exit': 4, 'write': False}, 4, 'missing'), ({'exit': 2, 'write': False}, 2, 'bad-input'),
                                  ({'exit': 0, 'write': False}, 2, 'stale'), ({'exit': 0, 'pass': False}, 1, 'fail'),
                                  ({'exit': 7}, 4, 'crashed')):
            self.behavior(face_box=beh)
            self.assertEqual(code, self.run_fin(), (beh, self.out))
            self.assertEqual(status, self.gate_rec('face-box')['status'], beh)

    def test_a_report_of_another_avatar_or_another_box_is_refused(self):
        for beh in ({'avatar_sha256': 'f' * 64}, {'face_box': {'x': 0.0, 'y': 0.0, 'w': 1.0, 'h': 1.0}}, {'schema': 'other'}):
            self.behavior(face_box=beh)
            self.assertEqual(2, self.run_fin(), (beh, self.out))
            self.assertEqual('stale', self.gate_rec('face-box')['status'], beh)


class RealFaceBoxContractTests(Base):
    """The real face_box.py behind the gate: the fixture avatar is 2 s long, which it refuses (exit 2) -- never a pass."""
    real = ('face_box.py', 'face_vision.swift')

    def test_an_avatar_it_cannot_measure_is_bad_input_exit_2(self):
        self.assertEqual(2, self.run_fin(), self.out)
        g = self.gate_rec('face-box')
        self.assertEqual('bad-input', g['status'])
        self.assertIn('need at least 20s', g['reason'])
        self.assertFalse((self.rdir / 'face-box.json').exists())


# ------------------------------------------------------------------------------------------------------------- A3 cuts
def probe_duration(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', str(path)],
                       capture_output=True, text=True, check=True)
    return round(float(r.stdout.strip()), 3)


class CutsGateTests(Base):
    """Real clips cut by the real cut_clips.sh from a synthetic source whose picture changes every frame (a moving gradient)."""
    SRC = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        d = Path(tempfile.mkdtemp(prefix='cuts-src-')).resolve()
        cls.SRC = d
        ffmpeg('-f', 'lavfi', '-i', "nullsrc=s=320x180:r=30:d=14,geq=lum='mod(2*X+40*T\\,256)':cb=128:cr=128", '-c:v', 'libx264',
               '-pix_fmt', 'yuv420p', str(d / 'source.mp4'))
        r = subprocess.run(['bash', str(SCRIPTS / 'cut_clips.sh'), str(d / 'source.mp4'), str(d / 'clips'), 'c1:2:6', 'c2:8:12'],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        cls.DUR = {n: probe_duration(d / 'clips' / (n + '.mp4')) for n in ('c1', 'c2')}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.SRC, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        yts = self.proj / 'assets' / 'ytsource'
        shutil.copy(self.SRC / 'source.mp4', yts / 'source.mp4')
        shutil.copytree(self.SRC / 'clips', yts / 'clips')
        broll = self.repo / 'remotion-composer' / 'public' / 'ep1' / 'broll'
        for n in ('c1', 'c2'):
            shutil.copy(yts / 'clips' / (n + '.mp4'), broll / (n + '.mp4'))
        shutil.copy(yts / 'clips' / '_cuts.json', self.proj / 'artifacts' / '_cuts.json')
        self.edit(self.proj / 'artifacts' / 'episode.json', lambda d: d.update(brollDur=dict(self.DUR), beats=[
            {'t': 0, 'mode': 'pip', 'media': 'clip', 'src': 'c1', 'origin': 'source'},
            {'t': 1, 'mode': 'pip', 'media': 'clip', 'src': 'c2', 'origin': 'source'},
            {'t': 1.5, 'mode': 'pip', 'media': 'clip', 'src': 'c1', 'origin': 'source', 'from': 2}]))
        self.rebind()

    def shown(self):
        """beat 2 (t 1.5, from 2, until totalDurationSec 4.0) is held by the engine after floor((len - 2) * 25) - 2 frames"""
        return min(2.5, max(1, int((self.DUR['c1'] - 2) * 25) - 2) / 25)

    def cuts(self, fn):
        self.edit(self.proj / 'artifacts' / '_cuts.json', fn)

    def test_clips_cut_from_the_source_pass_by_bytes_and_by_picture(self):
        self.assertEqual(0, self.run_fin(), self.out)
        g = self.gate_rec('cuts')
        self.assertEqual('pass', g['status'])
        rep = json.loads((self.rdir / 'cuts.json').read_text())
        self.assertEqual(['c1', 'c2'], [c['src'] for c in rep['clips']])          # every distinct shown clip, once
        for c in rep['clips']:
            self.assertEqual(sha(self.repo / 'remotion-composer' / 'public' / 'ep1' / 'broll' / (c['src'] + '.mp4')), c['stagedSha256'])
        # B7: every footage BEAT at 3 points of the range it shows (1 point when it shows <= 1.0 s): 1 + 1 + 3
        sh = self.shown()
        self.assertEqual([('c1', 0, 0, 0.5), ('c2', 1, 0, 0.25), ('c1', 2, 0, 2.5), ('c1', 2, 1, round(2 + sh / 2, 3)),
                          ('c1', 2, 2, round(2 + sh - 0.5, 3))],
                         [(p['src'], p['beat'], p['point'], p['clipSec']) for p in rep['pictures']])
        self.assertEqual(5, rep['pictureChecks'])
        for p in rep['pictures']:
            self.assertLess(p['distance'], 1.5, p)
            self.assertGreater(p['sourceFrames'], 5)
        self.assertEqual(0.5, rep['edgeSec'])
        self.assertEqual(sha(self.proj / 'assets' / 'ytsource' / 'source.mp4'), rep['sourceVideo']['sha256'])
        self.assertEqual(rep['sourceVideo']['sha256'], self.receipt()['input_hashes']['source_video']['sha256'])

    def test_a_lying_source_in_is_a_quality_failure_exit_1(self):
        self.cuts(lambda d: d['clips']['c1'].update(source_in=d['clips']['c1']['source_in'] + 5))
        self.assertEqual(1, self.run_fin(), self.out)
        g = self.gate_rec('cuts')
        self.assertEqual('fail', g['status'])
        self.assertIn('clip c1, beat 0 (t 0, from 0, shows 1.00 s), does not show the source video: picture distance', g['reason'])
        self.assertIn('around source_in 7', g['reason'])
        self.assertNotIn('clip c2', g['reason'])

    def test_a_small_shift_of_source_in_is_caught_too(self):
        self.cuts(lambda d: d['clips']['c2'].update(source_in=d['clips']['c2']['source_in'] + 1))
        self.assertEqual(1, self.run_fin(), self.out)
        self.assertIn('clip c2, beat 1 (t 1, from 0, shows 0.50 s), does not show the source video', self.gate_rec('cuts')['reason'])

    def test_other_footage_spliced_into_the_end_of_a_shown_range_is_caught(self):
        # B7: c1's first 3.2 s are the real cut, then other footage; _cuts.json's sha is updated to the spliced file (a lie the byte
        # check cannot see).  Beat 0 (0..1 s) and beat 2's first two points (2.5 s, 2 + shown / 2 <= 3.0 s) are honest; only the last
        # point of beat 2 (2 + shown - 0.5 >= 3.4 s) lands in the splice.  A single mid-clip picture would have passed.
        broll = self.repo / 'remotion-composer' / 'public' / 'ep1' / 'broll'
        spliced = Path(self.tmp) / 'c1-spliced.mp4'
        ffmpeg('-i', str(broll / 'c1.mp4'), '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=30:d=%.3f' % (self.DUR['c1'] - 3.2),
               '-filter_complex', '[0:v]trim=0:3.2,setpts=PTS-STARTPTS[a];[1:v]setpts=PTS-STARTPTS[b];[a][b]concat=n=2:v=1:a=0[v]',
               '-map', '[v]', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-r', '30', str(spliced))
        shutil.copy(spliced, broll / 'c1.mp4')
        self.cuts(lambda d: d['clips']['c1'].update(sha256=sha(broll / 'c1.mp4')))
        self.edit(self.proj / 'artifacts' / 'episode.json', lambda d: d['brollDur'].update(c1=probe_duration(broll / 'c1.mp4')))
        self.rebind()
        self.assertEqual(1, self.run_fin(), self.out)
        g = self.gate_rec('cuts')
        self.assertEqual('fail', g['status'])
        self.assertIn('clip c1, beat 2 (t 1.5, from 2, shows', g['reason'])
        self.assertNotIn('beat 0', g['reason'])
        rep = json.loads((self.rdir / 'cuts.json').read_text())
        dist = {(p['beat'], p['point']): p['distance'] for p in rep['pictures']}
        self.assertLess(dist[(0, 0)], 1.5)
        self.assertLess(dist[(2, 0)], 1.5)
        self.assertLess(dist[(2, 1)], 1.5)
        self.assertGreater(dist[(2, 2)], 1.5)
        self.assertEqual(['clip c1, beat 2'], sorted({m.split(' (')[0] for m in rep['problems']}))

    def test_an_episode_without_broll_durations_is_refused_not_guessed(self):
        self.edit(self.proj / 'artifacts' / 'episode.json', lambda d: d.pop('brollDur'))
        self.rebind()
        self.assertEqual(2, self.run_fin(), self.out)
        self.assertIn('beat 0 (c1) has no valid t / from / next t / brollDur[c1]', self.gate_rec('cuts')['reason'])

    def test_a_staged_file_that_is_not_the_recorded_cut_is_stale(self):
        broll = self.repo / 'remotion-composer' / 'public' / 'ep1' / 'broll'
        shutil.copy(broll / 'c2.mp4', broll / 'c1.mp4')
        self.rebind()                                # the agent re-ran layout/render/mux on the swapped file: the receipts agree
        self.assertEqual(2, self.run_fin(), self.out)
        g = self.gate_rec('cuts')
        self.assertEqual('stale', g['status'])
        self.assertIn('clip c1: remotion-composer/public/ep1/broll/c1.mp4 is not the file _cuts.json recorded', g['reason'])

    def test_a_record_from_another_source_video_is_stale(self):
        self.cuts(lambda d: d['clips']['c2'].update(source_sha256='a' * 64))
        self.assertEqual(2, self.run_fin(), self.out)
        self.assertIn('clip c2: _cuts.json says it was cut from another file', self.gate_rec('cuts')['reason'])

    def test_a_replaced_source_video_is_stale(self):
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=30:d=14', '-pix_fmt', 'yuv420p', str(self.proj / 'assets' / 'ytsource' / 'source.mp4'))
        self.assertEqual(2, self.run_fin(), self.out)
        reason = self.gate_rec('cuts')['reason']
        self.assertIn('clip c1: _cuts.json says it was cut from another file', reason)

    def test_a_shown_clip_without_a_record_is_refused(self):
        self.cuts(lambda d: d['clips'].pop('c2'))
        self.assertEqual(2, self.run_fin(), self.out)
        self.assertIn('clip c2 has no record', self.gate_rec('cuts')['reason'])

    def test_the_source_video_is_required_once_a_clip_is_shown(self):
        (self.proj / 'assets' / 'ytsource' / 'source.mp4').unlink()
        self.assertEqual(2, self.run_fin(), self.out)
        self.assertIn('the source video projects/p1/assets/ytsource/source.mp4 is missing', self.gate_rec('cuts')['reason'])

    def test_a_cuts_file_that_is_not_a_cuts_object_is_refused(self):
        (self.proj / 'artifacts' / '_cuts.json').write_text('[]')
        self.assertEqual(2, self.run_fin(), self.out)
        self.assertIn('not a cuts file', self.gate_rec('cuts')['reason'])


class CutsWithoutFootageTests(Base):
    def test_an_episode_without_footage_needs_no_binding(self):
        self.assertEqual(0, self.run_fin(), self.out)
        self.assertEqual('pass', self.gate_rec('cuts')['status'])
        rep = json.loads((self.rdir / 'cuts.json').read_text())
        self.assertEqual(0, rep['footageBeats'])
        self.assertIn('nothing to bind', rep['note'])


# ------------------------------------------------------------------------------------------------------------- A8 mux-audio
def mux_script_copy(tmp, old, new):
    """A modified copy of the REAL mux_av.sh (what a mux with other settings would have made)."""
    text = (SCRIPTS / 'mux_av.sh').read_text()
    assert text.count(old) == 1, old
    d = Path(tmp) / 'muxcopy'
    d.mkdir(exist_ok=True)
    for f in ('measure_loudness.py',):
        shutil.copy(SCRIPTS / f, d / f)
    p = d / ('mux_av_%s.sh' % hashlib.sha1(new.encode()).hexdigest()[:8])
    p.write_text(text.replace(old, new))
    return p


class MuxAudioGateTests(Base):
    def final_from(self, audio):
        visual = self.proj / 'renders' / 'visual.mp4'
        ffmpeg('-i', str(visual), '-i', str(audio), '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'copy', '-shortest',
               str(self.fin))
        self.rebind()

    def remux(self, old, new):
        work = Path(self.tmp) / ('mux-' + hashlib.sha1(new.encode()).hexdigest()[:8])
        audio = tf.real_mux_audio(work, self.proj / 'renders' / 'visual.mp4', self.repo / 'remotion-composer' / 'public' / 'ep1' / 'avatar.mp4',
                                  tf.LIB_BYTES, script=mux_script_copy(self.tmp, old, new))
        self.final_from(audio)

    def test_the_real_mux_is_rebuilt_bit_for_bit_and_its_mix_is_not_kept(self):
        self.assertEqual(0, self.run_fin(), self.out)
        g = self.gate_rec('mux-audio')
        self.assertEqual('pass', g['status'])
        self.assertTrue(g['streamhash_equal'])
        rep = json.loads((self.rdir / 'mux-audio.json').read_text())
        self.assertEqual(rep['rebuiltStreamhash'], rep['finalStreamhash'])
        self.assertEqual({'total': 4.0, 'vo_end': 2.0, 'bed_volume': 0.22}, {k: rep[k] for k in ('total', 'vo_end', 'bed_volume')})
        self.assertEqual(sha(self.proj / 'assets' / 'audio' / 'bed.mp3'), rep['bed']['sha256'])
        self.assertFalse((self.rdir / 'mux-audio' / 'mix.wav').exists())

    def test_a_final_muxed_with_another_bed_volume_fails_exit_1(self):
        self.remux('VOL=0.22', 'VOL=0.5')                 # the receipt still says 0.22 (write_receipts): only the audio tells
        self.assertEqual(1, self.run_fin(), self.out)
        g = self.gate_rec('mux-audio')
        self.assertEqual('fail', g['status'])
        self.assertFalse(g['streamhash_equal'])
        self.assertLess(g['snr_db'], 60)
        self.assertIn('is not what mux_av.sh makes from the avatar', g['reason'])
        self.assertEqual('pass', self.gate_rec('mux')['status'])        # every receipt check passes: the claim is what is wrong

    def test_a_shifted_voice_fails_exit_1(self):
        self.remux('[0:a]apad=', '[0:a]adelay=40:all=1,apad=')
        self.assertEqual(1, self.run_fin(), self.out)
        self.assertEqual('fail', self.gate_rec('mux-audio')['status'])

    def test_a_final_with_other_audio_fails_and_one_without_audio_too(self):
        final_with_audio(self.proj, audio='sine=frequency=440:sample_rate=48000:duration=30')
        self.rebind()
        self.assertEqual(1, self.run_fin(), self.out)
        self.assertEqual('fail', self.gate_rec('mux-audio')['status'])
        final_with_audio(self.proj, audio=None)
        self.rebind()
        self.assertEqual(1, self.run_fin(), self.out)
        self.assertIn('has no readable audio stream', self.gate_rec('mux-audio')['reason'])

    def test_a_bed_that_is_not_audio_is_bad_input(self):
        self.rebind(bed_bytes=b'NOT AUDIO AT ALL')
        self.assertEqual(2, self.run_fin(), self.out)
        g = self.gate_rec('mux-audio')
        self.assertEqual('bad-input', g['status'])
        self.assertIn('has no readable audio stream', g['reason'])

    def test_the_bed_must_be_a_file_under_the_project_audio_dir(self):
        outside = Path(self.tmp) / 'bed.wav'
        outside.write_bytes(tf.LIB_BYTES)
        self.edit(self.mux_path(), lambda d: d['bed'].update(path=str(outside)))
        self.assertEqual(2, self.run_fin(), self.out)
        self.assertIn('is not a file under projects/p1/assets/audio/', self.gate_rec('mux-audio')['reason'])

    def test_graph_loudnorm_and_encoder_settings_are_those_of_mux_av_sh(self):
        m = self.module()
        text = (SCRIPTS / 'mux_av.sh').read_text()
        self.assertIn('"%s"' % m.MUX_GRAPH, text)
        self.assertIn('VOL=%s' % m.MUX_BED_VOLUME, text)
        self.assertIn('-af %s:print_format=json -f null -' % m.MUX_LOUDNORM, text)
        self.assertIn("f='%s:linear=true:print_format=json:'" % m.MUX_LOUDNORM, text)
        self.assertIn('-c:a pcm_f32le', text)
        self.assertIn('-ar 48000 -c:a pcm_f32le', text)
        self.assertIn('-c:a aac -ar 48000 -b:a 192k', text)
        self.assertIn("[('measured_I','input_i'),('measured_TP','input_tp'),('measured_LRA','input_lra'),('measured_thresh','input_thresh'),"
                      "('offset','target_offset')]", text)

    def test_parse_loudnorm_is_the_one_of_measure_loudness(self):
        m = self.module()
        spec = importlib.util.spec_from_file_location('ml_real', SCRIPTS / 'measure_loudness.py')
        ml = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ml)
        r = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(tf.MUXED[tf.MUX_LIB]), '-af',
                            'loudnorm=I=-14:TP=-1.5:LRA=20:print_format=json', '-f', 'null', '-'], capture_output=True, text=True)
        real = ml.parse_loudnorm(r.stderr)
        mine = m.parse_loudnorm(r.stderr)
        self.assertEqual({k: real[k] for k in m.LOUDNORM_KEYS}, mine)
        # the LAST object that has all five keys wins; objects without them are skipped (an earlier one too)
        two = '{"input_i": "-1"}\n' + r.stderr + '\n{"other": "1"}'
        self.assertEqual({k: ml.parse_loudnorm(two)[k] for k in m.LOUDNORM_KEYS}, m.parse_loudnorm(two))
        five = '"input_tp": "1", "input_lra": "1", "input_thresh": "1", "target_offset": "1"'
        for bad in ('no json', '{"input_i": "-inf", %s}' % five, r.stderr + '\n{"input_i": "x", %s}' % five):   # unparsable number = error
            with self.assertRaises(ValueError):
                ml.parse_loudnorm(bad)
            with self.assertRaises(ValueError):
                m.parse_loudnorm(bad)


# ------------------------------------------------------------------------------------------------------------- A6 layout hashes
class LayoutFreshHashTests(Base):
    def rehash_manifest(self, fn):
        mp = self.manifest_path()
        manifest = json.loads(mp.read_text())
        fn(manifest)
        mp.write_text(json.dumps(manifest, indent=2))
        mhash = hashlib.sha256(tf.canon(manifest).encode()).hexdigest()
        self.edit(self.layout_path(), lambda d: d.update(manifestHash=mhash))
        self.edit(self.render_path(), lambda d: d.update(gateManifestHash=mhash, gateReportSha256=sha(self.layout_path())))

    def test_a_planted_hash_cache_entry_that_lies_is_never_believed(self):
        cache = self.proj / 'qc' / 'layout' / 'cache' / 'media-hash.json'
        self.rebind(cache_file=cache)                               # the cache now holds the true sha of broll/a.mp4
        a = self.repo / 'remotion-composer' / 'public' / 'ep1' / 'broll' / 'a.mp4'
        st = a.stat()
        with open(a, 'r+b') as f:                                    # same size, same inode, same mtime: the cache entry still "hits"
            f.write(b'y')
        os.utime(a, ns=(st.st_atime_ns, st.st_mtime_ns))
        self.assertEqual((st.st_size, st.st_ino, st.st_mtime_ns), (a.stat().st_size, a.stat().st_ino, a.stat().st_mtime_ns))
        self.rebind(cache_file=cache)                               # what qc_layout / render_episode would record with that cache
        claimed = json.loads(self.manifest_path().read_text())['mediaDigest']['digest']
        honest = tf.layout_inputs(self.repo)['media']['digest']
        self.assertNotEqual(honest, claimed)                         # the cache lied
        self.assertEqual(2, self.run_fin(), self.out)
        self.assertIn('layout was run on different media: run manifest mediaDigest.digest', self.gate_rec('layout')['reason'])
        self.assertIn('render receipt mediaDigest does not match the media', self.gate_rec('render')['reason'])

    def test_media_or_fonts_changed_after_the_layout_are_stale(self):
        for rel in ('ep1/broll/a.mp4', 'fonts/Kanit-Bold.ttf'):
            p = self.repo / 'remotion-composer' / 'public' / rel
            p.write_bytes(p.read_bytes() + b'!')
            self.assertEqual(2, self.run_fin(), (rel, self.out))
            self.assertIn('layout was run on different media', self.gate_rec('layout')['reason'], rel)
            p.write_bytes(p.read_bytes()[:-1])

    def test_every_source_hash_must_equal_the_running_checkout(self):
        self.rehash_manifest(lambda m: m['sourceHashes'].update({'remotion-composer/package-lock.json': '0' * 64}))
        self.assertEqual(2, self.run_fin(), self.out)
        self.assertIn('sourceHashes differ for remotion-composer/package-lock.json', self.gate_rec('layout')['reason'])
        self.rehash_manifest(lambda m: m['sourceHashes'].update({'remotion-composer/package-lock.json': tf.layout_inputs(self.repo)
                                                                ['sourceHashes']['remotion-composer/package-lock.json'],
                                                                'scripts/qc_extra.mjs': '1' * 64}))
        self.assertEqual(2, self.run_fin(), self.out)
        self.assertIn('sourceHashes differ for scripts/qc_extra.mjs', self.gate_rec('layout')['reason'])
        self.rehash_manifest(lambda m: m['sourceHashes'].pop('scripts/qc_extra.mjs'))
        self.assertEqual(0, self.run_fin(), self.out)

    def test_render_receipt_digests_must_be_the_fresh_ones(self):
        for key in ('mediaDigest', 'fontsDigest'):
            self.edit(self.render_path(), lambda d: d.update({key: '0' * 64}))
            self.assertEqual(2, self.run_fin(), self.out)
            self.assertIn('render receipt %s does not match' % key, self.gate_rec('render')['reason'])
            self.rebind()


# ------------------------------------------------------------------------------------------------------------- A7 clean checkout
class CleanCheckoutCheckTests(Base):
    """The repo of the fixture is the 'clean checkout'; the agent's project and public/ are moved OUT of it."""

    def setUp(self):
        super().setUp()
        self.agent = Path(self.tmp) / 'agent'
        self.aproj = self.agent / 'projects' / 'p1'
        self.apub = self.agent / 'remotion-composer' / 'public'
        self.aproj.parent.mkdir(parents=True)
        self.apub.parent.mkdir(parents=True)
        shutil.move(str(self.proj), str(self.aproj))
        shutil.move(str(self.repo / 'remotion-composer' / 'public'), str(self.apub))
        write_receipts(self.repo, name=self.name, proj=self.aproj, public=self.apub)
        self.wd = Path(self.tmp) / 'work'

    def check(self, *extra, work=True, public=True, patch=None):
        argv = ['--check', '--project', self.aproj, '--deliver', self.deliver]
        argv += ['--public-root', self.apub] if public else []
        argv += ['--work-dir', self.wd] if work else []
        return self.run_argv(argv + list(extra), patch=patch)

    def test_inputs_outside_the_repo_pass_and_nothing_is_written_there(self):
        before = tree_state(self.agent)
        self.assertEqual(0, self.check(), self.out)
        self.assertEqual(before, tree_state(self.agent))
        doc = json.loads((self.wd / 'check.json').read_text())
        self.assertEqual(('finished', True, 'clean-checkout'), (doc['status'], doc['would_deliver'], doc['mode']))
        self.assertEqual((str(self.aproj), str(self.apub), str(self.wd)), (doc['project'], doc['public_root'], doc['work_dir']))
        self.assertEqual(tf.CHECK_RECORDS, [g['name'] for g in doc['gates']])
        for f in ('frames.json', 'cuts.json', 'mux-audio.json', 'face-box.json', 'derived.json', 'script.json'):
            self.assertTrue((self.wd / f).is_file(), f)
        self.assertIn('CHECK WORK DIR: %s' % self.wd, self.out)
        self.assertFalse(self.deliver.exists())
        self.assertFalse(Path(str(self.deliver) + '.FAILED.json').exists())
        self.assertFalse((self.wd / '.finalize.lock').exists())

    def test_the_media_come_from_the_public_root_and_the_code_from_the_running_checkout(self):
        # a decoy "agent checkout" next to the agent's dirs: another engine and a garbage lock; neither may be used
        (self.agent / 'remotion-composer' / 'src').mkdir(parents=True)
        (self.agent / 'remotion-composer' / 'src' / 'YtNewsStyle01V4.tsx').write_text('export const tampered = 1;\n')
        (self.agent / '.claude' / 'skills' / self.name / 'scripts').mkdir(parents=True)
        (self.agent / '.claude' / 'skills' / self.name / 'scripts' / 'gates.lock.json').write_text('{"garbage": true}')
        self.assertEqual(0, self.check(), self.out)
        integ = self.argv_of('gate_integrity')
        self.assertEqual(str(self.repo / 'remotion-composer'), integ[0])
        self.assertEqual(str(self.skill), integ[integ.index('--skill-dir') + 1])
        schema = self.argv_of('episode_schema')
        self.assertEqual(str(self.apub), schema[schema.index('--public') + 1])
        frames = self.argv_of('frame_checks')
        self.assertEqual(str(self.apub / 'ep1' / 'broll'), frames[frames.index('--media-root') + 1])
        self.assertEqual(str(self.wd / 'frames.json'), frames[frames.index('--report') + 1])
        self.assertEqual(str(self.apub / 'ep1' / 'avatar.mp4'), self.argv_of('face_box')[2])
        # the running checkout's engine is what is locked and compared: tampering THERE is an integrity refusal
        eng = self.repo / 'remotion-composer' / 'src' / 'YtNewsStyle01V4.tsx'
        eng.write_text(eng.read_text() + '// tampered\n')
        shutil.rmtree(self.wd)
        self.assertEqual(3, self.check(), self.out)

    def test_the_agents_own_qc_finalize_files_are_ignored(self):
        old = self.aproj / 'qc' / 'finalize'
        old.mkdir(parents=True, exist_ok=True)
        (old / 'frames.json').write_text(json.dumps({'pass': True, 'planted': True}))
        (old / 'check.json').write_text(json.dumps({'would_deliver': True, 'planted': True}))
        (old / 'cache').mkdir(exist_ok=True)
        before = tree_state(self.agent)
        self.assertEqual(0, self.check(), self.out)
        content = self.argv_of('lint_content')
        self.assertEqual(str(self.wd / 'frames.json'), content[content.index('--frames-report') + 1])
        self.assertNotIn(str(old), json.dumps([self.argv_of(n) for n in ('lint_content', 'frame_checks', 'face_box')]))
        self.assertEqual(before, tree_state(self.agent))
        self.assertNotIn('planted', (self.wd / 'frames.json').read_text())
        self.behavior(frame_checks={'pass': False, 'exit': 1})
        shutil.rmtree(self.wd)
        self.assertEqual(1, self.check(), self.out)                 # the planted pass of the agent's own frames.json counts for nothing
        self.assertFalse(json.loads((self.wd / 'check.json').read_text())['would_deliver'])
        self.assertEqual(before, tree_state(self.agent))

    def test_a_default_work_dir_is_a_new_temp_dir_named_at_the_end(self):
        self.assertEqual(0, self.check(work=False), self.out)
        line = next(x for x in self.out.splitlines() if x.startswith('CHECK RESULT FILE: '))
        cj = Path(line.split(': ', 1)[1])
        self.addCleanup(shutil.rmtree, cj.parent, True)
        self.assertTrue(cj.is_file())
        self.assertTrue(cj.parent.name.startswith('yt-news-v4-check-'))
        self.assertTrue(str(cj.parent).startswith(str(Path(tempfile.gettempdir()).resolve())))
        self.assertIn('CHECK WORK DIR: %s' % cj.parent, self.out)

    def test_a_work_dir_that_is_not_empty_or_inside_the_agent_dirs_is_refused(self):
        self.wd.mkdir()
        (self.wd / 'old.txt').write_text('an earlier result')
        self.assertEqual(2, self.check(), self.out)
        self.assertEqual(['old.txt'], os.listdir(self.wd))
        self.assertIn('must be an empty directory or not exist yet', self.out)
        before = tree_state(self.agent)
        for inner in (self.aproj / 'qc' / 'w', self.apub / 'w', self.aproj):
            self.wd = inner
            self.assertEqual(2, self.check(), self.out)
            self.assertIn('the check must not write there', self.out)
            self.assertEqual(before, tree_state(self.agent))         # not even the (refused) work dir itself was created

    def test_an_outside_project_with_plain_check_never_writes_into_it(self):
        before = tree_state(self.agent)
        code = self.check(work=False, public=False)          # no --public-root: the repo has no public/ -> the environment check fails
        self.assertEqual(4, code, self.out)
        self.assertEqual(before, tree_state(self.agent))
        line = next(x for x in self.out.splitlines() if x.startswith('CHECK RESULT FILE: '))
        cj = Path(line.split(': ', 1)[1])
        self.addCleanup(shutil.rmtree, cj.parent, True)
        self.assertEqual('clean-checkout', json.loads(cj.read_text())['mode'])

    def test_a_real_delivery_refuses_the_check_only_options_and_an_outside_project(self):
        for extra in (['--public-root', self.apub], ['--work-dir', self.wd]):
            with self.assertRaises(SystemExit) as cm, contextlib.redirect_stderr(io.StringIO()):
                self.run_argv(['--project', self.aproj, '--deliver', self.deliver] + extra)
            self.assertEqual(2, cm.exception.code)
        shutil.move(str(self.apub), str(self.repo / 'remotion-composer' / 'public'))      # the repo has its media again
        before = tree_state(self.agent)
        self.assertEqual(2, self.run_argv(['--project', self.aproj, '--deliver', self.deliver]), self.out)
        self.assertIn('outside the repository', ' '.join(self.failed()['reasons']))
        self.assertNotDelivered()
        self.assertEqual(before, tree_state(self.agent))


# ------------------------------------------------------------------------------------------------------------- A9 budgets
class CheckBudgetTests(Base):
    def test_check_has_its_own_constant_budget(self):
        m = self.module()
        self.assertEqual((450, 600), (m.TOTAL_BUDGET_SEC, m.CHECK_TOTAL_BUDGET_SEC))
        self.assertEqual(4, self.run_fin('--check', patch=lambda m: setattr(m, 'CHECK_TOTAL_BUDGET_SEC', 0)), self.out)
        self.assertIn('CHECK FAIL (exit 4): time budget (0s) exhausted during phase "integrity"', self.out)
        self.assertEqual(0, self.run_fin('--check', patch=lambda m: setattr(m, 'TOTAL_BUDGET_SEC', 0)), self.out)
        self.assertEqual(0, self.run_fin(patch=lambda m: setattr(m, 'CHECK_TOTAL_BUDGET_SEC', 0)), self.out)      # a delivery: 450
        self.assertTrue(self.deliver.exists())


if __name__ == '__main__':
    unittest.main()
