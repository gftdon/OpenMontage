#!/usr/bin/env python3
"""Signature shots for an episode: still (image tool) -> Kling image-to-video, or Kling text-to-video, -> 1080p25 mp4.

usage (from the repo root, .venv python):
  gen_shots.py SHOTS.json GEN_DIR PUBLIC_BROLL_DIR images     # stills via IMAGE_TOOL (default flux_image)
  gen_shots.py SHOTS.json GEN_DIR PUBLIC_BROLL_DIR videos     # Kling: i2v when <name>.png exists, else t2v
  gen_shots.py SHOTS.json GEN_DIR PUBLIC_BROLL_DIR transcode  # -> PUBLIC_BROLL_DIR/<name>.mp4 + BROLL_DUR lines

SHOTS.json: {"style": "<suffix appended to every image prompt>",
             "shots": {"gen_glitch": {"image": "...", "motion": "..."}, ...}}
Env: IMAGE_TOOL=flux_image|google_imagen (registry tool name). FAL_KEY for Kling.
Cost 2026-09: Kling v3/standard 5 s ≈ $0.10 (720p24; i2v needs a URL — upload_image_fal or a data URL).
"""
import base64, json, os, subprocess, sys, threading, time
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(".env")
from tools.tool_registry import registry  # noqa: E402

cfg = json.load(open(sys.argv[1]))
GEN = Path(sys.argv[2]); GEN.mkdir(parents=True, exist_ok=True)
PUB = Path(sys.argv[3]); PUB.mkdir(parents=True, exist_ok=True)
MODE = sys.argv[4]
STYLE = cfg.get("style", "")
SHOTS = cfg["shots"]
IMAGE_TOOL = os.environ.get("IMAGE_TOOL", "flux_image")

def images():
    registry.discover()
    tool = registry._tools[IMAGE_TOOL]
    for name, s in SHOTS.items():
        out = GEN / f"{name}.png"
        if out.exists():
            print("skip", name); continue
        r = tool.execute({"prompt": (s["image"] + " " + STYLE).strip(), "aspect_ratio": "16:9", "output_path": str(out)})
        print(name, "ok" if r.success else "FAIL", r.error or "", flush=True)

def image_url_for(png: Path) -> str:
    try:
        from tools.video._shared import upload_image_fal
        return upload_image_fal(str(png))
    except Exception as e:  # noqa
        print("upload_image_fal failed -> data URL:", str(e)[:100])
        return "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode()

def one_video(name, s, results):
    registry.discover()
    tool = registry._tools["kling_video"]
    png = GEN / f"{name}.png"
    out = GEN / f"{name}_raw.mp4"
    t0 = time.time()
    if png.exists():
        inputs = {"prompt": s["motion"], "operation": "image_to_video", "image_url": image_url_for(png)}
    else:
        inputs = {"prompt": (s["image"] + " " + STYLE + " " + s["motion"]).strip(), "operation": "text_to_video"}
    inputs.update({"duration": "5", "aspect_ratio": "16:9", "model_variant": "v3/standard", "output_path": str(out)})
    r = tool.execute(inputs)
    results[name] = {"ok": r.success, "err": r.error, "secs": round(time.time() - t0), "op": inputs["operation"], "cost": (r.data or {}).get("cost")}
    print(name, inputs["operation"], "ok" if r.success else "FAIL", r.error or "", f"{round(time.time()-t0)}s", flush=True)

def videos():
    results = {}
    threads = [threading.Thread(target=one_video, args=(n, s, results)) for n, s in SHOTS.items() if not (GEN / f"{n}_raw.mp4").exists()]
    for t in threads: t.start()
    for t in threads: t.join()
    json.dump(results, open(GEN / "videos.json", "w"), indent=2)

def transcode():
    for name in SHOTS:
        raw = GEN / f"{name}_raw.mp4"
        if not raw.exists():
            print("missing", raw); continue
        out = PUB / f"{name}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-vf", "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=25", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-an", str(out)], check=True)
        d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
        print(f"BROLL_DUR {name}={float(d):.2f}")

{"images": images, "videos": videos, "transcode": transcode}[MODE]()
