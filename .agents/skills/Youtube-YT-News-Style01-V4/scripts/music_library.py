#!/usr/bin/env python3
"""Owner-approved local music library for the V4 music bed (stdlib only).

The list of approved tracks is `music_library.json` next to this file, so it is part of the skill and covered by
the gate lock. The mp3 files themselves live in the library directory (default `<repo root>/music_library`,
override with the absolute path in env MUSIC_LIBRARY_DIR); a file only counts when its sha256 equals the
manifest entry. `fetch_broll.py --music` falls back to this library when Pixabay fails.

  python music_library.py check [--repo-root R]
      one line per track `<status> <file> <sha256[:12]>` + a summary; exit 0 when at least one track is ok, else 4.

Manifest: {"schema": "yt-news-v4-music-library", "version": 1, "tracks": [track, ...]}; a track has exactly
sha256, file, title, license, origin, approved_by, approved_on, duration_sec.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MANIFEST_SCHEMA = "yt-news-v4-music-library"
MANIFEST_VERSION = 1
SIDECAR_PROVIDER = "music_library"

_SHA = re.compile(r"[0-9a-f]{64}")
_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.mp3")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TRACK_KEYS = {"sha256", "file", "title", "license", "origin", "approved_by", "approved_on", "duration_sec"}
_TOP_KEYS = {"schema", "version", "tracks"}


class MusicLibraryError(Exception):
    pass


def manifest_path() -> Path:
    return Path(__file__).resolve().parent / "music_library.json"


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _text(track, key, where):
    v = track.get(key)
    if not isinstance(v, str) or not v.strip():
        raise MusicLibraryError(f"{where}: '{key}' must be a non-empty string")
    return v


def _validate(data, source) -> dict:
    if not isinstance(data, dict):
        raise MusicLibraryError(f"{source}: manifest must be a JSON object")
    if set(data) != _TOP_KEYS:
        raise MusicLibraryError(f"{source}: manifest keys must be exactly {sorted(_TOP_KEYS)} (got {sorted(data)})")
    if data["schema"] != MANIFEST_SCHEMA:
        raise MusicLibraryError(f"{source}: schema must be '{MANIFEST_SCHEMA}' (got {data['schema']!r})")
    if type(data["version"]) is not int or data["version"] != MANIFEST_VERSION:
        raise MusicLibraryError(f"{source}: version must be {MANIFEST_VERSION} (got {data['version']!r})")
    tracks = data["tracks"]
    if not isinstance(tracks, list):
        raise MusicLibraryError(f"{source}: 'tracks' must be a list")
    seen_sha, seen_file = set(), set()
    for i, t in enumerate(tracks):
        where = f"{source}: tracks[{i}]"
        if not isinstance(t, dict):
            raise MusicLibraryError(f"{where} must be an object")
        if set(t) != _TRACK_KEYS:
            missing, extra = sorted(_TRACK_KEYS - set(t)), sorted(set(t) - _TRACK_KEYS)
            raise MusicLibraryError(f"{where}: keys must be exactly {sorted(_TRACK_KEYS)} (missing {missing}, extra {extra})")
        sha = t["sha256"]
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise MusicLibraryError(f"{where}: 'sha256' must be 64 lowercase hex characters")
        if sha in seen_sha:
            raise MusicLibraryError(f"{where}: duplicate sha256 {sha[:12]}")
        seen_sha.add(sha)
        f = t["file"]
        if not isinstance(f, str) or not _FILE.fullmatch(f):
            raise MusicLibraryError(f"{where}: 'file' must be a plain .mp3 file name (no path)")
        if f in seen_file:
            raise MusicLibraryError(f"{where}: duplicate file {f}")
        seen_file.add(f)
        if t["title"] is not None and not isinstance(t["title"], str):
            raise MusicLibraryError(f"{where}: 'title' must be a string or null")
        for key in ("license", "origin", "approved_by"):
            _text(t, key, where)
        d = t["approved_on"]
        try:
            if not isinstance(d, str) or not _DATE.fullmatch(d):
                raise ValueError(d)
            datetime.date.fromisoformat(d)
        except ValueError:
            raise MusicLibraryError(f"{where}: 'approved_on' must be a real date YYYY-MM-DD (got {d!r})")
        dur = t["duration_sec"]
        if dur is not None and (isinstance(dur, bool) or not isinstance(dur, (int, float)) or not dur > 0):
            raise MusicLibraryError(f"{where}: 'duration_sec' must be a number > 0 or null")
    return data


def load_manifest_with_sha(path=None) -> tuple[dict, str]:
    """(validated manifest, sha256 of the manifest bytes that were parsed)."""
    p = Path(path) if path is not None else manifest_path()
    try:
        raw = p.read_bytes()
    except OSError as e:
        raise MusicLibraryError(f"music library manifest unreadable: {p} ({e.strerror or e})")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise MusicLibraryError(f"music library manifest is not valid JSON: {p} ({e})")
    return _validate(data, p.name), hashlib.sha256(raw).hexdigest()


def load_manifest(path=None) -> dict:
    return load_manifest_with_sha(path)[0]


def library_dir(repo_root) -> Path:
    env = os.environ.get("MUSIC_LIBRARY_DIR", "")
    if env.strip():
        p = Path(env)
        if not p.is_absolute():
            raise MusicLibraryError(f"MUSIC_LIBRARY_DIR must be an absolute path (got {env!r})")
        return p
    return Path(repo_root) / "music_library"


def find_track(manifest, sha256):
    for t in manifest.get("tracks", []):
        if t["sha256"] == sha256:
            return t
    return None


def check_library(repo_root, manifest=None) -> list:
    manifest = manifest if manifest is not None else load_manifest()
    lib = library_dir(repo_root)
    rows = []
    for t in manifest["tracks"]:
        p = lib / t["file"]
        try:
            if p.is_symlink() or not p.is_file():
                status = "missing"
            else:
                status = "ok" if sha256_file(p) == t["sha256"] else "sha-mismatch"
        except OSError:
            status = "missing"
        rows.append({"sha256": t["sha256"], "file": t["file"], "path": str(p), "status": status})
    return rows


def pick_track(repo_root, manifest=None):
    manifest = manifest if manifest is not None else load_manifest()
    lib = library_dir(repo_root)
    if not manifest["tracks"]:
        raise MusicLibraryError(f"music library is empty (no approved tracks; library dir {lib})")
    rows = check_library(repo_root, manifest)
    for row in rows:
        if row["status"] == "ok":
            return find_track(manifest, row["sha256"]), Path(row["path"])
    detail = "; ".join(f"{r['file']}: {r['status']}" for r in rows)
    raise MusicLibraryError(f"no approved track is usable in {lib} ({detail})")


def _default_repo_root() -> Path:
    here = Path(__file__).resolve().parent
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=here, capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.cwd()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check the approved V4 music library.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="list every approved track and whether its file is present and intact")
    c.add_argument("--repo-root", default=None)
    args = ap.parse_args(argv)
    root = Path(args.repo_root) if args.repo_root else _default_repo_root()
    try:
        manifest = load_manifest()
        rows = check_library(root, manifest)
        lib = library_dir(root)
    except MusicLibraryError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 4
    for r in rows:
        print(f"{r['status']} {r['file']} {r['sha256'][:12]}")
    ok = sum(r["status"] == "ok" for r in rows)
    print(f"{ok}/{len(rows)} approved track(s) usable in {lib}")
    return 0 if ok else 4


if __name__ == "__main__":
    sys.exit(main())
