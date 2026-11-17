"""The ONE rule for a Thai|Thai junction, shared by srt_to_script.py (which merges cues at a failing junction)
and lint_captions.py (which fails one). Both must judge exactly the same strings, so everything that finds,
windows or decides a junction lives here and nowhere else.

Word-boundary oracle: a position inside Thai text is acceptable when it is a word boundary of the de-spaced
text according to EITHER ICU (node Intl.Segmenter('th')) OR pythainlp newmm. Missing tools raise ToolMissing
(the callers turn that into exit 4), never a silent skip. The heavy imports (pythainlp, node) are lazy, so
importing this module needs neither.

thai_junction_ok(left, right, kind, bsets, src_ok), decided in this order:
  1. the right side starts with the mai yamok (ๆ, U+0E46): kind "space" passes, "break" FAILS (ๆ may never
     start a page, a display line or a script line);
  2. the left side ends with ๆ: pass (a space or break after ๆ is a normal boundary, "มาก ๆ บน");
  3. ICU or newmm finds a boundary in the joined text: pass;
  4. the junction coincides with whitespace that exists in the SOURCE script at that position (src_ok), and
     newmm tokenising each side SEPARATELY gives, on EACH side, a token touching the junction that is a
     pythainlp.corpus.thai_words() entry longer than one character ("ว่า|การ", "แล้ว|ไป"): pass. Without a
     source, or where the source has no whitespace there (an engine broke a page mid-word), rule 4 is not
     available. Accepted risk: a typo IN THE SOURCE whose halves are both words ("แส ดง") passes; that is the
     script step's fault, the edit step cannot change the source;
  5. otherwise FAIL ("ระ|บบ": "บบ" is not a word).
kind "space" = whitespace inside a line/page; kind "break" = a new caption page, a script line, or a line break
inside a page.

break_probe(left_text, right_text) builds the (left_ctx, right_ctx) strings for a break junction, the same way
for every caller.
"""
import json
import os
import pwd
import re
import subprocess

MAI_YAMOK = "ๆ"   # U+0E46, Thai repetition mark; deliberately the ONLY character with rules 1 and 2
WINDOW = 25
# zero-width format characters: neither str.isspace() nor Thai, but invisible, so they hide a junction
CF_CHARS = "​‌‍⁠﻿"
LINE_BREAKS = "\n\r\v\f\x85  "
# Characters that never count towards the character stream compared with the source / SRT.
SKIP = set("“”\"„«»→←➜⇒")
HEADING = re.compile(r"^\s*Part\s*\d+\s*:?\s*$", re.IGNORECASE)

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


# node comes from a FIXED candidate list, first executable wins, never from $PATH (finalize resolves node the same way:
# finalize.TOOL_CANDIDATES['node'] is a second copy of this tuple, test_finalize.py asserts they are equal). The ICU
# segmentation is part of the verdict, so the agent's srt_to_script.py and finalize's rebuild must use the same node.
def passwd_home() -> str:
    """Home of the account running this process, from the passwd entry (never $HOME), like finalize.passwd_home()."""
    return pwd.getpwuid(os.getuid()).pw_dir


NODE_CANDIDATES = (passwd_home() + "/.local/bin/node", "/opt/homebrew/bin/node", "/usr/local/bin/node")


def resolve_node():
    """realpath of the first executable in NODE_CANDIDATES, or None. $PATH is never searched."""
    for c in NODE_CANDIDATES:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return os.path.realpath(c)
    return None


def is_thai(ch: str) -> bool:
    return bool(ch) and "฀" <= ch <= "๿"


def is_ws(ch: str) -> bool:
    """Whitespace for the purpose of FINDING a junction: real whitespace plus invisible Cf characters."""
    return ch.isspace() or ch in CF_CHARS


def lstrip_ws(text: str) -> str:
    i = 0
    while i < len(text) and is_ws(text[i]):
        i += 1
    return text[i:]


def rstrip_ws(text: str) -> str:
    j = len(text)
    while j > 0 and is_ws(text[j - 1]):
        j -= 1
    return text[:j]


def strip_ws(text: str) -> str:
    return lstrip_ws(rstrip_ws(text))


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
    node = None if "node" in missing else resolve_node()
    if not node:
        raise ToolMissing("node not found at " + ", ".join(NODE_CANDIDATES) + " ($PATH is never searched; needed for the "
                          "Intl.Segmenter ICU oracle)")
    try:
        info = _run_icu(["ทดสอบ"], node)
    except Exception as e:
        raise ToolMissing(f"node Intl.Segmenter('th') failed: {e}")
    tools["icu"] = f"node {info['node']} icu {info['icu']}"
    global _IDENTITY
    _IDENTITY = f"TOOLS node={node} {info['node']} icu={info['icu']} pythainlp={tools['pythainlp']}"
    return tools


_IDENTITY = None


def identity_line() -> str:
    """One line naming the tools of the last successful check_tools(): node realpath + version, ICU, pythainlp.
    The callers print it to STDERR (stdout and the output files stay byte-identical)."""
    return _IDENTITY or "TOOLS unchecked"


def _run_icu(strings, node=None) -> dict:
    node = node or resolve_node()
    if not node:
        raise ToolMissing("node not found at " + ", ".join(NODE_CANDIDATES))
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
        if is_ws(text[i]):
            j = i
            while j < n and is_ws(text[j]):
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
        if is_ws(text[i]):
            j = i
            while j < n and is_ws(text[j]):
                j += 1
            if j < n:
                thai_pair = i > 0 and is_thai(text[i - 1]) and is_thai(text[j])
                if thai_pair or text[j] == MAI_YAMOK:
                    brk = i == 0 or any(c in LINE_BREAKS for c in text[i:j])
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
    boundary_sets() results keyed by left + right, so a caller can batch the ICU call (a miss is computed
    and stored). src_ok says that the junction coincides with whitespace that exists in the source script
    (rule 4 is only available then)."""
    if right[:1] == MAI_YAMOK:
        return kind == "space"
    if left[-1:] == MAI_YAMOK:
        return True
    joined = left + right
    b = bsets.get(joined) if bsets is not None else None
    if b is None:
        b = boundary_sets([joined])[joined]
        if bsets is not None:
            bsets[joined] = b
    if len(left) in b:
        return True
    return src_ok and _is_dictionary_word(_edge_token(left, True)) and _is_dictionary_word(_edge_token(right, False))


def break_probe(left_text: str, right_text: str):
    """The strings to judge for a junction between two pieces of text (a script line break, a page break, a
    line break inside a page): (left_ctx, right_ctx), or None when the junction is not judged. Whitespace
    and Cf characters facing the junction are stripped, the junction is judged when it is Thai|Thai or when
    the right side starts with ๆ, and each side is windowed to WINDOW characters. The same two texts always
    give the same strings, whoever asks."""
    left, right = rstrip_ws(left_text), lstrip_ws(right_text)
    if not left or not right:
        return None
    if not ((is_thai(left[-1]) and is_thai(right[0])) or right[0] == MAI_YAMOK):
        return None
    return left[-WINDOW:], right[:WINDOW]


# -- the character streams compared with the source / SRT (Cf characters are NOT whitespace here) ---------------

def kept(text: str):
    """(char, original index) for every char that counts towards the stream."""
    return [(ch, i) for i, ch in enumerate(text) if not ch.isspace() and ch not in SKIP]


def source_clean(source_text: str) -> str:
    """Original script without heading lines / blank lines / tags (lines kept as lines)."""
    s = re.sub(r"<[^>]+>", "", source_text.replace("\r\n", "\n").replace("\r", "\n")).replace(" ", " ")
    return "\n".join(l for l in s.split("\n") if l.strip() and not HEADING.match(l))


def source_whitespace(source_text):
    """(kept-character stream of the source, set of stream offsets k with whitespace between kept char k-1 and k)."""
    src = source_clean(source_text)
    sk = kept(src)
    src_ws = set()
    for k in range(1, len(sk)):
        if any(ch.isspace() for ch in src[sk[k - 1][1] + 1:sk[k][1]]):
            src_ws.add(k)
    return "".join(c for c, _ in sk), src_ws


def facing_run(left_text: str, right_text: str):
    """The whitespace/Cf run that faces a junction between two texts (a script line break, a page break):
    (trailing run of left + leading run of right, number of KEPT characters (Cf) in the leading run of right)."""
    lt = rstrip_ws(left_text)
    rt = lstrip_ws(right_text)
    lead = right_text[:len(right_text) - len(rt)]
    return left_text[len(lt):] + lead, sum(1 for ch in lead if not ch.isspace() and ch not in SKIP)


def judge_run(run: str, k_after, src_ws, kind: str):
    """THE ONE judgement of a whitespace run against the source, used by the srt_to_script merge, lint_script
    (in-line and between lines), lint_pages and space-not-in-source, so merge and lint always judge the same thing.

    run: the whitespace/Cf run (it may hold Cf characters, which are KEPT characters of the stream: they sit in the
    run but not in `isspace()`). k_after: the kept offset of the character right after the run. The run covers the kept
    offsets from the first kept character inside it (the first Cf; or k_after when it holds none) through k_after,
    and the source has whitespace "here" when ANY offset of that range is in src_ws (offset k = whitespace between
    kept chars k-1 and k). So `ก ​ข` and `ก​ ข` (space+Cf / Cf+space) give the same answer.

    Returns (src_ok, space_not_in_source):
      src_ok: rule 4 is available. kind "space": the run holds a real isspace() char AND the source has whitespace
              here (a Cf-only run never gets rule 4). kind "break": the source has whitespace here (the break is the
              separator).
      space_not_in_source: the run holds a real isspace() char AND the source has none here (a Cf-only run never
              fires it: stream equality already proves the Cf is in the source).
    Without a source (src_ws None) or without a known offset (k_after None) neither flag is set."""
    if src_ws is None or k_after is None:
        return False, False
    has_real_space = any(ch.isspace() for ch in run)
    n_kept = sum(1 for ch in run if not ch.isspace() and ch not in SKIP)
    src_has_ws = any(k in src_ws for k in range(k_after - n_kept, k_after + 1))
    return src_has_ws and (has_real_space or kind == "break"), has_real_space and not src_has_ws


def script_stream(lines):
    """(kept-character stream of the script lines, per line (base offset, {position: kept offset}))."""
    stream, per_line = [], []
    for line in lines:
        k = kept(line)
        per_line.append((len(stream), {orig: n for n, (_, orig) in enumerate(k)}))
        stream.extend(c for c, _ in k)
    return "".join(stream), per_line
