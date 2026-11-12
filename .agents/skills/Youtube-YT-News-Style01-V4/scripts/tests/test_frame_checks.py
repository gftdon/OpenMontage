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
    def run_beats(self, beats, cuts=None, end=200, obj=None, roots=None):
        p = Media.dir / ("beats_cut.json" if obj is None else "episode_cut.json")
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
        self.assertEqual({"schema", "version", "pass", "counts", "issues", "beats", "tools", "inputs", "seconds"}, set(rep))
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



class SeverityTests(unittest.TestCase):
    """Wave 3: blank-frame is an error on stock/ai, a warn on source; only errors fail the run."""

    def fake(self, paths):
        return {p: ok_lines() for p in paths}

    def run_cli(self, beats, name, extra=()):
        b = Media.dir / f"sev_{name}.json"
        b.write_text(json.dumps(beats))
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

    def test_blank_source_is_warn_and_passes(self):
        rc, rep = self.run_cli([{"t": 0, "media": "clip", "src": "white", "origin": "source"}, {"t": 3, "mode": "full"}], "source")
        self.assertEqual(0, rc)
        self.assertTrue(rep["pass"])
        self.assertEqual([("blank-frame", "warn")], [(i["code"], i["severity"]) for i in rep["issues"]])
        self.assertEqual(0, rep["counts"]["error"])
        self.assertEqual(1, rep["counts"]["warn"])
        self.assertEqual({"error": 0, "warn": 1}, rep["counts"]["by_code"]["blank-frame"])

    def test_warn_does_not_hide_a_real_error(self):
        beats = [{"t": 0, "media": "clip", "src": "white", "origin": "source"}, {"t": 3, "media": "clip", "src": "gone", "origin": "source"},
                 {"t": 6, "mode": "full"}]
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
