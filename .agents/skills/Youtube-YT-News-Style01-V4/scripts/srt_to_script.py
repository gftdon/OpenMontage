"""Extract a clean script.txt from an SRT file: one line per cue, text only.

The SRT is trusted for TEXT (it is the exact spoken script) but never for
TIMING (HeyGen SRT drifts up to -4.1s vs the actual audio). The output is the
script.txt that word_timing.sh aligns onto the whisper word times
(asr_align.py), line for line.

  python3 srt_to_script.py --srt source.srt --out script.txt [--script original.txt [--strict]]

Thai is written without spaces, but the avatar SRT wraps rows in the middle of
words. Rows of one cue are therefore joined with "" when both sides of the
break are Thai characters (a mid-word wrap) and with " " otherwise.

--script is the text authority: when the whitespace-free, quote-stripped
character stream of the cues equals that of the original script (headings such
as "Part 1:" and blank lines dropped), every output line is the matching slice
of the ORIGINAL script, keeping its own whitespace. Otherwise a WARNING goes to
stderr and the Thai-aware join is used (exit 1 with --strict).
"""
import argparse
import re
import sys

_HEADING = re.compile(r"^\s*Part\s*\d+\s*:?\s*$", re.IGNORECASE)
_QUOTES = "“”\"„«»"
_ARROWS = "→←➜⇒"
# Characters that never count towards the text stream.
_SKIP = set(_QUOTES) | set(_ARROWS)


def is_thai(ch: str) -> bool:
    return bool(ch) and "฀" <= ch <= "๿"


def join_rows(rows: list[str]) -> str:
    """Join wrapped rows: no space across a Thai|Thai break, a space otherwise."""
    out = ""
    for row in rows:
        if not out:
            out = row
        elif is_thai(out[-1]) and is_thai(row[0]):
            out += row
        else:
            out += " " + row
    return out


def clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)          # strip html-ish tags
    text = text.replace(" ", " ")           # NBSP
    # Unspoken glyphs break whisper char-alignment: quotes vanish, arrows
    # become a word gap. (Apostrophes kept — they appear inside words.)
    text = re.sub(r"[“”\"„«»]", "", text)
    text = re.sub(r"[→←➜⇒]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


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
        text = clean(join_rows(rows))
        if text:
            lines_out.append(text)
    return lines_out


def _kept(text: str) -> list[tuple[str, int]]:
    """(char, original index) for every char that counts towards the stream."""
    return [(ch, i) for i, ch in enumerate(text) if not ch.isspace() and ch not in _SKIP]


def script_text_clean(script_text: str) -> str:
    """Original script without heading lines / blank lines / tags (lines kept as lines)."""
    script_text = re.sub(r"<[^>]+>", "", script_text.replace("\r\n", "\n").replace("\r", "\n"))
    script_text = script_text.replace(" ", " ")
    keep = [l for l in script_text.split("\n") if l.strip() and not _HEADING.match(l)]
    return "\n".join(keep)


def _context(a: str, b: str) -> str:
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    lo = max(0, i - 20)
    return (f"first difference at stream offset {i}: "
            f"srt=...{a[lo:i + 20]!r} script=...{b[lo:i + 20]!r}")


def align_to_script(cue_texts: list[str], script_text: str):
    """Return (lines, None) when the streams are identical, else (None, warning)."""
    script = script_text_clean(script_text)
    sk = _kept(script)
    script_stream = "".join(c for c, _ in sk)
    cue_streams = ["".join(c for c, _ in _kept(t)) for t in cue_texts]
    srt_stream = "".join(cue_streams)
    if srt_stream != script_stream:
        return None, _context(srt_stream, script_stream)
    lines, pos = [], 0
    for cs in cue_streams:
        if not cs:
            continue
        first, last = sk[pos][1], sk[pos + len(cs) - 1][1]
        pos += len(cs)
        text = clean(script[first:last + 1])
        if text:
            lines.append(text)
    return lines, None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--srt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--script", help="original script file (text authority)")
    ap.add_argument("--strict", action="store_true",
                    help="with --script: exit 1 when the character streams differ")
    a = ap.parse_args(argv)
    lines = parse(open(a.srt, encoding="utf-8-sig").read())
    mode, rc = "Thai-aware join", 0
    if a.script:
        sliced, warning = align_to_script(lines, open(a.script, encoding="utf-8-sig").read())
        if sliced is not None:
            lines, mode = sliced, "original-script slices"
        else:
            print(f"WARNING: SRT text differs from --script; falling back to Thai-aware join. {warning}",
                  file=sys.stderr)
            rc = 1 if a.strict else 0
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {a.out}: {len(lines)} script lines ({mode})")
    return rc


if __name__ == "__main__":
    sys.exit(main())
