#!/usr/bin/env python3
"""Pre-render b-roll uniqueness gate for the YT-News V2 skill.

  python check_broll.py <CompId.tsx> --media-dir <mediaDir>
                        --manifest projects/<slug>/assets/broll/_manifest.json
                        [--public-root remotion-composer/public] [--projects-root projects]
                        [--ledger projects/_broll_ledger.json] [--max-old 2]

Exit 0 = pass, 1 = violations, 2 = usage / parse error. The ledger is (re)seeded from the
public + project folders on every run, so a missing or stale ledger cannot cause a PASS.

"Fresh" is positive: a stock file is fresh only if fetch_broll.py downloaded it for THIS
episode (it is a key in --manifest, the raw file still matches the manifest md5) AND its
content (public file and raw file) is not found in any other episode. Everything else is
"old"; at most --max-old (hard cap 2) old stock files are allowed. Checks:
  1. BEATS parsed fail-closed (real tokenizer; spreads / .map / duplicate decls = exit 2)
  2. every footage beat has an explicit `src` (media broll/clip/typo)
  3. no src is used by more than one beat
  4. every referenced file exists as public/<mediaDir>/broll/<src>.mp4
  5. no two different srcs are byte-identical (renamed copies)
  6. yt_ clips must be cut from this episode's source: content found in another episode
     is a hard violation (never counted toward the allowance)
  7. old stock files (see above) <= --max-old
  8. raw file of a manifest key unchanged since fetch
  9. composition's assetDir == --media-dir
 10. mediaDir not already recorded for a different composition
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import broll_ledger as bl  # noqa: E402


def _eps(s, limit=4) -> str:
    s = sorted(s)
    return ", ".join(s[:limit]) + (f" (+{len(s) - limit} more)" if len(s) > limit else "")


def check(beats, media_dir, public_root, ledger, max_old, manifest, raw_dir, slug,
          comp_name=None, asset_dirs=None):
    """Returns (violations, rows, warnings). rows = [{src, kind, uses, ts, status}]."""
    violations: list[str] = []
    warnings: list[str] = []
    own = (media_dir, slug)

    mk = ledger.get("episodes", {}).get(media_dir)
    if comp_name and isinstance(mk, dict) and mk.get("comp") and mk["comp"] != comp_name:
        violations.append(f"mediaDir `{media_dir}` was already recorded for composition {mk['comp']}, "
                          f"not {comp_name} — use a new mediaDir for a new video")

    if asset_dirs is not None:
        if not asset_dirs:
            warnings.append("no `assetDir: \"...\"` found in the composition — cannot verify it "
                            f"points at public/{media_dir}")
        for d in sorted(set(asset_dirs)):
            if d != media_dir:
                violations.append(f"composition assetDir is `{d}` but --media-dir is `{media_dir}` — "
                                  "renders would play another episode's folder")

    uses: dict[str, list] = {}
    for fb in bl.footage_beats(beats):
        if fb["src"] is None:
            violations.append(
                f"beat t={fb['t']} (media={fb['media']}) has no `src` — the component silently "
                "falls back to a default file; set an explicit src")
            continue
        uses.setdefault(fb["src"], []).append(fb["t"])

    for src, ts in uses.items():
        if len(ts) > 1:
            violations.append(f"`{src}` is used by {len(ts)} beats (t={', '.join(str(t) for t in ts)}); "
                              "each footage file may be used by at most one beat")

    broll_dir = Path(public_root) / media_dir / "broll"
    md5s: dict[str, str] = {}
    for src in uses:
        f = broll_dir / f"{src}.mp4"
        if f.exists():
            md5s[src] = bl.file_md5(ledger, f)
        else:
            violations.append(f"`{src}` is missing: {f}")

    by_md5: dict[str, list[str]] = {}
    for src, m in md5s.items():
        by_md5.setdefault(m, []).append(src)
    for m, srcs in by_md5.items():
        if len(srcs) > 1:
            violations.append(f"identical files under different names (md5 {m[:12]}): "
                              f"{', '.join(sorted(srcs))} — a renamed copy is still the same footage")

    idx = bl.episodes_by_md5(ledger)
    old: dict[str, list[str]] = {}
    bad_yt: set[str] = set()
    for src in uses:
        is_yt = bl.is_yt_key(src)
        reasons: list[str] = []
        others = bl.other_episodes(idx, md5s[src], own) if src in md5s else set()
        if is_yt:
            if others:
                bad_yt.add(src)
                violations.append(f"`{src}` has the same content as footage of other episodes "
                                  f"({_eps(others)}) — yt_ clips must be cut from THIS episode's source video")
            continue
        if others:
            reasons.append(f"same content as {_eps(others)}")
        m = manifest.get(src) if isinstance(manifest, dict) else None
        raw_md5 = m.get("raw_md5") if isinstance(m, dict) else None
        if not raw_md5:
            reasons.append("not in this episode's fetch manifest (not downloaded by fetch_broll for this video)")
        else:
            raw = next((raw_dir / f"{src}{e}" for e in bl.MEDIA_EXTS if (raw_dir / f"{src}{e}").exists()), None)
            if raw is None:
                violations.append(f"`{src}` is in the manifest but its raw file is missing: "
                                  f"{raw_dir / (src + '.mp4')}")
            elif bl.file_md5(ledger, raw) != raw_md5:
                violations.append(f"`{src}`: raw file changed after fetch ({raw.name} md5 != manifest raw_md5)")
            else:
                raw_others = bl.other_episodes(idx, raw_md5, own)
                if raw_others:
                    reasons.append(f"raw download also used by {_eps(raw_others)}")
        if reasons:
            old[src] = reasons
    if len(old) > max_old:
        lines = "\n    ".join(f"{s}: {'; '.join(r)}" for s, r in sorted(old.items()))
        violations.append(f"{len(old)} stock files are old / not fresh (max {max_old}):\n    {lines}")

    rows = []
    for src, ts in uses.items():
        if src not in md5s:
            status = "missing"
        elif src in bad_yt:
            status = "copied"
        elif src in old:
            status = "old"
        else:
            status = "fresh"
        rows.append({"src": src, "kind": "yt" if bl.is_yt_key(src) else "stock",
                     "uses": len(ts), "ts": ts, "status": status})
    rows.sort(key=lambda r: (r["kind"], r["src"]))
    return violations, rows, warnings


def print_table(rows: list[dict]) -> None:
    w = max([len("src")] + [len(r["src"]) for r in rows])
    print(f"{'src':<{w}}  {'kind':<5}  {'uses':>4}  status")
    for r in rows:
        print(f"{r['src']:<{w}}  {r['kind']:<5}  {r['uses']:>4}  {r['status']}")


def _max_old(v: str) -> int:
    n = int(v)
    if n < 0 or n > bl.MAX_OLD_CAP:
        raise argparse.ArgumentTypeError(f"--max-old must be 0..{bl.MAX_OLD_CAP} (got {n})")
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check b-roll uniqueness of a Remotion composition.")
    ap.add_argument("composition", help="CompId.tsx (path, or name under remotion-composer/src)")
    ap.add_argument("--media-dir", required=True, help="folder name under remotion-composer/public/")
    ap.add_argument("--manifest", required=True,
                    help="projects/<slug>/assets/broll/_manifest.json written by fetch_broll.py")
    ap.add_argument("--public-root", default=bl.DEFAULT_PUBLIC_ROOT)
    ap.add_argument("--projects-root", default=bl.DEFAULT_PROJECTS_ROOT)
    ap.add_argument("--ledger", default=bl.DEFAULT_LEDGER)
    ap.add_argument("--max-old", type=_max_old, default=2,
                    help=f"max old stock files per video, 0..{bl.MAX_OLD_CAP} (default 2)")
    args = ap.parse_args(argv)

    mpath = Path(args.manifest).resolve()
    if mpath.parent.name != "broll" or mpath.parent.parent.name != "assets":
        print("ERROR: --manifest must be projects/<slug>/assets/broll/_manifest.json", file=sys.stderr)
        return 2
    slug = mpath.parent.parent.parent.name
    try:
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be a JSON object")
        text = bl.read_composition_text(args.composition)
        beats = bl.parse_beats(text)
        asset_dirs = bl.find_asset_dirs(text)
        bl.footage_beats(beats)
        bl.auto_seed(args.ledger, args.public_root, args.projects_root)
        ledger = bl.load_ledger(args.ledger)
        violations, rows, warnings = check(
            beats, args.media_dir, args.public_root, ledger, args.max_old, manifest, mpath.parent, slug,
            comp_name=Path(args.composition).name, asset_dirs=asset_dirs)
    except (OSError, bl.BeatsParseError, ValueError) as e:  # json errors are ValueErrors
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print_table(rows)
    for w in warnings:
        print(f"warning: {w}")
    print()
    if violations:
        for v in violations:
            print(f"VIOLATION: {v}")
        print(f"\nFAIL — {len(violations)} violation(s)")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
