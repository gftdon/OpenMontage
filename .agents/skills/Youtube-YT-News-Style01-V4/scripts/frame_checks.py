#!/usr/bin/env python3
"""Pixel / watermark / crop / shot-reuse checks on every cutaway (YT-News V4, WP2b).

Local tools only (ffmpeg, numpy, PIL, macOS Vision through scripts/ocr_vision.swift). No network.

  frame_checks.py pixels       --video V --in A --out B [--crop x:y:w:h]
  frame_checks.py watermark    --video V --in A --out B [--crop x:y:w:h] --frames-dir D [--cache-dir C]
  frame_checks.py cutaways     --beats beats.json [--cuts _cuts.json] --media-root DIR [--media-root DIR ...]
                               --frames-dir D --report R.json [--cache-dir C] [--episode-end SEC]
  frame_checks.py crop-propose --video V --in A --out B
  frame_checks.py crop-check   --video V --in A --out B --crop x:y:w:h

Exit codes: 0 = pass, 1 = issues found, 2 = bad input, 4 = a required tool (ffmpeg / swift+Vision) cannot run.
OCR is never skipped silently: when Vision OCR cannot run the command exits 4.

Sampling note: the pixel check samples at THRESHOLDS["sample_fps"]. A run needs at least two consecutive
flagged samples (first-to-last span >= run_min_seconds), so a single-sample flash (a 0.2 s white flash)
is never reported; a blank range that is shorter than the run minimum is reported only when the whole
shown range is blank.
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
from pathlib import Path

import numpy as np

THRESHOLDS = {
    # pixel check
    "sample_fps": 2.0,
    "blank_mean_min": 225,          # blank-white: mean luma above this ...
    "blank_range_max": 40,          # ... and (max - min luma) below this
    "black_mean_max": 20,           # near-black: mean luma below this
    "run_min_seconds": 0.5,         # a run must span at least this long
    "sample_size": (96, 54),        # frames are area-downscaled to this before the stats
    # OCR
    "ocr_min_frames": 5,            # frames per range = max(ocr_min_frames, ceil(duration / ocr_seconds_per_frame))
    "ocr_seconds_per_frame": 2.0,
    "ocr_max_width": 1920,
    "watermark_regex": r"pixabay|shutterstock|getty|istock|envato|storyblocks|pexels|videvo|adobe\s*stock|dreamstime|pond5|watermark",
    "promo_regex": r"subscribe|sponsor(ed)?",
    # shot reuse
    "reuse_max_distance": 6,        # dHash (64 bit) Hamming distance
    "reuse_window_seconds": 60.0,   # beats whose start times are closer than this are compared
    "reuse_flat_std": 4.0,          # evidence frames flatter than this (luma std) are not compared (all-black == all-black)
    # crop
    "crop_aspect": 16 / 9,
    "crop_aspect_tolerance": 0.02,
    "crop_min_width": 640,
    "crop_samples": 24,
    "crop_work_width": 960,
    "crop_dark_mean": 18,
    "crop_static_tstd": 2.0,
    "crop_dark_tstd": 3.0,
    "crop_uniform_vstd": 10.0,
    "crop_max_bar_fraction": 0.4,   # more than this per side is not a bar, it is content
}

SCRIPT_DIR = Path(__file__).resolve().parent
SWIFT_SRC = SCRIPT_DIR / "ocr_vision.swift"
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
SCHEMA = "yt-news-v4-frame-checks"
VERSION = 1


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


def luma_samples(video, a, b, crop=None):
    """-> (times, per-frame stats list). Times are clip-local seconds."""
    fps = THRESHOLDS["sample_fps"]
    w, h = THRESHOLDS["sample_size"]
    arr = decode_gray(video, a, b, _crop_vf(crop), w, h, fps)
    stats = []
    for i in range(arr.shape[0]):
        f = arr[i].astype(np.float32)
        stats.append({"t": round(a + i / fps, 3), "mean": float(f.mean()),
                      "range": float(f.max() - f.min())})
    return stats


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
            out.append((times[i], min(b, times[j] + 1.0 / fps)))
        i = j + 1
    return out


def pixel_issues(stats, a, b):
    """Blank-white / near-black runs from luma samples -> list of issue dicts (code, range, detail)."""
    T = THRESHOLDS
    fps, minspan = T["sample_fps"], T["run_min_seconds"]
    times = [s["t"] for s in stats]
    issues = []
    white = [s["mean"] > T["blank_mean_min"] and s["range"] < T["blank_range_max"] for s in stats]
    black = [s["mean"] < T["black_mean_max"] for s in stats]
    for code, flags, what in (("blank-white", white, "mean luma > %d and range < %d" % (T["blank_mean_min"], T["blank_range_max"])),
                              ("near-black", black, "mean luma < %d" % T["black_mean_max"])):
        for t0, t1 in _runs(flags, times, a, b, fps, minspan):
            sel = [s for s in stats if t0 - 1e-6 <= s["t"] <= t1]
            issues.append({"code": code, "range": [round(t0, 3), round(t1, 3)],
                           "detail": f"{what}; {len(sel)} samples, mean luma {np.mean([s['mean'] for s in sel]):.1f}, "
                                     f"mean luma range (max-min) {np.mean([s['range'] for s in sel]):.0f}"})
    return issues


def luma_summary(stats):
    T = THRESHOLDS
    if not stats:
        return {"n": 0}
    m = [s["mean"] for s in stats]
    return {"n": len(stats), "mean": round(float(np.mean(m)), 1), "min_mean": round(min(m), 1),
            "max_mean": round(max(m), 1),
            "blank_white_samples": sum(1 for s in stats if s["mean"] > T["blank_mean_min"] and s["range"] < T["blank_range_max"]),
            "near_black_samples": sum(1 for s in stats if s["mean"] < T["black_mean_max"])}


def check_pixels(video, a, b, crop=None):
    """Pixel check of one range. -> {"issues": [...], "luma": {...}, "samples": n}"""
    stats = luma_samples(video, a, b, crop)
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
    n = max(T["ocr_min_frames"], math.ceil((b - a) / T["ocr_seconds_per_frame"]))
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


def dhash(path):
    """-> (hex dHash (64 bit), flat?)"""
    from PIL import Image
    with Image.open(path) as im:
        g = im.convert("L")
        small = np.asarray(g.resize((9, 8), Image.LANCZOS), dtype=np.int16)
        flat = float(np.asarray(g.resize((16, 16), Image.BILINEAR), dtype=np.float32).std()) < THRESHOLDS["reuse_flat_std"]
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    v = 0
    for bit in bits:
        v = (v << 1) | int(bit)
    return f"{v:016x}", flat


def hamming(h1, h2):
    return bin(int(h1, 16) ^ int(h2, 16)).count("1")


# ----------------------------------------------------------------------------------------------
# OCR (macOS Vision via ocr_vision.swift)
# ----------------------------------------------------------------------------------------------

class VisionOcr:
    """Runs ocr_vision.swift on a batch of images in ONE process. Compiled once per source hash when
    swiftc works (cache_dir), otherwise interpreted with `swift`. Raises ToolMissing when neither works."""

    def __init__(self, cache_dir=None, swift_src=None):
        self.src = Path(swift_src or SWIFT_SRC)
        self.cache_dir = Path(cache_dir) if cache_dir else Path(tempfile.gettempdir()) / "yt-news-v4-ocr-cache"
        self.mode = None            # "compiled" | "interpreted"
        self.compile_seconds = 0.0
        self.run_seconds = 0.0
        self.invocations = 0
        self._cmd = None

    def _prepare(self):
        if self._cmd is not None:
            return
        if not self.src.is_file():
            raise ToolMissing(f"OCR source missing: {self.src}")
        sha = hashlib.sha256(self.src.read_bytes()).hexdigest()[:16]
        swiftc, swift = shutil.which("swiftc"), shutil.which("swift")
        if swiftc:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            binary = self.cache_dir / f"ocr_vision-{sha}"
            if not (binary.is_file() and os.access(binary, os.X_OK)):
                tmp = self.cache_dir / f".build-{os.getpid()}-{sha}"
                t0 = time.time()
                try:
                    r = subprocess.run([swiftc, "-O", str(self.src), "-o", str(tmp)], capture_output=True, timeout=600)
                except subprocess.TimeoutExpired:
                    r = None
                self.compile_seconds = time.time() - t0
                if r is not None and r.returncode == 0 and tmp.is_file():
                    os.replace(tmp, binary)
                else:
                    tmp.unlink(missing_ok=True)
            if binary.is_file() and os.access(binary, os.X_OK):
                self.mode, self._cmd = "compiled", [str(binary)]
                return
        if swift:
            self.mode, self._cmd = "interpreted", [swift, str(self.src)]
            return
        raise ToolMissing("swift / swiftc not found: macOS Vision OCR cannot run")

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


def cmd_pixels(video, a, b, crop=None):
    _check_range(video, a, b)
    r = check_pixels(video, a, b, crop)
    return {"schema": SCHEMA, "version": VERSION, "command": "pixels", "video": str(video), "range": [a, b],
            "crop": crop, "pass": not r["issues"], "issues": r["issues"], "luma": r["luma"]}


def cmd_watermark(video, a, b, crop, frames_dir, runner):
    _check_range(video, a, b)
    frames, failed = collect_frames(video, a, b, crop, frames_dir, _prefix_for(video))
    issues = [{"code": "frame-missing", "range": [t, t], "detail": f"could not extract a frame at t={t}s"} for t in failed]
    issues += ocr_frames(runner, frames)
    issues += text_issues(frames)
    return {"schema": SCHEMA, "version": VERSION, "command": "watermark", "video": str(video), "range": [a, b],
            "crop": crop, "pass": not issues, "issues": issues,
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


def load_beats(path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise BadInput(f"cannot read beats {path}: {e}") from e
    if isinstance(data, dict):
        data = data.get("beats")
    if not isinstance(data, list) or not all(isinstance(b, dict) and isinstance(b.get("t"), (int, float)) for b in data):
        raise BadInput("beats must be a JSON list of objects with a numeric `t`")
    return data


def beat_durations(beats, episode_end=None):
    """-> list of beat durations (None when unknown). End = beat.end, else next beat's t, else episode_end."""
    out = []
    for i, b in enumerate(beats):
        if isinstance(b.get("end"), (int, float)):
            end = float(b["end"])
        elif i + 1 < len(beats):
            end = float(beats[i + 1]["t"])
        else:
            end = episode_end
        out.append(None if end is None else max(0.0, end - float(b["t"])))
    return out


def resolve_media(src, roots, cuts):
    cands = [Path(r) / f"{src}.mp4" for r in roots]
    p = ((cuts or {}).get("clips") or {}).get(src, {}).get("path") if isinstance(cuts, dict) else None
    if p:
        cands.append(Path(p))
    for c in cands:
        if c.is_file():
            return c
    return None


def shown_segments(frm, dur, fdur):
    """-> (segments [[a,b],...], loops, invalid). Primary segment is [from, min(from+dur, fdur)]; when the
    beat outlasts the clip and from > 0, the part of the loop that wraps to the clip start is checked too."""
    frm = float(frm or 0.0)
    if frm >= fdur:
        return [], False, True
    if dur is None or dur <= 0:
        return [[frm, fdur]], False, False
    end = min(frm + dur, fdur)
    segs = [[frm, end]]
    loops = dur > (fdur - frm) + 1e-6
    if loops and frm > 0:
        wrap = min(dur - (fdur - frm), frm)
        if wrap > 0.05:
            segs.append([0.0, wrap])
    return segs, loops, False


def _beat_job(idx, beat, dur, path, frames_dir):
    """Phase 1 for one beat (thread-safe): pixel stats + evidence frames for each shown segment."""
    fdur, _, _ = probe(path)
    crop = parse_crop(beat.get("srcCrop")) if beat.get("srcCrop") else None
    segs, loops, invalid = shown_segments(beat.get("from"), dur, fdur)
    res = {"idx": idx, "file": str(path), "segments": [], "loops": loops, "invalid": invalid, "fdur": fdur,
           "crop": crop, "issues": [], "frames": [], "luma": {}}
    allstats = []
    for si, (a, b) in enumerate(segs):
        stats = luma_samples(path, a, b, crop)
        allstats += stats
        for iss in pixel_issues(stats, a, b):
            res["issues"].append(iss)
        if not stats:
            res["issues"].append({"code": "no-frames", "range": [round(a, 3), round(b, 3)],
                                  "detail": "ffmpeg decoded no frames in the shown range"})
        prefix = f"b{idx:03d}_{re.sub(r'[^A-Za-z0-9_.-]+', '_', str(beat.get('src')))[:40]}" + (f"_w{si}" if si else "")
        frames, failed = collect_frames(path, a, b, crop, frames_dir, prefix)
        for t in failed:
            res["issues"].append({"code": "frame-missing", "range": [t, t], "detail": f"could not extract a frame at t={t}s"})
        res["frames"] += frames
        res["segments"].append([round(a, 3), round(b, 3)])
    res["luma"] = luma_summary(allstats)
    return res


def reuse_issues(beat_results):
    """Cross-beat shot reuse from the evidence-frame dHashes. beat_results: [{t, src, origin, frames:[{t,dhash,flat}]}]"""
    T = THRESHOLDS
    issues = []
    order = sorted(range(len(beat_results)), key=lambda i: beat_results[i]["t"])
    for ii, i in enumerate(order):
        for j in order[ii + 1:]:
            A, B = beat_results[i], beat_results[j]
            if B["t"] - A["t"] >= T["reuse_window_seconds"]:
                break
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
    beats = load_beats(beats_path)
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
    durs = beat_durations(beats, episode_end)
    issues, entries, jobs = [], {}, []
    inputs = {str(beats_path): _sha256(beats_path)}
    if cuts_path:
        inputs[str(cuts_path)] = _sha256(cuts_path)

    def base(i, extra=None):
        b = beats[i]
        d = {"beat_t": b["t"], "src": b.get("src"), "origin": b.get("origin")}
        d.update(extra or {})
        return d

    for i, b in enumerate(beats):
        if b.get("media") not in ("broll", "clip"):
            continue
        src = b.get("src")
        path = resolve_media(src, media_roots, cuts) if src else None
        if path is None:
            issues.append({"code": "media-missing", "severity": "error", **base(i), "range": None,
                           "detail": f"no media file for src {src!r} (looked for <media-root>/{src}.mp4 and the _cuts.json path)"})
            continue
        jobs.append((i, b, durs[i], path))
    workers = workers or min(4, os.cpu_count() or 2)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda j: _beat_job(j[0], j[1], j[2], j[3], frames_dir), jobs))

    # phase 2: OCR every evidence frame of the run in ONE batch
    allframes = [f for r in results for f in r["frames"]]
    ocr_res = run_ocr(runner, [f["path"] for f in allframes])
    beat_out = []
    for r in results:
        i, b = r["idx"], beats[r["idx"]]
        if r["invalid"]:
            issues.append({"code": "from-out-of-range", "severity": "error", **base(i), "range": None,
                           "detail": f"from={b.get('from')} is beyond the clip ({r['fdur']:.2f}s)"})
        for f in r["frames"]:
            o = ocr_res[f["path"]]
            f["ocr"] = list(o.get("lines") or []) if o.get("ok") else []
            if not o.get("ok"):
                issues.append({"code": "ocr-failed", "severity": "error", **base(i), "range": [f["t"], f["t"]],
                               "detail": f"OCR could not read the frame at t={f['t']}s: {o.get('error')}"})
            f["dhash"], f["flat"] = dhash(f["path"])
        for iss in r["issues"] + text_issues(r["frames"]):
            issues.append({"code": iss["code"], "severity": "error", **base(i), "range": iss["range"], "detail": iss["detail"]})
        entry = {"t": b["t"], "src": b.get("src"), "origin": b.get("origin"), "file": r["file"],
                 "shown": r["segments"][0] if r["segments"] else None, "loops": r["loops"]}
        if len(r["segments"]) > 1:
            entry["shown_wrapped"] = r["segments"][1]
        if r["crop"]:
            entry["srcCrop"] = list(r["crop"])
        entry["frames"] = [{"path": f["path"], "t": f["t"], "ocr": f["ocr"], "dhash": f["dhash"], "flat": f["flat"]} for f in r["frames"]]
        entry["luma"] = r["luma"]
        beat_out.append(entry)
        if r["file"] not in inputs:
            inputs[r["file"]] = _sha256(r["file"])

    # phase 3: shot reuse across beats
    for iss in reuse_issues(beat_out):
        issues.append({**iss, "severity": "error"})
    order = {b["t"]: n for n, b in enumerate(beats)}
    issues.sort(key=lambda x: (order.get(x["beat_t"], 0), x["code"]))
    return {"schema": SCHEMA, "version": VERSION, "pass": not issues, "issues": issues, "beats": beat_out,
            "tools": {"ocr": "vision-swift", "ocr_mode": getattr(runner, "mode", None),
                      "ocr_compile_seconds": round(getattr(runner, "compile_seconds", 0.0), 1),
                      "ocr_run_seconds": round(getattr(runner, "run_seconds", 0.0), 1),
                      "ocr_invocations": getattr(runner, "invocations", None)},
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


def propose_crop(video, a, b):
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
    full_ok = abs(fw / fh / T["crop_aspect"] - 1) <= T["crop_aspect_tolerance"]
    if not bars:
        if full_ok:
            return {"x": 0, "y": 0, "w": fw - fw % 2, "h": fh - fh % 2, "confidence": 0.9 if arr.shape[0] >= 3 else 0.6,
                    "reason": f"no static/black bars found in {arr.shape[0]} samples; full frame is 16:9",
                    "frame": [fw, fh], "bars": {"left": 0, "right": 0, "top": 0, "bottom": 0}}
        x, y, w, h = snap_16_9(0, 0, fw, fh, fw, fh)
        return {"x": x, "y": y, "w": w, "h": h, "confidence": 0.5,
                "reason": f"no bars found but the frame is {fw}x{fh} (not 16:9); centered 16:9 crop",
                "frame": [fw, fh], "bars": {"left": 0, "right": 0, "top": 0, "bottom": 0}}
    x, y, w, h = snap_16_9(x0, y0, x1, y1, fw, fh)
    clean = cx[2] and cy[2]
    conf = 0.7 if (clean and arr.shape[0] >= 3) else 0.5   # heuristic: a dark baked-in panel looks like a bar
    if (x1 - x0) < 0.3 * fw or (y1 - y0) < 0.3 * fh:
        conf = 0.2
    return {"x": x, "y": y, "w": w, "h": h, "confidence": conf,
            "reason": f"content box {int(round(x0))},{int(round(y0))} {int(round(x1 - x0))}x{int(round(y1 - y0))} found by static/black bar scan "
                      f"over {arr.shape[0]} samples; snapped to 16:9" + ("" if clean else "; a side exceeded the bar cap and was ignored"),
            "frame": [fw, fh],
            "bars": {"left": int(round(x0)), "right": int(round(fw - x1)), "top": int(round(y0)), "bottom": int(round(fh - y1))}}


def check_crop(video, a, b, crop):
    T = THRESHOLDS
    dur, fw, fh = probe(video)
    x, y, w, h = crop
    errors = []
    if x < 0 or y < 0 or x + w > fw or y + h > fh:
        errors.append({"code": "crop-out-of-bounds", "detail": f"crop {x}:{y}:{w}:{h} exceeds the {fw}x{fh} frame"})
    if abs(w / h / T["crop_aspect"] - 1) > T["crop_aspect_tolerance"]:
        errors.append({"code": "crop-aspect", "detail": f"aspect {w / h:.4f} differs from 16:9 by more than {T['crop_aspect_tolerance'] * 100:.0f}%"})
    if w < T["crop_min_width"]:
        errors.append({"code": "crop-too-small", "detail": f"w={w} < {T['crop_min_width']}"})
    if not errors:
        for iss in check_pixels(video, a, min(b, dur), (x, y, w, h))["issues"]:
            errors.append({"code": f"crop-{iss['code']}", "detail": f"inside the crop: {iss['detail']} at {iss['range']}"})
    return {"schema": SCHEMA, "version": VERSION, "command": "crop-check", "video": str(video), "crop": [x, y, w, h],
            "pass": not errors, "errors": errors}


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
    sp = sub.add_parser("watermark"); rng(sp); sp.add_argument("--crop"); sp.add_argument("--frames-dir", required=True); sp.add_argument("--cache-dir")
    sp = sub.add_parser("cutaways")
    sp.add_argument("--beats", required=True); sp.add_argument("--cuts"); sp.add_argument("--media-root", action="append", default=[])
    sp.add_argument("--frames-dir", required=True); sp.add_argument("--report"); sp.add_argument("--cache-dir")
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
    try:
        runner = ocr_runner or VisionOcr(getattr(args, "cache_dir", None))
        if args.cmd == "pixels":
            out = cmd_pixels(args.video, args.t_in, args.t_out, parse_crop(args.crop))
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
    return 2


if __name__ == "__main__":
    sys.exit(main())
