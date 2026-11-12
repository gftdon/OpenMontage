#!/usr/bin/env python3
"""finalize.py - the ONLY way to hand over the final video of a YT-News V4 episode.

  finalize.py --project projects/<slug> [--comp YtNewsStyle01V4] --deliver <output.mp4>
              [--composer remotion-composer] [--repo-root .] [--manifest <json>] [--check]

Order of work: (1) integrity of the gate files (gates_lock, exit 3), (2) the cheap gates are RUN fresh,
(3) the reports of the long jobs (layout sweep, render, mux, relevance) are VERIFIED by hash binding,
(4) only if every one of them passes the final mp4 is copied to --deliver and a delivery receipt is written.

There is deliberately NO flag and NO environment variable that skips or downgrades a gate.
Exit codes (precedence): 3 integrity > 4 tool/gate missing or timeout > 2 stale/missing report or bad input
> 1 quality failure; 0 delivered (or --check: everything would pass).
"""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / 'scripts'

DEFAULT_COMP = 'YtNewsStyle01V4'
RECEIPT_SCHEMA = 'yt-news-v4-delivery-receipt'
FAILED_SCHEMA = 'yt-news-v4-finalize-failed'
CHECK_SCHEMA = 'yt-news-v4-finalize-check'
TOTAL_BUDGET_SEC = 420          # unattended commands are killed after ~10 min; stay well below
MAX_WORKERS = 3
STALE_TOLERANCE_NS = 2_000_000_000
# A layout report must be bound (sourceHashes) to at least these project files (manifest keys).
LAYOUT_REQUIRED_BOUND = ('episode', 'captions')

# ---------------------------------------------------------------- conventions (override ONLY via manifest)
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
    'relevance': 'artifacts/relevance.json',                 # optional
    'media_roots': ['assets/broll', 'assets/ytsource/clips'],
    'layout_report': 'qc/layout/report.json',
    'visual': 'renders/visual.mp4',
    'final': 'renders/final.mp4',
    'reports': 'qc/finalize',
}
OPTIONAL_KEYS = {'source_script', 'source_transcript', 'chapters', 'relevance'}

# ---------------------------------------------------------------- gate registry (data-driven)
# name, interp ('python'|'node'), script (file in this scripts dir), args (templates; {key} = project path,
# {report} / {reports} = report file / reports dir), optional_args [[flag, key]] (added only when the file exists),
# repeat_args [[flag, key-of-list]], inputs (required path keys; also hashed into the receipt),
# need_any (list keys of which at least one entry must exist), report (template), limit (seconds), required,
# validate (name of an extra report validator).  qc_final_pixels is never given --allow-draft.
GATES = [
    dict(name='beats', interp='python', script='lint_beats.py', args=['{episode}', '--report', '{report}'],
         optional_args=[], repeat_args=[], inputs=['episode'], need_any=[], report='{reports}/beats.json',
         limit=30, required=True, validate=None),
    dict(name='content', interp='python', script='lint_content.py',
         args=['--beats', '{episode}', '--script', '{script}', '--words', '{words}', '--line-starts', '{line_starts}',
               '--cuts', '{cuts}', '--report', '{report}'],
         optional_args=[['--source-transcript', 'source_transcript'], ['--chapters', 'chapters'],
                        ['--relevance', 'relevance']],
         repeat_args=[], inputs=['episode', 'script', 'words', 'line_starts', 'cuts'], need_any=[],
         report='{reports}/content.json', limit=60, required=True, validate=None),
    dict(name='captions', interp='python', script='lint_captions.py',
         args=['--script', '{script}', '--pages', '{captions}', '--report', '{report}'],
         optional_args=[['--source-script', 'source_script']], repeat_args=[], inputs=['script', 'captions'],
         need_any=[], report='{reports}/captions.json', limit=60, required=True, validate=None),
    dict(name='frames', interp='python', script='frame_checks.py',
         args=['cutaways', '--beats', '{episode}', '--cuts', '{cuts}', '--frames-dir', '{reports}/frames',
               '--report', '{report}', '--cache-dir', '{reports}/cache'],
         optional_args=[], repeat_args=[['--media-root', 'media_roots']], inputs=['episode', 'cuts'],
         need_any=['media_roots'], report='{reports}/frames.json', limit=150, required=True, validate=None),
    dict(name='final-av', interp='python', script='final_av_checks.py', args=['{final}', '--report', '{report}'],
         optional_args=[], repeat_args=[], inputs=['final'], need_any=[], report='{reports}/final-av.json',
         limit=120, required=True, validate=None),
    dict(name='final-pixels', interp='node', script='qc_final_pixels.mjs',
         args=['{final}', '--out-dir', '{reports}/final-pixels'], optional_args=[], repeat_args=[],
         inputs=['final'], need_any=[], report='{reports}/final-pixels/final-pixels.json', limit=120,
         required=True, validate='final_pixels'),
    dict(name='loudness', interp='python', script='measure_loudness.py', args=['{final}', '--report', '{report}'],
         optional_args=[], repeat_args=[], inputs=['final'], need_any=[], report='{reports}/final-audio.json',
         limit=60, required=True, validate=None),
]

CLASS_BY_EXIT = {1: 1, 2: 2, 4: 4}
STATUS_BY_CLASS = {1: 'fail', 2: 'bad-input', 4: 'missing'}


# ---------------------------------------------------------------- helpers
def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


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


def valid_sha(v):
    return isinstance(v, str) and re.fullmatch(r'[0-9a-fA-F]{64}', v) is not None


def tail(text, n=1500):
    return text[-n:] if text else ''


# ---------------------------------------------------------------- context
class BadInput(Exception):
    pass


class Ctx:
    def __init__(self, args):
        self.repo_root = Path(args.repo_root).resolve()
        p = Path(args.project)
        self.project = (p if p.is_absolute() else self.repo_root / p).resolve()
        self.comp = args.comp
        self.deliver = Path(args.deliver).resolve()
        self.hash = Hasher()
        self.manifest_path = None
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
            for k, v in data.items():
                ok = (isinstance(v, list) and v and all(isinstance(x, str) and x for x in v)) if k == 'media_roots' \
                    else (isinstance(v, str) and v)
                if not ok:
                    raise BadInput('manifest key %s has an invalid value' % k)
                cfg[k] = v
                explicit.add(k)
            self.manifest_path = mp
            self.manifest_sha = sha256_file(mp)
        self.paths = {}
        for k, v in cfg.items():
            if k == 'media_roots':
                self.paths[k] = [(self.project / x).resolve() for x in v]
            else:
                self.paths[k] = (self.project / v).resolve()
        for k in explicit & OPTIONAL_KEYS:
            if not self.paths[k].is_file():
                raise BadInput('manifest sets optional %s but %s does not exist' % (k, self.paths[k]))
        self.reports = self.paths['reports']
        if self.deliver.suffix.lower() != '.mp4':
            raise BadInput('--deliver must be an .mp4 path')
        if self.deliver == self.paths['final']:
            raise BadInput('--deliver must differ from the final render path')

    def rel(self, p):
        try:
            return Path(p).resolve().relative_to(self.repo_root).as_posix()
        except ValueError:
            return str(Path(p).resolve())

    def receipt_path(self, key, suffix):
        return Path(str(self.paths[key]) + suffix)


# ---------------------------------------------------------------- fresh gates
def final_pixels_validator(report, ctx):
    probs = []
    final = ctx.paths['final']
    if report.get('videoSha256') != ctx.hash(final):
        probs.append((2, 'final-pixels report is bound to a different video (videoSha256 mismatch)'))
    if report.get('certified') is not True:
        probs.append((1, 'final-pixels report is not certified (certified != true)'))
    return probs


VALIDATORS = {'final_pixels': final_pixels_validator}


def build_command(gate, ctx):
    """Return (argv-without-interpreter, report path, input paths, problems)."""
    report = Path(gate['report'].format(reports=ctx.reports))
    ph = {k: str(v) for k, v in ctx.paths.items() if not isinstance(v, list)}
    ph.update(report=str(report), reports=str(ctx.reports))
    problems, inputs = [], []
    for key in gate['inputs']:
        if not ctx.paths[key].is_file():
            problems.append('required input %s missing: %s' % (key, ctx.rel(ctx.paths[key])))
        else:
            inputs.append(ctx.paths[key])
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


def record(gate, status, cls, reason, report=None, code=None, seconds=0.0, inputs=None, out='', kind='fresh', extra=None):
    r = {'name': gate['name'], 'kind': kind, 'required': gate.get('required', True), 'status': status,
         'cls': cls, 'exit': code, 'seconds': round(seconds, 2), 'report': report, 'reason': reason,
         'inputs': inputs or {}, 'output_tail': tail(out)}
    if extra:
        r.update(extra)
    return r


def run_gate(gate, ctx, inputs, deadline, env):
    script = SCRIPTS_DIR / gate['script']
    argv, report, _paths, problems = build_command(gate, ctx)
    rel_report = ctx.rel(report)
    if not script.is_file():
        return record(gate, 'missing', 4, 'gate script missing: %s' % gate['script'], rel_report, inputs=inputs)
    if gate['interp'] == 'python':
        exe = [sys.executable]
    else:
        node = shutil.which(gate['interp'])
        if not node:
            return record(gate, 'missing', 4, '%s not found on PATH' % gate['interp'], rel_report, inputs=inputs)
        exe = [node]
    if problems:
        return record(gate, 'bad-input', 2, '; '.join(problems), rel_report, inputs=inputs)
    report.parent.mkdir(parents=True, exist_ok=True)
    if report.exists():
        report.unlink()           # a report can only exist if THIS run wrote it
    remaining = deadline - time.monotonic()
    limit = min(gate['limit'], remaining)
    if limit < 1:
        return record(gate, 'timeout', 4, 'finalize time budget (%ds) exhausted before the gate started' % TOTAL_BUDGET_SEC,
                      rel_report, inputs=inputs)
    start_ns, t0 = time.time_ns(), time.monotonic()
    proc = subprocess.Popen(exe + [str(script)] + argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, errors='replace', env=env, cwd=str(ctx.repo_root), start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=limit)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)    # our own process group only
        except OSError:
            pass
        out, _ = proc.communicate()
        return record(gate, 'timeout', 4, 'timeout: gate exceeded its %.0fs limit' % limit, rel_report, None,
                      time.monotonic() - t0, inputs, out)
    secs, code = time.monotonic() - t0, proc.returncode
    if code != 0:
        cls = CLASS_BY_EXIT.get(code, 1)
        return record(gate, STATUS_BY_CLASS[cls], cls, 'gate exited with code %d' % code, rel_report, code, secs, inputs, out)
    # exit 0: the report must exist, be fresh, parse, and say pass:true
    if not report.is_file():
        return record(gate, 'stale', 2, 'exit 0 but no report was written at %s' % rel_report, rel_report, 0, secs, inputs, out)
    if report.stat().st_mtime_ns < start_ns - STALE_TOLERANCE_NS:
        return record(gate, 'stale', 2, 'report is older than this run (stale): %s' % rel_report, rel_report, 0, secs, inputs, out)
    data, err = read_json(report)
    if err or not isinstance(data, dict):
        return record(gate, 'stale', 2, 'report unreadable: %s' % (err or 'not a JSON object'), rel_report, 0, secs, inputs, out)
    if data.get('pass') is not True:
        return record(gate, 'fail', 1, 'report says pass != true', rel_report, 0, secs, inputs, out)
    if gate.get('validate'):
        bad = VALIDATORS[gate['validate']](data, ctx)
        if bad:
            cls = 2 if any(c == 2 for c, _ in bad) else 1
            return record(gate, STATUS_BY_CLASS[cls], cls, '; '.join(m for _, m in bad), rel_report, 0, secs, inputs, out)
    inputs = dict(inputs)
    inputs[rel_report] = ctx.hash(report)
    return record(gate, 'pass', 0, '', rel_report, 0, secs, inputs, out)


def gate_env():
    env = {k: v for k, v in os.environ.items()
           if k not in ('PYTHONPATH', 'PYTHONSTARTUP', 'PYTHONINSPECT', 'NODE_OPTIONS', 'NODE_PATH')}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return env


def purge_pycache(skill_dir):
    for dirpath, dirnames, _ in os.walk(skill_dir):
        for d in list(dirnames):
            if d == '__pycache__':
                shutil.rmtree(os.path.join(dirpath, d), ignore_errors=True)
                dirnames.remove(d)


# ---------------------------------------------------------------- verified reports
def verify_layout(report_path, comp, repo_root, required_bound, sha):
    """-> (problems, bound {abs path: sha}, extra)"""
    data, err = read_json(report_path)
    if err or not isinstance(data, dict):
        return ['layout report %s: %s' % (report_path, err or 'not a JSON object')], {}, {}
    p = []
    if data.get('status') != 'finished':
        p.append('layout status is %r, not "finished"' % data.get('status'))
    if data.get('pass') is not True:
        p.append('layout report pass != true')
    if data.get('complete') is not True:
        p.append('layout report is not complete')
    rc, fc = data.get('requestedCount'), data.get('fullPlanCount')
    if not (is_int(rc) and is_int(fc) and fc > 0 and rc == fc):
        p.append('layout requestedCount (%r) != fullPlanCount (%r)' % (rc, fc))
    if data.get('compositionId') != comp:
        p.append('layout compositionId %r != %r' % (data.get('compositionId'), comp))
    extra = {}
    if data.get('reusedFrames'):
        manifest = data.get('cacheManifest')
        if not manifest:
            p.append('layout reusedFrames is set but cacheManifest is missing')
        else:
            extra = {'reused_frames': True,
                     'cache_manifest_sha256': sha256_bytes(json.dumps(manifest, sort_keys=True).encode())}
    hashes = data.get('sourceHashes')
    bound = {}
    if not isinstance(hashes, dict) or not hashes:
        p.append('layout sourceHashes missing or empty')
    else:
        for name, digest in hashes.items():
            f = Path(name)
            f = (f if f.is_absolute() else Path(repo_root) / f).resolve()
            if not valid_sha(digest):
                p.append('layout sourceHashes[%s] is not a sha256' % name)
            elif not f.is_file():
                p.append('layout source file missing: %s' % name)
            elif sha(f) != digest.lower():
                p.append('layout source changed since the sweep: %s' % name)
            else:
                bound[str(f)] = digest.lower()
        for req in required_bound:
            if str(Path(req).resolve()) not in bound:
                p.append('layout sourceHashes does not bind %s' % req)
    return p, bound, extra


def verify_render_receipt(receipt_path, comp, visual, episode, captions, sha):
    """Minimum contract (format owned by the render workstream): compositionId == comp,
    output.sha256 == sha(visual); episode.sha256 / captions.sha256 are compared when present."""
    data, err = read_json(receipt_path)
    if err or not isinstance(data, dict):
        return ['render receipt %s: %s' % (receipt_path, err or 'not a JSON object')]
    p = []
    if data.get('compositionId') != comp:
        p.append('render receipt compositionId %r != %r' % (data.get('compositionId'), comp))
    out = data.get('output')
    if not Path(visual).is_file():
        p.append('visual render missing: %s' % visual)
    elif not (isinstance(out, dict) and valid_sha(out.get('sha256')) and out['sha256'].lower() == sha(visual)):
        p.append('render receipt output.sha256 does not match the visual render')
    for key, path in (('episode', episode), ('captions', captions)):
        if key not in data:
            continue
        v = data[key]
        digest = v.get('sha256') if isinstance(v, dict) else v
        if not valid_sha(digest):
            p.append('render receipt %s field has no sha256' % key)
        elif not Path(path).is_file() or digest.lower() != sha(path):
            p.append('render receipt %s.sha256 does not match the current %s (stale render)' % (key, key))
    return p


def verify_mux_receipt(receipt_path, visual, final, sha):
    data, err = read_json(receipt_path)
    if err or not isinstance(data, dict):
        return ['mux receipt %s: %s' % (receipt_path, err or 'not a JSON object')]
    p = []
    if data.get('schema') != 'yt-news-v4-mux-receipt':
        p.append('mux receipt has the wrong schema')
    for key, path in (('visual', visual), ('final', final)):
        v = data.get(key)
        if not (isinstance(v, dict) and valid_sha(v.get('sha256'))):
            p.append('mux receipt %s.sha256 missing' % key)
        elif not Path(path).is_file() or v['sha256'].lower() != sha(path):
            p.append('mux receipt %s.sha256 does not match the current %s' % (key, key))
    return p


def verified_record(name, problems, ctx, report, inputs, cls_on_problem=2, extra=None, status_fail='stale'):
    if problems:
        return record({'name': name, 'required': True}, status_fail, cls_on_problem, '; '.join(problems),
                      ctx.rel(report), None, 0, inputs, kind='verified', extra=extra)
    return record({'name': name, 'required': True}, 'pass', 0, '', ctx.rel(report), None, 0, inputs, kind='verified', extra=extra)


def run_verified(ctx):
    h, P = ctx.hash, ctx.paths
    recs = []
    # layout
    lp = P['layout_report']
    required = [str(P[k]) for k in LAYOUT_REQUIRED_BOUND]
    probs, bound, extra = verify_layout(lp, ctx.comp, ctx.repo_root, required, h)
    inputs = {ctx.rel(k): v for k, v in bound.items()}
    if lp.is_file():
        inputs[ctx.rel(lp)] = h(lp)
    recs.append(verified_record('layout', probs, ctx, lp, inputs, extra=extra))
    # render receipt
    rr = ctx.receipt_path('visual', '.render.json')
    probs = verify_render_receipt(rr, ctx.comp, P['visual'], P['episode'], P['captions'], h)
    inputs = {ctx.rel(p): h(p) for p in (P['visual'], P['episode'], P['captions'], rr) if p.is_file()}
    recs.append(verified_record('render', probs, ctx, rr, inputs))
    # mux receipt
    mr = ctx.receipt_path('final', '.mux.json')
    probs = verify_mux_receipt(mr, P['visual'], P['final'], h)
    inputs = {ctx.rel(p): h(p) for p in (P['visual'], P['final'], mr) if p.is_file()}
    recs.append(verified_record('mux', probs, ctx, mr, inputs))
    # relevance (recorded; failed is a quality failure)
    rv = P['relevance']
    status = 'absent'
    if rv.is_file():
        data, err = read_json(rv)
        if err or not isinstance(data, dict):
            recs.append(verified_record('relevance', ['relevance file unreadable: %s' % (err or 'not an object')], ctx, rv, {}))
        else:
            status = data.get('verification_status') if isinstance(data.get('verification_status'), str) else 'unknown'
            probs = ['relevance verification_status is "failed"'] if status == 'failed' else []
            recs.append(verified_record('relevance', probs, ctx, rv, {ctx.rel(rv): h(rv)}, cls_on_problem=1,
                                        status_fail='fail', extra={'verification_status': status}))
    else:
        recs.append(record({'name': 'relevance', 'required': True}, 'pass', 0, 'no relevance file (recorded only)',
                           ctx.rel(rv), None, 0, {}, kind='verified', extra={'verification_status': 'absent'}))
    return recs, status


# ---------------------------------------------------------------- outcome
def exit_class(records, extra_classes=()):
    classes = {r['cls'] for r in records if r['status'] != 'pass' and r.get('required', True)} | set(extra_classes)
    for c in (4, 2, 1):
        if c in classes:
            return c
    return 0


def public(rec, with_output):
    r = {k: v for k, v in rec.items() if k != 'cls' and (with_output or k != 'output_tail')}
    return r


def write_json_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    os.replace(tmp, path)


def remove_quiet(p):
    try:
        Path(p).unlink()
    except FileNotFoundError:
        pass


def summary(records, verdict_line):
    lines = []
    for r in records:
        lines.append('%-5s %-13s %-9s %6.1fs  %s' % ('PASS' if r['status'] == 'pass' else 'FAIL', r['name'], r['kind'],
                                                   r['seconds'], r['reason'] if r['status'] != 'pass' else ''))
    lines.append(verdict_line)
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--project', required=True)
    ap.add_argument('--comp', default=DEFAULT_COMP)
    ap.add_argument('--deliver', required=True)
    ap.add_argument('--composer', default='remotion-composer', help='kept for compatibility; V4 has no per-episode TSX')
    ap.add_argument('--repo-root', default='.')
    ap.add_argument('--manifest')
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args(argv)
    t_start, started = time.monotonic(), now_iso()
    deliver = Path(args.deliver).resolve()
    repo_root = Path(args.repo_root).resolve()
    out = {'deliver': deliver, 'check': args.check}
    preexisting = deliver.is_file()
    partial, receipt_p, failed_p = (Path(str(deliver) + s) for s in ('.partial', '.receipt.json', '.FAILED.json'))

    def finish(code, records, reasons, ctx=None, integrity=(), relevance='absent', lock_sha=None, head=None):
        finished = now_iso()
        secs = round(time.monotonic() - t_start, 2)
        body = {'skill': SKILL_DIR.name, 'composition': args.comp, 'exit_code': code, 'started_at': started,
                'finished_at': finished, 'seconds': secs, 'git_head': head, 'lock_sha256': lock_sha}
        if code != 0 and not args.check:
            for p in (receipt_p, partial):
                remove_quiet(p)
            body.update(schema=FAILED_SCHEMA, version=1, reasons=reasons, integrity_problems=list(integrity),
                        preexisting_output_not_certified=preexisting,
                        gates=[public(r, True) for r in records])
            try:
                write_json_atomic(failed_p, body)
            except OSError as e:
                print('cannot write %s: %s' % (failed_p, e), file=sys.stderr)
        elif args.check:
            body.update(schema=CHECK_SCHEMA, version=1, would_deliver=(code == 0), reasons=reasons,
                        integrity_problems=list(integrity), relevance_status=relevance,
                        gates=[public(r, True) for r in records])
            try:
                rdir = ctx.reports if ctx is not None else \
                    ((Path(args.project) if Path(args.project).is_absolute() else repo_root / args.project) / DEFAULT_PATHS['reports'])
                write_json_atomic(rdir / 'check.json', body)
            except OSError as e:
                print('cannot write check.json: %s' % e, file=sys.stderr)
        verdict = 'FINALIZE %s (exit %d)%s' % ('PASS' if code == 0 else 'FAIL', code,
                                              '' if code == 0 else ': ' + ' | '.join(reasons[:6]))
        print(summary(records, verdict + ('' if args.check or code == 0 else '  -> see ' + str(failed_p))))
        return code

    # ---- 0. stale artefacts of a previous run must never outlive this one
    if not args.check:
        for p in (receipt_p, failed_p, partial):
            try:
                remove_quiet(p)
            except OSError:
                pass

    # ---- 1. integrity
    try:
        lock_mod = load_sibling('gates_lock')
        mirror = []
        parent = SKILL_DIR.parent
        if parent.name == 'skills' and parent.parent.name in ('.claude', '.agents'):
            other = '.agents' if parent.parent.name == '.claude' else '.claude'
            mirror = [parent.parent.parent / other / 'skills' / SKILL_DIR.name]
        problems = lock_mod.verify(SKILL_DIR, repo_root, mirror)
        head = lock_mod.git_head(repo_root)
        lock_sha = sha256_file(SKILL_DIR / 'scripts' / 'gates.lock.json') if (SKILL_DIR / 'scripts' / 'gates.lock.json').is_file() else None
    except Exception as e:  # noqa: BLE001 - fail closed on anything
        problems, head, lock_sha = ['integrity-check-error: %s' % e], None, None
    if problems:
        return finish(3, [], ['integrity: %s' % p for p in problems[:20]], None, problems, lock_sha=lock_sha, head=head)

    # ---- context / early input problems (class 2)
    try:
        ctx = Ctx(args)
    except BadInput as e:
        return finish(2, [], ['bad input: %s' % e], None, lock_sha=lock_sha, head=head)
    except OSError as e:
        return finish(2, [], ['bad input: %s' % e], None, lock_sha=lock_sha, head=head)
    purge_pycache(SKILL_DIR)
    env = gate_env()
    ctx.reports.mkdir(parents=True, exist_ok=True)

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
    vrecs, relevance = run_verified(ctx)
    records += vrecs

    # ---- 4. result
    extra = []
    reasons = ['%s: %s' % (r['name'], r['reason']) for r in records if r['status'] != 'pass' and r.get('required', True)]
    code = exit_class(records, extra)
    if code == 0:
        changed = ctx.hash.recheck()
        if changed:
            code = 2
            reasons.append('input changed while finalize was running: ' + ', '.join(ctx.rel(c) for c in changed))
    if code == 0:
        try:
            again = lock_mod.verify(SKILL_DIR, repo_root, mirror)
        except Exception as e:  # noqa: BLE001
            again = ['integrity-check-error: %s' % e]
        if again:
            return finish(3, records, ['integrity (re-check before delivery): %s' % p for p in again[:20]], ctx, again,
                          relevance, lock_sha, head)
    if code != 0 or args.check:
        return finish(code, records, reasons, ctx, (), relevance, lock_sha, head)

    final = ctx.paths['final']
    final_sha = ctx.hash(final)
    try:
        deliver.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(final, partial)
        if sha256_file(partial) != final_sha:
            raise OSError('copy verification failed (sha256 mismatch)')
        os.replace(partial, deliver)
        if sha256_file(deliver) != final_sha:
            remove_quiet(deliver)
            raise OSError('delivered file sha256 mismatch after replace')
    except OSError as e:
        remove_quiet(partial)
        return finish(2, records, ['delivery failed: %s' % e], ctx, (), relevance, lock_sha, head)
    finished = now_iso()
    receipt = {'schema': RECEIPT_SCHEMA, 'version': 1, 'skill': SKILL_DIR.name, 'composition': args.comp,
               'delivered': {'path': str(deliver), 'sha256': final_sha, 'bytes': deliver.stat().st_size},
               'git_head': head, 'lock_sha256': lock_sha,
               'bound_inputs': {k: {'path': ctx.rel(ctx.paths[k]), 'sha256': ctx.hash(ctx.paths[k])}
                                for k in ('episode', 'captions', 'visual', 'final')},
               'manifest_sha256': ctx.manifest_sha,
               'gates': [public(r, False) for r in records], 'relevance_status': relevance,
               'started_at': started, 'finished_at': finished, 'seconds': round(time.monotonic() - t_start, 2)}
    write_json_atomic(receipt_p, receipt)
    print(summary(records, 'FINALIZE PASS (exit 0): delivered %s sha256=%s' % (deliver, final_sha[:12])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
