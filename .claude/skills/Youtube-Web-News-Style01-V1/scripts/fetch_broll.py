"""Fetch stock b-roll (Pixabay, free licence) through the OpenMontage tool registry.

  .venv/bin/python fetch_broll.py QUERIES.json OUT_DIR [--music "query" MUSIC_OUT.mp3]

QUERIES.json = {"coding": ["programmer coding laptop screen", "computer"], ...}
(key -> [search query, pixabay category]). Downloads the first matching clip per
key as OUT_DIR/<key>.mp4 (8-40 s, 'large' quality). Skips keys already present.
Always view a contact sheet of the results afterwards — the first hit is wrong
often enough (a "shopping" query returned a kitchen blender) that ~1 in 5 picks
needs a replacement query.

Run from the repo root with the project .venv (PIXABAY_API_KEY in .env).
"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())
from dotenv import load_dotenv  # noqa: E402

load_dotenv(".env")
from tools.tool_registry import registry  # noqa: E402

registry.discover()


def fetch_videos(queries_path: str, out_dir: str) -> None:
    pv = registry._tools["pixabay_video"]
    os.makedirs(out_dir, exist_ok=True)
    queries = json.load(open(queries_path, encoding="utf-8"))
    for key, (q, cat) in queries.items():
        path = os.path.join(out_dir, f"{key}.mp4")
        if os.path.exists(path):
            print("skip", key)
            continue
        r = pv.execute({"query": q, "category": cat, "min_duration": 8, "max_duration": 40,
                        "per_page": 8, "output_path": path, "preferred_quality": "large"})
        print(key, "OK" if r.success else f"FAIL {r.error}")


def fetch_music(query: str, out_path: str) -> None:
    pm = registry._tools["pixabay_music"]
    r = pm.execute({"query": query, "min_duration": 120, "max_duration": 400, "output_path": out_path})
    print("music", "OK" if r.success else f"FAIL {r.error}", (r.data or {}).get("track_title"))


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--music" in args:
        i = args.index("--music")
        fetch_music(args[i + 1], args[i + 2])
        args = args[:i]
    if len(args) >= 2:
        fetch_videos(args[0], args[1])
