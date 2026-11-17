"""Dump whisper word times grouped by script line (for keying stat chips / cues).

  python words_by_line.py <caption_pages.json> <script.txt> [line numbers...]

caption_pages.json is the raw word_timing.sh output ([{start,end,words:[{w,s,e}]}]; pages may cross script lines).
Prints one `L<n>: word@sec word@sec ...` row per spoken (non-blank) script line, or only the lines asked for.

map_tokens() is the ONE matcher of word tokens to script lines (line_starts.py imports it): it walks the whole
script as one whitespace-free character string, consuming the tokens in order; a token belongs to the line holding
its first character (a token may straddle a line break). strict=False (this tool) skips script characters that no
token matches; strict=True (line_starts.py) raises MappingError instead, with the line number and both snippets.
"""
import argparse
import bisect
import json
import re
import sys


class MappingError(ValueError):
    pass


def norm(s):
    return re.sub(r'\s+', '', s)


def flatten(pages):
    return [w for p in pages for w in p['words']]


def spoken_lines(text):
    return [l for l in text.splitlines() if l.strip()]


def map_tokens(tokens, script_lines, strict=False):
    """-> list of 1-based line numbers, one per token (see module docstring). Lenient mode gives len(lines)+1 once the script is used up."""
    nl = [norm(l) for l in script_lines if l.strip()]
    text = ''.join(nl)
    starts, c = [], 0
    for l in nl:
        starts.append(c)
        c += len(l)

    def line_at(pos):
        return len(nl) + 1 if pos >= len(text) else bisect.bisect_right(starts, pos)

    out = []
    pos = 0
    for k, tok in enumerate(tokens):
        t = norm(tok['w'])
        if t and not text.startswith(t, pos):
            if strict:
                ahead = ' '.join(x['w'] for x in tokens[k:k + 4])
                raise MappingError('line %d mapping mismatch:\n  script: %s\n  tokens: %s' % (min(line_at(pos), len(nl)), text[pos:pos + 40] or '(end of script)', ahead[:40]))
            while pos < len(text) and not text.startswith(t, pos):
                pos += 1
        out.append(line_at(pos))
        pos += len(t)
    if strict and pos < len(text):
        raise MappingError('line %d mapping mismatch:\n  script: %s\n  tokens: (no more tokens)' % (line_at(pos), text[pos:pos + 40]))
    return out


def words_by_line(pages, script_lines):
    """[(line, word, start, end)] for every token, lenient matching."""
    tokens = flatten(pages)
    return [(l, t['w'], t['s'], t['e']) for l, t in zip(map_tokens(tokens, script_lines), tokens)]


def main(argv=None):
    ap = argparse.ArgumentParser(description='Dump whisper word times grouped by script line.')
    ap.add_argument('caption_pages', help='raw word_timing.sh pages JSON ([{start,end,words:[{w,s,e}]}])')
    ap.add_argument('script', help='script.txt, one spoken line per row')
    ap.add_argument('lines', nargs='*', type=int, help='only these 1-based line numbers (default: all)')
    a = ap.parse_args(argv)
    pages = json.load(open(a.caption_pages))
    lines = spoken_lines(open(a.script, encoding='utf-8').read())
    want = set(a.lines)
    words = words_by_line(pages, lines)
    for L in range(1, len(lines) + 1):
        if want and L not in want:
            continue
        ws = [(w, s) for (l, w, s, e) in words if l == L]
        print(f"L{L}:", ' '.join(f"{w}@{s:.1f}" for w, s in ws))


if __name__ == '__main__':
    sys.exit(main())
