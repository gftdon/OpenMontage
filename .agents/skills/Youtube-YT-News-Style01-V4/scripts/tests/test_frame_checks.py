"""Tests for frame_checks.py (WP2b, wave 2). Media is generated with ffmpeg lavfi / PIL in a temp dir.

Coordinates: every srcCrop / --crop / crop-propose box is in pixels of a 1920x1080 source frame and is
scaled to the real file resolution; the synthetic files here are 640x360 or 1280x720 on purpose.
"""
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


def ui_png(path, bg, fg, size=(640, 360)):
    """A 'screen recording': flat background with a few small UI blocks (~3 % of the pixels)."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    for i in range(4):
        d.rectangle([40 + i * 5, 40 + i * 60, 40 + i * 5 + 70, 40 + i * 60 + 10], fill=fg)
    d.rectangle([400, 60, 520, 100], fill=fg)
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
        ff("-f", "lavfi", "-i", "color=c=gray:s=320x180:r=10:d=4", "-pix_fmt", "yuv420p", str(d / "gray.mp4"))
        ff("-f", "lavfi", "-i", "testsrc2=s=640x360:r=10:d=6", "-pix_fmt", "yuv420p", str(d / "clean.mp4"))
        ff("-f", "lavfi", "-i", "testsrc2=s=640x360:r=10:d=6", "-vf",
           "drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='between(t,2.05,2.25)'",
           "-pix_fmt", "yuv420p", str(d / "flash.mp4"))
        ui_png(d / "dark_ui.png", (8, 8, 10), (235, 235, 240))
        ui_png(d / "white_ui.png", (252, 252, 252), (30, 30, 40))
        still_mp4(d / "dark_ui.png", d / "dark_ui.mp4", 4)
        still_mp4(d / "white_ui.png", d / "white_ui.mp4", 4)
        busy_png(d / "bg1.png", seed=1)
        busy_png(d / "bg2.png", seed=2)
        busy_png(d / "wm.png", "PIXABAY", seed=3)
        busy_png(d / "sub.png", "SUBSCRIBE", seed=4)
        still_mp4(d / "bg1.png", d / "bg1.mp4", 4)
        still_mp4(d / "bg2.png", d / "bg2.mp4", 4)
        still_mp4(d / "wm.png", d / "wm.mp4", 4)
        still_mp4(d / "sub.png", d / "sub.mp4", 4)
        # 10 s clip: clean for 5 s, watermark for the last 5 s; and the mirror image
        ff("-loop", "1", "-framerate", "5", "-t", "5", "-i", str(d / "bg1.png"),
           "-loop", "1", "-framerate", "5", "-t", "5", "-i", str(d / "wm.png"),
           "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p", str(d / "half_wm.mp4"))
        ff("-loop", "1", "-framerate", "5", "-t", "3", "-i", str(d / "wm.png"),
           "-loop", "1", "-framerate", "5", "-t", "7", "-i", str(d / "bg1.png"),
           "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p", str(d / "wm_first.mp4"))
        # padded clips (crop proposer): 1280x720 files, inner picture 800x450
        ff("-f", "lavfi", "-i", "testsrc2=s=800x450:r=10:d=5", "-vf", "pad=1280:720:240:135:black",
           "-pix_fmt", "yuv420p", str(d / "boxed.mp4"))
        ff("-f", "lavfi", "-i", "testsrc2=s=800x450:r=10:d=5", "-vf", "pad=1280:720:60:30:black",
           "-pix_fmt", "yuv420p", str(d / "boxed_b.mp4"))
        ff("-f", "lavfi", "-i", "testsrc2=s=960x720:r=10:d=5", "-vf", "pad=1280:720:160:0:black",
           "-pix_fmt", "yuv420p", str(d / "pillar.mp4"))
        ff("-f", "lavfi", "-i", "color=c=white:s=1280x720:r=10:d=3", "-pix_fmt", "yuv420p", str(d / "white_big.mp4"))
        ff("-f", "lavfi", "-i", "color=c=black:s=1280x720:r=10:d=3", "-pix_fmt", "yuv420p", str(d / "black_big.mp4"))
        shutil.copy(d / "clean.mp4", d / "clean_copy.mp4")


def setUpModule():
    Media.build()


def tearDownModule():
    if Media.dir:
        shutil.rmtree(Media.dir, ignore_errors=True)


def codes(issues):
    return [i["code"] for i in issues]


def with_layout(beats):
    """Source clip beats need a layout for static-hold (the visible region depends on it): default `stage` where a test did not say."""
    return [{"layout": "stage", **b} if b.get("media") == "clip" and b.get("origin") == "source" and b.get("mode") != "full" else b for b in beats]


def S(median, info, t=0.0, mean=None):
    return {"t": t, "mean": median if mean is None else mean, "median": median, "info": info}


class PixelTests(unittest.TestCase):
    def px(self, name, a=0, b=4, crop=None):
        return fc.check_pixels(Media.dir / name, a, b, crop)

    def blank(self, name, a=0, b=4, crop=None):
        return self.px(name, a, b, crop)["issues"]

    def test_white_clip_is_blank_frame_white(self):
        r = self.blank("white.mp4")
        self.assertEqual(["blank-frame"], codes(r))
        self.assertIn("white", r[0]["detail"])
        self.assertAlmostEqual(0.0, r[0]["range"][0])

    def test_black_clip_is_blank_frame_black(self):
        r = self.blank("black.mp4")
        self.assertEqual(["blank-frame"], codes(r))
        self.assertIn("black", r[0]["detail"])

    def test_mid_gray_clip_is_blank_frame_flat(self):
        r = self.blank("gray.mp4")
        self.assertEqual(["blank-frame"], codes(r))
        self.assertIn("flat", r[0]["detail"])

    def test_testsrc2_is_clean(self):
        self.assertEqual([], self.blank("clean.mp4", 0, 6))

    def test_dark_ui_is_not_blank(self):
        # mean luma is ~12 (the old near-black rule flagged this); ~3 % of the pixels carry information
        self.assertEqual([], self.blank("dark_ui.mp4"))
        self.assertEqual([], self.blank("white_ui.mp4"))

    def test_short_white_flash_is_clean(self):
        self.assertEqual([], self.blank("flash.mp4", 0, 6))

    def test_summary_keeps_mean_and_adds_info_fraction(self):
        s = self.px("dark_ui.mp4")["luma"]
        for k in ("n", "mean", "min_mean", "max_mean"):
            self.assertIn(k, s)
        self.assertLess(s["mean"], 20)
        self.assertGreater(s["infoFraction"]["min"], 0.02)
        self.assertGreater(s["infoFraction"]["median"], 0.02)
        self.assertLess(self.px("black.mp4")["luma"]["infoFraction"]["median"], 0.02)

    def test_rule_thresholds_and_subtypes(self):
        T = fc.THRESHOLDS
        self.assertEqual(40, T["infoDelta"])
        self.assertEqual(0.02, T["infoMinFraction"])
        two = lambda m, i: [S(m, i, 0.0), S(m, i, 0.5), S(100, 0.5, 1.0)]
        self.assertIn("white", fc.pixel_issues(two(230, 0.01), 0, 1.5)[0]["detail"])
        self.assertIn("black", fc.pixel_issues(two(10, 0.0), 0, 1.5)[0]["detail"])
        self.assertIn("flat", fc.pixel_issues(two(120, 0.019), 0, 1.5)[0]["detail"])
        self.assertEqual([], fc.pixel_issues(two(120, 0.02), 0, 1.5))     # >= minFraction is informative

    def test_run_needs_two_samples(self):
        self.assertEqual([], fc.pixel_issues([S(250, 0, 0.0), S(100, 0.5, 0.5)], 0, 1.0))
        self.assertEqual(["blank-frame"], codes(fc.pixel_issues([S(250, 0, 0.0), S(250, 0, 0.5), S(100, 0.5, 1.0)], 0, 1.5)))

    def test_cli_pixels_exit_codes(self):
        self.assertEqual(1, fc.main(["pixels", "--video", str(Media.dir / "white.mp4"), "--in", "0", "--out", "4"]))
        self.assertEqual(0, fc.main(["pixels", "--video", str(Media.dir / "clean.mp4"), "--in", "0", "--out", "5"]))
        self.assertEqual(2, fc.main(["pixels", "--video", str(Media.dir / "nope.mp4"), "--in", "0", "--out", "5"]))
        self.assertEqual(2, fc.main(["pixels", "--video", str(Media.dir / "clean.mp4"), "--in", "0", "--out", "5", "--crop", "1:2"]))

    def test_crop_is_in_1920_space(self):
        # boxed.mp4 is 1280x720 with an 800x450 picture at (240,135) => in 1920x1080 space at (360,202) 1200x675
        self.assertEqual(["blank-frame"], codes(self.blank("boxed.mp4", 0, 5, (0, 0, 300, 150))))
        self.assertEqual([], self.blank("boxed.mp4", 0, 5, (360, 202, 1200, 675)))


class OcrBatchTests(unittest.TestCase):
    def write(self, beats):
        p = Media.dir / "beats_tmp.json"
        p.write_text(json.dumps(beats))
        return p

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
                 {"t": 4, "media": "broll", "src": "bg1", "origin": "stock"},
                 {"t": 12, "mode": "full"}]
        rep = fc.cmd_cutaways(self.write(beats), None, [Media.dir], Media.dir / "fr", fake, episode_end=30)
        self.assertEqual(1, len(calls))
        self.assertEqual(sum(len(b["frames"]) for b in rep["beats"]), len(calls[0]))
        self.assertGreaterEqual(len(calls[0]), 10)

    def test_frames_per_range_is_about_one_per_second(self):
        self.assertEqual(5, len(fc.ocr_frame_times(0, 4)))
        self.assertEqual(5, len(fc.ocr_frame_times(0, 5)))
        self.assertEqual(8, len(fc.ocr_frame_times(0, 7.2)))
        self.assertEqual(10, len(fc.ocr_frame_times(0, 10)))
        self.assertEqual(16, len(fc.ocr_frame_times(2, 18)))
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
                      "--episode-end", "9", "--report", str(Media.dir / "r4.json")], ocr_runner=broken)
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
    def wm(self, name, a=0, b=4, crop=None):
        return fc.cmd_watermark(Media.dir / name, a, b, crop, Media.dir / "wfr", self.ocr())

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
        # file is 640x360; the text sits in the middle, the top 180 px (1920 space) = top 60 px of the file
        self.assertEqual([], self.wm("wm.mp4", crop=(0, 0, 1920, 180))["issues"])

    def test_cli_exit_1(self):
        rc = fc.main(["watermark", "--video", str(Media.dir / "wm.mp4"), "--in", "0", "--out", "4", "--frames-dir",
                      str(Media.dir / "wfr3"), "--cache-dir", str(Media.dir / "ocrcache")])
        self.assertEqual(1, rc)


@unittest.skipUnless(HAVE_SWIFT, "swift is not installed: Vision OCR tests skipped (CLI must exit 4, see OcrBatchTests)")
class CutawayTests(RealOcrMixin, unittest.TestCase):
    def run_beats(self, beats, cuts=None, end=200, obj=None, roots=None, fill_layout=True):
        p = Media.dir / ("beats_cut.json" if obj is None else "episode_cut.json")
        beats = with_layout(beats) if fill_layout else beats
        p.write_text(json.dumps(beats if obj is None else {**obj, "beats": beats}))
        return fc.cmd_cutaways(p, cuts, roots or [Media.dir], Media.dir / "cfr", self.ocr(), episode_end=end)

    def by_beat(self, rep):
        out = {}
        for i in rep["issues"]:
            out.setdefault(i["beat_t"], []).append(i["code"])
        return out

    def test_synthetic_episode(self):
        beats = [
            {"t": 0, "mode": "full"},
            {"t": 10, "media": "clip", "src": "bg1", "origin": "source"},
            {"t": 13, "media": "broll", "src": "wm", "origin": "stock"},
            {"t": 16, "media": "broll", "src": "does_not_exist", "origin": "stock"},
            {"t": 20, "mode": "full"},
        ]
        rep = self.run_beats(beats)
        by = self.by_beat(rep)
        self.assertNotIn(10, by)
        self.assertEqual(["watermark"], by[13])
        self.assertEqual(["media-missing"], by[16])
        self.assertFalse(rep["pass"])
        self.assertEqual("vision-swift", rep["tools"]["ocr"])
        self.assertEqual({"schema", "version", "pass", "counts", "issues", "beats", "tools", "inputs", "seconds", "staticHold", "timing"}, set(rep))
        self.assertEqual(2, len(rep["beats"]))
        for b in rep["beats"]:
            self.assertIn("infoFraction", b["luma"])
            for f in b["frames"]:
                self.assertTrue(Path(f["path"]).is_file())
                self.assertEqual(16, len(f["dhash"]))

    def test_dark_ui_source_cut_is_not_flagged(self):
        rep = self.run_beats([{"t": 0, "media": "clip", "src": "dark_ui", "origin": "source"}, {"t": 3, "mode": "full"}])
        self.assertEqual([], rep["issues"], rep["issues"])

    def test_from_offset_selects_the_shown_range(self):
        base = {"media": "clip", "src": "half_wm", "origin": "source"}
        clean = self.run_beats([{"t": 0, **base, "from": 0}, {"t": 4, "mode": "full"}])        # shows 0..4 -> clean half
        self.assertEqual([], clean["issues"], clean["issues"])
        self.assertEqual([0.0, 4.0], clean["beats"][0]["shown"])
        flagged = self.run_beats([{"t": 0, **base, "from": 6}, {"t": 3, "mode": "full"}])      # shows 6..9 -> watermark half
        self.assertEqual(["watermark"], codes(flagged["issues"]))
        self.assertEqual([6.0, 9.0], flagged["beats"][0]["shown"])

    def test_source_beat_never_loops(self):
        # 6 s beat on a 4 s source cut
        rep = self.run_beats([{"t": 0, "media": "clip", "src": "bg1", "origin": "source"}, {"t": 6, "mode": "full"}])
        self.assertIn("source-loop", codes(rep["issues"]))
        self.assertEqual("error", rep["issues"][0]["severity"])
        # leaving the end of the clip because of `from`
        rep = self.run_beats([{"t": 0, "media": "clip", "src": "half_wm", "origin": "source", "from": 8}, {"t": 4, "mode": "full"}])
        self.assertIn("source-loop", codes(rep["issues"]))
        # fits (3.5 s of a 4 s clip, one-frame loop margin respected)
        rep = self.run_beats([{"t": 0, "media": "clip", "src": "bg1", "origin": "source"}, {"t": 3.5, "mode": "full"}])
        self.assertNotIn("source-loop", codes(rep["issues"]))

    def test_schema_owned_clip_length_is_not_judged_again(self):
        """Declared brollDur == file: S09 (episode_schema.mjs) owns source-loop / from-out-of-range, so no duplicate verdict here."""
        beats = [{"t": 0, "media": "clip", "src": "bg1", "origin": "source"}, {"t": 6, "mode": "full"}]       # 6 s on a 4 s cut
        rep = self.run_beats(beats, obj={"voEndSec": 30, "brollDur": {"bg1": 4.0}})
        self.assertNotIn("source-loop", codes(rep["issues"]))
        rep = self.run_beats([{"t": 0, "media": "clip", "src": "bg1", "origin": "source", "from": 99}, {"t": 6, "mode": "full"}],
                             obj={"voEndSec": 30, "brollDur": {"bg1": 4.0}})
        self.assertNotIn("from-out-of-range", codes(rep["issues"]))
        # no declared duration (legacy) or a wrong one: the real file is the only judge
        rep = self.run_beats(beats)
        self.assertIn("source-loop", codes(rep["issues"]))
        rep = self.run_beats(beats, obj={"voEndSec": 30, "brollDur": {"bg1": 9.0}})
        self.assertIn("broll-dur-mismatch", codes(rep["issues"]))
        self.assertIn("source-loop", codes(rep["issues"]))

    def test_stock_loop_restarts_at_from(self):
        # wm_first.mp4: watermark 0..3 s, clean 3..10 s. Stock beat from=4, 10 s long: loop length
        # (floor((10-4)*25)-2)/25 = 5.92 s => shown [4, 9.92]; the loop restarts at `from`, never at 0.
        rep = self.run_beats([{"t": 0, "media": "broll", "src": "wm_first", "origin": "stock", "from": 4}, {"t": 10, "mode": "full"}])
        self.assertEqual([], rep["issues"], rep["issues"])
        b = rep["beats"][0]
        self.assertTrue(b["loops"])
        self.assertAlmostEqual(4.0, b["shown"][0])
        self.assertAlmostEqual(9.92, b["shown"][1], places=2)
        # without `from` the same beat shows the watermark
        rep = self.run_beats([{"t": 0, "media": "broll", "src": "wm_first", "origin": "stock"}, {"t": 10, "mode": "full"}])
        self.assertEqual(["watermark"], codes(rep["issues"]))

    def test_broll_dur_from_episode_is_used(self):
        obj = {"voEndSec": 30, "brollDur": {"bg1": 4.0}}
        rep = self.run_beats([{"t": 0, "media": "broll", "src": "bg1", "origin": "stock"}, {"t": 10, "mode": "full"}], obj=obj)
        self.assertEqual([], rep["issues"], rep["issues"])
        self.assertAlmostEqual(3.92, rep["beats"][0]["shown"][1], places=2)
        rep = self.run_beats([{"t": 0, "media": "broll", "src": "bg1", "origin": "stock"}, {"t": 10, "mode": "full"}],
                             obj={"voEndSec": 30, "brollDur": {"bg1": 9.0}})
        self.assertIn("broll-dur-mismatch", codes(rep["issues"]))

    def test_src_crop_is_scaled_from_1920_space(self):
        beat = {"t": 0, "media": "broll", "src": "wm", "origin": "stock", "srcCrop": {"x": 0, "y": 0, "w": 1920, "h": 180}}
        rep = self.run_beats([beat, {"t": 3, "mode": "full"}])
        self.assertEqual([], rep["issues"], rep["issues"])
        self.assertEqual([0, 0, 1920, 180], rep["beats"][0]["srcCrop"])
        self.assertEqual([0, 0, 640, 60], rep["beats"][0]["srcCropPx"])
        self.assertEqual("srcCrop", rep["beats"][0]["hashBox"]["kind"])

    def test_path_from_cuts_json_is_used(self):
        cuts = Media.dir / "cuts.json"
        cuts.write_text(json.dumps({"clips": {"elsewhere": {"path": str(Media.dir / "wm.mp4"), "source_in": 100.0}}}))
        rep = self.run_beats([{"t": 0, "media": "clip", "src": "elsewhere", "origin": "source"}, {"t": 3, "mode": "full"}], cuts=cuts)
        self.assertEqual(["watermark"], codes(rep["issues"]))

    def test_source_time_is_reported(self):
        cuts = Media.dir / "cuts2.json"
        cuts.write_text(json.dumps({"clips": {"half_wm": {"source_in": 100.0, "source_out": 110.0}}}))
        rep = self.run_beats([{"t": 0, "media": "clip", "src": "half_wm", "origin": "source", "from": 1}, {"t": 3, "mode": "full"}], cuts=cuts)
        b = rep["beats"][0]
        self.assertEqual([1.0, 4.0], b["shown"])
        self.assertEqual([101.0, 104.0], b["shown_source"])
        for f in b["frames"]:
            self.assertAlmostEqual(100.0 + f["t"], f["source_t"], places=3)
        # stock beats have no source time
        rep = self.run_beats([{"t": 0, "media": "broll", "src": "bg1", "origin": "stock"}, {"t": 3, "mode": "full"}], cuts=cuts)
        self.assertNotIn("shown_source", rep["beats"][0])

    def test_loads_v4_object_json_and_legacy_list(self):
        rep = self.run_beats([{"t": 0, "media": "clip", "src": "bg1", "origin": "source"}, {"t": 3, "mode": "full"}], obj={"voEndSec": 9})
        self.assertEqual([], rep["issues"])
        p = Media.dir / "list_noend.json"
        p.write_text(json.dumps([{"t": 0, "media": "clip", "src": "bg1", "origin": "source"}]))
        with self.assertRaises(fc.BadInput):
            fc.cmd_cutaways(p, None, [Media.dir], Media.dir / "cfr", self.ocr())
        self.assertEqual(2, fc.main(["cutaways", "--beats", str(p), "--media-root", str(Media.dir), "--frames-dir", str(Media.dir / "cfr")]))

    def test_shot_reuse_within_60s(self):
        beats = [{"t": 0, "media": "clip", "src": "clean", "origin": "source"}, {"t": 3, "mode": "full"},
                 {"t": 40, "media": "clip", "src": "clean_copy", "origin": "source"}, {"t": 43, "mode": "full"}]
        rep = self.run_beats(beats)
        self.assertEqual(["shot-reuse"], codes(rep["issues"]))
        self.assertEqual(40, rep["issues"][0]["beat_t"])
        self.assertIn("t=0", rep["issues"][0]["detail"])

    def test_no_shot_reuse_70s_apart(self):
        beats = [{"t": 0, "media": "clip", "src": "clean", "origin": "source"}, {"t": 3, "mode": "full"},
                 {"t": 70, "media": "clip", "src": "clean_copy", "origin": "source"}, {"t": 73, "mode": "full"}]
        self.assertEqual([], self.run_beats(beats)["issues"])

    def test_different_shots_are_not_reuse(self):
        beats = [{"t": 0, "media": "clip", "src": "bg1", "origin": "source"}, {"t": 3, "media": "clip", "src": "bg2", "origin": "source"},
                 {"t": 6, "mode": "full"}]
        self.assertEqual([], self.run_beats(beats)["issues"])

    def test_reuse_hashes_the_content_box_not_the_layout(self):
        # same 800x450 picture, placed differently inside two 1280x720 frames
        beats = [{"t": 0, "media": "clip", "src": "boxed", "origin": "source"}, {"t": 3, "mode": "full"},
                 {"t": 20, "media": "clip", "src": "boxed_b", "origin": "source"}, {"t": 23, "mode": "full"}]
        rep = self.run_beats(beats)
        self.assertEqual(["shot-reuse"], codes(rep["issues"]), rep["issues"])
        for b in rep["beats"]:
            self.assertEqual("crop-propose", b["hashBox"]["kind"])
        # the boxes are in 1920 space and close to the picture
        x, y, w, h = rep["beats"][0]["hashBox"]["box"]
        self.assertLessEqual(abs(x - 360), 14)
        self.assertLessEqual(abs(w - 1200), 14)

    def test_full_frame_when_no_bars(self):
        rep = self.run_beats([{"t": 0, "media": "clip", "src": "clean", "origin": "source"}, {"t": 3, "mode": "full"}])
        self.assertEqual("frame", rep["beats"][0]["hashBox"]["kind"])



# A 640x360 file with srcCrop {0,0,1440,810} (1920 space) shows only its top-left 480x270 pixels in the stage box: the right (x > 480)
# and bottom (y > 270) margins are NOT visible to the viewer (they stand for the presenter / overlay area of the real episode).
VISIBLE_CROP = {"x": 0, "y": 0, "w": 1440, "h": 810}


def clip_beat(t, src, **kw):
    return {"t": t, "media": "clip", "src": src, "origin": "source", "layout": "stage", "srcCrop": VISIBLE_CROP, **kw}


def ensure_static_media():
    d = Media.dir
    margin = "drawbox=x=490:y=0:w=150:h=360:color={c}:t=fill:enable='lt(mod(t,2),1)',drawbox=x=0:y=280:w=640:h=80:color={c}:t=fill:enable='lt(mod(t,2),1)'"
    if (d / "st_margin.mp4").exists():
        return
    busy_png(d / "st_bg.png", seed=11)
    busy_png(d / "st_bg_b.png", seed=12)
    # static visible region, margin pixels flip white / black every other second (12.5 s)
    ff("-loop", "1", "-framerate", "10", "-t", "12.5", "-i", str(d / "st_bg.png"), "-vf", margin.format(c="white"), "-pix_fmt", "yuv420p", str(d / "st_margin.mp4"))
    # fully static (14 s), and one that is static but for a big white box in the VISIBLE region during [5, 10) of every 10 s
    ff("-loop", "1", "-framerate", "10", "-t", "14", "-i", str(d / "st_bg.png"), "-pix_fmt", "yuv420p", str(d / "st_plain.mp4"))
    ff("-loop", "1", "-framerate", "10", "-t", "12.5", "-i", str(d / "st_bg.png"), "-vf",
       "drawbox=x=40:y=30:w=380:h=210:color=white:t=fill:enable='between(mod(t,10),5,10)'", "-pix_fmt", "yuv420p", str(d / "st_region.mp4"))
    ff("-loop", "1", "-framerate", "10", "-t", "14", "-i", str(d / "st_bg_b.png"), "-pix_fmt", "yuv420p", str(d / "st_plain_b.mp4"))


def ensure_blank_media():
    """640x360 files, 10 fps, 8 s of a busy picture with a white flash: bl_full06 (whole frame, 0.6 s; bl_full12 1.2 s), bl_vis12 / bl_vis06 (only the
    top-left 480x270 that VISIBLE_CROP shows, 1.2 s / 0.6 s, margins stay busy), bl_margin (only the margins, 2 s)."""
    d = Media.dir
    if (d / "bl_margin.mp4").exists():
        return
    busy_png(d / "bl_bg.png", seed=21)
    def clip(name, box, t0, t1):
        ff("-loop", "1", "-framerate", "10", "-t", "8", "-i", str(d / "bl_bg.png"), "-vf",
           ",".join(f"drawbox={b}:color=white:t=fill:enable='between(t,{t0},{t1})'" for b in box), "-pix_fmt", "yuv420p", str(d / name))
    clip("bl_full06.mp4", ["x=0:y=0:w=640:h=360"], 2.0, 2.55)
    clip("bl_full12.mp4", ["x=0:y=0:w=640:h=360"], 2.0, 3.15)
    clip("bl_vis12.mp4", ["x=0:y=0:w=480:h=270"], 2.0, 3.15)
    clip("bl_vis06.mp4", ["x=0:y=0:w=480:h=270"], 2.0, 2.55)
    clip("bl_margin.mp4", ["x=480:y=0:w=160:h=360", "x=0:y=270:w=640:h=90"], 2.0, 4.0)


class BlankFrameSourceTests(unittest.TestCase):
    """blank-frame on a SOURCE clip: >= 1.0 s of low-information picture in the visible region is an error (locked by lead 2026-11-12)."""

    @classmethod
    def setUpClass(cls):
        ensure_blank_media()

    def run_beats(self, beats):
        p = Media.dir / "blank_beats.json"
        p.write_text(json.dumps(beats))
        return fc.cmd_cutaways(p, None, [Media.dir], Media.dir / "bfr", lambda paths: {x: ok_lines() for x in paths}, episode_end=60)

    def blanks(self, rep):
        return [i for i in rep["issues"] if i["code"] == "blank-frame"]

    def test_threshold_is_in_the_table(self):
        self.assertEqual(1.0, fc.THRESHOLDS["blank_error_seconds"])

    def test_blank_1_2s_in_the_visible_region_is_an_error_naming_beat_clip_and_file_range(self):
        rep = self.run_beats([clip_beat(3, "bl_vis12", **{"from": 0}), {"t": 9, "mode": "full"}])
        got = self.blanks(rep)
        self.assertEqual(1, len(got), rep["issues"])
        self.assertEqual("error", got[0]["severity"])
        self.assertEqual(3, got[0]["beat_t"])
        self.assertIn("beat t=3", got[0]["detail"])
        self.assertIn("bl_vis12", got[0]["detail"])
        a, b = got[0]["range"]
        self.assertAlmostEqual(2.0, a, delta=0.12)
        self.assertAlmostEqual(3.2, b, delta=0.12)                        # range inside the CLIP FILE, not the episode timeline (beat starts at 3)
        self.assertRegex(got[0]["detail"], r"from 2\.\d\d+s to 3\.\d\ds inside the clip file")
        self.assertIn("move `from` past", got[0]["detail"])
        self.assertFalse(rep["pass"])

    def test_from_offset_is_added_to_the_clip_range(self):
        rep = self.run_beats([clip_beat(0, "bl_vis12", **{"from": 1.0}), {"t": 5, "mode": "full"}])
        a, b = self.blanks(rep)[0]["range"]
        self.assertAlmostEqual(2.0, a, delta=0.12)                        # still file seconds although the beat started at from=1.0

    def test_blank_0_6s_is_a_warning(self):
        rep = self.run_beats([clip_beat(0, "bl_vis06"), {"t": 6, "mode": "full"}])
        got = self.blanks(rep)
        self.assertEqual([("blank-frame", "warn")], [(i["code"], i["severity"]) for i in got], rep["issues"])
        self.assertAlmostEqual(0.6, got[0]["duration"], delta=0.15)
        self.assertTrue(rep["pass"])

    def test_blank_only_outside_the_visible_region_is_nothing(self):
        rep = self.run_beats([clip_beat(0, "bl_margin"), {"t": 6, "mode": "full"}])
        self.assertEqual([], self.blanks(rep), rep["issues"])
        self.assertEqual([], [i for i in rep["issues"] if i["severity"] == "error" and i["code"] != "static-hold"], rep["issues"])

    def test_stock_and_ai_stay_errors_whatever_their_length(self):
        for origin in ("stock", "ai"):
            with self.subTest(origin):
                rep = self.run_beats([{"t": 0, "media": "broll", "src": "bl_full12", "origin": origin, "layout": "stage"}, {"t": 6, "mode": "full"}])
                self.assertEqual([("blank-frame", "error")], [(i["code"], i["severity"]) for i in self.blanks(rep)], rep["issues"])

    def test_dense_run_unit(self):
        mk = lambda flags: [{"t": round(k / 25, 3), "mean": 0, "median": 255 if f else 100, "info": 0.0 if f else 0.5} for k, f in enumerate(flags)]
        e = fc.dense_blank_issues(mk([False] * 10 + [True] * 25 + [False] * 10), 0.0, 1.8, "clipx", 7.0)
        self.assertEqual(["error"], [i["severity"] for i in e])
        self.assertEqual([0.4, 1.4], e[0]["range"])
        w = fc.dense_blank_issues(mk([False] * 10 + [True] * 24 + [False] * 10), 0.0, 1.8, "clipx", 7.0)      # 0.96 s
        self.assertEqual(["warn"], [i["severity"] for i in w])
        self.assertEqual([], fc.dense_blank_issues(mk([False] * 10 + [True] * 6 + [False] * 10), 0.0, 1.0, "clipx", 7.0))    # 0.24 s flash


def _pale_frame(vlines, noise=0.0, seed=0):
    """640x360 RGB frame imitating a floor plan / white 3D model: pale background (216) with `vlines` thin (4 px) darker (150) vertical
    lines inside the top-left 480x270 that VISIBLE_CROP shows, plus optional gaussian noise (std `noise`)."""
    import numpy as np
    from PIL import Image
    a = np.full((360, 640), 216.0)
    for k in range(vlines):
        x = 20 + k * 58
        a[0:270, x:x + 4] = 150.0
    if noise:
        a += np.random.default_rng(seed).normal(0, noise, a.shape)
    return Image.fromarray(a.clip(0, 255).astype("uint8"), mode="L").convert("RGB")


def _write_pale_clips():
    d = Media.dir
    if (d / "pale_flicker.mp4").exists():
        return
    detail = d / "pale_detail.png"
    _pale_frame(8).save(detail)                                                   # ~5 % of the visible region is line detail
    ff("-loop", "1", "-framerate", "25", "-t", "4", "-i", str(detail), "-pix_fmt", "yuv420p", "-crf", "10", str(d / "pale_detail.mp4"))
    flat = d / "pale_flat.png"
    _pale_frame(0, noise=10).save(flat)                                           # no detail at all: pale + noise std 10
    ff("-loop", "1", "-framerate", "25", "-t", "4", "-i", str(flat), "-pix_fmt", "yuv420p", "-crf", "10", str(d / "pale_flat.mp4"))
    # detail flickering around the 2 % line: poor (1 line, ~0.6 %) for 6 frames (0.24 s) and 4 frames (0.16 s), rich (8 lines) otherwise
    seq = d / "pale_seq"
    seq.mkdir(exist_ok=True)
    rich, poor = _pale_frame(8), _pale_frame(1)
    plan = [rich] * 10 + [poor] * 6 + [rich] * 20 + [poor] * 4 + [rich] * 60       # 4 s; the beat shows the first 3 s
    for k, im in enumerate(plan):
        im.save(seq / f"f{k:03d}.png")
    ff("-framerate", "25", "-i", str(seq / "f%03d.png"), "-pix_fmt", "yuv420p", "-crf", "10", str(d / "pale_flicker.mp4"))


class PaleLowContrastTests(unittest.TestCase):
    """Pale, low-contrast pictures that still have detail are NOT blank (lead decision 2026-11-12). The old white spot of
    yt_house_walkthrough (floor plan / white 3D house model, mean luma ~210-215) was such a picture; the time bounds stay
    (>= 0.5 s warning, >= 1.0 s error, < 0.5 s not reported)."""

    @classmethod
    def setUpClass(cls):
        _write_pale_clips()

    def run_beats(self, src, shown):
        p = Media.dir / "pale_beats.json"
        p.write_text(json.dumps([clip_beat(0, src), {"t": shown, "mode": "full"}]))
        return fc.cmd_cutaways(p, None, [Media.dir], Media.dir / "pfr", lambda paths: {x: ok_lines() for x in paths}, episode_end=60)

    def region_stats(self, src):
        """(mean, std, info fraction) of the first frame of the visible region, as the gate sees it."""
        path = Media.dir / f"{src}.mp4"
        _, fw, fh = fc.probe(path)
        px = fc.region_px(fc._episode_data().visible_region("stage", fw, fh, VISIBLE_CROP), fw, fh)
        arr = fc.decode_region(path, 0.0, 1.0, px)
        f = arr[5].astype("float32")
        return float(f.mean()), float(f.std()), fc.luma_stats(arr, 0.0, 25)[5]["info"]

    def blanks(self, rep):
        return [i for i in rep["issues"] if i["code"] == "blank-frame"]

    def test_pale_low_contrast_picture_with_detail_is_not_blank(self):
        # lead decision 2026-11-12: pale + thin line detail over clearly more than 2 % of the visible region is a picture, not a blank
        mean, std, info = self.region_stats("pale_detail")
        self.assertTrue(205 <= mean <= 220 and 8 <= std <= 22, (mean, std))              # the imitated look: pale, low contrast
        self.assertGreater(info, 0.035, info)                                             # detail well above the 2 % line
        rep = self.run_beats("pale_detail", 3.0)
        self.assertEqual([], self.blanks(rep), rep["issues"])
        self.assertTrue(rep["pass"], rep["issues"])

    def test_pale_picture_without_any_detail_is_still_blank_for_1_2s(self):
        # lead decision 2026-11-12: the metric still catches a really empty pale frame
        mean, std, info = self.region_stats("pale_flat")
        self.assertTrue(mean > 200 and std < 20 and info < fc.THRESHOLDS["infoMinFraction"], (mean, std, info))
        rep = self.run_beats("pale_flat", 1.2)
        self.assertEqual([("blank-frame", "error")], [(i["code"], i["severity"]) for i in self.blanks(rep)], rep["issues"])
        self.assertFalse(rep["pass"])

    def test_pale_detail_flickering_around_the_two_percent_line_with_short_runs_reports_nothing(self):
        # lead decision 2026-11-12: the measured pattern at the old white spot was runs of 0.24 s and 0.16 s (< 0.5 s floor): not reported
        path = Media.dir / "pale_flicker.mp4"
        _, fw, fh = fc.probe(path)
        px = fc.region_px(fc._episode_data().visible_region("stage", fw, fh, VISIBLE_CROP), fw, fh)
        stats = fc.luma_stats(fc.decode_region(path, 0.0, 3.0, px), 0.0, 25)
        flags = [s["info"] < fc.THRESHOLDS["infoMinFraction"] for s in stats]
        runs, k = [], 0
        while k < len(flags):                                                              # guard: the clip really has the measured pattern
            if flags[k]:
                j = k
                while j + 1 < len(flags) and flags[j + 1]:
                    j += 1
                runs.append((j - k + 1) / 25)
                k = j + 1
            else:
                k += 1
        self.assertEqual(2, len(runs), runs)
        self.assertTrue(all(0.12 <= r <= 0.32 for r in runs) and abs(sum(runs) - 0.40) <= 0.12, runs)
        rep = self.run_beats("pale_flicker", 3.0)
        self.assertEqual([], self.blanks(rep), rep["issues"])
        self.assertTrue(rep["pass"], rep["issues"])


class NearlyBlankMetricTests(unittest.TestCase):
    """What the gate calls "nearly blank": a frame (area-downscaled to 160x90, full-range luma) is blank when FEWER THAN 2 % of its pixels differ
    from the frame's MEDIAN luma by MORE THAN 40 (infoDelta, infoMinFraction). Mean and std are not used, so the engine team's "pale"
    criterion (mean > 200 and std < 20) is neither necessary nor sufficient."""

    def frames(self, make, n=30):
        import numpy as np
        rnd = np.random.default_rng(5)
        return np.stack([make(rnd) for _ in range(n)]).clip(0, 255).astype(np.uint8)

    def verdict(self, arr):
        st = fc.luma_stats(arr, 0.0, 25)
        issues = fc.dense_blank_issues(st, 0.0, arr.shape[0] / 25, "c", 1.0)
        f = arr[0].astype("float32")
        return {"mean": float(f.mean()), "std": float(f.std()), "info": st[0]["info"], "issues": [(i["severity"]) for i in issues]}

    def test_thresholds_are_the_documented_numbers(self):
        T = fc.THRESHOLDS
        self.assertEqual((40, 0.02, 0.5, 1.0, (160, 90)), (T["infoDelta"], T["infoMinFraction"], T["run_min_seconds"], T["blank_error_seconds"], T["sample_size"]))

    def test_pale_frame_with_small_noise_is_caught(self):
        import numpy as np
        v = self.verdict(self.frames(lambda r: 210 + r.normal(0, 10, (90, 160))))          # mean 210, std 10: engine "pale"
        self.assertTrue(v["mean"] > 200 and v["std"] < 20)
        self.assertEqual(["error"], v["issues"])                                               # 30 frames = 1.2 s

    def test_pale_frame_with_a_smooth_gradient_is_caught(self):
        import numpy as np
        grad = np.tile(np.linspace(176, 244, 160), (90, 1))                                    # 210 +- 34: no pixel is more than 40 from the median
        v = self.verdict(self.frames(lambda r: grad))
        self.assertTrue(v["mean"] > 200 and v["std"] < 20)
        self.assertEqual(["error"], v["issues"])

    def test_pale_frame_with_5_percent_dark_detail_is_not_caught(self):
        import numpy as np

        def make(r):
            a = np.full((90, 160), 210.0)
            a[:9, :80] = 120.0                                                                 # 720 of 14,400 pixels = 5 % far from the median
            return a
        v = self.verdict(self.frames(make))
        self.assertTrue(v["mean"] > 200 and v["std"] < 20, v)                                  # still "pale" by the engine criterion ...
        self.assertAlmostEqual(0.05, v["info"], places=3)
        self.assertEqual([], v["issues"])                                                       # ... but not blank: 5 % >= 2 %

    def test_the_two_percent_edge(self):
        import numpy as np

        def make(frac):
            def f(r):
                a = np.full((90, 160), 210.0)
                a.flat[:int(14400 * frac)] = 100.0
                return a
            return f
        self.assertEqual(["error"], self.verdict(self.frames(make(0.019)))["issues"])
        self.assertEqual([], self.verdict(self.frames(make(0.021)))["issues"])

    def test_duration_floor_and_error_bound(self):
        import numpy as np
        blank = lambda r: np.full((90, 160), 210.0)
        busy = lambda r: r.integers(0, 256, (90, 160)).astype(float)
        for n, want in ((24, ["warn"]), (25, ["error"]), (13, ["warn"]), (12, [])):            # 0.96 s / 1.0 s / 0.52 s / 0.48 s
            with self.subTest(frames=n):
                arr = np.concatenate([self.frames(busy, 10), self.frames(blank, n), self.frames(busy, 10)])
                self.assertEqual(want, self.verdict(arr)["issues"])


class StaticHoldTests(unittest.TestCase):
    """static-hold (error): the part of a source clip the viewer sees hardly changes for longer than maxHoldSeconds (qc_thresholds.json)."""

    @classmethod
    def setUpClass(cls):
        ensure_static_media()

    def run_beats(self, beats, **kw):
        p = Media.dir / "static_beats.json"
        p.write_text(json.dumps(beats))
        return fc.cmd_cutaways(p, None, [Media.dir], Media.dir / "sfr", lambda paths: {x: ok_lines() for x in paths}, episode_end=kw.pop("end", 60))

    def holds(self, rep, code="static-hold"):
        return [i for i in rep["issues"] if i["code"] == code]

    def test_1_static_visible_region_with_changing_margin_is_an_error(self):
        rep = self.run_beats([clip_beat(0, "st_margin"), {"t": 11, "mode": "full"}])
        h = self.holds(rep)
        self.assertEqual(1, len(h), rep["issues"])
        self.assertEqual("error", h[0]["severity"])
        self.assertEqual(0, h[0]["beat_t"])
        self.assertEqual(["st_margin"], h[0]["srcs"])
        self.assertGreater(h[0]["duration"], 10.0)
        self.assertLessEqual(h[0]["duration"], 11.0)
        self.assertFalse(rep["pass"])
        # guard: the margin really does change a whole-frame hash, so only the visible-region restriction can make this a hold
        p = Media.dir / "st_margin.mp4"
        whole = fc.static_samples(p, 0, 6, (0, 0, 640, 360))
        self.assertGreater(max(fc.hamming(whole[0]["dhash"], x["dhash"]) for x in whole), fc.THRESHOLDS["reuse_max_distance"])

    def test_2_visible_region_changing_every_5s_passes(self):
        rep = self.run_beats([clip_beat(0, "st_region"), {"t": 11, "mode": "full"}])
        self.assertEqual([], self.holds(rep), rep["issues"])
        longest = rep["staticHold"]["runs"][0]["longestStatic"]
        self.assertLess(longest["duration"], 5.5)
        self.assertGreater(longest["duration"], 4.0)

    def test_3_two_consecutive_beats_accumulate(self):
        rep = self.run_beats([clip_beat(0, "st_plain"), clip_beat(6, "st_plain", **{"from": 6}), {"t": 12, "mode": "full"}])
        h = self.holds(rep)
        self.assertEqual(1, len(h), rep["issues"])
        self.assertGreater(h[0]["duration"], 11.5)
        self.assertEqual({"start": 0.0, "end": h[0]["range"][1], "duration": h[0]["duration"], "srcs": ["st_plain"], "beat_t": 0},
                         {k: rep["staticHold"]["runs"][0]["longestStatic"][k] for k in ("start", "end", "duration", "srcs", "beat_t")})
        self.assertEqual([0, 6], rep["staticHold"]["runs"][0]["beats"])

    def test_3b_accumulates_across_different_files_with_the_same_picture(self):
        shutil.copy(Media.dir / "st_plain.mp4", Media.dir / "st_plain_copy.mp4")
        rep = self.run_beats([clip_beat(0, "st_plain"), clip_beat(6, "st_plain_copy"), {"t": 12, "mode": "full"}])
        h = self.holds(rep)
        self.assertEqual(1, len(h), rep["issues"])
        self.assertEqual(["st_plain", "st_plain_copy"], h[0]["srcs"])

    def test_3c_a_different_picture_between_files_resets(self):
        rep = self.run_beats([clip_beat(0, "st_plain"), clip_beat(6, "st_plain_b"), {"t": 12, "mode": "full"}])
        self.assertEqual([], self.holds(rep), rep["issues"])

    def test_4_a_presenter_beat_between_resets(self):
        rep = self.run_beats([clip_beat(0, "st_plain"), {"t": 6, "mode": "full"}, clip_beat(7, "st_plain", **{"from": 6}), {"t": 13, "mode": "full"}])
        self.assertEqual([], self.holds(rep), rep["issues"])
        self.assertEqual([0, 7], [r["start"] for r in rep["staticHold"]["runs"]])
        self.assertTrue(all(r["longestStatic"]["duration"] < 6.5 for r in rep["staticHold"]["runs"]))

    def test_4b_typo_stock_and_ai_beats_between_reset(self):
        for mid in ({"t": 6, "mode": "pip", "media": "typo", "typo": "card", "layout": "stage"},
                    {"t": 6, "mode": "pip", "media": "broll", "src": "bg1", "origin": "stock", "layout": "stage"},
                    {"t": 6, "mode": "pip", "media": "broll", "src": "bg1", "origin": "ai", "layout": "stage"}):
            with self.subTest(mid=mid.get("origin") or mid["media"]):
                rep = self.run_beats([clip_beat(0, "st_plain"), mid, clip_beat(7, "st_plain", **{"from": 6}), {"t": 13, "mode": "full"}])
                self.assertEqual([], self.holds(rep), rep["issues"])

    def test_5_layout_change_between_two_static_beats_resets(self):
        rep = self.run_beats([clip_beat(0, "st_plain"), clip_beat(6, "st_plain", layout="wide", **{"from": 6}), {"t": 12, "mode": "full"}])
        self.assertEqual([], self.holds(rep), rep["issues"])
        self.assertEqual([], self.holds(rep, "static-hold-region-unknown"))

    def test_6_region_that_cannot_be_computed_fails_closed(self):
        bad = {"unknown layout": dict(layout="flat"), "missing layout": dict(layout=None), "crop outside the frame": dict(srcCrop={"x": 1900, "y": 0, "w": 640, "h": 360}),
               "crop not a dict": dict(srcCrop="0:0:640:360")}
        for name, kw in bad.items():
            with self.subTest(name):
                beat = clip_beat(0, "st_plain", **kw)
                if beat["layout"] is None:
                    del beat["layout"]
                rep = self.run_beats([beat, {"t": 11, "mode": "full"}])
                got = self.holds(rep, "static-hold-region-unknown")
                self.assertEqual(1, len(got), rep["issues"])
                self.assertEqual("error", got[0]["severity"])
                self.assertEqual([], self.holds(rep))                 # no fallback to the whole frame: nothing is measured
                self.assertFalse(rep["pass"])

    def test_6b_a_beat_without_resolution_is_unknown_too(self):
        # visible_region itself rejects a bad resolution; the loader path passes the probed one, so exercise the unit directly
        with self.assertRaises(ValueError):
            fc._episode_data().visible_region("stage", 0, 360, None)

    def test_7_static_9_5s_passes(self):
        rep = self.run_beats([clip_beat(0, "st_plain"), {"t": 9.5, "mode": "full"}])
        self.assertEqual([], self.holds(rep), rep["issues"])
        d = rep["staticHold"]["runs"][0]["longestStatic"]["duration"]
        self.assertGreater(d, 9.3)
        self.assertLess(d, 9.5)

    def test_lanes_file_missing_is_tool_missing_and_invalid_is_region_unknown(self):
        ed = fc._episode_data()
        old = ed.LANES_PATH
        beats = Media.dir / "static_lanes.json"
        beats.write_text(json.dumps([clip_beat(0, "st_plain"), {"t": 3, "mode": "full"}]))
        argv = ["cutaways", "--beats", str(beats), "--media-root", str(Media.dir), "--frames-dir", str(Media.dir / "sfr_lanes"), "--episode-end", "5"]
        runner = lambda paths: {x: ok_lines() for x in paths}
        try:
            ed.LANES_PATH = Media.dir / "no_such_lanes.json"
            self.assertEqual(4, fc.main(argv, ocr_runner=runner))
            bad = Media.dir / "bad_lanes.json"
            bad.write_text('{"schema": "yt-news-v4-lanes", "version": 1, "lanes": {}, "pictureLaneByScene": {}}')
            ed.LANES_PATH = bad
            rep = self.run_beats([clip_beat(0, "st_plain"), {"t": 3, "mode": "full"}])
            got = self.holds(rep, "static-hold-region-unknown")
            self.assertEqual(1, len(got), rep["issues"])
            self.assertEqual("error", got[0]["severity"])
            self.assertIn("lane", got[0]["detail"])
            self.assertFalse(rep["pass"])
        finally:
            ed.LANES_PATH = old

    def test_threshold_comes_from_qc_thresholds_json(self):
        data = json.loads(fc.QC_THRESHOLDS_PATH.read_text())
        self.assertEqual(float(data["maxHoldSeconds"]), fc.load_max_hold())
        self.assertEqual(float(data["maxHoldSeconds"]), self.run_beats([clip_beat(0, "st_plain"), {"t": 3, "mode": "full"}])["staticHold"]["maxHoldSeconds"])
        # a different value in the file changes the verdict (nothing is hard coded here)
        alt = Media.dir / "qc_alt.json"
        alt.write_text(json.dumps({"maxHoldSeconds": 4}))
        old = fc.QC_THRESHOLDS_PATH
        fc.QC_THRESHOLDS_PATH = alt
        try:
            rep = self.run_beats([clip_beat(0, "st_plain"), {"t": 6, "mode": "full"}])
        finally:
            fc.QC_THRESHOLDS_PATH = old
        self.assertEqual(1, len(self.holds(rep)))

    def test_missing_or_broken_threshold_file_is_tool_missing_exit_4(self):
        old = fc.QC_THRESHOLDS_PATH
        beats = Media.dir / "static_cli.json"
        beats.write_text(json.dumps([clip_beat(0, "st_plain"), {"t": 3, "mode": "full"}]))
        argv = ["cutaways", "--beats", str(beats), "--media-root", str(Media.dir), "--frames-dir", str(Media.dir / "sfr_cli"), "--episode-end", "5"]
        try:
            for name, content in (("missing", None), ("no key", "{}"), ("not json", "nope"), ("zero", '{"maxHoldSeconds": 0}'), ("string", '{"maxHoldSeconds": "10"}')):
                with self.subTest(name):
                    alt = Media.dir / "qc_bad.json"
                    alt.unlink(missing_ok=True)
                    if content is not None:
                        alt.write_text(content)
                    fc.QC_THRESHOLDS_PATH = alt
                    self.assertEqual(4, fc.main(argv, ocr_runner=lambda paths: {x: ok_lines() for x in paths}))
        finally:
            fc.QC_THRESHOLDS_PATH = old

    def test_sampling_gap_is_at_most_one_second_for_every_beat_length(self):
        # evidence (OCR) frames: spacing = duration / max(5, ceil(duration))
        for k in range(1, 3000):
            d = k / 100.0
            ts = fc.ocr_frame_times(0.0, d)
            gaps = [b - a for a, b in zip(ts, ts[1:])]
            self.assertTrue(all(g <= 1.0 + 1e-3 for g in gaps), (d, max(gaps or [0])))
        # static samples: grid of 1 / static_sample_fps plus the last frame of the beat
        smp = fc.static_samples(Media.dir / "st_plain.mp4", 0.0, 6.0, (0, 0, 640, 360))
        locals_ = [x["local"] for x in smp]
        self.assertLessEqual(max(b - a for a, b in zip(locals_, locals_[1:])), 1.0)
        self.assertLessEqual(locals_[0], 0.001)
        self.assertGreaterEqual(locals_[-1], 6.0 - 0.1)

    def test_static_stretch_unit(self):
        h = lambda v: f"{v:016x}"
        beats = [clip_beat(0, "a"), clip_beat(4, "b"), {"t": 8, "mode": "full"}]
        smp = lambda off, hv: [{"local": off + k * 0.5, "dhash": h(hv), "flat": False} for k in range(8)]
        iss, runs = fc.static_timeline(beats, {0: {"from": 0.0, "samples": smp(0, 0)}, 1: {"from": 0.0, "samples": smp(0, 0b11)}}, 3.0)
        self.assertEqual(1, len(iss))                                 # distance 2 <= threshold: still the same picture, 7.5 s > 3
        self.assertEqual(7.5, iss[0]["duration"])
        iss, runs = fc.static_timeline(beats, {0: {"from": 0.0, "samples": smp(0, 0)}, 1: {"from": 0.0, "samples": smp(0, 0xFF)}}, 5.0)
        self.assertEqual([], iss)                                     # distance 8 > threshold: a visible change
        self.assertAlmostEqual(3.5, runs[0]["longestStatic"]["duration"])


class ShotReuseExceptionTests(unittest.TestCase):
    """The only shot-reuse exception: same file, adjacent beats, both source clips, forward (non-overlapping) playback."""

    @classmethod
    def setUpClass(cls):
        ensure_static_media()
        shutil.copy(Media.dir / "st_plain.mp4", Media.dir / "st_plain_copy.mp4")

    def run_beats(self, beats):
        p = Media.dir / "reuse_beats.json"
        p.write_text(json.dumps(beats))
        return fc.cmd_cutaways(p, None, [Media.dir], Media.dir / "rfr", lambda paths: {x: ok_lines() for x in paths}, episode_end=60)

    def reuse(self, rep):
        return [i for i in rep["issues"] if i["code"] == "shot-reuse"]

    def test_forward_playback_of_the_same_file_in_adjacent_beats_is_not_reuse(self):
        rep = self.run_beats([clip_beat(0, "st_plain"), clip_beat(3, "st_plain", **{"from": 3}), {"t": 6, "mode": "full"}])
        self.assertEqual([], self.reuse(rep), rep["issues"])
        self.assertTrue(rep["pass"], rep["issues"])
        # touching ranges (second starts exactly where the first stops) are the S10-allowed case too
        rep = self.run_beats([clip_beat(0, "st_plain", **{"from": 1}), clip_beat(3, "st_plain", **{"from": 4}), {"t": 6, "mode": "full"}])
        self.assertEqual([], self.reuse(rep), rep["issues"])

    def test_same_file_with_a_beat_in_between_is_still_reuse(self):
        rep = self.run_beats([clip_beat(0, "st_plain"), {"t": 3, "mode": "full"}, clip_beat(4, "st_plain", **{"from": 3}), {"t": 7, "mode": "full"}])
        self.assertEqual(1, len(self.reuse(rep)), rep["issues"])
        self.assertEqual("error", self.reuse(rep)[0]["severity"])

    def test_same_picture_from_two_files_is_still_reuse(self):
        rep = self.run_beats([clip_beat(0, "st_plain"), clip_beat(3, "st_plain_copy", **{"from": 3}), {"t": 6, "mode": "full"}])
        self.assertEqual(1, len(self.reuse(rep)), rep["issues"])

    def test_overlapping_ranges_of_the_same_file_stay_reuse(self):
        rep = self.run_beats([clip_beat(0, "st_plain", **{"from": 2}), clip_beat(3, "st_plain", **{"from": 3}), {"t": 6, "mode": "full"}])
        self.assertEqual(1, len(self.reuse(rep)), rep["issues"])

    def test_stock_beats_are_not_covered_by_the_exception(self):
        a = {"t": 0, "media": "broll", "src": "st_plain", "origin": "stock", "layout": "stage"}
        b = {"t": 3, "media": "broll", "src": "st_plain", "origin": "stock", "layout": "stage", "from": 3}
        rep = self.run_beats([a, b, {"t": 6, "mode": "full"}])
        self.assertEqual(1, len(self.reuse(rep)), rep["issues"])

    def test_continuous_playback_unit(self):
        a = {"index": 3, "src": "x", "media": "clip", "origin": "source", "playFrames": [100, 200]}
        b = {"index": 4, "src": "x", "media": "clip", "origin": "source", "playFrames": [200, 300]}
        self.assertTrue(fc.continuous_playback(a, b))
        self.assertFalse(fc.continuous_playback(a, {**b, "playFrames": [199, 300]}))
        self.assertFalse(fc.continuous_playback(a, {**b, "index": 5}))
        self.assertFalse(fc.continuous_playback(a, {**b, "src": "y"}))
        self.assertFalse(fc.continuous_playback(a, {**b, "origin": "stock"}))
        self.assertFalse(fc.continuous_playback({k: v for k, v in a.items() if k != "index"}, b))


class SeverityTests(unittest.TestCase):
    """Wave 3: blank-frame is an error on stock/ai, a warn on source; only errors fail the run."""

    def fake(self, paths):
        return {p: ok_lines() for p in paths}

    def run_cli(self, beats, name, extra=()):
        b = Media.dir / f"sev_{name}.json"
        b.write_text(json.dumps(with_layout(beats)))
        rep = Media.dir / f"sev_{name}_report.json"
        rc = fc.main(["cutaways", "--beats", str(b), "--media-root", str(Media.dir), "--frames-dir", str(Media.dir / f"sevfr_{name}"),
                      "--episode-end", "20", "--report", str(rep), *extra], ocr_runner=self.fake)
        return rc, json.loads(rep.read_text())

    def test_blank_stock_is_error_and_fails(self):
        rc, rep = self.run_cli([{"t": 0, "media": "broll", "src": "white", "origin": "stock"}, {"t": 3, "mode": "full"}], "stock")
        self.assertEqual(1, rc)
        self.assertFalse(rep["pass"])
        self.assertEqual([("blank-frame", "error")], [(i["code"], i["severity"]) for i in rep["issues"]])
        self.assertEqual(1, rep["counts"]["error"])
        self.assertEqual(0, rep["counts"]["warn"])

    def test_blank_ai_is_error(self):
        rc, rep = self.run_cli([{"t": 0, "media": "broll", "src": "black", "origin": "ai"}, {"t": 3, "mode": "full"}], "ai")
        self.assertEqual(1, rc)
        self.assertEqual("error", rep["issues"][0]["severity"])

    def test_blank_source_clip_of_one_second_or_more_is_an_error(self):
        rc, rep = self.run_cli([{"t": 0, "media": "clip", "src": "white", "origin": "source"}, {"t": 3, "mode": "full"}], "source")
        self.assertEqual(1, rc)
        self.assertFalse(rep["pass"])
        self.assertEqual([("blank-frame", "error")], [(i["code"], i["severity"]) for i in rep["issues"]])
        self.assertEqual({"error": 1, "warn": 0}, rep["counts"]["by_code"]["blank-frame"])

    def test_short_blank_source_clip_is_a_warning_and_passes(self):
        ensure_blank_media()
        rc, rep = self.run_cli([{"t": 0, "media": "clip", "src": "bl_full06", "origin": "source"}, {"t": 6, "mode": "full"}], "short")
        self.assertEqual(0, rc)
        self.assertTrue(rep["pass"])
        self.assertEqual([("blank-frame", "warn")], [(i["code"], i["severity"]) for i in rep["issues"]])
        self.assertEqual({"error": 0, "warn": 1}, rep["counts"]["by_code"]["blank-frame"])

    def test_warn_does_not_hide_a_real_error(self):
        ensure_blank_media()
        beats = [{"t": 0, "media": "clip", "src": "bl_full06", "origin": "source"}, {"t": 6, "media": "clip", "src": "gone", "origin": "source"},
                 {"t": 9, "mode": "full"}]
        rc, rep = self.run_cli(beats, "mixed")
        self.assertEqual(1, rc)
        self.assertFalse(rep["pass"])
        self.assertEqual({"error": 1, "warn": 1}, {k: rep["counts"][k] for k in ("error", "warn")})

    def test_every_issue_has_a_severity_and_hard_codes_are_errors(self):
        beats = [{"t": 0, "media": "clip", "src": "gone", "origin": "source"},
                 {"t": 3, "media": "clip", "src": "bg1", "origin": "source"},        # 6 s on a 4 s cut -> source-loop
                 {"t": 9, "media": "broll", "src": "bg1", "origin": "stock", "from": 99},
                 {"t": 12, "media": "clip", "src": "clean", "origin": "source"},
                 {"t": 15, "media": "clip", "src": "clean_copy", "origin": "source"},   # shot-reuse
                 {"t": 18, "mode": "full"}]
        rc, rep = self.run_cli(beats, "all")
        got = {i["code"]: i["severity"] for i in rep["issues"]}
        for code in ("media-missing", "source-loop", "from-out-of-range", "shot-reuse"):
            self.assertEqual("error", got.get(code), (code, got))
        self.assertTrue(all(i.get("severity") in ("error", "warn") for i in rep["issues"]))

    def test_severity_of_codes(self):
        for c in ("watermark", "promo-text", "shot-reuse", "source-loop", "broll-dur-mismatch", "media-missing", "from-out-of-range",
                  "ocr-failed", "no-frames", "frame-missing"):
            self.assertEqual("error", fc.severity_for(c, {"origin": "source", "media": "clip"}), c)
        self.assertEqual("warn", fc.severity_for("blank-frame", {"origin": "source", "media": "clip"}))
        self.assertEqual("error", fc.severity_for("blank-frame", {"origin": "stock", "media": "broll"}))
        self.assertEqual("error", fc.severity_for("blank-frame", {"origin": "ai", "media": "broll"}))

    def test_single_range_pixels_origin_option(self):
        v = str(Media.dir / "white.mp4")
        self.assertEqual(1, fc.main(["pixels", "--video", v, "--in", "0", "--out", "4"]))
        self.assertEqual(1, fc.main(["pixels", "--video", v, "--in", "0", "--out", "4", "--origin", "stock"]))
        self.assertEqual(0, fc.main(["pixels", "--video", v, "--in", "0", "--out", "4", "--origin", "source"]))

    def test_crop_propose_box_only_hashes_source_beats(self):
        beats = [{"t": 0, "media": "broll", "src": "boxed", "origin": "stock"}, {"t": 3, "media": "clip", "src": "boxed_b", "origin": "source"},
                 {"t": 6, "media": "broll", "src": "boxed", "origin": "stock", "srcCrop": {"x": 360, "y": 202, "w": 1200, "h": 675}},
                 {"t": 9, "mode": "full"}]
        rc, rep = self.run_cli(beats, "hash")
        kinds = [(b["origin"], b["hashBox"]["kind"]) for b in rep["beats"]]
        self.assertEqual([("stock", "frame"), ("source", "crop-propose"), ("stock", "srcCrop")], kinds)

    def test_crop_check_issues_carry_severity(self):
        v = Media.dir / "boxed.mp4"
        r = fc.check_crop(v, 0, 5, (360, 202, 1200, 603))
        self.assertEqual(["warn"], [w["severity"] for w in r["warnings"]])
        r = fc.check_crop(v, 0, 5, (360, 202, 1200, 400))
        self.assertEqual({"error"}, {e["severity"] for e in r["errors"]})


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
    def near(self, got, want, tol=14):
        for k, v in zip("xywh", want):
            self.assertLessEqual(abs(got[k] - v), tol, (k, got, want))
            self.assertIsInstance(got[k], int)

    def test_propose_is_in_1920_space(self):
        r = fc.propose_crop(Media.dir / "boxed.mp4", 0, 5)      # 1280x720 file, picture 800x450 at (240,135)
        self.near(r, (360, 202, 1200, 675))
        self.assertGreaterEqual(r["confidence"], 0.7)
        self.assertIn("reason", r)

    def test_propose_pillarbox_snaps_to_16_9(self):
        r = fc.propose_crop(Media.dir / "pillar.mp4", 0, 5)     # 960x720 picture at x=160 => 1440x1080 at 240
        self.near(r, (240, 135, 1440, 810))
        self.assertLess(abs(r["w"] / r["h"] / (16 / 9) - 1), 0.02)

    def test_propose_no_bars_is_full_frame(self):
        r = fc.propose_crop(Media.dir / "clean.mp4", 0, 6)
        self.near(r, (0, 0, 1920, 1080), tol=4)

    def test_check_positive(self):
        r = fc.check_crop(Media.dir / "boxed.mp4", 0, 5, (360, 202, 1200, 675))
        self.assertTrue(r["pass"], r)

    def test_check_negatives(self):
        v = Media.dir / "boxed.mp4"
        self.assertEqual(["crop-out-of-bounds"], codes(fc.check_crop(v, 0, 5, (1100, 202, 1200, 675))["errors"]))
        self.assertEqual(["crop-out-of-bounds"], codes(fc.check_crop(v, 0, 5, (360, 600, 1200, 675))["errors"]))
        self.assertIn("crop-aspect", codes(fc.check_crop(v, 0, 5, (360, 202, 1200, 400))["errors"]))       # 3.0 : 1
        self.assertIn("crop-too-small", codes(fc.check_crop(v, 0, 5, (360, 202, 480, 270))["errors"]))

    def test_check_aspect_tolerances_are_s11(self):
        v = Media.dir / "boxed.mp4"
        # 12 % off 16:9: warning only
        r = fc.check_crop(v, 0, 5, (360, 202, 1200, 603))
        self.assertTrue(r["pass"], r)
        self.assertEqual(["crop-aspect"], codes(r["warnings"]))
        # 5 % off: nothing
        r = fc.check_crop(v, 0, 5, (360, 202, 1200, 643))
        self.assertEqual([], r["warnings"] + r["errors"])
        # 30 % off: error
        r = fc.check_crop(v, 0, 5, (360, 202, 1200, 520))
        self.assertFalse(r["pass"])
        self.assertEqual(["crop-aspect"], codes(r["errors"]))

    def test_check_blank_inside_is_an_error(self):
        self.assertEqual(["crop-blank-frame"], codes(fc.check_crop(Media.dir / "white_big.mp4", 0, 3, (0, 0, 1920, 1080))["errors"]))
        self.assertEqual(["crop-blank-frame"], codes(fc.check_crop(Media.dir / "black_big.mp4", 0, 3, (0, 0, 1920, 1080))["errors"]))

    def test_cli_exit_codes(self):
        v = str(Media.dir / "boxed.mp4")
        self.assertEqual(0, fc.main(["crop-propose", "--video", v, "--in", "0", "--out", "5"]))
        self.assertEqual(0, fc.main(["crop-check", "--video", v, "--in", "0", "--out", "5", "--crop", "360:202:1200:675"]))
        self.assertEqual(1, fc.main(["crop-check", "--video", v, "--in", "0", "--out", "5", "--crop", "360:202:1200:400"]))


if __name__ == "__main__":
    unittest.main()
