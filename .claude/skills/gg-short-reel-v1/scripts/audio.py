"""Music bed (via a provider interface), loudness normalisation and measurement."""
import json
import math
import re
from pathlib import Path
from typing import Protocol

import common

TARGET_I, TARGET_TP, TARGET_LRA = -14.0, -1.5, 11.0
TOL_I, MAX_TP = 1.0, -1.0
FADE_OUT_S = 1.0
NOT_CONFIGURED_MESSAGE = "ยังไม่ได้ตั้งตัวสร้างเพลง AI (CF-A85 รอแผนเพลง)"


class MusicUnavailable(Exception):
    """The provider cannot supply music. Raise ONLY when no paid/external work was started
    (the receipt then stays retry_safe)."""


class MusicProvider(Protocol):
    #: True when get_music may start paid/external work. A non-MusicUnavailable failure of such a
    #: provider makes the receipt retry_safe:false.
    is_paid: bool

    def get_music(self, duration_s: float, mood, out_path: Path) -> Path:
        ...


class NotConfiguredMusicProvider:
    """Default provider: the real AI-music provider is not implemented yet (CF-A85)."""
    is_paid = False

    def get_music(self, duration_s, mood, out_path):
        raise MusicUnavailable(NOT_CONFIGURED_MESSAGE)


def loudness_ok(integrated, true_peak):
    try:
        i, tp = float(integrated), float(true_peak)
    except (TypeError, ValueError):
        return False
    return math.isfinite(i) and math.isfinite(tp) and abs(i - TARGET_I) <= TOL_I + 1e-8 and tp <= MAX_TP + 1e-8


def parse_loudnorm(text):
    """Last complete loudnorm JSON object of an ffmpeg log; finite values only (silence -> -inf -> error)."""
    for raw in reversed(re.findall(r"\{[^{}]*\}", text or "")):
        try:
            d = json.loads(raw)
            keys = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
            out = {k: float(d[k]) for k in keys}
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(v) for v in out.values()):
            raise common.GgError("วัดความดังไม่ได้ (เสียงเงียบหรือไม่มีเสียง)")
        return out
    raise common.GgError("ไม่พบผลวัดความดัง (loudnorm) จาก ffmpeg")


def _loudnorm_run(args, deadline, what):
    proc = common.run_cmd(args, deadline, what)
    return parse_loudnorm(proc.stderr)


def measure_loudness(path, deadline):
    """Integrated loudness (LUFS) and true peak (dBTP) of the file's first audio stream, as delivered."""
    d = _loudnorm_run([common.find_tool("ffmpeg"), "-nostdin", "-hide_banner", "-nostats", "-v", "info", "-i", path,
                       "-map", "0:a:0", "-af", f"loudnorm=I={TARGET_I:g}:TP={TARGET_TP:g}:LRA=20:print_format=json",
                       "-f", "null", "-"], deadline, "วัดความดังของไฟล์สุดท้าย")
    return d["input_i"], d["input_tp"]


def validate_music(path, deadline):
    p = Path(path)
    if not p.is_file():
        raise common.GgError(f"ไฟล์เพลงไม่มีอยู่: {p.name}")
    if p.stat().st_size <= 0:
        raise common.GgError(f"ไฟล์เพลงว่าง: {p.name}")
    info = common.probe(p, deadline)
    if not common.streams_of(info, "audio"):
        raise common.GgError(f"ไฟล์เพลง {p.name} ไม่มี audio stream")
    try:
        dur = float(info.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        dur = 0.0
    if not dur > 0:
        raise common.GgError(f"ไฟล์เพลง {p.name} ความยาวไม่ถูกต้อง")
    return info


def build_music_bed(music, duration_s, out_wav, deadline):
    """Loop/trim to the video length, ~1 s fade-out, two-pass loudnorm (I=-14, TP=-1.5) -> 48 kHz stereo wav."""
    ffmpeg = common.find_tool("ffmpeg")
    chain = (f"aformat=sample_rates=48000:channel_layouts=stereo,"
             f"afade=t=out:st={max(duration_s - FADE_OUT_S, 0):.3f}:d={FADE_OUT_S:g}")
    base = [ffmpeg, "-nostdin", "-hide_banner", "-nostats", "-v", "info", "-stream_loop", "-1", "-i", music,
            "-map", "0:a:0", "-t", f"{duration_s:.3f}"]
    ln = f"loudnorm=I={TARGET_I:g}:TP={TARGET_TP:g}:LRA={TARGET_LRA:g}"
    m = _loudnorm_run(base + ["-af", f"{chain},{ln}:print_format=json", "-f", "null", "-"], deadline, "วัดความดังเพลง (pass 1)")
    second = (f"{chain},{ln}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
              f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true:print_format=summary")
    common.run_cmd(base + ["-af", second, "-c:a", "pcm_f32le", "-ar", "48000", "-y", out_wav], deadline,
                   "ปรับความดังเพลง (pass 2)")


def mux(video, bed_wav, out_path, deadline):
    common.run_cmd([common.find_tool("ffmpeg"), "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", video, "-i", bed_wav,
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "48000", "-ac", "2", "-movflags", "+faststart", out_path], deadline, "ffmpeg mux")
