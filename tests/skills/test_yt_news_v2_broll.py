"""Tests for the YT-News V2 b-roll uniqueness tooling (ledger / check / fetch / transcode).

No network, no real media: footage files are tiny byte strings; Pixabay search +
download are monkeypatched.
"""
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = PROJECT_ROOT / ".claude" / "skills" / "Youtube-YT-News-Style01-V2" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import broll_ledger as bl  # noqa: E402
import check_broll as cb  # noqa: E402
import fetch_broll as fb  # noqa: E402


# ----------------------------------------------------------------- helpers

def comp(*beats: str, asset_dir=None) -> str:
    head = f'const EPISODE = {{ assetDir: "{asset_dir}" }};\n' if asset_dir else "const R = 1;\n"
    return head + "const BEATS: Beat[] = [\n" + ",\n".join(beats) + "\n];\nexport const X = 1;\n"


def beat(t, media="broll", src=None, extra=""):
    s = f'{{ t: {t}, mode: "pip", media: "{media}",'
    if src is not None:
        s += f' src: "{src}",'
    return s + f" {extra} }}"


def md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def make_public(root: Path, media_dir: str, files: dict):
    d = root / media_dir / "broll"
    d.mkdir(parents=True, exist_ok=True)
    for k, content in files.items():
        (d / f"{k}.mp4").write_bytes(content)


def make_raw(projects: Path, slug: str, files: dict) -> Path:
    d = projects / slug / "assets" / "broll"
    d.mkdir(parents=True, exist_ok=True)
    for k, content in files.items():
        (d / f"{k}.mp4").write_bytes(content)
    return d


@pytest.fixture
def env(tmp_path):
    e = {"tmp": tmp_path, "public": tmp_path / "public", "projects": tmp_path / "projects",
         "ledger": tmp_path / "projects" / "_broll_ledger.json", "slug": "ep-slug"}
    e["raw"] = e["projects"] / e["slug"] / "assets" / "broll"
    e["manifest"] = e["raw"] / "_manifest.json"
    return e


def build_fresh(env, keys, media_dir="ep", slug=None, yt=()):
    """A properly fetched episode: raw files + manifest + (different bytes) transcoded public files."""
    slug = slug or env["slug"]
    raw = make_raw(env["projects"], slug, {})
    man = {}
    for i, k in enumerate(keys):
        rb, pb = f"RAW-{media_dir}-{k}".encode(), f"PUB-{media_dir}-{k}".encode()
        (raw / f"{k}.mp4").write_bytes(rb)
        make_public(env["public"], media_dir, {k: pb})
        man[k] = {"pixabay_id": str(1000 + i), "raw_md5": md5(rb), "duration": 12}
    for y in yt:
        make_public(env["public"], media_dir, {y: f"YT-{media_dir}-{y}".encode()})
    (raw / "_manifest.json").write_text(json.dumps(man))
    return raw / "_manifest.json"


def build_other(env, media_dir, keys, slug=None):
    """Another, earlier episode: public files + its raw downloads."""
    slug = slug or f"{media_dir}-slug"
    make_public(env["public"], media_dir, {k: f"PUB-{media_dir}-{k}".encode() for k in keys})
    make_raw(env["projects"], slug, {k: f"RAW-{media_dir}-{k}".encode() for k in keys})
    return slug


def run_check(env, text, media_dir="ep", manifest=None, max_old=2, comp_name="Ep.tsx", extra=()):
    """Run check_broll.main like the CLI. Returns exit code."""
    comp_path = env["tmp"] / comp_name
    comp_path.write_text(text, encoding="utf-8")
    manifest = Path(manifest) if manifest else env["manifest"]
    if not manifest.exists():
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("{}")
    return cb.main([str(comp_path), "--media-dir", media_dir, "--manifest", str(manifest),
                    "--public-root", str(env["public"]), "--projects-root", str(env["projects"]),
                    "--ledger", str(env["ledger"]), "--max-old", str(max_old), *extra])


# --------------------------------------------------------------- tokenizer

def test_tokenizer_strings_with_braces_and_slashes():
    text = comp(
        '{ t: 1, mode: "full", media: "broll", src: "city", headline: "a } { // not a comment /* x */",'
        " sub: 'it\\'s {fine}', url: `https://x.y/z?{a}` }",
        '{ t: 2, mode: "full", media: "broll", src: "office" }',
    )
    beats = bl.parse_beats(text)
    assert [b["src"] for b in beats] == ["city", "office"]
    assert beats[0]["headline"] == "a } { // not a comment /* x */"
    assert beats[0]["sub"] == "it's {fine}"


def test_tokenizer_comments_hide_fake_beats():
    text = comp(
        '// { t: 0, media: "broll", src: "ghost" },',
        '/* { t: 1, media: "broll", src: "ghost2" }, */',
        '{ t: 3, mode: "full", media: "broll", /* inline } */ src: "real" // trailing { \n }',
    )
    beats = bl.parse_beats(text)
    assert len(beats) == 1 and beats[0]["src"] == "real"
    assert bl.beat_t(beats[0]) == 3.0


def test_tokenizer_nested_objects_do_not_leak_src():
    text = comp(
        '{ t: 1, mode: "pip", media: "broll", src: "top",'
        ' stats: [{ t: 2, label: "x", src: "nested1" }], lower: { title: "a", sub: "b", src: "nested2" },'
        ' cam: [{ t: 1, fy: 0, z: 1 }] }',
        '{ t: 5, mode: "full", lower: { title: "only lower", src: "nested3" } }',
    )
    beats = bl.parse_beats(text)
    assert beats[0]["src"] == "top"
    assert "src" not in beats[1]
    assert [f["src"] for f in bl.footage_beats(beats)] == ["top"]


def test_tokenizer_thai_text_and_escapes():
    text = comp('{ t: 1, mode: "full", media: "typo", src: "x", headline: "ตัวถูกแทนตัวแพง \\"ได้ไหม\\" {?}", sub: "\\u0e01" }')
    b = bl.parse_beats(text)[0]
    assert b["headline"] == 'ตัวถูกแทนตัวแพง "ได้ไหม" {?}'
    assert b["sub"] == "ก"


def test_tokenizer_expressions_and_trailing_commas():
    text = comp('{ t: 1.5, mode: "full", media: "broll", src: "a", cssH: R("k").h + 3, from: -2, }',
                '{ t: 2, mode: "full", media: "broll", src: cond ? "a" : "b" }')
    beats = bl.parse_beats(text)
    assert beats[0]["src"] == "a"
    with pytest.raises(bl.BeatsParseError):
        bl.footage_beats(beats)  # non-literal src is refused


def test_tokenizer_errors():
    with pytest.raises(bl.BeatsParseError):
        bl.parse_beats("const X = 1;")
    with pytest.raises(bl.BeatsParseError):
        bl.parse_beats('const BEATS: Beat[] = [ { t: 1, src: "unterminated } ];')


def test_footage_beats_definition():
    """src + media not in {web, none} = footage (explain/chart/img count); broll/clip/typo need a src."""
    text = comp(beat(1, "web", "ignored"), beat(2, "none"), beat(3, "broll", "a"), beat(4, "clip", "yt_b"),
                beat(5, "typo", "c"), beat(6, "explain", "d"), beat(7, "chart", "e"), beat(8, "img"),
                '{ t: 9, mode: "pip", src: "no_media" }', '{ t: 10, mode: "full" }', beat(11, "broll"))
    got = bl.footage_beats(bl.parse_beats(text))
    assert [(g["t"], g["src"]) for g in got] == [
        (3.0, "a"), (4.0, "yt_b"), (5.0, "c"), (6.0, "d"), (7.0, "e"), (9.0, "no_media"), (11.0, None)]


# ---------------------------------------------------- fix 5: parser fails closed

@pytest.mark.parametrize("text,needle", [
    ('const BEATS: Beat[] = [...OLD, { t: 1, media: "broll", src: "a" }];', "not an object literal"),  # (d)
    ('const BEATS: Beat[] = [{ t: 1, media: "broll", src: "a" }, "oops"];', "not an object literal"),
    ('const BEATS: Beat[] = [{ t: 1, ...OLD, media: "broll", src: "a" }];', "spread"),
    ('const BEATS: Beat[] = [{ t: 1, media: "broll", src: "a" }].map(fix);', "same statement"),  # (f)
    ('const BEATS: Beat[] = [{ t: 1, media: "broll", src: "a" }].concat(OLD);', "same statement"),
    ('const BEATS: Beat[] = [{ t: 1, media: "broll", src: "a" }] as Beat[];', "same statement"),
    ('const BEATS: Beat[] = [{ t: 1, media: "broll", src: "a" }];\nBEATS.push({ t: 2 });', "modified"),
    ('const BEATS: Beat[] = [{ t: 1, media: "broll", src: "a" }];\nBEATS[0] = OLD;', "modified"),
    ('const BEATS = [{ t: 1 }];\nconst BEATS2 = 1;\nBEATS = [];', "modified"),
    ('const BEATS = [{ t: 1 }];\nconst BEATS = [{ t: 2 }];', "2 BEATS declarations"),
    ('const X = 1;', "no `const BEATS"),
])
def test_parser_fails_closed(text, needle):
    with pytest.raises(bl.BeatsParseError) as e:
        bl.parse_beats(text)
    assert needle in str(e.value)


@pytest.mark.parametrize("beat_src", [
    '{ t: 1, media: kind, src: "a" }',
    '{ t: 1, media: "broll", src: pick }',
    '{ t: 1, media: "broll", src: `x${i}` }',
])
def test_non_literal_media_or_src_fails_closed(beat_src):
    with pytest.raises(bl.BeatsParseError):
        bl.footage_beats(bl.parse_beats(comp(beat_src)))


def test_commented_or_quoted_decls_do_not_count_and_normal_use_is_fine():
    text = ('// const BEATS: Beat[] = [{ t: 0, media: "broll", src: "ghost" }];\n'
            '/* const BEATS = [] */\nconst s = "const BEATS = [";\n'
            'const BEATS: Beat[] = [{ t: 1, media: "broll", src: "real" }]; // done\n'
            'for (let i = 0; i < BEATS.length; i++) { const b = BEATS[i]; BEATS.map((x) => x); }\n'
            'const done = BEATS[0].t === 1;\n')
    beats = bl.parse_beats(text)
    assert [b["src"] for b in beats] == ["real"]


def test_array_followed_by_next_statement_without_semicolon_is_ok():
    beats = bl.parse_beats('const BEATS = [{ t: 1, media: "broll", src: "a" }]\nconst NEXT = 2;\n')
    assert len(beats) == 1


def test_find_asset_dirs_ignores_comments_and_templates():
    text = ('// assetDir: "ghost"\nconst E = { assetDir: "real", /* assetDir: "x" */ };\n'
            'const p = `${E.assetDir}/broll`;\n')
    assert bl.find_asset_dirs(text) == ["real"]
    assert bl.find_asset_dirs("const x = 1;") == []


def test_check_cli_parse_errors_exit_2(env, capsys):
    build_fresh(env, ["a"])
    for text in ('const BEATS = [...OLD];', 'const BEATS = [{t:1}].map(f);', "export const x = 1;",
                 '// const BEATS = []\nexport const x = 1;'):
        assert run_check(env, text) == 2
        assert "ERROR" in capsys.readouterr().err


# ------------------------------------------------- real composition (fixture)

def test_tripo_fixture_reports_exactly_the_repeated_srcs():
    text = (FIXTURES / "tripo_beats.tsx.txt").read_text(encoding="utf-8")
    beats = bl.parse_beats(text)
    assert len(beats) == 34
    v, rows, warnings = cb.check(beats, "tripoGameNews", Path("/nonexistent"), bl.empty_ledger(), 2,
                                 {}, Path("/nonexistent"), "s", asset_dirs=bl.find_asset_dirs(text))
    assert {r["src"] for r in rows if r["uses"] > 1} == {"yt_pipeline", "office", "typing", "abstract", "brain"}
    repeated = [x for x in v if "is used by" in x]
    assert len(repeated) == 5
    assert bl.find_asset_dirs(text) == ["tripoGameNews"]
    assert not any("assetDir" in x for x in v)


# ------------------------------------------------------ check: base behaviour

def test_check_passes_when_everything_is_fresh(env, capsys):
    build_fresh(env, ["a", "b"], yt=["yt_c"])
    text = comp(beat(1, "broll", "a"), beat(2, "typo", "b"), beat(3, "clip", "yt_c"))
    assert run_check(env, text, max_old=0) == 0
    out = capsys.readouterr().out
    assert "PASS" in out and "fresh" in out and "VIOLATION" not in out


def test_check_repeated_src_fails(env, capsys):
    build_fresh(env, ["a"], yt=["yt_c"])
    text = comp(beat(1, "broll", "a"), beat(2, "typo", "a"), beat(3, "clip", "yt_c"), beat(4, "clip", "yt_c"))
    assert run_check(env, text) == 1
    out = capsys.readouterr().out
    assert "`a` is used by 2 beats (t=1.0, 2.0)" in out and "`yt_c` is used by 2 beats (t=3.0, 4.0)" in out


def test_check_missing_src_fails(env, capsys):
    build_fresh(env, ["a"])
    assert run_check(env, comp(beat(1, "broll", "a"), beat(2, "broll"), beat(3, "typo"))) == 1
    assert capsys.readouterr().out.count("no `src`") == 2


def test_check_missing_file_fails(env, capsys):
    build_fresh(env, ["a"])
    assert run_check(env, comp(beat(1, "broll", "a"), beat(2, "broll", "gone"))) == 1
    out = capsys.readouterr().out
    assert "`gone` is missing" in out and "missing" in out


def test_check_renamed_duplicate_fails(env, capsys):
    build_fresh(env, ["a", "b", "c"])
    make_public(env["public"], "ep", {"b": b"PUB-ep-a"})  # b is a renamed copy of a
    assert run_check(env, comp(beat(1, "broll", "a"), beat(2, "broll", "b"), beat(3, "broll", "c"))) == 1
    assert "identical files" in capsys.readouterr().out


# ---------------------------------------- fix 1: auto-seed (missing/stale ledger)

def test_c_no_ledger_file_still_detects_old_footage(env, capsys):
    build_other(env, "ep_old", ["k0", "k1"])
    # this episode just copied the old public files, no fetch, no ledger file at all
    make_public(env["public"], "ep", {"k0": b"PUB-ep_old-k0", "k1": b"PUB-ep_old-k1"})
    assert not env["ledger"].exists()
    assert run_check(env, comp(beat(1, "broll", "k0"), beat(2, "broll", "k1")), max_old=0) == 1
    out = capsys.readouterr().out
    assert "same content as ep_old" in out
    assert env["ledger"].exists()  # created by the auto-seed


def test_stale_ledger_is_refreshed_on_every_run(env):
    build_fresh(env, ["a"])
    assert run_check(env, comp(beat(1, "broll", "a")), max_old=0) == 0
    # an other episode appears afterwards with the very same file
    make_public(env["public"], "late", {"a": b"PUB-ep-a"})
    # (late is "another episode" using ep's file; ep is the one being checked -> a becomes old)
    assert run_check(env, comp(beat(1, "broll", "a")), max_old=0) == 1


def test_seed_scans_webm_and_yt_and_skips_hidden(env):
    make_public(env["public"], "ep1", {"a": b"A", "yt_x": b"Y"})
    d = env["public"] / "ep1" / "broll"
    (d / "w.webm").write_bytes(b"W")
    (d / ".tmp_h.mp4").write_bytes(b"H")
    raw = make_raw(env["projects"], "s1", {"r": b"R"})
    (raw / "yt_z.mp4").write_bytes(b"Z")
    stats = bl.seed_scan(led := bl.empty_ledger(), env["public"], env["projects"])
    kinds = sorted((e["kind"], e["key"]) for e in led["entries"].values())
    assert kinds == [("public", "a"), ("public", "w"), ("raw", "r"), ("yt", "yt_x"), ("yt", "yt_z")]
    assert stats["yt"][0] == 2 and stats["public"][0] == 2 and stats["raw"][0] == 1


def test_seed_cmd_idempotent(env):
    make_public(env["public"], "ep1", {"a": b"A", "yt_x": b"Y"})
    make_public(env["public"], "ep2", {"a": b"A", "b": b"B"})
    make_raw(env["projects"], "slug-1", {"a": b"RAWA"})
    args = ["seed", "--public-root", str(env["public"]), "--projects-root", str(env["projects"]),
            "--ledger", str(env["ledger"])]
    assert bl.main(args) == 0
    data = json.loads(env["ledger"].read_text())
    assert data["schema"] == 1
    assert sorted(e["kind"] for e in data["entries"].values()) == ["public", "public", "raw", "yt"]
    pub_a = bl.find_entry(bl.load_ledger(env["ledger"]), md5(b"A"), "public")
    assert pub_a["episodes"] == ["ep1", "ep2"]
    first = {k: e["first_seen"] for k, e in data["entries"].items()}
    assert bl.main(args) == 0
    again = json.loads(env["ledger"].read_text())
    assert {k: e["first_seen"] for k, e in again["entries"].items()} == first
    assert again["entries"].keys() == data["entries"].keys()


def test_md5_cache_avoids_rehashing(env, monkeypatch):
    build_fresh(env, ["a", "b"])
    calls = []
    real = bl.md5_file
    monkeypatch.setattr(bl, "md5_file", lambda p: (calls.append(str(p)), real(p))[1])
    text = comp(beat(1, "broll", "a"), beat(2, "broll", "b"))
    assert run_check(env, text) == 0
    first = len(calls)
    assert first >= 4  # 2 public + 2 raw
    assert run_check(env, text) == 0
    assert len(calls) == first  # second run: everything served from the (path,size,mtime) cache
    # touching a file invalidates only that file
    p = env["public"] / "ep" / "broll" / "a.mp4"
    p.write_bytes(b"PUB-ep-a-changed")
    assert run_check(env, text) == 0
    assert len(calls) == first + 1


def test_hand_edited_ledger_entries_are_tolerated(env):
    build_fresh(env, ["a"])
    env["ledger"].parent.mkdir(parents=True, exist_ok=True)
    env["ledger"].write_text(json.dumps({"entries": {
        "abc": {"kind": "public"}, "def": "junk", "ghi": {"md5": "x"}, "jkl": {"kind": "raw", "episodes": "oops"},
        "reserved:5": {"kind": "reserved"}}, "files": [], "episodes": None}))
    assert run_check(env, comp(beat(1, "broll", "a")), max_old=0) == 0
    assert bl.main(["show", "--ledger", str(env["ledger"])]) == 0


def test_missing_ledger_is_empty(tmp_path):
    led = bl.load_ledger(tmp_path / "absent.json")
    assert led["entries"] == {} and bl.used_pixabay_ids(led) == set()


def test_corrupt_ledger_raises(tmp_path):
    p = tmp_path / "l.json"
    p.write_text("{nope")
    with pytest.raises(ValueError):
        bl.load_ledger(p)


# ---------------------------------------------- fix 2: content-based old detection

def test_a_old_public_file_copied_as_yt_name_fails(env, capsys):
    build_other(env, "ep_old", ["office"])
    build_fresh(env, [])
    make_public(env["public"], "ep", {"yt_office": b"PUB-ep_old-office"})
    assert run_check(env, comp(beat(1, "clip", "yt_office")), max_old=0) == 1
    out = capsys.readouterr().out
    assert "`yt_office`" in out and "cut from THIS episode's source" in out and "copied" in out
    # a hard violation: it is not absorbed by the old-file allowance
    assert run_check(env, comp(beat(1, "clip", "yt_office")), max_old=2) == 1


def test_b_old_raw_file_copied_straight_into_public_is_old(env, capsys):
    build_other(env, "ep_old", ["k0"])
    build_fresh(env, [])
    make_public(env["public"], "ep", {"k0": b"RAW-ep_old-k0"})  # un-transcoded raw of another project
    assert run_check(env, comp(beat(1, "broll", "k0")), max_old=0) == 1
    assert "same content as ep_old-slug" in capsys.readouterr().out


def test_stock_matching_another_episodes_yt_clip_is_old(env, capsys):
    make_public(env["public"], "other", {"yt_q": b"SHARED"})
    build_fresh(env, ["a"])
    make_public(env["public"], "ep", {"a": b"SHARED"})
    assert run_check(env, comp(beat(1, "broll", "a")), max_old=0) == 1
    assert "same content as other" in capsys.readouterr().out


def test_yt_clip_from_own_source_is_fine_even_with_unique_bytes(env):
    build_fresh(env, [], yt=["yt_a"])
    assert run_check(env, comp(beat(1, "clip", "yt_a")), max_old=0) == 0


def test_old_above_max_fails_within_max_passes(env, capsys):
    build_other(env, "ep_old", ["k0", "k1", "k2"])
    man = build_fresh(env, ["fresh"])
    for k in ("k0", "k1", "k2"):
        make_public(env["public"], "ep", {k: f"PUB-ep_old-{k}".encode()})
    three = comp(*[beat(i, "broll", f"k{i}") for i in range(3)], beat(9, "broll", "fresh"))
    assert run_check(env, three, max_old=2) == 1
    out = capsys.readouterr().out
    assert "3 stock files are old" in out and "ep_old" in out
    two = comp(beat(0, "broll", "k0"), beat(1, "broll", "k1"), beat(9, "broll", "fresh"))
    assert run_check(env, two, max_old=2) == 0
    assert run_check(env, two, max_old=1) == 1
    capsys.readouterr()


def test_own_episode_files_are_not_old_on_rerun(env):
    build_fresh(env, ["a", "b", "c"])
    text = comp(beat(1, "broll", "a"), beat(2, "broll", "b"), beat(3, "broll", "c"))
    assert run_check(env, text, max_old=0) == 0
    assert run_check(env, text, max_old=0) == 0  # ledger now knows ep -> still not old


# --------------------------------------------------- fix 3: manifest + max-old cap

def test_stock_not_in_manifest_is_old(env, capsys):
    build_fresh(env, ["a"])
    make_public(env["public"], "ep", {"extra": b"UNIQUE-but-never-fetched"})
    text = comp(beat(1, "broll", "a"), beat(2, "broll", "extra"))
    assert run_check(env, text, max_old=0) == 1
    out = capsys.readouterr().out
    assert "extra: not in this episode's fetch manifest" in out
    assert run_check(env, text, max_old=1) == 0
    row = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("extra")][0]
    assert row.split()[-1] == "old"


def test_raw_file_changed_after_fetch_is_a_violation(env, capsys):
    build_fresh(env, ["a"])
    (env["raw"] / "a.mp4").write_bytes(b"swapped after fetch")
    assert run_check(env, comp(beat(1, "broll", "a")), max_old=2) == 1
    assert "raw file changed after fetch" in capsys.readouterr().out


def test_manifest_key_without_raw_file_is_a_violation(env, capsys):
    build_fresh(env, ["a"])
    (env["raw"] / "a.mp4").unlink()
    assert run_check(env, comp(beat(1, "broll", "a")), max_old=2) == 1
    assert "raw file is missing" in capsys.readouterr().out


def test_raw_download_used_by_other_episode_is_old(env, capsys):
    build_other(env, "ep_old", ["k"])
    man = build_fresh(env, ["k"])
    # the fetched raw is byte-identical to another episode's raw (same Pixabay video re-downloaded)
    same_raw = b"RAW-ep_old-k"
    (env["raw"] / "k.mp4").write_bytes(same_raw)
    m = json.loads(man.read_text())
    m["k"]["raw_md5"] = md5(same_raw)
    man.write_text(json.dumps(m))
    assert run_check(env, comp(beat(1, "broll", "k")), max_old=0) == 1
    assert "raw download also used by ep_old-slug" in capsys.readouterr().out


def test_max_old_above_cap_is_usage_error(env):
    build_fresh(env, ["a"])
    with pytest.raises(SystemExit) as e:
        run_check(env, comp(beat(1, "broll", "a")), max_old=3)
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        run_check(env, comp(beat(1, "broll", "a")), max_old=-1)
    assert e.value.code == 2


def test_manifest_flag_required_and_layout_validated(env, capsys):
    build_fresh(env, ["a"])
    c = env["tmp"] / "Ep.tsx"
    c.write_text(comp(beat(1, "broll", "a")))
    with pytest.raises(SystemExit) as e:
        cb.main([str(c), "--media-dir", "ep"])
    assert e.value.code == 2
    odd = env["tmp"] / "somewhere" / "_manifest.json"
    odd.parent.mkdir()
    odd.write_text("{}")
    assert run_check(env, comp(beat(1, "broll", "a")), manifest=odd) == 2
    assert "projects/<slug>/assets/broll" in capsys.readouterr().err
    gone = env["projects"] / "x" / "assets" / "broll" / "_manifest.json"
    assert cb.main([str(c), "--media-dir", "ep", "--manifest", str(gone),
                    "--public-root", str(env["public"]), "--projects-root", str(env["projects"]),
                    "--ledger", str(env["ledger"])]) == 2


def test_check_exit_codes(env):
    build_fresh(env, ["a"])
    assert run_check(env, comp(beat(1, "broll", "a"))) == 0
    assert run_check(env, comp(beat(1, "broll", "a"), beat(2, "broll", "a"))) == 1
    c = env["tmp"] / "nope.tsx"
    assert cb.main([str(c), "--media-dir", "ep", "--manifest", str(env["manifest"]),
                    "--public-root", str(env["public"]), "--projects-root", str(env["projects"]),
                    "--ledger", str(env["ledger"])]) == 2


# ------------------------------------------- fix 5 (via CLI): (d)(e)(f) bypasses

def test_d_spread_of_old_beats_cannot_hide_footage(env):
    build_fresh(env, ["a"])
    assert run_check(env, 'const BEATS: Beat[] = [...OLD, { t:1, media:"broll", src:"a" }];\n', max_old=0) == 2


def test_e_commented_out_decl_does_not_replace_the_real_one(env, capsys):
    build_other(env, "ep_old", ["k0"])
    build_fresh(env, [])
    make_public(env["public"], "ep", {"k0": b"PUB-ep_old-k0"})
    text = ('// const BEATS: Beat[] = [{ t: 1, media: "broll", src: "fresh" }];\n'
            'const BEATS: Beat[] = [{ t: 1, media: "broll", src: "k0" }];\n')
    assert run_check(env, text, max_old=0) == 1
    assert "same content as ep_old" in capsys.readouterr().out


def test_f_map_over_beats_is_refused(env):
    build_fresh(env, ["a"])
    text = 'const BEATS: Beat[] = [{ t: 1, media: "broll", src: "a" }].map((b) => ({ ...b, src: "zzz" }));\n'
    assert run_check(env, text, max_old=0) == 2


# ------------------------------------------------------------ fix 6: assetDir

def test_asset_dir_mismatch_is_a_violation(env, capsys):
    build_fresh(env, ["a"])
    assert run_check(env, comp(beat(1, "broll", "a"), asset_dir="someOtherEpisode")) == 1
    out = capsys.readouterr().out
    assert "assetDir is `someOtherEpisode`" in out and "--media-dir is `ep`" in out


def test_asset_dir_match_ok_and_missing_is_only_a_warning(env, capsys):
    build_fresh(env, ["a"])
    assert run_check(env, comp(beat(1, "broll", "a"), asset_dir="ep")) == 0
    assert "warning" not in capsys.readouterr().out
    assert run_check(env, comp(beat(1, "broll", "a"))) == 0
    out = capsys.readouterr().out
    assert "warning: no `assetDir" in out and "PASS" in out


# ------------------------------------------------------- fix 7: episode marker

def _record(env, media_dir, comp_path, manifest=None):
    args = ["record", media_dir, "--composition", str(comp_path), "--public-root", str(env["public"]),
            "--ledger", str(env["ledger"])]
    if manifest:
        args += ["--manifest", str(manifest)]
    return bl.main(args)


def test_record_writes_episode_marker_and_check_blocks_reuse_of_media_dir(env, capsys):
    man = build_fresh(env, ["a"])
    c1 = env["tmp"] / "Ep.tsx"
    c1.write_text(comp(beat(1, "broll", "a")))
    assert _record(env, "ep", c1, man) == 0
    mk = bl.load_ledger(env["ledger"])["episodes"]["ep"]
    assert mk["comp"] == "Ep.tsx" and mk["slug"] == "ep-slug" and mk["recorded_at"]
    capsys.readouterr()
    # same composition again: fine
    assert run_check(env, comp(beat(1, "broll", "a")), comp_name="Ep.tsx") == 0
    # a different composition re-using the same mediaDir: blocked
    assert run_check(env, comp(beat(1, "broll", "a")), comp_name="NewVideo.tsx") == 1
    assert "use a new mediaDir for a new video" in capsys.readouterr().out
    # and record refuses to re-bind the mediaDir
    c2 = env["tmp"] / "NewVideo.tsx"
    c2.write_text(comp(beat(1, "broll", "a")))
    assert _record(env, "ep", c2, man) == 1
    assert bl.load_ledger(env["ledger"])["episodes"]["ep"]["comp"] == "Ep.tsx"


# ----------------------------------------------------------------- ledger record

def test_record_merges_episodes_and_pixabay_id(env):
    make_public(env["public"], "ep1", {"a": b"A", "b": b"B"})
    make_public(env["public"], "ep2", {"a": b"A", "c": b"C"})
    c1 = env["tmp"] / "Ep1.tsx"
    c1.write_text(comp(beat(1, "broll", "a"), beat(2, "broll", "b")))
    c2 = env["tmp"] / "Ep2.tsx"
    c2.write_text(comp(beat(1, "broll", "a"), beat(2, "typo", "c"), beat(3, "clip", "yt_q"), beat(4, "web")))
    assert _record(env, "ep1", c1) == 0
    man = env["projects"] / "slug2" / "assets" / "broll" / "_manifest.json"
    man.parent.mkdir(parents=True)
    man.write_text(json.dumps({"a": {"pixabay_id": "111", "raw_md5": "r" * 32},
                               "c": {"pixabay_id": "333", "raw_md5": "s" * 32}}))
    assert _record(env, "ep2", c2, man) == 0
    led = bl.load_ledger(env["ledger"])
    a = bl.find_entry(led, md5(b"A"), "public")
    assert a["episodes"] == ["ep1", "ep2"] and a["pixabay_id"] == "111"
    c = bl.find_entry(led, md5(b"C"), "public")
    assert c["episodes"] == ["ep2"] and c["pixabay_id"] == "333"
    assert bl.used_pixabay_ids(led) == {"111", "333"}
    assert bl.known_raw_md5s(led) == {"r" * 32, "s" * 32}
    assert bl.find_entry(led, "r" * 32, "raw")["episodes"] == ["slug2"]
    assert not any(e["key"].startswith("yt_") for e in led["entries"].values())
    assert len(led["entries"]) == 5  # public a, b, c + raw a, raw c


def test_record_composition_by_name_and_missing_file_warns(env, capsys, monkeypatch):
    make_public(env["public"], "ep", {"a": b"A"})
    src = env["tmp"] / "remotion-composer" / "src"
    src.mkdir(parents=True)
    (src / "Named.tsx").write_text(comp(beat(1, "broll", "a"), beat(2, "broll", "ghost")))
    monkeypatch.chdir(env["tmp"])
    assert bl.main(["record", "ep", "--composition", "Named.tsx", "--public-root", str(env["public"]),
                    "--ledger", str(env["ledger"])]) == 0
    out = capsys.readouterr().out
    assert "ghost" in out and "missing" in out
    assert len(bl.load_ledger(env["ledger"])["entries"]) == 1


def test_record_bad_composition_exit_2(env):
    assert bl.main(["record", "ep", "--composition", str(env["tmp"] / "nope.tsx"),
                    "--public-root", str(env["public"]), "--ledger", str(env["ledger"])]) == 2
    bad = env["tmp"] / "Bad.tsx"
    bad.write_text("const BEATS = [...X];")
    assert _record(env, "ep", bad) == 2


def test_show(env, capsys):
    make_public(env["public"], "ep1", {"a": b"A"})
    bl.main(["seed", "--public-root", str(env["public"]), "--projects-root", str(env["projects"]),
             "--ledger", str(env["ledger"])])
    capsys.readouterr()
    assert bl.main(["show", "--ledger", str(env["ledger"])]) == 0
    out = capsys.readouterr().out
    assert "1 entries" in out and "ep1" in out


def test_save_is_atomic_no_temp_left(env):
    with bl.locked_ledger(env["ledger"]) as led:
        bl.add_entry(led, "m" * 32, "public", "k", "e")
    assert sorted(p.name for p in env["ledger"].parent.iterdir()) == ["_broll_ledger.json", "_broll_ledger.json.lock"]


def test_same_md5_in_several_kinds_coexists():
    led = bl.empty_ledger()
    bl.add_entry(led, "x" * 32, "public", "a", "e1")
    bl.add_entry(led, "x" * 32, "raw", "a", "e1")
    bl.add_entry(led, "x" * 32, "yt", "yt_a", "e2")
    assert len(led["entries"]) == 3
    assert bl.known_raw_md5s(led) == {"x" * 32}
    assert bl.episodes_by_md5(led) == {"x" * 32: {"e1", "e2"}}


# ------------------------------------------------------------------- fetch

def _cand(i, dur=20):
    return {"id": str(i), "page_url": f"https://pixabay.com/videos/{i}/", "url": f"https://cdn/{i}.mp4",
            "quality": "large", "duration": dur}


def _page(cands, raw_count=None):
    p = fb.Page(cands)
    p.raw_count = raw_count
    return p


@pytest.fixture
def fake_pixabay(monkeypatch):
    """search: per (query) -> list of pages; download writes bytes b'VID<n>.mp4'."""
    state = {"pages": {}, "searched": [], "downloaded": [], "fail_urls": set()}

    def search(api_key, query, category, page, per_page):
        state["searched"].append((query, category, page))
        pages = state["pages"].get(query, [])
        return _page(pages[page - 1] if page <= len(pages) else [])

    def download(url, dest):
        state["downloaded"].append(url)
        if url in state["fail_urls"]:
            raise OSError("boom")
        Path(dest).write_bytes(b"VID" + url.rsplit("/", 1)[1].encode())

    monkeypatch.setattr(fb, "search_candidates", search)
    monkeypatch.setattr(fb, "download_file", download)
    return state


def _queries(env, spec):
    p = env["tmp"] / "queries.json"
    p.write_text(json.dumps(spec), encoding="utf-8")
    return p


def _fetch(env, spec, out=None, slug=None, **kw):
    out = out or env["raw"]
    return fb.fetch_videos(_queries(env, spec), out, env["ledger"], "KEY",
                           public_root=env["public"], projects_root=env["projects"], **kw)


def test_fetch_skips_ledger_ids_and_underscore_keys(env, fake_pixabay):
    with bl.locked_ledger(env["ledger"]) as l:
        bl.add_entry(l, "a" * 32, "raw", "old", "ep0", pixabay_id="1")
    fake_pixabay["pages"]["q"] = [[_cand(1), _cand(2)]]
    assert _fetch(env, {"_note": ["x", "y"], "k": ["q", "computer"]}) == 0
    out = env["raw"]
    assert (out / "k.mp4").read_bytes() == b"VID2.mp4"
    assert not (out / "_note.mp4").exists()
    assert fake_pixabay["downloaded"] == ["https://cdn/2.mp4"]
    m = json.loads((out / "_manifest.json").read_text())
    assert set(m) == {"k"}
    assert m["k"]["pixabay_id"] == "2" and m["k"]["category"] == "computer" and m["k"]["query"] == "q"
    assert m["k"]["duration"] == 20 and m["k"]["page_url"].endswith("/2/")
    assert m["k"]["raw_md5"] == bl.md5_file(out / "k.mp4")
    assert bl.used_pixabay_ids(bl.load_ledger(env["ledger"])) == {"1"}  # fetch never marks "used"


def test_fetch_skips_known_raw_md5_takes_next(env, fake_pixabay):
    with bl.locked_ledger(env["ledger"]) as l:
        bl.add_entry(l, md5(b"VID1.mp4"), "raw", "old", "ep0")  # candidate 1 is byte-identical, no id known
    fake_pixabay["pages"]["q"] = [[_cand(1), _cand(2)]]
    assert _fetch(env, {"k": ["q", ""]}) == 0
    assert fake_pixabay["downloaded"] == ["https://cdn/1.mp4", "https://cdn/2.mp4"]
    assert (env["raw"] / "k.mp4").read_bytes() == b"VID2.mp4"
    assert not list(env["raw"].glob(".tmp_*"))


def test_fetch_known_md5_in_another_projects_folder_without_ledger(env, fake_pixabay):
    """No ledger file at all: the auto-seed finds the old raw file on disk."""
    make_raw(env["projects"], "older-slug", {"x": b"VID1.mp4"})
    fake_pixabay["pages"]["q"] = [[_cand(1), _cand(2)]]
    assert not env["ledger"].exists()
    assert _fetch(env, {"k": ["q", ""]}) == 0
    assert json.loads((env["raw"] / "_manifest.json").read_text())["k"]["pixabay_id"] == "2"


def test_fetch_distinct_ids_across_keys_and_resume(env, fake_pixabay):
    fake_pixabay["pages"]["q"] = [[_cand(1), _cand(2), _cand(3)]]
    assert _fetch(env, {"a": ["q", ""], "b": ["q", ""]}) == 0
    m = json.loads((env["raw"] / "_manifest.json").read_text())
    assert (m["a"]["pixabay_id"], m["b"]["pixabay_id"]) == ("1", "2")
    n = len(fake_pixabay["searched"])
    assert _fetch(env, {"a": ["q", ""], "b": ["q", ""], "c": ["q", ""]}) == 0
    assert len(fake_pixabay["searched"]) == n + 1
    m = json.loads((env["raw"] / "_manifest.json").read_text())
    assert set(m) == {"a", "b", "c"} and m["c"]["pixabay_id"] == "3"


def test_fetch_no_fresh_candidate_fails_but_continues(env, fake_pixabay, capsys):
    with bl.locked_ledger(env["ledger"]) as l:
        bl.add_entry(l, "a" * 32, "raw", "x", "ep0", pixabay_id="1")
    fake_pixabay["pages"]["bad"] = [[_cand(1)], [], []]
    fake_pixabay["pages"]["good"] = [[_cand(5)]]
    assert _fetch(env, {"bad": ["bad", ""], "good": ["good", ""]}) == 1
    assert "FAIL bad no fresh clip — use a more specific query" in capsys.readouterr().out
    assert not (env["raw"] / "bad.mp4").exists() and (env["raw"] / "good.mp4").exists()
    assert [p for (qq, c, p) in fake_pixabay["searched"] if qq == "bad"] == [1, 2, 3]


def test_fetch_search_error_fails_key_only(env, monkeypatch, capsys):
    def boom(api_key, query, category, page, per_page):
        if query == "boom":
            raise RuntimeError("HTTP 429")
        return _page([_cand(9)])

    monkeypatch.setattr(fb, "search_candidates", boom)
    monkeypatch.setattr(fb, "download_file", lambda url, dest: Path(dest).write_bytes(b"V9"))
    assert _fetch(env, {"x": ["boom", ""], "y": ["ok", ""]}) == 1
    assert (env["raw"] / "y.mp4").exists()
    assert "FAIL x" in capsys.readouterr().out


def test_fetch_dry_run_downloads_nothing(env, fake_pixabay, capsys):
    fake_pixabay["pages"]["q"] = [[_cand(1), _cand(2)]]
    out = env["tmp"] / "dry" / "assets" / "broll"
    assert _fetch(env, {"a": ["q", ""], "b": ["q", ""]}, out=out, dry_run=True) == 0
    assert fake_pixabay["downloaded"] == [] and not out.exists()
    text = capsys.readouterr().out
    assert "a: id=1" in text and "b: id=2" in text
    assert not any(e.get("kind") == "reserved" for e in bl.load_ledger(env["ledger"])["entries"].values())


def test_pick_rendition_prefers_large_then_falls_back():
    assert fb.pick_rendition({"videos": {"large": {"url": "L"}, "medium": {"url": "M"}}}) == ("L", "large")
    assert fb.pick_rendition({"videos": {"large": {"url": ""}, "small": {"url": "S"}}}) == ("S", "small")
    assert fb.pick_rendition({"videos": {}}) == (None, None)


class _Resp:
    def __init__(self, status=200, hits=()):
        self.status_code = status
        self._hits = list(hits)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return {"hits": self._hits}


def test_search_candidates_params_and_filter(monkeypatch):
    import requests

    seen = {}
    hits = [
        {"id": 1, "duration": 5, "videos": {"large": {"url": "u1"}}},    # too short
        {"id": 2, "duration": 20, "pageURL": "p2", "videos": {"medium": {"url": "u2"}}},
        {"id": 3, "duration": 99, "videos": {"large": {"url": "u3"}}},   # too long
        {"id": 4, "duration": 10, "videos": {}},                         # no file
    ]

    def fake_get(url, params=None, timeout=None):
        seen.update(params)
        return _Resp(200, hits)

    monkeypatch.setattr(requests, "get", fake_get)
    got = fb.search_candidates("K", "x" * 150, "computer", 2, 1)
    assert [c["id"] for c in got] == ["2"] and got[0]["quality"] == "medium"
    assert got.raw_count == 4
    assert seen["key"] == "K" and seen["category"] == "computer" and seen["page"] == 2
    assert seen["per_page"] == 3 and seen["safesearch"] == "true" and len(seen["q"]) == 100


# ---- fix 4: pre-existing files

def test_fetch_existing_file_not_from_fetch_fails(env, fake_pixabay, capsys):
    make_raw(env["projects"], env["slug"], {"k": b"copied from somewhere"})  # no manifest entry
    fake_pixabay["pages"]["q"] = [[_cand(1)]]
    assert _fetch(env, {"k": ["q", ""]}) == 1
    assert "FAIL k existing file was not fetched by fetch_broll (copied?) — delete it and re-run" in capsys.readouterr().out
    assert fake_pixabay["searched"] == []
    # manifest entry with a different md5 is just as bad
    env["manifest"].write_text(json.dumps({"k": {"pixabay_id": "1", "raw_md5": "0" * 32}}))
    assert _fetch(env, {"k": ["q", ""]}) == 1


def test_fetch_existing_file_matching_manifest_is_skipped(env, fake_pixabay, capsys):
    raw = make_raw(env["projects"], env["slug"], {"k": b"VID1.mp4"})
    (raw / "_manifest.json").write_text(json.dumps({"k": {"pixabay_id": "1", "raw_md5": md5(b"VID1.mp4")}}))
    assert _fetch(env, {"k": ["q", ""]}) == 0
    assert "skip k" in capsys.readouterr().out and fake_pixabay["searched"] == []


def test_fetch_existing_file_matching_another_episode_fails(env, fake_pixabay, capsys):
    raw = make_raw(env["projects"], env["slug"], {"k": b"VID1.mp4"})
    (raw / "_manifest.json").write_text(json.dumps({"k": {"pixabay_id": "1", "raw_md5": md5(b"VID1.mp4")}}))
    make_raw(env["projects"], "other-slug", {"z": b"VID1.mp4"})
    assert _fetch(env, {"k": ["q", ""]}) == 1
    assert "matches footage of another episode (other-slug)" in capsys.readouterr().out


def test_fetch_existing_webm_counts_too(env, fake_pixabay, capsys):
    raw = make_raw(env["projects"], env["slug"], {})
    (raw / "k.webm").write_bytes(b"x")
    assert _fetch(env, {"k": ["q", ""]}) == 1
    assert "not fetched by fetch_broll" in capsys.readouterr().out


# ---- fix 8: reservations

def test_fetch_reserves_chosen_id_for_its_slug_and_others_skip_it(env, fake_pixabay):
    fake_pixabay["pages"]["q"] = [[_cand(1), _cand(2)]]
    assert _fetch(env, {"k": ["q", ""]}) == 0
    led = bl.load_ledger(env["ledger"])
    res = led["entries"]["reserved:1"]
    assert res["kind"] == "reserved" and res["episodes"] == ["ep-slug"] and res["pixabay_id"] == "1"
    assert bl.used_pixabay_ids(led) == set()  # reserved != used
    other = env["projects"] / "other-slug" / "assets" / "broll"
    assert _fetch(env, {"k": ["q", ""]}, out=other) == 0
    assert json.loads((other / "_manifest.json").read_text())["k"]["pixabay_id"] == "2"
    assert bl.blocked_pixabay_ids(led, "other-slug") == {"1"}
    assert bl.blocked_pixabay_ids(led, "ep-slug") == set()


def test_same_slug_rerun_may_reuse_its_own_reservation(env, fake_pixabay):
    with bl.locked_ledger(env["ledger"]) as l:
        assert bl.reserve_pixabay_id(l, 1, "ep-slug", "k")
        assert not bl.reserve_pixabay_id(l, 1, "someone-else", "k")
        assert bl.reserve_pixabay_id(l, 1, "ep-slug", "k")  # idempotent for the owner
    fake_pixabay["pages"]["q"] = [[_cand(1)]]
    assert _fetch(env, {"k": ["q", ""]}) == 0
    assert json.loads(env["manifest"].read_text())["k"]["pixabay_id"] == "1"


def test_reservation_lost_to_concurrent_fetch_is_skipped(env, fake_pixabay, monkeypatch):
    fake_pixabay["pages"]["q"] = [[_cand(1), _cand(2)]]
    real = bl.reserve_pixabay_id

    def racing(ledger, pid, slug, key=""):
        if str(pid) == "1":  # another episode grabs id 1 between our view and our claim
            real(ledger, pid, "racer", key)
        return real(ledger, pid, slug, key)

    monkeypatch.setattr(bl, "reserve_pixabay_id", racing)
    assert _fetch(env, {"k": ["q", ""]}) == 0
    assert json.loads(env["manifest"].read_text())["k"]["pixabay_id"] == "2"
    assert fake_pixabay["downloaded"] == ["https://cdn/2.mp4"]


def test_seed_recreates_reservations_from_manifests_and_record_marks_used(env):
    raw = make_raw(env["projects"], "slug-x", {"a": b"A"})
    (raw / "_manifest.json").write_text(json.dumps({"a": {"pixabay_id": "77", "raw_md5": md5(b"A")}}))
    led = bl.empty_ledger()
    bl.seed_scan(led, env["public"], env["projects"])
    assert bl.blocked_pixabay_ids(led, "other") == {"77"}
    assert bl.blocked_pixabay_ids(led, "slug-x") == set()
    assert bl.used_pixabay_ids(led) == set()


# ---- fix 9: candidate loop

def test_fetch_failed_download_tries_next_candidate_and_releases_id(env, fake_pixabay):
    fake_pixabay["fail_urls"].add("https://cdn/1.mp4")
    fake_pixabay["pages"]["q"] = [[_cand(1), _cand(2)]]
    assert _fetch(env, {"k": ["q", ""]}) == 0
    assert fake_pixabay["downloaded"] == ["https://cdn/1.mp4", "https://cdn/2.mp4"]
    assert (env["raw"] / "k.mp4").read_bytes() == b"VID2.mp4"
    entries = bl.load_ledger(env["ledger"])["entries"]
    assert "reserved:1" not in entries and "reserved:2" in entries
    assert not list(env["raw"].glob(".tmp_*"))


def test_fetch_stops_paging_on_short_page(env, monkeypatch, capsys):
    seen = []

    def search(api_key, query, category, page, per_page):
        seen.append(page)
        return _page([_cand(1)], raw_count=5)  # 5 hits < per_page 30 -> last page

    monkeypatch.setattr(fb, "search_candidates", search)
    monkeypatch.setattr(fb, "download_file", lambda url, dest: Path(dest).write_bytes(b"V"))
    with bl.locked_ledger(env["ledger"]) as l:
        bl.add_entry(l, "a" * 32, "raw", "x", "ep0", pixabay_id="1")
    assert _fetch(env, {"k": ["q", ""]}) == 1
    assert seen == [1]
    assert "no fresh clip" in capsys.readouterr().out


def test_fetch_full_pages_keep_paging_up_to_three(env, monkeypatch):
    seen = []

    def search(api_key, query, category, page, per_page):
        seen.append(page)
        return _page([_cand(1)], raw_count=30)

    monkeypatch.setattr(fb, "search_candidates", search)
    with bl.locked_ledger(env["ledger"]) as l:
        bl.add_entry(l, "a" * 32, "raw", "x", "ep0", pixabay_id="1")
    assert _fetch(env, {"k": ["q", ""]}) == 1
    assert seen == [1, 2, 3]


def test_search_http_400_on_later_page_is_end_of_results(monkeypatch):
    import requests

    monkeypatch.setattr(requests, "get", lambda url, params=None, timeout=None: _Resp(400))
    page2 = fb.search_candidates("K", "q", "", 2, 30)
    assert list(page2) == [] and page2.raw_count == 0
    with pytest.raises(RuntimeError):  # but 400 on page 1 is a real error
        fb.search_candidates("K", "q", "", 1, 30)


def test_fetch_400_on_page_two_is_not_a_search_failure(env, monkeypatch, capsys):
    import requests

    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params["page"])
        if params["page"] == 1:
            return _Resp(200, [{"id": 1, "duration": 20, "videos": {"large": {"url": "u"}}}] * 30)
        return _Resp(400)

    monkeypatch.setattr(requests, "get", fake_get)
    with bl.locked_ledger(env["ledger"]) as l:
        bl.add_entry(l, "a" * 32, "raw", "x", "ep0", pixabay_id="1")
    assert _fetch(env, {"k": ["q", ""]}) == 1
    out = capsys.readouterr().out
    assert calls == [1, 2] and "no fresh clip" in out and "RuntimeError" not in out and "HTTP" not in out


# ------------------------------------------------------- fix 10: transcode_broll.sh

def _stub(bin_dir: Path, name: str, body: str):
    p = bin_dir / name
    p.write_text("#!/bin/bash\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


def _run_transcode(tmp, src, out, names):
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    _stub(bin_dir, "ffprobe", 'case "$*" in *duration*) echo 12.5;; esac; exit 0\n')
    _stub(bin_dir, "ffmpeg", 'for a; do last="$a"; done; echo transcoded > "$last"; exit 0\n')
    envv = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    r = subprocess.run(["bash", str(SCRIPTS / "transcode_broll.sh"), str(src), str(out), *names],
                       capture_output=True, text=True, env=envv)
    return r.stdout


def test_transcode_reencodes_when_raw_is_newer_than_output(tmp_path):
    src, out = tmp_path / "raw", tmp_path / "pub"
    src.mkdir()
    out.mkdir()
    (src / "a.mp4").write_bytes(b"raw")
    (out / "a.mp4").write_bytes(b"old output")
    # output newer than raw -> keep (V1 skip behaviour)
    os.utime(src / "a.mp4", (1_000_000, 1_000_000))
    os.utime(out / "a.mp4", (2_000_000, 2_000_000))
    o = _run_transcode(tmp_path, src, out, ["a"])
    assert "ok a" in o and (out / "a.mp4").read_bytes() == b"old output"
    # raw re-fetched (newer) -> re-encode
    os.utime(src / "a.mp4", (3_000_000, 3_000_000))
    o = _run_transcode(tmp_path, src, out, ["a"])
    assert "done a" in o and (out / "a.mp4").read_text().strip() == "transcoded"


def test_transcode_script_syntax():
    assert subprocess.run(["bash", "-n", str(SCRIPTS / "transcode_broll.sh")]).returncode == 0


# ------------------------------------------------------------------- CLI help

def test_cli_help_works(capsys):
    for mod in (bl, cb, fb):
        with pytest.raises(SystemExit) as e:
            mod.main(["--help"])
        assert e.value.code == 0
        assert "usage" in capsys.readouterr().out.lower()
