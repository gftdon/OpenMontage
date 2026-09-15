"""Extract a clean script.txt from an SRT file: one line per cue, text only.

The SRT is trusted for TEXT (it is the exact spoken script) but never for
TIMING (HeyGen SRT drifts up to -4.1s vs the actual audio). The output feeds
karaoke_subtitle_v2's extract_timing.py --script, which char-aligns whisper
output onto these exact lines.

  python3 srt_to_script.py --srt source.srt --out script.txt
"""
import argparse
import re


def parse(srt_text: str) -> list[str]:
    lines_out = []
    # Normalize newlines, split into cue blocks on blank lines.
    blocks = re.split(r"\n\s*\n", srt_text.replace("\r\n", "\n").replace("\r", "\n"))
    for block in blocks:
        rows = [r.strip() for r in block.strip().split("\n") if r.strip()]
        if not rows:
            continue
        # Drop leading index row and the timestamp row.
        if re.fullmatch(r"\d+", rows[0]):
            rows = rows[1:]
        rows = [r for r in rows if "-->" not in r]
        if not rows:
            continue
        text = " ".join(rows)
        text = re.sub(r"<[^>]+>", "", text)          # strip html-ish tags
        text = text.replace(" ", " ")           # NBSP
        # Unspoken glyphs break whisper char-alignment: quotes vanish, arrows
        # become a word gap. (Apostrophes kept — they appear inside words.)
        text = re.sub(r"[“”\"„«»]", "", text)
        text = re.sub(r"[→←➜⇒]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            lines_out.append(text)
    return lines_out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--srt", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    lines = parse(open(a.srt, encoding="utf-8-sig").read())
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {a.out}: {len(lines)} script lines")


if __name__ == "__main__":
    main()
