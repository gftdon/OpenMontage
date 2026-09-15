#!/usr/bin/env python3
"""Map a YouTube Studio audience-retention export onto the episode's beats.

usage: retention_map.py EVENTS.json RETENTION.csv [--top 8]

RETENTION.csv = YouTube Studio > Analytics > Engagement > Audience retention >
"Export current view" (CSV). Accepted column shapes (case-insensitive):
  - "Video position (%)" , "Absolute audience retention (%)"   (YouTube export)
  - "position_pct" , "retention_pct"                            (hand-made)
  - "time_sec" , "retention_pct"
Output: per-beat retention loss (percentage points lost inside the beat),
the steepest drops, and the beats to fix first — feed those numbers back into
the format rules (lint thresholds, pacing).
"""
import csv, json, sys

def load_curve(path, total):
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    if not rows:
        raise SystemExit("empty csv")
    keys = {k.lower().strip(): k for k in rows[0].keys()}
    def pick(*cands):
        for c in cands:
            for k in keys:
                if c in k:
                    return keys[k]
        return None
    pos = pick("video position", "position_pct", "position (%)")
    tim = pick("time_sec", "elapsed")
    ret = pick("audience retention", "retention")
    if not ret or not (pos or tim):
        raise SystemExit(f"cannot find columns in {list(rows[0].keys())}")
    curve = []
    for r in rows:
        try:
            t = float(r[pos]) / 100 * total if pos else float(r[tim])
            v = float(str(r[ret]).replace("%", ""))
        except ValueError:
            continue
        curve.append((t, v))
    curve.sort()
    return curve

def at(curve, t):
    prev = curve[0]
    for p in curve:
        if p[0] >= t:
            if p[0] == prev[0]:
                return p[1]
            f = (t - prev[0]) / (p[0] - prev[0])
            return prev[1] + (p[1] - prev[1]) * f
        prev = p
    return curve[-1][1]

def main():
    ev = json.load(open(sys.argv[1]))
    curve = load_curve(sys.argv[2], ev["total"])
    top = int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else 8
    rows = []
    for b in ev["beats"]:
        a, z = at(curve, b["t"]), at(curve, b["end"])
        dur = max(0.01, b["end"] - b["t"])
        rows.append({**b, "ret_in": round(a, 1), "ret_out": round(z, 1), "loss": round(a - z, 2), "loss_per_10s": round((a - z) / dur * 10, 2)})
    print(f"{'t':>7} {'dur':>5} {'media':<9} {'in%':>6} {'out%':>6} {'loss':>6} {'/10s':>6}  kicker")
    for r in rows:
        print(f"{r['t']:7.1f} {r['end']-r['t']:5.1f} {str(r['media'] or r['mode']):<9} {r['ret_in']:6.1f} {r['ret_out']:6.1f} {r['loss']:6.2f} {r['loss_per_10s']:6.2f}  {r['kicker'] or ''}")
    print("\nSTEEPEST DROPS (fix these first):")
    for r in sorted(rows, key=lambda r: -r["loss_per_10s"])[:top]:
        print(f"  t={r['t']:.1f}s  {r['media'] or r['mode']:<9} -{r['loss_per_10s']:.2f} pts / 10 s   {r['kicker'] or ''}")
    first30 = at(curve, 0) - at(curve, 30)
    print(f"\nFirst 30 s loss: {first30:.1f} pts   (target < 30)   retention at 50%: {at(curve, ev['total']*0.5):.1f}%   at VO end: {at(curve, ev['voEnd']):.1f}%")

if __name__ == "__main__":
    main()
