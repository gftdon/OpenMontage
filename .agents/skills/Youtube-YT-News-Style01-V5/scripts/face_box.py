#!/usr/bin/env python3
"""Presenter face box measured from the avatar video itself (YT-News V4, CF-A67 W4).

Local tools only (ffmpeg, ffprobe, macOS Vision through the `swift` interpreter running scripts/face_vision.swift).
No network, no cached binary: the Swift file is interpreted on every run.

  face_box.py measure --avatar A.mp4 [--json]
      Prints the per-frame face boxes, their union, the RECOMMENDED box and a ready-to-paste
      `"avatarFaceBox": {...}` line. Put exactly that value into episode.json.
  face_box.py check   --avatar A.mp4 --episode episode.json [--report R.json]
      Compares the episode's avatarFaceBox with the measured faces.

The declared box must (1) hold >= 90 % of the face area in EVERY sampled frame, (2) be centred on the measured face
(|dx|, |dy| <= 0.045: the renderer crops the presenter card around the box CENTRE) and (3) not be oversized or tiny
(w and h at least 0.9x, and at most max(1.5x, recommended size + 0.01), of the measured face width / height). "Measured face" = the union of the presenter faces
over all sampled frames, the same union the recommended box is built from.

Exit codes: 0 = pass, 1 = fail (box misses the face / is off-centre / is the wrong size / too few faces measured /
no avatarFaceBox in the episode),
2 = usage error or unreadable input, 4 = a tool failed or the 120 s limit ran out (swift / ffmpeg / ffprobe missing,
non-zero exit, timeout). "Cannot measure" is never a pass.

Sampling is FIXED so two runs on the same file give the same numbers: N = 40 frames at
t_i = 2.0 + (duration - 4.0) * i / (N - 1), each rounded to 0.01 s. The largest detected face of a frame is the
presenter. Coordinates: fractions of the avatar frame, top-left origin.

Importable API (used by finalize):
  measure(avatar_path, tools=None, deadline=None) -> dict      (schema yt-news-v4-face-box, no volatile fields)
  check(measurement, face_box) -> dict {pass, reason, min_share, worst:{t, share}, frames_with_face, recommended, ...}
  build_report(measurement, verdict) -> dict
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SWIFT_SRC = SCRIPT_DIR / "face_vision.swift"
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
SWIFT = shutil.which("swift") or "/usr/bin/swift"

SCHEMA = "yt-news-v4-face-box"
VERSION = 1

# --- constants (measured by the lead 2026-11-12, macOS Vision VNDetectFaceRectanglesRequest, these same 40 positions) ---
N_FRAMES = 40                 # fixed sample count; a face was found in 40/40 frames of both real clips
EDGE_SECONDS = 2.0            # first / last sample sit this far from the clip ends
MIN_DURATION = 20.0           # shorter clips are a usage error (the 2 s margins + 40 samples need room)
MIN_SHARE = 0.90              # EVERY sampled frame needs >= this share of the face area inside the declared box.
#                               Clip A (647 s): boxes accepted today measure 0.967 ({.41,.11,.16,.34}) and 1.000
#                               ({.37,.12,.20,.35}); the agent's wrong guess {.39,.05,.19,.37} (chin outside) measures
#                               0.849, with 2 frames < 0.90. Clip B (336 s): {.41,.11,.16,.33} = 0.947. 0.90 sits in the
#                               narrow gap 0.849 .. 0.947 -- which is why the sample positions must never change.
MIN_FACE_FRAMES = 30          # of 40; fewer frames with a face = cannot verify = FAIL (both real clips: 40/40)
CENTRE_MAX_OFFSET = 0.045     # |box centre - measured face-union centre| <= this on x AND on y. The renderer crops the card around
#                               the box centre (YtNewsStyle01V4.tsx Avatar(): cx = (box.x + box.w/2) * mw). Card crop analysed
#                               2026-11-13: the card is 478 x 850 (lanes.avatar), the frame is scaled by 850/1080 so the card shows
#                               the FULL height (no vertical crop: the box y centre never matters) and a 0.3163-wide window of the
#                               frame width; the face union is 0.1533 (A) / 0.1566 (B) wide. The share of the face union still
#                               visible in the card is 100 % for a centre offset of +-0.045 on x (A and B, both signs), still 100 %
#                               (A) / 98.9 % (B) at +-0.0815 and < 95 % only from ~0.085. punch zoom / origin do not depend on the
#                               box (layerPlan: z, fx, fy come from episode.punch; zoom only on full-bleed beats where the box is
#                               unused, and z = 1 in the settled card state). Measured offsets (union centre; clip A x .4828 y .3066,
#                               clip B x .4853 y .3002): known-good fable-1 {.41,.11,.16,.34} on A: x +.0072 y -.0265; fable-1
#                               {.41,.11,.16,.33} on B: x +.0047 y -.0252; WP6 final {.37,.12,.20,.35} on A: x -.0128 y -.0116;
#                               recommended boxes <= .0035. Known-bad: WP6 first guess {.39,.05,.19,.37} on A: y -.0716; oversized
#                               {.38,.10,.50,.40}: x +.1472; whole frame {0,0,1,1}: y +.19..+.20. (Was 0.03: only 0.0035 slack.)
SIZE_RATIO_MIN = 0.9          # box w / measured face-union w and box h / face-union h must be >= 0.9 ...
SIZE_RATIO_MAX = 1.5          # ... and <= max(1.5 x the face-union size, recommended-box size + 0.01) per axis. The second term
#                               means the recommended box always passes its own gate (its 0.02 margin + outward rounding exceeds 1.5x
#                               for faces narrower than ~0.085 of the frame). Known-good ratios w / h: fable-1 A 1.044 / 1.134,
#                               fable-1 B 1.022 / 1.095, WP6 final 1.305 / 1.167, recommended A 1.305 / 1.167, B 1.341 / 1.190.
#                               Known-bad: oversized {.38,.10,.50,.40} w 3.26; whole frame w 6.5 / h 3.3.
SIZE_RECOMMENDED_SLACK = 0.01  # absolute slack above the recommended box size (see SIZE_RATIO_MAX)
LIMIT_EPS = 1e-9              # float noise only: a value exactly at a limit passes, it never widens a limit
RECOMMEND_MARGIN = 0.02       # recommended box = union of all faces + this on every side (clamped, rounded outward)
#                               Clip A faces: x 0.406-0.559, y 0.157-0.458; clip B: x 0.407-0.563, y 0.148-0.453.
RUN_LIMIT_SECONDS = 120.0     # whole-run limit (no `timeout` binary on macOS: every subprocess gets a timeout)
PROBE_TIMEOUT = 30.0
FRAME_TIMEOUT = 60.0          # per frame extraction (capped by the remaining run time)
VISION_TIMEOUT = 90.0         # the one swift run over all frames (capped by the remaining run time)
EPS = 1e-9                    # only used when rounding outward, so float noise never moves a 2-decimal edge


class ToolFailure(RuntimeError):
    """swift / ffmpeg / ffprobe missing, failed, or the run time limit ran out. CLI exit 4."""


class UsageError(ValueError):
    """Bad arguments or unreadable / unusable input. CLI exit 2."""


# ----------------------------------------------------------------------------------------------
# geometry (pure)
# ----------------------------------------------------------------------------------------------

def share_inside(face, box):
    """Fraction (0..1) of the face rectangle's area that lies inside `box`. Both are {x,y,w,h}."""
    fw, fh = float(face["w"]), float(face["h"])
    if not (fw > 0 and fh > 0):
        return 0.0
    ix = min(face["x"] + fw, box["x"] + box["w"]) - max(face["x"], box["x"])
    iy = min(face["y"] + fh, box["y"] + box["h"]) - max(face["y"], box["y"])
    if ix <= 0 or iy <= 0:
        return 0.0
    return (ix * iy) / (fw * fh)


def union_box(faces):
    """Smallest rectangle containing every face {x,y,w,h}; None for an empty list."""
    if not faces:
        return None
    x0 = min(f["x"] for f in faces)
    y0 = min(f["y"] for f in faces)
    x1 = max(f["x"] + f["w"] for f in faces)
    y1 = max(f["y"] + f["h"] for f in faces)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def recommend_box(union, margin=RECOMMEND_MARGIN):
    """Union expanded by `margin` on every side, clamped to [0,1], rounded OUTWARD to 2 decimals
    (floor the left / top edge, ceil the right / bottom edge) so rounding never cuts the face."""
    if union is None:
        return None
    left = max(0.0, union["x"] - margin)
    top = max(0.0, union["y"] - margin)
    right = min(1.0, union["x"] + union["w"] + margin)
    bottom = min(1.0, union["y"] + union["h"] + margin)
    xi = max(0, math.floor(left * 100 + EPS))
    yi = max(0, math.floor(top * 100 + EPS))
    ri = min(100, math.ceil(right * 100 - EPS))
    bi = min(100, math.ceil(bottom * 100 - EPS))
    return {"x": xi / 100, "y": yi / 100, "w": round((ri - xi) / 100, 2), "h": round((bi - yi) / 100, 2)}


def sample_times(duration, n=N_FRAMES):
    """The fixed sample positions: 2.0 + (duration - 4.0) * i / (n - 1), rounded to 0.01 s."""
    if not (duration >= MIN_DURATION):
        raise UsageError(f"avatar clip is {duration:.1f}s: need at least {MIN_DURATION:.0f}s")
    return [round(EDGE_SECONDS + (duration - 2 * EDGE_SECONDS) * i / (n - 1), 2) for i in range(n)]


def largest_face(faces):
    """The presenter = the largest detected face (first one on a tie). None when there is none."""
    best, best_area = None, -1.0
    for f in faces or []:
        area = float(f["w"]) * float(f["h"])
        if area > best_area:
            best, best_area = f, area
    return best


def _valid_face_box(box):
    if not isinstance(box, dict):
        return False
    for k in ("x", "y", "w", "h"):
        v = box.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            return False
    return box["x"] >= 0 and box["y"] >= 0 and 0 < box["w"] <= 1 and 0 < box["h"] <= 1


def _fmt_box(b):
    return "{" + ", ".join(f'"{k}": {b[k]:g}' for k in ("x", "y", "w", "h")) + "}"


# ----------------------------------------------------------------------------------------------
# real tools
# ----------------------------------------------------------------------------------------------

def _remaining(deadline):
    if deadline is None:
        return RUN_LIMIT_SECONDS
    left = deadline - time.monotonic()
    if left <= 0:
        raise ToolFailure(f"face_box: the {RUN_LIMIT_SECONDS:.0f}s run limit ran out. Re-run it; "
                          "if it keeps timing out the machine is overloaded: report it, do not skip the check.")
    return left


def _run(cmd, timeout, deadline):
    t = min(timeout, _remaining(deadline))
    try:
        return subprocess.run(cmd, capture_output=True, timeout=t)
    except FileNotFoundError as e:
        raise ToolFailure(f"{Path(cmd[0]).name} not found: install it (this check needs ffmpeg, ffprobe and macOS swift/Vision)") from e
    except subprocess.TimeoutExpired as e:
        raise ToolFailure(f"{Path(cmd[0]).name} timed out after {t:.0f}s") from e


def _probe_duration(path, deadline):
    r = _run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
             PROBE_TIMEOUT, deadline)
    if r.returncode != 0:
        raise UsageError(f"ffprobe cannot read {path}: {r.stderr.decode(errors='replace')[-200:].strip()}")
    try:
        d = float(r.stdout.decode().strip().splitlines()[0])
    except (ValueError, IndexError):
        raise UsageError(f"ffprobe returned no duration for {path}")
    if not math.isfinite(d):
        raise UsageError(f"ffprobe returned an unusable duration for {path}")
    return d


def _extract_frame(path, t, out, deadline):
    r = _run([FFMPEG, "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1", "-q:v", "2", str(out)],
             FRAME_TIMEOUT, deadline)
    if r.returncode != 0 or not Path(out).is_file() or Path(out).stat().st_size == 0:
        raise ToolFailure(f"ffmpeg could not extract the frame at {t:.2f}s: {r.stderr.decode(errors='replace')[-200:].strip()}")


def _detect_faces(paths, deadline):
    """ONE `swift face_vision.swift <images...>` run (interpreted, never compiled or cached). -> {path: result}."""
    if not SWIFT_SRC.is_file():
        raise ToolFailure(f"face_vision.swift missing: {SWIFT_SRC}")
    r = _run([SWIFT, str(SWIFT_SRC), *[str(p) for p in paths]], VISION_TIMEOUT, deadline)
    if r.returncode != 0:
        raise ToolFailure(f"face detection (swift/Vision) exited {r.returncode}: {r.stderr.decode(errors='replace')[-300:].strip()}")
    res = {}
    for line in r.stdout.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        res[o.get("path")] = o
    return res


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------------------------------
# measure / check
# ----------------------------------------------------------------------------------------------

def measure(avatar_path, tools=None, deadline=None):
    """Samples the fixed frames of the avatar video and finds the presenter's face in each.
    `tools` (tests) may override: duration(path, deadline) -> float, extract(path, t, out, deadline),
    detect(paths, deadline) -> {path: {"ok":bool, "faces":[{x,y,w,h}]}}.
    `deadline` is a time.monotonic() value (default: now + 120 s). Raises UsageError / ToolFailure."""
    tools = tools or {}
    avatar = Path(avatar_path)
    if not avatar.is_file():
        raise UsageError(f"avatar file not found: {avatar}")
    if deadline is None:
        deadline = time.monotonic() + RUN_LIMIT_SECONDS
    duration_fn = tools.get("duration") or _probe_duration
    extract_fn = tools.get("extract") or _extract_frame
    detect_fn = tools.get("detect") or _detect_faces

    duration = duration_fn(avatar, deadline)
    times = sample_times(duration)
    tmp = tempfile.mkdtemp(prefix="face_box_")
    try:
        paths = []
        for i, t in enumerate(times):
            out = os.path.join(tmp, f"f_{i:03d}.jpg")
            extract_fn(avatar, t, out, deadline)
            paths.append(out)
        res = detect_fn(paths, deadline)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    frames, faces_found = [], []
    for t, p in zip(times, paths):
        r = res.get(p)
        if r is None:
            raise ToolFailure(f"face detection returned no result for the frame at {t:.2f}s")
        face = largest_face(r.get("faces")) if r.get("ok") else None
        if face is not None:
            face = {k: round(float(face[k]), 4) for k in ("x", "y", "w", "h")}
            faces_found.append(face)
        frames.append({"t": t, "face": face, "faces": len(r.get("faces") or []) if r.get("ok") else 0,
                       "error": None if r.get("ok") else str(r.get("error") or "unknown")})
    if all(f["error"] is not None for f in frames):
        raise ToolFailure("face detection failed on every frame: " + str(frames[0]["error"]))
    union = union_box(faces_found)
    return {
        "schema": SCHEMA, "version": VERSION,
        "avatar_sha256": _sha256(avatar),
        "duration": round(duration, 3),
        "frame_count": len(times),
        "times": times,
        "frames": frames,
        "frames_with_face": len(faces_found),
        "union": None if union is None else {k: round(v, 4) for k, v in union.items()},
        "recommended": recommend_box(union),
    }


def _centre(b):
    return {"x": b["x"] + b["w"] / 2, "y": b["y"] + b["h"] / 2}


def _median(vals):
    v = sorted(vals)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def _r4(d):
    return None if d is None else {k: round(v, 4) for k, v in d.items()}


def check(measurement, face_box):
    """Rules (all must hold): share (>= 90 % of the face in EVERY frame), frames (>= 30 frames with a face),
    centre (box centre within 0.045 of the face-union centre on x AND y), size (box w / h >= 0.9x the face-union w / h and <= max(1.5x, recommended size + 0.01) per axis).
    `reason` = the first failed rule in this order (kept from the earlier version):
      invalid / missing box -> 'no-face-box'; too few faces -> 'too-few-faces'; share -> 'share-below-threshold';
      centre -> 'centre-off'; size -> 'size-out-of-range'.   `reasons` = one sentence per failed rule.
    -> {pass, reason, reasons, rules:{share,frames,centre,size}, min_share, worst:{t, share}|None, frames_with_face,
        recommended, face_union, centre_offset:{x,y}, size_ratio:{w,h}, variants (report only), threshold, min_face_frames,
        centre_limit, size_limits, face_box, shares, frames_below}"""
    frames = measurement["frames"]
    box_ok = _valid_face_box(face_box)
    faces = [f["face"] for f in frames if f.get("face") is not None]
    shares = []
    for f in frames:
        if f.get("face") is not None and box_ok:
            shares.append({"t": f["t"], "share": share_inside(f["face"], face_box)})
    worst = min(shares, key=lambda s: s["share"]) if shares else None
    with_face = len(faces)  # recounted, never trusted from the field
    union = union_box(faces)  # recomputed from the frames, never trusted from the field

    centre_off = size_ratio = variants = size_max = None
    if box_ok and union is not None:
        uc, bc = _centre(union), _centre(face_box)
        centre_off = {"x": bc["x"] - uc["x"], "y": bc["y"] - uc["y"]}
        size_ratio = {"w": face_box["w"] / union["w"] if union["w"] > 0 else 1e9,
                      "h": face_box["h"] / union["h"] if union["h"] > 0 else 1e9}
        rec = recommend_box(union)  # recomputed from the frames: the recommended box must always pass its own gate
        size_max = {"w": max(SIZE_RATIO_MAX * union["w"], rec["w"] + SIZE_RECOMMENDED_SLACK),
                    "h": max(SIZE_RATIO_MAX * union["h"], rec["h"] + SIZE_RECOMMENDED_SLACK)}
        # report only (not a rule): would the choice of "measured face" matter?
        mc = {"x": sum(_centre(f)["x"] for f in faces) / len(faces), "y": sum(_centre(f)["y"] for f in faces) / len(faces)}
        ms = {"w": _median([f["w"] for f in faces]), "h": _median([f["h"] for f in faces])}
        variants = {"mean_face_centre": _r4(mc), "median_face_size": _r4(ms),
                    "centre_offset_mean": _r4({"x": bc["x"] - mc["x"], "y": bc["y"] - mc["y"]}),
                    "size_ratio_median": _r4({"w": face_box["w"] / ms["w"], "h": face_box["h"] / ms["h"]})}

    r_frames = with_face >= MIN_FACE_FRAMES
    r_share = box_ok and worst is not None and worst["share"] >= MIN_SHARE
    r_centre = centre_off is not None and all(abs(centre_off[k]) <= CENTRE_MAX_OFFSET + LIMIT_EPS for k in ("x", "y"))
    r_size = size_ratio is not None and all(
        SIZE_RATIO_MIN - LIMIT_EPS <= size_ratio[k] and face_box[k] <= size_max[k] + LIMIT_EPS for k in ("w", "h"))

    reasons, codes = [], []
    if not box_ok:
        codes.append("no-face-box")
        reasons.append("episode.json has no valid avatarFaceBox {x,y,w,h} (fractions 0..1)")
    else:
        if not r_frames:
            codes.append("too-few-faces")
            reasons.append(f"frames: a face was found in only {with_face} of {len(frames)} frames "
                           f"(need {MIN_FACE_FRAMES}): the presenter cannot be verified")
        if worst is not None and not r_share:
            codes.append("share-below-threshold")
            n_below = sum(1 for s in shares if s["share"] < MIN_SHARE)
            reasons.append(f"share: {n_below} frame(s) have less than {MIN_SHARE:.0%} of the face inside avatarFaceBox "
                           f"(worst {worst['share']:.3f} at t={worst['t']:.2f}s)")
        if centre_off is not None and not r_centre:
            codes.append("centre-off")
            reasons.append(f"centre: avatarFaceBox centre is off the measured face centre by x {centre_off['x']:+.3f} / "
                           f"y {centre_off['y']:+.3f} (limit +-{CENTRE_MAX_OFFSET:g} on each axis); the presenter card is cropped "
                           "around the box centre")
        if size_ratio is not None and not r_size:
            codes.append("size-out-of-range")
            hi = {k: round(size_max[k] / union[k], 2) for k in ("w", "h")}   # upper limit expressed as a ratio, for the message
            reasons.append(f"size: avatarFaceBox w is {size_ratio['w']:.2f}x the measured face width (allowed {SIZE_RATIO_MIN:g}x to "
                           f"{hi['w']:g}x) and h is {size_ratio['h']:.2f}x the face height (allowed {SIZE_RATIO_MIN:g}x to {hi['h']:g}x)")
    ok = box_ok and r_frames and r_share and r_centre and r_size
    return {
        "pass": ok, "reason": codes[0] if codes else None, "reasons": reasons,
        "rules": {k: ("pass" if v else "fail") for k, v in (("share", r_share), ("frames", r_frames), ("centre", r_centre), ("size", r_size))},
        "min_share": None if worst is None else round(worst["share"], 4),
        "worst": None if worst is None else {"t": worst["t"], "share": round(worst["share"], 4)},
        "frames_below": sum(1 for s in shares if s["share"] < MIN_SHARE),
        "frames_with_face": with_face,
        "recommended": measurement["recommended"],
        "face_union": _r4(union),
        "centre_offset": _r4(centre_off),
        "size_ratio": _r4(size_ratio),
        "variants": variants,
        "threshold": MIN_SHARE, "min_face_frames": MIN_FACE_FRAMES,
        "centre_limit": CENTRE_MAX_OFFSET, "size_limits": {"min": SIZE_RATIO_MIN, "max": SIZE_RATIO_MAX, "max_size": _r4(size_max)},
        "face_box": face_box if box_ok else None,
        "shares": [{"t": s["t"], "share": round(s["share"], 4)} for s in shares],
    }


def build_report(measurement, verdict):
    """The JSON report: schema, avatar sha256, frame times, per-frame boxes and the verdict."""
    return {"schema": SCHEMA, "version": VERSION, "avatar_sha256": measurement["avatar_sha256"],
            "times": measurement["times"], "frames": measurement["frames"],
            "union": measurement["union"], "recommended": measurement["recommended"], "verdict": verdict}


# ----------------------------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------------------------

def _recommend_lines(m):
    rec = m["recommended"]
    if rec is None:
        return ["recommended box: none (no face found in any frame)"]
    return [f"recommended box: put exactly this in episode.json:", f'"avatarFaceBox": {_fmt_box(rec)}']


def _print_measure(m):
    print(f"avatar sha256 {m['avatar_sha256']}  duration {m['duration']}s  {m['frame_count']} frames, face in {m['frames_with_face']}")
    for f in m["frames"]:
        if f["face"]:
            b = f["face"]
            print(f"  t={f['t']:8.2f}  x={b['x']:.4f} y={b['y']:.4f} w={b['w']:.4f} h={b['h']:.4f}  ({f['faces']} face(s))")
        else:
            print(f"  t={f['t']:8.2f}  NO FACE" + (f"  ({f['error']})" if f["error"] else ""))
    if m["union"]:
        u = m["union"]
        print(f"union of faces: x={u['x']:.4f} y={u['y']:.4f} w={u['w']:.4f} h={u['h']:.4f}")
    for line in _recommend_lines(m):
        print(line)


def _cmd_measure(args):
    m = measure(args.avatar)
    if args.json:
        print(json.dumps(m, indent=2, sort_keys=True))
    else:
        _print_measure(m)
    return 0


def _read_episode_box(path):
    p = Path(path)
    if not p.is_file():
        raise UsageError(f"episode file not found: {p}")
    try:
        ep = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise UsageError(f"episode file is not readable JSON: {p} ({e})")
    if not isinstance(ep, dict):
        raise UsageError(f"episode file is not a JSON object: {p}")
    return ep.get("avatarFaceBox")


def _cmd_check(args):
    box = _read_episode_box(args.episode)
    m = measure(args.avatar)
    v = check(m, box)
    if args.report:
        Path(args.report).write_text(json.dumps(build_report(m, v), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if v["pass"]:
        print(f"face-box PASS: min share {v['min_share']:.3f} (>= {MIN_SHARE}) over {m['frame_count']} frames, "
              f"face found in {v['frames_with_face']}; centre offset x {v['centre_offset']['x']:+.3f} / y {v['centre_offset']['y']:+.3f} "
              f"(limit +-{CENTRE_MAX_OFFSET:g}); size {v['size_ratio']['w']:.2f}x / {v['size_ratio']['h']:.2f}x "
              f"(min {SIZE_RATIO_MIN:g}x, max {SIZE_RATIO_MAX:g}x or recommended size + {SIZE_RECOMMENDED_SLACK:g})")
        return 0
    # first line stays "face-box FAIL: <first failed rule>" (finalize shows it); every further failed rule gets its own line
    print(f"face-box FAIL: {v['reasons'][0]}")
    for extra in v["reasons"][1:]:
        print(f"  also: {extra}")
    if v["worst"]:
        print(f"worst frame: t={v['worst']['t']:.2f}s, {v['worst']['share']:.3f} of the face inside the box")
    for line in _recommend_lines(m):
        print(line)
    print("fix: replace avatarFaceBox in episode.json with the recommended value above (exactly), then re-run this check.")
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Measure / check the presenter face box (YT-News V4)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pm = sub.add_parser("measure", help="print per-frame faces, union and the recommended avatarFaceBox")
    pm.add_argument("--avatar", required=True)
    pm.add_argument("--json", action="store_true")
    pc = sub.add_parser("check", help="check episode.json avatarFaceBox against the measured faces")
    pc.add_argument("--avatar", required=True)
    pc.add_argument("--episode", required=True)
    pc.add_argument("--report")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    try:
        return _cmd_measure(args) if args.cmd == "measure" else _cmd_check(args)
    except UsageError as e:
        print(f"face_box: {e}", file=sys.stderr)
        return 2
    except ToolFailure as e:
        print(f"face_box: TOOL FAILURE: {e}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
