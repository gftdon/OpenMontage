"""CF-A85 round 5: bounded wait on the result.lock (R5-1) and the inode re-check after the lock file was unlinked (R5-2)."""
import contextlib
import fcntl
import io
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import test_support as ts
from test_support import FakeMusic, needs_ffmpeg

CORR = {"schema": 1, "task_id": "t", "step_id": "s", "run_id": "r", "dispatch_id": "d",
        "target": {"project_id": "p", "config_ref": "c"}}


RUN_JOIN_S = 90      # R6-2: a whole run with the lock held must end well inside this; a blocking flock would never end


@contextlib.contextmanager
def held_lock(run_dir):
    """A peer that holds <run_dir>/.result.lock and never lets go (until the with block ends)."""
    fd = os.open(Path(run_dir) / ".result.lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        yield
    finally:
        os.close(fd)


def call_in_daemon_thread(testcase, fn, join_s):
    """R6-2: run `fn` in a daemon thread and fail (instead of hanging the suite) if it has not finished within `join_s`.
    Returns fn's value; an exception raised by fn is re-raised here, so assertRaises keeps working around the call."""
    box = {}

    def target():
        try:
            box["value"] = fn()
        except BaseException as e:   # noqa: BLE001
            box["error"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(join_s)
    testcase.assertFalse(t.is_alive(), f"the call did not return within {join_s} s: it is blocked on the lock instead of giving up")
    if "error" in box:
        raise box["error"]
    return box.get("value")


class LockBoundUnitTests(unittest.TestCase):
    def test_r5_1_publish_gives_up_on_a_lock_held_forever(self):
        import receipt
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "result.json"
            with held_lock(d):
                t0 = time.monotonic()
                with self.assertRaises(receipt.ReceiptLockTimeout):
                    call_in_daemon_thread(self, lambda: receipt.publish_receipt(
                        p, receipt.success_receipt(CORR, ["/x"]), CORR, timeout_s=0.4), 10)
                elapsed = time.monotonic() - t0
                self.assertGreaterEqual(elapsed, 0.35, "it did wait for the lock first")
                self.assertLess(elapsed, 3.0, "and then gave up")
                self.assertFalse(p.exists(), "nothing was published")
                self.assertEqual([".result.lock"], sorted(os.listdir(d)), "no temp file; the peer's lock file is not ours to unlink")
            # the peer is gone: the very same call now goes through at once
            self.assertIsNone(receipt.publish_receipt(p, receipt.success_receipt(CORR, ["/x"]), CORR, timeout_s=0.4))
            self.assertEqual(["result.json"], sorted(os.listdir(d)))

    def test_r5_1_timeout_is_capped_by_the_module_ceiling(self):
        import receipt
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "result.json"
            with held_lock(d), mock.patch.object(receipt, "LOCK_TIMEOUT_MAX_S", 0.3):
                t0 = time.monotonic()
                with self.assertRaises(receipt.ReceiptLockTimeout):
                    call_in_daemon_thread(self, lambda: receipt.publish_receipt(
                        p, receipt.success_receipt(CORR, ["/x"]), CORR, timeout_s=600), 10)
                self.assertLess(time.monotonic() - t0, 3.0)

    def test_r5_1_lock_budget_is_remaining_deadline_clamped_to_floor_and_ceiling(self):
        import common
        import gg_short_reel as gg
        now = [1000.0]
        dl = common.Deadline(100, clock=lambda: now[0])
        self.assertEqual(gg.LOCK_WAIT_MAX_S, gg._lock_budget(dl), "plenty of time left: the fixed ceiling")
        now[0] = 1000.0 + 95          # 5 s left
        self.assertEqual(5.0, gg._lock_budget(dl))
        now[0] = 1000.0 + 99.9        # 0.1 s left: the floor still allows one attempt
        self.assertEqual(gg.LOCK_WAIT_MIN_S, gg._lock_budget(dl))
        now[0] = 1000.0 + 500         # long past the deadline
        self.assertEqual(gg.LOCK_WAIT_MIN_S, gg._lock_budget(dl))
        self.assertEqual((1.0, 30.0), (gg.LOCK_WAIT_MIN_S, gg.LOCK_WAIT_MAX_S))


@needs_ffmpeg
class LockBoundRunTests(unittest.TestCase):
    """The whole script with a peer holding the lock forever: it must end (exit 3, no result.json) and never wait twice."""

    def setUp(self):
        import gg_short_reel
        self.gg = gg_short_reel
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.task = ts.Task(Path(self._tmp.name).resolve())

    def _run(self, **kw):
        import receipt
        calls, real = [], receipt.publish_receipt

        def spy(*a, **k):
            t0 = time.monotonic()
            calls.append({"status": a[1].get("status"), "timeout_s": k.get("timeout_s")})
            try:
                return real(*a, **k)
            finally:
                calls[-1]["waited_s"] = time.monotonic() - t0

        err = io.StringIO()
        with held_lock(self.task.run_dir), mock.patch.object(receipt, "publish_receipt", side_effect=spy), \
                contextlib.redirect_stderr(err):
            provider = kw.pop("provider", FakeMusic())
            rc = call_in_daemon_thread(self, lambda: self.gg.run(self.task.request_path, music_provider=provider, **kw),
                                       RUN_JOIN_S)
        return rc, calls, err.getvalue()

    def _assert_ended_cleanly(self, rc, err):
        self.assertEqual(3, rc)
        self.assertFalse(self.task.result_path.exists(), "no result.json: the agent's ln fallback writes it")
        self.assertIn("lock", err)
        leftovers = [n for n in self.task.run_dir_names() if n.startswith(".") and n != ".result.lock" or n.endswith(".partial.mp4")]
        self.assertEqual([], leftovers)
        self.assertFalse(self.task.final.exists(), "the final of a run that gets a failed receipt must not block a retry")

    def test_r5_1_success_path_lock_held_forever_exits_3_after_one_bounded_wait(self):
        with mock.patch.object(self.gg, "LOCK_WAIT_MAX_S", 1.0):
            t0 = time.monotonic()
            rc, calls, err = self._run(timeout_s=300)
            total = time.monotonic() - t0
        self._assert_ended_cleanly(rc, err)
        self.assertEqual(["succeeded"], [c["status"] for c in calls], "exactly one publish attempt: no failure-receipt retry on the same lock")
        self.assertLessEqual(calls[0]["timeout_s"], 1.0)
        self.assertLess(calls[0]["waited_s"], 3.0)
        self.assertLess(total, 60)

    def test_r5_1_failure_path_lock_held_forever_exits_3_after_one_bounded_wait(self):
        import compose
        with mock.patch.object(self.gg, "LOCK_WAIT_MAX_S", 1.0), \
                mock.patch.object(compose, "build_base", side_effect=RuntimeError("boom")):
            rc, calls, err = self._run(timeout_s=300)
        self._assert_ended_cleanly(rc, err)
        self.assertEqual(["failed"], [c["status"] for c in calls], "only the failure receipt was attempted, once")
        self.assertLess(calls[0]["waited_s"], 3.0)

    def test_r5_1_deadline_already_exhausted_still_gets_exactly_one_floor_length_attempt(self):
        import compose
        with mock.patch.object(compose, "build_base", side_effect=lambda *a, **k: time.sleep(30)):
            rc, calls, err = self._run(timeout_s=1)
        self._assert_ended_cleanly(rc, err)
        self.assertEqual(["failed"], [c["status"] for c in calls])
        self.assertEqual(self.gg.LOCK_WAIT_MIN_S, calls[0]["timeout_s"], "no time left: the small floor, not zero and not 30 s")
        self.assertLess(calls[0]["waited_s"], 4.0)

    def test_r5_1_a_free_lock_is_unaffected(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = self.gg.run(self.task.request_path, music_provider=FakeMusic(), timeout_s=300)
        self.assertEqual(0, rc)
        self.assertEqual("succeeded", json.loads(self.task.result_path.read_text())["status"])


class LockInodeRecheckTests(unittest.TestCase):
    """R5-2: the lock file is unlinked by whoever finishes. A waiter that wakes up on the unlinked inode I1 must notice the
    path now names a different inode (or none) and re-lock. Without that re-check it runs concurrently with the writer that
    created a fresh lock file I2.

    Sequence (all by events, no sleeps for ordering):
      A holds I1 and is parked at _before_replace.  B opens I1 and waits (_lock_contended).  A is released, replaces,
      unlinks the lock file.  B wins the flock on the now-unlinked I1 and is held right there (_after_flock) until
      C has opened a NEW lock file I2, won it and parked at _before_replace.  Then B is let go.
    Required: B and C are never inside classify/replace together, and C's terminal receipt is not overwritten by B."""

    def test_r5_2_waiter_on_an_unlinked_lock_inode_does_not_run_beside_the_new_holder(self):
        import receipt
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "result.json"
            p.write_text('{"status": "running"}')                   # exists and is not terminal: every writer reaches replace
            a_data = {**CORR, "status": "running", "outputs": []}   # A leaves a non-terminal file, so B and C reach replace too
            b_data = receipt.failure_receipt(CORR, "B", True)
            c_data = receipt.success_receipt(CORR, ["/c"])
            ev = {n: threading.Event() for n in ("a_parked", "release_a", "b_waiting_1", "b_held_i1", "release_b",
                                                 "c_parked", "release_c", "b_waiting_2", "b_in_replace", "a_done")}
            guard = threading.Lock()
            state = {"active": 0, "max_active": 0, "inside": [], "contended": {"B": 0}, "after_flock": []}
            results, errors = {}, []

            def name():
                return threading.current_thread().name

            def contended(path):
                if name() == "B":
                    state["contended"]["B"] += 1
                    ev["b_waiting_1" if state["contended"]["B"] == 1 else "b_waiting_2"].set()

            def after_flock(path):
                if name() == "B" and not ev["b_held_i1"].is_set():
                    ev["b_held_i1"].set()
                    if not ev["release_b"].wait(15):
                        errors.append("B was never released")

            def before_replace(tmp, path):
                who = name()
                with guard:
                    state["active"] += 1
                    state["inside"].append(who)
                    state["max_active"] = max(state["max_active"], state["active"])
                try:
                    if who == "A":
                        ev["a_parked"].set()
                        if not ev["release_a"].wait(15):
                            errors.append("A was never released")
                    elif who == "C":
                        ev["c_parked"].set()
                        if not ev["release_c"].wait(15):
                            errors.append("C was never released")
                    else:
                        ev["b_in_replace"].set()
                finally:
                    with guard:
                        state["active"] -= 1

            def worker(who, data):
                try:
                    results[who] = receipt.publish_receipt(p, data, CORR, timeout_s=20)
                except BaseException as e:   # noqa: BLE001
                    results[who] = e
                    errors.append(f"{who}: {e!r}")
                if who == "A":
                    ev["a_done"].set()

            threads = {w: threading.Thread(target=worker, args=(w, dat), name=w, daemon=True)
                       for w, dat in (("A", a_data), ("B", b_data), ("C", c_data))}
            patches = [mock.patch.object(receipt, "_before_replace", side_effect=before_replace),
                       mock.patch.object(receipt, "_lock_contended", side_effect=contended),
                       mock.patch.object(receipt, "_after_flock", side_effect=after_flock)]
            for pt in patches:
                pt.start()
            try:
                threads["A"].start()
                self.assertTrue(ev["a_parked"].wait(15), "A never reached the replace point")
                threads["B"].start()
                self.assertTrue(ev["b_waiting_1"].wait(15), "B never started waiting on A's lock file (I1)")
                ev["release_a"].set()                                # A replaces, unlinks I1, releases
                self.assertTrue(ev["b_held_i1"].wait(15), "B never won the flock on the unlinked I1")
                self.assertTrue(ev["a_done"].wait(15), "A never finished")
                self.assertFalse((Path(d) / ".result.lock").exists(), "A removed the lock file: B holds only a ghost inode")
                threads["C"].start()                                  # opens a NEW lock file (I2)
                self.assertTrue(ev["c_parked"].wait(15), "C never reached the replace point under its own lock file (I2)")
                ev["release_b"].set()                                 # B now checks / proceeds
                # B either runs into replace beside C (the bug) or notices the stale inode and waits on I2 again
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline and not (ev["b_in_replace"].is_set() or ev["b_waiting_2"].is_set()):
                    time.sleep(0.01)
                overlapped = state["max_active"] > 1
                snapshot_inside = list(state["inside"])
                ev["release_c"].set()
                for t in threads.values():
                    t.join(30)
            finally:
                ev["release_a"].set()
                ev["release_b"].set()
                ev["release_c"].set()
                for pt in patches:
                    pt.stop()
                for t in threads.values():
                    t.join(5)
            self.assertEqual([], errors)
            self.assertFalse(overlapped, f"B and C were inside classify/replace at the same time: {snapshot_inside}")
            self.assertEqual(1, state["max_active"])
            self.assertTrue(ev["b_waiting_2"].is_set(), "B must have gone back to wait on the NEW lock file")
            self.assertEqual(["A", "C"], state["inside"], "A then C entered classify/replace; B only saw the terminal receipt afterwards")
            self.assertIsNone(results["A"])
            self.assertIsNone(results["C"], "C published its terminal receipt")
            self.assertEqual("succeeded", results["B"], "B saw C's terminal receipt and left it alone")
            self.assertEqual(c_data, json.loads(p.read_text()), "no terminal receipt was overwritten")
            self.assertEqual(["result.json"], sorted(os.listdir(d)), "no temp file and no lock file left")


class LockReopenCeilingTests(unittest.TestCase):
    """R6-1: when the flock is won at once but the path no longer names the locked inode, the lock is re-opened. Those
    re-open rounds never hit the contended branch, so the ceiling must be checked on every round, not only while waiting."""

    def test_r6_1_endless_inode_mismatch_ends_with_a_timeout_within_the_ceiling(self):
        import receipt
        rounds = [0]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "result.json"

            def after_flock(lock_path):
                # the flock was won immediately; now make the path stop naming the locked inode, every single round
                rounds[0] += 1
                if rounds[0] > 1500:
                    raise AssertionError("still re-opening after 1500 rounds: the ceiling is not enforced on re-open rounds")
                time.sleep(0.001)            # keeps a correct run to a few hundred rounds
                try:
                    os.unlink(lock_path)
                except FileNotFoundError:
                    pass

            with mock.patch.object(receipt, "_after_flock", side_effect=after_flock):
                t0 = time.monotonic()
                with self.assertRaises(receipt.ReceiptLockTimeout):
                    call_in_daemon_thread(self, lambda: receipt.publish_receipt(
                        p, receipt.success_receipt(CORR, ["/x"]), CORR, timeout_s=0.4), 10)
                elapsed = time.monotonic() - t0
            self.assertGreaterEqual(elapsed, 0.35, "it kept trying until the budget was used up")
            self.assertLess(elapsed, 3.0, "and then gave up within the ceiling")
            self.assertGreater(rounds[0], 1, "the mismatch really repeated")
            self.assertFalse(p.exists(), "nothing was published")
            self.assertEqual([], sorted(os.listdir(d)), "no temp file and no lock file left")


if __name__ == "__main__":
    unittest.main()
