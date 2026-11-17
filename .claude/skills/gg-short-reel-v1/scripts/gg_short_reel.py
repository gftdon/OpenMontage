#!/usr/bin/env python3
"""AIOS edit_short for G&G Short Reels: clips -> 1080x1920 -> burned text -> AIOS music bed -> verified final + receipt.

The script always writes the correlated AIOS receipt (result.json) itself, success or failure.
"""
import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audio  # noqa: E402
import common  # noqa: E402
import compose  # noqa: E402
import overlay  # noqa: E402
import receipt  # noqa: E402
import request_io  # noqa: E402

DEFAULT_TIMEOUT_S = 900.0
MIN_DURATION_S, MAX_DURATION_S = 10.0, 90.0
PREFLIGHT_SLACK_S = 1.0   # source-duration estimate is only used to refuse clearly impossible inputs early
ERROR_MAX = 480
LOCK_WAIT_MAX_S = receipt.LOCK_TIMEOUT_MAX_S   # ceiling of the one wait for result.lock when a receipt is published (30 s)
LOCK_WAIT_MIN_S = 1.0     # floor: even with the run deadline spent, a failure receipt gets one short attempt
EXIT_LOCK_TIMEOUT = 3     # same code as "could not write the receipt": the agent then writes it with the `ln` fallback
EXIT_RECEIPT_EXISTS = 4   # result.json already holds a terminal receipt of this correlation: nothing was touched


class State:
    def __init__(self):
        self.stage = "start"
        self.paid_call_started = False
        self.final = None          # validated final path (None until outputs validate)
        self.partial = None
        self.final_produced = False
        self.workdir = None


def check_duration(duration_s):
    """Exactly AIOS' gate (10 <= d <= 90 on ffprobe format.duration). No tolerance: anything the skill lets through
    that AIOS then rejects would end as outcome_unknown and lock the single-flight, so this must never be looser."""
    if not (MIN_DURATION_S <= duration_s <= MAX_DURATION_S):
        raise common.GgError(f"ความยาววิดีโอ {duration_s:.4f} วินาที อยู่นอกช่วง {MIN_DURATION_S:g}-{MAX_DURATION_S:g} วินาที")


def verify_final(path, deadline, measured=None):
    """The delivered file itself: exactly 1 H.264 video + 1 AAC audio, 1080x1920, SAR 1, 30 fps, duration + loudness gates.
    `measured` = (LUFS, dBTP) just taken from this very file (saves a second measurement pass)."""
    info = common.probe(path, deadline)
    v, a = common.streams_of(info, "video"), common.streams_of(info, "audio")
    if len(v) != 1 or len(a) != 1 or len(info.get("streams", [])) != 2:
        raise common.GgError(f"ไฟล์สุดท้ายต้องมี video 1 + audio 1 stream (พบ video {len(v)}, audio {len(a)})")
    vs, as_ = v[0], a[0]
    if (vs.get("codec_name"), vs.get("width"), vs.get("height"), vs.get("pix_fmt")) != ("h264", compose.W, compose.H, "yuv420p"):
        raise common.GgError(f"video ไม่ตรงสเปก: {vs.get('codec_name')} {vs.get('width')}x{vs.get('height')} {vs.get('pix_fmt')}")
    if vs.get("sample_aspect_ratio") not in ("1:1", None) or vs.get("r_frame_rate") != f"{compose.FPS}/1" \
            or vs.get("avg_frame_rate") != f"{compose.FPS}/1":
        raise common.GgError(f"video ต้อง SAR 1 และ {compose.FPS} fps คงที่ (SAR {vs.get('sample_aspect_ratio')}, "
                             f"fps {vs.get('r_frame_rate')}/{vs.get('avg_frame_rate')})")
    if as_.get("codec_name") != "aac":
        raise common.GgError(f"audio ต้องเป็น AAC (ได้ {as_.get('codec_name')})")
    try:
        duration = float(info["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        raise common.GgError("อ่านความยาวไฟล์สุดท้ายไม่ได้")
    check_duration(duration)
    loud, peak = measured if measured is not None else audio.measure_loudness(path, deadline)
    if not audio.loudness_ok(loud, peak):
        raise common.GgError(f"loudness {loud:.1f} LUFS / true peak {peak:.1f} dBTP อยู่นอกเกณฑ์ "
                             f"(เป้า {audio.TARGET_I:g}±{audio.TOL_I:g} LUFS, TP ≤ {audio.MAX_TP:g} dBTP)")
    return {"duration_s": duration, "integrated_lufs": loud, "true_peak_dbtp": peak}


def pipeline(env, state, provider, deadline):
    state.stage = "validate"
    state.final = request_io.validate_outputs(env)
    request_io.validate_request(env)
    final = state.final
    if os.path.lexists(final):
        raise common.GgError(f"ไฟล์ปลายทางมีอยู่แล้ว — ไม่เขียนทับ: {final.name}")
    state.partial = final.with_name(final.name + ".partial.mp4")
    if os.path.lexists(state.partial):          # stale leftover of a killed run: ours by name, never trusted
        state.partial.unlink()

    state.stage = "inputs"
    plan = request_io.load_plan(env)
    state.stage = "script"
    items = overlay.parse_items(plan.texts_raw)
    font = overlay.resolve_font()

    state.stage = "probe"
    est = compose.estimate_duration(plan.shots, deadline)
    if est < MIN_DURATION_S - PREFLIGHT_SLACK_S or est > MAX_DURATION_S + PREFLIGHT_SLACK_S:
        raise common.GgError(f"ความยาวรวมโดยประมาณ {est:.1f} วินาที อยู่นอกช่วง {MIN_DURATION_S:g}-{MAX_DURATION_S:g} วินาที")

    state.workdir = Path(tempfile.mkdtemp(prefix=".gg-short-work-", dir=str(final.parent)))
    work = state.workdir

    state.stage = "compose"
    base = work / "base.mp4"
    compose.build_base(plan.shots, base, deadline)
    try:
        duration = float(common.probe(base, deadline)["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        raise common.GgError("อ่านความยาววิดีโอที่ตัดต่อแล้วไม่ได้")
    check_duration(duration)   # before any music call: a video that cannot pass the gate never costs anything more

    state.stage = "overlay"
    kept = overlay.clamp_items(items, duration)
    video = base
    if kept:
        video = work / "overlay.mp4"
        overlay.burn(base, kept, font, video, work, deadline)

    state.stage = "music"
    state.paid_call_started = bool(getattr(provider, "is_paid", False))
    try:
        music = provider.get_music(duration, None, work / "music_source.wav")
    except audio.MusicUnavailable as e:
        state.paid_call_started = False       # contract: raised only when nothing paid was started
        raise common.GgError(f"เพลงไม่พร้อมใช้งาน: {e}")
    audio.validate_music(music, deadline, min_duration_s=duration)
    bed = work / "bed.wav"
    trim, measured = 0.0, None
    for attempt in range(audio.MUX_ATTEMPTS):
        state.stage = "music"
        audio.build_music_bed(music, duration, bed, deadline, tp_trim_db=trim)
        state.stage = "mux"
        audio.mux(video, bed, state.partial, deadline)      # -y: a retry overwrites our own partial
        state.stage = "verify"
        measured = audio.measure_loudness(state.partial, deadline)
        trim = audio.next_tp_trim(*measured, trim)          # the AAC encode can push the peak over the gate: re-aim the bed
        if trim is None:
            break
    state.stage = "verify"
    verify_final(state.partial, deadline, measured=measured)

    state.stage = "publish"
    os.link(state.partial, final)              # fails if final appeared meanwhile: never overwrite
    state.final_produced = True
    os.unlink(state.partial)
    stale = final.with_name(final.name + ".FAILED.json")
    if stale.exists():
        stale.unlink()


def describe(exc, state):
    if isinstance(exc, KeyboardInterrupt):
        msg = "interrupted: ถูกขัดจังหวะ (KeyboardInterrupt)"
    elif isinstance(exc, (common.GgError, common.RunTimeout, common.RunTerminated)):
        msg = str(exc)
    elif isinstance(exc, FileExistsError) and state.stage == "publish":
        msg = "ไฟล์ปลายทางถูกสร้างขึ้นระหว่างทำงาน — ไม่เขียนทับ"
    else:
        msg = f"{type(exc).__name__}: {exc}"
    return f"[{state.stage}] {' '.join(msg.split())}"[:ERROR_MAX]


def _unlink_ours(p):
    try:
        os.unlink(p)
    except FileNotFoundError:
        pass
    except OSError as e:
        print(f"gg_short_reel: ลบ {p} ไม่ได้: {e}", file=sys.stderr)


def _cleanup_work(state):
    """Our scratch only: the work dir and our own .partial. Never a delivered file."""
    if state.workdir is not None:
        shutil.rmtree(state.workdir, ignore_errors=True)
    if state.partial is not None:
        _unlink_ours(state.partial)


def _cleanup_final(state):
    """Our own published final (only when this run's os.link created it)."""
    if state.final is not None and state.final_produced:
        _unlink_ours(state.final)


def _refuse(state, status):
    """A terminal receipt of this correlation is already in result_path (`status`): it stands and we exit 4.
    Our scratch goes. Our final goes too, unless that receipt is a success: it points at the final path, so the file
    there must stay exactly as it is (a success receipt whose output vanished fails AIOS' verify and locks the step)."""
    print(f"gg_short_reel: result.json มี receipt สถานะ {status} ของ correlation นี้อยู่แล้ว — ไม่เขียนทับ "
          f"และไม่แตะไฟล์อื่น (exit {EXIT_RECEIPT_EXISTS})", file=sys.stderr)
    _cleanup_work(state)
    if status != "succeeded":
        _cleanup_final(state)
    return EXIT_RECEIPT_EXISTS


def _lock_budget(deadline):
    """Seconds to wait for result.lock: what is left of the run deadline, at most LOCK_WAIT_MAX_S, at least LOCK_WAIT_MIN_S."""
    return max(LOCK_WAIT_MIN_S, min(deadline.remaining(), LOCK_WAIT_MAX_S))


def _lock_timeout_exit(state, exc):
    """A peer holds result.lock and did not let go: no receipt was written and none is attempted again (same lock, same wait).
    Our scratch and our own final go, because the agent's fallback writes a *failed* receipt and a leftover final would make
    every retry fail with "destination exists"."""
    print(f"gg_short_reel: เขียน receipt ไม่สำเร็จ: {exc} (exit {EXIT_LOCK_TIMEOUT}; agent ต้องเขียน receipt ล้มเหลวด้วย ln no-clobber)",
          file=sys.stderr)
    _cleanup_work(state)
    _cleanup_final(state)
    return EXIT_LOCK_TIMEOUT


def run(request_path, music_provider=None, timeout_s=DEFAULT_TIMEOUT_S):
    """Returns the process exit code. `music_provider` is a Python-only injection point (tests); the CLI always uses FileMusicProvider."""
    try:
        env = request_io.parse_envelope(request_path)
    except request_io.RequestError as e:
        print(f"gg_short_reel: {e}", file=sys.stderr)
        return 2
    state, failure = State(), None
    status = receipt.existing_terminal_status(env.result_path, env.correlation)
    if status is not None:                      # a finished run is never re-run over: first line of defence, touches nothing
        return _refuse(state, status)
    provider = music_provider if music_provider is not None else audio.FileMusicProvider(env.request)
    deadline = common.Deadline(timeout_s)
    try:
        with common.armed(deadline):
            pipeline(env, state, provider, deadline)
    except BaseException as e:   # noqa: BLE001 - KeyboardInterrupt/timeout/anything must still yield a receipt
        failure = e
    finally:
        if state.workdir is not None:
            shutil.rmtree(state.workdir, ignore_errors=True)

    try:
        if failure is None:
            state.stage = "receipt"
            try:
                # no-clobber link: a terminal receipt that appeared while we ran (even a moment ago) is never replaced
                status = receipt.publish_receipt(env.result_path,
                                                 receipt.success_receipt(env.correlation, env.request["outputs"]), env.correlation,
                                                 timeout_s=_lock_budget(deadline))
                if status is not None:
                    return _refuse(state, status)
                return 0
            except receipt.ReceiptLockTimeout as e:   # never fall through to a failure receipt on the very same lock
                return _lock_timeout_exit(state, e)
            except BaseException as e:   # noqa: BLE001
                failure = e
        error = describe(failure, state)
        _cleanup_work(state)
        status = receipt.existing_terminal_status(env.result_path, env.correlation)
        if status is not None:                  # someone else's receipt, and no diagnostic file beside it
            return _refuse(state, status)
        retry_safe = receipt.decide_retry_safe(state.paid_call_started)
        diagnostic = None
        if state.final is not None:
            diagnostic = state.final.with_name(state.final.name + ".FAILED.json")
            try:
                receipt.write_diagnostic(diagnostic, {"error": error, "stage": state.stage, "retry_safe": retry_safe,
                                                      "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
            except OSError as e:
                diagnostic = None
                print(f"gg_short_reel: เขียน .FAILED.json ไม่ได้: {e}", file=sys.stderr)
        status = receipt.publish_receipt(env.result_path, receipt.failure_receipt(env.correlation, error, retry_safe),
                                         env.correlation,
                                         timeout_s=_lock_budget(deadline))
        if status is not None:                  # lost the race at the last moment: theirs stands, our diagnostic goes
            if diagnostic is not None:
                _unlink_ours(diagnostic)
            return _refuse(state, status)
        _cleanup_final(state)
        print(f"gg_short_reel: FAILED {error}", file=sys.stderr)
        return 130 if isinstance(failure, KeyboardInterrupt) else 1
    except receipt.ReceiptLockTimeout as e:
        return _lock_timeout_exit(state, e)
    except BaseException as e:   # noqa: BLE001 - even the failure receipt could not be written
        print(f"gg_short_reel: เขียน receipt ไม่สำเร็จ: {type(e).__name__}: {e}", file=sys.stderr)
        return 3


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gg_short_reel.py",
                                 description="AIOS edit_short ของ G&G Short Reel: ตัดต่อคลิป AI เป็น 9:16 + ข้อความบนจอ + เสียง "
                                             "แล้วเขียน result.json เอง (success หรือ failed)")
    ap.add_argument("--request", required=True, help="absolute path ของ request.json")
    ap.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_S, help="เวลารวมสูงสุดของทั้งงาน (วินาที, default 900)")
    args = ap.parse_args(argv)
    if not args.timeout_s > 0:
        ap.error("--timeout-s ต้องมากกว่า 0")
    return run(args.request, timeout_s=args.timeout_s)


if __name__ == "__main__":
    sys.exit(main())
