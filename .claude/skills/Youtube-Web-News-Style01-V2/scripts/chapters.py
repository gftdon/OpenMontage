#!/usr/bin/env python3
"""YouTube description chapters from the timeline export.
usage: chapters.py EVENTS.json [OUT.txt] [--first "title for 0:00"] [--last "title at VO end"]
Defaults: --first "ตัวอย่างข่าว (Preview)"  --last "สรุป + Subscribe"
YouTube rules: first chapter at 0:00, at least 3 chapters, each >= 10 s (shorter ones are merged into the previous).
"""
import json, sys

args = sys.argv[1:]
def opt(name, default):
    if name in args:
        i = args.index(name); v = args[i + 1]; del args[i:i + 2]; return v
    return default
first = opt("--first", "ตัวอย่างข่าว (Preview)")
last = opt("--last", "สรุป + Subscribe")
ev = json.load(open(args[0]))
rows = [(0.0, first)] + [(c["t"], c["title"]) for c in ev["chapters"]] + [(ev["voEnd"], last)]
out, prev = [], None
for t, title in rows:
    if prev is not None and t - prev < 10:
        continue
    m, s = divmod(int(round(t)), 60)
    out.append(f"{m}:{s:02d} {title}")
    prev = t
text = "\n".join(out)
print(text)
if len(args) > 1:
    open(args[1], "w").write(text + "\n")
