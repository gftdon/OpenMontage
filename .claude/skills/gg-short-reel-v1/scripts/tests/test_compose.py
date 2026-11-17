import tempfile
import unittest
from pathlib import Path

import test_support as ts
from test_support import needs_ffmpeg


@needs_ffmpeg
class ComposeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()

    def _shots(self, specs):
        import compose
        out = []
        for i, s in enumerate(specs, start=1):
            f = self.tmp / f"s{i}.mp4"
            ts.make_clip(f, w=s["w"], h=s["h"], frames=s["frames"], base=s["base"], step=s["step"])
            out.append(compose.Shot(seq=i, path=f, continues=s["continues"]))
        return out

    def test_a_continuation_drops_first_frame_only(self):
        import common
        import compose
        # A: levels 20..107, B continues from A (B[0] == A[last] == 107, then +3/frame), C is a plain new shot
        shots = self._shots([
            {"w": 416, "h": 752, "frames": 30, "base": 20, "step": 3, "continues": False},
            {"w": 400, "h": 736, "frames": 30, "base": 107, "step": 3, "continues": True},
            {"w": 416, "h": 752, "frames": 20, "base": 200, "step": 1, "continues": False},
        ])
        out = self.tmp / "base.mp4"
        compose.build_base(shots, out, common.Deadline(120))
        expected = [20 + 3 * n for n in range(30)] + [107 + 3 * k for k in range(1, 30)] + [200 + n for n in range(20)]
        levels = ts.frame_levels(out)
        self.assertEqual(30 + 29 + 20, len(levels), "frame count must be N1+N2-1+N3")
        for i, (got, want) in enumerate(zip(levels, expected)):
            self.assertAlmostEqual(want, got, delta=2.5, msg=f"frame {i}")
        # boundary: the frame after A's last is B's SECOND frame (110), never a repeat of 107
        self.assertAlmostEqual(110, levels[30], delta=2.5)
        md5 = ts.frame_md5s(out)
        self.assertNotEqual(md5[29], md5[30])
        self.assertEqual(len(md5), len(set(md5)), "no duplicate frame anywhere")
        # non-continuation shot C is not trimmed: its first frame (200) is present
        self.assertAlmostEqual(200, levels[59], delta=2.5)

    def test_b_mixed_sizes_two_video_streams_conform(self):
        import common
        import compose
        shots = self._shots([
            {"w": 416, "h": 752, "frames": 30, "base": 20, "step": 3, "continues": False},
            {"w": 400, "h": 736, "frames": 30, "base": 20, "step": 3, "continues": False},
        ])
        out = self.tmp / "base.mp4"
        compose.build_base(shots, out, common.Deadline(120))
        info = ts.probe(out)
        v = [s for s in info["streams"] if s["codec_type"] == "video"]
        self.assertEqual(1, len(v))
        self.assertEqual([], [s for s in info["streams"] if s["codec_type"] == "audio"], "source audio dropped")
        self.assertEqual((1080, 1920), (v[0]["width"], v[0]["height"]))
        self.assertIn(v[0]["sample_aspect_ratio"], ("1:1",))
        self.assertEqual("yuv420p", v[0]["pix_fmt"])
        self.assertEqual("h264", v[0]["codec_name"])
        self.assertEqual("30/1", v[0]["r_frame_rate"])
        self.assertEqual("30/1", v[0]["avg_frame_rate"])
        self.assertEqual(60, len(ts.frame_levels(out)))

    def test_probe_shot_rejects_file_without_video(self):
        import common
        import compose
        bad = self.tmp / "audio-only.mp4"
        import subprocess
        subprocess.run([ts.FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=d=2", str(bad)], check=True)
        with self.assertRaises(common.GgError):
            compose.probe_shot(bad, common.Deadline(60))

    def test_estimate_duration_accounts_for_dropped_frames(self):
        import common
        import compose
        shots = self._shots([
            {"w": 416, "h": 752, "frames": 30, "base": 20, "step": 3, "continues": False},
            {"w": 416, "h": 752, "frames": 30, "base": 20, "step": 3, "continues": True},
        ])
        est = compose.estimate_duration(shots, common.Deadline(60))
        self.assertAlmostEqual(59 / 30, est, delta=0.05)


if __name__ == "__main__":
    unittest.main()
