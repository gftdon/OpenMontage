"""Dump whisper word times grouped by script line (for keying stat chips / cues).
usage: python words_by_line.py caption_pages_final.json script.txt [line numbers...]
"""
import json, re, sys
pages = json.load(open(sys.argv[1]))
lines = [l for l in open(sys.argv[2], encoding='utf-8').read().splitlines() if l.strip()]
want = set(int(x) for x in sys.argv[3:])
norm = lambda s: re.sub(r'\s+', '', s)
nl = [norm(l) for l in lines]
words = []; li = 0; pos = 0
for p in pages:
    for w in p['words']:
        t = norm(w['w'])
        while li < len(nl) and not nl[li][pos:].startswith(t):
            pos += 1
            if pos >= len(nl[li]): li += 1; pos = 0
        words.append((li + 1, w['w'], w['s'], w['e']))
        pos += len(t)
        if li < len(nl) and pos >= len(nl[li]): li += 1; pos = 0
for L in range(1, len(lines) + 1):
    if want and L not in want: continue
    ws = [(w, s) for (l, w, s, e) in words if l == L]
    print(f"L{L}:", ' '.join(f"{w}@{s:.1f}" for w, s in ws))
