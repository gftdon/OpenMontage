#!/usr/bin/env python3
"""Pixel / watermark / crop / shot-reuse checks on every cutaway (YT-News V4, WP2b).

Local tools only (ffmpeg, numpy, PIL, macOS Vision through scripts/ocr_vision.swift). No network.

  frame_checks.py pixels       --video V --in A --out B [--crop x:y:w:h]
  frame_checks.py watermark    --video V --in A --out B [--crop x:y:w:h] --frames-dir D
  frame_checks.py cutaways     --beats beats.json [--cuts _cuts.json] --media-root DIR [--media-root DIR ...]
                               --frames-dir D --report R.json [--episode-end SEC]
  frame_checks.py crop-propose --video V --in A --out B
  frame_checks.py crop-check   --video V --in A --out B --crop x:y:w:h

Exit codes: 0 = pass, 1 = issues found, 2 = bad input, 4 = a required tool (ffmpeg / swift+Vision) cannot run.
OCR is never skipped silently: when Vision OCR cannot run the command exits 4.  The OCR program is compiled into a fresh private
temp directory on every run (or interpreted with `swift`) and never taken from a cache: there is no --cache-dir (see VisionOcr).

Coordinates: every crop (--crop, beat `srcCrop`, `crop-propose` output) is in pixels of a 1920x1080 source
frame and is scaled to the real file resolution when the file differs.

Blank-frame rule: a sampled frame is low-information when the fraction of pixels whose luma differs from the
frame's MEDIAN luma by more than infoDelta is below infoMinFraction. Dark-theme screen recordings are NOT
blank (a few bright UI pixels are enough). Subtype in the detail: white (median > 200), black (median < 40), flat.
A run needs at least two consecutive low-information samples (first-to-last span >= run_min_seconds), so a
single-sample flash is never reported; a range shorter than the run minimum is reported only when all of it is blank.

V4 playback semantics (episode_schema.mjs S09-S11): `from` is the offset inside the public cut file; stock loops
restart at `from` with loop length floor((brollDur - from) * 25) - 2 frames, so only [from, from + loop length] is
ever shown. Clip length / looping against the DECLARED brollDur is the schema's rule S09 (a source clip that would
loop or freeze is an S09 error, reported by lint_content as code `schema`); this file only reports what the schema
cannot see, i.e. the same checks against the REAL file on disk: `source-loop` (source beat longer than the file
allows), `from-out-of-range` (`from` leaves nothing of the real file) and `broll-dur-mismatch`. They are skipped
for a clip whose declared brollDur matches the file within one frame (the schema owns it then).

blank-frame on a source clip beat (cutaways) is measured frame by frame on the visible region: a blank picture lasting >= 1.0 s
(`blank_error_seconds`, locked by lead 2026-11-12) is an ERROR naming the beat, the clip and the blank range inside the clip file; a shorter one
(>= `run_min_seconds`) stays a warning. Stock / ai blank-frame stays an error as before.

static-hold (cutaways, error): source video clips (media `clip`, origin `source`) are sampled over their whole shown range
(`static_sample_fps` per second) in the part the viewer really sees (episode_data.visible_region: srcCrop cover-fitted into the stage /
wide picture box) and hashed (dHash). A stretch of samples whose hash stays within `reuse_max_distance` of the stretch's first sample
continues across consecutive pip clip beats (also across files) and is reset by a presenter (`full`), typo, stock / ai beat, a
layout change or a visible change. Longer than `maxHoldSeconds` (qc_thresholds.json; missing file or key = tool missing, exit 4) ->
one `static-hold` error per stretch. A beat whose visible region cannot be computed is `static-hold-region-unknown` (error), never
skipped. The report carries `staticHold.runs` with the longest static stretch of every run of consecutive clip beats.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import weakref
from pathlib import Path

import numpy as np

THRESHOLDS = {
    # blank-frame rule
    "sample_fps": 2.0,
    "infoDelta": 40,                # a pixel is "information" when |luma - frame median| exceeds this ...
    "infoMinFraction": 0.02,        # ... and a frame is blank when fewer than this fraction of pixels are
    "whiteMedian": 200,             # subtype: median above this = white
    "blackMedian": 40,              # subtype: median below this = black, otherwise flat
    "run_min_seconds": 0.5,         # a run must span at least this long
    "sample_size": (160, 90),       # frames are area-downscaled to this before the stats
    # OCR
    "ocr_min_frames": 5,            # frames per range = max(ocr_min_frames, ceil(duration / ocr_seconds_per_frame))
    "ocr_seconds_per_frame": 1.0,
    "ocr_max_width": 1920,
    "watermark_regex": r"pixabay|shutterstock|getty|istock|envato|storyblocks|pexels|videvo|adobe\s*stock|dreamstime|pond5|watermark",
    "promo_regex": r"subscribe|sponsor(ed)?",
    # shot reuse (hash of the CONTENT box)
    "reuse_max_distance": 6,        # dHash (64 bit) Hamming distance
    "reuse_window_seconds": 60.0,   # beats whose start times are closer than this are compared
    "reuse_flat_std": 4.0,          # evidence frames flatter than this (luma std) are not compared (all-black == all-black)
    "reuse_box_min_confidence": 0.7,  # crop-propose boxes below this confidence are ignored
    "reuse_box_max_area": 0.97,     # ... and so are boxes that are not smaller than this fraction of the frame
    # crop (S11)
    "crop_aspect": 16 / 9,
    "crop_aspect_error": 0.25,
    "crop_aspect_warning": 0.10,
    "crop_min_width": 640,          # 1920-space pixels
    "crop_samples": 24,
    "crop_work_width": 960,
    "crop_dark_mean": 18,
    "crop_static_tstd": 2.0,
    "crop_dark_tstd": 3.0,
    "crop_uniform_vstd": 10.0,
    "crop_max_bar_fraction": 0.4,   # more than this per side is not a bar, it is content
    # blank-frame on SOURCE clips: a low-information picture that lasts at least this long (continuously, measured frame by frame on the
    # visible region) is an error, a shorter one stays a warning. locked by lead 2026-11-12
    "blank_error_seconds": 1.0,
    # static-hold (maxHoldSeconds itself comes from qc_thresholds.json, never from here)
    "static_sample_fps": 4.0,       # samples per second of shown time (>= 1; a stretch is measured first sample -> last sample)
    "static_work_size": (160, 90),  # the visible region is area-downscaled to this before the dHash
    # engine
    "engine_fps": 25,
}
QC_THRESHOLDS_PATH = Path(__file__).resolve().parent / "qc_thresholds.json"
REF_W, REF_H = 1920, 1080

SCRIPT_DIR = Path(__file__).resolve().parent
SWIFT_SRC = SCRIPT_DIR / "ocr_vision.swift"
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
SCHEMA = "yt-news-v4-frame-checks"
VERSION = 2


class ToolMissing(RuntimeError):
    """A required local tool (ffmpeg, swift / Vision) cannot run. CLI exit 4."""


class BadInput(ValueError):
    """Unusable arguments or input files. CLI exit 2."""


# ----------------------------------------------------------------------------------------------
# ffmpeg helpers
# ----------------------------------------------------------------------------------------------

def _run(cmd, timeout=600):
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout)
    except FileNotFoundError as e:
        raise ToolMissing(f"{cmd[0]} not found") from e
    except subprocess.TimeoutExpired as e:
        raise ToolMissing(f"{cmd[0]} timed out after {timeout}s") from e


def probe(video):
    """-> (duration seconds, width, height) of the first video stream."""
    if not Path(video).is_file():
        raise BadInput(f"video not found: {video}")
    r = _run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
              "stream=width,height:format=duration", "-of", "json", str(video)], 60)
    if r.returncode != 0:
        raise BadInput(f"ffprobe failed on {video}: {r.stderr.decode(errors='replace')[-200:]}")
    j = json.loads(r.stdout or b"{}")
    try:
        st = j["streams"][0]
        return float(j["format"]["duration"]), int(st["width"]), int(st["height"])
    except (KeyError, IndexError, ValueError, TypeError) as e:
        raise BadInput(f"cannot read stream info of {video}") from e


def parse_crop(s):
    if s is None:
        return None
    if isinstance(s, (list, tuple)):
        parts = list(s)
    elif isinstance(s, dict):
        parts = [s.get(k) for k in "xywh"]
    else:
        parts = str(s).split(":")
    try:
        x, y, w, h = [int(round(float(p))) for p in parts]
    except (TypeError, ValueError) as e:
        raise BadInput(f"bad crop {s!r}; expected x:y:w:h") from e
    if len(parts) != 4 or w <= 0 or h <= 0 or x < 0 or y < 0:
        raise BadInput(f"bad crop {s!r}; expected x:y:w:h with positive w/h")
    return (x, y, w, h)


def _crop_vf(crop):
    return [f"crop={crop[2]}:{crop[3]}:{crop[0]}:{crop[1]}"] if crop else []


def decode_gray(video, a, b, vf, w, h, fps, fps_expr=None):
    """Decode [a, b) of `video` to an (n, h, w) uint8 array of FULL-RANGE luma, sampled with the fps filter."""
    vf = list(vf) + [f"fps={fps_expr or fps}", f"scale={w}:{h}:flags=area:out_range=full", "format=gray"]
    cmd = [FFMPEG, "-v", "error", "-ss", f"{a:.3f}", "-t", f"{max(b - a, 0.04):.3f}", "-i", str(video),
           "-an", "-sn", "-vf", ",".join(vf), "-f", "rawvideo", "-"]
    r = _run(cmd)
    if r.returncode != 0:
        raise BadInput(f"ffmpeg failed on {video}: {r.stderr.decode(errors='replace')[-300:]}")
    buf = np.frombuffer(r.stdout, dtype=np.uint8)
    n = buf.size // (w * h)
    return buf[: n * w * h].reshape(n, h, w)


def scale_crop(crop, fw, fh):
    """1920x1080-space crop -> pixels of a fw x fh file (integers, even size, inside the frame)."""
    if crop is None:
        return None
    x, y, w, h = crop
    sx, sy = fw / REF_W, fh / REF_H
    px, py = int(round(x * sx)), int(round(y * sy))
    pw, ph = int(round(w * sx)), int(round(h * sy))
    px, py = max(0, min(px, fw - 2)), max(0, min(py, fh - 2))
    pw, ph = max(2, min(pw, fw - px)), max(2, min(ph, fh - py))
    return (px, py, pw - pw % 2, ph - ph % 2)


def luma_stats(arr, a, fps):
    """(n, h, w) uint8 luma frames -> per-frame stats [{t, mean, median, info}] (t = a + i / fps)."""
    T = THRESHOLDS
    stats = []
    for i in range(arr.shape[0]):
        f = arr[i].astype(np.float32)
        med = float(np.median(f))
        stats.append({"t": round(a + i / fps, 3), "mean": float(f.mean()), "median": med,
                      "info": float((np.abs(f - med) > T["infoDelta"]).mean())})
    return stats


def luma_samples(video, a, b, crop_px=None):
    """-> per-sample stats [{t, mean, median, info}] for [a, b]. crop_px is in FILE pixels.
    info = fraction of pixels whose luma differs from the frame median by more than infoDelta."""
    T = THRESHOLDS
    fps = T["sample_fps"]
    w, h = T["sample_size"]
    return luma_stats(decode_gray(video, a, b, _crop_vf(crop_px), w, h, fps), a, fps)


def _runs(flags, times, a, b, fps, min_span):
    out, i, n = [], 0, len(flags)
    while i < n:
        if not flags[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and flags[j + 1]:
            j += 1
        span = times[j] - times[i]
        whole = i == 0 and j == n - 1
        if span >= min_span - 1e-9 or (whole and (b - a) >= min_span - 1e-9):
            out.append((i, j, times[i], min(b, times[j] + 1.0 / fps)))
        i = j + 1
    return out


def pixel_issues(stats, a, b):
    """blank-frame runs from luma samples -> list of issue dicts (code, range, detail)."""
    T = THRESHOLDS
    fps = T["sample_fps"]
    times = [s["t"] for s in stats]
    flags = [s["info"] < T["infoMinFraction"] for s in stats]
    issues = []
    for i, j, t0, t1 in _runs(flags, times, a, b, fps, T["run_min_seconds"]):
        sel = stats[i:j + 1]
        med = float(np.mean([s["median"] for s in sel]))
        sub = "white" if med > T["whiteMedian"] else "black" if med < T["blackMedian"] else "flat"
        issues.append({"code": "blank-frame", "range": [round(t0, 3), round(t1, 3)],
                       "detail": f"{sub}: {len(sel)} low-information samples (< {T['infoMinFraction']:.0%} of pixels differ from the "
                                 f"median luma by > {T['infoDelta']}); median luma {med:.0f}, "
                                 f"info fraction max {max(s['info'] for s in sel):.4f}"})
    return issues


def luma_summary(stats):
    T = THRESHOLDS
    if not stats:
        return {"n": 0}
    m = [s["mean"] for s in stats]
    inf = [s["info"] for s in stats]
    return {"n": len(stats), "mean": round(float(np.mean(m)), 1), "min_mean": round(min(m), 1), "max_mean": round(max(m), 1),
            "infoFraction": {"min": round(min(inf), 4), "median": round(float(np.median(inf)), 4)},
            "blank_samples": sum(1 for x in inf if x < T["infoMinFraction"])}


def check_pixels(video, a, b, crop=None):
    """Pixel check of one range; crop in 1920x1080 space. -> {"issues": [...], "luma": {...}, "samples": n}"""
    _, fw, fh = probe(video)
    stats = luma_samples(video, a, b, scale_crop(crop, fw, fh))
    issues = pixel_issues(stats, a, b)
    if not stats:
        issues.append({"code": "no-frames", "range": [round(a, 3), round(b, 3)],
                       "detail": "ffmpeg decoded no frames in the range"})
    return {"issues": issues, "luma": luma_summary(stats), "samples": len(stats)}


# ----------------------------------------------------------------------------------------------
# evidence frames, hashes
# ----------------------------------------------------------------------------------------------

def ocr_frame_times(a, b):
    T = THRESHOLDS
    n = max(T["ocr_min_frames"], math.ceil((b - a) / T["ocr_seconds_per_frame"] - 1e-9))
    return [round(a + (i + 0.5) * (b - a) / n, 3) for i in range(n)]


def extract_frame(video, t, out, crop=None):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = _crop_vf(crop) + [f"scale='min({THRESHOLDS['ocr_max_width']},iw)':-2"]
    last = ""
    for tt in (t, max(t - 0.15, 0.0)):   # the very last frame of a file can be unreachable
        cmd = [FFMPEG, "-v", "error", "-y", "-ss", f"{tt:.3f}", "-i", str(video), "-an", "-sn",
               "-frames:v", "1", "-vf", ",".join(vf), "-q:v", "2", str(out)]
        r = _run(cmd, 120)
        last = r.stderr.decode(errors="replace")[-200:]
        if r.returncode == 0 and out.is_file() and out.stat().st_size > 0:
            return True
    return False


def dhash(path, box=None):
    """-> (hex dHash (64 bit) of the content box, flat?). `box` is x,y,w,h in 1920x1080 space (scaled to the
    image); None = the whole image."""
    from PIL import Image
    with Image.open(path) as im:
        g = im.convert("L")
        if box:
            sx, sy = g.width / REF_W, g.height / REF_H
            x0, y0 = int(round(box[0] * sx)), int(round(box[1] * sy))
            x1, y1 = min(g.width, x0 + int(round(box[2] * sx))), min(g.height, y0 + int(round(box[3] * sy)))
            if x1 - x0 >= 8 and y1 - y0 >= 8:
                g = g.crop((x0, y0, x1, y1))
        return _dhash_image(g)


def _dhash_image(g):
    """-> (hex dHash (64 bit), flat?) of a PIL grayscale image."""
    from PIL import Image
    small = np.asarray(g.resize((9, 8), Image.LANCZOS), dtype=np.int16)
    flat = float(np.asarray(g.resize((16, 16), Image.BILINEAR), dtype=np.float32).std()) < THRESHOLDS["reuse_flat_std"]
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    v = 0
    for bit in bits:
        v = (v << 1) | int(bit)
    return f"{v:016x}", flat


def dhash_gray(arr):
    """dHash of a decoded (h, w) uint8 luma array -> (hex, flat?). Same hash as dhash() gives for the same picture."""
    from PIL import Image
    return _dhash_image(Image.fromarray(arr, mode="L"))


def hamming(h1, h2):
    return bin(int(h1, 16) ^ int(h2, 16)).count("1")


# ----------------------------------------------------------------------------------------------
# static-hold (picture that hardly changes)
# ----------------------------------------------------------------------------------------------

def load_max_hold(path=None):
    """maxHoldSeconds from qc_thresholds.json. Missing / unreadable file or key = ToolMissing (exit 4): never a default."""
    p = Path(path or QC_THRESHOLDS_PATH)
    try:
        v = json.loads(p.read_text(encoding="utf-8"))["maxHoldSeconds"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ToolMissing(f"cannot read maxHoldSeconds from {p}: {e}") from e
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
        raise ToolMissing(f"maxHoldSeconds in {p} must be a positive number, got {v!r}")
    return float(v)


def is_clip_source(beat):
    """Beats that are measured: source VIDEO clips in the picture box (not presenter, typo, stock or ai)."""
    return beat.get("mode") != "full" and beat.get("media") == "clip" and beat.get("origin") == "source"


def region_px(region, fw, fh):
    """visible_region() floats -> integer crop (x, y, w, h) inside a fw x fh file."""
    x, y, w, h = region
    x0, y0 = max(0, min(int(round(x)), fw - 2)), max(0, min(int(round(y)), fh - 2))
    return (x0, y0, max(2, min(int(round(w)), fw - x0)), max(2, min(int(round(h)), fh - y0)))


def decode_region(path, a, b, region):
    """Every frame (at the engine fps) of the visible region of [a, b] -> (n, h, w) uint8 luma, frame i at a + i / engine_fps."""
    w, h = THRESHOLDS["static_work_size"]
    return decode_gray(path, a, b, _crop_vf(region), w, h, THRESHOLDS["engine_fps"])


def samples_from_frames(arr, a):
    """dHash samples (`static_sample_fps` per second, plus the last frame shown) from the frames of decode_region.
    -> [{"local": file second, "dhash": hex, "flat": bool}]"""
    T = THRESHOLDS
    fps = T["engine_fps"]
    n = arr.shape[0]
    idx, m = [], 0
    while n and round(m * fps / T["static_sample_fps"]) < n:
        idx.append(round(m * fps / T["static_sample_fps"]))
        m += 1
    if n and idx[-1] != n - 1:          # a stretch is measured up to the last frame of the beat, not only to the last grid sample
        idx.append(n - 1)
    out = []
    for i in idx:
        d, flat = dhash_gray(arr[i])
        out.append({"local": round(a + i / fps, 3), "dhash": d, "flat": flat})
    return out


def static_samples(path, a, b, region):
    """dHash samples of the visible region of [a, b] (file seconds). -> [{"local", "dhash", "flat"}]"""
    return samples_from_frames(decode_region(path, a, b, region), a)


def dense_blank_issues(stats, a, b, src, beat_t):
    """blank-frame runs of a SOURCE clip beat from per-frame stats of its visible region (see decode_region / luma_stats).
    A run of low-information frames lasting >= blank_error_seconds is an ERROR, a shorter run (>= run_min_seconds) a warning; the
    detail names the beat, the clip and the blank range INSIDE THE CLIP FILE so `from` can be moved past it."""
    T = THRESHOLDS
    fps = T["engine_fps"]
    flags = [s_["info"] < T["infoMinFraction"] for s_ in stats]
    issues, i, n = [], 0, len(flags)
    while i < n:
        if not flags[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and flags[j + 1]:
            j += 1
        t0, t1 = stats[i]["t"], min(b, round(stats[j]["t"] + 1.0 / fps, 3))
        dur = (j - i + 1) / fps
        i = j + 1
        if dur < T["run_min_seconds"] - 1e-9 and not (t0 <= a + 1e-9 and t1 >= b - 1e-9):
            continue
        sel = [s_ for s_ in stats if t0 - 1e-9 <= s_["t"] < t1 - 1e-9]
        med = float(np.mean([s_["median"] for s_ in sel]))
        sub = "white" if med > T["whiteMedian"] else "black" if med < T["blackMedian"] else "flat"
        err = dur >= T["blank_error_seconds"] - 1e-9
        issues.append({"code": "blank-frame", "severity": "error" if err else "warn", "range": [round(t0, 3), round(t1, 3)], "duration": round(dur, 3),
                       "detail": f"beat t={beat_t:g} clip {src}: blank picture ({sub}) for {dur:.2f}s from {t0:.2f}s to {t1:.2f}s inside the clip file "
                                 f"(visible region; median luma {med:.0f}, info fraction max {max(s_['info'] for s_ in sel):.4f}); "
                                 + (f"an error from {T['blank_error_seconds']:g}s: move `from` past {t1:.2f}s" if err else
                                    f"a warning below {T['blank_error_seconds']:g}s")})
    return issues


def same_picture(h0, flat0, h1, flat1):
    """No visible change = dHash distance <= reuse_max_distance (the shot-reuse threshold). Two flat frames are the same picture."""
    if flat0 and flat1:
        return True
    return hamming(h0, h1) <= THRESHOLDS["reuse_max_distance"]


def static_timeline(beats, statics, max_hold):
    """Accumulate the on-screen timeline.
    beats: the episode beats (with t, end, layout, src, ...); statics: {beat index: {"samples": [...], "from": file second of the first
    shown frame} | {"error": text}} for the measured clip beats. -> (issues, runs)

    A stretch starts at a sample and continues while later samples stay within the hash threshold of ITS FIRST sample. It spans
    consecutive pip clip beats (any file) and is closed by a non-clip beat, a layout change, a beat without samples or a visible
    change. runs: one entry per run of consecutive clip beats with the longest stretch (start, end, duration, srcs)."""
    issues, runs = [], []
    state = {"run": None, "st": None}

    def close_stretch():
        st = state["st"]
        state["st"] = None
        if st is None:
            return
        dur = st["last"] - st["first"]
        run = st["run"]
        if dur > run["_best"] + 1e-9 or run["longestStatic"] is None:
            run["_best"] = dur
            run["longestStatic"] = {"start": round(st["first"], 3), "end": round(st["last"], 3), "duration": round(dur, 3), "srcs": st["srcs"],
                                    "beat_t": st["beat_t"]}
        if dur > max_hold + 1e-9:
            issues.append({"code": "static-hold", "severity": "error", "beat_t": st["beat_t"], "src": st["srcs"][0], "origin": "source",
                           "srcs": st["srcs"], "range": [round(st["first"], 3), round(st["last"], 3)], "duration": round(dur, 3),
                           "detail": f"the visible picture hardly changes for {dur:.2f}s (from t={st['first']:.2f}s to t={st['last']:.2f}s, "
                                     f"src {', '.join(st['srcs'])}); maximum {max_hold:g}s (dHash distance <= {THRESHOLDS['reuse_max_distance']} "
                                     f"to the first sample of the stretch)"})

    def close_run():
        close_stretch()
        run = state["run"]
        state["run"] = None
        if run is not None:
            run.pop("_best")
            runs.append(run)

    for i, b in enumerate(beats):
        if not is_clip_source(b):
            close_run()
            continue
        if state["run"] is None:
            state["run"] = {"start": b["t"], "beats": [], "longestStatic": None, "_best": -1.0}
        state["run"]["beats"].append(b["t"])
        info = statics.get(i)
        if not info or "samples" not in info:
            close_stretch()
            continue
        st = state["st"]
        if st is not None and st["layout"] != b.get("layout"):
            close_stretch()
        for smp in info["samples"]:
            at = b["t"] + (smp["local"] - info["from"])
            st = state["st"]
            if st is not None and same_picture(st["h0"], st["flat0"], smp["dhash"], smp["flat"]):
                st["last"] = at
                if b.get("src") not in st["srcs"]:
                    st["srcs"].append(b.get("src"))
                continue
            close_stretch()
            state["st"] = {"first": at, "last": at, "h0": smp["dhash"], "flat0": smp["flat"], "srcs": [b.get("src")], "beat_t": b["t"],
                           "layout": b.get("layout"), "run": state["run"]}
    close_run()
    return issues, runs


# ----------------------------------------------------------------------------------------------
# OCR (macOS Vision via ocr_vision.swift)
# ----------------------------------------------------------------------------------------------

class VisionOcr:
    """Runs ocr_vision.swift on a batch of images in ONE process.

    No executable is EVER taken from a cache or from any directory another process could have written to before this runner
    existed (CF-A67: an unattended agent can plant a fake `ocr_vision-<hash>` binary in a project cache directory).  The first call
    compiles ocr_vision.swift with `swiftc -O` into a NEW private temp directory (tempfile.mkdtemp: random name, mode 0700), the
    binary is used by this runner only, and close() (also called by main(), and by a finalizer when the runner is garbage-collected)
    deletes the directory.  Without swiftc, or when the compile fails, the source is interpreted with `swift`.
    Measured on the proof run V261111_001 (395 cutaway frames, 2026-11-13, same OCR lines for every frame): compile 1.2 s + run
    34.5 s = 35.7 s; interpreted 45.3 s.  Raises ToolMissing when neither works."""

    def __init__(self, swift_src=None):
        self.src = Path(swift_src or SWIFT_SRC)
        self.mode = None            # "compiled-fresh" | "interpreted"
        self.compile_seconds = 0.0
        self.run_seconds = 0.0
        self.invocations = 0
        self.build_dir = None       # the private temp dir of THIS runner (deleted by close())
        self._cmd = None
        self._finalizer = None

    def _prepare(self):
        if self._cmd is not None:
            return
        if not self.src.is_file():
            raise ToolMissing(f"OCR source missing: {self.src}")
        swiftc, swift = shutil.which("swiftc"), shutil.which("swift")
        if swiftc:
            build = Path(tempfile.mkdtemp(prefix="ocr-vision-build-"))       # 0700, random name: never a shared / predictable path
            self.build_dir = build
            self._finalizer = weakref.finalize(self, shutil.rmtree, str(build), True)
            binary = build / "ocr_vision"
            t0 = time.time()
            try:
                r = subprocess.run([swiftc, "-O", str(self.src), "-o", str(binary)], capture_output=True, timeout=600)
            except subprocess.TimeoutExpired:
                r = None
            self.compile_seconds = time.time() - t0
            if r is not None and r.returncode == 0 and binary.is_file() and os.access(binary, os.X_OK):
                self.mode, self._cmd = "compiled-fresh", [str(binary)]
                return
            self.close()
        if swift:
            self.mode, self._cmd = "interpreted", [swift, str(self.src)]
            return
        raise ToolMissing("swift / swiftc not found: macOS Vision OCR cannot run")

    def close(self):
        """Delete the private build directory (idempotent).  A closed compiled runner compiles again on its next call."""
        if self._finalizer is not None:
            self._finalizer()
            self._finalizer = None
        if self.mode == "compiled-fresh":
            self._cmd = None
        self.build_dir = None

    def __call__(self, paths):
        paths = [str(p) for p in paths]
        if not paths:
            return {}
        self._prepare()
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write("\n".join(paths) + "\n")
            listfile = fh.name
        try:
            t0 = time.time()
            r = _run(self._cmd + ["--list", listfile], 1800)
            self.run_seconds += time.time() - t0
            self.invocations += 1
        finally:
            os.unlink(listfile)
        if r.returncode != 0:
            raise ToolMissing(f"OCR ({self.mode}) exited {r.returncode}: {r.stderr.decode(errors='replace')[-300:]}")
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
        missing = [p for p in paths if p not in res]
        if missing:
            raise ToolMissing(f"OCR returned no result for {len(missing)} of {len(paths)} frames")
        return res


def run_ocr(runner, paths):
    """Batch-OCR `paths`. -> {path: {"ok": bool, "lines": [...]|"error": str}}. All frames in ONE runner call.
    Raises ToolMissing when the runner fails or when every frame failed (Vision unusable)."""
    paths = list(dict.fromkeys(str(p) for p in paths))
    if not paths:
        return {}
    res = runner(paths)
    for p in paths:
        if p not in res:
            raise ToolMissing(f"OCR runner returned no result for {p}")
    if all(not res[p].get("ok") for p in paths):
        raise ToolMissing("OCR failed on every frame: " + str(res[paths[0]].get("error")))
    return {p: res[p] for p in paths}


def text_issues(frames_ocr):
    """frames_ocr: [{"t":..., "ocr":[lines]}] -> list of issue dicts (watermark / promo-text) for ONE range."""
    T = THRESHOLDS
    wm, promo = re.compile(T["watermark_regex"], re.I), re.compile(T["promo_regex"], re.I)
    issues = []
    for code, rx in (("watermark", wm), ("promo-text", promo)):
        hits = []
        for f in frames_ocr:
            for line in f.get("ocr") or []:
                m = rx.search(line)
                if m:
                    hits.append((f["t"], m.group(0), line))
                    break
        if hits:
            ts = [h[0] for h in hits]
            issues.append({"code": code, "range": [min(ts), max(ts)],
                           "detail": f"matched {sorted({h[1].lower() for h in hits})} in {len(hits)} of {len(frames_ocr)} OCR frames; "
                                     f"first at t={hits[0][0]}s: {hits[0][2]!r}"})
    return issues


# ----------------------------------------------------------------------------------------------
# single-range commands
# ----------------------------------------------------------------------------------------------

def _prefix_for(video):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(video).stem)[:60]


def collect_frames(video, a, b, crop, frames_dir, prefix):
    """Extract the OCR evidence frames of a range. -> ([{path,t}], [failed t])"""
    out, failed = [], []
    for t in ocr_frame_times(a, b):
        p = Path(frames_dir) / f"{prefix}_{int(round(t * 1000)):08d}.jpg"
        if extract_frame(video, t, p, crop):
            out.append({"path": str(p), "t": t})
        else:
            failed.append(t)
    return out, failed


def ocr_frames(runner, frames):
    """Fill frames[*]['ocr'] (+ dhash) in place with ONE batched OCR call. -> list of ocr-failed issues."""
    res = run_ocr(runner, [f["path"] for f in frames])
    problems = []
    for f in frames:
        r = res[f["path"]]
        if r.get("ok"):
            f["ocr"] = list(r.get("lines") or [])
        else:
            f["ocr"] = []
            problems.append({"code": "ocr-failed", "range": [f["t"], f["t"]],
                             "detail": f"OCR could not read the frame at t={f['t']}s: {r.get('error')}"})
        f["dhash"], f["flat"] = dhash(f["path"])
    return problems


def cmd_pixels(video, a, b, crop=None, origin="stock"):
    _check_range(video, a, b)
    r = check_pixels(video, a, b, crop)   # crop: 1920x1080 space
    beat = {"origin": origin}
    issues = [{**i, "severity": severity_for(i["code"], beat)} for i in r["issues"]]
    counts = count_issues(issues)
    return {"schema": SCHEMA, "version": VERSION, "command": "pixels", "video": str(video), "range": [a, b], "origin": origin,
            "crop": crop, "pass": counts["error"] == 0, "counts": counts, "issues": issues, "luma": r["luma"]}


def cmd_watermark(video, a, b, crop, frames_dir, runner):
    _check_range(video, a, b)
    _, fw, fh = probe(video)
    frames, failed = collect_frames(video, a, b, scale_crop(crop, fw, fh), frames_dir, _prefix_for(video))
    issues = [{"code": "frame-missing", "range": [t, t], "detail": f"could not extract a frame at t={t}s"} for t in failed]
    issues += ocr_frames(runner, frames)
    issues += text_issues(frames)
    issues = [{**i, "severity": "error"} for i in issues]
    return {"schema": SCHEMA, "version": VERSION, "command": "watermark", "video": str(video), "range": [a, b],
            "crop": crop, "pass": not issues, "counts": count_issues(issues), "issues": issues,
            "frames": [{"path": f["path"], "t": f["t"], "ocr": f["ocr"]} for f in frames],
            "tools": {"ocr": "vision-swift"}}


def _check_range(video, a, b):
    dur, _, _ = probe(video)
    if not (a >= 0 and b > a):
        raise BadInput(f"bad range --in {a} --out {b}")
    if a >= dur:
        raise BadInput(f"--in {a} is beyond the end of the video ({dur:.2f}s)")


# ----------------------------------------------------------------------------------------------
# cutaways (whole episode)
# ----------------------------------------------------------------------------------------------

def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _episode_data():
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        import episode_data
    finally:
        sys.path.pop(0)
    return episode_data


def resolve_media(src, roots, cuts):
    cands = [Path(r) / f"{src}.mp4" for r in roots]
    clips = (cuts or {}).get("clips") if isinstance(cuts, dict) else None
    p = (clips or {}).get(src, {}).get("path") if isinstance(clips, dict) else None
    if p:
        cands.append(Path(p))
    for c in cands:
        if c.is_file():
            return c
    return None


def is_source_beat(beat):
    return beat.get("origin") == "source" or beat.get("media") == "clip"


def severity_for(code, beat):
    """blank-frame is a defect on stock / ai media (error) but source content on a source beat (warn; cutaways measure source clips
    frame by frame in dense_blank_issues, which sets its own severity: error from blank_error_seconds); every other code is an error."""
    if code == "blank-frame" and is_source_beat(beat or {}):
        return "warn"
    return "error"


def count_issues(issues):
    by = {}
    for i in issues:
        sev = i.get("severity", "error")
        by.setdefault(i["code"], {"error": 0, "warn": 0})[sev] += 1
    return {"error": sum(v["error"] for v in by.values()), "warn": sum(v["warn"] for v in by.values()), "by_code": by}


def plan_range(beat, fdur, dur_declared=None):
    """Which local range of the file the beat really shows (engine spec 1a / S09).
    -> {"segment": [a, b] | None, "loops": bool, "source_loop": bool, "loop_len": s | None, "out_of_range": bool}
    `source_loop` / `out_of_range` are judged on the REAL file and are False when the declared brollDur matches the file
    (episode_schema.mjs S09 owns that verdict).

    The renderer mounts the clip in a Loop of L = floor((D - from) * fps) - 2 frames starting at `from`
    (D = brollDur[src], else the real file duration); a loop restarts at `from`, never at 0."""
    T = THRESHOLDS
    fps = T["engine_fps"]
    frm = float(beat.get("from") or 0.0)
    D = float(dur_declared) if dur_declared else fdur
    L = math.floor((D - frm) * fps + 1e-9) - 2
    # what the SCHEMA cannot see: the real file. When the declared brollDur matches it (within one frame) S09 owns the verdict.
    schema_owns = bool(dur_declared) and abs(D - fdur) <= 1.0 / fps + 0.02
    L_real = math.floor((fdur - frm) * fps + 1e-9) - 2
    out_of_range = not schema_owns and (frm < 0 or frm >= fdur or L_real < 1)
    if frm < 0 or frm >= min(D, fdur) or L < 1:
        return {"segment": None, "loops": False, "source_loop": False, "loop_len": None, "out_of_range": out_of_range}
    t, end = float(beat["t"]), float(beat["end"])
    shown_frames = math.ceil(end * fps - 1e-9) - math.ceil(t * fps - 1e-9)
    loops = shown_frames > L
    seg_len = min(end - t, L / fps)
    seg = [frm, min(frm + seg_len, fdur)]
    source_loop = not schema_owns and is_source_beat(beat) and shown_frames > L_real
    return {"segment": seg, "loops": loops, "source_loop": source_loop, "loop_len": L / fps, "real_loop_len": L_real / fps,
            "out_of_range": out_of_range}


def _beat_job(idx, beat, path, frames_dir, broll_dur):
    """Phase 1 for one beat (thread-safe): range plan, pixel stats, hash box, evidence frames."""
    fdur, fw, fh = probe(path)
    src = beat.get("src")
    declared = broll_dur.get(src) if isinstance(broll_dur, dict) else None
    crop = parse_crop(beat.get("srcCrop")) if beat.get("srcCrop") else None
    crop_px = scale_crop(crop, fw, fh)
    plan = plan_range(beat, fdur, declared)
    res = {"idx": idx, "file": str(path), "plan": plan, "fdur": fdur, "res": [fw, fh], "crop": crop, "crop_px": crop_px,
           "issues": [], "frames": [], "luma": {}, "hash_box": {"kind": "frame", "box": None},
           "secs": {"staticSampling": 0.0, "blank": 0.0, "cropPropose": 0.0, "frameExtract": 0.0}}
    if declared and abs(float(declared) - fdur) > 1.0 / THRESHOLDS["engine_fps"] + 0.02:
        res["issues"].append({"code": "broll-dur-mismatch", "range": None,
                              "detail": f"brollDur[{src}]={declared} but the file is {fdur:.3f}s (must match within 1 frame)"})
    if plan["segment"] is None:
        return res
    a, b = plan["segment"]
    dense = None
    if is_clip_source(beat):
        t0 = time.time()
        try:
            region = _episode_data().visible_region(beat.get("layout"), fw, fh, beat.get("srcCrop"))
            px = region_px(region, fw, fh)
            dense = decode_region(path, a, b, px)       # ONE decode of the visible region serves static-hold AND blank-frame
            res["static"] = {"from": a, "region": [round(v, 2) for v in region], "regionPx": list(px), "samples": samples_from_frames(dense, a)}
        except ValueError as e:
            res["static"] = {"error": str(e)}
        res["secs"]["staticSampling"] += time.time() - t0
    t0 = time.time()
    if dense is not None and dense.shape[0]:
        stats = luma_stats(dense, a, THRESHOLDS["engine_fps"])
        res["issues"] += dense_blank_issues(stats, a, b, src, beat["t"])
    else:
        stats = luma_samples(path, a, b, crop_px)
        res["issues"] += pixel_issues(stats, a, b)
    res["secs"]["blank"] += time.time() - t0
    if not stats:
        res["issues"].append({"code": "no-frames", "range": [round(a, 3), round(b, 3)],
                              "detail": "ffmpeg decoded no frames in the shown range"})
    res["luma"] = luma_summary(stats)
    # content box used for the shot-reuse hash: explicit srcCrop on any beat; crop-propose on source beats only
    if crop is not None:
        res["hash_box"] = {"kind": "srcCrop", "box": None}      # evidence frames are already cropped
    elif is_source_beat(beat):
        t0 = time.time()
        try:
            pr = propose_crop(path, a, b)
        except BadInput:
            pr = None
        res["secs"]["cropPropose"] += time.time() - t0
        T = THRESHOLDS
        if pr and pr["confidence"] >= T["reuse_box_min_confidence"] and pr["w"] * pr["h"] < T["reuse_box_max_area"] * REF_W * REF_H:
            res["hash_box"] = {"kind": "crop-propose", "box": [pr["x"], pr["y"], pr["w"], pr["h"]]}
    prefix = f"b{idx:03d}_{re.sub(r'[^A-Za-z0-9_.-]+', '_', str(src))[:40]}"
    t0 = time.time()
    frames, failed = collect_frames(path, a, b, crop_px, frames_dir, prefix)
    res["secs"]["frameExtract"] += time.time() - t0
    for t in failed:
        res["issues"].append({"code": "frame-missing", "range": [t, t], "detail": f"could not extract a frame at t={t}s"})
    res["frames"] = frames
    return res


def continuous_playback(a, b):
    """The ONE shot-reuse exception: same src file, adjacent in the beat list, both source clip beats, and b's played range starts at or
    after the end of a's (forward playback; the S10-allowed case, covered by static-hold). The ranges are the renderer's frame ranges
    [floor(from * 25 + .5), + shown frames) exactly as schema rule S10 counts them. Needs the optional keys index / media / origin /
    playFrames; entries without them never qualify."""
    if a.get("index") is None or b.get("index") is None or b["index"] != a["index"] + 1:
        return False
    if a.get("src") is None or a["src"] != b["src"]:
        return False
    if not all(x.get("media") == "clip" and x.get("origin") == "source" for x in (a, b)):
        return False
    if not a.get("playFrames") or not b.get("playFrames"):
        return False
    return b["playFrames"][0] >= a["playFrames"][1]


def reuse_issues(beat_results):
    """Cross-beat shot reuse from the evidence-frame dHashes. beat_results: [{t, src, origin, frames:[{t,dhash,flat}]}]
    (+ optional index, media, playFrames: see continuous_playback)."""
    T = THRESHOLDS
    issues = []
    order = sorted(range(len(beat_results)), key=lambda i: beat_results[i]["t"])
    for ii, i in enumerate(order):
        for j in order[ii + 1:]:
            A, B = beat_results[i], beat_results[j]
            if B["t"] - A["t"] >= T["reuse_window_seconds"]:
                break
            if continuous_playback(A, B):
                continue
            pairs = []
            for fa in A["frames"]:
                for fb in B["frames"]:
                    if fa.get("flat") or fb.get("flat") or not fa.get("dhash") or not fb.get("dhash"):
                        continue
                    d = hamming(fa["dhash"], fb["dhash"])
                    if d <= T["reuse_max_distance"]:
                        pairs.append((d, fa["t"], fb["t"]))
            if pairs:
                pairs.sort()
                d, ta, tb = pairs[0]
                issues.append({"code": "shot-reuse", "beat_t": B["t"], "src": B["src"], "origin": B["origin"],
                               "range": [tb, tb],
                               "detail": f"same shot as beat t={A['t']} ({A['src']}): {len(pairs)} matching frame pair(s), "
                                         f"best dHash distance {d} (this beat local t={tb}s vs {ta}s there); "
                                         f"{B['t'] - A['t']:.1f}s apart"})
    return issues


def cmd_cutaways(beats_path, cuts_path, media_roots, frames_dir, runner, episode_end=None, workers=None):
    t_start = time.time()
    max_hold = load_max_hold()
    ed = _episode_data()
    try:
        ed.picture_boxes()
    except ed.LanesFileMissing as e:          # config missing: exit 4 like a missing qc_thresholds.json. An INVALID file stays per-beat
        raise ToolMissing(str(e)) from e     # static-hold-region-unknown errors (ValueError from visible_region)
    except ed.LanesFileError:
        pass
    try:
        ep = ed.load_episode(beats_path, fallback_vo_end=episode_end)
    except ed.EpisodeFormatError as e:
        raise BadInput(str(e)) from e
    beats = ep["beats"]
    broll_dur = ep.get("broll_dur") or {}
    cuts = None
    if cuts_path:
        try:
            cuts = json.loads(Path(cuts_path).read_text())
        except (OSError, ValueError) as e:
            raise BadInput(f"cannot read cuts {cuts_path}: {e}") from e
    for r in media_roots:
        if not Path(r).is_dir():
            raise BadInput(f"media root not found: {r}")
    Path(frames_dir).mkdir(parents=True, exist_ok=True)
    issues, jobs = [], []
    inputs = {str(beats_path): _sha256(beats_path)}
    if cuts_path:
        inputs[str(cuts_path)] = _sha256(cuts_path)
    clips = (cuts or {}).get("clips", {}) if isinstance(cuts, dict) else {}

    def base(i):
        b = beats[i]
        return {"beat_t": b["t"], "src": b.get("src"), "origin": b.get("origin")}

    for i, b in enumerate(beats):
        if b.get("media") not in ("broll", "clip"):
            continue
        src = b.get("src")
        path = resolve_media(src, media_roots, cuts) if src else None
        if path is None:
            issues.append({"code": "media-missing", "severity": "error", **base(i), "range": None,
                           "detail": f"no media file for src {src!r} (looked for <media-root>/{src}.mp4 and the _cuts.json path)"})
            continue
        jobs.append((i, b, path))
    workers = workers or min(4, os.cpu_count() or 2)
    t1 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda j: _beat_job(j[0], j[1], j[2], frames_dir, broll_dur), jobs))
    phase1 = time.time() - t1

    # phase 2: OCR every evidence frame of the run in ONE batch
    allframes = [f for r in results for f in r["frames"]]
    t2 = time.time()
    ocr_res = run_ocr(runner, [f["path"] for f in allframes])
    phase2 = time.time() - t2
    beat_out = []
    for r in results:
        i, b = r["idx"], beats[r["idx"]]
        plan = r["plan"]
        if plan["out_of_range"]:
            issues.append({"code": "from-out-of-range", "severity": severity_for("from-out-of-range", b), **base(i), "range": None,
                           "detail": f"from={b.get('from', 0)} leaves no playable loop in the real file ({r['fdur']:.2f}s)"})
        elif plan["source_loop"]:
            need = math.ceil(b["end"] * THRESHOLDS["engine_fps"] - 1e-9) - math.ceil(b["t"] * THRESHOLDS["engine_fps"] - 1e-9)
            issues.append({"code": "source-loop", "severity": severity_for("source-loop", b), **base(i), "range": plan["segment"],
                           "detail": f"source beat shows {need / THRESHOLDS['engine_fps']:.2f}s but only {plan['real_loop_len']:.2f}s of the real file "
                                     f"remains after from={b.get('from', 0)} (source beats never loop)"})
        hb = r["hash_box"]["box"]
        for f in r["frames"]:
            o = ocr_res[f["path"]]
            f["ocr"] = list(o.get("lines") or []) if o.get("ok") else []
            if not o.get("ok"):
                issues.append({"code": "ocr-failed", "severity": severity_for("ocr-failed", b), **base(i), "range": [f["t"], f["t"]],
                               "detail": f"OCR could not read the frame at t={f['t']}s: {o.get('error')}"})
            f["dhash"], f["flat"] = dhash(f["path"], hb)
        for iss in r["issues"] + text_issues(r["frames"]):
            issues.append({"code": iss["code"], "severity": iss.get("severity") or severity_for(iss["code"], b), **base(i), "range": iss["range"],
                           "detail": iss["detail"], **({"duration": iss["duration"]} if "duration" in iss else {})})
        fps_ = THRESHOLDS["engine_fps"]
        p0 = int(math.floor(float(b.get("from") or 0.0) * fps_ + 0.5))
        entry_frames = [p0, p0 + math.ceil(b["end"] * fps_ - 1e-9) - math.ceil(b["t"] * fps_ - 1e-9)]
        entry = {"t": b["t"], "index": i, "playFrames": entry_frames, "media": b.get("media"), "src": b.get("src"), "origin": b.get("origin"), "file": r["file"], "resolution": r["res"],
                 "shown": [round(x, 3) for x in plan["segment"]] if plan["segment"] else None, "loops": plan["loops"]}
        if plan["loop_len"] is not None:
            entry["loopSeconds"] = round(plan["loop_len"], 3)
        if r["crop"]:
            entry["srcCrop"] = list(r["crop"])
            entry["srcCropPx"] = list(r["crop_px"])
        entry["hashBox"] = r["hash_box"]
        cut = clips.get(b.get("src")) if isinstance(clips, dict) else None
        sin = cut.get("source_in") if isinstance(cut, dict) else None
        has_src_t = is_source_beat(b) and isinstance(sin, (int, float)) and not isinstance(sin, bool)
        if has_src_t and plan["segment"]:
            entry["shown_source"] = [round(sin + plan["segment"][0], 3), round(sin + plan["segment"][1], 3)]
        frames_out = []
        for f in r["frames"]:
            fo = {"path": f["path"], "t": f["t"], "ocr": f["ocr"], "dhash": f["dhash"], "flat": f["flat"]}
            if has_src_t:
                fo["source_t"] = round(sin + f["t"], 3)
            frames_out.append(fo)
        entry["frames"] = frames_out
        entry["luma"] = r["luma"]
        beat_out.append(entry)
        if r["file"] not in inputs:
            inputs[r["file"]] = _sha256(r["file"])

    # phase 2b: static-hold over the on-screen timeline
    statics = {}
    for r in results:
        i, b = r["idx"], beats[r["idx"]]
        st = r.get("static")
        if st is not None and "error" in st:
            issues.append({"code": "static-hold-region-unknown", "severity": "error", **base(i), "range": None,
                           "detail": f"cannot compute the visible picture region of this source clip beat ({st['error']}); static-hold not measured"})
        elif st is not None:
            statics[i] = st
        elif is_clip_source(b) and not r["plan"]["out_of_range"]:
            issues.append({"code": "no-frames", "severity": "error", **base(i), "range": None,
                           "detail": "static-hold not measured: no playable range of the clip is shown"})
    hold_issues, hold_runs = static_timeline(beats, statics, max_hold)
    issues += hold_issues
    static_report = {"maxHoldSeconds": max_hold, "sampleFps": THRESHOLDS["static_sample_fps"], "hashDistance": THRESHOLDS["reuse_max_distance"],
                     "runs": hold_runs}

    # phase 3: shot reuse across beats
    for iss in reuse_issues(beat_out):
        issues.append({**iss, "severity": "error"})
    order = {b["t"]: n for n, b in enumerate(beats)}
    issues.sort(key=lambda x: (order.get(x["beat_t"], 0), x["code"]))
    counts = count_issues(issues)
    return {"schema": SCHEMA, "version": VERSION, "pass": counts["error"] == 0, "counts": counts, "issues": issues, "beats": beat_out,
            "staticHold": static_report,
            "timing": {"workers": workers, "beatJobsWallSeconds": round(phase1, 1), "ocrWallSeconds": round(phase2, 1),
                       "perJobSecondsSummed": {k: round(sum(r["secs"][k] for r in results), 1) for k in ("frameExtract", "staticSampling", "blank", "cropPropose")}},
            "tools": {"ocr": "vision-swift", "ocr_mode": getattr(runner, "mode", None),
                      "ocr_compile_seconds": round(getattr(runner, "compile_seconds", 0.0), 1),
                      "ocr_run_seconds": round(getattr(runner, "run_seconds", 0.0), 1),
                      "ocr_invocations": getattr(runner, "invocations", None),
                      "ocr_frames": len(allframes), "episode_format": ep.get("format")},
            "inputs": inputs, "seconds": round(time.time() - t_start, 1)}


# ----------------------------------------------------------------------------------------------
# crop proposer / checker
# ----------------------------------------------------------------------------------------------

def _even(n):
    return int(n) - (int(n) % 2)


def snap_16_9(x0, y0, x1, y1, fw, fh):
    """Largest 16:9 rectangle inside the box [x0,x1) x [y0,y1) (centered), even-sized, inside the frame."""
    w, h = x1 - x0, y1 - y0
    ar = THRESHOLDS["crop_aspect"]
    if abs(w / h / ar - 1) > 0.005:
        if w / h > ar:
            nw, nh = h * ar, h
        else:
            nw, nh = w, w / ar
        x0, y0 = x0 + (w - nw) / 2, y0 + (h - nh) / 2
        w, h = nw, nh
    w = _even(round(w))
    h = _even(round(w / ar))
    x = max(0, min(int(round(x0)), fw - w))
    y = max(0, min(int(round(y0)), fh - h))
    return x, y, w, h


def _bar_mask(arr, rows=None, cols=None, axis="col"):
    """Boolean mask over columns (axis='col') or rows ('row') marking bar lines, from an (n,H,W) float stack,
    optionally restricted to a row/column slice."""
    T = THRESHOLDS
    sub = arr
    if rows is not None:
        sub = sub[:, rows[0]:rows[1], :]
    if cols is not None:
        sub = sub[:, :, cols[0]:cols[1]]
    n = sub.shape[0]
    tstd = sub.std(axis=0) if n >= 3 else np.zeros(sub.shape[1:], dtype=np.float32)    # (H, W)
    mean = sub.mean(axis=0)
    # "dark" uses the MEDIAN along the line so a small static caption chip inside a black margin does not
    # make the whole margin row look like content.
    if axis == "col":
        line_mean, line_tstd, line_vstd = np.median(mean, axis=0), tstd.mean(axis=0), sub.std(axis=1).mean(axis=0)
    else:
        line_mean, line_tstd, line_vstd = np.median(mean, axis=1), tstd.mean(axis=1), sub.std(axis=2).mean(axis=0)
    dark = (line_mean < T["crop_dark_mean"]) & (line_tstd < T["crop_dark_tstd"])
    static = (line_tstd < T["crop_static_tstd"]) & (line_vstd < T["crop_uniform_vstd"]) & (n >= 3)
    return dark | static


def _inner_span(mask, max_frac):
    n = len(mask)
    lo = 0
    while lo < n and mask[lo]:
        lo += 1
    hi = n
    while hi > lo and mask[hi - 1]:
        hi -= 1
    cap = int(n * max_frac)
    lo_ok, hi_ok = lo <= cap, (n - hi) <= cap
    return (lo if lo_ok else 0), (hi if hi_ok else n), (lo_ok and hi_ok)


def _to_ref(x, y, w, h, fw, fh):
    """file-pixel box -> integer box in 1920x1080 space."""
    sx, sy = REF_W / fw, REF_H / fh
    X, Y = int(round(x * sx)), int(round(y * sy))
    W, H = int(round(w * sx)), int(round(h * sy))
    return X, Y, min(W, REF_W - X), min(H, REF_H - Y)


def propose_crop(video, a, b):
    """Content box of a (letterboxed / pillarboxed) source cut, snapped to 16:9, in 1920x1080 space."""
    T = THRESHOLDS
    dur, fw, fh = probe(video)
    if not (b > a >= 0) or a >= dur:
        raise BadInput(f"bad range --in {a} --out {b} for a {dur:.2f}s video")
    b = min(b, dur)
    ww = min(T["crop_work_width"], fw)
    ww -= ww % 2
    wh = max(2, int(round(ww * fh / fw)))
    n = T["crop_samples"]
    arr = decode_gray(video, a, b, [], ww, wh, None, fps_expr=f"{n}/{b - a:.3f}").astype(np.float32)
    if arr.shape[0] == 0:
        raise BadInput("no frames could be decoded for crop-propose")
    sx, sy = fw / ww, fh / wh
    cols = rows = None
    cx = (0, ww, True)
    cy = (0, wh, True)
    for _ in range(2):    # columns <-> rows depend on each other (side panels + letterbox)
        cx = _inner_span(_bar_mask(arr, rows=rows, axis="col"), T["crop_max_bar_fraction"])
        cols = (cx[0], cx[1])
        cy = _inner_span(_bar_mask(arr, cols=cols, axis="row"), T["crop_max_bar_fraction"])
        rows = (cy[0], cy[1])
    x0, x1, y0, y1 = cx[0] * sx, cx[1] * sx, cy[0] * sy, cy[1] * sy
    bars = (cx[0] > 0 or cx[1] < ww or cy[0] > 0 or cy[1] < wh)
    full_ok = abs(fw / fh / T["crop_aspect"] - 1) <= 0.02
    out = {"frame": [fw, fh], "space": f"{REF_W}x{REF_H}"}
    if not bars:
        zero = {"left": 0, "right": 0, "top": 0, "bottom": 0}
        if full_ok:
            return {"x": 0, "y": 0, "w": REF_W, "h": REF_H, "confidence": 0.9 if arr.shape[0] >= 3 else 0.6,
                    "reason": f"no static/black bars found in {arr.shape[0]} samples; full frame is 16:9", "bars": zero, **out}
        x, y, w, h = snap_16_9(0, 0, fw, fh, fw, fh)
        X, Y, W, H = _to_ref(x, y, w, h, fw, fh)
        return {"x": X, "y": Y, "w": W, "h": H, "confidence": 0.5,
                "reason": f"no bars found but the frame is {fw}x{fh} (not 16:9); centered 16:9 crop", "bars": zero, **out}
    x, y, w, h = snap_16_9(x0, y0, x1, y1, fw, fh)
    X, Y, W, H = _to_ref(x, y, w, h, fw, fh)
    clean = cx[2] and cy[2]
    conf = 0.7 if (clean and arr.shape[0] >= 3) else 0.5   # heuristic: a dark baked-in panel looks like a bar
    if (x1 - x0) < 0.3 * fw or (y1 - y0) < 0.3 * fh:
        conf = 0.2
    bx0, by0, bw, bh = _to_ref(x0, y0, x1 - x0, y1 - y0, fw, fh)
    return {"x": X, "y": Y, "w": W, "h": H, "confidence": conf,
            "reason": f"content box {bx0},{by0} {bw}x{bh} (1920x1080 space) found by static/black bar scan "
                      f"over {arr.shape[0]} samples; snapped to 16:9" + ("" if clean else "; a side exceeded the bar cap and was ignored"),
            "bars": {"left": int(round(x0)), "right": int(round(fw - x1)), "top": int(round(y0)), "bottom": int(round(fh - y1))}, **out}


def check_crop(video, a, b, crop):
    """crop in 1920x1080 space. Errors / warnings follow engine rule S11 (+ minimum width, blank inside)."""
    T = THRESHOLDS
    dur, fw, fh = probe(video)
    x, y, w, h = crop
    errors, warnings = [], []
    oob = x < 0 or y < 0 or x + w > REF_W or y + h > REF_H
    if oob:
        errors.append({"code": "crop-out-of-bounds", "severity": "error", "detail": f"crop {x}:{y}:{w}:{h} exceeds the {REF_W}x{REF_H} source frame"})
    dev = abs(w / h / T["crop_aspect"] - 1)
    if dev > T["crop_aspect_error"]:
        errors.append({"code": "crop-aspect", "severity": "error", "detail": f"aspect {w / h:.4f} is {dev:.0%} off 16:9 (error above {T['crop_aspect_error']:.0%})"})
    elif dev > T["crop_aspect_warning"]:
        warnings.append({"code": "crop-aspect", "severity": "warn", "detail": f"aspect {w / h:.4f} is {dev:.0%} off 16:9 (warning above {T['crop_aspect_warning']:.0%})"})
    if w < T["crop_min_width"]:
        errors.append({"code": "crop-too-small", "severity": "error", "detail": f"w={w} < {T['crop_min_width']} (1920 space)"})
    if not oob and w > 0 and h > 0:
        for iss in check_pixels(video, a, min(b, dur), (x, y, w, h))["issues"]:
            errors.append({"code": f"crop-{iss['code']}", "severity": "error", "detail": f"inside the crop: {iss['detail']} at {iss['range']}"})
    return {"schema": SCHEMA, "version": VERSION, "command": "crop-check", "video": str(video), "crop": [x, y, w, h],
            "pass": not errors, "errors": errors, "warnings": warnings}


# ----------------------------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------------------------

def _emit(obj, report=None):
    text = json.dumps(obj, indent=1, ensure_ascii=False)
    if report:
        Path(report).parent.mkdir(parents=True, exist_ok=True)
        Path(report).write_text(text + "\n")
    print(text)


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def rng(sp):
        sp.add_argument("--video", required=True)
        sp.add_argument("--in", dest="t_in", type=float, required=True)
        sp.add_argument("--out", dest="t_out", type=float, required=True)
        sp.add_argument("--report")

    sp = sub.add_parser("pixels"); rng(sp); sp.add_argument("--crop")
    sp.add_argument("--origin", choices=["stock", "ai", "source"], default="stock",
                    help="blank-frame is an error for stock/ai and a warning for source media")
    sp = sub.add_parser("watermark"); rng(sp); sp.add_argument("--crop"); sp.add_argument("--frames-dir", required=True)
    sp = sub.add_parser("cutaways")
    sp.add_argument("--beats", required=True); sp.add_argument("--cuts"); sp.add_argument("--media-root", action="append", default=[])
    sp.add_argument("--frames-dir", required=True); sp.add_argument("--report")
    sp.add_argument("--episode-end", type=float)
    sp = sub.add_parser("crop-propose"); rng(sp)
    sp = sub.add_parser("crop-check"); rng(sp); sp.add_argument("--crop", required=True)
    return p


def main(argv=None, ocr_runner=None):
    """`ocr_runner(paths) -> {path: {"ok":bool, "lines":[...]|"error":str}}` is injectable for tests."""
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    runner = ocr_runner or VisionOcr()
    try:
        if args.cmd == "pixels":
            out = cmd_pixels(args.video, args.t_in, args.t_out, parse_crop(args.crop), args.origin)
            _emit(out, args.report); return 0 if out["pass"] else 1
        if args.cmd == "watermark":
            out = cmd_watermark(args.video, args.t_in, args.t_out, parse_crop(args.crop), args.frames_dir, runner)
            _emit(out, args.report); return 0 if out["pass"] else 1
        if args.cmd == "cutaways":
            if not args.media_root:
                raise BadInput("--media-root is required (may be given several times)")
            out = cmd_cutaways(args.beats, args.cuts, args.media_root, args.frames_dir, runner, args.episode_end)
            _emit(out, args.report); return 0 if out["pass"] else 1
        if args.cmd == "crop-propose":
            out = {"schema": SCHEMA, "version": VERSION, "command": "crop-propose", "video": args.video,
                   **propose_crop(args.video, args.t_in, args.t_out)}
            _emit(out, args.report); return 0
        if args.cmd == "crop-check":
            out = check_crop(args.video, args.t_in, args.t_out, parse_crop(args.crop))
            _emit(out, args.report); return 0 if out["pass"] else 1
    except ToolMissing as e:
        print(f"frame_checks: tool missing: {e}", file=sys.stderr)
        return 4
    except BadInput as e:
        print(f"frame_checks: bad input: {e}", file=sys.stderr)
        return 2
    finally:
        if hasattr(runner, "close"):
            runner.close()          # the private OCR build directory never outlives the command
    return 2


if __name__ == "__main__":
    sys.exit(main())
