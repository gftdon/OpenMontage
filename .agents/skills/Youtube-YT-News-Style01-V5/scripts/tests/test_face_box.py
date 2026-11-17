"""Tests for face_box.py (CF-A67 W4 + W4b centre / size rules). Geometry, decision table, report schema and CLI exit codes run without
swift / ffmpeg (fake runners injected). One real-clip test is skipped unless the two lead-measured clips exist.
"""
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location("face_box", SCRIPTS / "face_box.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


fb = load()

SP = "/private/tmp/claude-501/-Volumes-Ext-SS990Pro-Dev-ai-business-os-fable/ad1c62c1-0730-4732-a74c-029d7ea153a0/scratchpad"
CLIP_A = Path(SP) / "a67-wp6/video-tasks/V261111_001/steps/3ad7a94c-2b5f-4f60-8b78-a5e573734cfa/runs/1/V261111_001_10_Vdo_Avatar.mp4"
WP6_EPISODE = Path("/Volumes/Ext_SS990Pro/Dev/openMontage-worktrees/cf-a67-wp6-proof/projects/V261111_001/artifacts/episode.json")
CLIP_B = Path("/Volumes/Ext_SS990Pro/Dev/openMontage-worktrees/cf-a66-engine/remotion-composer/public/ytNewsV3BrollTest/avatar_source.mp4")

FACE = {"x": 0.40, "y": 0.20, "w": 0.10, "h": 0.20}      # centre (0.45, 0.30) of a plausible presenter
GOOD_BOX = {"x": 0.38, "y": 0.18, "w": 0.14, "h": 0.24}  # contains FACE fully, centred on it (0.45, 0.30), 1.4x / 1.2x


def fake_measurement(faces, recommended="auto"):
    """A measurement dict as measure() returns it, built from per-frame faces (None = no face)."""
    n = len(faces)
    frames = [{"t": float(i), "face": f, "faces": 0 if f is None else 1, "error": None} for i, f in enumerate(faces)]
    found = [f for f in faces if f is not None]
    u = fb.union_box(found)
    return {"schema": fb.SCHEMA, "version": fb.VERSION, "avatar_sha256": "0" * 64, "duration": 100.0,
            "frame_count": n, "times": [fr["t"] for fr in frames], "frames": frames, "frames_with_face": len(found),
            "union": u, "recommended": fb.recommend_box(u) if recommended == "auto" else recommended}


class Geometry(unittest.TestCase):
    def test_share_fully_inside_is_one(self):
        self.assertAlmostEqual(fb.share_inside(FACE, GOOD_BOX), 1.0)

    def test_share_partial_overlap(self):
        # box covers the top 3/4 of the face -> 0.75
        box = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.35}
        self.assertAlmostEqual(fb.share_inside(FACE, box), 0.75)

    def test_share_disjoint_is_zero(self):
        self.assertEqual(fb.share_inside(FACE, {"x": 0.0, "y": 0.0, "w": 0.1, "h": 0.1}), 0.0)

    def test_share_degenerate_face_is_zero(self):
        self.assertEqual(fb.share_inside({"x": 0.4, "y": 0.2, "w": 0.0, "h": 0.2}, GOOD_BOX), 0.0)

    def test_union(self):
        u = fb.union_box([{"x": 0.40, "y": 0.20, "w": 0.10, "h": 0.20}, {"x": 0.45, "y": 0.15, "w": 0.10, "h": 0.20}])
        self.assertAlmostEqual(u["x"], 0.40)
        self.assertAlmostEqual(u["y"], 0.15)
        self.assertAlmostEqual(u["w"], 0.15)
        self.assertAlmostEqual(u["h"], 0.25)

    def test_union_empty_is_none(self):
        self.assertIsNone(fb.union_box([]))
        self.assertIsNone(fb.recommend_box(None))

    def test_recommend_expands_and_rounds_outward(self):
        # union x 0.4061..0.5594, y 0.1566..0.4565 (clip A) -> margin 0.02 -> 0.3861..0.5794 / 0.1366..0.4765
        u = {"x": 0.4061, "y": 0.1566, "w": 0.1533, "h": 0.2999}
        self.assertEqual(fb.recommend_box(u), {"x": 0.38, "y": 0.13, "w": 0.20, "h": 0.35})

    def test_recommend_never_cuts_the_face(self):
        # whatever the union is, the recommended box contains it entirely (outward rounding)
        for x, y, w, h in [(0.4061, 0.1566, 0.1533, 0.2999), (0.411, 0.149, 0.1566, 0.3024), (0.5, 0.5, 0.123456, 0.0001)]:
            u = {"x": x, "y": y, "w": w, "h": h}
            r = fb.recommend_box(u)
            self.assertLessEqual(r["x"], x)
            self.assertLessEqual(r["y"], y)
            self.assertGreaterEqual(r["x"] + r["w"], x + w)
            self.assertGreaterEqual(r["y"] + r["h"], y + h)

    def test_recommend_exact_hundredths_do_not_round_the_wrong_way(self):
        # 0.41 - 0.02 is 0.39 in decimal but 0.38999999999999996 in floats: must stay 0.39, not drop to 0.38
        r = fb.recommend_box({"x": 0.41, "y": 0.41, "w": 0.0, "h": 0.0}, margin=0.02)
        self.assertEqual((r["x"], r["y"]), (0.39, 0.39))
        self.assertEqual((r["w"], r["h"]), (0.04, 0.04))

    def test_recommend_clamps_to_unit_square(self):
        r = fb.recommend_box({"x": 0.01, "y": 0.0, "w": 0.98, "h": 0.995})
        self.assertEqual(r, {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0})

    def test_largest_face_is_the_presenter(self):
        small = {"x": 0.1, "y": 0.1, "w": 0.05, "h": 0.05}
        big = {"x": 0.4, "y": 0.2, "w": 0.14, "h": 0.25}
        self.assertEqual(fb.largest_face([small, big]), big)
        self.assertIsNone(fb.largest_face([]))

    def test_sample_times_fixed_positions(self):
        t = fb.sample_times(100.0)
        self.assertEqual(len(t), 40)
        self.assertEqual(t[0], 2.0)
        self.assertEqual(t[-1], 98.0)
        self.assertEqual(t[1], round(2.0 + 96.0 / 39, 2))
        self.assertEqual(t, fb.sample_times(100.0))  # same every call
        self.assertTrue(all(abs(x * 100 - round(x * 100)) < 1e-6 for x in t))  # 0.01 s grid

    def test_sample_times_short_clip_is_usage_error(self):
        with self.assertRaises(fb.UsageError):
            fb.sample_times(19.99)
        self.assertEqual(len(fb.sample_times(20.0)), 40)


class DecisionTable(unittest.TestCase):
    def test_pass_when_every_frame_inside(self):
        v = fb.check(fake_measurement([FACE] * 40), GOOD_BOX)
        self.assertTrue(v["pass"])
        self.assertIsNone(v["reason"])
        self.assertAlmostEqual(v["min_share"], 1.0)
        self.assertEqual(v["frames_with_face"], 40)

    def test_exactly_ninety_percent_passes_and_just_below_fails(self):
        # face 0.5 x 0.5 at the origin; a box of height 0.45 holds exactly 0.9 of it; 0.44 holds 0.88
        face = {"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5}
        at = fb.check(fake_measurement([face] * 40), {"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.45})
        self.assertTrue(at["pass"], at)
        below = fb.check(fake_measurement([face] * 40), {"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.44})
        self.assertFalse(below["pass"])
        self.assertEqual(below["reason"], "share-below-threshold")

    def test_one_bad_frame_fails_even_when_the_rest_are_perfect(self):
        faces = [FACE] * 40
        faces[17] = {"x": 0.40, "y": 0.34, "w": 0.10, "h": 0.20}   # chin-down frame: only 0.30..0.45 of y in box
        m = fake_measurement(faces)
        v = fb.check(m, GOOD_BOX)
        self.assertFalse(v["pass"])
        self.assertEqual(v["reason"], "share-below-threshold")
        self.assertEqual(v["worst"]["t"], 17.0)
        self.assertLess(v["worst"]["share"], 0.90)
        self.assertEqual(v["frames_below"], 1)

    def test_too_few_faces_fails_even_with_a_perfect_box(self):
        faces = [FACE] * 29 + [None] * 11
        v = fb.check(fake_measurement(faces), GOOD_BOX)
        self.assertFalse(v["pass"])
        self.assertEqual(v["reason"], "too-few-faces")
        self.assertEqual(v["frames_with_face"], 29)

    def test_thirty_faces_is_enough(self):
        faces = [FACE] * 30 + [None] * 10
        self.assertTrue(fb.check(fake_measurement(faces), GOOD_BOX)["pass"])

    def test_no_faces_at_all_fails(self):
        v = fb.check(fake_measurement([None] * 40), GOOD_BOX)
        self.assertFalse(v["pass"])
        self.assertEqual(v["reason"], "too-few-faces")
        self.assertIsNone(v["min_share"])
        self.assertIsNone(v["recommended"])

    def test_frames_with_face_is_recounted_not_trusted(self):
        m = fake_measurement([None] * 40)
        m["frames_with_face"] = 40          # a lying field must not turn "no faces" into a pass
        self.assertFalse(fb.check(m, GOOD_BOX)["pass"])

    def test_missing_or_invalid_box_fails(self):
        m = fake_measurement([FACE] * 40)
        for bad in (None, {}, {"x": 0.1, "y": 0.1, "w": 0.0, "h": 0.2}, {"x": "a", "y": 0, "w": 1, "h": 1},
                    {"x": 0.1, "y": 0.1, "w": 0.2}, {"x": True, "y": 0.1, "w": 0.2, "h": 0.2},
                    {"x": float("nan"), "y": 0.1, "w": 0.2, "h": 0.2}, [0.1, 0.1, 0.2, 0.2],
                    {"x": -0.1, "y": 0.1, "w": 0.5, "h": 0.5}):
            v = fb.check(m, bad)
            self.assertFalse(v["pass"], bad)
            self.assertEqual(v["reason"], "no-face-box", bad)
            self.assertIsNotNone(v["recommended"])      # the agent is still told what to write

    def test_integer_box_values_are_accepted(self):
        v = fb.check(fake_measurement([{"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}] * 40), {"x": 0, "y": 0, "w": 1, "h": 1})
        self.assertTrue(v["pass"])

    def test_recommended_box_always_passes_its_own_check(self):
        faces = [{"x": 0.40 + 0.003 * (i % 7), "y": 0.15 + 0.004 * (i % 11), "w": 0.13, "h": 0.24} for i in range(40)]
        m = fake_measurement(faces)
        self.assertTrue(fb.check(m, m["recommended"])["pass"])

    def test_wrong_guess_from_the_proof_run_fails_a_face_with_the_chin_outside(self):
        # chin at y = 0.458 is outside a box ending at 0.05 + 0.37 = 0.42: the lower 0.038 of a 0.30-high face is cut
        face = {"x": 0.45, "y": 0.158, "w": 0.10, "h": 0.30}
        v = fb.check(fake_measurement([face] * 40), {"x": 0.39, "y": 0.05, "w": 0.19, "h": 0.37})
        self.assertAlmostEqual(v["min_share"], (0.42 - 0.158) / 0.30, places=3)
        self.assertFalse(v["pass"])


def box_around(face_union_box, dx=0.0, dy=0.0, rw=1.2, rh=1.2):
    """A declared box with the given centre offset from `face_union_box` and size ratios rw / rh."""
    w, h = face_union_box["w"] * rw, face_union_box["h"] * rh
    cx = face_union_box["x"] + face_union_box["w"] / 2 + dx
    cy = face_union_box["y"] + face_union_box["h"] / 2 + dy
    return {"x": cx - w / 2, "y": cy - h / 2, "w": w, "h": h}


# a face big enough that every box below holds >= 90 % of it: 0.20 x 0.30 at (0.40, 0.20)
BIG = {"x": 0.40, "y": 0.20, "w": 0.20, "h": 0.30}


class CentreAndSizeRules(unittest.TestCase):
    """CF-A67 W4b: the renderer crops the card around the box centre, so share >= 90 % is not enough."""

    def verdict(self, box, faces=None):
        return fb.check(fake_measurement(faces or [BIG] * 40), box)

    # --- (a) centre ---------------------------------------------------------------------------
    def test_centred_box_passes_centre_rule(self):
        v = self.verdict(box_around(BIG))
        self.assertTrue(v["pass"], v)
        self.assertEqual(v["rules"], {"share": "pass", "frames": "pass", "centre": "pass", "size": "pass"})
        self.assertAlmostEqual(v["centre_offset"]["x"], 0.0, places=4)
        self.assertAlmostEqual(v["centre_offset"]["y"], 0.0, places=4)

    def test_off_centre_box_fails_centre_rule_on_x_even_with_full_share(self):
        # shifted 0.05 right: the face is still 100 % inside (box is 1.5x wide) but the card centre moves
        box = box_around(BIG, dx=0.05, rw=1.5, rh=1.2)
        v = self.verdict(box)
        self.assertAlmostEqual(v["min_share"], 1.0, places=3)
        self.assertFalse(v["pass"])
        self.assertEqual(v["reason"], "centre-off")
        self.assertEqual(v["rules"]["centre"], "fail")
        self.assertEqual(v["rules"]["share"], "pass")
        self.assertEqual(v["rules"]["size"], "pass")
        self.assertAlmostEqual(v["centre_offset"]["x"], 0.05, places=4)
        self.assertIn("centre", v["reasons"][0])
        self.assertIn("+0.050", v["reasons"][0])
        self.assertIn("0.045", v["reasons"][0])

    def test_off_centre_box_fails_centre_rule_on_y(self):
        v = self.verdict(box_around(BIG, dy=-0.05, rw=1.2, rh=1.5))
        self.assertEqual(v["reason"], "centre-off")
        self.assertAlmostEqual(v["centre_offset"]["y"], -0.05, places=4)
        self.assertAlmostEqual(v["centre_offset"]["x"], 0.0, places=4)

    def test_centre_offset_exactly_at_limit_passes_and_just_over_fails(self):
        self.assertEqual(fb.CENTRE_MAX_OFFSET, 0.045)
        at = self.verdict(box_around(BIG, dx=0.045, dy=-0.045, rw=1.5, rh=1.5))
        self.assertTrue(at["pass"], at)
        over = self.verdict(box_around(BIG, dx=0.0455, rw=1.5, rh=1.5))
        self.assertFalse(over["pass"])
        self.assertEqual(over["rules"]["centre"], "fail")
        over_y = self.verdict(box_around(BIG, dy=0.0455, rw=1.5, rh=1.5))
        self.assertEqual(over_y["rules"]["centre"], "fail")

    def test_mean_vs_union_centre_variant_is_reported_but_not_a_rule(self):
        # 39 frames at the left edge of the union, 1 frame far right: union centre != mean centre
        faces = [BIG] * 39 + [{"x": 0.50, "y": 0.20, "w": 0.20, "h": 0.30}]
        m = fake_measurement(faces)
        box = box_around(fb.union_box(faces), rw=1.2, rh=1.2)
        v = fb.check(m, box)
        self.assertTrue(v["pass"], v)
        self.assertAlmostEqual(v["centre_offset"]["x"], 0.0, places=4)
        self.assertGreater(abs(v["variants"]["centre_offset_mean"]["x"]), 0.04)   # mean centre sits 0.0475 left of the union centre

    # --- (b) size -----------------------------------------------------------------------------
    def test_box_exactly_at_size_limits_passes(self):
        self.assertTrue(self.verdict(box_around(BIG, rw=0.9, rh=0.9))["rules"]["size"] == "pass")  # share fails, size does not
        v = self.verdict(box_around(BIG, rw=1.5, rh=1.5))
        self.assertTrue(v["pass"], v)
        self.assertAlmostEqual(v["size_ratio"]["w"], 1.5, places=4)

    def test_oversized_box_fails_size_rule(self):
        v = self.verdict(box_around(BIG, rw=1.51, rh=1.2))
        self.assertFalse(v["pass"])
        self.assertEqual(v["reason"], "size-out-of-range")
        self.assertEqual(v["rules"]["size"], "fail")
        self.assertEqual(v["rules"]["centre"], "pass")
        self.assertIn("size", v["reasons"][0])
        self.assertIn("1.51x", v["reasons"][0])
        self.assertIn("1.5x", v["reasons"][0])

    def test_oversized_box_from_the_proof_analysis_fails_on_size_and_centre(self):
        # {.38,.10,.50,.40} on a face at x .406-.559, y .157-.457: share 1.0, but 3.3x wide and centre moved ~0.15
        face = {"x": 0.4061, "y": 0.1566, "w": 0.1533, "h": 0.2999}
        v = self.verdict({"x": 0.38, "y": 0.10, "w": 0.50, "h": 0.40}, faces=[face] * 40)
        self.assertAlmostEqual(v["min_share"], 1.0, places=3)
        self.assertFalse(v["pass"])
        self.assertEqual(v["rules"], {"share": "pass", "frames": "pass", "centre": "fail", "size": "fail"})
        self.assertEqual(len(v["reasons"]), 2)
        self.assertGreater(v["size_ratio"]["w"], 3.0)

    def test_whole_frame_box_fails_both_rules(self):
        face = {"x": 0.4061, "y": 0.1566, "w": 0.1533, "h": 0.2999}
        v = self.verdict({"x": 0, "y": 0, "w": 1, "h": 1}, faces=[face] * 40)
        self.assertFalse(v["pass"])
        self.assertEqual(v["rules"]["size"], "fail")
        self.assertEqual(v["rules"]["centre"], "fail")      # y centre 0.5 vs 0.307
        self.assertGreater(v["size_ratio"]["w"], 6.0)
        self.assertGreater(v["centre_offset"]["y"], 0.19)

    def test_whole_frame_box_around_a_centred_face_still_fails_on_size(self):
        centred = {"x": 0.45, "y": 0.45, "w": 0.10, "h": 0.10}
        v = fb.check(fake_measurement([centred] * 40), {"x": 0, "y": 0, "w": 1, "h": 1})
        self.assertEqual(v["rules"]["centre"], "pass")
        self.assertEqual(v["rules"]["size"], "fail")
        self.assertEqual(v["reason"], "size-out-of-range")

    # --- (b) size, small faces: the recommended box must always pass its own gate ------------------
    SMALL = {"x": 0.45, "y": 0.30, "w": 0.06, "h": 0.10}

    def test_small_face_recommended_box_passes_even_beyond_1_5x(self):
        m = fake_measurement([self.SMALL] * 40)
        rec = m["recommended"]
        self.assertGreater(rec["w"] / 0.06, 1.5)                      # the situation the extra term exists for
        v = fb.check(m, rec)
        self.assertTrue(v["pass"], v["reasons"])
        self.assertEqual(v["rules"]["size"], "pass")

    def test_small_face_box_above_recommended_plus_slack_fails(self):
        m = fake_measurement([self.SMALL] * 40)
        rec = m["recommended"]
        def grown(extra):   # the recommended box, widened and heightened by `extra` around its own centre
            return {"x": rec["x"] - extra / 2, "y": rec["y"] - extra / 2, "w": rec["w"] + extra, "h": rec["h"] + extra}
        self.assertTrue(fb.check(m, grown(0.01))["pass"])             # exactly recommended + 0.01 on both axes
        v = fb.check(m, grown(0.02))
        self.assertFalse(v["pass"])
        self.assertEqual(v["reason"], "size-out-of-range")
        self.assertEqual(v["rules"]["size"], "fail")
        self.assertEqual(v["rules"]["centre"], "pass")

    def test_small_face_lower_limit_still_applies(self):
        m = fake_measurement([self.SMALL] * 40)
        self.assertEqual(fb.check(m, box_around(self.SMALL, rw=0.85, rh=1.2))["rules"]["size"], "fail")

    def test_big_face_upper_limit_is_still_1_5x(self):
        # for the real-sized face the recommended box (1.2x) is far below 1.5x, so 1.5x governs
        v = self.verdict(box_around(BIG, rw=1.5, rh=1.5))
        self.assertEqual(v["rules"]["size"], "pass")
        self.assertEqual(self.verdict(box_around(BIG, rw=1.52, rh=1.2))["rules"]["size"], "fail")
        self.assertEqual(self.verdict(box_around(BIG, rw=1.2, rh=1.52))["rules"]["size"], "fail")

    def test_box_too_tight_fails_size_rule(self):
        v = self.verdict(box_around(BIG, rw=0.85, rh=1.2))
        self.assertEqual(v["rules"]["size"], "fail")
        self.assertIn("0.85x", v["reasons"][-1])

    def test_median_size_variant_is_reported_but_not_a_rule(self):
        faces = [BIG] * 38 + [{"x": 0.40, "y": 0.20, "w": 0.10, "h": 0.15}] * 2   # smaller faces in 2 frames
        v = fb.check(fake_measurement(faces), box_around(fb.union_box(faces), rw=1.3, rh=1.3))
        self.assertTrue(v["pass"], v)
        self.assertAlmostEqual(v["variants"]["median_face_size"]["w"], 0.20, places=4)
        self.assertAlmostEqual(v["variants"]["size_ratio_median"]["w"], 1.3, places=3)

    # --- result keys / messages ----------------------------------------------------------------
    def test_result_keys_are_added_and_old_keys_kept(self):
        v = self.verdict(box_around(BIG))
        for k in ("pass", "reason", "min_share", "worst", "frames_with_face", "recommended", "threshold", "min_face_frames",
                  "face_box", "shares", "frames_below"):
            self.assertIn(k, v)                         # the earlier contract (finalize reads some of these)
        for k in ("centre_offset", "size_ratio", "face_union", "rules", "reasons"):
            self.assertIn(k, v)
        self.assertEqual(set(v["centre_offset"]), {"x", "y"})
        self.assertEqual(set(v["size_ratio"]), {"w", "h"})
        self.assertEqual(set(v["face_union"]), {"x", "y", "w", "h"})
        self.assertEqual(v["reasons"], [])
        self.assertEqual(fb.build_report(fake_measurement([BIG] * 40), v)["version"], 1)
        json.dumps(fb.build_report(fake_measurement([BIG] * 40), v))

    def test_unverifiable_cases_fail_every_rule_that_needs_a_face(self):
        v = fb.check(fake_measurement([None] * 40), GOOD_BOX)
        self.assertEqual(v["rules"], {"share": "fail", "frames": "fail", "centre": "fail", "size": "fail"})
        self.assertIsNone(v["centre_offset"])
        self.assertIsNone(v["size_ratio"])
        self.assertIsNone(v["face_union"])
        v2 = fb.check(fake_measurement([FACE] * 40), None)
        self.assertEqual(v2["rules"]["centre"], "fail")
        self.assertEqual(v2["rules"]["size"], "fail")

    def test_face_union_is_recomputed_from_frames_not_trusted(self):
        m = fake_measurement([FACE] * 40)
        m["union"] = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}      # a lying field must not change the verdict
        self.assertTrue(fb.check(m, GOOD_BOX)["pass"])

    def test_recommended_box_passes_centre_and_size_rules(self):
        faces = [{"x": 0.40 + 0.003 * (i % 7), "y": 0.15 + 0.004 * (i % 11), "w": 0.15, "h": 0.30} for i in range(40)]
        m = fake_measurement(faces)
        v = fb.check(m, m["recommended"])
        self.assertTrue(v["pass"], v)
        self.assertLess(abs(v["centre_offset"]["x"]), 0.01)
        self.assertLess(abs(v["centre_offset"]["y"]), 0.01)


class MeasureWithFakeTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.avatar = Path(self.tmp.name) / "avatar.mp4"
        self.avatar.write_bytes(b"not really a video")
        self.extracted = []

    def tools(self, per_frame, duration=100.0, detect_override=None):
        """per_frame: callable(i) -> list of faces for the i-th extracted frame."""
        def extract(path, t, out, deadline):
            Path(out).write_bytes(b"jpg")
            self.extracted.append((t, out))

        def detect(paths, deadline):
            return {p: ({"path": p, "ok": True, "faces": per_frame(i)}) for i, p in enumerate(paths)}
        return {"duration": lambda p, d: duration, "extract": extract, "detect": detect_override or detect}

    def test_measure_samples_the_fixed_positions_and_cleans_up(self):
        m = fb.measure(self.avatar, tools=self.tools(lambda i: [FACE]))
        self.assertEqual(m["times"], fb.sample_times(100.0))
        self.assertEqual([t for t, _ in self.extracted], m["times"])
        self.assertEqual(m["frames_with_face"], 40)
        for _, out in self.extracted:
            self.assertFalse(os.path.exists(out), "frame files must be removed")
            self.assertFalse(os.path.exists(os.path.dirname(out)), "temp dir must be removed")
        self.assertEqual(m["schema"], "yt-news-v4-face-box")
        self.assertEqual(m["version"], 1)
        self.assertEqual(len(m["avatar_sha256"]), 64)

    def test_measure_picks_the_largest_face(self):
        small = {"x": 0.1, "y": 0.1, "w": 0.04, "h": 0.04}
        m = fb.measure(self.avatar, tools=self.tools(lambda i: [small, FACE]))
        self.assertEqual(m["frames"][0]["face"], FACE)
        self.assertEqual(m["frames"][0]["faces"], 2)

    def test_measure_is_deterministic(self):
        a = fb.measure(self.avatar, tools=self.tools(lambda i: [FACE]))
        b = fb.measure(self.avatar, tools=self.tools(lambda i: [FACE]))
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_frame_without_face_is_recorded_as_none(self):
        m = fb.measure(self.avatar, tools=self.tools(lambda i: [] if i % 2 else [FACE]))
        self.assertEqual(m["frames_with_face"], 20)
        self.assertIsNone(m["frames"][1]["face"])
        self.assertFalse(fb.check(m, GOOD_BOX)["pass"])

    def test_vision_failing_on_every_frame_is_a_tool_failure(self):
        def detect(paths, deadline):
            return {p: {"path": p, "ok": False, "error": "cannot decode image"} for p in paths}
        with self.assertRaises(fb.ToolFailure):
            fb.measure(self.avatar, tools=self.tools(lambda i: [], detect_override=detect))

    def test_missing_vision_result_is_a_tool_failure(self):
        def detect(paths, deadline):
            return {p: {"path": p, "ok": True, "faces": [FACE]} for p in paths[:-1]}
        with self.assertRaises(fb.ToolFailure):
            fb.measure(self.avatar, tools=self.tools(lambda i: [], detect_override=detect))

    def test_short_clip_is_a_usage_error(self):
        with self.assertRaises(fb.UsageError):
            fb.measure(self.avatar, tools=self.tools(lambda i: [FACE], duration=12.0))

    def test_missing_avatar_is_a_usage_error(self):
        with self.assertRaises(fb.UsageError):
            fb.measure(Path(self.tmp.name) / "nope.mp4", tools=self.tools(lambda i: [FACE]))

    def test_expired_deadline_is_a_tool_failure(self):
        with self.assertRaises(fb.ToolFailure):
            fb._run(["true"], 5, time.monotonic() - 1)


class ReportSchema(unittest.TestCase):
    def test_report_carries_schema_sha_times_frames_verdict(self):
        m = fake_measurement([FACE] * 40)
        v = fb.check(m, GOOD_BOX)
        r = fb.build_report(m, v)
        self.assertEqual(r["schema"], "yt-news-v4-face-box")
        self.assertEqual(r["version"], 1)
        self.assertEqual(r["avatar_sha256"], "0" * 64)
        self.assertEqual(len(r["times"]), 40)
        self.assertEqual(len(r["frames"]), 40)
        self.assertEqual(r["verdict"]["pass"], True)
        self.assertEqual(set(r["verdict"]) >= {"pass", "min_share", "worst", "frames_with_face", "recommended"}, True)
        json.dumps(r)   # serialisable


class Cli(unittest.TestCase):
    """CLI exit codes with the tools patched on the module."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.avatar = Path(self.tmp.name) / "avatar.mp4"
        self.avatar.write_bytes(b"x")
        self.saved = (fb._probe_duration, fb._extract_frame, fb._detect_faces)
        self.addCleanup(self.restore)

    def restore(self):
        fb._probe_duration, fb._extract_frame, fb._detect_faces = self.saved

    def patch(self, faces_fn, duration=100.0):
        fb._probe_duration = lambda p, d: duration
        fb._extract_frame = lambda p, t, out, d: Path(out).write_bytes(b"jpg")
        fb._detect_faces = lambda paths, d: {p: {"path": p, "ok": True, "faces": faces_fn(i)} for i, p in enumerate(paths)}

    def episode(self, box):
        p = Path(self.tmp.name) / "episode.json"
        p.write_text(json.dumps({"avatarFaceBox": box} if box is not None else {"title": "x"}))
        return str(p)

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = fb.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_check_pass_exit_0_and_writes_report(self):
        self.patch(lambda i: [FACE])
        rep = Path(self.tmp.name) / "r.json"
        rc, out, _ = self.run_cli(["check", "--avatar", str(self.avatar), "--episode", self.episode(GOOD_BOX), "--report", str(rep)])
        self.assertEqual(rc, 0, out)
        self.assertTrue(json.loads(rep.read_text())["verdict"]["pass"])

    def test_check_fail_exit_1_prints_worst_frame_and_recommended_box(self):
        self.patch(lambda i: [FACE])
        rc, out, _ = self.run_cli(["check", "--avatar", str(self.avatar), "--episode", self.episode({"x": 0.0, "y": 0.0, "w": 0.2, "h": 0.2})])
        self.assertEqual(rc, 1)
        self.assertIn("worst frame", out)
        self.assertIn('"avatarFaceBox": {"x": 0.38', out)

    def test_check_fail_message_names_the_rule_value_limit_and_prints_the_paste_line(self):
        # box 0.05 right of the face centre, 1.5x wide / 1.2x high: share stays 1.0, only the centre rule fails
        self.patch(lambda i: [BIG])
        box = box_around(BIG, dx=0.05, rw=1.5, rh=1.2)
        rc, out, _ = self.run_cli(["check", "--avatar", str(self.avatar), "--episode", self.episode(box)])
        self.assertEqual(rc, 1)
        first = out.splitlines()[0]
        self.assertTrue(first.startswith("face-box FAIL: centre:"), first)
        self.assertIn("+0.050", first)
        self.assertIn("0.045", first)
        self.assertIn('"avatarFaceBox": {"x": 0.38, "y": 0.18, "w": 0.24, "h": 0.34}', out)

    def test_check_fail_lists_every_failed_rule(self):
        self.patch(lambda i: [BIG])
        rc, out, _ = self.run_cli(["check", "--avatar", str(self.avatar), "--episode", self.episode({"x": 0, "y": 0, "w": 1, "h": 1})])
        self.assertEqual(rc, 1)
        self.assertIn("face-box FAIL: centre:", out)
        self.assertIn("also: size:", out)
        self.assertIn("allowed 0.9x to 1.5x", out)

    def test_check_pass_report_has_rules_and_offsets(self):
        self.patch(lambda i: [FACE])
        rep = Path(self.tmp.name) / "r2.json"
        rc, out, _ = self.run_cli(["check", "--avatar", str(self.avatar), "--episode", self.episode(GOOD_BOX), "--report", str(rep)])
        self.assertEqual(rc, 0, out)
        verdict = json.loads(rep.read_text())["verdict"]
        self.assertEqual(verdict["rules"], {"share": "pass", "frames": "pass", "centre": "pass", "size": "pass"})
        self.assertIn("centre_offset", verdict)
        self.assertIn("size_ratio", verdict)
        self.assertIn("face_union", verdict)

    def test_check_missing_box_exit_1(self):
        self.patch(lambda i: [FACE])
        rc, out, _ = self.run_cli(["check", "--avatar", str(self.avatar), "--episode", self.episode(None)])
        self.assertEqual(rc, 1)
        self.assertIn("no valid avatarFaceBox", out)

    def test_check_no_faces_exit_1(self):
        self.patch(lambda i: [])
        rc, out, _ = self.run_cli(["check", "--avatar", str(self.avatar), "--episode", self.episode(GOOD_BOX)])
        self.assertEqual(rc, 1)
        self.assertIn("cannot be verified", out)

    def test_unreadable_episode_exit_2(self):
        self.patch(lambda i: [FACE])
        bad = Path(self.tmp.name) / "bad.json"
        bad.write_text("{not json")
        self.assertEqual(self.run_cli(["check", "--avatar", str(self.avatar), "--episode", str(bad)])[0], 2)
        self.assertEqual(self.run_cli(["check", "--avatar", str(self.avatar), "--episode", str(Path(self.tmp.name) / "none.json")])[0], 2)

    def test_missing_avatar_and_bad_args_exit_2(self):
        self.patch(lambda i: [FACE])
        self.assertEqual(self.run_cli(["measure", "--avatar", str(Path(self.tmp.name) / "none.mp4")])[0], 2)
        self.assertEqual(self.run_cli(["measure"])[0], 2)

    def test_tool_failure_exit_4(self):
        def boom(paths, d):
            raise fb.ToolFailure("swift not found")
        self.patch(lambda i: [FACE])
        fb._detect_faces = boom
        rc, _, err = self.run_cli(["check", "--avatar", str(self.avatar), "--episode", self.episode(GOOD_BOX)])
        self.assertEqual(rc, 4)
        self.assertIn("TOOL FAILURE", err)

    def test_measure_prints_paste_ready_line_and_json_mode(self):
        self.patch(lambda i: [FACE])
        rc, out, _ = self.run_cli(["measure", "--avatar", str(self.avatar)])
        self.assertEqual(rc, 0)
        self.assertIn('"avatarFaceBox": {"x": 0.38, "y": 0.18, "w": 0.14, "h": 0.24}', out)
        rc, out, _ = self.run_cli(["measure", "--avatar", str(self.avatar), "--json"])
        self.assertEqual(json.loads(out)["recommended"], {"x": 0.38, "y": 0.18, "w": 0.14, "h": 0.24})


@unittest.skipUnless(CLIP_A.is_file() and CLIP_B.is_file(), "real presenter clips not available")
class RealClips(unittest.TestCase):
    """Reproduces the lead's published numbers (macOS Vision, 40 fixed frames) within +-0.01 and checks determinism."""

    @classmethod
    def setUpClass(cls):
        cls.a = fb.measure(CLIP_A)
        cls.b = fb.measure(CLIP_B)

    def share(self, m, box):
        return fb.check(m, box)["min_share"]

    def test_clip_a_numbers(self):
        self.assertEqual(self.a["frames_with_face"], 40)
        self.assertAlmostEqual(self.share(self.a, {"x": .41, "y": .11, "w": .16, "h": .34}), 0.967, delta=0.01)
        self.assertAlmostEqual(self.share(self.a, {"x": .39, "y": .05, "w": .19, "h": .37}), 0.849, delta=0.01)
        self.assertAlmostEqual(self.share(self.a, {"x": .37, "y": .12, "w": .20, "h": .35}), 1.000, delta=0.01)

    def test_clip_a_verdicts(self):
        self.assertTrue(fb.check(self.a, {"x": .41, "y": .11, "w": .16, "h": .34})["pass"])
        self.assertFalse(fb.check(self.a, {"x": .39, "y": .05, "w": .19, "h": .37})["pass"])
        self.assertTrue(fb.check(self.a, {"x": .37, "y": .12, "w": .20, "h": .35})["pass"])

    def test_known_good_boxes_pass_all_four_rules(self):
        wp6_final = json.loads((WP6_EPISODE).read_text())["avatarFaceBox"] if WP6_EPISODE.is_file() else {"x": .37, "y": .12, "w": .20, "h": .35}
        for name, m, box in (("fable-1 A", self.a, {"x": .41, "y": .11, "w": .16, "h": .34}),
                             ("fable-1 B", self.b, {"x": .41, "y": .11, "w": .16, "h": .33}),
                             ("WP6 final A", self.a, wp6_final),
                             ("recommended A", self.a, self.a["recommended"]),
                             ("recommended B", self.b, self.b["recommended"])):
            v = fb.check(m, box)
            self.assertTrue(v["pass"], (name, v["reasons"]))
            self.assertEqual(set(v["rules"].values()), {"pass"}, name)

    def test_known_bad_boxes_fail_on_the_expected_rule(self):
        first_guess = fb.check(self.a, {"x": .39, "y": .05, "w": .19, "h": .37})
        self.assertEqual(first_guess["rules"]["centre"], "fail")        # y centre 0.07 above the face centre
        self.assertEqual(first_guess["rules"]["share"], "fail")
        oversized = fb.check(self.a, {"x": .38, "y": .10, "w": .50, "h": .40})
        self.assertGreaterEqual(oversized["min_share"], 0.99)           # the old rule alone passed this
        self.assertEqual(oversized["rules"]["size"], "fail")
        self.assertEqual(oversized["rules"]["centre"], "fail")
        for m in (self.a, self.b):
            whole = fb.check(m, {"x": 0, "y": 0, "w": 1, "h": 1})
            self.assertFalse(whole["pass"])
            self.assertEqual(whole["rules"]["size"], "fail")
            self.assertEqual(whole["rules"]["centre"], "fail")

    def test_measured_offsets_and_ratios_of_a_known_good_box(self):
        v = fb.check(self.a, {"x": .41, "y": .11, "w": .16, "h": .34})
        self.assertAlmostEqual(v["centre_offset"]["x"], 0.0072, delta=0.002)
        self.assertAlmostEqual(v["centre_offset"]["y"], -0.0265, delta=0.002)
        self.assertAlmostEqual(v["size_ratio"]["w"], 1.044, delta=0.01)
        self.assertAlmostEqual(v["size_ratio"]["h"], 1.134, delta=0.01)

    def test_clip_b_numbers(self):
        self.assertEqual(self.b["frames_with_face"], 40)
        self.assertAlmostEqual(self.share(self.b, {"x": .41, "y": .11, "w": .16, "h": .33}), 0.947, delta=0.01)

    def test_recommended_boxes_pass_their_own_clip(self):
        self.assertTrue(fb.check(self.a, self.a["recommended"])["pass"])
        self.assertTrue(fb.check(self.b, self.b["recommended"])["pass"])

    def test_two_runs_are_identical(self):
        again = fb.measure(CLIP_B)
        self.assertEqual(json.dumps(again, sort_keys=True), json.dumps(self.b, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
