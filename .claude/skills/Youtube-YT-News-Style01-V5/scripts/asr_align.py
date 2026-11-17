#!/usr/bin/env python3
"""asr_align.py — step 2 of the word-timing chain: raw ASR words (raw_asr.json of asr_transcribe.py) + the EXACT script
-> caption pages.  Pure and deterministic (no model, no clock, no environment in the output).

  bash asr_run.sh asr_align.py --raw raw_asr.json --script script.txt --out caption_pages.json
      exit 0 ok
      exit 2 bad arguments / unreadable or malformed raw or script / no timed words / no script text /
             raw.script_sha256 != sha256(script) (the raw words were decoded for another script)
      exit 4 pythainlp missing, or its version differs from tokenizer.pythainlp recorded in raw_asr.json (the pages are
             re-derived byte for byte later; a different tokenizer may split words differently -> run it with the venv
             python that wrote raw_asr.json); or started without `-I -S -B -X pycache_prefix=/var/empty`
  An existing <out> is removed first: a failed run never leaves the previous run's pages behind.
  Like asr_transcribe.py it is started ONLY through asr_run.sh (which verifies the interpreter, the stdlib and the venv against
  the manifest first).  Run as __main__ it refuses (exit 4, before importing anything but sys) unless python was started
  isolated, without site processing (-S), without bytecode and with pycache_prefix=/var/empty (a planted .pyc can never be
  read), it appends the V4 venv's site-packages to sys.path itself, and it re-runs itself ONCE under the minimal environment
  {HOME from the passwd entry, PATH, LANG, TMPDIR=/var/empty} (pythainlp finds its data dir from HOME) if the caller's differs.

Runs from the V4 ASR venv's site-packages because the pagination tokenizes with pythainlp `newmm` (any python with the SAME
pythainlp version gives the same bytes).

Output = EXACTLY what the old karaoke_subtitle_v2/scripts/extract_timing.py wrote (so words_by_line.py, line_starts.py,
caption_join.mjs, timing_check.py and the byte-equal re-derivation keep working):
  [{"start": float, "end": float, "words": [{"w": str, "s": float, "e": float}]}]
  times round(x, 3); page start/end = first word s / last word e; json ensure_ascii=False, indent=1, no trailing newline,
  UTF-8.  Written to <out>.tmp.<pid> then renamed.  Same raw + same script -> same bytes.

Provenance — behaviour-preserving copies (read-only reference files, not imported; this skill must not depend on them):
  ~/.claude/skills/karaoke-subtitle/scripts/make_karaoke_sub.py
      sha256 2c9da476ae0fdb488f46c1183556c2b77c804d7e095fbdcf6fb0c75520c41ab4
      -> read_script_lines, _asr_char_timeline, apply_script
  ~/.claude/skills/karaoke-subtitle/scripts/karaoke_lib.py
      sha256 a299e346ab6bc4d7fdf1af32ec2edb22f4207b69d2074e6f916ab3188a184831
      -> COMBINING, _base_weight, _is_thai, _has_letter, _merge_adjacent, build_chunks
  .claude/skills/karaoke_subtitle_v2/scripts/extract_timing.py
      sha256 2d209578364e68a6e7cad24f2464734ac36e121936d3fc36b7e8e54bb4933a73
      -> page format + build_chunks arguments (max_words=4, max_chars=24, pause=0.42)
  Two behavioural changes, both deliberate:
  (1) apply_script also returns per-character `anchored` flags (True = the character's start time comes from a difflib match
      with a whisper character, False = interpolated / clamped) for the defect reports;
  (2) fix round 1: the `end` of a MATCHED character is its raw whisper end (never past the next character's start), not the next
      character's start, so a real pause stays a gap in the pages (build_chunks' own `pause` rule then also splits pages at it).
      Unmatched / interpolated / clamped characters keep the reference rule (end = next start).
  Verified 2026-11-13 (before change 2): on the same raw words the old chain and this file wrote byte-identical pages; now they
  differ exactly where a matched character is followed by a pause (tests/fixtures/a67/timing/vendored_equiv_*).
"""
import sys

RUN_FLAGS = ('-I', '-S', '-B', '-X', 'pycache_prefix=/var/empty')
if __name__ == '__main__' and not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
                                   and sys.pycache_prefix == '/var/empty'):
    sys.stderr.write('ERROR: refusing to run: python was not started isolated (-I), without site processing (-S) and without '
                     'bytecode (a planted .pyc could replace this tool).  Start it only through the launcher: '
                     '/bin/bash %s/asr_run.sh %s <arguments>\n' % (sys.argv[0].rpartition('/')[0] or '.', sys.argv[0].rpartition('/')[2]))
    sys.exit(4)

import os  # noqa: E402
import pwd  # noqa: E402

FFMPEG_CANDIDATES = ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/usr/bin/ffmpeg')   # = asr_transcribe.py = asr_run.sh (a test asserts it)
ENV_KEYS = ('HOME', 'PATH', 'LANG', 'TMPDIR')
OS_ADDED_ENV = ('__CF_USER_TEXT_ENCODING',)       # macOS puts this into every process; it is only an encoding hint
ENV_LANG = 'en_US.UTF-8'
ENV_TMPDIR = '/var/empty'
USER_HOME = pwd.getpwuid(os.getuid()).pw_dir      # the passwd entry, never $HOME


def minimal_env():
    """the same environment asr_run.sh and asr_transcribe.py use: PATH = <the first ffmpeg's dir>:/usr/bin:/bin"""
    ff = next((c for c in FFMPEG_CANDIDATES if os.path.isfile(c) and os.access(c, os.X_OK)), None)
    return {'HOME': USER_HOME, 'PATH': (os.path.dirname(ff) + ':' if ff else '') + '/usr/bin:/bin', 'LANG': ENV_LANG,
            'TMPDIR': ENV_TMPDIR}


def env_is_minimal(env_mapping):
    """exactly minimal_env() (every value compared) plus what macOS adds itself"""
    return {k: v for k, v in dict(env_mapping).items() if k not in OS_ADDED_ENV} == minimal_env()


if __name__ == '__main__' and not env_is_minimal(os.environ):
    if 'asr_reexec' in sys._xoptions:
        sys.stderr.write('ERROR: the environment is still not the minimal one after a restart; stop and report this.\n')
        sys.exit(4)
    os.execve(sys.executable, [sys.executable, *RUN_FLAGS, '-X', 'asr_reexec=1', os.path.abspath(sys.argv[0]), *sys.argv[1:]],
              minimal_env())

# = asr_transcribe.SITE_DIR (a test asserts it): -S processed no site-packages, so the V4 venv's are appended here
SITE_DIR = os.path.join(USER_HOME, '.cache', 'yt-news-v4', 'asr-venv', 'lib', 'python3.12', 'site-packages')
if __name__ == '__main__':
    sys.path.append(SITE_DIR)

import argparse  # noqa: E402
import difflib  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402

RAW_SCHEMA = 'yt-news-v4-raw-asr'
RAW_VERSION = 1
# build_chunks arguments of the old extract_timing.py (its argparse defaults; word_timing.sh never passed others)
MAX_WORDS = 4
MAX_CHARS = 24
PAUSE = 0.42


class InputError(Exception):
    """exit 2"""


class TokenizerError(Exception):
    """exit 4"""


# ===================================================================== vendored: make_karaoke_sub.py
def read_script_lines(path):
    txt = open(path, encoding="utf-8").read()
    if path.lower().endswith(".md") and "Audio TH" in txt:
        # pipeline storyboard: take the line after each "## Audio TH" header
        lines = []
        rows = txt.splitlines()
        for i, ln in enumerate(rows):
            if ln.strip().lower().startswith("## audio th"):
                for j in range(i + 1, len(rows)):
                    s = rows[j].strip()
                    if s and not s.startswith("**") and not s.startswith("#"):
                        lines.append(s); break
        return lines
    return [l.strip() for l in txt.splitlines() if l.strip()]


def _asr_char_timeline(result):
    """Flatten whisper words into [(char, t0, t1)] over non-space chars only."""
    out = []
    for seg in result.get("segments", []):
        for p in seg.get("words") or []:
            w = p.get("word", "")
            if not w:
                continue
            s, e = float(p["start"]), float(p["end"])
            n = len(w)
            for i, c in enumerate(w):
                if c.isspace():
                    continue
                out.append((c, s + (e - s) * i / n, s + (e - s) * (i + 1) / n))
    return out


def apply_script(result, lines):
    """Overlay the script's EXACT wording onto whisper's timing (vendored; see the module docstring).

    -> (result, anchored).  anchored[k] is True when the k-th non-space script character got its start time from a
    difflib matching block (a real whisper character), False when it was interpolated between anchors or clamped.
    anchored is None when the input is unusable (no timing or no script text) and `result` is returned unchanged.
    Deviation from the reference (documented, tested): the `end` of a matched character is its raw whisper end, not the next start."""
    asr = _asr_char_timeline(result)
    correct = " ".join(l.strip() for l in lines if l.strip())
    if not asr or not correct:
        print("  ! no usable timing or script text; keeping transcription")
        return result, None

    asr_str = "".join(c for c, _, _ in asr)
    chars = list(correct)
    align_pos = [i for i, c in enumerate(chars) if not c.isspace()]
    align_str = "".join(chars[i] for i in align_pos)
    M = len(align_str)
    if M == 0:
        return result, None

    # anchor each correct (non-space) char to a whisper start time, then
    # linearly interpolate the gaps and clamp to non-decreasing.
    times = [None] * (M + 1)
    anchored = [False] * M
    raw_end = [None] * M                      # fix round 1 (item 4): the raw end of the whisper character a script character matched
    sm = difflib.SequenceMatcher(None, asr_str, align_str, autojunk=False)
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            times[blk.b + k] = asr[blk.a + k][1]
            raw_end[blk.b + k] = asr[blk.a + k][2]
            anchored[blk.b + k] = True
    if times[0] is None:
        times[0] = asr[0][1]
    times[M] = asr[-1][2]
    known = [i for i in range(M + 1) if times[i] is not None]
    for a, b in zip(known, known[1:]):
        if b - a > 1:
            ta, tb = times[a], times[b]
            for x in range(a + 1, b):
                times[x] = ta + (tb - ta) * (x - a) / (b - a)
    for i in range(1, M + 1):
        if times[i] < times[i - 1]:
            times[i] = times[i - 1]
            if i < M:
                anchored[i] = False       # clamped: no longer the matched whisper time

    # one word-piece per correct char (spaces included so tokenizer spacing is
    # preserved); build_chunks re-tokenizes this into real Thai words.
    words, k = [], 0
    for c in chars:
        if c.isspace():
            t = times[min(k, M)]
            words.append({"word": c, "start": float(t), "end": float(t)})
        else:
            end = times[k + 1]
            if anchored[k] and raw_end[k] is not None:
                # A MATCHED character keeps its raw end (never past the next character's start): a real pause after a word then stays
                # a gap in the pages instead of being absorbed into the word before it (the reference set every end to the next
                # start, so a 1.2 s pause made a 3-letter word "slow" and the job failed for ever).  Unmatched / interpolated /
                # clamped characters keep the reference rule.
                end = min(max(raw_end[k], times[k]), times[k + 1])
            words.append({"word": c, "start": float(times[k]), "end": float(end)})
            k += 1
    print(f"  ✓ aligned {len(lines)} script line(s) onto whisper timing "
          f"({M} correct chars vs {len(asr)} ASR chars)")
    return {"segments": [{"start": float(times[0]), "end": float(times[M]),
                          "text": correct, "words": words}]}, anchored


# ===================================================================== vendored: karaoke_lib.py
# Thai combining marks (above/below vowels + tone marks): they ride on a base
# glyph and add no spoken duration, so we don't count them when weighting time.
COMBINING = {0x0E31} | set(range(0x0E34, 0x0E3B)) | set(range(0x0E47, 0x0E4F))


def _base_weight(tok):
    return max(1, sum(1 for c in tok if (not c.isspace()) and (ord(c) not in COMBINING)))


def _is_thai(s):
    return any("฀" <= c <= "๿" for c in s)


def _has_letter(s):
    return _is_thai(s) or any(c.isalnum() for c in s)


def _merge_adjacent(timed):
    """Merge tokenizer crumbs so each highlight lands on a sensible unit.

    newmm emits things like ['700','-','10,000'] and the lone '-' looks wrong
    highlighted on its own. Rule: join directly-adjacent (no space between) runs
    of non-Thai tokens (digits/latin/punctuation) into one, and fold any
    pure-punctuation token into its neighbor. Real Thai words are left untouched.
    `timed` is a list of [tok, start, end]; whitespace tokens have start=end=None.
    """
    out = []
    for (t, s, e) in timed:
        if t.strip() == "":
            out.append([t, s, e]); continue
        if out and out[-1][0].strip() != "":
            prev = out[-1]
            both_nonthai = (not _is_thai(prev[0])) and (not _is_thai(t))
            if both_nonthai or not _has_letter(t):
                prev[0] += t
                if e is not None:
                    prev[2] = e
                continue
        out.append([t, s, e])
    return [tuple(x) for x in out]


def build_chunks(whisper_result, max_words=4, max_chars=18, pause=0.45):
    """Turn a whisper transcription (word_timestamps=True) into display chunks.

    Returns a list of dicts: {text, words:[{tok,start,end}]}. Timing comes from
    whisper's own word/char timestamps; words are re-tokenized into real Thai
    words with pythainlp so highlighting lands on natural word units.
    """
    from pythainlp.tokenize import word_tokenize
    chunks = []
    for seg in whisper_result.get("segments", []):
        pieces = seg.get("words") or []
        # Build a per-character timeline for this segment.
        chars = []  # (char, t0, t1)
        text = ""
        for p in pieces:
            w = p.get("word", "")
            if w == "":
                continue
            s, e = float(p["start"]), float(p["end"])
            n = len(w)
            for i, c in enumerate(w):
                c0 = s + (e - s) * i / n
                c1 = s + (e - s) * (i + 1) / n
                chars.append((c, c0, c1))
            text += w
        if not text.strip():
            continue
        if not chars:  # fallback: no per-word timing -> spread the segment evenly
            s, e = float(seg["start"]), float(seg["end"])
            n = len(text)
            chars = [(c, s + (e - s) * i / n, s + (e - s) * (i + 1) / n)
                     for i, c in enumerate(text)]

        # Tokenize into Thai words, keeping whitespace so spacing around latin /
        # digits (e.g. "สอน AI 10 ตัว") is preserved exactly.
        toks = word_tokenize(text, engine="newmm", keep_whitespace=True)

        # Map each token to a char span -> start/end time.
        timed = []
        pos = 0
        for t in toks:
            a, b = pos, pos + len(t)
            pos = b
            if t.strip() == "":
                timed.append((t, None, None))
                continue
            a = min(a, len(chars) - 1)
            b = min(b, len(chars))
            timed.append((t, chars[a][1], chars[b - 1][2]))

        timed = _merge_adjacent(timed)

        # Group tokens into chunks by word-count / width / pause between words.
        cur, cur_words, last_end = [], 0, None
        def flush():
            nonlocal cur, cur_words
            # strip leading/trailing whitespace tokens
            while cur and cur[0][0].strip() == "":
                cur.pop(0)
            while cur and cur[-1][0].strip() == "":
                cur.pop()
            if not cur:
                cur, cur_words = [], 0
                return
            tokens = [t for (t, _, _) in cur]
            words = [{"tok": t, "start": s, "end": e} for (t, s, e) in cur if t.strip() != ""]
            # store the exact tokens used here so rendering never re-tokenizes
            # (re-tokenizing a substring can split differently and misalign the
            # highlight with the timing).
            chunks.append({"text": "".join(tokens), "tokens": tokens, "words": words})
            cur, cur_words = [], 0

        for (t, s, e) in timed:
            is_word = t.strip() != ""
            chars_if = sum(_base_weight(x[0]) for x in cur if x[0].strip() != "") + (_base_weight(t) if is_word else 0)
            gap_break = (is_word and last_end is not None and s is not None and (s - last_end) >= pause)
            if cur and is_word and (cur_words >= max_words or chars_if > max_chars or gap_break):
                flush()
            cur.append((t, s, e))
            if is_word:
                cur_words += 1
                last_end = e
        flush()
    return chunks


# ===================================================================== vendored: extract_timing.py (page format)
def chunks_to_pages(chunks):
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
    return pages


def pages_text(pages):
    """The exact text extract_timing.py's json.dump(pages, f, ensure_ascii=False, indent=1) wrote."""
    return json.dumps(pages, ensure_ascii=False, indent=1)


# ===================================================================== this skill
def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validate_raw(raw):
    """Structural check of a raw_asr.json document (InputError on anything unusable)."""
    if not isinstance(raw, dict) or raw.get('schema') != RAW_SCHEMA or raw.get('version') != RAW_VERSION:
        raise InputError('not a %s v%d document' % (RAW_SCHEMA, RAW_VERSION))
    segs = raw.get('segments')
    if not isinstance(segs, list):
        raise InputError('raw has no "segments" list')
    for si, seg in enumerate(segs):
        if not isinstance(seg, dict) or not isinstance(seg.get('words'), list):
            raise InputError('raw segment %d has no "words" list' % si)
        for wi, w in enumerate(seg['words']):
            if not (isinstance(w, dict) and isinstance(w.get('word'), str) and _finite(w.get('start')) and _finite(w.get('end'))):
                raise InputError('raw segment %d word %d is not {word: str, start, end} with finite times' % (si, wi))
    tok = raw.get('tokenizer')
    if not isinstance(tok, dict) or not isinstance(tok.get('pythainlp'), str):
        raise InputError('raw has no tokenizer.pythainlp version')
    return raw


def tokenizer_version():
    try:
        import pythainlp
    except Exception as e:  # noqa: BLE001 - any import failure is a tool problem
        raise TokenizerError('pythainlp is not importable with %s (%s): run it through asr_run.sh (the V4 ASR venv '
                             'is built by a human with setup_asr_venv.sh)' % (sys.executable, e))
    return pythainlp.__version__


def word_anchors(pages, lines, anchored):
    """Share (0..1) of each page word's non-space characters whose time is a whisper anchor, in page-word order.
    None for a word that cannot be located in the script text (never expected: words are script substrings)."""
    correct = " ".join(l.strip() for l in lines if l.strip())
    out, pos, k = [], 0, 0
    for p in pages:
        for w in p['words']:
            while pos < len(correct) and correct[pos].isspace():
                pos += 1
            tok = w['w']
            if anchored is None or not correct.startswith(tok, pos):
                out.append(None)
                continue
            n = sum(1 for c in tok if not c.isspace())
            flags = anchored[k:k + n]
            out.append(round(sum(flags) / n, 3) if n else None)
            k += n
            pos += len(tok)
    return out


def align(raw, lines):
    """raw_asr document + script lines -> (pages, per-word anchored share).  InputError when nothing can be aligned."""
    validate_raw(raw)
    if not any(l.strip() for l in lines):
        raise InputError('the script has no text')
    result, anchored = apply_script({'segments': raw['segments']}, lines)
    if anchored is None:
        raise InputError('raw_asr.json has no timed characters to align the script onto')
    pages = chunks_to_pages(build_chunks(result, max_words=MAX_WORDS, max_chars=MAX_CHARS, pause=PAUSE))
    if not pages:
        raise InputError('alignment produced no pages')
    return pages, word_anchors(pages, lines, anchored)


def write_atomic(path, text):
    tmp = '%s.tmp.%d' % (path, os.getpid())
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv=None):
    ap = argparse.ArgumentParser(description='align the exact script onto raw ASR word times -> caption_pages.json')
    ap.add_argument('--raw', required=True, help='raw_asr.json written by asr_transcribe.py')
    ap.add_argument('--script', required=True, help='plain .txt of the spoken lines, in order')
    ap.add_argument('--out', required=True, help='caption_pages.json to write')
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    try:
        if os.path.lexists(a.out) and os.path.realpath(a.out) not in (os.path.realpath(a.raw), os.path.realpath(a.script)):
            os.unlink(a.out)                       # never leave the previous run's pages behind when this run fails
    except OSError as e:
        print('ERROR: cannot remove the old %s: %s' % (a.out, e), file=sys.stderr)
        return 2
    try:
        try:
            raw = json.load(open(a.raw, encoding='utf-8'))
        except (OSError, ValueError) as e:
            raise InputError('cannot read %s: %s' % (a.raw, e))
        validate_raw(raw)
        try:
            script_sha = hashlib.sha256(open(a.script, 'rb').read()).hexdigest()
        except OSError as e:
            raise InputError('cannot read script %s: %s' % (a.script, e))
        if raw.get('script_sha256') != script_sha:
            raise InputError('raw_asr.json was decoded for another script (script_sha256 %s != sha256 of %s = %s): run '
                             'asr_transcribe.py on this script first' % (str(raw.get('script_sha256'))[:16], a.script, script_sha[:16]))
        have = tokenizer_version()
        if have != raw['tokenizer']['pythainlp']:
            raise TokenizerError('pythainlp %s here but raw_asr.json was checked with %s: run asr_align.py through '
                                 'asr_run.sh (the V4 ASR venv python that wrote it)'
                                 % (have, raw['tokenizer']['pythainlp']))
        try:
            lines = read_script_lines(a.script)
        except (OSError, UnicodeDecodeError) as e:
            raise InputError('cannot read script %s: %s' % (a.script, e))
        pages, _ = align(raw, lines)
        write_atomic(a.out, pages_text(pages))
    except InputError as e:
        print('ERROR: %s' % e, file=sys.stderr)
        return 2
    except TokenizerError as e:
        print('ERROR: %s' % e, file=sys.stderr)
        return 4
    except OSError as e:
        print('ERROR: cannot write %s: %s' % (a.out, e), file=sys.stderr)
        return 2
    print('wrote %d pages / %d words -> %s' % (len(pages), sum(len(p['words']) for p in pages), a.out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
