"""Lint a V4 project script and caption pages for Thai text split inside words.

  python3 lint_captions.py --script script.txt --pages caption-joined.json \
      [--source-script original_script.txt] --report captions-lint.json

Word-boundary oracle: a position inside Thai text is acceptable when it is a
word boundary of the de-spaced text according to EITHER ICU (node
Intl.Segmenter('th')) OR pythainlp newmm. It is "mid-word" only when NEITHER
engine puts a boundary there. Missing tools are an error (exit 4), never a
silent skip.

Checks
  midword-space         Thai|Thai whitespace in a script line whose removal gives a
                        position that is not a word boundary
  space-not-in-source   (--source-script) Thai|Thai whitespace in the script where
                        the source script has none at the same character-stream offset
  source-stream-mismatch (--source-script) script and source character streams differ,
                        so the source comparison could not run
  midword-page-break    consecutive caption pages that join Thai|Thai at a non-boundary
                        (no whitespace or a plain space between them; a script line break
                        is a real boundary and is skipped), or a Thai|Thai whitespace/line break inside one page's displayText
                        (also: a page or display line that starts with the mai yamok, see below)

One rule for every Thai|Thai junction: thai_junction.thai_junction_ok, shared with srt_to_script.py (which merges
cues at a failing junction, so a correct job never meets it here). kind "space" = whitespace inside a line/page;
kind "break" = a new caption page, a script line, or a line break inside a page. Decided in this order:
  1. the right side starts with the mai yamok (ๆ, U+0E46): "space" passes, "break" FAILS (ๆ may never
     start a page, a display line or a script line);
  2. the left side ends with ๆ: pass (a space or break after ๆ is a normal boundary, "มาก ๆ บน");
  3. ICU or newmm finds a boundary in the joined text: pass;
  4. the junction coincides with whitespace that exists in the SOURCE script at that position, and newmm
     tokenising each side SEPARATELY gives, on EACH side, a token touching the junction that is a
     pythainlp.corpus.thai_words() entry longer than one character ("ว่า|การ", "แล้ว|ไป"): pass. Without
     --source-script, or where the source has no whitespace there (an engine broke a page mid-word), rule 4
     is not available. Accepted risk: a typo IN THE SOURCE whose halves are both words ("แส ดง") passes;
     that is the script step's fault, the edit step cannot change the source;
  5. otherwise FAIL ("ระ|บบ": "บบ" is not a word).
Junctions across a script line break are judged too (between consecutive script lines, and between caption
pages across a line break), on the full lines on each side (thai_junction.break_probe), exactly like the
cue merge in srt_to_script.py. Zero-width Cf characters (U+200B/C/D, U+2060, U+FEFF) count as whitespace
when a junction is FOUND.

Exit: 0 pass, 1 issues, 2 bad/missing input, 4 required tool missing.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from thai_junction import (CF_CHARS, LINE_BREAKS, MAI_YAMOK, SKIP, ToolMissing, WINDOW, boundary_sets,  # noqa: F401
                               break_probe, check_tools, facing_run, identity_line, is_thai, is_ws, judge_run,
                               junction_gaps, kept, lstrip_ws,
                               rstrip_ws, script_stream, source_whitespace, strip_ws, thai_gaps,
                               thai_junction_ok)
except Exception as _e:   # a missing / broken shared module is a missing tool (exit 4), not a quality failure
    print(f"ERROR: required tool missing: cannot import thai_junction.py next to {Path(__file__).name}: {_e}",
          file=sys.stderr)
    sys.exit(4)

SCHEMA = "yt-news-v4-captions-lint"
CODES = ["midword-space", "space-not-in-source", "source-stream-mismatch", "midword-page-break"]


class BadInput(Exception):
    pass


def _show(text: str) -> str:
    return text.replace("\n", "⏎")


def _junction_detail(left, right, kind, where):
    if right[:1] == MAI_YAMOK and kind == "break":
        return f"ๆ starts a {where}: it must stay glued to the word before it"
    return None


def lint_script(lines, source_text=None):
    """Lint project script lines (list of str). Returns issue dicts. Rule 4 of thai_junction_ok needs source_text.
    Judges every Thai|Thai whitespace inside a line AND every junction between two consecutive lines."""
    issues, probes = [], []   # probes: (line_no, kind, left, right, context, index of the right line (between lines) or None, (s, e) or None)
    for idx, line in enumerate(lines, 1):
        for s, e, kind in junction_gaps(line):
            probes.append((idx, kind, line[:s], line[e:], _show(line[max(0, s - 15):e + 15]), None, (s, e)))
    for idx in range(1, len(lines)):
        if lstrip_ws(lines[idx])[:1] == MAI_YAMOK:
            continue   # a line that starts with ๆ is already judged by its own junction_gaps
        pr = break_probe(lines[idx - 1], lines[idx])
        if pr is not None:
            probes.append((idx + 1, "break", pr[0], pr[1], _show(pr[0][-15:] + "\n" + pr[1][:15]), idx, None))
    bsets = boundary_sets([p[2] + p[3] for p in probes])
    src_stream = src_ws = stream = per_line = None
    if source_text is not None:
        src_stream, src_ws = source_whitespace(source_text)
        stream, per_line = script_stream(lines)
    for idx, kind, left, right, ctx, between, se in probes:
        src_ok = False
        if src_ws is not None and stream == src_stream:
            if between is not None:
                run, n_lead = facing_run(lines[between - 1], lines[between])
                src_ok = judge_run(run, per_line[between][0] + n_lead, src_ws, "break")[0]
            else:
                base, pos_to_k = per_line[idx - 1]
                k = pos_to_k.get(se[1])
                src_ok = judge_run(lines[idx - 1][se[0]:se[1]], None if k is None else base + k, src_ws, kind)[0]
        if not thai_junction_ok(left, right, kind, bsets, src_ok):
            what = ("line break" if between is not None else "whitespace")
            issues.append({"code": "midword-space", "line": idx, "t": None,
                           "detail": _junction_detail(left, right, kind, "script line")
                           or f"{what} splits a Thai word (no ICU/newmm boundary, and not two dictionary words at source whitespace)",
                           "context": ctx})
    if source_text is not None:
        issues.extend(_space_not_in_source(lines, source_text))
    issues.sort(key=lambda i: (i.get("line") or 0, i["code"]))
    return issues


def _space_not_in_source(lines, source_text):
    src_stream, src_ws = source_whitespace(source_text)
    stream, per_line = script_stream(lines)
    gaps = []   # (line_no, kept offset after the run, s, e)
    for idx, line in enumerate(lines, 1):
        base, pos_to_k = per_line[idx - 1]
        for s, e in thai_gaps(line):
            k = pos_to_k.get(e)
            if k is not None:
                gaps.append((idx, base + k, s, e))
    if stream != src_stream:
        i = 0
        while i < min(len(stream), len(src_stream)) and stream[i] == src_stream[i]:
            i += 1
        lo = max(0, i - 20)
        return [{"code": "source-stream-mismatch", "line": None, "t": None,
                 "detail": f"script and source character streams differ at offset {i}; source comparison skipped",
                 "context": f"script=...{stream[lo:i + 20]} | source=...{src_stream[lo:i + 20]}"}]
    out = []
    for idx, off, s, e in gaps:
        if judge_run(lines[idx - 1][s:e], off, src_ws, "space")[1]:
            out.append({"code": "space-not-in-source", "line": idx, "t": None,
                        "detail": "Thai|Thai whitespace in script where the source script has none",
                        "context": _show(lines[idx - 1][max(0, s - 15):e + 15])})
    return out


def load_pages(path):
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BadInput(f"cannot read pages {path}: {e}")
    pages = data.get("pages") if isinstance(data, dict) else data
    if not isinstance(pages, list) or not all(isinstance(p, dict) for p in pages):
        raise BadInput(f"{path}: expected a list of pages or an object with a 'pages' list")
    for n, p in enumerate(pages, 1):
        if not isinstance(p.get("displayText", p.get("text")), str):
            raise BadInput(f"{path}: page {n} has neither displayText nor text")
    return pages


def _body(p):
    d = p.get("displayText")
    return d if isinstance(d, str) else strip_ws(p.get("text", ""))


def _line_around(full, pos):
    """The whole text line to the left and to the right of the whitespace run that holds offset pos of full."""
    s = e = pos
    while s > 0 and is_ws(full[s - 1]):
        s -= 1
    while e < len(full) and is_ws(full[e]):
        e += 1
    a = s
    while a > 0 and full[a - 1] not in LINE_BREAKS:
        a -= 1
    b = e
    while b < len(full) and full[b] not in LINE_BREAKS:
        b += 1
    return full[a:s], full[e:b]


def lint_pages(pages, source_text=None):
    """Lint caption pages. Rule 4 of thai_junction_ok needs source_text: the pages' kept-character stream must
    equal the source's, and the junction must sit on whitespace that the source has at that offset. A page
    junction across a script line break is judged on the full lines on both sides, like lint_script does."""
    probes = []   # (page_no, t, kind, left, right, context, where, detail_kind, src_ok)
    texts = []
    for pg in pages:
        tx = pg.get("text")
        if not isinstance(tx, str):
            lead = pg.get("leadingWhitespace")
            tx = (lead if isinstance(lead, str) else "") + _body(pg)
        texts.append(tx)
    full = "".join(texts)
    src_ws, base, offs = None, [0], [0]
    for tx in texts:
        base.append(base[-1] + len(kept(tx)))
        offs.append(offs[-1] + len(tx))
    if source_text is not None:
        src_stream, ws_set = source_whitespace(source_text)
        if "".join(c for tx in texts for c, _ in kept(tx)) == src_stream:
            src_ws = ws_set
    for i, p in enumerate(pages):
        body = _body(p)
        lead = p.get("leadingWhitespace")
        if not isinstance(lead, str):
            t = p.get("text", "")
            lead = t[:len(t) - len(lstrip_ws(t))]
        n_lead = sum(1 for ch in lead if not ch.isspace() and ch not in SKIP)   # Cf kept characters in this page's lead
        # base[i] is the kept offset of texts[i], which starts with the lead; body does not. Fail closed when the
        # page text does not read lead + body in kept characters (then no kept offset of body is known).
        offs_ok = [c for c, _ in kept(lead)] + [c for c, _ in kept(body)] == [c for c, _ in kept(texts[i])][:n_lead + len(kept(body))]
        for s, e, kind in junction_gaps(body):
            where = "caption page" if strip_ws(body[:s]) == "" else "display line"
            k_after = base[i] + n_lead + len(kept(body[:e])) if offs_ok else None
            probes.append((i + 1, p.get("start"), kind, body[:s], body[e:], _show(body[max(0, s - 15):e + 15]),
                           where, "displayText whitespace/line break inside page",
                           judge_run(body[s:e], k_after, src_ws, kind)[0]))
        if i == 0:
            continue
        ptext = texts[i - 1]
        pbody = rstrip_ws(ptext)
        ws = ptext[len(pbody):] + lead
        nbody = lstrip_ws(body)
        if not (pbody and nbody and is_thai(pbody[-1]) and is_thai(nbody[0])):
            continue
        if nbody[0] == MAI_YAMOK:
            continue   # a page that starts with ๆ is already judged (and reported) by its own junction_gaps above
        # The run that faces the junction also holds what lstrip_ws removed from the START of the body (a U+200B stays in
        # displayText: caption_join's /\s/u does not match it). k_after is the kept offset of nbody[0], past those Cf.
        body_lead = body[:len(body) - len(nbody)]
        run = ws + body_lead
        k_after = base[i] + n_lead + len(kept(body_lead)) if offs_ok else None
        src_ok = bool(run) and judge_run(run, k_after, src_ws, "break")[0]
        if any(c in LINE_BREAKS for c in ws):
            # a script line break: judge the full lines on both sides, the same strings lint_script / the cue merge use
            pr = break_probe(*_line_around(full, offs[i]))
            kind = "line break between pages"
        else:
            pr = break_probe(pbody, nbody)
            kind = "page break across whitespace" if ws else "page break with no whitespace"
        if pr is None:
            continue
        tail, head = pr
        probes.append((i + 1, p.get("start"), "break", tail, head,
                       _show(tail[-WINDOW:] + ("|" + _show(ws) + "|" if ws else "|") + head), "caption page", kind,
                       src_ok))
    bsets = boundary_sets([pr[3] + pr[4] for pr in probes])
    issues = []
    for page_no, t, kind, left, right, ctx, where, label, src_ok in probes:
        if not thai_junction_ok(left, right, kind, bsets, src_ok):
            issues.append({"code": "midword-page-break", "page": page_no, "t": t,
                           "detail": _junction_detail(left, right, kind, where)
                           or f"{label}: junction is not a Thai word boundary (ICU or newmm) and not two dictionary words at source whitespace",
                           "context": ctx})
    issues.sort(key=lambda x: (x["page"], x["code"]))
    return issues


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_text(path, label):
    try:
        return open(path, encoding="utf-8-sig").read()
    except OSError as e:
        raise BadInput(f"cannot read {label} {path}: {e}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True)
    ap.add_argument("--pages", required=True)
    ap.add_argument("--source-script")
    ap.add_argument("--report", required=True)
    a = ap.parse_args(argv)
    try:
        script = _read_text(a.script, "script")
        source = _read_text(a.source_script, "source script") if a.source_script else None
        pages = load_pages(a.pages)
    except BadInput as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    try:
        tools = check_tools()
        print(identity_line(), file=sys.stderr)   # which node / ICU / pythainlp judged this (stdout and the report stay unchanged)
        lines = [l for l in script.replace("\r\n", "\n").split("\n") if l.strip()]
        issues = lint_script(lines, source) + lint_pages(pages, source)
    except ToolMissing as e:
        print(f"ERROR: required tool missing: {e}", file=sys.stderr)
        return 4
    except (RuntimeError, subprocess.SubprocessError) as e:
        print(f"ERROR: required tool missing/failed: {e}", file=sys.stderr)
        return 4
    counts = {c: 0 for c in CODES}
    for i in issues:
        counts[i["code"]] += 1
    inputs = {p: _sha256(p) for p in [a.script, a.pages, a.source_script] if p}
    report = {"schema": SCHEMA, "version": 1, "pass": not issues, "issues": issues,
              "counts": counts, "inputs": inputs, "tools": tools}
    with open(a.report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
