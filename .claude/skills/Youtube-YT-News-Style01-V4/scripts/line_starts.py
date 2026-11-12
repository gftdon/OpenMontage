"""Per-script-line whisper start/end times — the timing spine for all beats.

WHY THIS EXISTS: vendor SRT cue times (HeyGen etc.) drift non-linearly vs the
actual audio (measured up to -4.1s mid-video on EP.1). Captions are whisper-
timed, so any visual keyed to SRT times fires out of sync with them. Every
BEAT t, kicker, chip swap, and typo sub-animation must be keyed to the times
this script prints, never to SRT times.

Reads the raw word-timing pages (word_timing.sh output / caption_pages.json:
[{start,end,words:[{w,s,e}]}]; a page MAY cross script lines) plus script.txt,
flattens the word tokens and maps them to script lines by characters with the
shared matcher of words_by_line.py (whitespace-insensitive, one consumption
order, strict: any token that does not match the script is a hard error).

  line start = start time (s) of the first token that BEGINS in the line (a token that
               straddles a line break belongs to the line of its first character)
  line end   = latest end time (e) of the tokens that begin in the line
A line in which no token begins is an error; no time is ever invented.

  python3 line_starts.py --pages caption_pages.json --script script.txt --out line_starts.json

Output (unchanged): [{"line": 1-based spoken-line number, "start", "end", "text": first 60 chars}].
Blank script lines are ignored and do not count.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from words_by_line import MappingError, flatten, map_tokens, norm, spoken_lines  # noqa: E402,F401  (map_tokens is the shared matcher)


class LineStartsError(ValueError):
    pass


def compute_line_starts(pages, script_lines):
    script_lines = [l for l in script_lines if l.strip()]
    tokens = flatten(pages)
    try:
        lines = map_tokens(tokens, script_lines, strict=True)
    except MappingError as e:
        raise LineStartsError(str(e))
    out = []
    for idx, line_text in enumerate(script_lines):
        mine = [t for t, l in zip(tokens, lines) if l == idx + 1 and norm(t['w'])]
        if not mine:
            raise LineStartsError('line %d: no word token begins in this line (a token spans it entirely?): %s' % (idx + 1, norm(line_text)[:60]))
        out.append({
            'line': idx + 1,
            'start': round(mine[0]['s'], 3),
            'end': round(max(t['e'] for t in mine), 3),
            'text': line_text[:60],
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", required=True, help="caption_pages.json (raw word_timing.sh pages; may cross script lines)")
    ap.add_argument("--script", required=True, help="script.txt, one spoken line per row")
    ap.add_argument("--out", required=True, help="output JSON")
    a = ap.parse_args()

    try:
        pages = json.load(open(a.pages))
        script_lines = spoken_lines(open(a.script, encoding="utf-8").read())
        out = compute_line_starts(pages, script_lines)
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise SystemExit("line_starts: %s" % e)

    json.dump(out, open(a.out, "w"), ensure_ascii=False, indent=1)
    print(f"wrote {a.out}: {len(out)} lines")
    for r in out:
        print(f"  L{r['line']:>3}  {r['start']:>8.2f} - {r['end']:>8.2f}  {r['text'][:44]}")


if __name__ == "__main__":
    main()
