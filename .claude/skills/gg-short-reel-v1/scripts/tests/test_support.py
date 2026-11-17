"""Shared fixtures for the gg-short-reel-v1 tests (no tests in this module).

Builds a fake AIOS task dir with ffmpeg lavfi clips (2 video streams each) so the
full pipeline can be exercised offline. Source clips are generated once per test
process and copied per test.
"""
import atexit
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def tool(name):
    return shutil.which(name) or (f"/opt/homebrew/bin/{name}" if os.path.exists(f"/opt/homebrew/bin/{name}") else None)


FFMPEG = tool("ffmpeg")
FFPROBE = tool("ffprobe")
HAVE_FFMPEG = bool(FFMPEG and FFPROBE)
needs_ffmpeg = unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe not installed")

_CACHE = None


def cache_dir():
    global _CACHE
    if _CACHE is None:
        _CACHE = Path(tempfile.mkdtemp(prefix="ggsr-cache-")).resolve()
        atexit.register(shutil.rmtree, str(_CACHE), True)
    return _CACHE


def make_clip(path, *, w=416, h=752, frames=150, base=20, step=3, two_video=True, fps=30):
    """Clip whose frame N is uniform gray level clip(base+step*N); 2 video streams + 1 audio."""
    key = hashlib.sha1(json.dumps([w, h, frames, base, step, two_video, fps]).encode()).hexdigest()[:16]
    cached = cache_dir() / f"clip-{key}.mp4"
    if not cached.exists():
        tmp = cache_dir() / f"tmp-{key}.mp4"
        cmd = [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
               f"color=c=black:s={w}x{h}:r={fps},geq=lum='clip({base}+{step}*N,0,255)':cb=128:cr=128"]
        if two_video:
            cmd += ["-f", "lavfi", "-i", f"color=c=red:s={w}x{h}:r={fps}"]
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=300:sample_rate=44100:duration={frames / fps + 1:.3f}"]
        cmd += ["-map", "0:v"] + (["-map", "1:v", "-map", "2:a"] if two_video else ["-map", "1:a"])
        cmd += ["-frames:v", str(frames), "-c:v", "libx264", "-preset", "ultrafast", "-crf", "10",
                "-pix_fmt", "yuv420p", "-c:a", "aac", str(tmp)]
        subprocess.run(cmd, check=True)
        tmp.replace(cached)
    shutil.copy(cached, path)


MUSIC_NOISE_SEED = 8501  # fixed anoisesrc seed: the fixture must be byte-identical on every generation


def make_music(path, *, seconds=14.0, kind="tone", amp=0.3, freq=440, video_only=False):
    """AIOS-style music fixture (mp3). kind: 'tone' (steady sine), 'bursts' (loud transient-rich pink-noise bursts)."""
    key = hashlib.sha1(json.dumps(["music", seconds, kind, amp, freq, video_only, MUSIC_NOISE_SEED]).encode()).hexdigest()[:16]
    cached = cache_dir() / f"music-{key}.bin"
    if not cached.exists():
        tmp = cache_dir() / f"tmp-{key}.bin"
        if video_only:   # content is an mp4 with no audio (the name still says .mp3)
            cmd = [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=blue:s=64x64:r=10:d={seconds}",
                   "-pix_fmt", "yuv420p", "-f", "mp4", str(tmp)]
        elif kind == "bursts":
            cmd = [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", f"anoisesrc=d={seconds}:c=pink:a={amp}:r=44100:seed={MUSIC_NOISE_SEED}",
                   "-af", "volume='if(lt(mod(t,0.8),0.06),1,0.1)':eval=frame", "-c:a", "libmp3lame", "-b:a", "192k",
                   "-f", "mp3", str(tmp)]
        else:
            cmd = [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
                   f"sine=frequency={freq}:sample_rate=44100:duration={seconds}",
                   "-af", f"volume={amp}", "-c:a", "libmp3lame", "-b:a", "192k", "-f", "mp3", str(tmp)]
        subprocess.run(cmd, check=True)
        tmp.replace(cached)
    shutil.copy(cached, path)


def probe(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def frame_levels(path):
    """Mean Y of every decoded frame (scaled to 16x16, area average)."""
    r = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-map", "0:v:0", "-vf",
                        "scale=16:16:flags=area,format=yuv420p", "-f", "rawvideo", "-"],
                       capture_output=True, check=True)
    data, size = r.stdout, 16 * 16 * 3 // 2
    return [sum(data[i:i + 256]) / 256.0 for i in range(0, len(data), size)]


def frame_md5s(path):
    r = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-map", "0:v:0", "-f", "framemd5", "-"],
                       capture_output=True, text=True, check=True)
    return [ln.split(",")[-1].strip() for ln in r.stdout.splitlines() if ln and not ln.startswith("#")]


def measure_loudness(path):
    """Independent measurement (not via the module under test): (integrated LUFS, true peak dBTP)."""
    r = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0", "-af",
                        "loudnorm=I=-14:TP=-1.5:LRA=20:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, check=True)
    d = json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1])
    return float(d["input_i"]), float(d["input_tp"])


DEFAULT_SHOTS = [
    {"w": 416, "h": 752, "frames": 150, "continues": False},
    {"w": 400, "h": 736, "frames": 150, "continues": True},
    {"w": 416, "h": 752, "frames": 60, "continues": False},
]  # 150 + 149 + 60 = 359 frames = 11.967 s

DEFAULT_TEXTS = [
    {"text": "จังหวะนี้ใครก็ไม่คาด", "start_s": 0.5, "end_s": 3.0, "placement": "top"},
    {"text": "Look closely at the second shot", "start_s": 3.0, "end_s": 6.0, "placement": "center"},
    {"text": "ติดตามตอนต่อไป", "start_s": 8.0, "end_s": 99.0, "placement": "bottom"},
]


class Task:
    def __init__(self, root, shots=None, texts=None, mood="warm", code="V261117_001", workflow=True,
                 music=True, music_seconds=14.0, music_kind="tone", music_amp=0.3):
        self.root = Path(root).resolve()
        self.code = code
        self.dir = self.root / "task"
        self.script_dir = self.dir / "steps/script/runs/1"
        self.clips_dir = self.dir / "steps/ai_clip/runs/1" / f"{code}_20_Clips"
        self.run_dir = self.dir / "steps/edit_short/runs/1"
        for d in (self.script_dir, self.clips_dir, self.run_dir):
            d.mkdir(parents=True)
        self.request_path = self.run_dir / "request.json"
        self.result_path = self.run_dir / "result.json"
        self.final = self.run_dir / f"{code}_40_Short_Final.mp4"
        self.shots_spec = copy.deepcopy(shots if shots is not None else DEFAULT_SHOTS)
        self.texts = copy.deepcopy(texts if texts is not None else DEFAULT_TEXTS)
        self.script_path = self.script_dir / f"{code}_00_Script.txt"
        self.orig_path = self.script_dir / "originality.json"
        self.manifest_path = self.clips_dir / "manifest.json"
        self.manifest = {"schema": 1, "run_id": "run-clips-1", "shots": []}
        self.clip_files = []
        for i, s in enumerate(self.shots_spec, start=1):
            f = self.clips_dir / f"shot-{i}.mp4"
            make_clip(f, w=s["w"], h=s["h"], frames=s["frames"], fps=s.get("fps", 30),
                      base=s.get("base", 20), step=s.get("step", 3))
            self.clip_files.append(f)
            shot = {"seq": i, "kind": "grok_i2v_continue" if s["continues"] else "grok_t2v",
                    "file": str(f.relative_to(self.dir)), "duration_s": s["frames"] / 30,
                    "actual_duration_s": s["frames"] / 30, "width": s["w"], "height": s["h"]}
            if s["continues"]:
                shot["continues_from_seq"] = i - 1
            self.manifest["shots"].append(shot)
        self.script = {"shots": [{"seq": i, "prompt": "p", "duration_s": 5} for i in range(1, len(self.shots_spec) + 1)],
                       "on_screen_text": self.texts, "post_caption": "c", "hashtags": ["#a"]}
        if workflow:
            (self.dir / "workflow.json").write_text(json.dumps(
                {"viral": {"production_plan": {"audio": {"type": "ai_music", "mood": mood}}}}))
        # AIOS `music` step output (produced and paid for by AIOS, never by the skill)
        self.music_dir = self.dir / "steps/music/runs/1"
        self.music_path = self.music_dir / f"{code}_30_Music.mp3"
        self.music_input = None
        if music:
            self.music_dir.mkdir(parents=True)
            make_music(self.music_path, seconds=music_seconds, kind=music_kind, amp=music_amp)
            (self.music_dir / "music-state.json").write_text('{"schema":1}')
            (self.music_dir / "result.json").write_text('{"status":"succeeded"}')
            self.music_input = {"role": "music", "step_id": "music", "run_id": "run-music-1",
                                "files": [str(self.music_dir / "music-state.json"), str(self.music_dir / "result.json"),
                                          str(self.music_path)]}
        self.script_input_run_id = "run-script-1"
        self.clips_input_run_id = "run-clips-1"
        self.extra_clip_files = []
        self.write_all()

    def write_all(self):
        self.script_path.write_bytes(json.dumps(self.script, indent=2, ensure_ascii=False).encode("utf-8"))
        self.write_originality()
        self.manifest_path.write_text(json.dumps(self.manifest, indent=2))
        self.write_request()

    def write_originality(self, sha=None, passed=True):
        sha = sha or hashlib.sha256(self.script_path.read_bytes()).hexdigest()
        self.orig_path.write_text(json.dumps({"schema": 1, "pass": passed, "script_sha256": sha,
                                              "checked_at": "2026-11-17T00:00:00.000Z", "model": "m", "reasons": []}))

    def write_request(self, **overrides):
        req = {
            "schema": 1, "task_id": "task-1", "step_id": "edit_short", "run_id": "run-edit-1",
            "dispatch_id": "dispatch-1", "target": {"project_id": "open-montage", "config_ref": "cfg-1"},
            "kind": "edit_short", "aspect": "9:16", "prompt": "x",
            # list order deliberately unlike AIOS: manifest first, originality before script
            "inputs": [
                {"role": "script", "step_id": "script", "run_id": self.script_input_run_id,
                 "files": [str(self.orig_path), str(self.script_path)]},
                {"role": "clips", "step_id": "ai_clip", "run_id": self.clips_input_run_id,
                 "files": [str(self.manifest_path)] + [str(f) for f in self.clip_files] + self.extra_clip_files},
            ],
            "outputs": [str(self.final)], "result_path": str(self.result_path),
        }
        if self.music_input is not None:
            req["inputs"].append(copy.deepcopy(self.music_input))
        req.update(overrides)
        self.request = req
        self.request_path.write_text(json.dumps(req))
        return req

    def result(self):
        return json.loads(self.result_path.read_text())

    def run_dir_names(self):
        return sorted(p.name for p in self.run_dir.iterdir())


class FakeMusic:
    """Injected music provider for tests (the real one does not exist yet)."""
    is_paid = False

    def __init__(self, mode="tone", seconds=None, freq=440, amp=0.3, exc=None):
        self.mode, self.seconds, self.freq, self.amp, self.exc = mode, seconds, freq, amp, exc
        self.calls = []

    def get_music(self, duration_s, mood, out_path):
        self.calls.append((duration_s, mood, Path(out_path)))
        out = Path(out_path)
        if self.mode == "raise":
            raise self.exc
        if self.mode == "missing":
            return out.with_name("does-not-exist.wav")
        if self.mode == "empty":
            out.write_bytes(b"")
            return out
        if self.mode == "noaudio":
            out = out.with_suffix(".mp4")
            subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=10:d=3",
                            "-pix_fmt", "yuv420p", str(out)], check=True)
            return out
        secs = self.seconds if self.seconds is not None else duration_s + 2
        subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"sine=frequency={self.freq}:sample_rate=44100:duration={secs}",
                        "-af", f"volume={self.amp}", str(out)], check=True)
        return out
