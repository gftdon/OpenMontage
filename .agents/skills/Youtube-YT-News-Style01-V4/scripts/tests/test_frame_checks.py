"""Tests for frame_checks.py (WP2b). Media is generated with ffmpeg lavfi / PIL in a temp dir."""
import importlib.util
import json
import random
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
HAVE_SWIFT = bool(shutil.which("swiftc") or shutil.which("swift"))


def load():
    spec = importlib.util.spec_from_file_location("frame_checks", SCRIPTS / "frame_checks.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


fc = load()


def ff(*args):
    r = subprocess.run([FFMPEG, "-v", "error", "-y", *args], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode()[-500:])


def busy_png(path, text=None, seed=1, size=(640, 360)):
    """Colourful busy background; optional big white-with-black-outline text."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    rnd = random.Random(seed)
    im = Image.new("RGB", size, (40, 90, 140))
    d = ImageDraw.Draw(im)
    for _ in range(60):
        x, y = rnd.randrange(size[0]), rnd.randrange(size[1])
        r = rnd.randrange(20, 90)
        d.ellipse([x - r, y - r, x + r, y + r], fill=tuple(rnd.randrange(30, 200) for _ in range(3)))
    im = im.filter(ImageFilter.GaussianBlur(3))
    if text:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Black.ttf", 96)
        d = ImageDraw.Draw(im)
        bb = d.textbbox((0, 0), text, font=font)
        xy = ((size[0] - (bb[2] - bb[0])) // 2, (size[1] - (bb[3] - bb[1])) // 2 - bb[1])
        d.text(xy, text, font=font, fill="white", stroke_width=4, stroke_fill="black")
    im.save(path)


def still_mp4(png, out, secs, fps=5):
    ff("-loop", "1", "-framerate", str(fps), "-i", str(png), "-t", str(secs), "-pix_fmt", "yuv420p", str(out))


def ok_lines(lines=()):
    return {"ok": True, "lines": list(lines)}


class Media:
    """Synthetic clips shared by all tests (built once)."""
    dir = None

    @classmethod
    def build(cls):
        if cls.dir:
            return
        d = Path(tempfile.mkdtemp(prefix="fc-test-"))
        cls.dir = d
        ff("-f", "lavfi", "-i", "color=c=white:s=320x180:r=10:d=4", "-pix_fmt", "yuv420p", str(d / "white.mp4"))
        ff("-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=4", "-pix_fmt", "yuv420p", str(d / "black.mp4"))
        ff("-f", "lavfi", "-i", "testsrc2=s=640x360:r=10:d=6", "-pix_fmt", "yuv420p", str(d / "clean.mp4"))
        ff("-f", "lavfi", "-i", "testsrc2=s=640x360:r=10:d=6", "-vf",
           "drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='between(t,2.05,2.25)'",
           "-pix_fmt", "yuv420p", str(d / "flash.mp4"))
        # still clips with text
        busy_png(d / "bg1.png", seed=1)
        busy_png(d / "bg2.png", seed=2)
        busy_png(d / "wm.png", "PIXABAY", seed=3)
        busy_png(d / "sub.png", "SUBSCRIBE", seed=4)
        still_mp4(d / "bg1.png", d / "bg1.mp4", 4)
        still_mp4(d / "bg2.png", d / "bg2.mp4", 4)
        still_mp4(d / "wm.png", d / "wm.mp4", 4)
        still_mp4(d / "sub.png", d / "sub.mp4", 4)
        # 10 s clip: clean for 5 s, watermark for the last 5 s
        ff("-loop", "1", "-framerate", "5", "-t", "5", "-i", str(d / "bg1.png"),
           "-loop", "1", "-framerate", "5", "-t", "5", "-i", str(d / "wm.png"),
           "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p", str(d / "half_wm.mp4"))
        # padded clips (crop proposer)
        ff("-f", "lavfi", "-i", "testsrc2=s=800x450:r=10:d=5", "-vf", "pad=1280:720:240:135:black",
           "-pix_fmt", "yuv420p", str(d / "boxed.mp4"))
        ff("-f", "lavfi", "-i", "testsrc2=s=960x720:r=10:d=5", "-vf", "pad=1280:720:160:0:black",
           "-pix_fmt", "yuv420p", str(d / "pillar.mp4"))
        shutil.copy(d / "clean.mp4", d / "clean_copy.mp4")


def setUpModule():
    Media.build()


def tearDownModule():
    if Media.dir:
        shutil.rmtree(Media.dir, ignore_errors=True)


def codes(issues):
    return [i["code"] for i in issues]


class PixelTests(unittest.TestCase):
    def px(self, name, a=0, b=4, crop=None):
        return fc.check_pixels(Media.dir / name, a, b, crop)

    def test_white_clip_is_blank_white(self):
        r = self.px("white.mp4")
        self.assertEqual(["blank-white"], codes(r["issues"]))
        self.assertAlmostEqual(0.0, r["issues"][0]["range"][0])

    def test_black_clip_is_near_black(self):
        self.assertEqual(["near-black"], codes(self.px("black.mp4")["issues"]))

    def test_testsrc2_is_clean(self):
        self.assertEqual([], self.px("clean.mp4", 0, 6)["issues"])

    def test_short_white_flash_is_clean(self):
        self.assertEqual([], self.px("flash.mp4", 0, 6)["issues"])

    def test_blank_run_needs_half_a_second(self):
        stats = [{"t": 0.0, "mean": 250, "range": 2}, {"t": 0.5, "mean": 100, "range": 90}]
        self.assertEqual([], fc.pixel_issues(stats, 0, 1.0))
        stats = [{"t": 0.0, "mean": 250, "range": 2}, {"t": 0.5, "mean": 250, "range": 2}, {"t": 1.0, "mean": 100, "range": 90}]
        self.assertEqual(["blank-white"], codes(fc.pixel_issues(stats, 0, 1.5)))

    def test_cli_pixels_exit_codes(self):
        self.assertEqual(1, fc.main(["pixels", "--video", str(Media.dir / "white.mp4"), "--in", "0", "--out", "4"]))
        self.assertEqual(0, fc.main(["pixels", "--video", str(Media.dir / "clean.mp4"), "--in", "0", "--out", "5"]))
        self.assertEqual(2, fc.main(["pixels", "--video", str(Media.dir / "nope.mp4"), "--in", "0", "--out", "5"]))
        self.assertEqual(2, fc.main(["pixels", "--video", str(Media.dir / "clean.mp4"), "--in", "0", "--out", "5", "--crop", "1:2"]))

    def test_crop_applies_to_pixels(self):
        # the boxed clip is black outside the 800x450 content box
        self.assertIn("near-black", codes(self.px("boxed.mp4", 0, 5, (0, 0, 200, 100))["issues"]))
        self.assertEqual([], self.px("boxed.mp4", 0, 5, (240, 135, 800, 450))["issues"])


class OcrBatchTests(unittest.TestCase):
    def test_batches_all_frames_in_one_call(self):
        calls = []

        def fake(paths):
            calls.append(list(paths))
            return {p: ok_lines() for p in paths}

        paths = [f"/x/{i}.jpg" for i in range(7)]
        out = fc.run_ocr(fake, paths)
        self.assertEqual(1, len(calls))
        self.assertEqual(paths, calls[0])
        self.assertEqual(set(paths), set(out))

    def test_whole_episode_is_one_invocation(self):
        calls = []

        def fake(paths):
            calls.append(list(paths))
            return {p: ok_lines() for p in paths}

        beats = [{"t": 0, "media": "clip", "src": "clean", "origin": "source"},
                 {"t": 10, "media": "broll", "src": "bg1", "origin": "stock"},
                 {"t": 20, "mode": "full"}]
        rep = fc.cmd_cutaways(self.write(beats), None, [Media.dir], Media.dir / "fr", fake, episode_end=30)
        self.assertEqual(1, len(calls))
        self.assertEqual(sum(len(b["frames"]) for b in rep["beats"]), len(calls[0]))
        self.assertGreaterEqual(len(calls[0]), 10)   # >= 5 frames per range

    def test_frames_per_range(self):
        self.assertEqual(5, len(fc.ocr_frame_times(0, 4)))
        self.assertEqual(5, len(fc.ocr_frame_times(0, 10)))
        self.assertEqual(8, len(fc.ocr_frame_times(2, 18)))
        ts = fc.ocr_frame_times(0, 10)
        self.assertTrue(all(0 < t < 10 for t in ts))

    def test_all_frames_failing_is_tool_missing(self):
        with self.assertRaises(fc.ToolMissing):
            fc.run_ocr(lambda ps: {p: {"ok": False, "error": "x"} for p in ps}, ["/a.jpg", "/b.jpg"])

    def test_failing_runner_exits_4(self):
        def broken(paths):
            raise fc.ToolMissing("swift not found")

        beats = Media.dir / "beats4.json"
        beats.write_text(json.dumps([{"t": 0, "media": "clip", "src": "clean", "origin": "source"}, {"t": 5, "mode": "full"}]))
        rc = fc.main(["cutaways", "--beats", str(beats), "--media-root", str(Media.dir), "--frames-dir", str(Media.dir / "fr4"),
                      "--report", str(Media.dir / "r4.json")], ocr_runner=broken)
        self.assertEqual(4, rc)
        self.assertFalse((Media.dir / "r4.json").exists())
        rc = fc.main(["watermark", "--video", str(Media.dir / "clean.mp4"), "--in", "0", "--out", "4",
                      "--frames-dir", str(Media.dir / "fr5")], ocr_runner=broken)
        self.assertEqual(4, rc)

    def test_missing_swift_is_tool_missing(self):
        real_which = shutil.which
        try:
            fc.shutil.which = lambda name, *a, **k: None
            with self.assertRaises(fc.ToolMissing):
                fc.VisionOcr(cache_dir=Media.dir / "nocache")(["/x.jpg"])
        finally:
            fc.shutil.which = real_which

    def write(self, beats):
        p = Media.dir / "beats_tmp.json"
        p.write_text(json.dumps(beats))
        return p


class RealOcrMixin:
    """One compiled Vision OCR binary shared by the OCR tests."""
    _ocr = None

    @classmethod
    def ocr(cls):
        if RealOcrMixin._ocr is None:
            RealOcrMixin._ocr = fc.VisionOcr(cache_dir=Media.dir / "ocrcache")
        return RealOcrMixin._ocr


@unittest.skipUnless(HAVE_SWIFT, "swift is not installed: Vision OCR tests skipped (CLI must exit 4, see OcrBatchTests)")
class WatermarkTests(RealOcrMixin, unittest.TestCase):
    def wm(self, name, a=0, b=4):
        return fc.cmd_watermark(Media.dir / name, a, b, None, Media.dir / "wfr", self.ocr())

    def test_watermark_clip(self):
        r = self.wm("wm.mp4")
        self.assertEqual(["watermark"], codes(r["issues"]))
        self.assertIn("pixabay", r["issues"][0]["detail"].lower())
        self.assertTrue(any("PIXABAY" in " ".join(f["ocr"]).upper() for f in r["frames"]))

    def test_subscribe_clip(self):
        self.assertEqual(["promo-text"], codes(self.wm("sub.mp4")["issues"]))

    def test_clean_clip(self):
        self.assertEqual([], self.wm("bg1.mp4")["issues"])
        self.assertEqual([], self.wm("clean.mp4", 0, 6)["issues"])

    def test_crop_outside_the_text_is_clean(self):
        # PIXABAY sits in the middle; a crop of the top 60 px must not see it
        r = fc.cmd_watermark(Media.dir / "wm.mp4", 0, 4, (0, 0, 640, 60), Media.dir / "wfr2", self.ocr())
        self.assertEqual([], r["issues"])

    def test_cli_exit_1(self):
        rc = fc.main(["watermark", "--video", str(Media.dir / "wm.mp4"), "--in", "0", "--out", "4", "--frames-dir",
                      str(Media.dir / "wfr3"), "--cache-dir", str(Media.dir / "ocrcache")])
        self.assertEqual(1, rc)


@unittest.skipUnless(HAVE_SWIFT, "swift is not installed: Vision OCR tests skipped (CLI must exit 4, see OcrBatchTests)")
class CutawayTests(RealOcrMixin, unittest.TestCase):
    def run_beats(self, beats, **kw):
        p = Media.dir / "beats_cut.json"
        p.write_text(json.dumps(beats))
        return fc.cmd_cutaways(p, kw.get("cuts"), [Media.dir], Media.dir / "cfr", self.ocr(), episode_end=kw.get("end", 200))

    def test_synthetic_episode(self):
        beats = [
            {"t": 0, "mode": "full"},
            {"t": 10, "media": "clip", "src": "bg1", "origin": "source"},
            {"t": 20, "media": "broll", "src": "wm", "origin": "stock"},
            {"t": 30, "media": "broll", "src": "does_not_exist", "origin": "stock"},
            {"t": 40, "mode": "full"},
        ]
        rep = self.run_beats(beats)
        by = {}
        for i in rep["issues"]:
            by.setdefault(i["beat_t"], []).append(i["code"])
        self.assertNotIn(10, by)
        self.assertEqual(["watermark"], by[20])
        self.assertEqual(["media-missing"], by[30])
        self.assertFalse(rep["pass"])
        self.assertEqual("vision-swift", rep["tools"]["ocr"])
        self.assertEqual({"schema", "version", "pass", "issues", "beats", "tools", "inputs", "seconds"}, set(rep))
        self.assertEqual(2, len(rep["beats"]))
        self.assertTrue(rep["beats"][0]["loops"])  # 10 s beat on a 4 s clip
        for b in rep["beats"]:
            for f in b["frames"]:
                self.assertTrue(Path(f["path"]).is_file())
                self.assertEqual(16, len(f["dhash"]))

    def test_from_offset_selects_the_shown_range(self):
        base = {"media": "clip", "src": "half_wm", "origin": "source"}
        clean = self.run_beats([{"t": 0, **base, "from": 0}, {"t": 4, "mode": "full"}])        # shows 0..4 -> clean half
        self.assertEqual([], clean["issues"], clean["issues"])
        self.assertEqual([0.0, 4.0], clean["beats"][0]["shown"])
        flagged = self.run_beats([{"t": 0, **base, "from": 6}, {"t": 3, "mode": "full"}])      # shows 6..9 -> watermark half
        self.assertEqual(["watermark"], codes(flagged["issues"]))
        self.assertEqual([6.0, 9.0], flagged["beats"][0]["shown"])

    def test_loop_wrap_is_checked(self):
        # from=8, 4 s beat on a 10 s clip -> shows 8..10 and wraps to 0..2
        rep = self.run_beats([{"t": 0, "media": "clip", "src": "half_wm", "origin": "source", "from": 8}, {"t": 4, "mode": "full"}])
        self.assertTrue(rep["beats"][0]["loops"])
        self.assertEqual([0.0, 2.0], rep["beats"][0]["shown_wrapped"])

    def test_src_crop_hides_the_text(self):
        beat = {"t": 0, "media": "broll", "src": "wm", "origin": "stock", "srcCrop": {"x": 0, "y": 0, "w": 640, "h": 60}}
        rep = self.run_beats([beat, {"t": 4, "mode": "full"}])
        self.assertEqual([], rep["issues"])
        self.assertEqual([0, 0, 640, 60], rep["beats"][0]["srcCrop"])

    def test_path_from_cuts_json_is_used(self):
        cuts = Media.dir / "cuts.json"
        cuts.write_text(json.dumps({"clips": {"elsewhere": {"path": str(Media.dir / "wm.mp4")}}}))
        rep = self.run_beats([{"t": 0, "media": "clip", "src": "elsewhere", "origin": "source"}, {"t": 4, "mode": "full"}], cuts=cuts)
        self.assertEqual(["watermark"], codes(rep["issues"]))

    def test_shot_reuse_within_60s(self):
        beats = [{"t": 0, "media": "clip", "src": "clean", "origin": "source"},
                 {"t": 40, "media": "clip", "src": "clean_copy", "origin": "source"},
                 {"t": 80, "mode": "full"}]
        rep = self.run_beats(beats)
        self.assertEqual(["shot-reuse"], codes(rep["issues"]))
        self.assertEqual(40, rep["issues"][0]["beat_t"])
        self.assertIn("t=0", rep["issues"][0]["detail"])

    def test_no_shot_reuse_70s_apart(self):
        beats = [{"t": 0, "media": "clip", "src": "clean", "origin": "source"},
                 {"t": 70, "media": "clip", "src": "clean_copy", "origin": "source"},
                 {"t": 110, "mode": "full"}]
        self.assertEqual([], self.run_beats(beats)["issues"])

    def test_different_shots_are_not_reuse(self):
        beats = [{"t": 0, "media": "clip", "src": "bg1", "origin": "source"},
                 {"t": 10, "media": "clip", "src": "bg2", "origin": "source"},
                 {"t": 20, "mode": "full"}]
        self.assertEqual([], self.run_beats(beats)["issues"])


class ReuseUnitTests(unittest.TestCase):
    def beat(self, t, h, flat=False):
        return {"t": t, "src": f"s{t}", "origin": "source", "frames": [{"t": 1.0, "dhash": h, "flat": flat}]}

    def test_distance_threshold(self):
        a = "0f0f0f0f0f0f0f0f"
        near = f"{int(a, 16) ^ 0b111111:016x}"      # distance 6
        far = f"{int(a, 16) ^ 0b1111111:016x}"      # distance 7
        self.assertEqual(["shot-reuse"], codes(fc.reuse_issues([self.beat(0, a), self.beat(10, near)])))
        self.assertEqual([], fc.reuse_issues([self.beat(0, a), self.beat(10, far)]))

    def test_flat_frames_are_not_compared(self):
        z = "0" * 16
        self.assertEqual([], fc.reuse_issues([self.beat(0, z, True), self.beat(10, z, True)]))


class CropTests(unittest.TestCase):
    def near(self, got, want, tol=8):
        for k, v in zip("xywh", want):
            self.assertLessEqual(abs(got[k] - v), tol, (k, got, want))

    def test_propose_letterboxed_box(self):
        r = fc.propose_crop(Media.dir / "boxed.mp4", 0, 5)
        self.near(r, (240, 135, 800, 450))
        self.assertGreater(r["confidence"], 0.5)
        self.assertIn("reason", r)

    def test_propose_pillarbox_snaps_to_16_9(self):
        r = fc.propose_crop(Media.dir / "pillar.mp4", 0, 5)
        self.near(r, (160, 90, 960, 540))
        self.assertLess(abs(r["w"] / r["h"] / (16 / 9) - 1), 0.02)

    def test_propose_no_bars_is_full_frame(self):
        r = fc.propose_crop(Media.dir / "clean.mp4", 0, 6)
        self.near(r, (0, 0, 640, 360), tol=2)

    def test_check_positive(self):
        self.assertTrue(fc.check_crop(Media.dir / "boxed.mp4", 0, 5, (240, 135, 800, 450))["pass"])

    def test_check_negatives(self):
        v = Media.dir / "boxed.mp4"
        self.assertEqual(["crop-out-of-bounds"], codes(fc.check_crop(v, 0, 5, (700, 0, 800, 450))["errors"]))
        self.assertIn("crop-aspect", codes(fc.check_crop(v, 0, 5, (240, 135, 800, 600))["errors"]))
        self.assertIn("crop-too-small", codes(fc.check_crop(v, 0, 5, (240, 135, 480, 270))["errors"]))

    def test_check_blank_inside_is_an_error(self):
        # 320x180 clips are below the minimum width, so use a padded white clip
        d = Media.dir / "white_big.mp4"
        if not d.exists():
            ff("-f", "lavfi", "-i", "color=c=white:s=1280x720:r=10:d=3", "-pix_fmt", "yuv420p", str(d))
        r = fc.check_crop(d, 0, 3, (0, 0, 1280, 720))
        self.assertEqual(["crop-blank-white"], codes(r["errors"]))
        d = Media.dir / "black_big.mp4"
        if not d.exists():
            ff("-f", "lavfi", "-i", "color=c=black:s=1280x720:r=10:d=3", "-pix_fmt", "yuv420p", str(d))
        self.assertEqual(["crop-near-black"], codes(fc.check_crop(d, 0, 3, (0, 0, 1280, 720))["errors"]))

    def test_cli_exit_codes(self):
        v = str(Media.dir / "boxed.mp4")
        self.assertEqual(0, fc.main(["crop-propose", "--video", v, "--in", "0", "--out", "5"]))
        self.assertEqual(0, fc.main(["crop-check", "--video", v, "--in", "0", "--out", "5", "--crop", "240:135:800:450"]))
        self.assertEqual(1, fc.main(["crop-check", "--video", v, "--in", "0", "--out", "5", "--crop", "240:135:800:600"]))


if __name__ == "__main__":
    unittest.main()
