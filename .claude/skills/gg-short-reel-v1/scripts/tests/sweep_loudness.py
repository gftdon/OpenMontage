#!/usr/bin/env python3
"""MANUAL TOOL (not auto-discovered: no `test` prefix). Loudness-gate sweep through the REAL gg_short_reel pipeline.

    /Volumes/Ext_SS990Pro/Dev/openMontage-video-production/.venv/bin/python sweep_loudness.py [--seeds 30]

Cases: anoisesrc 'bursts' fixture (amp 0.9) with seed 1..N, plus the tone / quiet fixtures. For each: the final's integrated
LUFS and true peak measured independently (test_support.measure_loudness) and whether the pipeline's own gate passed
(receipt status). Exit code 0 only when every case passes. No network.
"""
import argparse
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_support as ts  # noqa: E402

GATE_I, GATE_TOL, GATE_TP = -14.0, 1.0, -1.0


def run_case(label, **task_kw):
    import gg_short_reel
    with tempfile.TemporaryDirectory() as d:
        task = ts.Task(Path(d), **task_kw)
        rc = gg_short_reel.run(task.request_path, music_provider=None, timeout_s=300)
        res = task.result()
        if rc == 0 and res["status"] == "succeeded":
            i, tp = ts.measure_loudness(task.final)
            ok = abs(i - GATE_I) <= GATE_TOL and tp <= GATE_TP
            return label, i, tp, ok, ""
        m = re.search(r"loudness (-?[\d.]+) LUFS / true peak (-?[\d.]+) dBTP", res.get("error", ""))
        i, tp = (float(m.group(1)), float(m.group(2))) if m else (float("nan"), float("nan"))
        return label, i, tp, False, res.get("error", "")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    args = ap.parse_args(argv)
    cases = [(f"bursts seed={s}", dict(music_kind="bursts", music_amp=0.9, music_seed=s)) for s in range(1, args.seeds + 1)]
    cases += [("tone amp=0.3", dict(music_kind="tone", music_amp=0.3)), ("tone amp=0.02 (quiet)", dict(music_kind="tone", music_amp=0.02)),
              ("tone amp=0.05 (quiet)", dict(music_kind="tone", music_amp=0.05)), ("tone amp=0.9 (loud)", dict(music_kind="tone", music_amp=0.9))]
    passed = 0
    print(f"{'case':<24}{'LUFS':>8}{'dBTP':>8}  result")
    for label, kw in cases:
        label, i, tp, ok, err = run_case(label, **kw)
        passed += ok
        print(f"{label:<24}{i:>8.2f}{tp:>8.2f}  {'PASS' if ok else 'FAIL ' + err}", flush=True)
    print(f"\n{passed}/{len(cases)} pass (gate: {GATE_I:g} +/- {GATE_TOL:g} LUFS, TP <= {GATE_TP:g} dBTP)")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
