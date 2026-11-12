#!/usr/bin/env python3
"""Final-video freeze / black-frame gate (fail-closed).

final_av_checks.py <final.mp4> --report R [--freeze-min 2.0] [--black-min 0.5] [--allow-tail SEC] [--ignore-from SEC]

--ignore-from: issues that START at or after this time are ignored (the V4 end card, a static dark frame on
[voEndSec, totalDurationSec)); a span that starts before it is still reported.

Exit codes: 0 pass, 1 quality issues, 2 bad input / decode failure, 4 ffmpeg missing.
The report is always written (also on failure) so a caller can tell a fresh report from a stale one.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys

SCHEMA = 'yt-news-v4-final-av'
FREEZE_NOISE = '-60dB'


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def probe_duration(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', str(path)],
                       capture_output=True, text=True)
    if r.returncode:
        raise ValueError('ffprobe failed: ' + r.stderr[-500:])
    d = float(r.stdout.strip())
    if not math.isfinite(d) or d <= 0:
        raise ValueError('invalid duration')
    return d


def parse_spans(stderr, duration):
    """Return (freeze_spans, black_spans) as lists of (start, end)."""
    freezes, blacks = [], []
    open_start = None
    for line in stderr.splitlines():
        m = re.search(r'freeze_start:\s*([\d.]+)', line)
        if m:
            open_start = float(m[1])
            continue
        m = re.search(r'freeze_end:\s*([\d.]+)', line)
        if m and open_start is not None:
            freezes.append((open_start, float(m[1])))
            open_start = None
            continue
        m = re.search(r'black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)', line)
        if m:
            blacks.append((float(m[1]), float(m[2])))
    if open_start is not None:  # freeze running to end of file
        freezes.append((open_start, duration))
    return freezes, blacks


def evaluate(freezes, blacks, duration, freeze_min, black_min, allow_tail, ignore_from=None):
    issues = []
    tail_start = duration - allow_tail if allow_tail > 0 else duration
    for kind, spans, minimum in (('freeze', freezes, freeze_min), ('black', blacks, black_min)):
        for start, end in spans:
            if ignore_from is not None and start >= ignore_from - 1e-3:
                continue
            effective_end = min(end, tail_start)
            if effective_end - start + 1e-6 >= minimum:
                issues.append({'code': kind, 'start': round(start, 3), 'end': round(end, 3),
                               'duration': round(end - start, 3),
                               'detail': '%s span %.2fs-%.2fs (%.2fs)' % (kind, start, end, end - start)})
    issues.sort(key=lambda i: (i['start'], i['code']))
    return issues


def write_report(path, report):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + '.tmp')
    tmp.write_text(json.dumps(report, indent=2))
    tmp.replace(p)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('mp4')
    ap.add_argument('--report', required=True)
    ap.add_argument('--freeze-min', type=float, default=2.0)
    ap.add_argument('--black-min', type=float, default=0.5)
    ap.add_argument('--allow-tail', type=float, default=0.0)
    ap.add_argument('--ignore-from', type=float, default=None)
    args = ap.parse_args(argv)
    report = {'schema': SCHEMA, 'version': 1, 'pass': False, 'issues': [], 'duration': None, 'inputs': {},
              'params': {'freeze_min': args.freeze_min, 'black_min': args.black_min, 'allow_tail': args.allow_tail, 'ignore_from': args.ignore_from,
                         'freeze_noise': FREEZE_NOISE}}
    code = 2
    try:
        if not (shutil.which('ffmpeg') and shutil.which('ffprobe')):
            report['error'] = 'ffmpeg/ffprobe not found'
            code = 4
            raise SystemExit
        src = Path(args.mp4)
        if not src.is_file():
            report['error'] = 'input not found: ' + str(src)
            raise SystemExit
        if min(args.freeze_min, args.black_min) <= 0 or args.allow_tail < 0 \
                or (args.ignore_from is not None and args.ignore_from < 0):
            report['error'] = 'thresholds must be positive'
            raise SystemExit
        report['inputs'] = {str(src.resolve()): sha256_file(src)}
        duration = probe_duration(src)
        report['duration'] = round(duration, 3)
        vf = 'freezedetect=n=%s:d=%s,blackdetect=d=%s' % (FREEZE_NOISE, args.freeze_min, args.black_min)
        r = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(src), '-vf', vf, '-an', '-f', 'null', '-'],
                           capture_output=True, text=True)
        if r.returncode:
            report['error'] = 'ffmpeg analysis failed: ' + r.stderr[-1000:]
            raise SystemExit
        freezes, blacks = parse_spans(r.stderr, duration)
        report['issues'] = evaluate(freezes, blacks, duration, args.freeze_min, args.black_min, args.allow_tail, args.ignore_from)
        report['pass'] = not report['issues']
        code = 0 if report['pass'] else 1
    except SystemExit:
        pass
    except (ValueError, OSError) as e:
        report['error'] = str(e)
        code = 2
    try:
        write_report(args.report, report)
    except OSError as e:
        print('cannot write report: %s' % e, file=sys.stderr)
        return 2
    print(json.dumps({k: report[k] for k in ('pass', 'issues', 'duration') if k in report} | ({'error': report['error']} if 'error' in report else {})))
    return code


if __name__ == '__main__':
    sys.exit(main())
