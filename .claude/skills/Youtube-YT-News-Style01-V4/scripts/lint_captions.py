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

One rule for every Thai|Thai junction (thai_junction_ok, used by lint_script and lint_pages).
kind "space" = whitespace inside a line/page; kind "break" = a new caption page or a line break inside a page.
Decided in this order:
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
MAI_YAMOK = "ๆ"   # U+0E46, Thai repetition mark; deliberately the ONLY character with rules 1 and 2
_LINE_BREAKS = "\n\r\v\f\x85\u2028\u2029"

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


def junction_gaps(text: str):
    """(start, end, kind) of every whitespace run in text that is a junction to judge: Thai|Thai, or any run
    (even a missing one at the very start) that is followed by ๆ. kind is "break" when the run holds a line
    break or sits at the start of the text (a new page / script line), else "space"."""
    out = []
    n = len(text)
    if text[:1] == MAI_YAMOK:
        out.append((0, 0, "break"))
    i = 0
    while i < n:
        if text[i].isspace():
            j = i
            while j < n and text[j].isspace():
                j += 1
            if j < n:
                thai_pair = i > 0 and is_thai(text[i - 1]) and is_thai(text[j])
                if thai_pair or text[j] == MAI_YAMOK:
                    brk = i == 0 or any(c in _LINE_BREAKS for c in text[i:j])
                    out.append((i, j, "break" if brk else "space"))
            i = j
        else:
            i += 1
    return out


_DICT = None


def _thai_dictionary():
    global _DICT
    if _DICT is None:
        from pythainlp.corpus import thai_words
        _DICT = thai_words()
    return _DICT


def _edge_token(text: str, last: bool) -> str:
    from pythainlp.tokenize import word_tokenize
    toks = [x for x in word_tokenize(text, engine="newmm", keep_whitespace=False) if x]
    return (toks[-1] if last else toks[0]) if toks else ""


def _is_dictionary_word(tok: str) -> bool:
    return len(tok) > 1 and tok in _thai_dictionary()


def thai_junction_ok(left: str, right: str, kind: str, bsets=None, src_ok: bool = False) -> bool:
    """The single rule for a Thai|Thai junction (see the module docstring). left/right are the text on
    each side with the whitespace between them removed; kind is "space" or "break". bsets optionally holds
    boundary_sets() results keyed by left + right, so a caller can batch the ICU call. src_ok says that the
    junction coincides with whitespace that exists in the source script (rule 4 is only available then)."""
    if right[:1] == MAI_YAMOK:
        return kind == "space"
    if left[-1:] == MAI_YAMOK:
        return True
    joined = left + right
    b = bsets.get(joined) if bsets is not None else None
    if b is None:
        b = boundary_sets([joined])[joined]
    if len(left) in b:
        return True
    return src_ok and _is_dictionary_word(_edge_token(left, True)) and _is_dictionary_word(_edge_token(right, False))


def _show(text: str) -> str:
    return text.replace("\n", "⏎")


def _kept(text: str):
    return [(ch, i) for i, ch in enumerate(text) if not ch.isspace() and ch not in _SKIP]


def _source_clean(source_text: str) -> str:
    s = re.sub(r"<[^>]+>", "", source_text.replace("\r\n", "\n").replace("\r", "\n")).replace(" ", " ")
    return "\n".join(l for l in s.split("\n") if l.strip() and not _HEADING.match(l))


def _junction_detail(left, right, kind, where):
    if right[:1] == MAI_YAMOK and kind == "break":
        return f"ๆ starts a {where}: it must stay glued to the word before it"
    return None


def _source_whitespace(source_text):
    """(kept-character stream of the source, set of stream offsets k with whitespace between kept char k-1 and k)."""
    src = _source_clean(source_text)
    sk = _kept(src)
    src_ws = set()
    for k in range(1, len(sk)):
        if any(ch.isspace() for ch in src[sk[k - 1][1] + 1:sk[k][1]]):
            src_ws.add(k)
    return "".join(c for c, _ in sk), src_ws


def _script_stream(lines):
    """(kept-character stream of the script lines, per line (base offset, {position: kept offset}))."""
    stream, per_line = [], []
    for line in lines:
        kept = _kept(line)
        per_line.append((len(stream), {orig: k for k, (_, orig) in enumerate(kept)}))
        stream.extend(c for c, _ in kept)
    return "".join(stream), per_line


def lint_script(lines, source_text=None):
    """Lint project script lines (list of str). Returns issue dicts. Rule 4 of thai_junction_ok needs source_text."""
    issues, probes = [], []   # probes: (line_no, s, e, kind, left, right)
    for idx, line in enumerate(lines, 1):
        for s, e, kind in junction_gaps(line):
            probes.append((idx, s, e, kind, line[:s], line[e:]))
    bsets = boundary_sets([p[4] + p[5] for p in probes])
    src_stream = src_ws = stream = per_line = None
    if source_text is not None:
        src_stream, src_ws = _source_whitespace(source_text)
        stream, per_line = _script_stream(lines)
    for idx, s, e, kind, left, right in probes:
        src_ok = False
        if src_ws is not None and stream == src_stream:
            base, pos_to_k = per_line[idx - 1]
            k = pos_to_k.get(e)
            src_ok = k is not None and (base + k) in src_ws
        if not thai_junction_ok(left, right, kind, bsets, src_ok):
            line = lines[idx - 1]
            issues.append({"code": "midword-space", "line": idx, "t": None,
                           "detail": _junction_detail(left, right, kind, "script line")
                           or "whitespace splits a Thai word (no ICU/newmm boundary, and not two dictionary words at source whitespace)",
                           "context": _show(line[max(0, s - 15):e + 15])})
    if source_text is not None:
        issues.extend(_space_not_in_source(lines, source_text))
    issues.sort(key=lambda i: (i.get("line") or 0, i["code"]))
    return issues


def _space_not_in_source(lines, source_text):
    src_stream, src_ws = _source_whitespace(source_text)
    stream, per_line = _script_stream(lines)
    gaps = []   # (line_no, offset, s, e)
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


def lint_pages(pages, source_text=None):
    """Lint caption pages. Rule 4 of thai_junction_ok needs source_text: the pages' kept-character stream must
    equal the source's, and the junction must sit on whitespace that the source has at that offset."""
    probes = []   # (page_no, t, kind, left, right, context, where, detail_kind, src_ok)
    texts = [pg.get("text") if isinstance(pg.get("text"), str) else _body(pg) for pg in pages]
    src_ws, base = None, [0]
    for tx in texts:
        base.append(base[-1] + len(_kept(tx)))
    if source_text is not None:
        src_stream, ws_set = _source_whitespace(source_text)
        if "".join(c for tx in texts for c, _ in _kept(tx)) == src_stream:
            src_ws = ws_set
    for i, p in enumerate(pages):
        body = _body(p)
        for s, e, kind in junction_gaps(body):
            where = "caption page" if body[:s].strip() == "" else "display line"
            k = base[i] + len(_kept(body[:s]))
            probes.append((i + 1, p.get("start"), kind, body[:s], body[e:], _show(body[max(0, s - 15):e + 15]),
                           where, "displayText whitespace/line break inside page",
                           src_ws is not None and k in src_ws))
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
        if nbody[0] == MAI_YAMOK:
            continue   # a page that starts with ๆ is already judged (and reported) by its own junction_gaps above
        tail, head = pbody[-WINDOW:], nbody[:WINDOW]
        kind = "page break across whitespace" if ws else "page break with no whitespace"
        probes.append((i + 1, p.get("start"), "break", tail, head,
                       _show(tail + ("|" + _show(ws) + "|" if ws else "|") + head), "caption page", kind,
                       bool(ws) and src_ws is not None and base[i] in src_ws))
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
