import os
import tempfile
import unittest
from pathlib import Path

import test_support as ts  # noqa: F401  (puts scripts/ on sys.path)

LONG_EN = ("The quick brown fox jumps over the lazy dog while the grandparents watch in total disbelief "
           "as the dog does something nobody expected at all, and then everybody laughs together happily.")
LONG_TH = "ยายกับตาหัวเราะเสียงดังเมื่อหลานทำสิ่งที่ไม่มีใครคาดคิดมาก่อนในชีวิตและทุกคนก็ตกใจกันทั้งบ้าน" * 2
SAFE = (90, 210, 990, 1600)


class SafeZoneTests(unittest.TestCase):
    def setUp(self):
        import overlay
        self.overlay = overlay
        self.font = overlay.resolve_font()

    def assertInSafe(self, box):
        x0, y0, x1, y1 = box
        self.assertGreaterEqual(x0, SAFE[0])
        self.assertGreaterEqual(y0, SAFE[1])
        self.assertLessEqual(x1, SAFE[2])
        self.assertLessEqual(y1, SAFE[3])

    def test_c_boxes_inside_safe_zone_for_all_placements(self):
        for text in ("สั้น ๆ", "Short", LONG_EN, LONG_TH, "บรรทัดแรก\nบรรทัดสอง\nบรรทัดสาม"):
            for placement in ("top", "center", "bottom"):
                with self.subTest(text=text[:12], placement=placement):
                    lay = self.overlay.layout_item(text, placement, self.font)
                    self.assertInSafe(lay.box)
                    self.assertGreaterEqual(lay.font_size, 42)
                    self.assertTrue(all(lay.line_widths[i] <= lay.box[2] - lay.box[0] for i in range(len(lay.lines))))

    def test_c_anchors(self):
        top = self.overlay.layout_item("Hi", "top", self.font)
        bottom = self.overlay.layout_item("Hi", "bottom", self.font)
        center = self.overlay.layout_item("Hi", "center", self.font)
        self.assertEqual(210, top.box[1])
        self.assertEqual(1600, bottom.box[3])
        self.assertAlmostEqual(905, (center.box[1] + center.box[3]) / 2, delta=1.5)
        self.assertAlmostEqual(540, (center.box[0] + center.box[2]) / 2, delta=1.5)

    def test_c_long_text_wraps(self):
        for text in (LONG_EN, LONG_TH):
            lay = self.overlay.layout_item(text, "center", self.font)
            self.assertGreater(len(lay.lines), 1)
            self.assertEqual("".join(text.split()), "".join("".join(lay.lines).split()), "no characters lost by wrapping")

    def test_c_thai_wrap_keeps_marks_and_leading_vowels_attached(self):
        lay = self.overlay.layout_item(LONG_TH, "center", self.font)
        for line in lay.lines:
            self.assertNotIn(line[:1], "ะัาำิีึืฺุู็่้๊๋์ํ", "line starts with a combining mark")
            self.assertNotIn(line[-1:], "เแโใไ", "line ends with a leading vowel")

    def test_c_unfittable_text_fails(self):
        with self.assertRaises(self.overlay.OverlayError):
            self.overlay.layout_item("ก" * 6000, "top", self.font)

    def test_c_png_ink_inside_box_and_not_clipped(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            for text in (LONG_TH, "จังหวะนี้ใครก็ไม่คาด", LONG_EN):
                lay = self.overlay.layout_item(text, "top", self.font)
                png = Path(d) / "t.png"
                self.overlay.render_png(lay, self.font, png)
                im = Image.open(png)
                self.assertEqual((lay.box[2] - lay.box[0], lay.box[3] - lay.box[1]), im.size)
                bbox = im.getchannel("A").getbbox()
                self.assertIsNotNone(bbox)
                self.assertGreater(bbox[0], 0)
                self.assertGreater(bbox[1], 0)
                self.assertLess(bbox[2], im.size[0])
                self.assertLess(bbox[3], im.size[1])

    def test_c_times_clamped_and_empty_dropped(self):
        ov = self.overlay
        items = ov.parse_items([
            {"text": "a", "start_s": 0.5, "end_s": 3, "placement": "top"},
            {"text": "b", "start_s": 0, "end_s": 99, "placement": "center"},
            {"text": "c", "start_s": 20, "end_s": 30, "placement": "bottom"},   # starts after video end
            {"text": "d", "start_s": 5, "end_s": 5, "placement": "top"},        # empty
            {"text": "e", "start_s": 11.9, "end_s": 15, "placement": "top"},
        ])
        kept = ov.clamp_items(items, 12.0)
        self.assertEqual(["a", "b", "e"], [k.text for k in kept])
        self.assertEqual((0.5, 3.0), (kept[0].start_s, kept[0].end_s))
        self.assertEqual((0.0, 12.0), (kept[1].start_s, kept[1].end_s))
        self.assertEqual((11.9, 12.0), (kept[2].start_s, kept[2].end_s))

    def test_parse_items_rejects_bad_items(self):
        ov = self.overlay
        for bad in ([{"text": "x", "start_s": 0, "end_s": 1, "placement": "left"}],
                    [{"text": "x", "start_s": float("nan"), "end_s": 1, "placement": "top"}],
                    [{"text": "", "start_s": 0, "end_s": 1, "placement": "top"}],
                    [{"text": "x", "start_s": "0", "end_s": 1, "placement": "top"}],
                    ["not a dict"], "not a list"):
            with self.subTest(bad=str(bad)[:40]), self.assertRaises(ov.OverlayError):
                ov.parse_items(bad)

    def test_font_resolution_order(self):
        ov = self.overlay
        with tempfile.TemporaryDirectory() as d:
            envfont = Path(d) / "env.ttf"
            envfont.write_bytes(b"x")
            self.assertEqual(envfont, ov.resolve_font(env={"GG_SHORT_FONT": str(envfont)}, repo_fonts=[]))
            with self.assertRaises(ov.OverlayError):  # env set but missing = explicit misconfiguration
                ov.resolve_font(env={"GG_SHORT_FONT": str(Path(d) / "nope.ttf")}, repo_fonts=[])
            with self.assertRaises(ov.OverlayError):  # nothing found anywhere
                ov.resolve_font(env={}, repo_fonts=[Path(d) / "a.ttf", Path(d) / "b.ttf"])
            second = Path(d) / "second.ttf"
            second.write_bytes(b"x")
            self.assertEqual(second, ov.resolve_font(env={}, repo_fonts=[Path(d) / "a.ttf", second]))


class UnrenderableStripTests(unittest.TestCase):
    """Characters Kanit has no glyph for (emoji etc.) are removed before layout, never rendered as tofu boxes."""

    def setUp(self):
        import overlay
        self.overlay = overlay
        self.font = overlay.resolve_font()

    def strip(self, text):
        return self.overlay.strip_unrenderable(text, self.font)

    def test_emoji_variation_selector_zwj_and_skin_tone_removed(self):
        self.assertEqual("ใจ", self.strip("❤️ ใจ")[0])
        self.assertEqual("ok", self.strip("👍🏽 ok")[0])
        self.assertEqual("สวัสดีค่ะ", self.strip("สวัสดีค่ะ 🙏")[0])
        self.assertEqual("a b", self.strip("a 👨‍👩‍👧 b")[0])
        self.assertEqual("", self.strip("❤️👍🏽\U0001F64F")[0])
        self.assertEqual("ใครคิดถึงคุณยายบ้าง กดหัวใจให้หน่อย",
                         self.strip("ใครคิดถึงคุณยายบ้าง กดหัวใจให้หน่อย ❤")[0])

    def test_removed_characters_are_reported(self):
        clean, removed = self.strip("สวัสดีค่ะ 🙏")
        self.assertEqual("🙏", removed)
        self.assertEqual("", self.strip("ok")[1])

    def test_supported_text_is_unchanged(self):
        for text in ("สวัสดีค่ะ คุณยาย", "ยายกับตาหัวเราะเสียงดังเมื่อหลานทำสิ่งที่ไม่มีใครคาดคิด", "Hello World",
                     "2026 100% real!?.,", "บรรทัดแรก\nบรรทัดสอง", "café — ok’s…", "a  b"):
            with self.subTest(text=text):
                self.assertEqual((text, ""), self.strip(text))

    def test_double_spaces_collapsed_and_trimmed_only_after_removal(self):
        self.assertEqual("a b", self.strip("a ❤ b")[0])
        self.assertEqual("ก ข", self.strip("  ❤  ก  ❤❤  ข  ❤ ")[0])
        self.assertEqual("บน\nล่าง", self.strip("บน ❤\n\n❤\nล่าง")[0])

    def _items(self, *texts):
        # built directly (not via parse_items, which now rejects non-Latin text): these tests are about glyph stripping
        return [self.overlay.TextItem(t.strip(), 0.0, 2.0, "top", i) for i, t in enumerate(texts)]

    def test_sanitize_items_drops_emoji_only_item_and_logs_to_stderr(self):
        import contextlib
        import io
        items = self._items("ใจ ❤️", "❤️❤️", "ok")
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            kept = self.overlay.sanitize_items(items, self.font)
        self.assertEqual(["ใจ", "ok"], [k.text for k in kept])
        log = buf.getvalue()
        self.assertIn("on_screen_text[0]", log)
        self.assertIn("❤", log)
        self.assertIn("on_screen_text[1]", log)
        self.assertNotIn("on_screen_text[2]", log)

    def test_sanitize_items_keeps_original_index_after_clamp(self):
        import contextlib
        import io
        items = self.overlay.clamp_items(self._items("a", "b ❤"), 12.0)
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            self.overlay.sanitize_items(items[1:], self.font)
        self.assertIn("on_screen_text[1]", buf.getvalue())

    def test_sanitize_items_silent_when_nothing_removed(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            kept = self.overlay.sanitize_items(self._items("สวัสดี", "ok"), self.font)
        self.assertEqual("", buf.getvalue())
        self.assertEqual(["สวัสดี", "ok"], [k.text for k in kept])

    def test_rendered_png_has_no_tofu(self):
        from PIL import Image
        ov = self.overlay
        with tempfile.TemporaryDirectory() as d:
            def render(text, name):
                lay = ov.layout_item(text, "center", self.font)
                png = Path(d) / name
                ov.render_png(lay, self.font, png)
                return Image.open(png).convert("RGBA").tobytes(), lay.box

            clean_text, _ = self.strip("ใครคิดถึงคุณยายบ้าง ❤")
            self.assertEqual("ใครคิดถึงคุณยายบ้าง", clean_text)
            got = render(clean_text, "a.png")
            self.assertEqual(render("ใครคิดถึงคุณยายบ้าง", "b.png"), got)
            self.assertNotEqual(render("ใครคิดถึงคุณยายบ้าง ❤", "c.png"), got)   # the unstripped one has a tofu box

    @unittest.skipUnless(ts.HAVE_FFMPEG, "ffmpeg not installed")
    def test_burn_with_only_unrenderable_text_still_produces_video(self):
        import contextlib
        import io
        import common
        ov = self.overlay
        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / "base.mp4"
            ts.subprocess.run([ts.FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=216x384:r=30:d=1",
                               "-pix_fmt", "yuv420p", str(base)], check=True)
            out = Path(d) / "out.mp4"
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                ov.burn(base, self._items("❤️"), self.font, out, d, common.Deadline(60))
            self.assertTrue(out.is_file() and out.stat().st_size > 0)
            self.assertIn("on_screen_text[0]", buf.getvalue())


class EnglishOnlyTests(unittest.TestCase):
    """CF-A85 R3-7: on-screen text must be Latin-script (G&G on-video text is English)."""

    def setUp(self):
        import overlay
        self.overlay = overlay

    def _parse(self, *texts):
        return self.overlay.parse_items([{"text": t, "start_s": 0, "end_s": 2, "placement": "top"} for t in texts])

    def test_thai_in_item_1_names_the_index_and_shows_sample(self):
        with self.assertRaises(self.overlay.OverlayError) as cm:
            self._parse("Hello", "ยายกับตา")
        msg = str(cm.exception)
        self.assertIn("on_screen_text[1]", msg)
        self.assertNotIn("on_screen_text[0]", msg)
        self.assertIn("ต้องเป็นภาษาอังกฤษเท่านั้น", msg)
        self.assertIn('"ยากบต"', msg)   # distinct letters, in order of appearance

    def test_japanese_and_cyrillic_rejected(self):
        for text in ("こんにちは", "Привет", "mixed ok สวัสดี", "한국어", "مرحبا"):
            with self.subTest(text=text), self.assertRaises(self.overlay.OverlayError):
                self._parse(text)

    def test_sample_is_capped_at_five_distinct_characters(self):
        with self.assertRaises(self.overlay.OverlayError) as cm:
            self._parse("กขคงจฉชซญ กขค")
        msg = str(cm.exception)
        self.assertIn("กขคงจ", msg)
        self.assertNotIn("ฉ", msg)

    def test_decomposed_input_is_normalised_before_judging(self):
        import unicodedata
        self.assertEqual(1, len(self._parse(unicodedata.normalize("NFD", "Café déjà vu"))))

    def test_english_and_latin_variants_pass(self):
        for text in ("Look closely at the second shot", "I love you ❤", "I love you ❤️ 👍🏽", "Café déjà vu", "Señor Müller",
                     "ＡＩ", "2026", "100% !?.,—…", "1ª y 2º", "Line one\nLine two"):
            with self.subTest(text=text):
                self.assertEqual(1, len(self._parse(text)))

    def test_check_runs_on_raw_text_before_stripping(self):
        # a Thai word next to an emoji is still rejected (the emoji would be stripped later, the Thai is not)
        with self.assertRaises(self.overlay.OverlayError):
            self._parse("❤️ ใจ")


if __name__ == "__main__":
    unittest.main()
