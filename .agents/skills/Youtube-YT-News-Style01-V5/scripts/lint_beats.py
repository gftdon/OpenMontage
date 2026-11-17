#!/usr/bin/env python3
"""Fail-closed V4 hold gate: one unchanged rendered picture may not stay on screen too long.

  python lint_beats.py <episode.json> [--report <file>]

Exit 0 = pass (warnings never fail), 1 = at least one error, 2 = input / parse error.
Report: {pass, issues:[{code,t,detail,severity}], beats, warnings, runs}. `severity` is "error" or "warn";
`warnings` counts the warn issues; `pass` is true when there is no error. Errors are listed before warnings.
`runs` lists EVERY run of consecutive pip beats with one picture identity, so the numbers can be read even
when the lint passes: {t, end, seconds, kind ("clip"|"typo"|"broll"), src, layout}.
The episode is read through episode_data.load_episode (the single loader of episode.json).

Only this rule lives here, because the schema validator (episode_schema.mjs) does not own it. Picture identity:
  * broll / clip beat   (media, src, layout)
  * typo beat           changes at every cards[].at / items[].at; identity = ('typo', variant, content shown
                        so far), so a card repeated with the same lines is NOT a change
Consecutive beats with the same identity accumulate (a run). Overlays (stats, kicker, headline, sub, lower) never
reset a run. A `mode: "full"` (presenter-only) beat is NOT held to this rule: the presenter-only run length is the
`presenter-run` gate of lint_content.py (12 s). A full beat only closes the running run.

What a run is held to depends on what is on screen:

  hold         ERROR  text cards (media typo) and stock / AI b-roll (media broll): one unchanged picture longer
                      than `maxHoldSeconds` (qc_thresholds.json, 10 s).
  hold-layout  WARN   source video clips (media clip, origin source): a playing clip changes by itself, so the 10 s
                      limit for clips is NOT measured here. It is measured from real rendered frames by the
                      `static-hold` gate of frame_checks.py. This metadata check only warns when the same
                      src + layout run across consecutive beats is longer than CLIP_LAYOUT_RUN_WARN_SECONDS.

Rules of the V3 version that were deleted, and what owns them now:

  metadata      empty BEATS, invalid / non-contiguous interval, invalid mode / media / layout, pip without media,
                missing src             -> schema enums + S01 (t increasing, first beat 0), S02 (>= 1 s), S04, S05
  captionLane   per-beat caption lane   -> removed from the format (caption lane is fixed; additionalProperties:false)
  chrome        chrome literal, stock-chrome -> removed from the format (the engine draws the chrome by origin)
  layout full   layout "full"           -> replaced by "wide" (schema enum, S08)
  origin        yt_ / ai_ prefix vs origin   -> S06
  punch-origin  punch target + geometry (z, fx, fy, cropStep, scaleStep, time order) -> S12 (punch only on full beats,
                at in [t, end), increasing) and the schema punch definition (z 1..1.6)
  cards         invalid typography card -> S14
  lower         invalid lower timing    -> S15 (+ schema lower definition)
  endcard       endcard longer than maxEndcardSeconds -> S03 (totalDurationSec - voEndSec in [3, 5])
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import episode_data as ed

EPS = 1e-8
# Warn when one source clip stays in the same layout for longer than this many seconds across consecutive beats.
# 30 is the project lead's STARTING value, not an acceptance threshold; the 10 s limit for clips is frame_checks static-hold.
CLIP_LAYOUT_RUN_WARN_SECONDS = 30


def _content_identity(beat, now):
    """What a typo beat shows at time `now`: the latest card, or the items revealed so far, or the vs table."""
    variant = beat.get('typo')
    if variant == 'vs':
        return ('typo', variant, json.dumps(beat.get('vs'), sort_keys=True, ensure_ascii=False))
    if variant == 'card':
        shown = [c for c in beat.get('cards') or [] if isinstance(c, dict) and (ed.num(c.get('at')) or 0) <= now + EPS]
        return ('typo', variant, tuple(shown[-1].get('lines') or ()) if shown else ())
    shown = [i.get('text') for i in beat.get('items') or [] if isinstance(i, dict) and (ed.num(i.get('at')) or 0) <= now + EPS]
    return ('typo', variant, tuple(shown))


def _segments(beat):
    """[(start_time, identity)] of a pip beat; the picture changes at each cards[].at / items[].at of a typo beat."""
    t, end = beat['t'], beat['end']
    media = beat.get('media')
    if media != 'typo':
        return [(t, (media, beat.get('src'), beat.get('layout')))]
    times = {t}
    for key in ('cards', 'items'):
        for entry in beat.get(key) or []:
            at = ed.num(entry.get('at')) if isinstance(entry, dict) else None
            if at is not None and t < at < end:
                times.add(at)
    return [(now, _content_identity(beat, now)) for now in sorted(times)]


def _kind(identity):
    media = identity[0]
    return 'typo' if media == 'typo' else 'clip' if media == 'clip' else 'broll'


def holds(beats):
    """Every maximal run of one unchanged picture in pip scenes (presenter-only beats excluded):
    [{'t','end','seconds','kind','src','layout'}] with kind clip / typo / broll."""
    runs = []
    identity = None
    start = None
    layout = None

    def close(end):
        kind = _kind(identity)
        runs.append({'t': start, 'end': end, 'seconds': end - start, 'kind': kind,
                     'src': identity[1] if kind != 'typo' else None, 'layout': layout})

    for b in beats:
        if b.get('mode') == 'full':
            if start is not None:
                close(b['t'])
            identity = start = None
            continue
        for now, ident in _segments(b):
            if ident != identity:
                if start is not None:
                    close(now)
                identity, start, layout = ident, now, b.get('layout')
    if start is not None and beats:
        close(beats[-1]['end'])
    return runs


def lint_beats(beats, thresholds):
    issues = []
    limit = thresholds['maxHoldSeconds']
    for r in holds(beats):
        if r['kind'] == 'clip':
            if r['seconds'] > CLIP_LAYOUT_RUN_WARN_SECONDS + EPS:
                issues.append(dict(code='hold-layout', t=r['t'], severity='warn',
                                   detail='source clip %s stays in layout %s for %.2f s (%.2f-%.2f), warning above %s s; '
                                          'the 10 s limit for clips is the static-hold gate (frame_checks.py)'
                                          % (r['src'], r['layout'], r['seconds'], r['t'], r['end'], CLIP_LAYOUT_RUN_WARN_SECONDS)))
        elif r['seconds'] > limit + EPS:
            issues.append(dict(code='hold', t=r['t'], severity='error',
                               detail='rendered visual hold of %.2f s exceeds %s s (%.2f-%.2f)' % (r['seconds'], limit, r['t'], r['end'])))
    return sorted(issues, key=lambda i: i['severity'] != 'error')  # errors first (finalize.py shows the first few)


def lint_report(beats, thresholds):
    issues = lint_beats(beats, thresholds)
    return {'pass': not any(i['severity'] == 'error' for i in issues), 'issues': issues, 'beats': len(beats),
            'warnings': sum(i['severity'] == 'warn' for i in issues), 'runs': holds(beats)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('episode', help='episode.json (yt-news-v4-episode/1)')
    ap.add_argument('--report')
    args = ap.parse_args()
    try:
        beats = ed.load_episode(args.episode)['beats']
        thresholds = json.loads((Path(__file__).parent / 'qc_thresholds.json').read_text())
        result = lint_report(beats, thresholds)
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.report:
            Path(args.report).write_text(output)
        print(output)
        return 0 if result['pass'] else 1
    except (OSError, ValueError, KeyError) as e:
        print(json.dumps({'pass': False, 'issues': [{'code': 'parse', 'detail': str(e), 'severity': 'error'}]}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
