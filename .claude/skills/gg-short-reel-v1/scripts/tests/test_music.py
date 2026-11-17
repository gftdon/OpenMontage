"""Music comes from the AIOS `music` step input (FileMusicProvider): no network, no paid call, no loop."""
import copy
import json
import re
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_support as ts
from test_support import Task, needs_ffmpeg
from test_pipeline import Base

VIDEO_S = 359 / 30   # DEFAULT_SHOTS: 150 + 149 + 60 frames


def mean_volume_db(path, start, length):
    """Mean volume (dB) of a slice of the first audio stream, measured independently with volumedetect."""
    r = subprocess.run([ts.FFMPEG, "-hide_banner", "-nostats", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(path),
                        "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True, check=True)
    m = re.search(r"mean_volume:\s*(-?[\d.]+|-inf) dB", r.stderr)
    return float("-inf") if m.group(1) == "-inf" else float(m.group(1))


class FileMusicProviderUnitTests(unittest.TestCase):
    def test_is_not_paid_and_has_no_not_configured_default(self):
        import audio
        self.assertFalse(audio.FileMusicProvider({"result_path": "/x/steps/a/runs/1/result.json", "inputs": []}).is_paid)
        self.assertFalse(hasattr(audio, "NotConfiguredMusicProvider"))


@needs_ffmpeg
class MusicInputResolutionTests(Base):
    def provider(self, task):
        import audio
        return audio.FileMusicProvider(task.request)

    def test_music_resolved_by_name_not_order(self):
        import audio
        task = self.task()
        # the AIOS-listed order is arbitrary: put the mp3 first and noise files after it, music input first of all
        task.music_input["files"] = [str(task.music_path)] + [f for f in task.music_input["files"] if f != str(task.music_path)]
        req = task.write_request()
        req["inputs"].insert(0, req["inputs"].pop())     # music input first
        task.request = req
        task.request_path.write_text(json.dumps(req))
        got = audio.FileMusicProvider(req).get_music(VIDEO_S, None, self.root / "unused.wav")
        self.assertEqual(task.music_path.resolve(), Path(got).resolve())
        self.assertEqual(0, self.run_task(task, None))
        self.assertEqual("succeeded", task.result()["status"])

    def _expect_unavailable(self, task, contains, duration=VIDEO_S):
        import audio
        with self.assertRaises(audio.MusicUnavailable) as cm:
            self.provider(task).get_music(duration, None, self.root / "unused.wav")
        self.assertIn(contains, str(cm.exception))

    def test_provider_errors_are_specific(self):
        task = self.task(music=False)
        task.write_request()
        self._expect_unavailable(task, "input role music")                                  # no music input
        # no *_30_Music.mp3 among the files
        with tempfile.TemporaryDirectory() as d:
            t = Task(Path(d))
            t.music_input["files"] = [f for f in t.music_input["files"] if not f.endswith("_30_Music.mp3")]
            t.write_request()
            self._expect_unavailable(t, "_30_Music.mp3")
        with tempfile.TemporaryDirectory() as d:                                            # listed but gone
            t = Task(Path(d))
            t.music_path.unlink()
            self._expect_unavailable(t, "ไม่พบไฟล์เพลง")
        with tempfile.TemporaryDirectory() as d:                                            # empty
            t = Task(Path(d))
            t.music_path.write_bytes(b"")
            self._expect_unavailable(t, "ว่าง")
        with tempfile.TemporaryDirectory() as d:                                            # no audio stream
            t = Task(Path(d))
            ts.make_music(t.music_path, seconds=14, video_only=True)
            self._expect_unavailable(t, "audio stream")
        with tempfile.TemporaryDirectory() as d:                                            # shorter than the video
            t = Task(Path(d), music_seconds=8)
            self._expect_unavailable(t, "เพลงสั้นกว่าวิดีโอ")

    def test_outside_task_dir_and_symlink_escape(self):
        outside = self.root / "elsewhere"
        outside.mkdir()
        evil = outside / "X_30_Music.mp3"
        ts.make_music(evil, seconds=14)
        task = self.task()
        task.music_input["files"] = [str(evil)]
        task.write_request()
        self._expect_unavailable(task, "นอกโฟลเดอร์งาน")
        # a listed path inside the task dir that is a symlink pointing outside is also refused
        with tempfile.TemporaryDirectory() as d:
            t = Task(Path(d))
            link = t.music_dir / "Y_30_Music.mp3"
            link.symlink_to(evil)
            t.music_input["files"] = [str(link)]
            t.write_request()
            self._expect_unavailable(t, "นอกโฟลเดอร์งาน")

    def test_two_music_files_is_ambiguous(self):
        task = self.task()
        second = task.music_dir / "Z_30_Music.mp3"
        ts.make_music(second, seconds=14)
        task.music_input["files"].append(str(second))
        task.write_request()
        self._expect_unavailable(task, "_30_Music.mp3")

    def test_two_music_inputs_is_ambiguous(self):
        task = self.task()
        req = task.write_request()
        req["inputs"].append(copy.deepcopy(task.music_input))
        task.request = req
        self._expect_unavailable(task, "input role music")


@needs_ffmpeg
class MusicPipelineFailureTests(Base):
    """Every FileMusicProvider failure -> failed receipt, retry_safe true (the skill never pays), no final."""

    def _check(self, task, contains):
        rc = self.run_task(task, None)           # None = the real default provider (what the CLI uses)
        res = self.assertFailed(task, rc, contains=contains, retry_safe=True)
        self.assertTrue(res["error"].startswith("[music]"))
        return res

    def test_no_music_input(self):
        task = self.task(music=False)
        self._check(task, "input role music")

    def test_no_music_file_in_input(self):
        task = self.task()
        task.music_input["files"] = [f for f in task.music_input["files"] if not f.endswith("_30_Music.mp3")]
        task.write_request()
        self._check(task, "_30_Music.mp3")

    def test_music_file_missing(self):
        task = self.task()
        task.music_path.unlink()
        self._check(task, "ไม่พบไฟล์เพลง")

    def test_music_outside_task_dir(self):
        task = self.task()
        outside = self.root / "outside_30_Music.mp3"
        ts.make_music(outside, seconds=14)
        task.music_input["files"] = [str(outside)]
        task.write_request()
        self._check(task, "นอกโฟลเดอร์งาน")

    def test_music_not_listed_in_input(self):
        task = self.task()                       # file exists in the task dir but the input does not list it
        task.music_input["files"] = [str(task.music_dir / "music-state.json")]
        task.write_request()
        self._check(task, "_30_Music.mp3")

    def test_music_empty(self):
        task = self.task()
        task.music_path.write_bytes(b"")
        self._check(task, "ว่าง")

    def test_music_without_audio_stream(self):
        task = self.task()
        ts.make_music(task.music_path, seconds=14, video_only=True)
        self._check(task, "audio stream")

    def test_music_shorter_than_video_is_not_looped(self):
        task = self.task(music_seconds=8)
        res = self._check(task, "เพลงสั้นกว่าวิดีโอ")
        self.assertRegex(res["error"], r"\(\d+(\.\d+)? วิ < \d+(\.\d+)? วิ\)")

    def test_injected_provider_returning_short_music_also_fails(self):
        # the duration rule is enforced by the pipeline, not only by FileMusicProvider
        task = self.task()
        rc = self.run_task(task, ts.FakeMusic(seconds=5))
        self.assertFailed(task, rc, contains="เพลงสั้นกว่าวิดีโอ")


@needs_ffmpeg
class MusicMixTests(Base):
    def test_longer_music_is_trimmed_to_video_with_fades(self):
        task = self.task(music_seconds=20)       # much longer than the 11.97 s video
        self.assertEqual(0, self.run_task(task, None))
        info = ts.probe(task.final)
        dur = float(info["format"]["duration"])
        self.assertAlmostEqual(VIDEO_S, dur, delta=1 / 30)
        a = [s for s in info["streams"] if s["codec_type"] == "audio"][0]
        self.assertLessEqual(abs(float(a["duration"]) - VIDEO_S), 1 / 30 + 0.02)
        mid = mean_volume_db(task.final, 5.0, 0.5)
        tail = mean_volume_db(task.final, dur - 0.5, 0.5)
        head = mean_volume_db(task.final, 0.0, 0.06)
        self.assertLess(tail, mid - 6.0, f"fade-out missing: tail {tail} dB vs middle {mid} dB")
        self.assertLess(head, mid - 3.0, f"fade-in missing: head {head} dB vs middle {mid} dB")

    def test_music_a_little_longer_than_video_succeeds(self):
        task = self.task(music_seconds=12.5)
        self.assertEqual(0, self.run_task(task, None))

    def test_transient_rich_loud_music_passes_loudness_and_true_peak_gates(self):
        task = self.task(music_kind="bursts", music_amp=0.9)
        self.assertEqual(0, self.run_task(task, None), task.result_path.read_text() if task.result_path.exists() else "")
        i, tp = ts.measure_loudness(task.final)
        self.assertAlmostEqual(-14.0, i, delta=1.0)
        self.assertLessEqual(tp, -1.0)

    def test_peaky_music_bed_uses_limiter_and_lands_on_target(self):
        import audio
        import common
        src = self.root / "burst_30_Music.mp3"
        ts.make_music(src, seconds=14, kind="bursts", amp=0.9)
        m = audio._loudnorm_run([ts.FFMPEG, "-hide_banner", "-nostats", "-t", "11.967", "-i", str(src), "-af",
                                 "loudnorm=I=-14:TP=-2:LRA=11:print_format=json", "-f", "null", "-"], common.Deadline(60), "m")
        self.assertGreater(m["input_tp"] + (-14.0 - m["input_i"]), audio.TARGET_TP, "fixture must be too peaky for a linear gain")
        bed = self.root / "bed.wav"
        audio.build_music_bed(src, 11.967, bed, common.Deadline(120))
        i, tp = ts.measure_loudness(bed)
        self.assertAlmostEqual(-14.0, i, delta=0.5)
        self.assertLessEqual(tp, -1.5)

    def test_quiet_music_is_brought_to_target(self):
        task = self.task(music_amp=0.02)
        self.assertEqual(0, self.run_task(task, None))
        i, tp = ts.measure_loudness(task.final)
        self.assertAlmostEqual(-14.0, i, delta=1.0)
        self.assertLessEqual(tp, -1.0)

    def test_true_peak_target_is_minus_two(self):
        import audio
        self.assertEqual(-2.0, audio.TARGET_TP)
        self.assertEqual(-1.0, audio.MAX_TP)
        self.assertEqual(-14.0, audio.TARGET_I)
        self.assertEqual(1.0, audio.TOL_I)


@needs_ffmpeg
class NoNetworkTests(Base):
    def test_full_successful_pipeline_makes_no_network_call(self):
        def boom(*a, **k):
            raise AssertionError("network access attempted")

        task = self.task()
        with mock.patch.object(socket, "socket", side_effect=boom), \
                mock.patch.object(socket, "create_connection", side_effect=boom), \
                mock.patch.object(socket, "getaddrinfo", side_effect=boom):
            rc = self.run_task(task, None)
        self.assertEqual(0, rc, task.result_path.read_text())
        self.assertEqual("succeeded", task.result()["status"])
        self.assertTrue(task.final.exists())


class NoNetworkStaticTests(unittest.TestCase):
    def test_skill_scripts_import_no_network_modules(self):
        banned = re.compile(r"^\s*(?:import|from)\s+(socket|ssl|http|urllib|requests|httpx|aiohttp|ftplib|smtplib|websocket)\b", re.M)
        for p in sorted(ts.SCRIPTS.glob("*.py")):
            self.assertIsNone(banned.search(p.read_text(encoding="utf-8")), f"{p.name} imports a network module")


@needs_ffmpeg
class CliMusicTests(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run(["/Volumes/Ext_SS990Pro/Dev/openMontage-video-production/.venv/bin/python", "-B",
                               str(ts.SCRIPTS / "gg_short_reel.py"), *args], capture_output=True, text=True, timeout=180)

    def test_cli_with_aios_music_input_succeeds(self):
        with tempfile.TemporaryDirectory() as d:
            task = Task(Path(d))
            r = self.cli("--request", str(task.request_path), "--timeout-s", "150")
            self.assertEqual(0, r.returncode, r.stderr)
            self.assertEqual("succeeded", task.result()["status"])
            self.assertTrue(task.final.exists())

    def test_cli_without_music_input_fails_with_retry_safe_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            task = Task(Path(d), music=False)
            r = self.cli("--request", str(task.request_path), "--timeout-s", "150")
            self.assertNotEqual(0, r.returncode)
            res = task.result()
            self.assertEqual("failed", res["status"])
            self.assertIs(True, res["retry_safe"])
            self.assertIn("input role music", res["error"])
            self.assertFalse(task.final.exists())


if __name__ == "__main__":
    unittest.main()
