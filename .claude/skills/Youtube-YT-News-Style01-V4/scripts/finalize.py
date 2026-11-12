#!/usr/bin/env python3
"""finalize.py - the ONLY way to hand over the final video of a YT-News V4 episode.

  finalize.py --project projects/<slug> --deliver <output.mp4> [--composer remotion-composer]
              [--repo-root <git top level>] [--manifest <json>] [--check]

Order of work: (1) integrity of the gate files (gates_lock, exit 3), (2) the gates are RUN fresh (long ones
first), (3) the reports of the long jobs (layout sweep, render, mux, relevance, final duration) are VERIFIED by
hash binding, (4) only if every one of them passes the final mp4 is copied to --deliver and a delivery receipt is
written.  There is deliberately NO flag and NO environment variable that skips or downgrades a gate.

ONE deadline covers the whole invocation (TOTAL_BUDGET_SEC, lock/git checks + gates + verification + copy); when it
runs out the command ends with exit 4 and a FAILED file that names the phase.  The tools (node, ffmpeg, ffprobe, git,
swift) are resolved once to absolute realpaths and the gates run with a fixed minimal PATH.

Exit codes (precedence): 3 integrity > 4 tool/gate missing, crash or timeout > 2 stale/missing report or bad
input > 1 quality failure; 0 delivered (or --check: everything would pass).
A relative --project is resolved against the repository root (git top level of this skill), --deliver against
the current directory.  --composer must be <repo root>/remotion-composer (anything else is exit 3).
"""
import argparse
import atexit
import concurrent.futures
import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / 'scripts'
LOCK_FILE = SCRIPTS_DIR / 'gates.lock.json'

COMP = 'YtNewsStyle01V4'                  # the single composition; there is no --comp
RECEIPT_SCHEMA = 'yt-news-v4-delivery-receipt'
FAILED_SCHEMA = 'yt-news-v4-finalize-failed'
CHECK_SCHEMA = 'yt-news-v4-finalize-check'
# One deadline for the whole invocation; unattended commands are killed after ~10 min.  The gates may only use the
# time up to TOTAL - POST_RESERVE; the rest is kept for verification + delivery.  A delivery copy is only started
# with DELIVER_RESERVE_SEC left.  Worst case wall time = TOTAL_BUDGET_SEC + the 5 s kill grace of one child.
TOTAL_BUDGET_SEC = 450
POST_RESERVE_SEC = 90
DELIVER_RESERVE_SEC = 20
GIT_TIMEOUT_SEC = 20
MAX_WORKERS = 3
STALE_TOLERANCE_NS = 2_000_000_000
RUN_LOCK_NAME = '.finalize.lock'
RUN_LOCK_STALE_SEC = 15 * 60     # only a guard against pid reuse: a lock whose pid is dead is stale at once
FRAME_TOLERANCE_SEC = 0.04       # final duration vs totalDurationSec
TOOL_NAMES = ('node', 'ffmpeg', 'ffprobe', 'git', 'swift')
REQUIRED_TOOLS = TOOL_NAMES      # all of them: swift = macOS Vision OCR of the frames gate (no OCR = no watermark/promo check)
# composer-relative files whose current hashes the layout manifest and the render receipt must carry (CF-A66, 5fe7699)
ENGINE_REL = 'src/YtNewsStyle01V4.tsx'
ENTRY_REL = 'src/ytNewsStyle01V4.entry.tsx'
EXPECTED_PIX_FMT = 'yuv420p'
# environment (the same checks run first in a real run and in `--preflight`)
PY_MODULES = ('numpy', 'PIL', 'pythainlp')          # the gates run under THIS interpreter (sys.executable)
# what qc_layout.mjs / render_episode.mjs load lazily from <composer>/node_modules (createRequire(<composer>/package.json)(name))
# plus `remotion` itself, imported by the engine bundle; each must be installed as <composer>/node_modules/<name>/package.json
COMPOSER_PACKAGES = ('remotion', '@remotion/bundler', '@remotion/renderer')
# the exact files YtNewsStyle01V4.tsx loads (render-blocking; a failed load cancels the render), relative to <composer>/public
FONT_FILES = ('fonts/Kanit-Bold.ttf', 'fonts/Kanit-ExtraBold.ttf')
WHISPER_DEFAULT_MODEL = 'mlx-community/whisper-large-v3-mlx'      # word_timing.sh default

# =================================================================================================================
# CONTRACT with the other team's scripts (CF-A66, commit 5fe7699).  EVERY field / flag name of those scripts that
# finalize depends on lives in this section; if their code changes, change it here only.
# Verified against the real files at 5fe7699; where code and gate-spec disagreed the CODE wins (see the notes).
# =================================================================================================================
# -- qc_layout / qc_report.mjs : layout report v3 (<project>/qc/layout/report.json) -----------------------------
#    keys used: schema, version, status ("finished"), pass, complete, requestedCount, fullPlanCount, compositionId,
#    runId, manifestHash, manifestPath (RELATIVE to the layout --out dir, as qc_layout.mjs writes it), reusedFrames.
#    The V4 bundle is built from its OWN entry (src/ytNewsStyle01V4.entry.tsx), never from Root.tsx / index.tsx.
LAYOUT_REPORT_SCHEMA = 'yt-news-layout-report'
LAYOUT_REPORT_VERSION = 3
# -- qc_manifest.mjs : run manifest + manifestHash() (we call the JS function; canonical JSON is NOT re-implemented).
#    sourceHashes keys used: episode.json, captions.json, scripts/gates.lock.json, src/YtNewsStyle01V4.tsx (ENGINE_REL),
#    src/ytNewsStyle01V4.entry.tsx (ENTRY_REL); the other keys (import closure files, assets references, scripts/qc_*, the
#    package-lock) are covered by the hash itself
RUN_MANIFEST_SCHEMA = 'yt-news-v4-run-manifest'
QC_MANIFEST_SCRIPT = 'qc_manifest.mjs'
MANIFEST_KEY_EPISODE = 'episode.json'            # keys of manifest.sourceHashes (computeSourceHashes)
MANIFEST_KEY_CAPTIONS = 'captions.json'
MANIFEST_KEY_LOCK = 'scripts/gates.lock.json'
# -- render_episode.mjs : render receipt <visual>.receipt.json (RECEIPT_FIELDS; written next to the output file as
#    `<out>.receipt.json`).  keys used: schema, schemaVersion, compositionId, draft (must be false), hasAudio (must be
#    false), outputSha256 (the visual), episodeJsonSha256, captionsJsonSha256, gatesLockSha256 (null without a lock),
#    gateManifestHash, gateRunId, renderId, width, height, fps, frameCount (checked against ffprobe of the visual),
#    engineSha256, entrySha256 and entryClosure ({"src/<file>": sha256} of the entry and every file it imports; each must
#    equal the current composer file).  rootTsxSha256 / indexTsxSha256 no longer exist.  The render reads public/ from
#    <composer>/public.  outputSha256 only binds THIS file to its receipt: two renders of the same sources are NOT
#    byte-identical, so nothing here compares or expects equal hashes across renders.
RENDER_RECEIPT_SUFFIX = '.receipt.json'
RENDER_RECEIPT_SCHEMA = 'yt-news-v4-render-receipt'
# -- episode.json (episode_schema.mjs): top level voEndSec, totalDurationSec, assetDir, avatarFile.  The media of an
#    episode live in <composer>/public/<assetDir>/ (broll/<src>.mp4, <avatarFile>): same convention as qc_layout.mjs
#    and render_episode.mjs (path.join(composer, 'public')).
# -- qc_final_pixels.mjs : `node qc_final_pixels.mjs <video.mp4> <out-dir> [--vo-end s]` (positional out-dir; the
#    gate-spec/coordinator note said --out-dir, the CODE rejects it as "unknown option"); report <out-dir>/final-pixels.json
#    with videoSha256 + certified + pass; exit 0 pass / 1 dips / 2 error.  --allow-draft is NEVER passed.
# -- episode_schema.mjs : `validate <episode> --captions <captions> --public <composer>/public --json` -> stdout
#    {valid, errors[{path,rule,message}], warnings, schemaSha256}; exit 0 valid / 1 invalid / 2 usage-IO (also a
#    --public directory that does not exist).  --public turns on the S07-file rule (every media file must exist).
# -- gate_integrity.mjs : `<composer-dir> --json --skill-dir <dir> --require-lock` -> stdout {ok, issues[{id,message}],
#    warnings, lock}, exit 0 / 3 refused / 2 usage.  Without --require-lock a missing lock is only a WARNING, so it is
#    always passed.  Its lock check needs the skill dir to sit at <repo>/.claude|.agents/skills/<skill>.  Exit 3 is an
#    INTEGRITY refusal (class 3 -> finalize exit 3).  Issue ids: engine-drift, entry-drift, entry-registration,
#    entry-closure, gates-lock*.  `<composer> --list-external` prints the repo-relative files the lock must pin (see below).
# -- gates_lock.py (ours) : the files the lock must pin under "external" are never typed by hand: gates_lock.py runs
#    `node <skill>/scripts/gate_integrity.mjs <repo>/remotion-composer --list-external` (one repo-relative path per line) in
#    write AND verify, so finalize refuses a lock that lacks one ("external-not-locked", exit 3); node / the script missing
#    ("tool-missing", exit 4) or an empty / failing list ("required-external-unavailable", exit 3) fail closed too.
# -- lint_content.py : --captions (same file as the schema gate) and --evidence / --frames-report / --source-timed (optional;
#    lint itself reports evidence-missing, window-evidence-unavailable, cue-mismatch when a source beat lacks them, so passing
#    what exists never hides an error)
# -- frame_checks.py cutaways : --media-root <composer>/public/<assetDir>/broll (the files the render really uses)
# -- timing_check.py : --audio <avatar media the words were measured on> --words <words_by_line.txt> --line-starts
#    <line_starts.json> --srt <project>/assets/avatar.srt (required here: without --srt the `srt-copied` check would not
#    run); exit 0/1/2/4
# -- srt_to_script.py : `--srt S --script SRC --strict --out O`, exit 0 ok / 1 SRT text differs from the source script
# -- words_by_line.py <pages> <script> (stdout) / line_starts.py --pages P --script S --out O / caption_join.mjs
#    --tokens P --script S --options <caption-options.json> --out O : the commands of SKILL step 2, re-run by the
#    `derived` gate; their outputs must be byte-identical to the artifacts
# -- word_timing.sh : leaves <word_timing dir>/word_timing.done.json {key, output, output_sha256, model, ...}; output_sha256
#    is the sha256 of caption_pages.json.  `key` hashes (audio sha, script sha, tool id, model, args): the audio hash alone is
#    NOT recorded, so the audio binding is only checked statistically by the timing gate
# -- mux_av.sh (ours) : <final>.mux.json {visual, avatar, bed, final: {path (absolute), sha256}}; the video is stream-copied
#    (-c:v copy) so the video packets of final.mp4 must equal those of visual.mp4.  The V4 render is yuv420p + bt709
#    (ENCODER in render_episode.mjs): ffprobe pix_fmt of BOTH files must be yuv420p; pix_fmt / color_space / color_range of the
#    final go into the delivery receipt
# -- frame_checks.py cutaways : needs swift/swiftc (Vision OCR); without it the command exits 4 ("OCR is never skipped
#    silently"), and finalize refuses to start without `swift` on PATH (REQUIRED_TOOLS)
# -- environment_checks() : tools, python modules, composer packages, fonts, gate lock are checked first by a real run, by
#    `--check` and by `--preflight` (same function).  ONE intentional difference: `word-timing` (venv / extractor / cached
#    whisper model of word_timing.sh) is `--preflight`-only; finalize never runs word_timing.sh.
# -- fetch_broll.py --music : <bed>.source.json {schema "yt-news-v4-music-source", provider, track_id, track_title, url,
#    query, sha256, fetched_at}; sha256 must equal the bed file's sha256
# =================================================================================================================

# -- conventions (override ONLY via the manifest, and only the keys in OVERRIDABLE) ----------------------------
# key -> default path (relative to the project).  Required unless the key is in OPTIONAL_KEYS (missing = exit 2).
DEFAULT_PATHS = {
    'episode': 'artifacts/episode.json',
    'script': 'artifacts/script.txt',
    'source_script': 'artifacts/source_script.txt',      # required: the `script` gate rebuilds script.txt from it
    'srt': 'assets/avatar.srt',                          # required: vendor SRT (script rebuild + srt-copied check)
    'words': 'artifacts/words_by_line.txt',
    'line_starts': 'artifacts/line_starts.json',
    'word_pages': 'artifacts/word_timing/caption_pages.json',   # required, not overridable: raw word timing
    'caption_options': 'artifacts/caption-options.json',        # required, not overridable: only endTime/lexicalOverrides
    'captions': 'artifacts/caption-joined.json',
    'cuts': 'artifacts/_cuts.json',
    'source_transcript': 'assets/ytsource/transcript.txt',  # optional
    'source_timed': 'assets/ytsource/transcript_timed.json',  # optional (lint_content treats absence as "no timed transcript")
    'evidence': 'artifacts/visual_evidence.json',            # optional (lint_content fails source beats that lack an entry)
    'chapters': 'assets/ytsource/chapters.txt',              # optional
    'relevance': 'artifacts/relevance.json',                 # optional (absent is allowed)
    'layout_report': 'qc/layout/report.json',
    'visual': 'renders/visual.mp4',
    'final': 'renders/final.mp4',
    'reports': 'qc/finalize',
}
OPTIONAL_KEYS = {'source_transcript', 'source_timed', 'evidence', 'chapters', 'relevance'}
# overridable = inputs the agent (or the fetch step) produces; gate-owned outputs, receipts and the raw timing are never
OVERRIDABLE = {'script', 'source_script', 'srt', 'words', 'line_starts', 'cuts', 'source_transcript', 'source_timed',
               'evidence', 'chapters'}
FORBIDDEN_OVERRIDES = set(DEFAULT_PATHS) - OVERRIDABLE
# derived-from-episode inputs (not path keys): avatar = <composer>/public/<assetDir>/<avatarFile>,
# word_done = <dir of word_pages>/word_timing.done.json, broll_root = <composer>/public/<assetDir>/broll

# -- gate registry (data-driven; long gates first so they start first) -----------------------------------------
# name, interp ('python'|'node'), script (file in this scripts dir), args (templates; {key} = project path,
# {report}, {reports}, {vo_end}, {composer}, {public}, {avatar}, {broll_root}, {skill}), optional_args [[flag,key]]
# (only when the file exists), inputs (required path keys, also hashed into the receipt; 'avatar' and 'word_done' are the
# derived inputs above), needs (episode values that must be readable), need_dirs (ctx attributes that must be
# directories), report (template), limit (s), required, validate (extra validator name), stdout_report (finalize stores
# the tool's stdout JSON at `report`), pass_key (report key that must be True), exit_classes (extra exit code -> class),
# after [gate names] (start only when those gates have FINISHED; if one did not pass this gate is 'blocked' with the
# same exit class and does not run), dep_args [[flag, gate name]] (the report that gate wrote in THIS run),
# runner (a gate that runs several commands / compares files and writes its own report; scripts = the files it needs).
GATES = [
    dict(name='frames', interp='python', script='frame_checks.py',
         args=['cutaways', '--beats', '{episode}', '--cuts', '{cuts}', '--frames-dir', '{reports}/frames',
               '--report', '{report}', '--cache-dir', '{reports}/cache', '--media-root', '{broll_root}'],
         optional_args=[], inputs=['episode', 'cuts'], needs=['asset_dir'], need_dirs=['broll_root'],
         report='{reports}/frames.json', limit=150, required=True),
    dict(name='final-av', interp='python', script='final_av_checks.py',
         args=['{final}', '--report', '{report}', '--ignore-from', '{vo_end}'],
         optional_args=[], inputs=['final'], needs=['vo_end'],
         report='{reports}/final-av.json', limit=120, required=True),
    dict(name='final-pixels', interp='node', script='qc_final_pixels.mjs',
         args=['{final}', '{reports}/final-pixels', '--vo-end', '{vo_end}'], optional_args=[],
         inputs=['final'], needs=['vo_end'], report='{reports}/final-pixels/final-pixels.json',
         limit=120, required=True, validate='final_pixels'),
    dict(name='loudness', interp='python', script='measure_loudness.py', args=['{final}', '--report', '{report}'],
         optional_args=[], inputs=['final'], needs=[], report='{reports}/final-audio.json',
         limit=60, required=True),
    dict(name='timing', interp='python', script='timing_check.py',
         args=['--audio', '{avatar}', '--words', '{words}', '--line-starts', '{line_starts}', '--srt', '{srt}',
               '--report', '{report}'],
         optional_args=[], inputs=['avatar', 'words', 'line_starts', 'srt'], needs=['asset_dir', 'avatar_file'],
         report='{reports}/timing.json', limit=120, required=True),
    dict(name='schema', interp='node', script='episode_schema.mjs',
         args=['validate', '{episode}', '--captions', '{captions}', '--public', '{public}', '--json'],
         optional_args=[], inputs=['episode', 'captions'], needs=[], report='{reports}/schema.json', limit=30,
         required=True, stdout_report=True, pass_key='valid'),
    dict(name='gate-integrity', interp='node', script='gate_integrity.mjs',
         args=['{composer}', '--json', '--skill-dir', '{skill}', '--require-lock'], optional_args=[], inputs=[],
         needs=[], report='{reports}/gate-integrity.json', limit=60, required=True,
         stdout_report=True, pass_key='ok', exit_classes={3: 3}),
    dict(name='beats', interp='python', script='lint_beats.py', args=['{episode}', '--report', '{report}'],
         optional_args=[], inputs=['episode'], needs=[], report='{reports}/beats.json',
         limit=30, required=True),
    dict(name='content', interp='python', script='lint_content.py',
         args=['--beats', '{episode}', '--script', '{script}', '--words', '{words}', '--line-starts', '{line_starts}',
               '--cuts', '{cuts}', '--captions', '{captions}', '--report', '{report}'],
         optional_args=[['--source-transcript', 'source_transcript'], ['--chapters', 'chapters'],
                        ['--relevance', 'relevance'], ['--evidence', 'evidence'], ['--source-timed', 'source_timed']],
         inputs=['episode', 'script', 'words', 'line_starts', 'cuts', 'captions'], needs=[],
         report='{reports}/content.json', limit=60, required=True,
         after=['frames'], dep_args=[['--frames-report', 'frames']]),
    dict(name='captions', interp='python', script='lint_captions.py',
         args=['--script', '{script}', '--pages', '{captions}', '--source-script', '{source_script}', '--report', '{report}'],
         optional_args=[], inputs=['script', 'captions', 'source_script'],
         needs=[], report='{reports}/captions.json', limit=60, required=True),
    dict(name='script', runner='script', scripts=['srt_to_script.py'], optional_args=[],
         inputs=['srt', 'source_script', 'script'], needs=[], report='{reports}/script.json', limit=30, required=True),
    dict(name='derived', runner='derived', scripts=['words_by_line.py', 'line_starts.py', 'caption_join.mjs'], optional_args=[],
         inputs=['word_pages', 'word_done', 'caption_options', 'script', 'words', 'line_starts', 'captions'],
         needs=['vo_end'], report='{reports}/derived.json', limit=90, required=True),
]

STATUS_BY_CLASS = {1: 'fail', 2: 'bad-input', 3: 'integrity', 4: 'missing'}
RESTORE_HINT = 'restore the skill files from git HEAD; never edit or regenerate gates.lock.json'


# ---------------------------------------------------------------- helpers
def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


class Hasher:
    """Memoised sha256 per resolved path; recheck() detects files that changed during the run."""

    def __init__(self):
        self.memo = {}

    def __call__(self, path):
        key = str(Path(path).resolve())
        if key not in self.memo:
            self.memo[key] = sha256_file(key)
        return self.memo[key]

    def recheck(self):
        changed = []
        for key, old in self.memo.items():
            try:
                new = sha256_file(key)
            except OSError:
                new = None
            if new != old:
                changed.append(key)
        return changed


def load_sibling(name):
    """Load scripts/<name>.py from source (no pycache involved)."""
    import types
    src = (SCRIPTS_DIR / (name + '.py')).read_text()
    mod = types.ModuleType(name)
    mod.__file__ = str(SCRIPTS_DIR / (name + '.py'))
    exec(compile(src, mod.__file__, 'exec'), mod.__dict__)
    return mod


def read_json(path):
    try:
        return json.loads(Path(path).read_text()), None
    except FileNotFoundError:
        return None, 'missing'
    except (OSError, ValueError) as e:
        return None, 'unreadable: %s' % e


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float('inf')


def valid_sha(v):
    return isinstance(v, str) and re.fullmatch(r'[0-9a-fA-F]{64}', v) is not None


def tail(text, n=1500):
    return text[-n:] if text else ''


def remove_quiet(p):
    try:
        os.unlink(p)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def write_json_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    os.replace(tmp, path)


def inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- child process hygiene
ACTIVE_PGIDS = set()
_ACTIVE_LOCK = threading.Lock()
STOP = threading.Event()          # set by SIGTERM/SIGINT: no child may be started afterwards


class Terminated(Exception):
    def __init__(self, message='terminated', signum=None):
        super().__init__(message)
        self.signum = signum


class BudgetExceeded(Exception):
    def __init__(self, phase, message=None):
        super().__init__(message or 'time budget exhausted during phase "%s"' % phase)
        self.phase = phase


def kill_all():
    with _ACTIVE_LOCK:
        pgids = list(ACTIVE_PGIDS)
    for pg in pgids:
        try:
            os.killpg(pg, signal.SIGKILL)      # only process groups WE started
        except OSError:
            pass


atexit.register(kill_all)


def _on_signal(signum, _frame):
    STOP.set()
    kill_all()
    raise Terminated('terminated by signal %d' % signum, signum)


class Deadline:
    """One monotonic deadline for the whole invocation."""

    def __init__(self, total):
        self.total = total
        self.end = time.monotonic() + total

    def remaining(self, reserve=0.0):
        return self.end - time.monotonic() - reserve

    def expired(self):
        return self.remaining() <= 0


# ---------------------------------------------------------------- tools (resolved once, absolute realpaths)
def resolve_tools():
    out = {}
    for name in TOOL_NAMES:
        found = shutil.which(name)
        out[name] = os.path.realpath(found) if found else None
    return out


def tool_path_env(tools):
    dirs = []
    for name in TOOL_NAMES:
        if tools.get(name):
            d = os.path.dirname(tools[name])
            if d not in dirs:
                dirs.append(d)
    return ':'.join(dirs + ['/usr/bin', '/bin'])


def gate_env(tools):
    env = {k: v for k, v in os.environ.items()
           if k not in ('PYTHONPATH', 'PYTHONSTARTUP', 'PYTHONINSPECT', 'NODE_OPTIONS', 'NODE_PATH', 'PATH')
           and not k.startswith('GIT_')}
    env['PATH'] = tool_path_env(tools)
    return env


def git_env():
    """No GIT_* from the caller except what is set here."""
    return {k: v for k, v in os.environ.items() if not k.startswith('GIT_')} | {
        'GIT_OPTIONAL_LOCKS': '0', 'GIT_NO_REPLACE_OBJECTS': '1'}


def git_run(tools, repo_root, *args, deadline=None):
    timeout = GIT_TIMEOUT_SEC
    if deadline is not None:
        timeout = min(timeout, deadline.remaining())
        if timeout <= 0:
            raise subprocess.TimeoutExpired('git', 0)
    return subprocess.run([tools.get('git') or 'git', '-c', 'core.fsmonitor=false', '-C', str(repo_root), *args],
                          capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, env=git_env())


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


# ---------------------------------------------------------------- context
class BadInput(Exception):
    pass


class Ctx:
    def __init__(self, args, repo_root, deliver, tools=None):
        self.repo_root = repo_root
        self.tools = tools or {n: None for n in TOOL_NAMES}
        p = Path(args.project)
        self.project = (p if p.is_absolute() else self.repo_root / p).resolve()
        self.comp = COMP
        self.deliver = deliver
        self.hash = Hasher()
        self.composer = (self.repo_root / args.composer).resolve()
        self.manifest_sha = None
        cfg = dict(DEFAULT_PATHS)
        explicit = set()
        mp = Path(args.manifest).resolve() if args.manifest else self.project / 'artifacts' / 'finalize.json'
        if args.manifest or mp.is_file():
            data, err = read_json(mp)
            if err or not isinstance(data, dict):
                raise BadInput('manifest %s is %s' % (mp, err or 'not a JSON object'))
            unknown = sorted(set(data) - set(DEFAULT_PATHS))
            if unknown:
                raise BadInput('manifest has unknown keys: %s' % ', '.join(unknown))
            forbidden = sorted(set(data) & FORBIDDEN_OVERRIDES)
            if forbidden:
                raise BadInput('manifest may not override: %s' % ', '.join(forbidden))
            for k, v in data.items():
                if not (isinstance(v, str) and v):
                    raise BadInput('manifest key %s has an invalid value' % k)
                if Path(v).is_absolute() or '..' in Path(v).parts:
                    raise BadInput('manifest key %s: absolute paths and ".." are not allowed (%s)' % (k, v))
                cfg[k] = v
                explicit.add(k)
            self.manifest_sha = sha256_file(mp)
        self.paths = {}
        for k, v in cfg.items():
            self.paths[k] = (self.project / v).resolve()
            if not inside(self.paths[k], self.project):
                raise BadInput('%s resolves outside the project: %s' % (k, self.paths[k]))
        for k in explicit & OPTIONAL_KEYS:
            if not self.paths[k].is_file():
                raise BadInput('manifest sets optional %s but %s does not exist' % (k, self.paths[k]))
        self.reports = self.paths['reports']
        if self.deliver.suffix.lower() != '.mp4':
            raise BadInput('--deliver must be an .mp4 path')
        self.public = self.composer / 'public'          # same convention as qc_layout.mjs / render_episode.mjs
        self.ep = {'vo_end': None, 'total': None, 'asset_dir': None, 'avatar_file': None, 'error': None}
        self.avatar = None
        self.broll_root = None
        self._read_episode()
        if self.ep['asset_dir']:
            self.broll_root = self.public / self.ep['asset_dir'] / 'broll'
            if self.ep['avatar_file']:
                self.avatar = self.public / self.ep['asset_dir'] / self.ep['avatar_file']
        self.word_done = self.paths['word_pages'].parent / 'word_timing.done.json'
        self.extra = {'avatar': self.avatar, 'word_done': self.word_done}

    def _read_episode(self):
        data, err = read_json(self.paths['episode'])
        if err or not isinstance(data, dict):
            self.ep['error'] = 'episode.json is %s' % (err or 'not a JSON object')
            return
        for key, name in (('vo_end', 'voEndSec'), ('total', 'totalDurationSec')):
            v = data.get(name)
            if is_num(v) and v > 0:
                self.ep[key] = float(v)
        for key, name in (('asset_dir', 'assetDir'), ('avatar_file', 'avatarFile')):
            v = data.get(name)
            if isinstance(v, str) and v and '/' not in v and '..' not in v:
                self.ep[key] = v
        if self.ep['vo_end'] is None or self.ep['total'] is None:
            self.ep['error'] = 'episode.json has no valid voEndSec / totalDurationSec'

    def rel(self, p):
        try:
            return Path(p).resolve().relative_to(self.repo_root).as_posix()
        except ValueError:
            return str(Path(p).resolve())

    def receipt_path(self, key, suffix):
        return Path(str(self.paths[key]) + suffix)

    def input_files(self):
        files = [p for p in self.paths.values()] + [p for p in self.extra.values() if p is not None]
        files += [LOCK_FILE, Path(str(self.paths['visual']) + RENDER_RECEIPT_SUFFIX), Path(str(self.paths['final']) + '.mux.json')]
        return files

    def deliver_collision(self):
        """-> message when the deliver path is (a link to / the same file as) any input of the run."""
        target = Path(os.path.realpath(self.deliver))
        for f in self.input_files():
            try:
                same = Path(os.path.realpath(f)) == target or (os.path.exists(f) and os.path.exists(self.deliver)
                                                               and os.path.samefile(f, self.deliver))
            except OSError:
                same = False
            if same:
                return '--deliver resolves to an input file of this run: %s' % self.rel(f)
        return None


# ---------------------------------------------------------------- reports: issue summaries
ISSUE_CODE_KEYS = ('code', 'rule', 'id', 'kind')
ISSUE_TEXT_KEYS = ('detail', 'message', 'reason')
ISSUE_TIME_KEYS = ('startSec', 'start_sec', 't', 'sec', 'time', 'start', 'at')
ISSUE_COMMAND_KEYS = ('command', 'rerun', 'cmd')
DETAIL_MAX = 300            # free-text details only; a command is never shortened
OCCURRENCES_SHOWN = 3


def _scalar(v):
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, float):
        return ('%.2f' % v).rstrip('0').rstrip('.')
    if isinstance(v, (int, str)):
        return str(v) if not isinstance(v, str) else (v if len(v) <= 60 else v[:57] + '...')
    return None


def _occurrence(it, skip):
    """One issue without detail text as a compact `@12.3s key=value ...` (scalar fields only, the time first)."""
    parts = []
    t_key = next((k for k in ISSUE_TIME_KEYS if isinstance(it.get(k), (int, float)) and not isinstance(it.get(k), bool)), None)
    if t_key:
        parts.append('@%ss' % _scalar(it[t_key]))
    for k, v in it.items():
        if k in skip or k == t_key or k in ISSUE_COMMAND_KEYS:
            continue
        sv = _scalar(v)
        if sv is not None:
            parts.append('%s=%s' % (k, sv))
    return ' '.join(parts)


def summarize_issues(data, limit=3):
    """Console lines for the issues of a report.  An issue with a detail text prints `code: detail (@where)`; issues without
    one are grouped by their code/kind and print the count plus the first few occurrences with all their scalar fields
    (time and measured values), so a bare `- dips` is never printed.  Commands inside an issue are printed in full."""
    out = []
    if not isinstance(data, dict):
        return out
    for key in ('issues', 'errors', 'dips', 'problems'):
        items = data.get(key)
        if not isinstance(items, list):
            continue
        groups = {}
        for it in items:
            if not isinstance(it, dict):
                out.append(str(it)[:DETAIL_MAX])
                continue
            code = next((it[k] for k in ISSUE_CODE_KEYS if it.get(k)), key)
            detail = next((it[k] for k in ISSUE_TEXT_KEYS if it.get(k)), '')
            for ck in ISSUE_COMMAND_KEYS:
                if isinstance(it.get(ck), str) and it[ck]:
                    out.append('rerun (copy this whole line): %s' % it[ck])
            if detail:
                text = '%s: %s' % (code, str(detail)[:DETAIL_MAX])
                where = it.get('path') or it.get('beat') or it.get('t') or it.get('start')
                if where not in (None, ''):
                    text += ' (@%s)' % (where,)
                out.append(text)
            else:
                groups.setdefault(str(code), []).append(it)
        for code, its in groups.items():
            skip = set(ISSUE_CODE_KEYS) | set(ISSUE_TEXT_KEYS)
            shown = ['[%s]' % _occurrence(it, skip) for it in its[:OCCURRENCES_SHOWN]]
            more = '' if len(its) <= OCCURRENCES_SHOWN else ' ... +%d more' % (len(its) - OCCURRENCES_SHOWN)
            out.append('%s x%d, first %d: %s%s' % (code, len(its), len(shown), ' '.join(shown), more))
    if not out and isinstance(data.get('error'), str):
        out.append('error: ' + data['error'][:DETAIL_MAX])
    return out[:max(limit, 1)] if limit else out


# ---------------------------------------------------------------- fresh gates
def final_pixels_validator(report, ctx):
    probs = []
    if report.get('videoSha256') != ctx.hash(ctx.paths['final']):
        probs.append((2, 'final-pixels report is bound to a different video (videoSha256 mismatch)'))
    if report.get('certified') is not True:
        probs.append((1, 'final-pixels report is not certified (certified != true)'))
    return probs


VALIDATORS = {'final_pixels': final_pixels_validator}
GATE_BY_NAME = {g['name']: g for g in GATES}


def gate_report_path(name, ctx):
    return Path(GATE_BY_NAME[name]['report'].format(reports=ctx.reports))


def input_path(ctx, key):
    return ctx.extra[key] if key in ctx.extra else ctx.paths[key]


def dependency_block(gate, deps):
    """-> (class, message) when a gate this one waits for did not pass, else None."""
    for name in gate.get('after', []):
        rec = (deps or {}).get(name)
        if rec is None:
            return 4, 'blocked: %s did not run' % name
        if rec['status'] != 'pass':
            return (rec['cls'] or 4), 'blocked: the %s gate did not pass (%s); its report is needed first' % (name, rec['status'])
    return None


def build_command(gate, ctx, deps=None):
    """Return (argv-without-interpreter, report path, input paths, problems).  deps: {gate name: finished record};
    None while only the inputs are being collected (dependent reports are added by run_gate)."""
    report = Path(gate['report'].format(reports=ctx.reports))
    ph = {k: str(v) for k, v in ctx.paths.items()}
    ph.update(report=str(report), reports=str(ctx.reports), composer=str(ctx.composer), skill=str(SKILL_DIR),
              public=str(ctx.public), avatar='' if ctx.avatar is None else str(ctx.avatar),
              broll_root='' if ctx.broll_root is None else str(ctx.broll_root),
              vo_end='' if ctx.ep['vo_end'] is None else repr(ctx.ep['vo_end']))
    problems, inputs = [], []
    for key in gate['inputs']:
        path = input_path(ctx, key)
        if path is None:
            problems.append('required input %s missing: episode.json has no assetDir/avatarFile' % key)
        elif not path.is_file():
            problems.append('required input %s missing: %s' % (key, ctx.rel(path)))
        else:
            inputs.append(path)
    for need in gate.get('needs', []):
        if ctx.ep.get(need) is None:
            problems.append('%s unavailable: %s' % (need, ctx.ep['error'] or 'not in episode.json'))
    argv = [a.format(**ph) for a in gate.get('args', [])]
    for flag, key in gate.get('optional_args', []):
        if ctx.paths[key].is_file():
            argv += [flag, str(ctx.paths[key])]
            inputs.append(ctx.paths[key])
    for name in gate.get('need_dirs', []):
        d = getattr(ctx, name)
        if d is None or not d.is_dir():
            problems.append('%s is not a directory: %s' % (name, 'unknown (no assetDir)' if d is None else ctx.rel(d)))
    if deps is not None:
        for flag, name in gate.get('dep_args', []):
            dep_report = gate_report_path(name, ctx)
            if not dep_report.is_file():
                problems.append('blocked: the %s gate wrote no report at %s' % (name, ctx.rel(dep_report)))
            else:
                argv += [flag, str(dep_report)]
                inputs.append(dep_report)
    return argv, report, inputs, problems


def record(gate, status, cls, reason, report=None, code=None, seconds=0.0, inputs=None, out='', kind='fresh',
           extra=None, command=None, issues=None):
    r = {'name': gate['name'], 'kind': kind, 'required': gate.get('required', True), 'status': status,
         'cls': cls, 'exit': code, 'seconds': round(seconds, 2), 'report': report, 'reason': reason,
         'inputs': inputs or {}, 'output_tail': tail(out)}
    if command:
        r['command'] = command
    if issues:
        r['issues'] = issues
    if extra:
        r.update(extra)
    return r


def class_for_exit(gate, code):
    if code < 0:
        return 4                                   # killed by a signal: infrastructure, not quality
    mapping = {1: 1, 2: 2, 4: 4}
    mapping.update(gate.get('exit_classes', {}))
    return mapping.get(code, 4)                    # unknown exit code: infrastructure


def spawn(cmd, ctx, limit, env):
    """Run one child in its own process group (killed with its leftovers).  Nothing is started once STOP is set.
    -> dict(code, stdout bytes, stderr str, timed_out, cancelled, seconds, start_ns)"""
    res = {'code': None, 'stdout': b'', 'stderr': '', 'timed_out': False, 'cancelled': False, 'seconds': 0.0,
           'start_ns': time.time_ns()}
    if STOP.is_set():
        res['cancelled'] = True
        return res
    t0 = time.monotonic()
    with tempfile.TemporaryFile() as fo, tempfile.TemporaryFile() as fe:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe, env=env, cwd=str(ctx.repo_root),
                                start_new_session=True)
        with _ACTIVE_LOCK:
            ACTIVE_PGIDS.add(proc.pid)
        try:
            if STOP.is_set():                         # terminated between the check and the registration
                res['cancelled'] = True
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    pass
            try:
                proc.wait(timeout=limit)
            except subprocess.TimeoutExpired:
                res['timed_out'] = True
                try:
                    os.killpg(proc.pid, signal.SIGKILL)    # our own process group only
                except OSError:
                    pass
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            try:
                os.killpg(proc.pid, signal.SIGKILL)        # leftovers of a gate that exited (background children)
            except OSError:
                pass
        finally:
            with _ACTIVE_LOCK:
                ACTIVE_PGIDS.discard(proc.pid)
        fo.seek(0)
        res['stdout'] = fo.read(50_000_000)
        fe.seek(0)
        res['stderr'] = fe.read(5_000_000).decode('utf-8', 'replace')
    res['seconds'] = time.monotonic() - t0
    res['code'] = proc.returncode
    if STOP.is_set():
        res['cancelled'] = True
    return res


def interps_needed(gate):
    scripts = gate.get('scripts') or [gate['script']]
    return {'python' if s.endswith('.py') else 'node' for s in scripts}


def exe_for(ctx, script_name):
    path = str(SCRIPTS_DIR / script_name)
    if script_name.endswith('.py'):
        return [sys.executable, '-B', '-E', '-s', path]
    return [ctx.tools.get('node') or 'node', path]


def step_problem(gate, base, res, label, limit):
    """A failed child of a runner gate -> record, or None when it exited 0."""
    out = (res['stdout'].decode('utf-8', 'replace')[-3000:] + ('\n' if res['stdout'] and res['stderr'] else '') + res['stderr'])
    b = dict(base, seconds=res['seconds'], out=out)
    if res['cancelled']:
        return record(gate, 'crashed', 4, 'cancelled: finalize was terminated', **dict(b, code=None))
    if res['timed_out']:
        return record(gate, 'timeout', 4, 'timeout: %s exceeded the %.0fs limit of the gate' % (label, limit), **dict(b, code=None))
    code = res['code']
    if code < 0:
        return record(gate, 'crashed', 4, '%s was killed by signal %d' % (label, -code), **dict(b, code=code))
    if code == 0:
        return None
    if code in (1, 2):
        return record(gate, STATUS_BY_CLASS[code], code, '%s exited with code %d' % (label, code), **dict(b, code=code))
    return record(gate, 'crashed', 4, '%s exited with unexpected code %d' % (label, code), **dict(b, code=code))


def finish_runner(gate, ctx, base, report, data, fail_reason, issues=None, cls=1):
    """The runner gate writes its own report (finalize is the author; the tools only wrote their outputs)."""
    write_json_atomic(report, data)
    b = dict(base)
    b['inputs'] = dict(base['inputs'])
    b['inputs'][ctx.rel(report)] = ctx.hash(report)
    if data.get('pass') is True:
        return record(gate, 'pass', 0, '', **b)
    return record(gate, STATUS_BY_CLASS[cls], cls, fail_reason, issues=issues, **b)


def runner_script(gate, ctx, base, report, limit, env):
    """srt_to_script.py --strict re-run; the result must be byte-identical to artifacts/script.txt."""
    P = ctx.paths
    out = ctx.reports / 'script.rebuilt.txt'
    remove_quiet(out)
    cmd = exe_for(ctx, 'srt_to_script.py') + ['--srt', str(P['srt']), '--script', str(P['source_script']), '--strict', '--out', str(out)]
    base['command'] = shlex.join(cmd)
    res = spawn(cmd, ctx, limit, env)
    bad = step_problem(gate, base, res, 'srt_to_script.py', limit)
    if bad:
        if res['code'] == 1 and not res['timed_out'] and not res['cancelled']:
            bad['reason'] = ('the SRT text differs from the source script (srt_to_script.py --strict exit 1): the voice-over '
                             'is not the script; fix the source or the audio, do not edit script.txt')
        return bad
    if not out.is_file():
        return record(gate, 'stale', 2, 'srt_to_script.py exited 0 but wrote no output', **base)
    equal = out.read_bytes() == P['script'].read_bytes()
    data = {'schema': 'yt-news-v4-script-rebuild', 'version': 1, 'pass': equal, 'equal': equal,
            'rebuilt': ctx.rel(out), 'rebuiltSha256': ctx.hash(out), 'script': ctx.rel(P['script']),
            'scriptSha256': ctx.hash(P['script'])}
    msg = ('%s is not what srt_to_script.py --strict rebuilds from %s + %s (see %s): regenerate it with that command, never '
           'edit it by hand' % (ctx.rel(P['script']), ctx.rel(P['srt']), ctx.rel(P['source_script']), ctx.rel(out)))
    return finish_runner(gate, ctx, dict(base, seconds=res['seconds'], code=0), report, data, msg)


def check_caption_options(ctx):
    """caption-options.json: ONLY endTime (== voEndSec within 0.01 s) and optionally lexicalOverrides (list of strings)."""
    data, err = read_json(ctx.paths['caption_options'])
    if err or not isinstance(data, dict):
        return ['caption-options.json is %s' % (err or 'not a JSON object')], {}
    p = []
    extra_keys = sorted(set(data) - {'endTime', 'lexicalOverrides'})
    if extra_keys:
        p.append('caption-options.json may only contain endTime and lexicalOverrides (found: %s)' % ', '.join(extra_keys))
    end = data.get('endTime')
    if not is_num(end):
        p.append('caption-options.json endTime is missing or not a number')
    elif ctx.ep['vo_end'] is not None and abs(end - ctx.ep['vo_end']) > 0.01 + 1e-9:
        p.append('caption-options.json endTime %s differs from episode voEndSec %s by more than 0.01 s' % (end, ctx.ep['vo_end']))
    lex = data.get('lexicalOverrides')
    if 'lexicalOverrides' in data and not (isinstance(lex, list) and all(isinstance(x, str) and x for x in lex)):
        p.append('caption-options.json lexicalOverrides must be a list of non-empty strings')
    return p, data


def check_word_done(ctx):
    """word_timing.done.json must bind caption_pages.json: output_sha256 == sha256(caption_pages.json)."""
    data, err = read_json(ctx.word_done)
    if err or not isinstance(data, dict):
        return ['%s is %s (word_timing.sh writes it next to caption_pages.json)' % (ctx.rel(ctx.word_done), err or 'not a JSON object')], {}
    want = data.get('output_sha256')
    if not valid_sha(want):
        return ['%s has no output_sha256' % ctx.rel(ctx.word_done)], data
    if ctx.hash(ctx.paths['word_pages']) != want.lower():
        return ['%s does not match output_sha256 of %s: caption_pages.json was edited or replaced after word_timing.sh wrote it'
                % (ctx.rel(ctx.paths['word_pages']), ctx.rel(ctx.word_done))], data
    return [], data


def runner_derived(gate, ctx, base, report, limit, env):
    """Re-run the commands of SKILL step 2 from the raw word timing; every artifact must be byte-identical."""
    P = ctx.paths
    ddir = ctx.reports / 'derived'
    shutil.rmtree(ddir, ignore_errors=True)
    ddir.mkdir(parents=True, exist_ok=True)
    problems, opts = check_caption_options(ctx)
    p2, done = check_word_done(ctx)
    problems += p2
    outs = {'words': ddir / 'words_by_line.txt', 'line_starts': ddir / 'line_starts.json', 'captions': ddir / 'caption-joined.json'}
    steps = [
        ('words_by_line.py', [str(P['word_pages']), str(P['script'])], outs['words']),
        ('line_starts.py', ['--pages', str(P['word_pages']), '--script', str(P['script']), '--out', str(outs['line_starts'])], None),
        ('caption_join.mjs', ['--tokens', str(P['word_pages']), '--script', str(P['script']), '--options', str(P['caption_options']),
                              '--out', str(outs['captions'])], None),
    ]
    base['command'] = ' && '.join(shlex.join(exe_for(ctx, n) + a) for n, a, _ in steps)
    data = {'schema': 'yt-news-v4-derived-check', 'version': 1, 'pass': False, 'captionOptions': opts,
            'wordTimingDone': {k: done.get(k) for k in ('key', 'model', 'output_sha256')} if isinstance(done, dict) else None,
            'comparisons': []}
    if problems:
        data['problems'] = problems
        return finish_runner(gate, ctx, base, report, data, '; '.join(problems), issues=problems)
    t_end = time.monotonic() + limit
    total = 0.0
    for name, args, stdout_to in steps:
        left = t_end - time.monotonic()
        if left < 1:
            return record(gate, 'timeout', 4, 'timeout: the derived gate exceeded its %.0fs limit' % limit, **dict(base, seconds=total))
        res = spawn(exe_for(ctx, name) + args, ctx, left, env)
        total += res['seconds']
        bad = step_problem(gate, base, res, name, limit)
        if bad:
            if bad['cls'] == 1:
                bad['reason'] += (' (the raw word timing %s does not produce the artifacts: regenerate them, never hand-edit)'
                                  % ctx.rel(P['word_pages']))
            return bad
        if stdout_to is not None:
            stdout_to.write_bytes(res['stdout'])
    mism = []
    for key, derived in outs.items():
        art = P[key]
        got = derived.read_bytes() if derived.is_file() else None
        equal = got is not None and got == art.read_bytes()
        data['comparisons'].append({'derived': ctx.rel(derived), 'artifact': ctx.rel(art), 'equal': equal,
                                    'derivedSha256': ctx.hash(derived) if derived.is_file() else None, 'artifactSha256': ctx.hash(art)})
        if not equal:
            mism.append('%s is not byte-identical to what the step-2 command derives from %s (%s)'
                        % (ctx.rel(art), ctx.rel(P['word_pages']), ctx.rel(derived)))
    data['pass'] = not mism
    if mism:
        data['problems'] = mism
    return finish_runner(gate, ctx, dict(base, seconds=total, code=0), report, data, '; '.join(mism), issues=mism)


RUNNERS = {'script': runner_script, 'derived': runner_derived}


def run_gate(gate, ctx, inputs, deadline, env, deps=None):
    """deadline: absolute time.monotonic() value the gates must be finished by."""
    deps = deps or {}
    argv, report, dep_paths, problems = build_command(gate, ctx, deps)
    inputs = dict(inputs)
    for path in dep_paths:
        inputs.setdefault(ctx.rel(path), ctx.hash(path))
    rel_report = ctx.rel(report)
    runner = gate.get('runner')
    scripts = gate.get('scripts') or [gate['script']]
    if runner:
        cmd = ['<%s>' % gate['name']]
        command = ' + '.join(scripts)
    else:
        cmd = exe_for(ctx, gate['script']) + argv
        command = shlex.join(cmd)
    base = dict(report=rel_report, inputs=inputs, command=command)
    for name in scripts:
        if not (SCRIPTS_DIR / name).is_file():
            return record(gate, 'missing', 4, 'gate script missing: %s' % name, **base)
    for interp in sorted(interps_needed(gate)):
        if interp != 'python' and not ctx.tools.get(interp):
            return record(gate, 'missing', 4, '%s not found on PATH' % interp, **base)
    block = dependency_block(gate, deps)
    if block:
        return record(gate, 'blocked', block[0], block[1], **base)
    if problems:
        return record(gate, 'bad-input', 2, '; '.join(problems), **base)
    report.parent.mkdir(parents=True, exist_ok=True)
    if report.exists():
        report.unlink()           # a report can only exist if THIS run wrote it
    remaining = deadline - time.monotonic()
    limit = min(gate['limit'], remaining)
    if limit < 1:
        return record(gate, 'timeout', 4, 'finalize time budget (%ds, phase gates) exhausted before the gate started' % TOTAL_BUDGET_SEC, **base)
    if STOP.is_set():
        return record(gate, 'crashed', 4, 'cancelled: finalize was terminated', **base)
    if runner:
        return RUNNERS[runner](gate, ctx, base, report, limit, env)
    res = spawn(cmd, ctx, limit, env)
    start_ns = res['start_ns']
    stdout = res['stdout'].decode('utf-8', 'replace')
    secs, code = res['seconds'], res['code']
    out = (stdout + ('\n' if stdout and res['stderr'] else '') + res['stderr'])
    base.update(code=code, seconds=secs, out=out)
    if res['cancelled']:
        return record(gate, 'crashed', 4, 'cancelled: finalize was terminated', **{**base, 'code': None})
    if res['timed_out']:
        return record(gate, 'timeout', 4, 'timeout: gate exceeded its %.0fs limit' % limit, **{**base, 'code': None})
    if gate.get('stdout_report'):
        try:
            parsed = json.loads(stdout)
            if isinstance(parsed, dict):
                write_json_atomic(report, parsed)
        except (ValueError, OSError):
            pass
    data = None
    if report.is_file() and report.stat().st_mtime_ns >= start_ns - STALE_TOLERANCE_NS:
        data, _err = read_json(report)
    issues = summarize_issues(data)
    base['issues'] = issues
    if code != 0:
        cls = class_for_exit(gate, code)
        if code < 0:
            return record(gate, 'crashed', 4, 'gate was killed by signal %d' % -code, **base)
        if code in (1, 2, 4) or code in gate.get('exit_classes', {}):
            return record(gate, STATUS_BY_CLASS[cls], cls, 'gate exited with code %d' % code, **base)
        return record(gate, 'crashed', 4, 'gate exited with unexpected code %d' % code, **base)
    # exit 0: the report must exist, be fresh, parse, and say pass:true
    if not report.is_file():
        return record(gate, 'stale', 2, 'exit 0 but no report was written at %s' % rel_report, **base)
    if report.stat().st_mtime_ns < start_ns - STALE_TOLERANCE_NS:
        return record(gate, 'stale', 2, 'report is older than this run (stale): %s' % rel_report, **base)
    if not isinstance(data, dict):
        return record(gate, 'stale', 2, 'report unreadable or not a JSON object: %s' % rel_report, **base)
    if data.get(gate.get('pass_key', 'pass')) is not True:
        return record(gate, 'fail', 1, 'report says %s != true' % gate.get('pass_key', 'pass'), **base)
    if gate.get('validate'):
        bad = VALIDATORS[gate['validate']](data, ctx)
        if bad:
            cls = 2 if any(c == 2 for c, _ in bad) else 1
            return record(gate, STATUS_BY_CLASS[cls], cls, '; '.join(m for _, m in bad), **base)
    base['inputs'] = dict(inputs)
    base['inputs'][rel_report] = ctx.hash(report)
    return record(gate, 'pass', 0, '', **base)


def purge_pycache(skill_dir):
    for dirpath, dirnames, _ in os.walk(skill_dir):
        for d in list(dirnames):
            if d == '__pycache__':
                shutil.rmtree(os.path.join(dirpath, d), ignore_errors=True)
                dirnames.remove(d)


# ---------------------------------------------------------------- verified reports
def time_left(deadline, cap):
    """Seconds a post-verification subprocess may use: min(cap, time left), or None when less than 1 s is left."""
    left = deadline.remaining()
    return None if left < 1 else min(cap, left)


BUDGET_MSG = 'time budget (%ds) exhausted during phase "post-verification"' % TOTAL_BUDGET_SEC


def node_manifest_hash(manifest_path, env, ctx, deadline):
    """manifestHash() computed by the OTHER team's JS (never re-implemented). -> (hash|None, error, class)"""
    qm = SCRIPTS_DIR / QC_MANIFEST_SCRIPT
    node = ctx.tools.get('node')
    if not qm.is_file():
        return None, '%s is missing from the skill (cannot recompute manifestHash)' % QC_MANIFEST_SCRIPT, 4
    if not node:
        return None, 'node not found on PATH (cannot recompute manifestHash)', 4
    timeout = time_left(deadline, 30)
    if timeout is None:
        return None, BUDGET_MSG, 4
    code = ("import {pathToFileURL} from 'node:url'; import fs from 'node:fs';"
            "const m = await import(pathToFileURL(process.argv[1]).href);"
            "console.log(m.manifestHash(JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))));")
    try:
        r = subprocess.run([node, '--input-type=module', '-e', code, str(qm), str(manifest_path)], capture_output=True,
                           text=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, 'manifestHash computation failed: %s' % e, 4
    h = r.stdout.strip()
    if r.returncode != 0 or not valid_sha(h):
        return None, 'manifestHash computation failed (exit %d): %s' % (r.returncode, tail(r.stderr, 300)), 4
    return h.lower(), None, 0


def verify_layout(report_path, ctx, env, deadline):
    """-> (problems, tool_class, info, inputs).  tool_class 4 when the hash helper could not run."""
    report_path = Path(report_path)
    data, err = read_json(report_path)
    if err or not isinstance(data, dict):
        return ['layout report %s: %s' % (ctx.rel(report_path), err or 'not a JSON object')], 0, {}, {}
    p, info, inputs, tool = [], {}, {}, 0
    if data.get('schema') != LAYOUT_REPORT_SCHEMA:
        p.append('layout report schema is %r' % data.get('schema'))
    if data.get('version') != LAYOUT_REPORT_VERSION:
        p.append('layout report version is %r, expected %d' % (data.get('version'), LAYOUT_REPORT_VERSION))
    if data.get('status') != 'finished':
        p.append('layout status is %r, not "finished"' % data.get('status'))
    if data.get('pass') is not True:
        p.append('layout report pass != true')
    if data.get('complete') is not True:
        p.append('layout report is not complete')
    rc, fc = data.get('requestedCount'), data.get('fullPlanCount')
    if not (is_int(rc) and is_int(fc) and fc > 0 and rc == fc):
        p.append('layout requestedCount (%r) != fullPlanCount (%r)' % (rc, fc))
    if data.get('compositionId') != COMP:
        p.append('layout compositionId %r != %r' % (data.get('compositionId'), COMP))
    run_id, mhash = data.get('runId'), data.get('manifestHash')
    if not (isinstance(run_id, str) and run_id):
        p.append('layout report has no runId')
    if not valid_sha(mhash):
        p.append('layout report has no valid manifestHash')
    info = {'runId': run_id, 'manifestHash': mhash, 'reportSha256': ctx.hash(report_path), 'reusedFrames': data.get('reusedFrames')}
    inputs[ctx.rel(report_path)] = info['reportSha256']
    mp = data.get('manifestPath')
    if not (isinstance(mp, str) and mp):
        p.append('layout report has no manifestPath')
        return p, tool, info, inputs
    layout_dir = report_path.parent.resolve()
    mpath = Path(mp)
    mpath = (mpath if mpath.is_absolute() else layout_dir / mpath).resolve()
    if not inside(mpath, layout_dir):
        p.append('layout manifestPath is outside %s: %s' % (ctx.rel(layout_dir), mp))
        return p, tool, info, inputs
    manifest, merr = read_json(mpath)
    if merr or not isinstance(manifest, dict):
        p.append('layout run manifest %s: %s' % (ctx.rel(mpath), merr or 'not a JSON object'))
        return p, tool, info, inputs
    inputs[ctx.rel(mpath)] = ctx.hash(mpath)
    if manifest.get('schema') != RUN_MANIFEST_SCHEMA:
        p.append('run manifest schema is %r' % manifest.get('schema'))
    if manifest.get('compositionId') != COMP:
        p.append('run manifest compositionId is %r' % manifest.get('compositionId'))
    if manifest.get('runId') != run_id:
        p.append('run manifest runId differs from the report')
    hashes = manifest.get('sourceHashes')
    if not isinstance(hashes, dict):
        p.append('run manifest has no sourceHashes')
    else:
        for key, path in ((MANIFEST_KEY_EPISODE, ctx.paths['episode']), (MANIFEST_KEY_CAPTIONS, ctx.paths['captions']),
                          (MANIFEST_KEY_LOCK, LOCK_FILE), (ENGINE_REL, ctx.composer / ENGINE_REL),
                          (ENTRY_REL, ctx.composer / ENTRY_REL)):
            want = hashes.get(key)
            if not valid_sha(want):
                p.append('run manifest sourceHashes[%s] missing' % key)
            elif not Path(path).is_file() or ctx.hash(path) != want.lower():
                p.append('layout was run on a different %s (sourceHashes[%s] differs from the current file)' % (key, key))
    h, herr, tool = node_manifest_hash(mpath, env, ctx, deadline)
    if herr:
        p.append(herr)
    elif valid_sha(mhash) and h != mhash.lower():
        p.append('run manifest hash %s does not match report.manifestHash' % h[:12])
    return p, tool, info, inputs


def parse_fps(text):
    try:
        a, _, b = str(text).partition('/')
        return float(a) / float(b or 1)
    except (ValueError, ZeroDivisionError):
        return None


def probe_video(ctx, path, env, deadline):
    """ffprobe of the first video stream WITHOUT decoding (packet count). -> (info|None, error, class)"""
    ffprobe = ctx.tools.get('ffprobe')
    if not ffprobe:
        return None, 'ffprobe not found', 4
    timeout = time_left(deadline, 60)
    if timeout is None:
        return None, BUDGET_MSG, 4
    try:
        r = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-count_packets', '-show_entries',
                            'stream=width,height,r_frame_rate,nb_read_packets,pix_fmt,color_space,color_range',
                            '-of', 'json', str(path)],
                           capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, env=env)
        s = json.loads(r.stdout)['streams'][0]
        info = {'width': int(s['width']), 'height': int(s['height']), 'fps': parse_fps(s['r_frame_rate']),
                'frames': int(s['nb_read_packets']), 'pix_fmt': s.get('pix_fmt'), 'color_space': s.get('color_space'),
                'color_range': s.get('color_range')}
    except subprocess.TimeoutExpired:
        return None, 'ffprobe timed out on %s' % ctx.rel(path), 4
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None, 'cannot probe the video stream of %s' % ctx.rel(path), 2
    if info['fps'] is None:
        return None, 'cannot read the frame rate of %s' % ctx.rel(path), 2
    return info, None, 0


def verify_video_format(ctx, probe_visual, probe_final):
    """The V4 render is yuv420p; mux_av.sh only copies it, so a different pix_fmt means the final was re-encoded."""
    p = []
    for label, path, probe in (('visual', ctx.paths['visual'], probe_visual), ('final', ctx.paths['final'], probe_final)):
        if probe is not None and probe['pix_fmt'] != EXPECTED_PIX_FMT:
            p.append('%s pix_fmt is %r, not %s: the final must not be re-encoded (mux_av.sh copies the visual stream as it was rendered)'
                     % (ctx.rel(path), probe['pix_fmt'], EXPECTED_PIX_FMT))
    return p


def verify_render_receipt(receipt_path, ctx, layout_info, probe=None):
    """Real contract (render_episode.mjs RECEIPT_FIELDS). -> (problems, info).  probe: ffprobe info of the visual file."""
    data, err = read_json(receipt_path)
    if err or not isinstance(data, dict):
        return ['render receipt %s: %s' % (ctx.rel(receipt_path), err or 'not a JSON object')], {}
    p = []
    h = ctx.hash
    visual = ctx.paths['visual']
    if data.get('schema') != RENDER_RECEIPT_SCHEMA:
        p.append('render receipt schema is %r' % data.get('schema'))
    if data.get('schemaVersion') != 1:
        p.append('render receipt schemaVersion is %r' % data.get('schemaVersion'))
    if data.get('compositionId') != COMP:
        p.append('render receipt compositionId is %r' % data.get('compositionId'))
    if data.get('draft') is not False:
        p.append('render receipt is a draft (or draft flag missing)')
    if data.get('hasAudio') is not False:
        p.append('render receipt hasAudio is not false')
    for key, path, label in (('outputSha256', visual, 'visual render'), ('episodeJsonSha256', ctx.paths['episode'], 'episode.json'),
                             ('captionsJsonSha256', ctx.paths['captions'], 'captions')):
        v = data.get(key)
        if not valid_sha(v):
            p.append('render receipt %s missing' % key)
        elif not Path(path).is_file() or h(path) != v.lower():
            p.append('render receipt %s does not match the current %s (stale render)' % (key, label))
    lock = data.get('gatesLockSha256')
    if not valid_sha(lock):
        p.append('render receipt gatesLockSha256 is null/invalid (render ran without a lock)')
    elif not LOCK_FILE.is_file() or h(LOCK_FILE) != lock.lower():
        p.append('render receipt gatesLockSha256 differs from the current gates.lock.json')
    for key, rel in (('engineSha256', ENGINE_REL), ('entrySha256', ENTRY_REL)):
        v, f = data.get(key), ctx.composer / rel
        if not valid_sha(v):
            p.append('render receipt %s missing' % key)
        elif not f.is_file() or h(f) != v.lower():
            p.append('render receipt %s does not match the current composer %s (rendered with another engine/entry)' % (key, rel))
    closure = data.get('entryClosure')
    if not (isinstance(closure, dict) and closure):
        p.append('render receipt entryClosure missing')
    else:
        for rel, v in sorted(closure.items()):
            f = (ctx.composer / rel) if isinstance(rel, str) and rel.startswith('src/') and '..' not in Path(rel).parts else None
            if f is None or not valid_sha(v):
                p.append('render receipt entryClosure has a bad entry %r' % (rel,))
            elif not f.is_file() or h(f) != v.lower():
                p.append('render receipt entryClosure[%s] does not match the current composer file' % rel)
        for rel in (ENGINE_REL, ENTRY_REL):
            if rel not in closure:
                p.append('render receipt entryClosure does not list %s' % rel)
    if layout_info.get('manifestHash') and (data.get('gateManifestHash') or '').lower() != str(layout_info['manifestHash']).lower():
        p.append('render receipt gateManifestHash differs from the layout report manifestHash')
    if layout_info.get('runId') and data.get('gateRunId') != layout_info['runId']:
        p.append('render receipt gateRunId differs from the layout report runId')
    if probe is not None:
        for key in ('width', 'height'):
            if data.get(key) != probe[key]:
                p.append('render receipt %s %r does not match the visual file (%d)' % (key, data.get(key), probe[key]))
        if not (is_num(data.get('fps')) and abs(data['fps'] - probe['fps']) < 1e-3):
            p.append('render receipt fps %r does not match the visual file (%s)' % (data.get('fps'), round(probe['fps'], 3)))
        if data.get('frameCount') != probe['frames']:
            p.append('render receipt frameCount %r does not match the visual file (%d frames)' % (data.get('frameCount'), probe['frames']))
    return p, {'renderId': data.get('renderId'), 'receiptSha256': h(receipt_path)}


MUSIC_SCHEMA = 'yt-news-v4-music-source'


def verify_mux_receipt(receipt_path, ctx):
    data, err = read_json(receipt_path)
    if err or not isinstance(data, dict):
        stem = ctx.paths['final'].with_suffix('')
        return ['mux receipt %s: %s (mux_av.sh writes it only after the loudness check passes; see %s.audio/final.json)'
                % (ctx.rel(receipt_path), err or 'not a JSON object', ctx.rel(stem))], {}
    p, info = [], {'receiptSha256': ctx.hash(receipt_path)}
    if data.get('schema') != 'yt-news-v4-mux-receipt':
        p.append('mux receipt has the wrong schema')
    avatar = ctx.avatar
    if avatar is None:
        p.append('episode.json has no assetDir/avatarFile; cannot bind the avatar')
    bed = data.get('bed')
    bed_path = Path(bed['path']) if isinstance(bed, dict) and isinstance(bed.get('path'), str) and bed['path'] else None
    for key, path in (('visual', ctx.paths['visual']), ('final', ctx.paths['final']), ('avatar', avatar), ('bed', bed_path)):
        if path is None:
            if key == 'bed':
                p.append('mux receipt bed.path missing')
            continue
        v = data.get(key)
        if not (isinstance(v, dict) and valid_sha(v.get('sha256'))):
            p.append('mux receipt %s.sha256 missing' % key)
        elif not Path(path).is_file() or ctx.hash(path) != v['sha256'].lower():
            p.append('mux receipt %s.sha256 does not match the current %s' % (key, ctx.rel(path)))
    if bed_path is not None and bed_path.is_file():
        sidecar = Path(str(bed_path) + '.source.json')
        src, serr = read_json(sidecar)
        bed_sha = ctx.hash(bed_path)
        if serr or not isinstance(src, dict):
            p.append('music bed has no fetch record: %s is %s' % (ctx.rel(sidecar), serr or 'not a JSON object'))
        elif src.get('schema') != MUSIC_SCHEMA:
            p.append('music bed has no fetch record: %s schema is %r' % (ctx.rel(sidecar), src.get('schema')))
        elif not (valid_sha(src.get('sha256')) and src['sha256'].lower() == bed_sha):
            p.append('music bed has no fetch record: %s sha256 does not match %s' % (ctx.rel(sidecar), ctx.rel(bed_path)))
        else:
            info['music'] = {k: src.get(k) for k in ('provider', 'track_id', 'track_title', 'url')}
            info['music']['sidecar'] = {'path': ctx.rel(sidecar), 'sha256': ctx.hash(sidecar)}
    return p, info


def stream_hash(ctx, path, env, deadline):
    """sha256 of the video packet stream: ffmpeg -c copy -f streamhash. -> (line|None, error, class)"""
    ffmpeg = ctx.tools.get('ffmpeg')
    if not ffmpeg:
        return None, 'ffmpeg not found', 4
    timeout = time_left(deadline, 60)
    if timeout is None:
        return None, BUDGET_MSG, 4
    try:
        r = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-i', str(path), '-map', '0:v:0', '-c', 'copy', '-f', 'streamhash',
                            '-hash', 'sha256', '-'], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        return None, 'ffmpeg streamhash timed out on %s' % ctx.rel(path), 4
    except OSError as e:
        return None, 'ffmpeg failed: %s' % e, 4
    lines = [x.strip() for x in r.stdout.splitlines() if x.strip().startswith('0,v,SHA256=')]
    if r.returncode != 0 or len(lines) != 1:
        return None, 'cannot hash the video stream of %s: %s' % (ctx.rel(path), tail(r.stderr, 200)), 2
    return lines[0], None, 0


def verify_mux_video(ctx, env, deadline):
    """mux_av.sh stream-copies the video (-c:v copy): final.mp4 must carry exactly the packets of visual.mp4."""
    a, err, cls = stream_hash(ctx, ctx.paths['visual'], env, deadline)
    if err:
        return [err], cls, {}
    b, err, cls = stream_hash(ctx, ctx.paths['final'], env, deadline)
    if err:
        return [err], cls, {}
    info = {'visualStream': a, 'finalStream': b}
    if a != b:
        return ['the video stream of %s differs from %s (mux_av.sh must only copy it): the final was not made from this visual'
                % (ctx.rel(ctx.paths['final']), ctx.rel(ctx.paths['visual']))], 2, info
    return [], 0, info


def verify_duration(ctx, env, deadline):
    final, total = ctx.paths['final'], ctx.ep['total']
    if total is None:
        return ['totalDurationSec unavailable: %s' % ctx.ep['error']], 2, {}
    ffprobe = ctx.tools.get('ffprobe')
    if not ffprobe:
        return ['ffprobe not found'], 4, {}
    timeout = time_left(deadline, 60)
    if timeout is None:
        return [BUDGET_MSG], 4, {}
    try:
        r = subprocess.run([ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1',
                            str(final)], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, env=env)
        dur = float(r.stdout.strip())
    except subprocess.TimeoutExpired:
        return ['ffprobe timed out on %s' % ctx.rel(final)], 4, {}
    except (OSError, ValueError):
        return ['cannot read the duration of %s' % ctx.rel(final)], 2, {}
    info = {'duration': round(dur, 3), 'totalDurationSec': total}
    if abs(dur - total) > FRAME_TOLERANCE_SEC + 1e-3:
        return ['final duration %.3fs differs from totalDurationSec %.3fs by more than one frame (%.2fs)'
                % (dur, total, FRAME_TOLERANCE_SEC)], 2, info
    return [], 0, info


def verified_record(name, problems, ctx, report, inputs, cls=2, status='stale', extra=None):
    g = {'name': name, 'required': True}
    rel = ctx.rel(report) if report else None
    if problems:
        return record(g, status, cls, '; '.join(problems), rel, None, 0, inputs, kind='verified', extra=extra)
    return record(g, 'pass', 0, '', rel, None, 0, inputs, kind='verified', extra=extra)


def run_verified(ctx, env, deadline):
    h, P = ctx.hash, ctx.paths
    recs, summary_info = [], {}
    # layout
    lp = P['layout_report']
    probs, tool, linfo, linputs = verify_layout(lp, ctx, env, deadline)
    extra = {'runId': linfo.get('runId'), 'manifestHash': linfo.get('manifestHash'), 'reportSha256': linfo.get('reportSha256'),
             'reusedFrames': linfo.get('reusedFrames')} if linfo else None
    recs.append(verified_record('layout', probs, ctx, lp, linputs, cls=4 if tool == 4 else 2,
                                status='missing' if tool == 4 else 'stale', extra=extra))
    summary_info['layout'] = {k: linfo.get(k) for k in ('runId', 'manifestHash', 'reportSha256', 'reusedFrames')}
    # render receipt (+ its width/height/fps/frameCount against ffprobe of the visual file)
    rr = ctx.receipt_path('visual', RENDER_RECEIPT_SUFFIX)
    probe, perr, pcls = (None, 'visual file missing', 2) if not P['visual'].is_file() else probe_video(ctx, P['visual'], env, deadline)
    probs, rinfo = verify_render_receipt(rr, ctx, linfo, probe)
    if perr:
        probs.append(perr)
    inputs = {ctx.rel(p): h(p) for p in (P['visual'], P['episode'], P['captions'], rr, LOCK_FILE) if p.is_file()}
    recs.append(verified_record('render', probs, ctx, rr, inputs, cls=4 if (perr and pcls == 4) else 2,
                                status='missing' if (perr and pcls == 4) else 'stale', extra=rinfo or None))
    summary_info['render'] = rinfo
    # mux receipt (+ the music bed's fetch record)
    mr = ctx.receipt_path('final', '.mux.json')
    probs, minfo = verify_mux_receipt(mr, ctx)
    inputs = {ctx.rel(p): h(p) for p in (P['visual'], P['final'], mr) if p.is_file()}
    music = minfo.pop('music', None)
    recs.append(verified_record('mux', probs, ctx, mr, inputs, extra=dict(minfo, **({'music': music} if music else {})) or None))
    summary_info['mux'] = minfo
    summary_info['music'] = music
    # final video stream == visual video stream
    if P['visual'].is_file() and P['final'].is_file():
        probs, cls, vinfo = verify_mux_video(ctx, env, deadline)
    else:
        probs, cls, vinfo = ['visual or final video missing'], 2, {}
    recs.append(verified_record('mux-video', probs, ctx, P['final'], {ctx.rel(p): h(p) for p in (P['visual'], P['final']) if p.is_file()},
                                cls=cls or 2, status='missing' if cls == 4 else 'stale', extra=vinfo or None))
    # pixel format: yuv420p on both (a re-encode of the final is a quality failure); colour facts of the final go into the receipt
    fprobe, ferr, fcls = (None, 'final file missing', 2) if not P['final'].is_file() else probe_video(ctx, P['final'], env, deadline)
    if ferr or perr:
        err_cls = 4 if 4 in (pcls if perr else 0, fcls if ferr else 0) else 2
        recs.append(verified_record('video-format', [x for x in (perr, ferr) if x], ctx, P['final'], {}, cls=err_cls,
                                    status='missing' if err_cls == 4 else 'stale'))
        summary_info['video'] = None
    else:
        vf = {k: fprobe.get(k) for k in ('pix_fmt', 'color_space', 'color_range')}
        recs.append(verified_record('video-format', verify_video_format(ctx, probe, fprobe), ctx, P['final'],
                                    {ctx.rel(p): h(p) for p in (P['visual'], P['final'])}, cls=1, status='fail', extra=dict(vf)))
        summary_info['video'] = vf
    # final duration
    probs, cls, dinfo = verify_duration(ctx, env, deadline)
    recs.append(verified_record('final-duration', probs, ctx, P['final'], {ctx.rel(P['final']): h(P['final'])} if P['final'].is_file() else {},
                                cls=cls or 2, status='missing' if cls == 4 else 'stale', extra=dinfo or None))
    # relevance: absent is allowed (the content lint fails any stock/ai media beat without a verified verdict)
    rv = P['relevance']
    status = 'absent'
    if rv.is_file():
        data, err = read_json(rv)
        value = data.get('verification_status') if isinstance(data, dict) else None
        if err or not isinstance(data, dict):
            status = 'unreadable'
            recs.append(verified_record('relevance', ['relevance file unreadable: %s' % (err or 'not an object')], ctx, rv, {},
                                        extra={'verification_status': status}))
        elif value in ('verified', 'unverified'):
            status = value
            recs.append(verified_record('relevance', [], ctx, rv, {ctx.rel(rv): h(rv)}, extra={'verification_status': status}))
        elif value == 'failed':
            status = 'failed'
            recs.append(verified_record('relevance', ['relevance verification_status is "failed"'], ctx, rv, {ctx.rel(rv): h(rv)},
                                        cls=1, status='fail', extra={'verification_status': status}))
        else:
            status = 'invalid'
            recs.append(verified_record('relevance', ['relevance verification_status is %r (expected verified/unverified/failed)' % (value,)],
                                        ctx, rv, {ctx.rel(rv): h(rv)}, extra={'verification_status': status}))
    else:
        recs.append(record({'name': 'relevance', 'required': True}, 'pass', 0, 'no relevance file (recorded only)',
                           ctx.rel(rv), None, 0, {}, kind='verified', extra={'verification_status': 'absent'}))
    return recs, status, summary_info


# ---------------------------------------------------------------- outcome
def exit_class(records, extra_classes=()):
    classes = {r['cls'] for r in records if r['status'] != 'pass' and r.get('required', True)} | set(extra_classes)
    for c in (3, 4, 2, 1):          # 3 integrity > 4 infrastructure > 2 stale/bad input > 1 quality
        if c in classes:
            return c
    return 0


def public(rec, with_output):
    return {k: v for k, v in rec.items() if k != 'cls' and (with_output or k != 'output_tail')}


def summary(records):
    lines = []
    for r in records:
        ok = r['status'] == 'pass'
        lines.append('%-5s %-15s %-9s %6.1fs  %s' % ('PASS' if ok else 'FAIL', r['name'], r['kind'], r['seconds'],
                                                     '' if ok else '[%s] %s' % (r['status'], r['reason'])))
        if not ok:
            for i in r.get('issues') or []:
                lines.append('        - %s' % i)
            if r.get('report'):
                lines.append('        report: %s' % r['report'])
            if r.get('command'):         # never shortened or wrapped: it is meant to be copied
                lines.append('        rerun (copy the next line):')
                lines.append(r['command'])
    return '\n'.join(lines)


def tool_versions(tools):
    def run(cmd):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
            return (r.stdout or r.stderr).strip().splitlines()[0][:200]
        except (OSError, subprocess.TimeoutExpired, IndexError):
            return None
    out = {'python': {'path': os.path.realpath(sys.executable), 'version': platform.python_version()}}
    for name, flag in (('node', '--version'), ('ffmpeg', '-version'), ('ffprobe', '-version'), ('git', '--version'),
                       ('swift', '--version')):
        path = tools.get(name)
        out[name] = {'path': path, 'version': run([path, flag]) if path else None}
    return out


def git_out(tools, repo_root, *args):
    try:
        r = git_run(tools, repo_root, *args)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def acquire_run_lock(reports_dir):
    """One finalize run per project.  A lock is stale when its pid is not alive (a killed run is retried at once); a lock
    of a live pid is honoured (RUN_LOCK_STALE_SEC only guards against pid reuse)."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    lock = reports_dir / RUN_LOCK_NAME
    for _ in range(3):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            with os.fdopen(fd, 'w') as f:
                f.write(json.dumps({'pid': os.getpid(), 'started_at': now_iso()}))
            return lock
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
                holder, _err = read_json(lock)
            except OSError:
                continue
            pid = holder.get('pid') if isinstance(holder, dict) else None
            if not is_int(pid):
                busy = age < 5                  # just created by a run that has not written its pid yet
            elif pid == os.getpid():
                busy = False
            else:
                busy = pid_alive(pid) and age <= RUN_LOCK_STALE_SEC
            if busy:
                raise BadInput('another finalize run is active (%s, pid %s, %.0fs old); wait for it to finish' % (lock, pid, age))
            remove_quiet(lock)
    raise BadInput('could not acquire %s' % lock)


def release_run_lock(lock):
    holder, _err = read_json(lock)
    if isinstance(holder, dict) and holder.get('pid') not in (None, os.getpid()):
        return                                  # not ours any more
    remove_quiet(lock)


CHECK_FILE = {'path': None, 'started_at': None}      # the check.json of THIS invocation (set once the marker is written)


def certified_pair(deliver, receipt_p):
    """True when <deliver> is a regular file that is exactly the mp4 a delivery receipt of ours vouches for."""
    try:
        if not stat.S_ISREG(os.lstat(deliver).st_mode):
            return False
        data, err = read_json(receipt_p)
        if err or not isinstance(data, dict) or data.get('schema') != RECEIPT_SCHEMA:
            return False
        want = (data.get('delivered') or {}).get('sha256')
        return valid_sha(want) and sha256_file(Path(deliver)) == want.lower()
    except OSError:
        return False


def retire_output(deliver, receipt_p):
    """A run that does not deliver must not leave an mp4 at the deliver path that this run did not certify.
    -> (moved_to, previous_delivery_kept, error).  An mp4 + receipt pair of an earlier SUCCESSFUL delivery is never deleted:
    both are renamed to <deliver>.previous[.N] (+ .receipt.json).  Any other regular mp4 is renamed to <deliver>.uncertified[.N];
    a symlink is removed itself (never its target)."""
    try:
        if os.path.islink(deliver):
            os.unlink(deliver)
            return None, False, None
        if not os.path.lexists(deliver) or not stat.S_ISREG(os.lstat(deliver).st_mode):
            return None, False, None
        previous = certified_pair(deliver, receipt_p)
        base, n = str(deliver) + ('.previous' if previous else '.uncertified'), 0
        target = Path(base)
        while os.path.lexists(target) or (previous and os.path.lexists(str(target) + '.receipt.json')):
            n += 1
            target = Path('%s.%d' % (base, n))
        os.rename(deliver, target)
        if previous:
            os.rename(receipt_p, str(target) + '.receipt.json')
        return str(target), previous, None
    except FileNotFoundError:
        return None, False, None
    except OSError as e:
        return None, False, str(e)


def write_check_state(status, started_at, **extra):
    """check.json of this invocation: a `running` marker at the start, a terminal document at the end (or on a signal)."""
    path = CHECK_FILE['path']
    if path is None:
        return
    body = {'schema': CHECK_SCHEMA, 'version': 1, 'skill': SKILL_DIR.name, 'composition': COMP, 'status': status,
            'pid': os.getpid(), 'started_at': started_at, 'would_deliver': False}
    body.update(extra)
    try:
        write_json_atomic(path, body)
    except OSError as e:
        print('cannot write %s: %s' % (path, e), file=sys.stderr)


def run_lock_held_by_other(reports_dir):
    holder, _err = read_json(Path(reports_dir) / RUN_LOCK_NAME)
    pid = holder.get('pid') if isinstance(holder, dict) else None
    return is_int(pid) and pid != os.getpid() and pid_alive(pid)


def git_toplevel(path, tools, deadline):
    r = git_run(tools, path, 'rev-parse', '--show-toplevel', deadline=deadline)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or 'not a git repository')
    return Path(r.stdout.strip()).resolve()


# ---------------------------------------------------------------- integrity + environment (shared by run() and --preflight)
def check_integrity(args, tools, deadline, state, on_root=None):
    """The skill's gate files against gates.lock.json (skill + mirror + externals) and git.  -> list of problems.  Fills
    state: repo_root, lock_mod, mirror, head, lock_sha."""
    problems = []
    state.update(lock_mod=None, mirror=[])
    try:
        repo_root = git_toplevel(SKILL_DIR, tools, deadline)
        state['repo_root'] = repo_root
        if on_root:
            on_root(repo_root)
        integ_end = time.monotonic() + min(60.0, max(deadline.remaining(), 0.0))
        if args.repo_root and Path(args.repo_root).resolve() != repo_root:
            problems.append('repo-root-mismatch: --repo-root %s is not the skill\'s git top level %s' % (args.repo_root, repo_root))
        if (repo_root / args.composer).resolve() != (repo_root / 'remotion-composer').resolve():
            problems.append('composer-mismatch: --composer %s is not %s' % (args.composer, repo_root / 'remotion-composer'))
        lock_mod = load_sibling('gates_lock')
        lock_mod.GIT_BIN = tools.get('git') or 'git'
        lock_mod.NODE_BIN = tools.get('node') or 'node'
        lock_mod.GIT_TIMEOUT = GIT_TIMEOUT_SEC
        state['lock_mod'] = lock_mod
        parent = SKILL_DIR.parent
        if parent.name == 'skills' and parent.parent.name in ('.claude', '.agents'):
            other = '.agents' if parent.parent.name == '.claude' else '.claude'
            state['mirror'] = [parent.parent.parent / other / 'skills' / SKILL_DIR.name]
        problems += lock_mod.verify(SKILL_DIR, repo_root, state['mirror'], None, integ_end)
        state['head'] = lock_mod.git_head(repo_root, integ_end)
        state['lock_sha'] = sha256_file(LOCK_FILE) if LOCK_FILE.is_file() else None
    except Terminated:
        raise
    except Exception as e:  # noqa: BLE001 - fail closed on anything
        problems.append('git-unavailable: %s' % e if 'git' in str(e).lower() else 'integrity-check-error: %s' % e)
    return problems


def whisper_snapshot(model):
    """Local HF cache check exactly as word_timing.sh does it (no network, nothing loaded): -> snapshot dir or None, hub dir."""
    hub = Path(os.environ.get('HF_HUB_CACHE') or (os.environ.get('HF_HOME') or str(Path.home() / '.cache' / 'huggingface')) + '/hub')
    for snap in sorted((hub / ('models--' + model.replace('/', '--')) / 'snapshots').glob('*')):
        if (snap / 'config.json').is_file() and ((snap / 'weights.safetensors').exists() or (snap / 'weights.npz').exists()):
            return snap, hub
    return None, hub


def environment_checks(repo_root, composer_arg, tools, lock_problems, versions=False, word_timing=True):
    """Fail-closed environment checks, shared by a real run and `finalize.py --preflight`.  Never raises, never touches the
    network, never loads a model.  -> [{name, status: ok|FAIL|skip, detail, cls}] in the order of the preflight listing.
    lock_problems: the problems check_integrity() found (None = not checked, an empty list = the lock verified).
    word_timing: the local-whisper check is the ONE intentional difference between `--preflight` (True) and a real run /
    `--check` (False): finalize never calls word_timing.sh, so a missing model cache at delivery time must not block an
    episode whose timing already passed the `timing` / `derived` gates.  Every other check is identical."""
    out = []

    def add(name, status, detail, cls=0):
        out.append({'name': name, 'status': status, 'detail': detail, 'cls': cls if status == 'FAIL' else 0})

    # 1. tools (same resolver as the real run)
    vers = tool_versions(tools) if versions else {}
    for n in REQUIRED_TOOLS:
        if tools.get(n):
            v = (vers.get(n) or {}).get('version')
            add('tool-' + n, 'ok', '%s%s' % (tools[n], ' (%s)' % v if v else ''))
        else:
            add('tool-' + n, 'FAIL', 'not found on PATH%s' % (' (macOS Vision OCR of the frames gate: no OCR = no watermark check)' if n == 'swift' else ''), 4)
    # 2. python modules (the gates run under this interpreter)
    missing = []
    for mod in PY_MODULES:
        try:
            importlib.import_module(mod)
        except Exception as e:  # noqa: BLE001 - any import failure
            missing.append('%s (%s)' % (mod, str(e).splitlines()[0][:80] if str(e) else type(e).__name__))
    if missing:
        add('python-modules', 'FAIL', 'cannot import %s with %s: run finalize with the repo\'s .venv python (%s)'
            % (', '.join(missing), os.path.realpath(sys.executable), Path(repo_root) / '.venv' / 'bin' / 'python'), 4)
    else:
        add('python-modules', 'ok', '%s importable with %s' % (', '.join(PY_MODULES), os.path.realpath(sys.executable)))
    # 3. composer node_modules
    composer = (Path(repo_root) / composer_arg).resolve()
    nm = composer / 'node_modules'
    if not nm.is_dir():
        add('composer-node-modules', 'FAIL', '%s does not exist (the render / layout scripts load %s from it; never install packages '
            'during a run)' % (nm, ', '.join(COMPOSER_PACKAGES)), 4)
    else:
        absent = [n for n in COMPOSER_PACKAGES if not (nm / n / 'package.json').is_file()]
        add('composer-node-modules', 'FAIL' if absent else 'ok',
            ('%s lacks %s' % (nm, ', '.join(absent))) if absent else '%s has %s' % (nm, ', '.join(COMPOSER_PACKAGES)), 4)
    # 4. fonts the engine loads
    absent = [f for f in FONT_FILES if not (composer / 'public' / f).is_file() or (composer / 'public' / f).stat().st_size == 0]
    add('fonts', 'FAIL' if absent else 'ok',
        ('missing or empty under %s: %s (the render loads them blocking; never download fonts during a run)' % (composer / 'public', ', '.join(absent)))
        if absent else '%s under %s' % (', '.join(FONT_FILES), composer / 'public'), 4)
    # 5. gate lock (verified by check_integrity)
    if lock_problems is None:
        add('gate-lock', 'skip', 'not checked')
    elif lock_problems:
        tool_only = all(p.startswith('tool-missing:') for p in lock_problems)
        add('gate-lock', 'FAIL', ' | '.join(lock_problems[:4]) + (' | ...(%d more)' % (len(lock_problems) - 4) if len(lock_problems) > 4 else ''),
            4 if tool_only else 3)
    else:
        add('gate-lock', 'ok', 'lock present; skill, mirror and external files match it and git HEAD')
    # 6. local speech model for word_timing.sh (--preflight only): file existence only, what the script itself checks before it starts
    if not word_timing:
        return out
    venv = Path(os.environ.get('KARAOKE_VENV') or Path.home() / '.cache' / 'karaoke-subtitle' / 'venv')
    model = os.environ.get('WHISPER_MODEL') or WHISPER_DEFAULT_MODEL
    problems = []
    py = venv / 'bin' / 'python'
    if not (py.is_file() and os.access(py, os.X_OK)):
        problems.append('karaoke venv python missing: %s' % py)
    tool = os.environ.get('EXTRACT_TIMING')
    if not tool:
        tool = next((str(c) for c in (SKILL_DIR.parent / 'karaoke_subtitle_v2' / 'scripts' / 'extract_timing.py',
                                      Path('/Volumes/Ext_SS990Pro/Dev/openMontage-video-production/.claude/skills/karaoke_subtitle_v2/scripts/extract_timing.py'))
                     if c.is_file()), '')
    if not (tool and Path(tool).is_file()):
        problems.append('extract_timing.py not found (set EXTRACT_TIMING)')
    snap, hub = whisper_snapshot(model)
    if snap is None:
        problems.append('speech model %s is not in the local HF cache %s' % (model, hub))
    if problems:
        add('word-timing', 'FAIL', '; '.join(problems) + ' (word_timing.sh would exit 4; nothing is downloaded)', 4)
    else:
        add('word-timing', 'ok', 'venv %s, %s, model %s cached at %s (not loaded)' % (venv, tool, model, snap))
    return out


def preflight(args):
    """`finalize.py --preflight`: print one line per check; exit 0 all ok, 3 integrity, 4 tool / dependency missing.
    A real run and `--check` execute the same environment_checks() except `word-timing` (local whisper for word_timing.sh):
    that one is preflight-only, on purpose (finalize never calls word_timing.sh)."""
    deadline = Deadline(TOTAL_BUDGET_SEC)
    STOP.clear()
    tools = resolve_tools()
    state = {'repo_root': None}
    args.check = False
    problems = check_integrity(args, tools, deadline, state)
    repo_root = state['repo_root'] or Path(args.repo_root or '.').resolve()
    results = environment_checks(repo_root, args.composer, tools, problems, versions=True)
    for r in results:
        print('PREFLIGHT %s %s: %s' % (r['status'], r['name'], r['detail']))
    failed = [r for r in results if r['status'] == 'FAIL']
    code = 3 if any(r['cls'] == 3 for r in failed) else 4 if failed else 0
    print('PREFLIGHT PASS (exit 0): %d checks ok' % sum(1 for r in results if r['status'] == 'ok') if code == 0 else
          'PREFLIGHT FAIL (exit %d): %s' % (code, ', '.join(r['name'] for r in failed)))
    return code


# ---------------------------------------------------------------- main
def run(args):
    t_start, started = time.monotonic(), now_iso()
    deadline = Deadline(TOTAL_BUDGET_SEC)
    STOP.clear()
    CHECK_FILE.update(path=None, started_at=started)
    tools = resolve_tools()
    # deliver path: resolve only the parent directory, then lstat BEFORE anything else runs
    lexical = Path(os.path.abspath(args.deliver))
    deliver = lexical.parent.resolve() / lexical.name
    partial, receipt_p, failed_p = (Path(str(deliver) + s) for s in ('.partial', '.receipt.json', '.FAILED.json'))
    receipt_tmp = Path(str(receipt_p) + '.tmp')
    deliver_problem, preexisting = None, False
    try:
        st = os.lstat(deliver)
        if stat.S_ISREG(st.st_mode):
            preexisting = True
        else:
            deliver_problem = '%s exists and is a %s; refusing to deliver there' % (
                deliver, 'symlink' if stat.S_ISLNK(st.st_mode) else 'directory' if stat.S_ISDIR(st.st_mode) else 'special file')
    except FileNotFoundError:
        pass
    except OSError as e:
        deliver_problem = 'cannot stat %s: %s' % (deliver, e)

    state = {'moved': None, 'check_path': None, 'lock': None, 'ctx': None, 'lock_sha': None, 'head': None, 'repo_root': None, 'collision': False}

    def remaining_msg(phase):
        return 'time budget (%ds) exhausted during phase "%s"' % (TOTAL_BUDGET_SEC, phase)

    def may_touch_deliver():
        """The deliver path may be cleaned up / moved aside only when it is certainly not an input of the run."""
        if state['collision']:
            return False
        if state['ctx'] is None and state['repo_root'] is not None:      # the context could not be built: be careful
            proj = Path(args.project)
            proj = proj if proj.is_absolute() else state['repo_root'] / proj
            if any(inside(deliver, d) for d in (proj, state['repo_root'] / 'remotion-composer' / 'public')):
                return False
        return True

    def finish(code, records, reasons, integrity=(), relevance='absent', hint=None):
        ctx = state['ctx']
        body = {'skill': SKILL_DIR.name, 'composition': COMP, 'exit_code': code, 'started_at': started,
                'finished_at': now_iso(), 'seconds': round(time.monotonic() - t_start, 2),
                'git_head': state['head'], 'lock_sha256': state['lock_sha']}
        if args.check:
            body.update(schema=CHECK_SCHEMA, version=1, status='finished', pid=os.getpid(), would_deliver=(code == 0), reasons=reasons,
                        integrity_problems=list(integrity), relevance_status=relevance,
                        gates=[public(r, True) for r in records])
            rdir = None
            if ctx is not None:
                rdir = ctx.reports
            elif state['repo_root'] is not None:        # never relative to the cwd: an unknown repo writes nothing
                proj = Path(args.project)
                rdir = (proj if proj.is_absolute() else state['repo_root'] / proj) / DEFAULT_PATHS['reports']
            if rdir is not None:
                try:
                    write_json_atomic(rdir / 'check.json', body)
                    state['check_path'] = rdir / 'check.json'
                except OSError as e:
                    print('cannot write check.json: %s' % e, file=sys.stderr)
        elif code != 0:
            previous_kept = False
            if may_touch_deliver():
                moved, previous_kept, err = retire_output(deliver, receipt_p)
                state['moved'] = moved
                if err:
                    reasons = reasons + ['could not move the pre-existing output aside: %s' % err]
                for p in (receipt_p, receipt_tmp, partial):
                    remove_quiet(p)
            body.update(schema=FAILED_SCHEMA, version=1, reasons=reasons, integrity_problems=list(integrity),
                        preexisting_output_not_certified=preexisting and not previous_kept,
                        preexisting_output_moved_to=state['moved'], previous_delivery_preserved=previous_kept,
                        deliver_path_problem=deliver_problem, gates=[public(r, True) for r in records])
            try:
                write_json_atomic(failed_p, body)
            except OSError as e:
                print('cannot write %s: %s' % (failed_p, e), file=sys.stderr)
        lines = [summary(records)] if records else []
        if code == 0:
            lines.append('CHECK PASS — nothing delivered' if args.check else 'FINALIZE PASS (exit 0)')
        else:
            lines.append('%s FAIL (exit %d): %s' % ('CHECK' if args.check else 'FINALIZE', code, ' | '.join(reasons[:6])))
            if hint:
                lines.append(hint)
            if not args.check:
                lines.append('  -> see %s' % failed_p)
        if args.check:
            cp = state['check_path']
            lines.append('CHECK RESULT FILE: %s' % (cp if cp else 'not written (the repository or project could not be resolved)'))
            lines.append('--check never writes %s; the result of this run is only in the file above' % failed_p)
        print('\n'.join(lines))
        return code

    # ---- 1. integrity (gate files); repo root is derived from the skill dir, never from the cwd
    def on_root(root):
        if args.check:       # the previous check.json must never be mistaken for the result of this run
            proj0 = Path(args.project)
            rdir0 = (proj0 if proj0.is_absolute() else root / proj0) / DEFAULT_PATHS['reports']
            if not run_lock_held_by_other(rdir0):          # never overwrite the file of a run that is still going
                CHECK_FILE['path'] = rdir0 / 'check.json'
                write_check_state('running', started)

    problems = check_integrity(args, tools, deadline, state, on_root)
    repo_root = state['repo_root'] or Path(args.repo_root or '.').resolve()
    lock_mod, mirror = state['lock_mod'], state['mirror']
    if problems:
        if deadline.expired():
            return finish(4, [], [remaining_msg('integrity')] + ['integrity: %s' % p for p in problems[:5]], problems)
        if all(p.startswith('tool-missing:') for p in problems):      # node / gate_integrity.mjs cannot list the required files
            return finish(4, [], ['integrity: %s' % p for p in problems[:20]], problems)
        return finish(3, [], ['integrity: %s' % p for p in problems[:20]], problems, hint=RESTORE_HINT)
    if deadline.expired():
        return finish(4, [], [remaining_msg('integrity')])
    bad_env = [r for r in environment_checks(repo_root, args.composer, tools, [], word_timing=False) if r['status'] == 'FAIL']
    if bad_env:                      # the very checks `finalize.py --preflight` prints: they can never disagree
        return finish(4, [], ['environment: %s: %s (nothing was run)' % (r['name'], r['detail']) for r in bad_env[:6]])

    # ---- context, run lock, deliver path (class 2 problems; nothing has run yet)
    try:
        ctx = Ctx(args, repo_root, deliver, tools)
        state['ctx'] = ctx
    except (BadInput, OSError) as e:
        return finish(2, [], ['bad input: %s' % e])
    collision = ctx.deliver_collision()
    if collision is None:
        for d in (ctx.public / (ctx.ep['asset_dir'] or '\0'), ctx.project / 'assets', ctx.project / 'artifacts'):
            if inside(deliver, d):
                collision = '--deliver is inside an input directory of this run: %s' % ctx.rel(d)
                break
    if collision:
        state['collision'] = True
        return finish(2, [], ['bad input: ' + collision])
    try:
        state['lock'] = acquire_run_lock(ctx.reports)
    except (BadInput, OSError) as e:
        if args.check and CHECK_FILE['path'] is not None:      # our own `running` marker must not outlive this invocation
            write_check_state('finished', started, exit_code=2, reasons=['bad input: %s' % e])
        print('FINALIZE FAIL (exit 2): %s' % e)       # do not touch anything the other run may be using
        return 2
    try:
        if deliver_problem:
            return finish(2, [], ['bad input: ' + deliver_problem])
        if not args.check:
            # no stale failure / partial of an earlier attempt may sit beside the deliver path while this one runs.  A receipt is
            # kept ONLY when it is still the receipt of the mp4 beside it (a certified earlier delivery is never deleted here;
            # it is replaced when this run delivers, or renamed to <deliver>.previous when it does not).
            for p in (receipt_tmp, failed_p, partial):
                remove_quiet(p)
            if not certified_pair(deliver, receipt_p):
                remove_quiet(receipt_p)
        purge_pycache(SKILL_DIR)
        env = gate_env(tools)

        # ---- 2. fresh gates (parallel, bounded by the invocation deadline minus the post-verification reserve)
        gate_end = deadline.end - POST_RESERVE_SEC
        prepared = []
        for g in GATES:
            _argv, _report, in_paths, _p = build_command(g, ctx)
            prepared.append((g, {ctx.rel(p): ctx.hash(p) for p in in_paths}))
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)
        try:
            futs = {}
            for g, inp in prepared:
                if not g.get('after'):
                    futs[g['name']] = ex.submit(run_gate, g, ctx, inp, gate_end, env)
            for g, inp in prepared:      # dependent gates start once the gates they wait for have finished
                if g.get('after'):
                    deps = {name: futs[name].result() for name in g['after']}
                    futs[g['name']] = ex.submit(run_gate, g, ctx, inp, gate_end, env, deps)
            records = [futs[g['name']].result() for g, _ in prepared]
        finally:
            ex.shutdown(wait=False, cancel_futures=True)      # nothing queued may start after a cancellation

        # ---- 3. verified reports
        if deadline.expired():
            return finish(4, records, [remaining_msg('post-verification')])
        vrecs, relevance, vinfo = run_verified(ctx, env, deadline)
        records += vrecs

        # ---- 4. result
        reasons = ['%s: %s' % (r['name'], r['reason']) for r in records if r['status'] != 'pass' and r.get('required', True)]
        code = exit_class(records)
        changed = ctx.hash.recheck()
        if changed:
            code = code if code in (3, 4) else max(code, 2)
            reasons.append('input changed while finalize was running: ' + ', '.join(ctx.rel(c) for c in changed))
        if deadline.remaining() < 1:
            return finish(4, records, [remaining_msg('integrity re-check')] + reasons[:5], (), relevance)
        try:
            again = lock_mod.verify(SKILL_DIR, repo_root, mirror, None, time.monotonic() + min(30.0, deadline.remaining()))
        except Terminated:
            raise
        except Exception as e:  # noqa: BLE001
            again = ['integrity-check-error: %s' % e]
        if again:
            return finish(3, records, ['integrity (re-check before delivery): %s' % p for p in again[:20]], again,
                          relevance, hint=RESTORE_HINT)
        if code != 0 or args.check:
            return finish(code, records, reasons, (), relevance)
        if deadline.remaining() < DELIVER_RESERVE_SEC:
            return finish(4, records, ['%s (only %.0fs left, %ds are needed to copy and verify the delivery)'
                                       % (remaining_msg('deliver'), max(deadline.remaining(), 0), DELIVER_RESERVE_SEC)], (), relevance)
        return deliver_now(ctx, args, records, relevance, vinfo, state, deliver, partial, receipt_p, receipt_tmp,
                           t_start, started, finish, lexical, tools)
    finally:
        if state['lock']:
            release_run_lock(state['lock'])


def deliver_now(ctx, args, records, relevance, vinfo, state, deliver, partial, receipt_p, receipt_tmp, t_start, started,
                finish, lexical, tools):
    """Order: copy -> partial; receipt -> its temp name; receipt renamed; the mp4 is renamed LAST, so an mp4 at the deliver
    path always has its receipt."""
    final = ctx.paths['final']
    final_sha = ctx.hash(final)
    replaced = False
    try:
        deliver.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(final, partial)
        if sha256_file(partial) != final_sha:
            raise OSError('copy verification failed (sha256 mismatch)')
        receipt = {'schema': RECEIPT_SCHEMA, 'version': 1, 'skill': SKILL_DIR.name, 'composition': COMP,
                   'delivered': {'path': str(deliver), 'sha256': final_sha, 'bytes': partial.stat().st_size},
                   'requested_deliver_path': str(lexical),
                   'git_head': state['head'], 'lock_sha256': state['lock_sha'],
                   'finalize_sha256': sha256_file(Path(__file__).resolve()),
                   'skill_tree': git_out(tools, ctx.repo_root, 'rev-parse', 'HEAD:' + SKILL_DIR.relative_to(ctx.repo_root).as_posix()),
                   'tools': tool_versions(tools),
                   'bound_inputs': {k: {'path': ctx.rel(ctx.paths[k]), 'sha256': ctx.hash(ctx.paths[k])}
                                    for k in ('episode', 'script', 'source_script', 'srt', 'words', 'line_starts', 'word_pages',
                                              'caption_options', 'captions', 'visual', 'final')},
                   'layout': vinfo.get('layout'), 'render': vinfo.get('render'), 'mux': vinfo.get('mux'),
                   'music': vinfo.get('music'), 'video': vinfo.get('video'),
                   'manifest_sha256': ctx.manifest_sha,
                   'gates': [public(r, False) for r in records], 'relevance_status': relevance,
                   'started_at': started, 'finished_at': now_iso(), 'seconds': round(time.monotonic() - t_start, 2)}
        receipt_tmp.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n')
        remove_quiet(deliver)               # a previous (uncertified) mp4 is never left beside the new receipt
        os.replace(receipt_tmp, receipt_p)
        os.replace(partial, deliver)        # LAST
        replaced = True
        if sha256_file(deliver) != final_sha:
            remove_quiet(deliver)
            remove_quiet(receipt_p)
            raise OSError('delivered file sha256 mismatch after replace')
    except OSError as e:
        for p in (partial, receipt_tmp, receipt_p) + ((deliver,) if replaced else ()):
            remove_quiet(p)
        return finish(2, records, ['delivery failed: %s' % e], (), relevance)
    print(summary(records))
    print('FINALIZE PASS (exit 0): delivered %s sha256=%s' % (deliver, final_sha[:12]))
    return 0


def crash(args, exc):
    """Any unexpected exception becomes exit 4 + FAILED.json (never a bare traceback with exit 1).  A SIGTERM / SIGINT
    (Terminated) is an interruption, not an internal error: it gets its own message and `status: terminated` in the file."""
    STOP.set()
    kill_all()
    interrupted = isinstance(exc, Terminated)
    text = ''.join(traceback.format_exception_only(type(exc), exc)).strip()
    if interrupted:
        what = str(exc) or 'terminated'
        reasons = ['interrupted: %s; nothing was delivered' % what]
        message = 'FINALIZE INTERRUPTED (exit 4): %s \u2014 nothing was delivered; re-run the same command' % what
    else:
        reasons = ['internal error: %s' % text]
        message = 'FINALIZE FAIL (exit 4): %s' % reasons[0]
    status = {'status': 'terminated', 'signal': exc.signum} if interrupted else {'status': 'crashed'}
    try:
        lexical = Path(os.path.abspath(args.deliver))
        deliver = lexical.parent.resolve() / lexical.name
        if args.check:
            write_check_state(status['status'], CHECK_FILE['started_at'], exit_code=4, reasons=reasons,
                              **({'signal': exc.signum} if interrupted else {}))
        else:
            receipt_p = str(deliver) + '.receipt.json'
            body = {'schema': FAILED_SCHEMA, 'version': 1, 'skill': SKILL_DIR.name, 'composition': COMP, 'exit_code': 4,
                    'reasons': reasons, 'gates': [], 'finished_at': now_iso(),
                    'preexisting_output_not_certified': deliver.is_file(), 'preexisting_output_moved_to': None,
                    'previous_delivery_preserved': False, **status}
            if not interrupted:
                body['traceback'] = tail(traceback.format_exc(), 3000)
            moved, kept, err = retire_output(deliver, receipt_p)
            body.update(preexisting_output_moved_to=moved, previous_delivery_preserved=kept)
            if kept:
                body['preexisting_output_not_certified'] = False
            if err:
                body['reasons'] = reasons + ['could not move the pre-existing output aside: %s' % err]
            for s_ in ('.receipt.json', '.receipt.json.tmp', '.partial'):
                remove_quiet(str(deliver) + s_)
            write_json_atomic(str(deliver) + '.FAILED.json', body)
    except Exception:  # noqa: BLE001
        pass
    print(message)
    return 4


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
    ap.add_argument('--project')
    ap.add_argument('--deliver')
    ap.add_argument('--preflight', action='store_true',
                    help='check the environment (tools, python modules, composer node_modules, fonts, gate lock, local whisper) and exit; '
                         'needs neither --project nor --deliver')
    ap.add_argument('--composer', default='remotion-composer', help='must be <repo root>/remotion-composer')
    ap.add_argument('--repo-root', default=None, help='optional; must equal the skill\'s git top level')
    ap.add_argument('--manifest')
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args(argv)
    if args.preflight:
        if args.project or args.deliver or args.check or args.manifest:
            ap.error('--preflight takes only --composer / --repo-root')
    elif not (args.project and args.deliver):
        ap.error('--project and --deliver are required (unless --preflight)')
    old = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            old[sig] = signal.signal(sig, _on_signal)
    try:
        return preflight(args) if args.preflight else run(args)
    except Exception as e:  # noqa: BLE001
        if args.preflight:
            print('PREFLIGHT FAIL (exit 4): %s' % ('interrupted: %s' % e if isinstance(e, Terminated) else 'internal error: %s' % e))
            return 4
        return crash(args, e)
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    sys.exit(main())
