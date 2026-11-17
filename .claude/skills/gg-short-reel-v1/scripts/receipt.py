"""AIOS receipt (result.json): always correlated, always written atomically."""
import copy
import json
import os
import tempfile
from pathlib import Path

CORRELATION_KEYS = ("schema", "task_id", "step_id", "run_id", "dispatch_id", "target")


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


def write_receipt(result_path, data):
    _atomic_write_json(result_path, data)


def write_diagnostic(path, data):
    """<final>.FAILED.json — same atomic write, separate entry point (not a receipt)."""
    _atomic_write_json(path, data)
