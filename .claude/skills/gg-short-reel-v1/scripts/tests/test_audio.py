import tempfile
import unittest
from pathlib import Path

import test_support as ts
from test_support import needs_ffmpeg


class AudioUnitTests(unittest.TestCase):
    def test_not_configured_default_is_gone(self):
        import audio
        self.assertFalse(hasattr(audio, "NotConfiguredMusicProvider"))
        self.assertFalse(audio.FileMusicProvider({}).is_paid)

    def test_loudness_acceptance(self):
        import audio
        for i, tp, ok in [(-14, -1.5, True), (-13.0, -1.0, True), (-15.0, -1.2, True), (-12.9, -2, False),
                          (-15.1, -2, False), (-14, -0.9, False), (float("nan"), -2, False), (-14, float("inf"), False)]:
            self.assertEqual(ok, audio.loudness_ok(i, tp), (i, tp))

    def test_parse_loudnorm_rejects_garbage_and_silence(self):
        import audio
        import common
        for text in ("", "{}", '{"input_i":"-inf","input_tp":"-70","input_lra":"0","input_thresh":"-70","target_offset":"0"}'):
            with self.assertRaises(common.GgError):
                audio.parse_loudnorm(text)
        d = audio.parse_loudnorm('noise\n{"input_i":"-20.5","input_tp":"-3.1","input_lra":"2.0",'
                                 '"input_thresh":"-30.0","target_offset":"0.4"}')
        self.assertEqual(-20.5, d["input_i"])


@needs_ffmpeg
class AudioFfmpegTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()

    def test_music_bed_is_trimmed_and_normalised(self):
        import audio
        import common
        long_ = ts.FakeMusic(seconds=20).get_music(12.0, None, self.tmp / "m.wav")  # longer than the video: trimmed, never looped
        out = self.tmp / "bed.wav"
        audio.build_music_bed(long_, 12.0, out, common.Deadline(120))
        info = ts.probe(out)
        self.assertAlmostEqual(12.0, float(info["format"]["duration"]), delta=0.05)
        i, tp = ts.measure_loudness(out)
        self.assertAlmostEqual(-14.0, i, delta=0.7)
        self.assertLessEqual(tp, -1.0)

    def test_validate_music_rejects_missing_empty_noaudio(self):
        import audio
        import common
        dl = common.Deadline(60)
        with self.assertRaises(common.GgError):
            audio.validate_music(self.tmp / "nope.wav", dl)
        empty = self.tmp / "e.wav"
        empty.write_bytes(b"")
        with self.assertRaises(common.GgError):
            audio.validate_music(empty, dl)
        noaudio = ts.FakeMusic(mode="noaudio").get_music(10, None, self.tmp / "v.wav")
        with self.assertRaises(common.GgError):
            audio.validate_music(noaudio, dl)
        ok = ts.FakeMusic().get_music(10, None, self.tmp / "ok.wav")   # 12 s
        audio.validate_music(ok, dl)
        audio.validate_music(ok, dl, min_duration_s=12.0)
        with self.assertRaises(common.GgError) as cm:
            audio.validate_music(ok, dl, min_duration_s=13.0)
        self.assertIn("เพลงสั้นกว่าวิดีโอ", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
