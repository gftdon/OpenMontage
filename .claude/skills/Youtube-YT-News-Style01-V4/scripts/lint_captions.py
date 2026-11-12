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

Exit: 0 pass, 1 issues, 2 bad/missing input, 4 required tool missing.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

SCHEMA = "yt-news-v4-captions-lint"
CODES = ["midword-space", "space-not-in-source", "source-stream-mismatch", "midword-page-break"]
WINDOW = 25
_HEADING = re.compile(r"^\s*Part\s*\d+\s*:?\s*$", re.IGNORECASE)
_SKIP = set("“”\"„«»→←➜⇒")

_NODE_JS = r"""
const a = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const seg = new Intl.Segmenter('th', {granularity: 'word'});
const b = a.map(s => {
  const out = [0]; let cp = 0;
  for (const x of seg.segment(s)) { cp += Array.from(x.segment).length; out.push(cp); }
  return out;
});
process.stdout.write(JSON.stringify({node: process.version, icu: process.versions.icu, b}));
"""


class ToolMissing(Exception):
    pass


class BadInput(Exception):
    pass


def is_thai(ch: str) -> bool:
    return bool(ch) and "฀" <= ch <= "๿"


def _simulated_missing() -> set:
    return {x.strip() for x in os.environ.get("LINT_CAPTIONS_SIMULATE_MISSING", "").split(",") if x.strip()}


def check_tools() -> dict:
    """Verify both oracle engines work; return their versions."""
    missing = _simulated_missing()
    tools = {}
    if "pythainlp" in missing:
        raise ToolMissing("pythainlp unavailable (simulated)")
    try:
        import pythainlp  # noqa: F401
        from pythainlp.tokenize import word_tokenize  # noqa: F401
        tools["pythainlp"] = getattr(pythainlp, "__version__", "unknown")
    except Exception as e:  # ImportError or a broken install
        raise ToolMissing(f"pythainlp import failed: {e}")
    node = None if "node" in missing else shutil.which("node")
    if not node:
        raise ToolMissing("node not found on PATH (needed for Intl.Segmenter ICU oracle)")
    try:
        info = _run_icu(["ทดสอบ"], node)
    except Exception as e:
        raise ToolMissing(f"node Intl.Segmenter('th') failed: {e}")
    tools["icu"] = f"node {info['node']} icu {info['icu']}"
    return tools


def _run_icu(strings, node=None) -> dict:
    node = node or shutil.which("node")
    r = subprocess.run([node, "-e", _NODE_JS], input=json.dumps(strings), capture_output=True,
                       text=True, encoding="utf-8", timeout=300)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300])
    return json.loads(r.stdout)


def _newmm_boundaries(strings):
    from pythainlp.tokenize import word_tokenize
    out = []
    for s in strings:
        toks = word_tokenize(s, engine="newmm", keep_whitespace=True)
        if "".join(toks) != s:
            raise ToolMissing("pythainlp newmm did not preserve the input text")
        b, cp = {0}, 0
        for t in toks:
            cp += len(t)
            b.add(cp)
        out.append(b)
    return out


def boundary_sets(strings):
    """Per string: the set of code-point offsets that are a boundary for ICU or newmm."""
    uniq = list(dict.fromkeys(strings))
    if not uniq:
        return {}
    icu = _run_icu(uniq)["b"]
    nm = _newmm_boundaries(uniq)
    return {s: set(i) | n for s, i, n in zip(uniq, icu, nm)}


def thai_gaps(text: str):
    """(start, end) of every whitespace run that sits between two Thai chars."""
    gaps, i, n = [], 0, len(text)
    while i < n:
        if text[i].isspace():
            j = i
            while j < n and text[j].isspace():
                j += 1
            if i > 0 and j < n and is_thai(text[i - 1]) and is_thai(text[j]):
                gaps.append((i, j))
            i = j
        else:
            i += 1
    return gaps


def _show(text: str) -> str:
    return text.replace("\n", "⏎")


def _kept(text: str):
    return [(ch, i) for i, ch in enumerate(text) if not ch.isspace() and ch not in _SKIP]


def _source_clean(source_text: str) -> str:
    s = re.sub(r"<[^>]+>", "", source_text.replace("\r\n", "\n").replace("\r", "\n")).replace(" ", " ")
    return "\n".join(l for l in s.split("\n") if l.strip() and not _HEADING.match(l))


def lint_script(lines, source_text=None):
    """Lint project script lines (list of str). Returns issue dicts."""
    issues, probes = [], []   # probes: (line_no, gap_start, gap_end, probe_text)
    for idx, line in enumerate(lines, 1):
        for s, e in thai_gaps(line):
            probes.append((idx, s, e, line[:s] + line[e:]))
    bsets = boundary_sets([p[3] for p in probes])
    for idx, s, e, probe in probes:
        if s not in bsets[probe]:
            line = lines[idx - 1]
            issues.append({"code": "midword-space", "line": idx, "t": None,
                           "detail": "whitespace splits a Thai word (no ICU/newmm boundary after removing it)",
                           "context": _show(line[max(0, s - 15):e + 15])})
    if source_text is not None:
        issues.extend(_space_not_in_source(lines, source_text))
    issues.sort(key=lambda i: (i.get("line") or 0, i["code"]))
    return issues


def _space_not_in_source(lines, source_text):
    src = _source_clean(source_text)
    sk = _kept(src)
    src_stream = "".join(c for c, _ in sk)
    src_ws = set()   # stream offsets k with whitespace between kept char k-1 and k
    for k in range(1, len(sk)):
        if any(ch.isspace() for ch in src[sk[k - 1][1] + 1:sk[k][1]]):
            src_ws.add(k)
    stream, gaps = [], []   # gaps: (line_no, offset, s, e)
    for idx, line in enumerate(lines, 1):
        base = len(stream)
        kept = _kept(line)
        stream.extend(c for c, _ in kept)
        pos_to_k = {orig: k for k, (_, orig) in enumerate(kept)}
        for s, e in thai_gaps(line):
            k = pos_to_k.get(e)
            if k is not None:
                gaps.append((idx, base + k, s, e))
    stream = "".join(stream)
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
        if off not in src_ws:
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
    return d if isinstance(d, str) else p.get("text", "").strip()


def lint_pages(pages):
    probes = []   # (page_no, t, kind, probe_text, pos, context)
    for i, p in enumerate(pages):
        body = _body(p)
        for s, e in thai_gaps(body):
            probes.append((i + 1, p.get("start"), "displayText whitespace/line break inside page",
                           body[:s] + body[e:], s, _show(body[max(0, s - 15):e + 15])))
        if i == 0:
            continue
        prev = pages[i - 1]
        ptext = prev.get("text") if isinstance(prev.get("text"), str) else _body(prev)
        pbody = ptext.rstrip()
        lead = p.get("leadingWhitespace")
        if not isinstance(lead, str):
            t = p.get("text", "")
            lead = t[:len(t) - len(t.lstrip())]
        ws = ptext[len(pbody):] + lead
        nbody = body.lstrip()
        if not (pbody and nbody and is_thai(pbody[-1]) and is_thai(nbody[0])):
            continue
        if "\n" in ws:
            continue   # a script line break is a real boundary; de-spacing it would be a false positive
        tail, head = pbody[-WINDOW:], nbody[:WINDOW]
        kind = "page break across whitespace" if ws else "page break with no whitespace"
        probes.append((i + 1, p.get("start"), kind, tail + head, len(tail),
                       _show(tail + ("|" + _show(ws) + "|" if ws else "|") + head)))
    bsets = boundary_sets([pr[3] for pr in probes])
    issues = []
    for page_no, t, kind, probe, pos, ctx in probes:
        if pos not in bsets[probe]:
            issues.append({"code": "midword-page-break", "page": page_no, "t": t,
                           "detail": f"{kind}: junction is not a Thai word boundary (ICU or newmm)",
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
        lines = [l for l in script.replace("\r\n", "\n").split("\n") if l.strip()]
        issues = lint_script(lines, source) + lint_pages(pages)
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
