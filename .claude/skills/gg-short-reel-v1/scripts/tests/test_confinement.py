"""CF-A85 review F4: the script file, the originality record and the clips manifest are read only through the same
resolver as clip/music files (realpath, regular file, inside the task dir, listed in the input's files)."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_support as ts
from test_support import FakeMusic, Task, needs_ffmpeg

CORR = ("schema", "task_id", "step_id", "run_id", "dispatch_id", "target")
OUTSIDE_TEXT = "OUTSIDE-SECRET-TEXT"
OUTSIDE_MSG = "นอกโฟลเดอร์งาน"


@needs_ffmpeg
class ConfinementTests(unittest.TestCase):
    def setUp(self):
        import gg_short_reel
        import request_io
        self.gg, self.rio = gg_short_reel, request_io
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.task = Task(self.root)
        self.outside = self.root / "outside"
        self.outside.mkdir()

    # ---- helpers ----
    def _outside_script(self, dirname=None):
        d = self.outside / dirname if dirname else self.outside
        d.mkdir(parents=True, exist_ok=True)
        script = {"shots": [], "on_screen_text": [{"text": OUTSIDE_TEXT, "start_s": 0.5, "end_s": 3.0, "placement": "top"}],
                  "post_caption": "c", "hashtags": ["#a"]}
        p = d / f"{self.task.code}_00_Script.txt"
        p.write_bytes(json.dumps(script).encode("utf-8"))
        return p

    @staticmethod
    def _originality(path, script_path):
        path.write_text(json.dumps({"schema": 1, "pass": True, "script_sha256": hashlib.sha256(script_path.read_bytes()).hexdigest(),
                                    "checked_at": "2026-11-17T00:00:00.000Z", "model": "m", "reasons": []}))

    def _set_files(self, idx, files):
        req = json.loads(self.task.request_path.read_text())
        req["inputs"][idx]["files"] = [str(f) for f in files]
        self.task.request_path.write_text(json.dumps(req))
        self.task.request = req

    def _run_and_assert_refused(self, contains):
        reads = []
        real_read = self.rio._read_capped

        def spy(path, cap, what):
            reads.append(os.path.realpath(path))
            return real_read(path, cap, what)

        music = FakeMusic()
        with mock.patch.object(self.rio, "_read_capped", side_effect=spy):
            rc = self.gg.run(self.task.request_path, music_provider=music, timeout_s=300)
        self.assertNotEqual(0, rc)
        res = self.task.result()
        self.assertEqual("failed", res["status"])
        self.assertEqual([], res["outputs"])
        self.assertIs(True, res["retry_safe"])
        for k in CORR:
            self.assertEqual(self.task.request[k], res[k])
        self.assertIn(contains, res["error"])
        self.assertFalse(self.task.final.exists())
        self.assertEqual([], music.calls, "nothing downstream of input validation may run")
        outside_real = os.path.realpath(self.outside)
        self.assertEqual([], [r for r in reads if r == outside_real or r.startswith(outside_real + os.sep)],
                         "no file outside the task dir may be read")
        for p in self.task.run_dir.iterdir():
            self.assertNotIn(OUTSIDE_TEXT, p.read_text(errors="ignore"))

    # ---- script ----
    def test_script_path_outside_task_dir(self):
        osc = self._outside_script()
        oorig = self.outside / "originality.json"
        self._originality(oorig, osc)
        self._set_files(0, [oorig, osc])
        self._run_and_assert_refused(OUTSIDE_MSG)

    def test_script_symlink_pointing_outside(self):
        osc = self._outside_script()
        self.task.script_path.unlink()
        os.symlink(osc, self.task.script_path)
        self._originality(self.task.orig_path, osc)       # valid record for the outside bytes
        self._run_and_assert_refused(OUTSIDE_MSG)

    # ---- originality record ----
    def test_originality_path_outside_task_dir(self):
        oorig = self.outside / "originality.json"
        self._originality(oorig, self.task.script_path)   # a perfectly valid record, but not beside the script / not in the task
        self._set_files(0, [oorig, self.task.script_path])
        self._run_and_assert_refused("ด่านกันลอก")

    def test_originality_symlink_pointing_outside(self):
        oorig = self.outside / "originality.json"
        self._originality(oorig, self.task.script_path)
        self.task.orig_path.unlink()
        os.symlink(oorig, self.task.orig_path)
        self._run_and_assert_refused(OUTSIDE_MSG)

    # ---- clips manifest ----
    def test_manifest_path_outside_task_dir(self):
        d = self.outside / f"{self.task.code}_20_Clips"
        d.mkdir()
        omf = d / "manifest.json"
        omf.write_bytes(self.task.manifest_path.read_bytes())     # valid manifest: it would run to success if it were read
        self._set_files(1, [omf] + self.task.clip_files)
        self._run_and_assert_refused(OUTSIDE_MSG)

    def test_manifest_symlink_pointing_outside(self):
        d = self.outside / f"{self.task.code}_20_Clips"
        d.mkdir()
        omf = d / "manifest.json"
        omf.write_bytes(self.task.manifest_path.read_bytes())
        self.task.manifest_path.unlink()
        os.symlink(omf, self.task.manifest_path)
        self._run_and_assert_refused(OUTSIDE_MSG)

    # ---- not a regular file ----
    def test_script_that_is_a_directory_is_refused(self):
        self.task.script_path.unlink()
        self.task.script_path.mkdir()
        self._run_and_assert_refused("ไม่ใช่ไฟล์ปกติ")


if __name__ == "__main__":
    unittest.main()
