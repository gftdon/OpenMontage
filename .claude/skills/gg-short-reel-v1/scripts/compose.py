"""Concatenate the AI clips into one conformed 1080x1920 / 30 fps video-only stream."""
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import common

W, H, FPS = 1080, 1920, 30
BASE_CRF = "14"  # intermediate: near-lossless, the overlay pass is the final video encode


@dataclass(frozen=True)
class Shot:
    seq: int
    path: Path
    continues: bool  # True: first frame duplicates the previous shot's last frame -> drop it


def _rate(text):
    try:
        f = Fraction(text)
        return float(f) if f > 0 else None
    except (ValueError, ZeroDivisionError, TypeError):
        return None


def probe_shot(path, deadline):
    """Validate that 0:v:0 exists and return (duration_s, fps). Grok files carry 2 video streams; only the first is used."""
    info = common.probe(path, deadline)
    videos = common.streams_of(info, "video")
    if not videos:
        raise common.GgError(f"คลิป {Path(path).name} ไม่มี video stream")
    v = videos[0]
    if not (int(v.get("width") or 0) > 0 and int(v.get("height") or 0) > 0):
        raise common.GgError(f"คลิป {Path(path).name} ขนาดภาพไม่ถูกต้อง")
    fps = _rate(v.get("avg_frame_rate") or "") or _rate(v.get("r_frame_rate") or "") or float(FPS)
    try:
        dur = float(v.get("duration") or info.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        dur = 0.0
    if not dur > 0:
        raise common.GgError(f"คลิป {Path(path).name} ความยาวไม่ถูกต้อง")
    return dur, fps


def estimate_duration(shots, deadline):
    """Cheap estimate of the composed length from source durations (continuation shots lose one frame)."""
    total = 0.0
    for s in shots:
        dur, fps = probe_shot(s.path, deadline)
        if s.continues:
            if dur < 2.0 / fps - 1e-6:
                raise common.GgError(f"ช็อต {s.seq} เป็นช็อตต่อแต่มีน้อยกว่า 2 เฟรม")
            dur -= 1.0 / fps
        total += dur
    return total


def build_filter(shots):
    parts, labels = [], []
    for i, s in enumerate(shots):
        trim = "trim=start_frame=1," if s.continues else ""
        parts.append(
            f"[{i}:v:0]{trim}setpts=PTS-STARTPTS,fps={FPS},"
            f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},"
            f"setsar=1,format=yuv420p[v{i}]")
        labels.append(f"[v{i}]")
    parts.append(f"{''.join(labels)}concat=n={len(shots)}:v=1:a=0[vout]")
    return ";".join(parts)


def build_base(shots, out_path, deadline):
    """Video-only intermediate. Source audio is dropped (-an); only 0:v:0 of each file is mapped."""
    if not shots:
        raise common.GgError("ไม่มีช็อตให้ตัดต่อ")
    args = [common.find_tool("ffmpeg"), "-nostdin", "-hide_banner", "-v", "error", "-y"]
    for s in shots:
        args += ["-i", s.path]
    args += ["-filter_complex", build_filter(shots), "-map", "[vout]", "-an",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", BASE_CRF, "-pix_fmt", "yuv420p",
             "-r", str(FPS), "-fps_mode", "cfr", "-movflags", "+faststart", out_path]
    common.run_cmd(args, deadline, "ffmpeg compose")
