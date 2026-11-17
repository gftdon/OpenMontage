"""Music bed (read from the AIOS `music` step input), loudness normalisation and measurement.

The skill never generates, fetches or pays for music: AIOS produces `<code>_30_Music.mp3` in its own step.
"""
import json
import math
import os
import re
from pathlib import Path
from typing import Protocol

import common

# TP target -2.0 (gate stays -1.0): leaves margin for the overshoot the AAC encode adds after loudnorm.
TARGET_I, TARGET_TP, TARGET_LRA = -14.0, -2.0, 11.0
TOL_I, MAX_TP = 1.0, -1.0
FADE_IN_S, FADE_OUT_S = 0.1, 1.2
MUSIC_SUFFIX = "_30_Music.mp3"
LIMITER_HEADROOM_DB, LIMITER_ITERATIONS, LIMITER_TOL_I = 1.0, 6, 0.25   # peak limit = TARGET_TP - 1 dB (inter-sample margin)
SHORT_TOLERANCE_S = 1 / 30     # music may be at most one video frame shorter than the video (mp3 framing)


class MusicUnavailable(Exception):
    """The provider cannot supply music. Raise ONLY when no paid/external work was started
    (the receipt then stays retry_safe)."""


class MusicProvider(Protocol):
    #: True when get_music may start paid/external work. A non-MusicUnavailable failure of such a
    #: provider makes the receipt retry_safe:false.
    is_paid: bool

    def get_music(self, duration_s: float, mood, out_path: Path) -> Path:
        ...


def _secs(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


def check_music_duration(music_s, video_s):
    if music_s + SHORT_TOLERANCE_S < video_s:
        raise MusicUnavailable(f"เพลงสั้นกว่าวิดีโอ ({_secs(music_s)} วิ < {_secs(video_s)} วิ) — ไม่ลูปเพลง")


class FileMusicProvider:
    """Uses the mp3 the AIOS `music` step already produced (request input role `music`). No network, never paid."""
    is_paid = False

    def __init__(self, request, task_dir=None):
        self.request = request
        self._task_dir = task_dir

    def _resolve_task_dir(self):
        if self._task_dir is not None:
            return os.path.realpath(self._task_dir)
        rp = self.request.get("result_path") if isinstance(self.request, dict) else None
        if not isinstance(rp, str) or not os.path.isabs(rp):
            raise MusicUnavailable("หาโฟลเดอร์งาน (task dir) ไม่ได้ — request ไม่มี result_path")
        run_dir = Path(os.path.realpath(os.path.dirname(rp)))
        if run_dir.parent.name != "runs" or run_dir.parent.parent.parent.name != "steps":
            raise MusicUnavailable("request ไม่ได้อยู่ใน <task>/steps/<step>/runs/<n>/ — หาโฟลเดอร์งาน (task dir) ไม่ได้")
        return str(run_dir.parent.parent.parent.parent)

    def _music_file(self):
        inputs = self.request.get("inputs") if isinstance(self.request, dict) else None
        found = [i for i in (inputs if isinstance(inputs, list) else []) if isinstance(i, dict) and i.get("role") == "music"]
        if len(found) != 1:
            raise MusicUnavailable(f"ต้องมี input role music ตัวเดียว (พบ {len(found)}) — ขั้นสร้างเพลงของ AIOS ยังไม่ส่งเพลงมา")
        files = found[0].get("files")
        if not isinstance(files, list) or not all(isinstance(f, str) and os.path.isabs(f) for f in files):
            raise MusicUnavailable("input music: files ต้องเป็น list ของ absolute path")
        mp3 = [f for f in files if os.path.basename(f).endswith(MUSIC_SUFFIX)]
        if len(mp3) != 1:
            raise MusicUnavailable(f"ไม่พบไฟล์ *{MUSIC_SUFFIX} ตัวเดียวในรายการ files ของ input music (พบ {len(mp3)})")
        return mp3[0]

    def get_music(self, duration_s, mood, out_path):
        real_task = self._resolve_task_dir()
        real = os.path.realpath(self._music_file())
        if not real.startswith(real_task + os.sep):
            raise MusicUnavailable("ไฟล์เพลงอยู่นอกโฟลเดอร์งาน (task dir)")
        p = Path(real)
        if not p.is_file():
            raise MusicUnavailable(f"ไม่พบไฟล์เพลง: {p.name}")
        if p.stat().st_size <= 0:
            raise MusicUnavailable(f"ไฟล์เพลงว่าง: {p.name}")
        info = common.probe(p, common.Deadline(60))
        if not common.streams_of(info, "audio"):
            raise MusicUnavailable(f"ไฟล์เพลง {p.name} ไม่มี audio stream")
        try:
            dur = float(info.get("format", {}).get("duration"))
        except (TypeError, ValueError):
            dur = 0.0
        if not dur > 0:
            raise MusicUnavailable(f"ไฟล์เพลง {p.name} ความยาวไม่ถูกต้อง")
        check_music_duration(dur, duration_s)
        return p


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


def validate_music(path, deadline, min_duration_s=None):
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
    if min_duration_s is not None:
        try:
            check_music_duration(dur, min_duration_s)
        except MusicUnavailable as e:        # enforced for every provider; nothing paid by the skill
            raise common.GgError(str(e))
    return info


def build_music_bed(music, duration_s, out_wav, deadline):
    """Trim to the video length (never loop), 0.1 s fade-in, 1.2 s fade-out, two-pass loudnorm (I=-14, TP=-2)
    -> 48 kHz stereo wav. Music too peaky for a linear gain gets gain + peak limiter instead (see below)."""
    ffmpeg = common.find_tool("ffmpeg")
    chain = (f"aformat=sample_rates=48000:channel_layouts=stereo,"
             f"afade=t=in:st=0:d={FADE_IN_S:g},"
             f"afade=t=out:st={max(duration_s - FADE_OUT_S, 0):.3f}:d={FADE_OUT_S:g}")
    base = [ffmpeg, "-nostdin", "-hide_banner", "-nostats", "-v", "info", "-t", f"{duration_s:.3f}", "-i", music,
            "-map", "0:a:0"]
    ln = f"loudnorm=I={TARGET_I:g}:TP={TARGET_TP:g}:LRA={TARGET_LRA:g}"
    m = _loudnorm_run(base + ["-af", f"{chain},{ln}:print_format=json", "-f", "null", "-"], deadline, "วัดความดังเพลง (pass 1)")
    gain = TARGET_I - m["input_i"]
    if m["input_tp"] + gain <= TARGET_TP:      # a purely linear gain reaches -14 LUFS under the true-peak target
        second = (f"{chain},{ln}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
                  f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true:print_format=summary")
        common.run_cmd(base + ["-af", second, "-c:a", "pcm_f32le", "-ar", "48000", "-y", out_wav], deadline,
                       "ปรับความดังเพลง (pass 2)")
        return
    # Peaky music (crest factor too high for a linear gain): loudnorm would fall back to dynamic mode and undershoot
    # the target. Use gain + peak limiter instead, iterating the gain until the limited result measures on target.
    limiter = f"alimiter=limit={10 ** ((TARGET_TP - LIMITER_HEADROOM_DB) / 20):.4f}:attack=5:release=60:level=0"
    for _ in range(LIMITER_ITERATIONS):
        shaped = f"{chain},volume={gain:.3f}dB,{limiter}"
        meas = _loudnorm_run(base + ["-af", f"{shaped},loudnorm=I={TARGET_I:g}:TP={TARGET_TP:g}:LRA=20:print_format=json",
                                     "-f", "null", "-"], deadline, "วัดความดังเพลงหลังลิมิตเตอร์")
        err = TARGET_I - meas["input_i"]
        if abs(err) <= LIMITER_TOL_I:
            break
        gain += err
    shaped = f"{chain},volume={gain:.3f}dB,{limiter}"
    common.run_cmd(base + ["-af", shaped, "-c:a", "pcm_f32le", "-ar", "48000", "-y", out_wav], deadline,
                   "ปรับความดังเพลง (gain + limiter)")


def mux(video, bed_wav, out_path, deadline):
    common.run_cmd([common.find_tool("ffmpeg"), "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", video, "-i", bed_wav,
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "48000", "-ac", "2", "-movflags", "+faststart", out_path], deadline, "ffmpeg mux")
