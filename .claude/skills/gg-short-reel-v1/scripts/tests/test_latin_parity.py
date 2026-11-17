"""R4-2: "Latin" has ONE standard, /\\p{Script=Latin}/u, shared with AIOS. The table comes from node (gen_latin_script_ranges.mjs)."""
import bisect
import shutil
import subprocess
import unittest

import test_support as ts  # noqa: F401  (puts scripts/ on sys.path)

# Shared parity sample list: the AIOS worker uses exactly this list.
MUST_PASS = ("ʰ", "ˢ", "ᵗ", "Ⅎ", "ª", "º", "é", "ﬀ", "Ａ", "100ᵗʰ birthday", "❤️👵", "2026")
MUST_FAIL = ("สวัสดี", "Привет", "Γειά", "你好", "こんにちは")

DUMP_JS = (
    "const re=/\\p{Script=Latin}/u;const out=[];"
    "for(let c=0;c<=0x10FFFF;c++){if(re.test(String.fromCodePoint(c)))out.push(c)}"
    "process.stdout.write(out.join(' '))"
)


class ParitySampleTests(unittest.TestCase):
    def setUp(self):
        import overlay
        self.overlay = overlay

    def test_must_pass_has_no_offending_letters(self):
        for text in MUST_PASS:
            with self.subTest(text=text):
                self.assertEqual([], self.overlay.non_latin_letters(text))

    def test_must_fail_has_offending_letters(self):
        for text in MUST_FAIL:
            with self.subTest(text=text):
                self.assertNotEqual([], self.overlay.non_latin_letters(text))

    def test_error_text_and_sample_cap_unchanged(self):
        with self.assertRaises(self.overlay.OverlayError) as cm:
            self.overlay.parse_items([{"text": "กขคงจฉ", "start_s": 0, "end_s": 1, "placement": "top"}])
        msg = str(cm.exception)
        self.assertIn('ต้องเป็นภาษาอังกฤษเท่านั้น (พบอักษรที่ไม่ใช่ละติน "กขคงจ")', msg)


class TableTests(unittest.TestCase):
    def test_header_records_node_and_unicode_versions_and_command(self):
        text = (ts.SCRIPTS / "latin_script_ranges.py").read_text(encoding="utf-8")
        for needle in ("Node: v", "process.versions.unicode", "Regenerate:", "gen_latin_script_ranges.mjs"):
            self.assertIn(needle, text)

    def test_table_is_sorted_disjoint_inclusive_ranges(self):
        import latin_script_ranges as t
        prev_end = -1
        for a, b in t.LATIN_RANGES:
            self.assertLessEqual(a, b)
            self.assertGreater(a, prev_end + 1, "sorted, disjoint and non-adjacent (merged)")
            prev_end = b

    def test_table_matches_live_node_over_all_planes(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not on PATH: cannot compare the table with the live /\\p{Script=Latin}/u")
        import latin_script_ranges as t
        proc = subprocess.Popen([node, "-e", DUMP_JS], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            out, err = proc.communicate(timeout=120)   # exits on its own
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        self.assertEqual(0, proc.returncode, err)
        live = {int(x) for x in out.split()}
        table = {cp for a, b in t.LATIN_RANGES for cp in range(a, b + 1)}
        self.assertEqual(live, table)
        starts = [a for a, _ in t.LATIN_RANGES]
        for cp in (0x41, 0x2B0, 0x2E2, 0x1D57, 0x2132, 0xAA, 0xBA, 0xFB00, 0xFF21):
            i = bisect.bisect_right(starts, cp) - 1
            self.assertTrue(i >= 0 and cp <= t.LATIN_RANGES[i][1], hex(cp))


if __name__ == "__main__":
    unittest.main()
