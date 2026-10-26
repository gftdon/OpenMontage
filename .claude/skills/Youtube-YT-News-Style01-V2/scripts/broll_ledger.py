#!/usr/bin/env python3
"""B-roll ledger for the YT-News V2 skill: which footage has been used before.

Run from the repo root (defaults are relative to the cwd):

  python broll_ledger.py seed   [--public-root remotion-composer/public]
                                [--projects-root projects]
                                [--ledger projects/_broll_ledger.json]
  python broll_ledger.py record <mediaDir> --composition <CompId.tsx>
                                [--manifest PATH] [--public-root ...] [--ledger ...]
  python broll_ledger.py show   [--ledger ...]

`check_broll.py` and `fetch_broll.py` run the seed scan themselves at start (under the
ledger lock), so a missing or stale ledger can never turn into a PASS. `seed` stays as a
manual command.

Ledger file (JSON, "schema": 1):

  entries : {"<md5>": {"md5", "kind", "key", "pixabay_id", "episodes", "first_seen"}}
            kind = public (transcoded stock in public/<mediaDir>/broll)
                   yt     (yt_* clip, in public/ or a project's assets/broll)
                   raw    (original Pixabay download, projects/<slug>/assets/broll)
                   reserved (key "reserved:<pixabay_id>": id claimed by a fetch in
                             progress; episodes = [slug]; NOT "used")
            Episode identity: <mediaDir> for public files, <slug> for project files.
  files   : {"<abs path>": {"size", "mtime_ns", "md5"}}   md5 cache (re-runs do not
            re-hash ~2 GB of footage)
  episodes: {"<mediaDir>": {"comp", "slug", "recorded_at"}}   written by `record`

Shared helpers (md5 cache, ledger I/O, seed scan, BEATS parser) are imported by
check_broll.py and fetch_broll.py.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

SCHEMA = 1
DEFAULT_PUBLIC_ROOT = "remotion-composer/public"
DEFAULT_PROJECTS_ROOT = "projects"
DEFAULT_LEDGER = "projects/_broll_ledger.json"
MEDIA_EXTS = (".mp4", ".webm")
FOOTAGE_MEDIA = ("broll", "clip", "typo")  # beats that MUST carry a src
NON_FOOTAGE_MEDIA = ("web", "none")  # beats whose src (if any) renders no footage
MAX_OLD_CAP = 2


# --------------------------------------------------------------------------- md5

def md5_file(path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_yt_key(key: str) -> bool:
    """yt_* = clip cut from the YouTube source; everything else = stock b-roll."""
    return key.startswith("yt_")


def file_md5(ledger: dict, path) -> str:
    """md5 of a file, cached in ledger["files"] by (path, size, mtime_ns)."""
    p = Path(path)
    st = p.stat()
    key = str(p.resolve())
    files = ledger.setdefault("files", {})
    c = files.get(key)
    if (isinstance(c, dict) and c.get("size") == st.st_size
            and c.get("mtime_ns") == st.st_mtime_ns and c.get("md5")):
        return c["md5"]
    m = md5_file(p)
    files[key] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "md5": m}
    return m


# ------------------------------------------------------------------- ledger I/O

def empty_ledger() -> dict:
    return {"schema": SCHEMA, "entries": {}, "files": {}, "episodes": {}}


def load_ledger(path) -> dict:
    """Missing file = empty ledger. Corrupt file raises ValueError."""
    p = Path(path)
    if not p.exists():
        return empty_ledger()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"ledger {p} is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"ledger {p} has an unexpected structure")
    data.setdefault("schema", SCHEMA)
    for k in ("entries", "files", "episodes"):
        if not isinstance(data.get(k), dict):
            data[k] = {}
    return data


def save_ledger(path, ledger: dict) -> None:
    """Atomic write: temp file in the same dir + os.replace (caller holds the lock)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(ledger, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
        os.replace(tmp, p)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def locked_ledger(path):
    """Read-modify-write under flock on <ledger>.lock; saves on clean exit."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lock_path = p.with_name(p.name + ".lock")
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            ledger = load_ledger(p)
            yield ledger
            save_ledger(p, ledger)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _entry_md5(key: str, e: dict) -> str:
    return e.get("md5") or key.split("#")[0]


def iter_entries(ledger: dict):
    """(key, entry) for every well-formed entry (hand-edited junk is skipped)."""
    for k, e in list(ledger.get("entries", {}).items()):
        if isinstance(e, dict):
            yield k, e


def find_entry(ledger: dict, md5: str, kind: str):
    """Entry for (md5, kind) or None."""
    for k in (md5, f"{md5}#{kind}"):
        e = ledger["entries"].get(k)
        if isinstance(e, dict) and e.get("kind") == kind:
            return e
    return None


def add_entry(ledger: dict, md5: str, kind: str, key: str, episode: str,
              pixabay_id=None) -> tuple[dict, bool]:
    """Add or merge an entry. Returns (entry, created)."""
    entries = ledger["entries"]
    e = find_entry(ledger, md5, kind)
    created = e is None
    if created:
        slot = md5 if md5 not in entries else f"{md5}#{kind}"
        e = {"md5": md5, "kind": kind, "key": key, "pixabay_id": None,
             "episodes": [], "first_seen": _now()}
        entries[slot] = e
    eps = e.get("episodes")
    e["episodes"] = sorted(set(eps if isinstance(eps, list) else []) | ({episode} if episode else set()))
    if pixabay_id not in (None, "") and not e.get("pixabay_id"):
        e["pixabay_id"] = str(pixabay_id)
    return e, created


def episodes_by_md5(ledger: dict, kinds=None) -> dict[str, set[str]]:
    """md5 -> every episode that used a file with this content (any kind except reserved)."""
    out: dict[str, set[str]] = {}
    for k, e in iter_entries(ledger):
        kind = e.get("kind")
        if kind == "reserved" or (kinds and kind not in kinds):
            continue
        eps = e.get("episodes")
        out.setdefault(_entry_md5(k, e), set()).update(eps if isinstance(eps, list) else [])
    return out


def other_episodes(index: dict[str, set[str]], md5: str, own) -> set[str]:
    """Episodes in `index` that used `md5` and are not one of `own` (mediaDir / slug)."""
    return index.get(md5, set()) - {o for o in own if o}


def known_md5s(ledger: dict, kinds=("raw", "yt")) -> set[str]:
    return {_entry_md5(k, e) for k, e in iter_entries(ledger) if e.get("kind") in kinds}


def known_raw_md5s(ledger: dict) -> set[str]:
    return known_md5s(ledger, ("raw",))


def public_episodes_by_md5(ledger: dict) -> dict[str, set[str]]:
    return episodes_by_md5(ledger, ("public",))


# ----------------------------------------------------- pixabay ids / reservations

def _reserved_key(pid) -> str:
    return f"reserved:{pid}"


def used_pixabay_ids(ledger: dict) -> set[str]:
    """Ids of clips that were actually used (recorded). Reservations are NOT used."""
    return {str(e["pixabay_id"]) for _, e in iter_entries(ledger)
            if e.get("pixabay_id") and e.get("kind") != "reserved"}


def blocked_pixabay_ids(ledger: dict, slug: str) -> set[str]:
    """Ids a fetch for `slug` must not pick: used ones + ids reserved by OTHER slugs."""
    out = set(used_pixabay_ids(ledger))
    for _, e in iter_entries(ledger):
        if e.get("kind") == "reserved" and e.get("pixabay_id"):
            eps = e.get("episodes") if isinstance(e.get("episodes"), list) else []
            if slug not in eps:
                out.add(str(e["pixabay_id"]))
    return out


def reserve_pixabay_id(ledger: dict, pid, slug: str, key: str = "") -> bool:
    """Claim `pid` for `slug` (caller holds the lock). False if used / held by another slug."""
    pid = str(pid)
    if pid in used_pixabay_ids(ledger):
        return False
    e = ledger["entries"].get(_reserved_key(pid))
    if isinstance(e, dict):
        eps = e.get("episodes") if isinstance(e.get("episodes"), list) else []
        if slug not in eps:
            return False
        return True
    ledger["entries"][_reserved_key(pid)] = {
        "kind": "reserved", "pixabay_id": pid, "key": key, "episodes": [slug], "first_seen": _now()}
    return True


def release_pixabay_id(ledger: dict, pid, slug: str) -> None:
    e = ledger["entries"].get(_reserved_key(pid))
    if isinstance(e, dict) and e.get("episodes") == [slug]:
        del ledger["entries"][_reserved_key(pid)]


def slug_from_raw_dir(raw_dir) -> str:
    """projects/<slug>/assets/broll -> <slug>; any other folder -> its own name."""
    p = Path(raw_dir).resolve()
    if p.name == "broll" and p.parent.name == "assets":
        return p.parent.parent.name
    return p.name


# ------------------------------------------------------------------- seed scan

def _media_files(pattern_root: Path, pattern: str):
    for f in sorted(pattern_root.glob(pattern)):
        if f.is_file() and f.suffix.lower() in MEDIA_EXTS and not f.name.startswith("."):
            yield f


def seed_scan(ledger: dict, public_root, projects_root) -> dict:
    """Scan public/*/broll and projects/*/assets/broll into the ledger (idempotent).

    Every *.mp4 / *.webm is recorded: kind yt for yt_* names, public / raw otherwise.
    Fetch manifests found next to raw files re-create id reservations.
    """
    public_root, projects_root = Path(public_root), Path(projects_root)
    stats = {k: [0, 0] for k in ("public", "yt", "raw")}  # kind -> [scanned, new]
    before = {k: set(e.get("episodes") if isinstance(e.get("episodes"), list) else [])
              for k, e in iter_entries(ledger)}

    def scan(files, episode_of, stock_kind):
        for f in files:
            kind = "yt" if is_yt_key(f.stem) else stock_kind
            stats[kind][0] += 1
            _, created = add_entry(ledger, file_md5(ledger, f), kind, f.stem, episode_of(f))
            stats[kind][1] += created

    scan(_media_files(public_root, "*/broll/*"), lambda f: f.parent.parent.name, "public")
    scan(_media_files(projects_root, "*/assets/broll/*"), lambda f: f.parent.parent.parent.name, "raw")
    for mf in sorted(projects_root.glob("*/assets/broll/_manifest.json")):
        slug = mf.parent.parent.parent.name
        with contextlib.suppress(Exception):
            for key, m in json.loads(mf.read_text(encoding="utf-8")).items():
                if isinstance(m, dict) and m.get("pixabay_id"):
                    reserve_pixabay_id(ledger, m["pixabay_id"], slug, key)
    links = sum(len({x for x in (e.get("episodes") or [])} - before.get(k, set()))
                for k, e in iter_entries(ledger))
    stats["links"] = links
    return stats


def auto_seed(ledger_path, public_root, projects_root, quiet=False) -> dict:
    """Seed under the ledger lock and persist (used by check_broll / fetch_broll)."""
    with locked_ledger(ledger_path) as ledger:
        stats = seed_scan(ledger, public_root, projects_root)
        total = len(ledger["entries"])
    if not quiet:
        print(f"ledger: scanned {sum(stats[k][0] for k in ('public', 'yt', 'raw'))} files "
              f"({sum(stats[k][1] for k in ('public', 'yt', 'raw'))} new entries, {total} total) "
              f"-> {ledger_path}")
    return stats


# --------------------------------------------------------------- BEATS tokenizer

class BeatsParseError(Exception):
    pass


class Raw(str):
    """A non-string-literal JS token (number, identifier, expression)."""


_IDENT = re.compile(r"[A-Za-z_$][\w$]*|\d+(?:\.\d+)?")
_BEATS_DECL = re.compile(r"(?:const|let|var)\s+(BEATS)\b[^=;]*=\s*\[")
_BEATS_MUTATION = re.compile(
    r"BEATS\s*(?:\.(?:push|unshift|splice|pop|shift|concat|fill|copyWithin|sort|reverse)\b"
    r"|\[[^\]]*\]\s*=(?!=)|=(?!=))")
_ASSET_DIR = re.compile(r"\bassetDir\s*:\s*(?=[\"'`])")
_CONTINUATION = ".([?+-*/%&|,=<>:"


class _Scanner:
    def __init__(self, text: str):
        self.s = text
        self.n = len(text)

    def err(self, i: int, msg: str):
        line = self.s.count("\n", 0, i) + 1
        raise BeatsParseError(f"{msg} (line {line})")

    def skip_ws(self, i: int) -> int:
        s, n = self.s, self.n
        while i < n:
            c = s[i]
            if c.isspace():
                i += 1
            elif s.startswith("//", i):
                j = s.find("\n", i)
                i = n if j < 0 else j + 1
            elif s.startswith("/*", i):
                j = s.find("*/", i + 2)
                if j < 0:
                    self.err(i, "unterminated /* comment")
                i = j + 2
            else:
                break
        return i

    def parse_string(self, i: int):
        """s[i] is a quote. Returns (value, end). Template literals with ${} -> Raw."""
        s, n = self.s, self.n
        q = s[i]
        out = []
        dynamic = False
        j = i + 1
        while j < n:
            c = s[j]
            if c == "\\":
                if j + 1 >= n:
                    break
                e = s[j + 1]
                if e == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", s[j + 2:j + 6]):
                    out.append(chr(int(s[j + 2:j + 6], 16)))
                    j += 6
                    continue
                if e == "x" and re.fullmatch(r"[0-9a-fA-F]{2}", s[j + 2:j + 4]):
                    out.append(chr(int(s[j + 2:j + 4], 16)))
                    j += 4
                    continue
                out.append({"n": "\n", "t": "\t", "r": "\r", "0": "\0"}.get(e, "" if e == "\n" else e))
                j += 2
                continue
            if c == q:
                text = "".join(out)
                return (Raw(text) if dynamic else text), j + 1
            if q == "`" and c == "$" and s.startswith("${", j):
                dynamic = True
                k, _ = self.skip_expr(j + 2, "}")
                if k >= n or s[k] != "}":
                    self.err(j, "unterminated ${ in template literal")
                j = k + 1
                continue
            if c == "\n" and q != "`":
                self.err(i, "unterminated string literal")
            out.append(c)
            j += 1
        self.err(i, "unterminated string literal")

    def skip_expr(self, i: int, stops: str):
        """Scan an expression to a depth-0 stop char. Returns (end, text-without-comments)."""
        s, n = self.s, self.n
        depth = 0
        parts: list[str] = []
        start = i
        while i < n:
            c = s[i]
            if c in "\"'`":
                _, j = self.parse_string(i)
                i = j
                continue
            if s.startswith("//", i) or s.startswith("/*", i):
                parts.append(s[start:i])
                i = self.skip_ws(i)
                start = i
                continue
            if depth == 0 and c in stops:
                parts.append(s[start:i])
                return i, "".join(parts).strip()
            if c in "([{":
                depth += 1
            elif c in ")]}":
                depth -= 1
                if depth < 0:
                    self.err(i, f"unbalanced '{c}'")
            i += 1
        self.err(start, "unexpected end of input")

    def parse_value(self, i: int):
        s = self.s
        i = self.skip_ws(i)
        if i >= self.n:
            self.err(i, "unexpected end of input")
        c = s[i]
        if c == "{":
            return self.parse_object(i)
        if c == "[":
            return self.parse_array(i)
        if c in "\"'`":
            val, j = self.parse_string(i)
            k = self.skip_ws(j)
            if k < self.n and s[k] in ",}]":
                return val, j
            # a string inside a larger expression ("a" + b, cond ? "x" : "y")
        j, text = self.skip_expr(i, ",}]")
        return Raw(text), j

    def parse_array(self, i: int):
        s = self.s
        out = []
        i += 1
        while True:
            i = self.skip_ws(i)
            if i >= self.n:
                self.err(i, "unterminated array")
            if s[i] == "]":
                return out, i + 1
            if s[i] == ",":  # hole
                i += 1
                continue
            val, i = self.parse_value(i)
            out.append(val)
            i = self.skip_ws(i)
            if i < self.n and s[i] == ",":
                i += 1
            elif i < self.n and s[i] == "]":
                continue
            else:
                self.err(i, "expected ',' or ']' in array")

    def parse_object(self, i: int):
        s = self.s
        out: dict = {}
        spreads = 0
        i += 1
        while True:
            i = self.skip_ws(i)
            if i >= self.n:
                self.err(i, "unterminated object")
            c = s[i]
            if c == "}":
                return out, i + 1
            if c == ",":
                i += 1
                continue
            if s.startswith("...", i):  # spread: recorded under a marker key
                val, i = self.parse_value(i)
                out[f"...{spreads}"] = val
                spreads += 1
                continue
            if c in "\"'":
                key, i = self.parse_string(i)
            elif c == "[":
                self.err(i, "computed object keys are not supported")
            else:
                m = _IDENT.match(s, i)
                if not m:
                    self.err(i, f"unexpected character {c!r} in object")
                key, i = m.group(0), m.end()
            i = self.skip_ws(i)
            if i < self.n and s[i] == ":":
                val, i = self.parse_value(i + 1)
                out[str(key)] = val
            elif i < self.n and s[i] in ",}":
                out[str(key)] = Raw(str(key))  # shorthand property
            else:
                self.err(i, "method shorthand / unexpected token in object")
            i = self.skip_ws(i)
            if i < self.n and s[i] == ",":
                i += 1
            elif i < self.n and s[i] == "}":
                continue
            else:
                self.err(i, "expected ',' or '}' in object")

    def find_code(self, rx):
        """Regex matches that start in real code (not inside comments / strings)."""
        s, n = self.s, self.n
        out = []
        i = 0
        while i < n:
            c = s[i]
            if s.startswith("//", i) or s.startswith("/*", i):
                try:
                    i = max(self.skip_ws(i), i + 1)
                except BeatsParseError:
                    break
            elif c in "\"'`":
                try:
                    i = self.parse_string(i)[1]
                except BeatsParseError:
                    i += 1  # stray apostrophe in JSX text etc.
            else:
                if i == 0 or not (s[i - 1].isalnum() or s[i - 1] in "_$"):
                    m = rx.match(s, i)
                    if m:
                        out.append(m)
                        i = max(m.end(), i + 1)
                        continue
                i += 1
        return out


def parse_beats(text: str) -> list[dict]:
    """Parse ``const BEATS: Beat[] = [ ... ];`` into a list of top-level-key dicts.

    Fail-closed (BeatsParseError) on anything that could hide footage from the gate:
    zero or several BEATS declarations (commented-out code does not count), spread /
    non-object array elements, spread inside a beat, anything but `;` / end of statement
    after the closing `]`, and mutation of BEATS elsewhere in the file.

    String values are ``str``; numbers / identifiers / expressions are ``Raw`` (a str
    subclass); nested objects / arrays are dict / list (nested `src` never leaks).
    """
    sc = _Scanner(text)
    decls = sc.find_code(_BEATS_DECL)
    if not decls:
        raise BeatsParseError("no `const BEATS ... = [` declaration found")
    if len(decls) > 1:
        raise BeatsParseError(f"{len(decls)} BEATS declarations found; exactly one is allowed")
    m = decls[0]
    arr, end = sc.parse_array(m.end() - 1)

    k = sc.skip_ws(end)
    if k < len(text) and text[k] != ";":
        newline = "\n" in text[end:k]
        if not newline or text[k] in _CONTINUATION:
            sc.err(k, "BEATS array is followed by more code on the same statement "
                      "(.map / .concat / `as` ...); end it with `];` and keep it a plain literal")
    for mm in sc.find_code(_BEATS_MUTATION):
        if mm.start() != m.start(1):
            sc.err(mm.start(), "BEATS is modified after its declaration; keep it a plain literal")

    beats = []
    for idx, el in enumerate(arr):
        if not isinstance(el, dict):
            raise BeatsParseError(f"BEATS element #{idx} is not an object literal "
                                  f"({str(el)[:40]!r}); spreads / expressions are not allowed")
        spreads = [key for key in el if key.startswith("...")]
        if spreads:
            raise BeatsParseError(f"BEATS element #{idx} (t={el.get('t')}) contains a spread; "
                                  "write every field out explicitly")
        beats.append(el)
    return beats


def find_asset_dirs(text: str) -> list[str]:
    """Every `assetDir: "<x>"` literal in real code."""
    sc = _Scanner(text)
    out = []
    for m in sc.find_code(_ASSET_DIR):
        with contextlib.suppress(BeatsParseError):
            val, _ = sc.parse_string(m.end())
            if not isinstance(val, Raw):
                out.append(str(val))
    return out


def beat_t(beat: dict):
    v = beat.get("t")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def footage_beats(beats: list[dict]) -> list[dict]:
    """Beats that render a footage file: [{"t", "media", "src"|None}, ...].

    A beat is footage when it has a `src` and its media is not web / none (so explain /
    chart / img ... count), or when its media is broll / clip / typo (then a missing
    `src` is reported: the component would silently fall back to a default file).
    """
    out = []
    for b in beats:
        media = b.get("media")
        if media is not None and (isinstance(media, Raw) or not isinstance(media, str)):
            raise BeatsParseError(f"beat t={beat_t(b)} has a non-literal media ({str(media)[:40]!r})")
        src = b.get("src")
        if src is not None and (isinstance(src, Raw) or not isinstance(src, str)):
            raise BeatsParseError(f"beat t={beat_t(b)} has a non-literal src ({str(src)[:40]!r}); "
                                  "use a plain string")
        if media in NON_FOOTAGE_MEDIA:
            continue
        if src is None:
            if media in FOOTAGE_MEDIA:
                out.append({"t": beat_t(b), "media": media, "src": None})
            continue
        out.append({"t": beat_t(b), "media": media, "src": src})
    return out


def read_composition_text(path) -> str:
    p = Path(path)
    if not p.exists():
        alt = Path("remotion-composer/src") / p.name
        if alt.exists():
            p = alt
        else:
            raise FileNotFoundError(f"composition not found: {path}")
    return p.read_text(encoding="utf-8")


def read_composition(path) -> list[dict]:
    return parse_beats(read_composition_text(path))


# -------------------------------------------------------------------- commands

def _print_seed_stats(stats, total, ledger_path):
    for k in ("public", "yt", "raw"):
        print(f"seed: {k:<6} files scanned={stats[k][0]} new entries={stats[k][1]}")
    print(f"seed: episode links added={stats['links']}; ledger now has {total} entries -> {ledger_path}")


def cmd_seed(args) -> int:
    with locked_ledger(args.ledger) as ledger:
        stats = seed_scan(ledger, args.public_root, args.projects_root)
        total = len(ledger["entries"])
    _print_seed_stats(stats, total, args.ledger)
    return 0


def cmd_record(args) -> int:
    try:
        text = read_composition_text(args.composition)
        used = footage_beats(parse_beats(text))
    except (FileNotFoundError, BeatsParseError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    manifest = {}
    slug = None
    if args.manifest:
        try:
            manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"ERROR: cannot read manifest {args.manifest}: {e}", file=sys.stderr)
            return 2
        slug = slug_from_raw_dir(Path(args.manifest).resolve().parent)
    media_dir = args.mediaDir
    comp_name = Path(args.composition).name
    keys = sorted({u["src"] for u in used if u["src"] and not is_yt_key(u["src"])})
    broll_dir = Path(args.public_root) / media_dir / "broll"
    recorded = 0
    rc = 0
    with locked_ledger(args.ledger) as ledger:
        mk = ledger["episodes"].get(media_dir)
        if isinstance(mk, dict) and mk.get("comp") and mk["comp"] != comp_name:
            print(f"ERROR: mediaDir {media_dir} was already recorded for composition {mk['comp']}; "
                  "use a new mediaDir for a new video", file=sys.stderr)
            return 1
        for key in keys:
            f = broll_dir / f"{key}.mp4"
            if not f.exists():
                print(f"WARN  {key}: {f} missing — not recorded")
                continue
            m = manifest.get(key) if isinstance(manifest.get(key), dict) else None
            pid = m.get("pixabay_id") if m else None
            md5 = file_md5(ledger, f)
            _, created = add_entry(ledger, md5, "public", key, media_dir, pid)
            msg = f"public {md5[:12]} {key} ({'new' if created else 'merged'})"
            if m:
                raw_md5 = m.get("raw_md5")
                if not raw_md5 and args.manifest:
                    raw = Path(args.manifest).parent / f"{key}.mp4"
                    raw_md5 = file_md5(ledger, raw) if raw.exists() else None
                if raw_md5:
                    add_entry(ledger, raw_md5, "raw", key, slug or media_dir, pid)
                    msg += f" + raw {raw_md5[:12]}"
                if pid:
                    msg += f" pixabay_id={pid}"
                    ledger["entries"].pop(_reserved_key(pid), None)  # reserved -> used
            print(f"RECORD {msg} episode={media_dir}")
            recorded += 1
        ledger["episodes"][media_dir] = {"comp": comp_name, "slug": slug, "recorded_at": _now()}
    print(f"record: {recorded}/{len(keys)} stock files recorded for episode {media_dir} "
          f"(composition {comp_name})")
    return rc


def cmd_show(args) -> int:
    try:
        ledger = load_ledger(args.ledger)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    kinds: dict[str, int] = {}
    per_ep: dict[str, dict[str, int]] = {}
    for _, e in iter_entries(ledger):
        kind = e.get("kind", "?")
        kinds[kind] = kinds.get(kind, 0) + 1
        for ep in (e.get("episodes") if isinstance(e.get("episodes"), list) else []):
            per_ep.setdefault(ep, {}).setdefault(kind, 0)
            per_ep[ep][kind] += 1
    print(f"ledger {args.ledger}: {len(ledger['entries'])} entries "
          f"({', '.join(f'{k}={v}' for k, v in sorted(kinds.items())) or 'empty'}), "
          f"{len(used_pixabay_ids(ledger))} used pixabay ids, "
          f"{len(ledger['episodes'])} recorded episodes")
    for ep in sorted(per_ep):
        c = per_ep[ep]
        print(f"  {ep:<32} " + " ".join(f"{k}={v}" for k, v in sorted(c.items())))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="B-roll ledger (seed / record / show).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, public=True):
        if public:
            p.add_argument("--public-root", default=DEFAULT_PUBLIC_ROOT)
        p.add_argument("--ledger", default=DEFAULT_LEDGER)

    p = sub.add_parser("seed", help="scan public + project broll folders into the ledger (idempotent)")
    common(p)
    p.add_argument("--projects-root", default=DEFAULT_PROJECTS_ROOT)
    p.set_defaults(fn=cmd_seed)

    p = sub.add_parser("record", help="record the stock files an episode actually uses")
    p.add_argument("mediaDir")
    p.add_argument("--composition", required=True, help="CompId.tsx (path, or name under remotion-composer/src)")
    p.add_argument("--manifest", help="projects/<slug>/assets/broll/_manifest.json from fetch_broll.py")
    common(p)
    p.set_defaults(fn=cmd_record)

    p = sub.add_parser("show", help="print totals and per-episode counts")
    common(p, public=False)
    p.set_defaults(fn=cmd_show)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
