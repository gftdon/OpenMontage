import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import test_support as ts
from test_support import FakeMusic, Task, needs_ffmpeg

SCRIPT = ts.SCRIPTS / "gg_short_reel.py"
CORR = ("schema", "task_id", "step_id", "run_id", "dispatch_id", "target")


class Base(unittest.TestCase):
    def setUp(self):
        import gg_short_reel
        self.gg = gg_short_reel
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def task(self, **kw):
        return Task(self.root, **kw)

    def run_task(self, task, provider=None, timeout_s=300):
        return self.gg.run(task.request_path, music_provider=provider, timeout_s=timeout_s)

    def assertFailed(self, task, rc, contains=None, retry_safe=True):
        self.assertNotEqual(0, rc)
        res = task.result()
        self.assertEqual("failed", res["status"])
        self.assertEqual([], res["outputs"])
        self.assertIs(retry_safe, res["retry_safe"])
        self.assertTrue(res["error"].strip())
        self.assertEqual({*CORR, "status", "error", "retry_safe", "outputs"}, set(res))
        for k in CORR:
            self.assertEqual(task.request[k], res[k])
        self.assertFalse(task.final.exists(), "no final may remain after a failure")
        self.assertEqual([], [n for n in task.run_dir_names() if "partial" in n or n.startswith(".") or n.endswith(".tmp")])
        if contains:
            self.assertIn(contains, res["error"])
        return res


@needs_ffmpeg
class SuccessTests(Base):
    def test_b_success_output_shape_and_receipt(self):
        task = self.task()
        music = FakeMusic()
        rc = self.run_task(task, music)
        self.assertEqual(0, rc)
        info = ts.probe(task.final)
        v = [s for s in info["streams"] if s["codec_type"] == "video"]
        a = [s for s in info["streams"] if s["codec_type"] == "audio"]
        self.assertEqual((1, 1), (len(v), len(a)))
        self.assertEqual((1080, 1920), (v[0]["width"], v[0]["height"]))
        self.assertEqual("1:1", v[0]["sample_aspect_ratio"])
        self.assertEqual("30/1", v[0]["r_frame_rate"])
        self.assertEqual("30/1", v[0]["avg_frame_rate"])
        self.assertEqual("h264", v[0]["codec_name"])
        self.assertEqual("yuv420p", v[0]["pix_fmt"])
        self.assertEqual("aac", a[0]["codec_name"])
        self.assertEqual(359, len(ts.frame_levels(task.final)), "150 + (150-1) + 60 frames")
        # constant 30 fps: every video packet is 1/30 s apart
        r = subprocess.run([ts.FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time",
                            "-of", "csv=p=0", str(task.final)], capture_output=True, text=True, check=True)
        pts = sorted(float(x) for x in r.stdout.split())
        self.assertTrue(all(abs((b - a_) - 1 / 30) < 1e-3 for a_, b in zip(pts, pts[1:])))
        # music provider got the video duration (mood is no longer passed: AIOS built the music prompt)
        self.assertEqual(1, len(music.calls))
        self.assertAlmostEqual(359 / 30, music.calls[0][0], delta=0.05)
        self.assertIsNone(music.calls[0][1])
        # receipt h: correlation exact, outputs == request outputs, only expected files remain
        res = task.result()
        self.assertEqual({*CORR, "status", "outputs"}, set(res))
        self.assertEqual("succeeded", res["status"])
        self.assertEqual(task.request["outputs"], res["outputs"])
        for k in CORR:
            self.assertEqual(task.request[k], res[k])
        self.assertEqual(sorted(["request.json", "result.json", task.final.name]), task.run_dir_names())
        self.assertEqual([], [p for p in self.root.rglob("*") if ".gg-short-work" in p.name or p.suffix == ".tmp"])

    def test_d_loudness_of_final(self):
        for amp, secs in ((0.05, None), (0.9, 20)):  # very quiet, and loud + much longer than the video (trimmed)
            with self.subTest(amp=amp), tempfile.TemporaryDirectory() as d:
                task = Task(Path(d))
                self.assertEqual(0, self.run_task(task, FakeMusic(amp=amp, seconds=secs)))
                i, tp = ts.measure_loudness(task.final)
                self.assertAlmostEqual(-14.0, i, delta=1.0)
                self.assertLessEqual(tp, -1.0)

    def test_e_duration_gate_boundaries(self):
        import common
        # F5: at least as strict as AIOS 10 <= d <= 90 (ffprobe format.duration) — no epsilon that widens the window
        for ok in (10.0, 10.0005, 50.0, 90.0):
            self.gg.check_duration(ok)
        for bad in (9.9, 9.998, 9.9995, 9.9999999, 90.0000001, 90.0005, 90.01, 95.0, 0.0):
            with self.subTest(bad=bad), self.assertRaises(common.GgError):
                self.gg.check_duration(bad)

    def test_e_verify_final_applies_the_strict_gate_to_format_duration(self):
        import audio
        import common
        import compose

        def info(duration):
            return {"streams": [{"codec_type": "video", "codec_name": "h264", "width": compose.W, "height": compose.H,
                                 "pix_fmt": "yuv420p", "sample_aspect_ratio": "1:1",
                                 "r_frame_rate": f"{compose.FPS}/1", "avg_frame_rate": f"{compose.FPS}/1"},
                                {"codec_type": "audio", "codec_name": "aac"}],
                    "format": {"duration": duration}}

        for bad in ("9.999500", "90.000500"):
            with self.subTest(bad=bad), mock.patch.object(common, "probe", return_value=info(bad)), \
                    mock.patch.object(audio, "measure_loudness", side_effect=AssertionError("duration gate must fire first")):
                with self.assertRaises(common.GgError) as cm:
                    self.gg.verify_final("x.mp4", None)
                self.assertIn("ช่วง", str(cm.exception))
        for ok, expect in (("10.000000", 10.0), ("90.000000", 90.0)):
            with self.subTest(ok=ok), mock.patch.object(common, "probe", return_value=info(ok)), \
                    mock.patch.object(audio, "measure_loudness", return_value=(-14.0, -2.0)):
                self.assertEqual(expect, self.gg.verify_final("x.mp4", None)["duration_s"])

    def test_e_9_9_seconds_fails_10_seconds_succeeds(self):
        with tempfile.TemporaryDirectory() as d:
            short = Task(Path(d), shots=[{"w": 416, "h": 752, "frames": 150, "continues": False},
                                         {"w": 416, "h": 752, "frames": 147, "continues": False}])  # 297 frames
            music = FakeMusic()
            rc = self.run_task(short, music)
            res = self.assertFailed(short, rc, contains="9.9")
            self.assertEqual(0, len(music.calls), "no music is requested for a video that already fails the gate")
            self.assertTrue((short.run_dir / (short.final.name + ".FAILED.json")).exists())
        with tempfile.TemporaryDirectory() as d:
            ok = Task(Path(d), shots=[{"w": 416, "h": 752, "frames": 150, "continues": False},
                                      {"w": 416, "h": 752, "frames": 150, "continues": False}])  # 300 frames
            self.assertEqual(0, self.run_task(ok, FakeMusic()))
            self.assertGreaterEqual(float(ts.probe(ok.final)["format"]["duration"]), 10.0 - 1e-3)

    def test_e_over_90_seconds_fails(self):
        with tempfile.TemporaryDirectory() as d:
            big = Task(Path(d), shots=[{"w": 64, "h": 112, "frames": 1425, "continues": False},
                                       {"w": 64, "h": 112, "frames": 1425, "continues": False}])  # 95 s
            rc = self.run_task(big, FakeMusic())
            self.assertFailed(big, rc, contains="90")


@needs_ffmpeg
class MusicFailureTests(Base):
    def test_f_provider_failures(self):
        from audio import MusicUnavailable
        cases = {
            "unavailable": FakeMusic(mode="raise", exc=MusicUnavailable("ไม่มีเพลง")),
            "empty": FakeMusic(mode="empty"),
            "noaudio": FakeMusic(mode="noaudio"),
            "missing": FakeMusic(mode="missing"),
        }
        for name, prov in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as d:
                task = Task(Path(d))
                rc = self.run_task(task, prov)
                self.assertFailed(task, rc)
                self.assertEqual(1, len(prov.calls))

    def test_paid_provider_exception_is_not_retry_safe(self):
        class Paid(FakeMusic):
            is_paid = True
        task = self.task()
        rc = self.run_task(task, Paid(mode="raise", exc=RuntimeError("provider blew up after billing")))
        self.assertFailed(task, rc, retry_safe=False)

    def test_music_unavailable_from_paid_provider_stays_retry_safe(self):
        from audio import MusicUnavailable

        class Paid(FakeMusic):
            is_paid = True
        task = self.task()
        rc = self.run_task(task, Paid(mode="raise", exc=MusicUnavailable("declined before any work")))
        self.assertFailed(task, rc, retry_safe=True)

    def test_bad_loudness_after_mux_fails_and_removes_partial(self):
        import audio
        task = self.task()
        with mock.patch.object(audio, "measure_loudness", return_value=(-20.0, -0.2)):
            rc = self.run_task(task, FakeMusic())
        self.assertFailed(task, rc, contains="loudness")


@needs_ffmpeg
class InputValidationTests(Base):
    def _fail(self, task, contains=None):
        rc = self.run_task(task, FakeMusic())
        self.assertFailed(task, rc, contains=contains)
        self.assertTrue((task.run_dir / (task.final.name + ".FAILED.json")).exists())

    def test_g_wrong_manifest_run_id(self):
        task = self.task()
        task.manifest["run_id"] = "someone-else"
        task.write_all()
        self._fail(task, "run_id")

    def test_g_clips_input_run_id_mismatch(self):
        task = self.task()
        task.clips_input_run_id = "newer-run"
        task.write_request()
        self._fail(task, "run_id")

    def test_g_missing_seq(self):
        task = self.task()
        task.manifest["shots"] = [task.manifest["shots"][0], task.manifest["shots"][2]]
        task.write_all()
        self._fail(task, "seq")

    def test_g_continuation_must_follow_previous_seq(self):
        task = self.task()
        task.manifest["shots"][1]["continues_from_seq"] = 3
        task.write_all()
        self._fail(task, "continues_from_seq")

    def test_g_shot_outside_task_dir(self):
        task = self.task()
        outside = self.root / "outside.mp4"
        ts.make_clip(outside, w=416, h=752, frames=30)
        task.manifest["shots"][1]["file"] = "../outside.mp4"
        task.extra_clip_files = [str(outside)]  # even listed in the input files it must be refused
        task.write_all()
        self._fail(task, "task")

    def test_g_shot_not_in_input_files(self):
        task = self.task()
        task.clip_files = [task.clip_files[0], task.clip_files[2]]
        task.write_request()
        self._fail(task, "input")

    def test_g_missing_script_input(self):
        task = self.task()
        req = task.write_request()
        req["inputs"] = [i for i in req["inputs"] if i["role"] != "script"]
        task.request_path.write_text(json.dumps(req))
        self._fail(task, "script")

    def test_g_script_not_in_files(self):
        task = self.task()
        req = task.write_request()
        req["inputs"][0]["files"] = [str(task.orig_path)]
        task.request_path.write_text(json.dumps(req))
        self._fail(task, "script")

    def test_g_manifest_not_in_files(self):
        task = self.task()
        req = task.write_request()
        req["inputs"][1]["files"] = [str(f) for f in task.clip_files]
        task.request_path.write_text(json.dumps(req))
        self._fail(task, "manifest")

    def test_g_originality_hash_mismatch(self):
        task = self.task()
        task.write_originality(sha="0" * 64)
        self._fail(task, "ด่านกันลอก")

    def test_g_originality_not_passed(self):
        task = self.task()
        task.write_originality(passed=False)
        self._fail(task, "ด่านกันลอก")

    def test_g_originality_missing_from_inputs(self):
        task = self.task()
        req = task.write_request()
        req["inputs"][0]["files"] = [str(task.script_path)]
        task.request_path.write_text(json.dumps(req))
        self._fail(task, "ด่านกันลอก")

    def test_g_script_not_json(self):
        task = self.task()
        task.script_path.write_text("this is plain text, not JSON")
        task.write_originality()
        self._fail(task, "JSON")

    def test_g_bad_on_screen_text_item(self):
        task = self.task()
        task.script["on_screen_text"][0]["placement"] = "left"
        task.write_all()
        self._fail(task, "placement")

    def test_g_non_english_on_screen_text_fails_at_script_stage(self):
        task = self.task()
        task.script["on_screen_text"][1]["text"] = "ยายกับตาหัวเราะ"
        task.write_all()
        music = FakeMusic()
        with mock.patch.object(self.gg.compose, "estimate_duration", side_effect=AssertionError("probe must not run")), \
                mock.patch.object(self.gg.compose, "build_base", side_effect=AssertionError("compose must not run")), \
                mock.patch.object(self.gg.audio, "validate_music", side_effect=AssertionError("music must not be decoded")):
            rc = self.run_task(task, music)
        res = self.assertFailed(task, rc, contains="ต้องเป็นภาษาอังกฤษเท่านั้น", retry_safe=True)
        self.assertIn("[script]", res["error"])
        self.assertIn("on_screen_text[1]", res["error"])
        self.assertEqual([], music.calls, "music must never be asked for")
        diag = json.loads((task.run_dir / (task.final.name + ".FAILED.json")).read_text())
        self.assertEqual("script", diag["stage"])
        self.assertEqual(sorted(["request.json", "result.json", task.final.name + ".FAILED.json"]), task.run_dir_names())

    def test_g_request_contract_violations(self):
        for key, bad in (("kind", "edit_long"), ("aspect", "16:9"), ("schema", 2),
                         ("outputs", ["/x/not_final.mp4"]), ("outputs", [])):
            with self.subTest(key=key, bad=bad), tempfile.TemporaryDirectory() as d:
                task = Task(Path(d))
                req = task.write_request()
                req[key] = bad
                task.request_path.write_text(json.dumps(req))
                rc = self.run_task(task, FakeMusic())
                self.assertNotEqual(0, rc)
                self.assertEqual("failed", task.result()["status"])
                self.assertFalse(task.final.exists())

    def test_g_two_outputs_refused(self):
        task = self.task()
        req = task.write_request()
        req["outputs"] = [str(task.final), str(task.run_dir / "x_40_Short_Final.mp4")]
        task.request_path.write_text(json.dumps(req))
        rc = self.run_task(task, FakeMusic())
        self.assertNotEqual(0, rc)
        self.assertEqual("failed", task.result()["status"])


@needs_ffmpeg
class RobustnessTests(Base):
    def test_i_forced_exception_midway_writes_failed_receipt(self):
        import compose
        import overlay
        for mod, name in ((compose, "build_base"), (overlay, "burn")):
            with self.subTest(step=name), tempfile.TemporaryDirectory() as d:
                task = Task(Path(d))
                with mock.patch.object(mod, name, side_effect=RuntimeError("boom")):
                    rc = self.run_task(task, FakeMusic())
                res = self.assertFailed(task, rc, contains="boom")
                self.assertEqual(sorted(["request.json", "result.json", task.final.name + ".FAILED.json"]),
                                 task.run_dir_names())
                diag = json.loads((task.run_dir / (task.final.name + ".FAILED.json")).read_text())
                self.assertIn("boom", diag["error"])
                self.assertIn("stage", diag)

    def test_i_keyboard_interrupt_still_writes_receipt(self):
        import compose
        task = self.task()
        with mock.patch.object(compose, "build_base", side_effect=KeyboardInterrupt()):
            rc = self.run_task(task, FakeMusic())
        self.assertFailed(task, rc)

    def test_i_receipt_write_failure_after_final_removes_final(self):
        import receipt
        task = self.task()
        real = receipt.publish_receipt
        calls = []

        def flaky(path, data, correlation, **kw):
            calls.append(data.get("status"))
            if len(calls) == 1:
                raise OSError("disk full")
            return real(path, data, correlation, **kw)

        with mock.patch.object(receipt, "publish_receipt", side_effect=flaky):
            rc = self.run_task(task, FakeMusic())
        self.assertEqual(["succeeded", "failed"], calls)
        self.assertFailed(task, rc, contains="disk full")

    def test_j_timeout_in_slow_stage(self):
        import compose
        task = self.task()
        started = time.monotonic()
        with mock.patch.object(compose, "build_base", side_effect=lambda *a, **k: time.sleep(30)):
            rc = self.run_task(task, FakeMusic(), timeout_s=1)
        self.assertLess(time.monotonic() - started, 15)
        self.assertFailed(task, rc, contains="timeout")

    def test_j_timeout_kills_real_ffmpeg(self):
        task = self.task()
        started = time.monotonic()
        rc = self.run_task(task, FakeMusic(), timeout_s=0.05)
        self.assertLess(time.monotonic() - started, 15)
        self.assertFailed(task, rc, contains="timeout")

    def test_k_existing_final_is_never_overwritten(self):
        task = self.task()
        task.final.write_bytes(b"precious earlier result")
        music = FakeMusic()
        rc = self.run_task(task, music)
        self.assertNotEqual(0, rc)
        res = task.result()
        self.assertEqual("failed", res["status"])
        self.assertEqual([], res["outputs"])
        self.assertEqual(b"precious earlier result", task.final.read_bytes())
        self.assertEqual(0, len(music.calls))
        self.assertEqual([], [n for n in task.run_dir_names() if "partial" in n])

    def test_stale_partial_is_replaced_not_trusted(self):
        task = self.task()
        (task.run_dir / (task.final.name + ".partial.mp4")).write_bytes(b"junk from a killed run")
        self.assertEqual(0, self.run_task(task, FakeMusic()))
        self.assertEqual(sorted(["request.json", "result.json", task.final.name]), task.run_dir_names())


@needs_ffmpeg
class TerminalReceiptNotOverwrittenTests(Base):
    """F6b: a terminal receipt (succeeded/failed) with the same correlation is never overwritten; nothing else is touched."""

    def _snapshot(self, task):
        return {p.name: p.read_bytes() for p in task.run_dir.iterdir() if p.is_file()}

    def _run_refused(self, task, provider=None):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = self.run_task(task, provider if provider is not None else FakeMusic())
        self.assertEqual(self.gg.EXIT_RECEIPT_EXISTS, rc)
        self.assertNotEqual(0, rc)
        self.assertIn("receipt", err.getvalue())
        self.assertIn("ไม่เขียนทับ", err.getvalue())
        return err.getvalue()

    def test_second_run_after_success_leaves_receipt_and_final_intact(self):
        task = self.task()
        self.assertEqual(0, self.run_task(task, FakeMusic()))
        before = self._snapshot(task)
        music = FakeMusic()
        self._run_refused(task, music)
        self.assertEqual(before, self._snapshot(task), "receipt, final and every other file byte-identical")
        self.assertEqual("succeeded", task.result()["status"])
        self.assertEqual([], music.calls)

    def test_second_run_after_failure_leaves_failed_receipt_intact(self):
        task = self.task()
        rc = self.run_task(task, FakeMusic(mode="empty"))
        self.assertFailed(task, rc)
        before = self._snapshot(task)
        self._run_refused(task)
        self.assertEqual(before, self._snapshot(task))
        self.assertEqual("failed", task.result()["status"])

    def test_receipt_written_by_someone_else_mid_run_is_not_overwritten_on_failure(self):
        import receipt
        task = self.task()
        planted = receipt.failure_receipt(receipt.correlation_of(task.request), "planted", True)

        class Plant(FakeMusic):
            def get_music(inner, duration_s, mood, out_path):
                receipt.write_receipt(task.result_path, planted)
                raise RuntimeError("provider blew up")

        self._run_refused(task, Plant())
        self.assertEqual(planted, task.result())
        self.assertFalse(task.final.exists())
        self.assertEqual([], [n for n in task.run_dir_names() if n.endswith(".FAILED.json")], "no diagnostic beside it either")

    def test_receipt_written_by_someone_else_mid_run_is_not_overwritten_on_success(self):
        import receipt
        task = self.task()
        planted = receipt.success_receipt(receipt.correlation_of(task.request), task.request["outputs"])

        class Plant(FakeMusic):
            def get_music(inner, duration_s, mood, out_path):
                receipt.write_receipt(task.result_path, planted)
                return FakeMusic.get_music(inner, duration_s, mood, out_path)

        self._run_refused(task, Plant())
        self.assertEqual(planted, task.result())

    # ---- R3-1: a success receipt that appears mid-run points at the final path: that file must survive untouched

    def _fingerprint(self, path):
        data = Path(path).read_bytes()
        shape = [(s["codec_type"], s.get("codec_name"), s.get("width"), s.get("height")) for s in ts.probe(path)["streams"]]
        return hashlib.sha256(data).hexdigest(), len(data), shape

    def test_r3_1_success_receipt_mid_run_keeps_the_final_it_points_to(self):
        import receipt
        task = self.task()
        planted = receipt.success_receipt(receipt.correlation_of(task.request), task.request["outputs"])
        seen = {}

        class Plant(FakeMusic):
            def get_music(inner, duration_s, mood, out_path):
                receipt.write_receipt(task.result_path, planted)
                return FakeMusic.get_music(inner, duration_s, mood, out_path)

        # the planted receipt is only noticed AFTER our link published the final: observe the final the instant before
        # the receipt decision, then compare after the refusal
        real = receipt.publish_receipt

        def spy(*a, **k):
            seen["before"] = self._fingerprint(task.final)
            return real(*a, **k)

        with mock.patch.object(receipt, "publish_receipt", side_effect=spy):
            self._run_refused(task, Plant())
        self.assertEqual(planted, task.result())
        self.assertTrue(task.final.is_file(), "the final the success receipt points at must still exist")
        self.assertEqual(seen["before"], self._fingerprint(task.final), "sha256 + size + stream shape unchanged")
        self.assertEqual(sorted(["request.json", "result.json", task.final.name]), task.run_dir_names())

    def test_r3_1_failed_receipt_mid_run_still_removes_our_own_final(self):
        import receipt
        task = self.task()
        planted = receipt.failure_receipt(receipt.correlation_of(task.request), "planted", True)

        class Plant(FakeMusic):
            def get_music(inner, duration_s, mood, out_path):
                receipt.write_receipt(task.result_path, planted)
                return FakeMusic.get_music(inner, duration_s, mood, out_path)

        self._run_refused(task, Plant())
        self.assertEqual(planted, task.result())
        self.assertFalse(task.final.exists(), "a failed receipt has no outputs: our own final does not stay")
        self.assertEqual(["request.json", "result.json"], task.run_dir_names())

    # ---- R3-2: no-clobber atomic publication: the competitor lands between our check and our link

    def _race(self, task, competing, provider=None):
        """Drop `competing` into result.json at the point immediately before our link; returns (rc, stderr, fingerprint then)."""
        import receipt
        seen = {}

        def plant(tmp, result_path):
            seen["final"] = self._fingerprint(task.final) if task.final.exists() else None
            Path(result_path).write_text(json.dumps(competing))

        err = io.StringIO()
        with mock.patch.object(receipt, "_before_link", side_effect=plant), contextlib.redirect_stderr(err):
            rc = self.run_task(task, provider if provider is not None else FakeMusic())
        return rc, err.getvalue(), seen

    def test_r3_2_success_race_terminal_same_correlation_is_not_overwritten(self):
        import receipt
        task = self.task()
        corr = receipt.correlation_of(task.request)
        competing = {**receipt.success_receipt(corr, task.request["outputs"]), "marker": "theirs"}
        rc, err, seen = self._race(task, competing)
        self.assertEqual(self.gg.EXIT_RECEIPT_EXISTS, rc)
        self.assertEqual(competing, task.result(), "their terminal receipt must not be overwritten")
        self.assertTrue(task.final.is_file(), "R3-1: the final their success receipt points at stays")
        self.assertEqual(seen["final"], self._fingerprint(task.final))
        self.assertEqual(sorted(["request.json", "result.json", task.final.name]), task.run_dir_names(), "no tmp file left")
        self.assertIn("ไม่เขียนทับ", err)

    def test_r3_2_success_race_failed_same_correlation_is_not_overwritten_and_our_final_goes(self):
        import receipt
        task = self.task()
        competing = {**receipt.failure_receipt(receipt.correlation_of(task.request), "theirs", True), "marker": "theirs"}
        rc, _, _ = self._race(task, competing)
        self.assertEqual(self.gg.EXIT_RECEIPT_EXISTS, rc)
        self.assertEqual(competing, task.result())
        self.assertFalse(task.final.exists())
        self.assertEqual(["request.json", "result.json"], task.run_dir_names())

    def test_r3_2_success_race_different_correlation_is_replaced(self):
        import receipt
        task = self.task()
        competing = receipt.success_receipt({**receipt.correlation_of(task.request), "dispatch_id": "older"}, ["/old/x.mp4"])
        rc, _, _ = self._race(task, competing)
        self.assertEqual(0, rc)
        self.assertEqual("succeeded", task.result()["status"])
        self.assertEqual("dispatch-1", task.result()["dispatch_id"])
        self.assertEqual(sorted(["request.json", "result.json", task.final.name]), task.run_dir_names())

    def test_r3_2_success_race_non_terminal_or_garbage_is_replaced(self):
        for content in ({"status": "running"}, [], "garbage"):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as d:
                task = Task(Path(d))
                rc, _, _ = self._race(task, content)
                self.assertEqual(0, rc)
                self.assertEqual("succeeded", task.result()["status"])
                self.assertEqual(sorted(["request.json", "result.json", task.final.name]), task.run_dir_names())

    def test_r3_2_failure_race_terminal_same_correlation_is_not_overwritten_and_leaves_no_diagnostic(self):
        import receipt
        task = self.task()
        corr = receipt.correlation_of(task.request)
        competing = {**receipt.success_receipt(corr, task.request["outputs"]), "marker": "theirs"}
        rc, _, _ = self._race(task, competing, FakeMusic(mode="empty"))
        self.assertEqual(self.gg.EXIT_RECEIPT_EXISTS, rc)
        self.assertEqual(competing, task.result())
        self.assertEqual(["request.json", "result.json"], task.run_dir_names(), "no tmp, no .FAILED.json, no partial")

    def test_r3_2_failure_race_different_correlation_is_replaced_by_our_failure(self):
        import receipt
        task = self.task()
        competing = receipt.failure_receipt({**receipt.correlation_of(task.request), "run_id": "older"}, "old", True)
        rc, _, _ = self._race(task, competing, FakeMusic(mode="empty"))
        self.assertNotEqual(self.gg.EXIT_RECEIPT_EXISTS, rc)
        self.assertEqual("failed", task.result()["status"])
        self.assertEqual("run-edit-1", task.result()["run_id"])
        self.assertEqual([n for n in task.run_dir_names() if n.startswith(".") or n.endswith(".tmp")], [])

    def test_receipt_with_different_correlation_is_replaced_as_before(self):
        import receipt
        task = self.task()
        stale = receipt.success_receipt({**receipt.correlation_of(task.request), "dispatch_id": "older-dispatch"}, ["/old/x.mp4"])
        receipt.write_receipt(task.result_path, stale)
        self.assertEqual(0, self.run_task(task, FakeMusic()))
        self.assertEqual("dispatch-1", task.result()["dispatch_id"])
        self.assertEqual(task.request["outputs"], task.result()["outputs"])

    def test_non_terminal_or_garbage_result_json_is_replaced_as_before(self):
        for content in ('{"status": "running"}', "not json at all", "[]", ""):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as d:
                task = Task(Path(d))
                task.result_path.write_text(content)
                self.assertEqual(0, self.run_task(task, FakeMusic()))
                self.assertEqual("succeeded", task.result()["status"])


class ReceiptUnitTests(unittest.TestCase):
    def test_decide_retry_safe(self):
        import receipt
        self.assertTrue(receipt.decide_retry_safe(False))
        self.assertFalse(receipt.decide_retry_safe(True))

    def test_write_receipt_is_atomic_and_leaves_no_temp(self):
        import receipt
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "result.json"
            p.write_text('{"old": true}')
            with mock.patch.object(os, "replace", side_effect=OSError("nope")):
                with self.assertRaises(OSError):
                    receipt.write_receipt(p, {"a": 1})
            self.assertEqual('{"old": true}', p.read_text())
            self.assertEqual(["result.json"], sorted(x.name for x in Path(d).iterdir()))
            receipt.write_receipt(p, {"a": 1})
            self.assertEqual({"a": 1}, json.loads(p.read_text()))
            self.assertEqual(["result.json"], sorted(x.name for x in Path(d).iterdir()))

    CORR_FIXTURE = {"schema": 1, "task_id": "t", "step_id": "s", "run_id": "r", "dispatch_id": "d",
                    "target": {"project_id": "p", "config_ref": "c"}}

    def _names(self, d):
        return sorted(x.name for x in Path(d).iterdir())

    def test_publish_receipt_is_no_clobber_atomic_and_leaves_no_temp(self):
        import receipt
        corr = self.CORR_FIXTURE
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "result.json"
            self.assertIsNone(receipt.publish_receipt(p, receipt.success_receipt(corr, ["/x"]), corr), "absent: written")
            self.assertEqual("succeeded", json.loads(p.read_text())["status"])
            self.assertEqual(["result.json"], self._names(d))
            # same-correlation terminal already there (either status): untouched, status reported
            before = p.read_bytes()
            self.assertEqual("succeeded", receipt.publish_receipt(p, receipt.failure_receipt(corr, "e", True), corr))
            self.assertEqual(before, p.read_bytes())
            p.write_text(json.dumps(receipt.failure_receipt(corr, "theirs", True)))
            before = p.read_bytes()
            self.assertEqual("failed", receipt.publish_receipt(p, receipt.success_receipt(corr, ["/x"]), corr))
            self.assertEqual(before, p.read_bytes())
            self.assertEqual(["result.json"], self._names(d))

    def test_publish_receipt_replaces_foreign_or_unreadable_existing_file(self):
        import receipt
        corr = self.CORR_FIXTURE
        other = receipt.failure_receipt({**corr, "dispatch_id": "d2"}, "e", True)
        for content in (json.dumps(other), '{"status": "running"}', "garbage", "", "[]"):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as d:
                p = Path(d) / "result.json"
                p.write_text(content)
                self.assertIsNone(receipt.publish_receipt(p, receipt.success_receipt(corr, ["/x"]), corr))
                self.assertEqual("succeeded", json.loads(p.read_text())["status"])
                self.assertEqual(["result.json"], self._names(d))

    def test_publish_receipt_competitor_at_the_link_point_is_not_overwritten(self):
        import receipt
        corr = self.CORR_FIXTURE
        theirs = {**receipt.success_receipt(corr, ["/x"]), "marker": "theirs"}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "result.json"

            def plant(tmp, path):
                Path(path).write_text(json.dumps(theirs))

            with mock.patch.object(receipt, "_before_link", side_effect=plant):
                self.assertEqual("succeeded", receipt.publish_receipt(p, receipt.success_receipt(corr, ["/y"]), corr))
            self.assertEqual(theirs, json.loads(p.read_text()))
            self.assertEqual(["result.json"], self._names(d))

    def test_publish_receipt_removes_temp_when_the_replace_fails(self):
        import receipt
        corr = self.CORR_FIXTURE
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "result.json"
            p.write_text("garbage")
            with mock.patch.object(os, "replace", side_effect=OSError("nope")):
                with self.assertRaises(OSError):
                    receipt.publish_receipt(p, receipt.success_receipt(corr, ["/x"]), corr)
            self.assertEqual("garbage", p.read_text())
            self.assertEqual(["result.json"], self._names(d))

    def test_publish_receipt_lock_covers_classify_to_replace_gap(self):
        """R4-3: writer A classified a non-terminal file and is about to os.replace; writer B (a thread) tries to publish a
        terminal receipt for the same correlation in that window. B must wait for A (lock), then see A's terminal receipt
        and leave it alone. Without the lock B's replace lands first and A silently clobbers it."""
        import receipt
        corr = self.CORR_FIXTURE
        a_receipt = receipt.failure_receipt(corr, "A", True)
        b_receipt = receipt.success_receipt(corr, ["/b"])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "result.json"
            p.write_text('{"status": "running"}')               # exists, but not terminal: A will replace it
            b_started, b_done, b_result, seen = threading.Event(), threading.Event(), [], {}
            real_replace = receipt._before_replace

            def writer_b():
                b_started.set()
                try:
                    b_result.append(receipt.publish_receipt(p, b_receipt, corr))
                except BaseException as e:   # noqa: BLE001
                    b_result.append(e)
                finally:
                    b_done.set()

            thread = threading.Thread(target=writer_b, daemon=True)

            def a_window(tmp, path):
                real_replace(tmp, path)
                if seen:                                         # only the first (A's) pass starts B
                    return
                seen["in_window"] = True
                thread.start()
                self.assertTrue(b_started.wait(10), "B never started")
                # B had its chance to run to completion while A sits between classify and replace
                seen["b_finished_inside_window"] = b_done.wait(0.5)

            with mock.patch.object(receipt, "_before_replace", side_effect=a_window):
                self.assertIsNone(receipt.publish_receipt(p, a_receipt, corr), "A wins: its receipt is now there")
            self.assertTrue(b_done.wait(10), "B must be released once A is done (no deadlock)")
            thread.join(10)
            self.assertTrue(seen["in_window"])
            self.assertFalse(seen["b_finished_inside_window"], "B must block while A holds the lock")
            self.assertEqual([a_receipt["status"]], [b_result[0]], "B sees A's terminal receipt and returns its status")
            self.assertEqual(a_receipt, json.loads(p.read_text()), "A's terminal receipt is the final file; nothing clobbered")
            self.assertEqual(["result.json"], self._names(d), "tmp and lock file are gone")

    def test_publish_receipt_many_writers_exactly_one_wins_and_lock_file_is_removed(self):
        """The lock file is removed on exit; waiters that locked the unlinked inode must re-lock (no two holders)."""
        import receipt
        corr = self.CORR_FIXTURE
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "result.json"
            gate, results = threading.Barrier(12), []

            def writer(i):
                gate.wait(10)
                results.append(receipt.publish_receipt(p, receipt.success_receipt(corr, [f"/w{i}"]), corr))

            threads = [threading.Thread(target=writer, args=(i,), daemon=True) for i in range(12)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
            self.assertEqual(12, len(results))
            self.assertEqual(1, results.count(None), "exactly one writer published")
            self.assertEqual(11, results.count("succeeded"))
            winner = json.loads(p.read_text())["outputs"][0]
            self.assertTrue(winner.startswith("/w"))
            self.assertEqual(["result.json"], self._names(d))

    def test_publish_receipt_lock_is_released_after_an_error(self):
        import receipt
        corr = self.CORR_FIXTURE
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "result.json"
            p.write_text("garbage")
            with mock.patch.object(os, "replace", side_effect=OSError("nope")):
                with self.assertRaises(OSError):
                    receipt.publish_receipt(p, receipt.success_receipt(corr, ["/x"]), corr)
            done = []
            t = threading.Thread(target=lambda: done.append(receipt.publish_receipt(p, receipt.success_receipt(corr, ["/x"]), corr)),
                                 daemon=True)
            t.start()
            t.join(10)
            self.assertEqual([None], done, "a second publish is not blocked by a leaked lock")
            self.assertEqual("succeeded", json.loads(p.read_text())["status"])
            self.assertEqual(["result.json"], self._names(d))

    def test_existing_terminal_status_needs_terminal_status_and_full_correlation(self):
        import receipt
        corr = {"schema": 1, "task_id": "t", "step_id": "s", "run_id": "r", "dispatch_id": "d",
                "target": {"project_id": "p", "config_ref": "c"}}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "result.json"
            self.assertIsNone(receipt.existing_terminal_status(p, corr), "absent file")
            receipt.write_receipt(p, receipt.success_receipt(corr, ["/x"]))
            self.assertEqual("succeeded", receipt.existing_terminal_status(p, corr))
            receipt.write_receipt(p, receipt.failure_receipt(corr, "e", True))
            self.assertEqual("failed", receipt.existing_terminal_status(p, corr))
            for key, other in (("dispatch_id", "d2"), ("run_id", "r2"), ("task_id", "t2"), ("step_id", "s2"), ("schema", 2),
                               ("target", {"project_id": "p", "config_ref": "other"})):
                receipt.write_receipt(p, receipt.failure_receipt({**corr, key: other}, "e", True))
                self.assertIsNone(receipt.existing_terminal_status(p, corr), key)
            partial = {k: v for k, v in receipt.failure_receipt(corr, "e", True).items() if k != "run_id"}
            p.write_text(json.dumps(partial))
            self.assertIsNone(receipt.existing_terminal_status(p, corr), "missing correlation key")
            for content in ('{"status": "running", "task_id": "t"}', "garbage", "[]", ""):
                p.write_text(content)
                self.assertIsNone(receipt.existing_terminal_status(p, corr), content)

    def test_correlation_is_copied_exactly(self):
        import receipt
        req = {"schema": 1, "task_id": "t", "step_id": "s", "run_id": "r", "dispatch_id": "d",
               "target": {"project_id": "p", "config_ref": "c"}, "prompt": "ignored"}
        corr = receipt.correlation_of(req)
        self.assertEqual({k: req[k] for k in CORR}, corr)
        req["target"]["project_id"] = "mutated"
        self.assertEqual("p", corr["target"]["project_id"], "deep copy")


class CliTests(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run([sys.executable, "-B", str(SCRIPT), *args], capture_output=True, text=True, timeout=120)

    def test_unparseable_request_writes_nothing_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "request.json"
            p.write_text("{not json")
            r = self.cli("--request", str(p))
            self.assertNotEqual(0, r.returncode)
            self.assertTrue(r.stderr.strip())
            self.assertEqual(["request.json"], sorted(x.name for x in Path(d).iterdir()))

    def test_request_with_foreign_result_path_is_not_written(self):
        with tempfile.TemporaryDirectory() as d:
            run = Path(d) / "steps/edit_short/runs/1"
            run.mkdir(parents=True)
            victim = Path(d) / "elsewhere.json"
            req = {"schema": 1, "task_id": "t", "step_id": "s", "run_id": "r", "dispatch_id": "d",
                   "target": {"project_id": "p", "config_ref": "c"}, "kind": "edit_short", "aspect": "9:16",
                   "inputs": [], "outputs": [str(run / "X_40_Short_Final.mp4")], "result_path": str(victim)}
            (run / "request.json").write_text(json.dumps(req))
            r = self.cli("--request", str(run / "request.json"))
            self.assertNotEqual(0, r.returncode)
            self.assertFalse(victim.exists())

    def test_relative_request_path_is_refused(self):
        r = self.cli("--request", "request.json")
        self.assertNotEqual(0, r.returncode)

    def test_no_flag_can_inject_music(self):
        r = self.cli("--help")
        self.assertEqual(0, r.returncode)
        self.assertNotIn("music", r.stdout.lower())
        r2 = self.cli("--request", "/x/request.json", "--music", "/x/a.wav")
        self.assertNotEqual(0, r2.returncode)
        self.assertIn("unrecognized", r2.stderr)


if __name__ == "__main__":
    unittest.main()
