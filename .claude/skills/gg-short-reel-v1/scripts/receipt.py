"""AIOS receipt (result.json): always correlated, always written atomically."""
import contextlib
import copy
import fcntl
import json
import os
import tempfile
from pathlib import Path

CORRELATION_KEYS = ("schema", "task_id", "step_id", "run_id", "dispatch_id", "target")
TERMINAL_STATUSES = ("succeeded", "failed")
RECEIPT_READ_MAX_BYTES = 1024 * 1024


def correlation_of(request):
    """Copy the correlation fields exactly (deep copy) — never invent IDs."""
    return {k: copy.deepcopy(request[k]) for k in CORRELATION_KEYS}


def decide_retry_safe(paid_call_started):
    """A new attempt is safe only if no paid/external work was started. Single source of truth."""
    return not paid_call_started


def success_receipt(correlation, outputs):
    return {**correlation, "status": "succeeded", "outputs": copy.deepcopy(list(outputs))}


def failure_receipt(correlation, error, retry_safe):
    return {**correlation, "status": "failed", "error": str(error), "retry_safe": bool(retry_safe), "outputs": []}


def _atomic_write_json(path, data):
    """Temp file beside `path`, fsync, then os.replace (no half-written file is ever visible)."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".result.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def existing_terminal_status(result_path, correlation):
    """'succeeded' / 'failed' when result_path already holds a terminal receipt of THIS correlation, else None.
    Anything unreadable, non-terminal or of another correlation counts as "nothing to protect"."""
    try:
        if os.path.getsize(result_path) > RECEIPT_READ_MAX_BYTES:
            return None
        with open(result_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("status") not in TERMINAL_STATUSES:
        return None
    if any(k not in data or data[k] != correlation[k] for k in CORRELATION_KEYS):
        return None
    return data["status"]


def write_receipt(result_path, data):
    _atomic_write_json(result_path, data)


def _before_link(tmp, result_path):
    """Seam for tests: runs after the temp file is complete, immediately before the no-clobber link."""


def _before_replace(tmp, result_path):
    """Seam for tests: runs after an existing non-protected file was classified, immediately before os.replace."""


@contextlib.contextmanager
def _result_lock(result_path):
    """Exclusive flock on <run_dir>/.result.lock for the whole classify + publish sequence (released in `finally`).
    The lock file is removed on exit while still locked; a waiter that wakes up on the unlinked inode notices (the path no
    longer names the inode it locked) and re-opens, so removal cannot let two writers hold "the" lock at once."""
    lock_path = Path(result_path).with_name(".result.lock")
    while True:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                st = os.stat(lock_path)
            except FileNotFoundError:
                st = None
            held = os.fstat(fd)
            if st is not None and (st.st_ino, st.st_dev) == (held.st_ino, held.st_dev):
                break
        except BaseException:
            os.close(fd)
            raise
        os.close(fd)                     # the previous holder unlinked the file we waited on: lock the new one
    try:
        yield
    finally:
        try:
            os.unlink(lock_path)
        except OSError:
            pass
        os.close(fd)                     # releases the flock


def publish_receipt(result_path, data, correlation):
    """No-clobber atomic publication of a receipt: temp file -> os.link(tmp, result_path) (fails with EEXIST instead of
    replacing). Returns None when `data` is now result_path; otherwise the status ('succeeded'/'failed') of the terminal
    receipt of THIS correlation that was already there, which is left untouched. An existing file that is anything else
    (other correlation, non-terminal, garbage) is replaced atomically as before. The temp file never outlives the call.
    The whole sequence (link attempt, classify the existing file, replace) runs under an exclusive flock, so a competing
    writer cannot slip a terminal receipt in between classifying and replacing."""
    path = Path(result_path)
    with _result_lock(path):
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".result.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            _before_link(tmp, path)
            try:
                os.link(tmp, path)
                return None
            except FileExistsError:
                pass
            status = existing_terminal_status(path, correlation)
            if status is not None:
                return status
            _before_replace(tmp, path)
            os.replace(tmp, path)
            return None
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def write_diagnostic(path, data):
    """<final>.FAILED.json — same atomic write, separate entry point (not a receipt)."""
    _atomic_write_json(path, data)
