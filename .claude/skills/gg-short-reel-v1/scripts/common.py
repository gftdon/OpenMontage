"""Shared helpers: errors, total-run deadline, subprocess runner, ffprobe wrapper."""
import contextlib
import json
import os
import shutil
import signal
import subprocess
import threading
import time


class GgError(Exception):
    """A specific, human-readable failure (message goes into the failed receipt)."""


class RunTimeout(BaseException):
    """Total run budget exhausted. BaseException so no `except Exception` can swallow it."""


class RunTerminated(BaseException):
    """SIGTERM received."""


class Deadline:
    def __init__(self, total_s, clock=time.monotonic):
        self.total_s = float(total_s)
        self._clock = clock
        self._end = clock() + self.total_s

    def remaining(self):
        return self._end - self._clock()

    def timeout_error(self):
        return RunTimeout(f"timeout: หมดเวลารวม {self.total_s:g} วินาที")

    def check(self):
        if self.remaining() <= 0:
            raise self.timeout_error()


@contextlib.contextmanager
def armed(deadline):
    """Enforce the total deadline even inside pure-Python stages (SIGALRM, main thread only)
    and convert SIGTERM into an exception so a failed receipt is still written."""
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "setitimer"):
        yield
        return

    def on_alarm(signum, frame):
        raise deadline.timeout_error()

    def on_term(signum, frame):
        raise RunTerminated("terminated: ได้รับสัญญาณ SIGTERM")

    old_alarm = signal.signal(signal.SIGALRM, on_alarm)
    old_term = signal.signal(signal.SIGTERM, on_term)
    try:
        signal.setitimer(signal.ITIMER_REAL, max(deadline.remaining(), 0.001))
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_alarm)
        signal.signal(signal.SIGTERM, old_term)


def find_tool(name):
    found = shutil.which(name)
    if found:
        return found
    for base in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"):
        cand = os.path.join(base, name)
        if os.path.exists(cand):
            return cand
    raise GgError(f"ไม่พบโปรแกรม {name} (ffmpeg/ffprobe ต้องติดตั้งไว้)")


def run_cmd(args, deadline, what, timeout_s=None):
    """Run one subprocess under the remaining total budget. Returns CompletedProcess (text)."""
    deadline.check()
    budget = deadline.remaining()
    if timeout_s is not None:
        budget = min(budget, timeout_s)
    try:
        proc = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=budget,
                              stdin=subprocess.DEVNULL, errors="replace")
    except subprocess.TimeoutExpired:  # subprocess.run already killed + reaped the child
        raise deadline.timeout_error()
    if proc.returncode != 0:
        tail = " ".join((proc.stderr or "").strip().split())[-240:]
        raise GgError(f"{what} ล้มเหลว (exit {proc.returncode}): {tail}")
    return proc


def probe(path, deadline):
    proc = run_cmd([find_tool("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                   deadline, f"ffprobe {os.path.basename(str(path))}", timeout_s=60)
    try:
        return json.loads(proc.stdout)
    except ValueError:
        raise GgError(f"ffprobe อ่านผลของ {os.path.basename(str(path))} ไม่ได้")


def streams_of(info, codec_type):
    return [s for s in info.get("streams", []) if s.get("codec_type") == codec_type]
