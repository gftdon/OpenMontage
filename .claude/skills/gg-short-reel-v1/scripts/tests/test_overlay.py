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


if __name__ == "__main__":
    unittest.main()
