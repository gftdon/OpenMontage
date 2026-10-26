#!/usr/bin/env python3
"""Fetch FRESH stock b-roll (Pixabay, free licence) — never a clip used before.

  python fetch_broll.py QUERIES.json OUT_DIR [--ledger projects/_broll_ledger.json]
                        [--public-root remotion-composer/public] [--projects-root projects]
                        [--env .env] [--per-page 30] [--dry-run]
                        [--music "query" MUSIC_OUT.mp3]

OUT_DIR is the episode's raw folder: projects/<slug>/assets/broll (the slug is read from
the path and identifies the episode in the ledger).
QUERIES.json = {"coding": ["programmer coding laptop screen", "computer"], ...}
(key -> [search query, pixabay category]); keys starting with "_" are ignored.

The ledger is re-seeded from the public + project folders at start (so a missing or stale
ledger cannot let an old clip through). For each key it walks Pixabay search pages 1..3
(8-40 s clips, 'large' rendition preferred) and takes the first candidate that is NOT
  - a Pixabay id already used (ledger) or reserved by another episode, or already in this
    folder's manifest,
  - a download whose md5 matches a raw / yt file already known to the ledger.
A chosen id is RESERVED in the ledger (under the lock) before it is downloaded, so two
episodes fetched at the same time cannot take the same clip. Reserved is not "used".
A failed download tries the next candidate; paging stops when a page is short or Pixabay
answers 400 for page > 1.
Result: OUT_DIR/<key>.mp4 + OUT_DIR/_manifest.json
        {key: {pixabay_id, page_url, query, category, raw_md5, duration}}
A pre-existing OUT_DIR/<key>.* that fetch_broll did not write (not in the manifest with
that md5) or that matches another episode is FAILED: delete it and re-run.
Run `broll_ledger.py record` after the episode is built to mark the clips as used.

Run from the repo root with the project .venv (PIXABAY_API_KEY in .env).
Always view a contact sheet of the results afterwards: a search hit can still be the
wrong scene (e.g. a "shopping" query returning a kitchen blender).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import broll_ledger as bl  # noqa: E402

API_URL = "https://pixabay.com/api/videos/"
MIN_DUR, MAX_DUR = 8, 40
MAX_PAGES = 3
QUALITIES = ("large", "medium", "small", "tiny")


class Page(list):
    """Duration-filtered candidates of one search page; .raw_count = hits before filtering."""
    raw_count = None


def pick_rendition(hit: dict):
    """First available rendition large -> medium -> small -> tiny, as (url, quality)."""
    videos = hit.get("videos") or {}
    for q in QUALITIES:
        url = (videos.get(q) or {}).get("url")
        if url:
            return url, q
    return None, None


def effective_per_page(per_page: int) -> int:
    return max(3, min(per_page, 200))  # Pixabay rejects <3 / >200 with 400


def search_candidates(api_key: str, query: str, category: str, page: int, per_page: int) -> Page:
    """One Pixabay search page -> ordered, duration-filtered candidates.

    Each candidate: {id, page_url, url, quality, duration}. Mirrors the HTTP params of
    tools/video/pixabay_video.py (plus `category`). HTTP 400 on page > 1 means "past the
    last page" and returns an empty page.
    """
    import requests

    params = {
        "key": api_key,
        "q": query[:100],
        "per_page": effective_per_page(per_page),
        "page": page,
        "safesearch": "true",
    }
    if category:
        params["category"] = category
    r = requests.get(API_URL, params=params, timeout=30)
    if page > 1 and getattr(r, "status_code", None) == 400:
        empty = Page()
        empty.raw_count = 0
        return empty
    r.raise_for_status()
    hits = r.json().get("hits", [])
    out = Page()
    out.raw_count = len(hits)
    for h in hits:
        dur = h.get("duration") or 0
        if dur < MIN_DUR or dur > MAX_DUR:
            continue
        url, quality = pick_rendition(h)
        if not url:
            continue
        out.append({"id": str(h["id"]), "page_url": h.get("pageURL", ""), "url": url,
                    "quality": quality, "duration": dur})
    return out


def download_file(url: str, dest) -> None:
    """Download immediately (Pixabay URLs expire)."""
    import requests

    with requests.get(url, timeout=120, stream=True) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)


def _load_manifest(path: Path) -> dict:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            print(f"WARN  manifest {path} is not valid JSON — starting a new one")
    return {}


def _save_manifest(path: Path, manifest: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _existing(out: Path, key: str):
    return [out / f"{key}{e}" for e in bl.MEDIA_EXTS if (out / f"{key}{e}").exists()]


def fetch_videos(queries_path, out_dir, ledger_path=bl.DEFAULT_LEDGER, api_key="",
                 per_page=30, dry_run=False, public_root=bl.DEFAULT_PUBLIC_ROOT,
                 projects_root=bl.DEFAULT_PROJECTS_ROOT) -> int:
    """Returns the process exit code (0 = all keys ok, 1 = at least one key failed)."""
    out = Path(out_dir)
    slug = bl.slug_from_raw_dir(out)
    queries = json.loads(Path(queries_path).read_text(encoding="utf-8"))
    bl.auto_seed(ledger_path, public_root, projects_root)
    ledger = bl.load_ledger(ledger_path)
    manifest_path = out / "_manifest.json"
    manifest = _load_manifest(manifest_path)
    chosen_ids = {str(m.get("pixabay_id")) for m in manifest.values()
                  if isinstance(m, dict) and m.get("pixabay_id")}
    dup_md5s = set(bl.known_md5s(ledger, ("raw", "yt")))
    dup_md5s |= {m["raw_md5"] for m in manifest.values() if isinstance(m, dict) and m.get("raw_md5")}
    idx = bl.episodes_by_md5(ledger)
    eff = effective_per_page(per_page)
    if not dry_run:
        out.mkdir(parents=True, exist_ok=True)

    failed = 0
    for key, spec in queries.items():
        if key.startswith("_"):
            continue

        existing = _existing(out, key)
        if existing:
            md5 = bl.file_md5(ledger, existing[0])
            m = manifest.get(key)
            others = bl.other_episodes(idx, md5, (slug,))
            if not (isinstance(m, dict) and m.get("raw_md5") == md5):
                print(f"FAIL {key} existing file was not fetched by fetch_broll (copied?) — "
                      "delete it and re-run")
                failed += 1
            elif others:
                print(f"FAIL {key} existing file matches footage of another episode "
                      f"({', '.join(sorted(others))}) — delete it and re-run")
                failed += 1
            else:
                print(f"skip {key} (exists, matches manifest)")
            continue

        query, category = (list(spec) + [""])[:2] if isinstance(spec, (list, tuple)) else (str(spec), "")
        blocked = bl.blocked_pixabay_ids(bl.load_ledger(ledger_path), slug)  # fresh view of reservations
        got = False
        error = None
        for page_no in range(1, MAX_PAGES + 1):
            try:
                page = search_candidates(api_key, query, category, page_no, per_page)
            except Exception as e:  # network / HTTP error: report, keep going with other keys
                error = f"{type(e).__name__}: {e}"
                break
            for cand in page:
                cid = cand["id"]
                if cid in blocked or cid in chosen_ids:
                    continue
                if dry_run:
                    chosen_ids.add(cid)
                    print(f"DRY  {key}: id={cid} {cand['duration']}s page={page_no} {cand['page_url']}")
                    got = True
                    break
                with bl.locked_ledger(ledger_path) as L:
                    won = bl.reserve_pixabay_id(L, cid, slug, key)
                if not won:
                    continue
                tmp = out / f".tmp_{key}.mp4"
                try:
                    download_file(cand["url"], tmp)
                    md5 = bl.md5_file(tmp)
                except Exception as e:  # this candidate failed — try the next one
                    print(f"  {key}: id={cid} download failed ({type(e).__name__}: {e}) — next candidate")
                    tmp.unlink(missing_ok=True)
                    with bl.locked_ledger(ledger_path) as L:
                        bl.release_pixabay_id(L, cid, slug)
                    continue
                if md5 in dup_md5s:
                    tmp.unlink(missing_ok=True)
                    print(f"  {key}: id={cid} is byte-identical to a known file — next candidate")
                    continue
                os.replace(tmp, dest := out / f"{key}.mp4")
                dup_md5s.add(md5)
                chosen_ids.add(cid)
                manifest[key] = {"pixabay_id": cid, "page_url": cand["page_url"], "query": query,
                                 "category": category, "raw_md5": md5, "duration": cand["duration"]}
                _save_manifest(manifest_path, manifest)
                print(f"{key} OK id={cid} {cand['duration']}s md5={md5[:12]} -> {dest}")
                got = True
                break
            if got:
                break
            rc = getattr(page, "raw_count", None)
            if rc is not None and rc < eff:
                break  # short page = last page
        if error and not got:
            print(f"FAIL {key} {error}")
            failed += 1
        elif not got:
            print(f"FAIL {key} no fresh clip — use a more specific query")
            failed += 1
    return 1 if failed else 0


def fetch_music(query: str, out_path: str) -> None:
    sys.path.insert(0, os.getcwd())
    from tools.tool_registry import registry  # noqa: E402

    registry.discover()
    pm = registry._tools["pixabay_music"]
    r = pm.execute({"query": query, "min_duration": 120, "max_duration": 400, "output_path": out_path})
    print("music", "OK" if r.success else f"FAIL {r.error}", (r.data or {}).get("track_title"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Fetch fresh (never-used) Pixabay stock b-roll.")
    ap.add_argument("queries", nargs="?", help='QUERIES.json: {"key": ["query", "category"]}')
    ap.add_argument("out_dir", nargs="?", help="projects/<slug>/assets/broll; also holds _manifest.json")
    ap.add_argument("--ledger", default=bl.DEFAULT_LEDGER)
    ap.add_argument("--public-root", default=bl.DEFAULT_PUBLIC_ROOT)
    ap.add_argument("--projects-root", default=bl.DEFAULT_PROJECTS_ROOT)
    ap.add_argument("--env", default=".env", help="dotenv file holding PIXABAY_API_KEY (default .env)")
    ap.add_argument("--per-page", type=int, default=30, help="Pixabay results per page (3-200, default 30)")
    ap.add_argument("--dry-run", action="store_true", help="search and print the chosen candidates; download nothing")
    ap.add_argument("--music", nargs=2, metavar=("QUERY", "MUSIC_OUT"),
                    help='also fetch a Pixabay music track, e.g. --music "calm tech" music.mp3')
    args = ap.parse_args(argv)
    if not args.music and not (args.queries and args.out_dir):
        ap.error("QUERIES.json and OUT_DIR are required (or use --music)")

    from dotenv import load_dotenv

    load_dotenv(args.env)
    rc = 0
    if args.music:
        fetch_music(*args.music)
    if args.queries and args.out_dir:
        api_key = os.environ.get("PIXABAY_API_KEY", "")
        if not api_key:
            print(f"ERROR: PIXABAY_API_KEY not set (looked in {args.env})", file=sys.stderr)
            return 2
        try:
            rc = fetch_videos(args.queries, args.out_dir, args.ledger, api_key, args.per_page,
                              args.dry_run, args.public_root, args.projects_root)
        except (OSError, ValueError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
    return rc


if __name__ == "__main__":
    sys.exit(main())
