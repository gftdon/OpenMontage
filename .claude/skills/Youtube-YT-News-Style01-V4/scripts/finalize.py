#!/usr/bin/env python3
"""finalize.py - the ONLY way to hand over the final video of a YT-News V4 episode.

  finalize.py --project projects/<slug> --deliver <output.mp4> [--composer remotion-composer]
              [--repo-root <git top level>] [--manifest <json>] [--check]

Order of work: (1) integrity of the gate files (gates_lock, exit 3), (2) the gates are RUN fresh (long ones
first), (3) the reports of the long jobs (layout sweep, render, mux, relevance, final duration) are VERIFIED by
hash binding, (4) only if every one of them passes the final mp4 is copied to --deliver and a delivery receipt is
written.  There is deliberately NO flag and NO environment variable that skips or downgrades a gate.

Exit codes (precedence): 3 integrity > 4 tool/gate missing, crash or timeout > 2 stale/missing report or bad
input > 1 quality failure; 0 delivered (or --check: everything would pass).
A relative --project is resolved against the repository root (git top level of this skill), --deliver against
the current directory.
"""
import argparse
import atexit
import concurrent.futures
import datetime
import hashlib
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
TOTAL_BUDGET_SEC = 420          # unattended commands are killed after ~10 min; stay well below
MAX_WORKERS = 3
STALE_TOLERANCE_NS = 2_000_000_000
RUN_LOCK_NAME = '.finalize.lock'
RUN_LOCK_STALE_SEC = 15 * 60
FRAME_TOLERANCE_SEC = 0.04       # final duration vs totalDurationSec

# =================================================================================================================
# CONTRACT with the other team's scripts (CF-A66, commit 907b80a).  EVERY field / flag name of those scripts that
# finalize depends on lives in this section; if their code changes, change it here only.
# Where code and gate-spec disagreed the CODE wins (see the notes).
# =================================================================================================================
# -- qc_layout / qc_report.mjs : layout report v3 (<project>/qc/layout/report.json) -----------------------------
LAYOUT_REPORT_SCHEMA = 'yt-news-layout-report'
LAYOUT_REPORT_VERSION = 3
# -- qc_manifest.mjs : run manifest + manifestHash() (we call the JS function; canonical JSON is NOT re-implemented)
RUN_MANIFEST_SCHEMA = 'yt-news-v4-run-manifest'
QC_MANIFEST_SCRIPT = 'qc_manifest.mjs'
MANIFEST_KEY_EPISODE = 'episode.json'            # keys of manifest.sourceHashes (computeSourceHashes)
MANIFEST_KEY_CAPTIONS = 'captions.json'
MANIFEST_KEY_LOCK = 'scripts/gates.lock.json'
# -- render_episode.mjs : render receipt <visual>.receipt.json (RECEIPT_FIELDS) ---------------------------------
RENDER_RECEIPT_SUFFIX = '.receipt.json'
RENDER_RECEIPT_SCHEMA = 'yt-news-v4-render-receipt'
# -- episode.json (episode_schema.mjs): top level voEndSec, totalDurationSec, assetDir, avatarFile ---------------
# -- qc_final_pixels.mjs : `node qc_final_pixels.mjs <video.mp4> <out-dir> [--vo-end s]` (positional out-dir; the
#    gate-spec/coordinator note said --out-dir, the CODE rejects it as "unknown option"); report <out-dir>/final-pixels.json
#    with videoSha256 + certified.  --allow-draft is NEVER passed.
# -- episode_schema.mjs : `validate <episode> --captions <captions> --json` -> stdout {valid, errors[{path,rule,message}]}
# -- gate_integrity.mjs : `<composer-dir> --json --skill-dir <dir>` -> stdout {ok, issues[{id,message}]}, exit 3 refused
# -- mux_av.sh (ours) : <final>.mux.json {visual, avatar, bed, final: {path, sha256}}
# =================================================================================================================

# -- conventions (override ONLY via the manifest, and only the keys in OVERRIDABLE) ----------------------------
DEFAULT_PATHS = {
    'episode': 'artifacts/episode.json',
    'script': 'artifacts/script.txt',
    'source_script': 'artifacts/source_script.txt',      # optional
    'words': 'artifacts/words_by_line.txt',
    'line_starts': 'artifacts/line_starts.json',
    'captions': 'artifacts/caption-joined.json',
    'cuts': 'artifacts/_cuts.json',
    'source_transcript': 'assets/ytsource/transcript.txt',  # optional
    'chapters': 'assets/ytsource/chapters.txt',              # optional
    'relevance': 'artifacts/relevance.json',                 # optional (absent is allowed)
    'media_roots': ['assets/broll', 'assets/ytsource/clips'],
    'layout_report': 'qc/layout/report.json',
    'visual': 'renders/visual.mp4',
    'final': 'renders/final.mp4',
    'reports': 'qc/finalize',
}
OPTIONAL_KEYS = {'source_script', 'source_transcript', 'chapters', 'relevance'}
OVERRIDABLE = {'script', 'source_script', 'words', 'line_starts', 'cuts', 'source_transcript', 'chapters', 'media_roots'}
FORBIDDEN_OVERRIDES = set(DEFAULT_PATHS) - OVERRIDABLE

# -- gate registry (data-driven; long gates first so they start first) -----------------------------------------
# name, interp ('python'|'node'), script (file in this scripts dir), args (templates; {key} = project path,
# {report}, {reports}, {vo_end}, {composer}, {skill}), optional_args [[flag,key]] (only when the file exists),
# repeat_args [[flag,key-of-list]], inputs (required path keys, also hashed into the receipt), needs (episode values
# that must be readable), need_any, report (template), limit (s), required, validate (extra validator name),
# stdout_report (finalize stores the tool's stdout JSON at `report`), pass_key (report key that must be True),
# exit_classes (extra exit code -> class).
GATES = [
    dict(name='frames', interp='python', script='frame_checks.py',
         args=['cutaways', '--beats', '{episode}', '--cuts', '{cuts}', '--frames-dir', '{reports}/frames',
               '--report', '{report}', '--cache-dir', '{reports}/cache'],
         optional_args=[], repeat_args=[['--media-root', 'media_roots']], inputs=['episode', 'cuts'], needs=[],
         need_any=['media_roots'], report='{reports}/frames.json', limit=150, required=True),
    dict(name='final-av', interp='python', script='final_av_checks.py',
         args=['{final}', '--report', '{report}', '--ignore-from', '{vo_end}'],
         optional_args=[], repeat_args=[], inputs=['final'], needs=['vo_end'], need_any=[],
         report='{reports}/final-av.json', limit=120, required=True),
    dict(name='final-pixels', interp='node', script='qc_final_pixels.mjs',
         args=['{final}', '{reports}/final-pixels', '--vo-end', '{vo_end}'], optional_args=[], repeat_args=[],
         inputs=['final'], needs=['vo_end'], need_any=[], report='{reports}/final-pixels/final-pixels.json',
         limit=120, required=True, validate='final_pixels'),
    dict(name='loudness', interp='python', script='measure_loudness.py', args=['{final}', '--report', '{report}'],
         optional_args=[], repeat_args=[], inputs=['final'], needs=[], need_any=[], report='{reports}/final-audio.json',
         limit=60, required=True),
    dict(name='schema', interp='node', script='episode_schema.mjs',
         args=['validate', '{episode}', '--captions', '{captions}', '--json'], optional_args=[], repeat_args=[],
         inputs=['episode', 'captions'], needs=[], need_any=[], report='{reports}/schema.json', limit=30,
         required=True, stdout_report=True, pass_key='valid'),
    dict(name='gate-integrity', interp='node', script='gate_integrity.mjs',
         args=['{composer}', '--json', '--skill-dir', '{skill}'], optional_args=[], repeat_args=[], inputs=[],
         needs=[], need_any=[], report='{reports}/gate-integrity.json', limit=60, required=True,
         stdout_report=True, pass_key='ok', exit_classes={3: 1}),
    dict(name='beats', interp='python', script='lint_beats.py', args=['{episode}', '--report', '{report}'],
         optional_args=[], repeat_args=[], inputs=['episode'], needs=[], need_any=[], report='{reports}/beats.json',
         limit=30, required=True),
    dict(name='content', interp='python', script='lint_content.py',
         args=['--beats', '{episode}', '--script', '{script}', '--words', '{words}', '--line-starts', '{line_starts}',
               '--cuts', '{cuts}', '--report', '{report}'],
         optional_args=[['--source-transcript', 'source_transcript'], ['--chapters', 'chapters'],
                        ['--relevance', 'relevance']],
         repeat_args=[], inputs=['episode', 'script', 'words', 'line_starts', 'cuts'], needs=[], need_any=[],
         report='{reports}/content.json', limit=60, required=True),
    dict(name='captions', interp='python', script='lint_captions.py',
         args=['--script', '{script}', '--pages', '{captions}', '--report', '{report}'],
         optional_args=[['--source-script', 'source_script']], repeat_args=[], inputs=['script', 'captions'],
         needs=[], need_any=[], report='{reports}/captions.json', limit=60, required=True),
]

STATUS_BY_CLASS = {1: 'fail', 2: 'bad-input', 4: 'missing'}
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


class Terminated(Exception):
    pass


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
    kill_all()
    raise Terminated('terminated by signal %d' % signum)


# ---------------------------------------------------------------- context
class BadInput(Exception):
    pass


class Ctx:
    def __init__(self, args, repo_root, deliver):
        self.repo_root = repo_root
        p = Path(args.project)
        self.project = (p if p.is_absolute() else self.repo_root / p).resolve()
        self.comp = COMP
        self.deliver = deliver
        self.hash = Hasher()
        self.composer = (self.repo_root / args.composer).resolve()
        self.manifest_sha = None
        cfg = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULT_PATHS.items()}
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
                values = v if k == 'media_roots' else [v]
                if not (isinstance(values, list) and values and all(isinstance(x, str) and x for x in values)):
                    raise BadInput('manifest key %s has an invalid value' % k)
                for x in values:
                    if Path(x).is_absolute() or '..' in Path(x).parts:
                        raise BadInput('manifest key %s: absolute paths and ".." are not allowed (%s)' % (k, x))
                cfg[k] = v
                explicit.add(k)
            self.manifest_sha = sha256_file(mp)
        self.paths = {}
        for k, v in cfg.items():
            if k == 'media_roots':
                self.paths[k] = [(self.project / x).resolve() for x in v]
                bad = [x for x in self.paths[k] if not inside(x, self.project)]
            else:
                self.paths[k] = (self.project / v).resolve()
                bad = [] if inside(self.paths[k], self.project) else [self.paths[k]]
            if bad:
                raise BadInput('%s resolves outside the project: %s' % (k, bad[0]))
        for k in explicit & OPTIONAL_KEYS:
            if not self.paths[k].is_file():
                raise BadInput('manifest sets optional %s but %s does not exist' % (k, self.paths[k]))
        self.reports = self.paths['reports']
        if self.deliver.suffix.lower() != '.mp4':
            raise BadInput('--deliver must be an .mp4 path')
        if self.deliver == self.paths['final']:
            raise BadInput('--deliver must differ from the final render path')
        self.ep = {'vo_end': None, 'total': None, 'asset_dir': None, 'avatar_file': None, 'error': None}
        self._read_episode()

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


# ---------------------------------------------------------------- reports: issue summaries
def summarize_issues(data, limit=3):
    out = []
    if not isinstance(data, dict):
        return out
    for key in ('issues', 'errors', 'dips', 'problems'):
        items = data.get(key)
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict):
                    code = it.get('code') or it.get('rule') or it.get('id') or key
                    detail = it.get('detail') or it.get('message') or it.get('reason') or ''
                    where = it.get('path') or it.get('beat') or it.get('t') or it.get('start')
                    text = '%s: %s' % (code, detail) if detail else str(code)
                    if where not in (None, ''):
                        text += ' (@%s)' % (where,)
                else:
                    text = str(it)
                out.append(text[:300])
                if len(out) >= limit:
                    return out
    if not out and isinstance(data.get('error'), str):
        out.append('error: ' + data['error'][:300])
    return out


# ---------------------------------------------------------------- fresh gates
def final_pixels_validator(report, ctx):
    probs = []
    if report.get('videoSha256') != ctx.hash(ctx.paths['final']):
        probs.append((2, 'final-pixels report is bound to a different video (videoSha256 mismatch)'))
    if report.get('certified') is not True:
        probs.append((1, 'final-pixels report is not certified (certified != true)'))
    return probs


VALIDATORS = {'final_pixels': final_pixels_validator}


def build_command(gate, ctx):
    """Return (argv-without-interpreter, report path, input paths, problems)."""
    report = Path(gate['report'].format(reports=ctx.reports))
    ph = {k: str(v) for k, v in ctx.paths.items() if not isinstance(v, list)}
    ph.update(report=str(report), reports=str(ctx.reports), composer=str(ctx.composer), skill=str(SKILL_DIR),
              vo_end='' if ctx.ep['vo_end'] is None else repr(ctx.ep['vo_end']))
    problems, inputs = [], []
    for key in gate['inputs']:
        if not ctx.paths[key].is_file():
            problems.append('required input %s missing: %s' % (key, ctx.rel(ctx.paths[key])))
        else:
            inputs.append(ctx.paths[key])
    for need in gate.get('needs', []):
        if ctx.ep.get(need) is None:
            problems.append('%s unavailable: %s' % (need, ctx.ep['error'] or 'not in episode.json'))
    argv = [a.format(**ph) for a in gate['args']]
    for flag, key in gate.get('optional_args', []):
        if ctx.paths[key].is_file():
            argv += [flag, str(ctx.paths[key])]
            inputs.append(ctx.paths[key])
    for flag, key in gate.get('repeat_args', []):
        for p in ctx.paths[key]:
            if p.is_dir():
                argv += [flag, str(p)]
    for key in gate.get('need_any', []):
        if not any(p.exists() for p in ctx.paths[key]):
            problems.append('none of the %s exist' % key)
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


def _read_text(f, limit=5_000_000):
    f.seek(0)
    return f.read(limit).decode('utf-8', 'replace')


def run_gate(gate, ctx, inputs, deadline, env):
    script = SCRIPTS_DIR / gate['script']
    argv, report, _paths, problems = build_command(gate, ctx)
    rel_report = ctx.rel(report)
    if gate['interp'] == 'python':
        exe = [sys.executable, '-B', '-E', '-s']
    else:
        exe = [shutil.which(gate['interp']) or gate['interp']]
    cmd = exe + [str(script)] + argv
    command = shlex.join(cmd)
    base = dict(report=rel_report, inputs=inputs, command=command)
    if not script.is_file():
        return record(gate, 'missing', 4, 'gate script missing: %s' % gate['script'], **base)
    if gate['interp'] != 'python' and not shutil.which(gate['interp']):
        return record(gate, 'missing', 4, '%s not found on PATH' % gate['interp'], **base)
    if problems:
        return record(gate, 'bad-input', 2, '; '.join(problems), **base)
    report.parent.mkdir(parents=True, exist_ok=True)
    if report.exists():
        report.unlink()           # a report can only exist if THIS run wrote it
    remaining = deadline - time.monotonic()
    limit = min(gate['limit'], remaining)
    if limit < 1:
        return record(gate, 'timeout', 4, 'finalize time budget (%ds) exhausted before the gate started' % TOTAL_BUDGET_SEC, **base)
    start_ns, t0 = time.time_ns(), time.monotonic()
    timed_out = False
    with tempfile.TemporaryFile() as fo, tempfile.TemporaryFile() as fe:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe, env=env, cwd=str(ctx.repo_root),
                                start_new_session=True)
        with _ACTIVE_LOCK:
            ACTIVE_PGIDS.add(proc.pid)
        try:
            try:
                proc.wait(timeout=limit)
            except subprocess.TimeoutExpired:
                timed_out = True
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
        stdout, stderr = _read_text(fo), _read_text(fe)
    secs, code = time.monotonic() - t0, proc.returncode
    out = (stdout + ('\n' if stdout and stderr else '') + stderr)
    base.update(code=code, seconds=secs, out=out)
    if timed_out:
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


def gate_env():
    return {k: v for k, v in os.environ.items()
            if k not in ('PYTHONPATH', 'PYTHONSTARTUP', 'PYTHONINSPECT', 'NODE_OPTIONS', 'NODE_PATH')}


def purge_pycache(skill_dir):
    for dirpath, dirnames, _ in os.walk(skill_dir):
        for d in list(dirnames):
            if d == '__pycache__':
                shutil.rmtree(os.path.join(dirpath, d), ignore_errors=True)
                dirnames.remove(d)


# ---------------------------------------------------------------- verified reports
def node_manifest_hash(manifest_path, env):
    """manifestHash() computed by the OTHER team's JS (never re-implemented). -> (hash|None, error, class)"""
    qm = SCRIPTS_DIR / QC_MANIFEST_SCRIPT
    node = shutil.which('node')
    if not qm.is_file():
        return None, '%s is missing from the skill (cannot recompute manifestHash)' % QC_MANIFEST_SCRIPT, 4
    if not node:
        return None, 'node not found on PATH (cannot recompute manifestHash)', 4
    code = ("import {pathToFileURL} from 'node:url'; import fs from 'node:fs';"
            "const m = await import(pathToFileURL(process.argv[1]).href);"
            "console.log(m.manifestHash(JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))));")
    try:
        r = subprocess.run([node, '--input-type=module', '-e', code, str(qm), str(manifest_path)], capture_output=True,
                           text=True, timeout=30, env=env, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, 'manifestHash computation failed: %s' % e, 4
    h = r.stdout.strip()
    if r.returncode != 0 or not valid_sha(h):
        return None, 'manifestHash computation failed (exit %d): %s' % (r.returncode, tail(r.stderr, 300)), 4
    return h.lower(), None, 0


def verify_layout(report_path, ctx, env):
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
        lock_sha = ctx.hash(LOCK_FILE) if LOCK_FILE.is_file() else None
        for key, path in ((MANIFEST_KEY_EPISODE, ctx.paths['episode']), (MANIFEST_KEY_CAPTIONS, ctx.paths['captions']),
                          (MANIFEST_KEY_LOCK, LOCK_FILE)):
            want = hashes.get(key)
            if not valid_sha(want):
                p.append('run manifest sourceHashes[%s] missing' % key)
            elif not Path(path).is_file() or ctx.hash(path) != want.lower():
                p.append('layout was run on a different %s (sourceHashes[%s] differs from the current file)' % (key, key))
    h, herr, tool = node_manifest_hash(mpath, env)
    if herr:
        p.append(herr)
    elif valid_sha(mhash) and h != mhash.lower():
        p.append('run manifest hash %s does not match report.manifestHash' % h[:12])
    return p, tool, info, inputs


def verify_render_receipt(receipt_path, ctx, layout_info):
    """Real contract (render_episode.mjs RECEIPT_FIELDS). -> (problems, info)"""
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
    if layout_info.get('manifestHash') and (data.get('gateManifestHash') or '').lower() != str(layout_info['manifestHash']).lower():
        p.append('render receipt gateManifestHash differs from the layout report manifestHash')
    if layout_info.get('runId') and data.get('gateRunId') != layout_info['runId']:
        p.append('render receipt gateRunId differs from the layout report runId')
    return p, {'renderId': data.get('renderId'), 'receiptSha256': h(receipt_path)}


def verify_mux_receipt(receipt_path, ctx):
    data, err = read_json(receipt_path)
    if err or not isinstance(data, dict):
        stem = ctx.paths['final'].with_suffix('')
        return ['mux receipt %s: %s (mux_av.sh writes it only after the loudness check passes; see %s.audio/final.json)'
                % (ctx.rel(receipt_path), err or 'not a JSON object', ctx.rel(stem))], {}
    p = []
    if data.get('schema') != 'yt-news-v4-mux-receipt':
        p.append('mux receipt has the wrong schema')
    avatar = None
    if ctx.ep['asset_dir'] and ctx.ep['avatar_file']:
        avatar = ctx.composer / 'public' / ctx.ep['asset_dir'] / ctx.ep['avatar_file']
    else:
        p.append('episode.json has no assetDir/avatarFile; cannot bind the avatar')
    for key, path in (('visual', ctx.paths['visual']), ('final', ctx.paths['final']), ('avatar', avatar)):
        if path is None:
            continue
        v = data.get(key)
        if not (isinstance(v, dict) and valid_sha(v.get('sha256'))):
            p.append('mux receipt %s.sha256 missing' % key)
        elif not Path(path).is_file() or ctx.hash(path) != v['sha256'].lower():
            p.append('mux receipt %s.sha256 does not match the current %s' % (key, ctx.rel(path)))
    return p, {'receiptSha256': ctx.hash(receipt_path)}


def verify_duration(ctx):
    final, total = ctx.paths['final'], ctx.ep['total']
    if total is None:
        return ['totalDurationSec unavailable: %s' % ctx.ep['error']], 2, {}
    if not shutil.which('ffprobe'):
        return ['ffprobe not found'], 4, {}
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1',
                            str(final)], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        dur = float(r.stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
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


def run_verified(ctx, env):
    h, P = ctx.hash, ctx.paths
    recs, summary_info = [], {}
    # layout
    lp = P['layout_report']
    probs, tool, linfo, linputs = verify_layout(lp, ctx, env)
    extra = {'runId': linfo.get('runId'), 'manifestHash': linfo.get('manifestHash'), 'reportSha256': linfo.get('reportSha256'),
             'reusedFrames': linfo.get('reusedFrames')} if linfo else None
    recs.append(verified_record('layout', probs, ctx, lp, linputs, cls=4 if tool == 4 else 2,
                                status='missing' if tool == 4 else 'stale', extra=extra))
    summary_info['layout'] = {k: linfo.get(k) for k in ('runId', 'manifestHash', 'reportSha256', 'reusedFrames')}
    # render receipt
    rr = ctx.receipt_path('visual', RENDER_RECEIPT_SUFFIX)
    probs, rinfo = verify_render_receipt(rr, ctx, linfo)
    inputs = {ctx.rel(p): h(p) for p in (P['visual'], P['episode'], P['captions'], rr, LOCK_FILE) if p.is_file()}
    recs.append(verified_record('render', probs, ctx, rr, inputs, extra=rinfo or None))
    summary_info['render'] = rinfo
    # mux receipt
    mr = ctx.receipt_path('final', '.mux.json')
    probs, minfo = verify_mux_receipt(mr, ctx)
    inputs = {ctx.rel(p): h(p) for p in (P['visual'], P['final'], mr) if p.is_file()}
    recs.append(verified_record('mux', probs, ctx, mr, inputs, extra=minfo or None))
    summary_info['mux'] = minfo
    # final duration
    probs, cls, dinfo = verify_duration(ctx)
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
    for c in (4, 2, 1):
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
            if r.get('command'):
                lines.append('        rerun : %s' % r['command'])
    return '\n'.join(lines)


def tool_versions():
    def run(cmd):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
            return (r.stdout or r.stderr).strip().splitlines()[0][:200]
        except (OSError, subprocess.TimeoutExpired, IndexError):
            return None
    tools = {'python': {'path': sys.executable, 'version': platform.python_version()}}
    for name, flag in (('node', '--version'), ('ffmpeg', '-version'), ('git', '--version')):
        path = shutil.which(name)
        tools[name] = {'path': path, 'version': run([path, flag]) if path else None}
    return tools


def git_out(repo_root, *args):
    try:
        r = subprocess.run(['git', '-C', str(repo_root), *args], capture_output=True, text=True, timeout=30,
                           stdin=subprocess.DEVNULL, env={k: v for k, v in os.environ.items() if not k.startswith('GIT_')})
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def acquire_run_lock(reports_dir):
    reports_dir.mkdir(parents=True, exist_ok=True)
    lock = reports_dir / RUN_LOCK_NAME
    for _ in range(2):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            with os.fdopen(fd, 'w') as f:
                f.write(json.dumps({'pid': os.getpid(), 'started_at': now_iso()}))
            return lock
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                continue
            if age > RUN_LOCK_STALE_SEC:
                remove_quiet(lock)
                continue
            raise BadInput('another finalize run is active (%s, %.0fs old); wait for it to finish' % (lock, age))
    raise BadInput('could not acquire %s' % lock)


def git_toplevel(path):
    r = subprocess.run(['git', '-C', str(path), 'rev-parse', '--show-toplevel'], capture_output=True, text=True, timeout=30,
                       stdin=subprocess.DEVNULL, env={k: v for k, v in os.environ.items() if not k.startswith('GIT_')})
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or 'not a git repository')
    return Path(r.stdout.strip()).resolve()


# ---------------------------------------------------------------- main
def run(args):
    t_start, started = time.monotonic(), now_iso()
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

    state = {'moved': None, 'lock': None, 'ctx': None, 'lock_sha': None, 'head': None, 'repo_root': None}

    def finish(code, records, reasons, integrity=(), relevance='absent', hint=None):
        ctx = state['ctx']
        body = {'skill': SKILL_DIR.name, 'composition': COMP, 'exit_code': code, 'started_at': started,
                'finished_at': now_iso(), 'seconds': round(time.monotonic() - t_start, 2),
                'git_head': state['head'], 'lock_sha256': state['lock_sha']}
        if args.check:
            body.update(schema=CHECK_SCHEMA, version=1, would_deliver=(code == 0), reasons=reasons,
                        integrity_problems=list(integrity), relevance_status=relevance,
                        gates=[public(r, True) for r in records])
            try:
                rdir = ctx.reports if ctx is not None else (
                    (Path(args.project) if Path(args.project).is_absolute() else (state['repo_root'] or Path(args.repo_root or '.').resolve()) / args.project)
                    / DEFAULT_PATHS['reports'])
                write_json_atomic(rdir / 'check.json', body)
            except OSError as e:
                print('cannot write check.json: %s' % e, file=sys.stderr)
        elif code != 0:
            for p in (receipt_p, receipt_tmp, partial):
                remove_quiet(p)
            if preexisting and deliver_problem is None:
                try:   # a regular mp4 that is still there is NOT certified: move it aside, never delete it
                    if stat.S_ISREG(os.lstat(deliver).st_mode):
                        target, n = Path(str(deliver) + '.uncertified'), 0
                        while os.path.lexists(target):
                            n += 1
                            target = Path('%s.uncertified.%d' % (deliver, n))
                        os.rename(deliver, target)
                        state['moved'] = str(target)
                except FileNotFoundError:
                    pass
                except OSError as e:
                    reasons = reasons + ['could not move the pre-existing output aside: %s' % e]
            body.update(schema=FAILED_SCHEMA, version=1, reasons=reasons, integrity_problems=list(integrity),
                        preexisting_output_not_certified=preexisting, preexisting_output_moved_to=state['moved'],
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
        print('\n'.join(lines))
        return code

    # ---- 1. integrity (gate files); repo root is derived from the skill dir, never from the cwd
    problems = []
    try:
        repo_root = git_toplevel(SKILL_DIR)
        state['repo_root'] = repo_root
        if args.repo_root and Path(args.repo_root).resolve() != repo_root:
            problems.append('repo-root-mismatch: --repo-root %s is not the skill\'s git top level %s' % (args.repo_root, repo_root))
        lock_mod = load_sibling('gates_lock')
        mirror = []
        parent = SKILL_DIR.parent
        if parent.name == 'skills' and parent.parent.name in ('.claude', '.agents'):
            other = '.agents' if parent.parent.name == '.claude' else '.claude'
            mirror = [parent.parent.parent / other / 'skills' / SKILL_DIR.name]
        problems += lock_mod.verify(SKILL_DIR, repo_root, mirror)
        state['head'] = lock_mod.git_head(repo_root)
        state['lock_sha'] = sha256_file(LOCK_FILE) if LOCK_FILE.is_file() else None
    except Exception as e:  # noqa: BLE001 - fail closed on anything
        repo_root = Path(args.repo_root or '.').resolve()
        problems.append('git-unavailable: %s' % e if 'git' in str(e).lower() else 'integrity-check-error: %s' % e)
    if problems:
        return finish(3, [], ['integrity: %s' % p for p in problems[:20]], problems, hint=RESTORE_HINT)

    # ---- context, run lock, deliver path (class 2 problems; nothing has run yet)
    try:
        ctx = Ctx(args, repo_root, deliver)
        state['ctx'] = ctx
    except (BadInput, OSError) as e:
        return finish(2, [], ['bad input: %s' % e])
    try:
        state['lock'] = acquire_run_lock(ctx.reports)
    except (BadInput, OSError) as e:
        print('FINALIZE FAIL (exit 2): %s' % e)       # do not touch anything the other run may be using
        return 2
    try:
        if not args.check:
            for p in (receipt_p, receipt_tmp, failed_p, partial):
                remove_quiet(p)
        if deliver_problem:
            return finish(2, [], ['bad input: ' + deliver_problem])
        purge_pycache(SKILL_DIR)
        env = gate_env()

        # ---- 2. fresh gates (parallel, bounded by one overall deadline)
        deadline = time.monotonic() + TOTAL_BUDGET_SEC
        prepared = []
        for g in GATES:
            _argv, _report, in_paths, _p = build_command(g, ctx)
            prepared.append((g, {ctx.rel(p): ctx.hash(p) for p in in_paths}))
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = [ex.submit(run_gate, g, ctx, inp, deadline, env) for g, inp in prepared]
            records = [f.result() for f in futs]

        # ---- 3. verified reports
        vrecs, relevance, vinfo = run_verified(ctx, env)
        records += vrecs

        # ---- 4. result
        reasons = ['%s: %s' % (r['name'], r['reason']) for r in records if r['status'] != 'pass' and r.get('required', True)]
        code = exit_class(records)
        changed = ctx.hash.recheck()
        if changed:
            code = max(code, 2) if code != 4 else 4
            reasons.append('input changed while finalize was running: ' + ', '.join(ctx.rel(c) for c in changed))
        try:
            again = lock_mod.verify(SKILL_DIR, repo_root, mirror)
        except Exception as e:  # noqa: BLE001
            again = ['integrity-check-error: %s' % e]
        if again:
            return finish(3, records, ['integrity (re-check before delivery): %s' % p for p in again[:20]], again,
                          relevance, hint=RESTORE_HINT)
        if code != 0 or args.check:
            return finish(code, records, reasons, (), relevance)
        return deliver_now(ctx, args, records, relevance, vinfo, state, deliver, partial, receipt_p, receipt_tmp,
                           t_start, started, finish, lexical)
    finally:
        if state['lock']:
            remove_quiet(state['lock'])


def deliver_now(ctx, args, records, relevance, vinfo, state, deliver, partial, receipt_p, receipt_tmp, t_start, started,
                finish, lexical):
    final = ctx.paths['final']
    final_sha = ctx.hash(final)
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
                   'skill_tree': git_out(ctx.repo_root, 'rev-parse', 'HEAD:' + SKILL_DIR.relative_to(ctx.repo_root).as_posix()),
                   'tools': tool_versions(),
                   'bound_inputs': {k: {'path': ctx.rel(ctx.paths[k]), 'sha256': ctx.hash(ctx.paths[k])}
                                    for k in ('episode', 'captions', 'visual', 'final')},
                   'layout': vinfo.get('layout'), 'render': vinfo.get('render'), 'mux': vinfo.get('mux'),
                   'manifest_sha256': ctx.manifest_sha,
                   'gates': [public(r, False) for r in records], 'relevance_status': relevance,
                   'started_at': started, 'finished_at': now_iso(), 'seconds': round(time.monotonic() - t_start, 2)}
        receipt_tmp.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n')
        os.replace(partial, deliver)
        try:
            os.replace(receipt_tmp, receipt_p)
        except OSError:
            remove_quiet(deliver)      # never leave an uncertified file at the output path
            raise
        if sha256_file(deliver) != final_sha:
            remove_quiet(deliver)
            remove_quiet(receipt_p)
            raise OSError('delivered file sha256 mismatch after replace')
    except OSError as e:
        for p in (partial, receipt_tmp, receipt_p):
            remove_quiet(p)
        return finish(2, records, ['delivery failed: %s' % e], (), relevance)
    print(summary(records))
    print('FINALIZE PASS (exit 0): delivered %s sha256=%s' % (deliver, final_sha[:12]))
    return 0


def crash(args, exc):
    """Any unexpected exception becomes exit 4 + FAILED.json (never a bare traceback with exit 1)."""
    kill_all()
    text = ''.join(traceback.format_exception_only(type(exc), exc)).strip()
    reasons = ['internal error: %s' % text]
    try:
        lexical = Path(os.path.abspath(args.deliver))
        deliver = lexical.parent.resolve() / lexical.name
        if not args.check:
            for s in ('.receipt.json', '.receipt.json.tmp', '.partial'):
                remove_quiet(str(deliver) + s)
            body = {'schema': FAILED_SCHEMA, 'version': 1, 'skill': SKILL_DIR.name, 'composition': COMP, 'exit_code': 4,
                    'reasons': reasons, 'traceback': tail(traceback.format_exc(), 3000), 'gates': [],
                    'finished_at': now_iso(), 'preexisting_output_not_certified': deliver.is_file(),
                    'preexisting_output_moved_to': None}
            if deliver.is_file() and not deliver.is_symlink():
                target, n = Path(str(deliver) + '.uncertified'), 0
                while os.path.lexists(target):
                    n += 1
                    target = Path('%s.uncertified.%d' % (deliver, n))
                os.rename(deliver, target)
                body['preexisting_output_moved_to'] = str(target)
            write_json_atomic(str(deliver) + '.FAILED.json', body)
    except Exception:  # noqa: BLE001
        pass
    print('FINALIZE FAIL (exit 4): %s' % reasons[0])
    return 4


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--project', required=True)
    ap.add_argument('--deliver', required=True)
    ap.add_argument('--composer', default='remotion-composer')
    ap.add_argument('--repo-root', default=None, help='optional; must equal the skill\'s git top level')
    ap.add_argument('--manifest')
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args(argv)
    old = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            old[sig] = signal.signal(sig, _on_signal)
    try:
        return run(args)
    except Exception as e:  # noqa: BLE001
        return crash(args, e)
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    sys.exit(main())
