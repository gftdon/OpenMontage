"""Extract word-level karaoke caption pages from a video's audio.

Uses the karaoke-subtitle skill's mlx-whisper + exact-script alignment so the
on-screen wording matches the script EXACTLY while timing comes from Whisper's
own word/char timestamps. Output is a JSON list of caption pages:

  [{"start": float, "end": float, "words": [{"w": str, "s": float, "e": float}]}]

Run with the karaoke venv python (mlx-whisper + pythainlp live there, NOT in
the project .venv):

  ~/.cache/karaoke-subtitle/venv/bin/python extract_timing.py \
      --wav vo.wav --script script.txt --out caption_pages.json

First run downloads the Whisper model (~1.6 GB) once into the HF cache.
If the venv is missing, run: bash ~/.claude/skills/karaoke-subtitle/scripts/setup.sh
"""
import argparse
import json
import sys

SKILL = "/Users/nunmacminim4pro/.claude/skills/karaoke-subtitle/scripts"
sys.path.insert(0, SKILL)

from make_karaoke_sub import transcribe, apply_script, read_script_lines  # noqa: E402
from karaoke_lib import build_chunks  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", required=True, help="16 kHz mono wav of the VO audio")
    ap.add_argument("--script", required=True, help="plain .txt of spoken lines, in order")
    ap.add_argument("--out", required=True, help="output JSON path")
    ap.add_argument("--model", default="mlx-community/whisper-large-v3-mlx")
    ap.add_argument("--lang", default="th")
    ap.add_argument("--max-words", type=int, default=4)
    ap.add_argument("--max-chars", type=int, default=24)
    ap.add_argument("--pause", type=float, default=0.42)
    a = ap.parse_args()

    result = transcribe(a.wav, model=a.model, lang=a.lang)
    lines = read_script_lines(a.script)
    print(f"script lines: {len(lines)}")
    result = apply_script(result, lines)

    chunks = build_chunks(result, max_words=a.max_words, max_chars=a.max_chars, pause=a.pause)

    pages = []
    for ch in chunks:
        words = [
            {"w": w["tok"], "s": round(w["start"], 3), "e": round(w["end"], 3)}
            for w in ch["words"]
        ]
        if words:
            pages.append({
                "start": round(words[0]["s"], 3),
                "end": round(words[-1]["e"], 3),
                "words": words,
            })

    json.dump(pages, open(a.out, "w"), ensure_ascii=False, indent=1)
    print(f"wrote {len(pages)} pages -> {a.out}")
    for p in pages[:6]:
        print(f"  {p['start']:7.2f}-{p['end']:7.2f}  " + "|".join(w["w"] for w in p["words"]))


if __name__ == "__main__":
    main()
