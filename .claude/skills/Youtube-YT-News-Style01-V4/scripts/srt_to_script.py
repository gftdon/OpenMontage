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

A cue boundary is a script line break, and a line break must not split a word. With --script, every cue
boundary that is Thai|Thai (or that puts a mai yamok at the start of a line) is judged by the ONE rule of
thai_junction.py, the same one lint_captions.py applies to the finished script. Where it fails, the two cues
are merged into one line, a slice of the ORIGINAL script that spans both (nothing is added or removed), and the
new junction is judged again. A judged junction needs node (ICU) and pythainlp: without them the command exits 4
("ERROR: required tool missing"); the fallback path (no --script, or the streams differ) needs neither.
Exit: 0 ok, 1 --strict and the streams differ, 4 required tool / shared module missing.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import thai_junction as tj
except Exception as _e:   # exit 1 means "the SRT differs from the source" to finalize; a missing module is exit 4
    print(f"ERROR: required tool missing: cannot import thai_junction.py next to {Path(__file__).name}: {_e}",
          file=sys.stderr)
    sys.exit(4)

_QUOTES = "“”\"„«»"
_ARROWS = "→←➜⇒"
is_thai = tj.is_thai


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


_kept = tj.kept                      # the character stream compared with the source: shared, byte-identical to before
script_text_clean = tj.source_clean  # original script without heading lines / blank lines / tags


def _context(a: str, b: str) -> str:
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    lo = max(0, i - 20)
    return (f"first difference at stream offset {i}: "
            f"srt=...{a[lo:i + 20]!r} script=...{b[lo:i + 20]!r}")


def align_to_script(cue_texts: list[str], script_text: str):
    """Return (lines, None) when the streams are identical, else (None, warning).

    Every cue becomes the matching slice of the original script. A cue boundary that fails
    thai_junction.thai_junction_ok (a word cut in two, or a line starting with the mai yamok) is merged: the two
    cues become ONE slice that spans both, then the next boundary is judged against the merged line. Raises
    thai_junction.ToolMissing (or RuntimeError / SubprocessError) when a judged boundary exists and node or
    pythainlp is unusable."""
    script = script_text_clean(script_text)
    sk = _kept(script)
    script_stream = "".join(c for c, _ in sk)
    cue_streams = ["".join(c for c, _ in _kept(t)) for t in cue_texts]
    srt_stream = "".join(cue_streams)
    if srt_stream != script_stream:
        return None, _context(srt_stream, script_stream)
    cues, pos = [], 0   # (first, last, kept offset of the first kept char): slices of the cleaned script
    for cs in cue_streams:
        if not cs:
            continue
        first, last = sk[pos][1], sk[pos + len(cs) - 1][1]
        cues.append((first, last, pos))
        pos += len(cs)

    def text_of(first, last):
        return clean(script[first:last + 1])

    texts = [text_of(f, l) for f, l, _ in cues]
    first_pass = [tj.break_probe(texts[i], texts[i + 1]) for i in range(len(texts) - 1)]
    judged = [pr for pr in first_pass if pr is not None]
    bsets = {}
    src_ws = set()
    if judged:
        tj.check_tools()   # raises ToolMissing: never a silent "no merge"
        print(tj.identity_line(), file=sys.stderr)   # which node / ICU / pythainlp judged this (stdout and the output stay unchanged)
        bsets = tj.boundary_sets([l + r for l, r in judged])
        src_ws = tj.source_whitespace(script_text)[1]
    lines = []
    cur_first, cur_last, cur_pos = cues[0] if cues else (0, -1, 0)
    for nxt_first, nxt_last, nxt_pos in cues[1:]:
        pr = tj.break_probe(text_of(cur_first, cur_last), text_of(nxt_first, nxt_last))
        run, n_lead = tj.facing_run(text_of(cur_first, cur_last), text_of(nxt_first, nxt_last))
        src_ok = tj.judge_run(run, nxt_pos + n_lead, src_ws, "break")[0]
        if pr is None or tj.thai_junction_ok(pr[0], pr[1], "break", bsets, src_ok):
            lines.append(text_of(cur_first, cur_last))
            cur_first, cur_last, cur_pos = nxt_first, nxt_last, nxt_pos
        else:
            cur_last = nxt_last   # merge: one slice of the source that spans both cues
    if cues:
        lines.append(text_of(cur_first, cur_last))
    return [l for l in lines if l], None


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
        try:
            sliced, warning = align_to_script(lines, open(a.script, encoding="utf-8-sig").read())
        except (tj.ToolMissing, RuntimeError, subprocess.SubprocessError) as e:
            print(f"ERROR: required tool missing: {e}", file=sys.stderr)
            return 4
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
