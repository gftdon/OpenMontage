#!/usr/bin/env python3
"""V4: fetch the MUSIC BED: the owner-approved local library first, Pixabay Music (free licence) only when that
library is empty. Stock FOOTAGE fetching is disabled in V4.

  python fetch_broll.py --music "<query>" projects/<slug>/assets/audio/bed.mp3 [--force]

ORDER (the owner chose the music, so an online source never silently replaces it):
 1. The approved list `music_library.json` next to this script (helper: music_library.py) is loaded first. An
    unreadable / invalid list, or an invalid MUSIC_LIBRARY_DIR, is exit 4 (Pixabay is not tried).
 2. List with >= 1 track: library ONLY, Pixabay is never called. The first track in list order whose file is
    present with the right sha256 is copied atomically to out.mp3 and the copy is re-verified. Files live in
    `<repo root>/music_library` or the absolute dir in env MUSIC_LIBRARY_DIR (repo root = the current directory,
    the same "run from the repo root" convention as the Pixabay tool). No usable track -> exit 4.
 3. EMPTY list: Pixabay Music, as before. If that fails too -> exit 4 naming both reasons.
There is no flag or variable that points the fetch at another list.

Writes the mp3 and a sidecar `<out.mp3>.source.json`
  library:  {"schema":"yt-news-v4-music-source","provider":"music_library","track_id":null,"track_title":<manifest
             title>,"url":null,"query","sha256":<of the delivered mp3>,"fetched_at":<UTC ISO>,"library_file",
             "license","origin","approved_by","approved_on","manifest_sha256":<of music_library.json>}
  pixabay:  {"schema":"yt-news-v4-music-source","provider":"pixabay_music","track_id","track_title","url","query",
             "sha256":<of the mp3>,"fetched_at":<UTC ISO>}      (a field the provider does not return is null)
A Pixabay mp3 is only accepted when ffprobe finds an audio stream of at least 30 s. An existing out.mp3 is never
overwritten without --force (a failed --force run keeps the previous pair). Transient Pixabay failures (network
errors, HTTP 429 / 5xx, timeouts) are retried with backoff inside MUSIC_RETRY_BUDGET_SECONDS (180 s).
Exit codes: 0 ok (valid mp3 + sidecar exist), 2 usage / refusal to overwrite, 3 footage mode refused,
4 no music bed could be fetched (one `ERROR:` line ending "no music bed was written"; no partial mp3 /
sidecar left).

FOOTAGE MODE (positional QUERIES.json OUT_DIR, --plan, --context, --dry-run) exits 3 with
  "V4: stock footage fetching is disabled (no verified relevance verdicts); only --music is available".
No existing approval mechanism of this skill covers stock fetching (broll_costs.py / native_paid.py /
--approval gate paid image + relevance calls by provider, model and USD caps), so the refusal is
unconditional; there is no override. The V3 footage code below is kept unreachable for a later,
explicitly approved re-enable.

--- V3 footage mode (kept, disabled) ---------------------------------------------------------------
Fetch FRESH stock b-roll (Pixabay, free licence) — never a clip used before.

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
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import broll_ledger as bl  # noqa: E402
import music_library as ml  # noqa: E402

FOOTAGE_DISABLED_MESSAGE = ("V4: stock footage fetching is disabled (no verified relevance verdicts); "
                            "only --music is available")
MUSIC_RETRY_BUDGET_SECONDS = 180      # total time for retrying transient music failures
MUSIC_BACKOFF_FIRST, MUSIC_BACKOFF_MAX = 2.0, 30.0
MUSIC_MIN_SECONDS = 30                # a valid bed has an audio stream of at least this length
MUSIC_SCHEMA = "yt-news-v4-music-source"
API_URL = "https://pixabay.com/api/videos/"
MIN_DUR, MAX_DUR = 8, 40
MAX_PAGES = 3
QUALITIES = ("large", "medium", "small", "tiny")


class FootageDisabled(RuntimeError):
    pass


class MusicRefused(Exception):      # exit 2
    pass


class MusicFailed(Exception):       # exit 4
    pass


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


def queries_from_plan(plan,context):
    from broll_plan import validate_plan
    errors=validate_plan(plan,context)
    if errors:raise ValueError('; '.join(errors))
    queries={}
    for beat in plan['beats']:
        selected=beat['selected']
        if selected['tier']!='stock':continue
        path=Path(selected['path']);key=path.stem
        if path.name!=selected['path'] or not __import__('re').fullmatch(r'[A-Za-z0-9_-]+',key):raise ValueError('stock filename must be a safe basename')
        spec=[beat['query'],beat.get('category','')]
        if key in queries and queries[key]!=spec:raise ValueError('conflicting per-beat stock query')
        queries[key]=spec
    return queries

def fetch_videos(queries_path, out_dir, ledger_path=bl.DEFAULT_LEDGER, api_key="",
                 per_page=30, dry_run=False, public_root=bl.DEFAULT_PUBLIC_ROOT,
                 projects_root=bl.DEFAULT_PROJECTS_ROOT) -> int:
    """Returns the process exit code (0 = all keys ok, 1 = at least one key failed). DISABLED in V4: always raises."""
    raise FootageDisabled(FOOTAGE_DISABLED_MESSAGE)
    out = Path(out_dir)
    slug = bl.slug_from_raw_dir(out)
    queries = queries_path if isinstance(queries_path,dict) else json.loads(Path(queries_path).read_text(encoding="utf-8"))
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


# ------------------------------------------------------------------ music (the only V4 mode)

_sleep = time.sleep
_monotonic = time.monotonic
_TRANSIENT = re.compile(r"timeout|timed out|connection|network|temporar|reset by peer|unreachable|URLError|"
                        r"HTTP Error (?:429|5\d\d)|\b429\b|\b5\d\d\b|too many requests|service unavailable|bad gateway", re.I)
_NO_KEY = re.compile(r"api[ _-]?key|credential|unauthori[sz]ed|forbidden|HTTP Error 40[13]", re.I)


def get_music_tool():
    """The registry's pixabay_music tool (run from the repo root)."""
    sys.path.insert(0, os.getcwd())
    from tools.tool_registry import registry  # noqa: E402

    registry.discover()
    return registry._tools["pixabay_music"]


def probe_audio(path):
    """(has_audio_stream, duration_seconds) from ffprobe; (False, 0.0) for anything unreadable."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                            "stream=codec_type:format=duration", "-of", "json", str(path)],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return False, 0.0
        info = json.loads(r.stdout or "{}")
        streams = info.get("streams") or []
        duration = float((info.get("format") or {}).get("duration") or 0)
        return bool(streams) and streams[0].get("codec_type") == "audio", duration
    except (OSError, ValueError, subprocess.SubprocessError):
        return False, 0.0


def _one_line(text) -> str:
    return " ".join(str(text).split())[:300]


def _first(data, *keys):
    for k in keys:
        if isinstance(data, dict) and data.get(k) not in (None, ""):
            return data[k]
    return None


def fetch_music(query: str, out_path, force: bool = False, manifest_path=None, repo_root=None) -> dict:
    """Fetch the bed. Returns the sidecar dict; raises MusicRefused (exit 2) / MusicFailed (exit 4).
    The approved library (music_library.py) comes first: a non-empty list means library only (no Pixabay call);
    Pixabay is used only when the list is empty. On any failure nothing new is left behind (a failed --force run
    keeps the previous mp3 + sidecar).
    manifest_path / repo_root are a test seam only: main() never passes them (default: the manifest shipped with
    the skill, and the current directory as repo root)."""
    out = Path(out_path)
    if out.suffix.lower() != ".mp3":
        raise MusicRefused(f"MUSIC_OUT must be an .mp3 file (got {out})")
    if out.exists() and not force:
        raise MusicRefused(f"{out} already exists; refusing to overwrite it (use --force)")
    root = Path(repo_root) if repo_root is not None else Path(os.getcwd())
    try:
        manifest, manifest_sha = ml.load_manifest_with_sha(manifest_path if manifest_path is not None else ml.manifest_path())
        ml.library_dir(root)    # an invalid MUSIC_LIBRARY_DIR stops the run before anything is fetched
    except ml.MusicLibraryError as e:
        raise MusicFailed(f"music library: {_one_line(e)}; no music bed was written")
    if manifest["tracks"]:
        try:
            return _copy_from_library(query, out, manifest, manifest_sha, root)
        except MusicFailed as e:
            raise MusicFailed(f"music library: {_one_line(e)}; Pixabay is not tried because the approved list is not empty; "
                              "no music bed was written")
    try:
        return _fetch_pixabay(query, out)
    except MusicFailed as pixabay_error:
        try:
            ml.pick_track(root, manifest)      # an empty list always raises "music library is empty (...)"
            empty = "the approved list is empty"
        except ml.MusicLibraryError as e:
            empty = _one_line(e)
        raise MusicFailed(f"Pixabay: {_one_line(pixabay_error)}; music library: {empty}; no music bed was written")


def _copy_from_library(query: str, out: Path, manifest: dict, manifest_sha: str, root: Path) -> dict:
    side = Path(str(out) + ".source.json")
    part = out.with_name(out.name + ".part")
    side_part = side.with_name(side.name + ".part")

    def cleanup():
        part.unlink(missing_ok=True)
        side_part.unlink(missing_ok=True)

    try:
        track, src = ml.pick_track(root, manifest)
    except ml.MusicLibraryError as e:
        raise MusicFailed(str(e))
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        cleanup()
        with open(src, "rb") as fin, open(part, "wb") as fout:
            shutil.copyfileobj(fin, fout, 1 << 20)
            fout.flush()
            os.fsync(fout.fileno())
        sha = ml.sha256_file(part)
        if sha != track["sha256"]:
            raise MusicFailed(f"the copy of {track['file']} does not match its manifest sha256 "
                              f"({sha[:12]} != {track['sha256'][:12]})")
        sidecar = {"schema": MUSIC_SCHEMA, "provider": ml.SIDECAR_PROVIDER, "track_id": None,
                   "track_title": track["title"], "url": None, "query": query, "sha256": sha,
                   "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                   "library_file": track["file"], "license": track["license"], "origin": track["origin"],
                   "approved_by": track["approved_by"], "approved_on": track["approved_on"],
                   "manifest_sha256": manifest_sha}
        side_part.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(part, out)
        try:
            os.replace(side_part, side)
        except OSError:
            out.unlink(missing_ok=True)   # never leave an mp3 without its sidecar
            raise
        return sidecar
    except MusicFailed:
        cleanup()
        raise
    except OSError as e:
        cleanup()
        raise MusicFailed(f"could not copy the library track: {_one_line(e)}")


def _fetch_pixabay(query: str, out: Path) -> dict:
    side = Path(str(out) + ".source.json")
    part = out.with_name(out.name + ".part")
    side_part = side.with_name(side.name + ".part")

    def cleanup():
        part.unlink(missing_ok=True)
        side_part.unlink(missing_ok=True)

    try:
        tool = get_music_tool()
    except Exception as e:  # registry cannot be loaded (not run from the repo root, ...)
        raise MusicFailed(f"music tool unavailable: {_one_line(e)}")
    status = getattr(getattr(tool, "get_status", lambda: None)(), "value", "available")
    if status != "available":
        raise MusicFailed("music provider unavailable (missing API key / not set up): "
                          + _one_line(getattr(tool, "install_instructions", status)))
    out.parent.mkdir(parents=True, exist_ok=True)
    started, delay, attempt = _monotonic(), MUSIC_BACKOFF_FIRST, 0
    data = None
    while True:
        attempt += 1
        cleanup()
        try:
            r = tool.execute({"query": query, "min_duration": 120, "max_duration": 400, "output_path": str(part)})
            ok, error, data = bool(r.success), r.error, (r.data or {})
        except Exception as e:  # tool raised: network class errors are transient
            transient = isinstance(e, (OSError, TimeoutError))
            ok, error, data = False, f"{type(e).__name__}: {e}", {}
            if not transient:
                cleanup()
                raise MusicFailed(f"music fetch failed: {_one_line(error)}")
        if ok:
            break
        cleanup()
        if _NO_KEY.search(str(error)):
            raise MusicFailed(f"music provider refused the request (HTTP 401/403: blocked or not authorised; this tool uses no API key): {_one_line(error)}")
        transient = isinstance(error, str) and bool(_TRANSIENT.search(error)) or error is None
        if not transient:
            raise MusicFailed(f"music fetch failed: {_one_line(error)}")
        elapsed = _monotonic() - started
        if elapsed + delay > MUSIC_RETRY_BUDGET_SECONDS:
            raise MusicFailed(f"music fetch still failing after {attempt} attempts / {elapsed:.0f} s "
                              f"(budget {MUSIC_RETRY_BUDGET_SECONDS} s): {_one_line(error)}")
        print(f"music attempt {attempt} failed ({_one_line(error)}); retrying in {delay:.0f} s")
        _sleep(delay)
        delay = min(delay * 2, MUSIC_BACKOFF_MAX)

    try:
        if not part.is_file() or part.stat().st_size == 0:
            raise MusicFailed("music download is empty (zero bytes)")
        has_audio, duration = probe_audio(part)
        if not has_audio:
            raise MusicFailed("music download is not audio (ffprobe found no audio stream)")
        if duration < MUSIC_MIN_SECONDS:
            raise MusicFailed(f"music track is too short ({duration:.1f} s < {MUSIC_MIN_SECONDS} s)")
        sha = hashlib.sha256(part.read_bytes()).hexdigest()
        sidecar = {"schema": MUSIC_SCHEMA, "provider": "pixabay_music",
                   "track_id": _first(data, "track_id", "pixabay_id", "id"),
                   "track_title": _first(data, "track_title", "title"),
                   "url": _first(data, "url", "track_url", "page_url"),
                   "query": query, "sha256": sha,
                   "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
        side_part.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(part, out)
        try:
            os.replace(side_part, side)
        except OSError:
            out.unlink(missing_ok=True)   # never leave an mp3 without its sidecar
            raise
        return sidecar
    except MusicFailed:
        cleanup()
        raise
    except OSError as e:
        cleanup()
        raise MusicFailed(f"could not write the music files: {_one_line(e)}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="V4: fetch the music bed: the approved music library, or Pixabay when that library is empty (stock footage fetching is disabled).")
    ap.add_argument("queries", nargs="?", help="(disabled in V4)")
    ap.add_argument("out_dir", nargs="?", help="(disabled in V4)")
    ap.add_argument("--ledger", default=bl.DEFAULT_LEDGER)
    ap.add_argument("--public-root", default=bl.DEFAULT_PUBLIC_ROOT)
    ap.add_argument("--projects-root", default=bl.DEFAULT_PROJECTS_ROOT)
    ap.add_argument("--env", default=".env")
    ap.add_argument("--per-page", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true", help="(footage mode, disabled in V4)")
    ap.add_argument("--music", nargs=2, metavar=("QUERY", "MUSIC_OUT"),
                    help='fetch a Pixabay music track, e.g. --music "calm tech" projects/<slug>/assets/audio/bed.mp3')
    ap.add_argument("--force", action="store_true", help="overwrite an existing MUSIC_OUT (only after a fully valid new download)")
    ap.add_argument("--plan", help="(footage mode, disabled in V4)")
    ap.add_argument("--context", help="(footage mode, disabled in V4)")
    args = ap.parse_args(argv)
    # Code guard: any footage form is refused, even next to --music. No approval mechanism of this skill covers it.
    if args.queries or args.out_dir or args.plan or args.context or args.dry_run:
        print(FOOTAGE_DISABLED_MESSAGE, file=sys.stderr)
        return 3
    if not args.music:
        ap.error("--music \"<query>\" <out.mp3> is required (the only mode in V4)")
    query, out_path = args.music
    try:
        sidecar = fetch_music(query, out_path, args.force)
    except MusicRefused as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except MusicFailed as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 4
    if sidecar.get("provider") == ml.SIDECAR_PROVIDER:
        print(f"music OK library track {sidecar['library_file']} ({sidecar['track_title'] or 'untitled'}) "
              f"sha256={sidecar['sha256'][:12]} -> {out_path} (+ .source.json)")
        return 0
    print(f"music OK {sidecar['track_title']} sha256={sidecar['sha256'][:12]} -> {out_path} (+ .source.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
