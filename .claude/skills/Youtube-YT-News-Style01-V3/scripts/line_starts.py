"""Per-script-line whisper start/end times — the timing spine for all beats.

WHY THIS EXISTS: vendor SRT cue times (HeyGen etc.) drift non-linearly vs the
actual audio (measured up to -4.1s mid-video on EP.1). Captions are whisper-
timed, so any visual keyed to SRT times fires out of sync with them. Every
BEAT t, kicker, chip swap, and typo sub-animation must be keyed to the times
this script prints, never to SRT times.

Reads the REPAGED pages (caption_pages_final.json — pages never cross script
lines) plus script.txt, maps each page back to its script line by walking the
concatenated normalized text (same algorithm as karaoke_subtitle_v2/repage.py,
which deletes the line field before writing), and emits per-line start/end.

  python3 line_starts.py --pages caption_pages_final.json --script script.txt \
      --out line_starts.json
"""
import argparse
import json
import re


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def map_pages_to_lines(pages, script_lines):
    norm_lines = [norm(l) for l in script_lines if l.strip()]
    page_line = []
    li, pos = 0, 0
    for p in pages:
        first_word_line = None
        for w in p["words"]:
            t = norm(w["w"])
            while li < len(norm_lines) and not norm_lines[li][pos:].startswith(t):
                pos += 1
                if pos >= len(norm_lines[li]):
                    li += 1
                    pos = 0
                    if li >= len(norm_lines):
                        break
            if first_word_line is None:
                first_word_line = li if li < len(norm_lines) else len(norm_lines) - 1
            pos += len(t)
            if li < len(norm_lines) and pos >= len(norm_lines[li]):
                li += 1
                pos = 0
        page_line.append(first_word_line)
    return page_line, norm_lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", required=True, help="caption_pages_final.json (repaged)")
    ap.add_argument("--script", required=True, help="script.txt, one spoken line per row")
    ap.add_argument("--out", required=True, help="output JSON")
    a = ap.parse_args()

    pages = json.load(open(a.pages))
    script_lines = [l for l in open(a.script, encoding="utf-8").read().splitlines() if l.strip()]
    page_line, _ = map_pages_to_lines(pages, script_lines)

    out = []
    for idx, line_text in enumerate(script_lines):
        mine = [p for p, ln in zip(pages, page_line) if ln == idx]
        if not mine:
            raise SystemExit(f"line {idx + 1} matched no caption pages — check script/pages pair")
        # Self-check: the pages assigned to this line must reproduce exactly
        # the line's text. Guarantees the mapping walk didn't slip a page.
        joined = norm("".join(w["w"] for p in mine for w in p["words"]))
        if joined != norm(line_text):
            raise SystemExit(
                f"line {idx + 1} mapping mismatch:\n  script: {norm(line_text)[:80]}\n  pages:  {joined[:80]}"
            )
        out.append({
            "line": idx + 1,
            "start": round(min(p["start"] for p in mine), 3),
            "end": round(max(p["end"] for p in mine), 3),
            "text": line_text[:60],
        })

    json.dump(out, open(a.out, "w"), ensure_ascii=False, indent=1)
    print(f"wrote {a.out}: {len(out)} lines")
    for r in out:
        print(f"  L{r['line']:>3}  {r['start']:>8.2f} - {r['end']:>8.2f}  {r['text'][:44]}")


if __name__ == "__main__":
    main()
