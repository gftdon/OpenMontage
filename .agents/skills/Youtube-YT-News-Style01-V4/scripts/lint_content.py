#!/usr/bin/env python3
"""Deterministic lint of the on-screen CONTENT of a YT-News episode (CF-A67 WP2a).

Complements lint_beats.py (geometry/hold). Offline, no network, no model calls, fail-closed:
a missing or unreadable input exits 2. issue = {code, severity:'error'|'warn', t, field, text, detail, ...};
only 'error' fails the run.

Checks: provenance-number / -ordinal / -latin / -thai, card-timing-*, presenter-share/-run, cta-length,
punch-forbidden, typo-kind, stock-unverified, source-reuse. Thresholds: content_thresholds.py.

--relevance accepted formats (see load_relevance): the `results` rows of the report written by
score_relevance.py / batch_relevance.py (matched to a beat by `src` if the row has one, else by beat start
`t`), a bare list of such rows, or {"<src>": row}. A row passes only when
score_relevance.verification_status(row, beat_origin) == 'verified' (derived from score / readable_text /
pending flags -- a stored `verification_status` label is never trusted).
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import episode_data as ed
from content_thresholds import THRESHOLDS, LEGACY_OVERRIDES

SCHEMA = 'yt-news-v4-content-lint'
VERSION = 1

ORDINAL = re.compile(r'(?<![A-Za-z])(รอบที่|ครั้งที่|ขั้นที่|ข้อที่|อันดับที่?|รุ่นที่|ตอนที่|เวอร์ชัน|Round|Step|Pass|Part)\s*(\d+)', re.IGNORECASE)
ENGLISH_ORDINALS = {'round', 'step', 'pass', 'part'}
FRACTION = re.compile(r'(?<![\d.,])(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)(?!\d)')
NUMBER = re.compile(r'(?<!\d)\d+(?:,\d{3})*(?:\.\d+)?%?')
LATIN = re.compile(r'[A-Za-z]+')
THAI_CHAR = re.compile(r'[฀-๿]')


def ordinal_key(prefix):
    p = prefix.casefold()
    return p[:-2] if p.endswith('ที่') else p


def numeric_tokens(text):
    """-> {'ordinals':[(raw_prefix,key,N,span)], 'fractions':[(a,b,span)], 'numbers':[(value,raw,span)]}.

    Digits are normalised (Thai -> Arabic, thousands commas stripped, % kept in `raw` only).
    Numbers inside an ordinal phrase or a fraction are reported only through that construct.
    """
    text = ed.norm_digits(text)
    used = []

    def free(span):
        return not any(span[0] < u[1] and u[0] < span[1] for u in used)
    ords, fracs, nums = [], [], []
    for m in ORDINAL.finditer(text):
        ords.append((m[1], ordinal_key(m[1]), str(int(m[2])), m.span()))
        used.append(m.span())
    for m in FRACTION.finditer(text):
        if free(m.span()):
            fracs.append((m[1], m[2], m.span()))
            used.append(m.span())
    for m in NUMBER.finditer(text):
        if free(m.span()):
            nums.append((m[0].rstrip('%').replace(',', ''), m[0], m.span()))
    return {'ordinals': ords, 'fractions': fracs, 'numbers': nums}


class Inputs:
    """Everything the checks read besides the episode."""

    def __init__(self, script_lines, tokens, line_starts, cuts, source=None, relevance=None, relevance_given=False):
        self.script_lines = [ed.norm_digits(l) for l in script_lines]
        self.script = '\n'.join(self.script_lines)
        self.script_nospace = re.sub(r'\s+', '', self.script)
        self.clock = ed.ScriptClock(script_lines, tokens)
        self.line_starts = line_starts
        self.cuts = cuts
        self.source = source or {'numbers': '', 'all': ''}
        self.relevance = relevance
        self.relevance_given = relevance_given
        corpus = self.script + '\n' + self.source['all']
        self.latin_corpus = {w.lower() for w in LATIN.findall(corpus)}

    def window_lines(self, t, end, neighbors):
        """Script lines overlapping [t,end] by time, widened by +-neighbors lines -> [(line_no, text)]."""
        hit = [r['line'] for r in self.line_starts if r['start'] < end and r['end'] > t]
        if not hit:
            nearest = min(self.line_starts, key=lambda r: min(abs(r['start'] - t), abs(r['end'] - t)))
            hit = [nearest['line']]
        lo, hi = min(hit) - neighbors, max(hit) + neighbors
        return [(n, self.script_lines[n - 1]) for n in range(max(1, lo), min(len(self.script_lines), hi) + 1)]


def _issue(code, severity, t, field, text, detail, **extra):
    d = {'code': code, 'severity': severity, 't': t, 'field': field, 'text': text, 'detail': detail}
    d.update(extra)
    return d


def _has_number(text, value):
    return ed.number_regex(value).search(text) is not None


def _fraction_in_lines(lines, a, b):
    ra, rb = ed.number_regex(a), ed.number_regex(b)
    return any(ra.search(l) and rb.search(l) for _, l in lines)


def _fraction_in_source(src, a, b, window):
    pa = [m.start() for m in ed.number_regex(a).finditer(src)]
    pb = [m.start() for m in ed.number_regex(b).finditer(src)]
    return any(abs(x - y) <= window for x in pa for y in pb)


# ------------------------------ checks ---------------------------------------

def check_provenance(ep, inp, th, issues):
    script_ords = {(ordinal_key(m[1]), str(int(m[2]))) for m in ORDINAL.finditer(inp.script)}
    english_ords = script_ords | {(ordinal_key(m[1]), str(int(m[2]))) for m in ORDINAL.finditer(inp.source['all'])}
    allow = {w.lower() for w in th['latinAllowlist']}
    tokenizer = None
    thai_unavailable = False
    for b in ep['beats']:
        win = inp.window_lines(b['t'], b['end'], th['lineNeighbors'])
        win_text = '\n'.join(l for _, l in win)
        span = '%d-%d' % (win[0][0], win[-1][0])
        for field, text, ws, we, kind in ed.text_fields(b):
            if field == 'cta':
                continue
            tk = numeric_tokens(text)
            for value, raw, _ in tk['numbers']:
                if not (_has_number(win_text, value) or _has_number(inp.source['numbers'], value)):
                    issues.append(_issue('provenance-number', 'error', b['t'], field, text,
                                         'number %s not in script lines %s (beat window +-%d) nor in source transcript/title/description' % (raw, span, th['lineNeighbors'])))
            for a, c, _ in tk['fractions']:
                if not (_fraction_in_lines(win, a, c) or _fraction_in_source(inp.source['numbers'], a, c, th['fractionSourceWindowChars'])):
                    issues.append(_issue('provenance-number', 'error', b['t'], field, text,
                                         'fraction %s/%s: %s and %s do not both occur in one script line of window %s nor within %d chars in the source' % (a, c, a, c, span, th['fractionSourceWindowChars'])))
            for raw_prefix, key, n, _ in tk['ordinals']:
                pool = english_ords if key in ENGLISH_ORDINALS else script_ords
                if (key, n) not in pool:
                    issues.append(_issue('provenance-ordinal', 'error', b['t'], field, text,
                                         'ordinal "%s %s" is never said (%s)' % (raw_prefix, n, 'script/source' if key in ENGLISH_ORDINALS else 'script')))
            seen = set()
            for w in LATIN.findall(text):
                lw = w.lower()
                if len(w) < th['latinMinLetters'] or lw in allow or lw in seen:
                    continue
                seen.add(lw)
                if lw not in inp.latin_corpus:
                    issues.append(_issue('provenance-latin', 'error', b['t'], field, text,
                                         'Latin word "%s" not in script, source transcript/title/description/chapters or allowlist' % w, word=w))
            thai_tokens = None
            if THAI_CHAR.search(text) and not thai_unavailable:
                if tokenizer is None:
                    try:
                        from pythainlp.tokenize import word_tokenize
                        tokenizer = word_tokenize
                    except ImportError:
                        thai_unavailable = True
                        issues.append(_issue('provenance-thai-unavailable', 'warn', None, None, None, 'pythainlp not importable; Thai token share not checked'))
                        continue
                thai_tokens = [t for t in tokenizer(text, engine='newmm') if len(t) >= th['thaiTokenMinLength'] and THAI_CHAR.search(t)]
                if thai_tokens:
                    found = [t for t in thai_tokens if t in inp.script_nospace]
                    share = len(found) / len(thai_tokens)
                    if share < th['thaiShareMin']:
                        missing = [t for t in thai_tokens if t not in found]
                        issues.append(_issue('provenance-thai', 'warn', b['t'], field, text,
                                             'only %.2f of Thai tokens occur in the script (min %.2f); missing: %s' % (share, th['thaiShareMin'], ' '.join(missing)),
                                             share=round(share, 3)))


def _anchors(field, text):
    """[(label, compiled_regex)] spoken-time anchors for one on-screen string."""
    tk = numeric_tokens(text)
    out = []
    for raw_prefix, _, n, _ in tk['ordinals']:
        out.append(('%s %s' % (raw_prefix, n), re.compile(re.escape(raw_prefix) + r'\s*' + ed.number_regex(n).pattern, re.IGNORECASE)))
    for value, raw, _ in tk['numbers']:
        out.append((raw, ed.number_regex(value)))
    if field.endswith('.big') and text.strip():
        out.append((text.strip(), ed.text_regex(text)))
    return out


def check_timing(ep, inp, th, issues, metrics):
    tol = th['timingToleranceSeconds']
    cache = {}
    checked = skipped = far = 0
    seen = set()
    for b in ep['beats']:
        for field, text, ws, we, kind in ed.text_fields(b):
            if field == 'cta':
                continue
            for label, rx in _anchors(field, text):
                key = rx.pattern + str(rx.flags)
                if key not in cache:
                    cache[key] = [o for o in inp.clock.occurrences(rx) if o[2] is not None]
                occ = cache[key]
                if not occ:
                    skipped += 1
                    continue
                checked += 1

                def dist(o):
                    return 0.0 if ws <= o[2] <= we else min(abs(o[2] - ws), abs(o[2] - we))
                best = min(occ, key=dist)
                s = best[2]
                if dist(best) > th['timingMaxDistanceSeconds']:
                    far += 1
                    continue
                key = (b['t'], field, s)
                if key in seen:      # same number reached via both the number and the whole-`big` anchor
                    continue
                seen.add(key)
                info = dict(anchor=label, spoken=round(s, 3), start=round(ws, 3), end=round(we, 3))
                if we < s:
                    issues.append(_issue('card-timing-gone-before-spoken', 'error', b['t'], field, text,
                                         '"%s" visible %.2f-%.2f but spoken at %.2f (gone %.2f s early)' % (label, ws, we, s, s - we), error=round(s - we, 3), **info))
                elif ws > s + tol:
                    issues.append(_issue('card-timing-late', 'error', b['t'], field, text,
                                         '"%s" appears at %.2f, %.2f s after it is spoken (%.2f; tolerance %.1f)' % (label, ws, ws - s, s, tol), error=round(ws - s, 3), **info))
                elif kind == 'timed' and ws < s - tol:
                    issues.append(_issue('card-timing-early', 'error', b['t'], field, text,
                                         '"%s" appears at %.2f, %.2f s before it is spoken (%.2f; tolerance %.1f)' % (label, ws, s - ws, s, tol), error=round(s - ws, 3), **info))
    metrics['timing'] = {'anchorsChecked': checked, 'anchorsNeverSpoken': skipped, 'anchorsOnlySpokenFar': far, 'toleranceSeconds': tol,
                         'maxDistanceSeconds': th['timingMaxDistanceSeconds'],
                         'misalignedScriptLines': inp.clock.misaligned_lines, 'unmatchedScriptChars': inp.clock.unmatched_chars}
    for n in inp.clock.misaligned_lines:
        issues.append(_issue('word-timing-misaligned', 'warn', None, 'script line %d' % n, inp.script_lines[n - 1][:60],
                             'word-timing tokens do not reproduce this script line exactly; anchors there use fuzzy alignment'))


def check_presenter(ep, th, issues, metrics):
    beats = ep['beats']
    first_t, vo_end = beats[0]['t'], ep['vo_end']
    vo_len = vo_end - first_t
    segs = []
    lead_end = first_t
    i = 0
    while i < len(beats) - 1 and not beats[i].get('media') and abs(beats[i]['t'] - lead_end) < 1e-6:
        lead_end = beats[i]['end']
        i += 1
    cold = min(lead_end, first_t + th['coldOpenSeconds']) if lead_end > first_t else first_t
    if lead_end > cold:
        segs.append([cold, lead_end])
    for j, b in enumerate(beats):
        if j < i or j == len(beats) - 1 or b.get('media'):
            continue
        segs.append([b['t'], b['end']])
    runs = []
    for s in sorted(segs):
        if runs and s[0] - runs[-1][1] < 1e-6:
            runs[-1][1] = s[1]
        else:
            runs.append(list(s))
    total = sum(e - s for s, e in runs)
    share = total / vo_len if vo_len > 0 else 0.0
    metrics['presenter'] = {
        'voSeconds': round(vo_len, 3), 'presenterSeconds': round(total, 3), 'share': round(share, 4),
        'coldOpenExcludedSeconds': round(cold - first_t, 3),
        'finalBeatExcluded': not beats[-1].get('media'),
        'runsAtLeastReportMin': [{'start': round(s, 3), 'end': round(e, 3), 'seconds': round(e - s, 3)} for s, e in runs if e - s >= th['presenterRunReportMin']],
        'maxPresenterShare': th['maxPresenterShare'], 'maxPresenterRun': th['maxPresenterRun'],
    }
    if share > th['maxPresenterShare']:
        issues.append(_issue('presenter-share', 'error', None, None, None,
                             'presenter-only share %.1f %% of the voice-over (%.1f s of %.1f s) exceeds %.0f %%' % (share * 100, total, vo_len, th['maxPresenterShare'] * 100), share=round(share, 4)))
    for s, e in runs:
        if e - s > th['maxPresenterRun']:
            issues.append(_issue('presenter-run', 'error', round(s, 3), None, None,
                                 'continuous presenter-only run %.2f-%.2f (%.1f s) exceeds %.1f s' % (s, e, e - s, th['maxPresenterRun']), seconds=round(e - s, 3)))


def check_cta(ep, th, issues, metrics):
    cta = ed.episode_cta(ep)
    n = len(re.sub(r'\s+', '', cta))
    metrics['cta'] = {'text': cta or None, 'chars': n}
    if n > th['maxCtaChars']:
        issues.append(_issue('cta-length', 'error', None, 'cta', cta, 'CTA has %d non-space characters (max %d)' % (n, th['maxCtaChars']), chars=n))


def check_punch(ep, issues):
    last = ep['beats'][-1]
    for b in ep['beats']:
        if not b.get('punch'):
            continue
        if b.get('origin') == 'source' and b.get('media') in ('broll', 'clip'):
            issues.append(_issue('punch-forbidden', 'error', b['t'], 'punch', None, 'punch on a source-origin clip beat (%s)' % b.get('src')))
        if b is last:
            issues.append(_issue('punch-forbidden', 'error', b['t'], 'punch', None, 'punch on the final beat'))


def check_typo_kind(ep, th, issues):
    if not th['requireTypoKind']:
        return
    for b in ep['beats']:
        if b.get('media') != 'typo':
            continue
        card = ed.typo_card(b)
        if card['kind'] not in th['typoKinds']:
            issues.append(_issue('typo-kind', 'error', b['t'], 'cardKind', str(card['kind']), 'typo beat must declare a card kind in %s' % th['typoKinds']))
        if not card['items']:
            issues.append(_issue('typo-kind', 'error', b['t'], 'items', None, 'typo beat has no items'))


def load_relevance(path):
    """Relevance verdict rows from score_relevance.py / batch_relevance.py output (see module docstring)."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise ed.EpisodeFormatError('cannot read relevance %s: %s' % (path, e))
    if isinstance(data, dict) and isinstance(data.get('results'), list):
        rows = data['results']
    elif isinstance(data, list):
        rows = data
    elif isinstance(data, dict) and all(isinstance(v, dict) for v in data.values()):
        rows = [{**v, 'src': v.get('src', k)} for k, v in data.items()]
    else:
        raise ed.EpisodeFormatError('relevance file is not a relevance report, row list or {src: row} map')
    return [r for r in rows if isinstance(r, dict)]


def check_stock(ep, inp, issues):
    verification_status = None
    for b in ep['beats']:
        if b.get('media') not in ('broll', 'clip') or b.get('origin') not in ('stock', 'ai'):
            continue
        src = b.get('src')
        if not inp.relevance_given:
            issues.append(_issue('stock-unverified', 'error', b['t'], 'src', src, 'no --relevance file: %s clip has no relevance verdict (fail closed)' % b['origin']))
            continue
        rows = [r for r in inp.relevance if r.get('src') == src]
        if not rows:
            rows = [r for r in inp.relevance if 'src' not in r and ed.num(r.get('t')) is not None and abs(ed.num(r['t']) - b['t']) < 0.05]
        if not rows:
            issues.append(_issue('stock-unverified', 'error', b['t'], 'src', src, 'no relevance verdict for %s clip %s' % (b['origin'], src)))
            continue
        if verification_status is None:
            from score_relevance import verification_status
        bad = [r for r in rows if verification_status(r, b['origin']) != 'verified']
        if bad:
            issues.append(_issue('stock-unverified', 'error', b['t'], 'src', src,
                                 'relevance verdict is not passing (score=%s readable_text=%s)' % (bad[0].get('score'), bad[0].get('readable_text'))))


def check_source_reuse(ep, inp, th, issues):
    shown = []
    for b in ep['beats']:
        if b.get('origin') != 'source' or b.get('media') not in ('clip', 'broll'):
            continue
        src = b.get('src')
        clip = inp.cuts.get(src)
        s_in = ed.num(clip.get('source_in')) if isinstance(clip, dict) else None
        if s_in is None:
            issues.append(_issue('source-reuse-unknown-clip', 'error', b['t'], 'src', src, 'source clip %s has no source_in in the cuts file; reuse cannot be checked' % src))
            continue
        r0 = s_in + (ed.num(b.get('from')) or 0.0)
        r1 = r0 + (b['end'] - b['t'])
        s_out = ed.num(clip.get('source_out'))
        if s_out is not None:
            r1 = min(r1, s_out)
        shown.append((b['t'], src, r0, r1))
    for i in range(len(shown)):
        for j in range(i + 1, len(shown)):
            (ta, sa, a0, a1), (tb, sb, b0, b1) = shown[i], shown[j]
            overlap = min(a1, b1) - max(a0, b0)
            if abs(tb - ta) < th['sourceReuseWindowSeconds'] and overlap > th['sourceReuseOverlapSeconds']:
                issues.append(_issue('source-reuse', 'error', tb, 'src', sb,
                                     '%s (%.1f-%.1f of the original) at %.2f overlaps %s (%.1f-%.1f) at %.2f by %.1f s, %.1f s apart (< %.0f s)' % (sb, b0, b1, tb, sa, a0, a1, ta, overlap, abs(tb - ta), th['sourceReuseWindowSeconds']),
                                     other=sa, other_t=ta, overlap=round(overlap, 3)))


def lint_content(ep, inp, thresholds=None):
    """Run every check -> (issues, metrics)."""
    th = {**THRESHOLDS, **(thresholds or {})}
    issues, metrics = [], {}
    check_provenance(ep, inp, th, issues)
    check_timing(ep, inp, th, issues, metrics)
    check_presenter(ep, th, issues, metrics)
    check_cta(ep, th, issues, metrics)
    check_punch(ep, issues)
    check_typo_kind(ep, th, issues)
    check_stock(ep, inp, issues)
    check_source_reuse(ep, inp, th, issues)
    counts = {}
    for i in issues:
        counts[i['code']] = counts.get(i['code'], 0) + 1
    metrics['issueCounts'] = counts
    metrics['beats'] = len(ep['beats'])
    metrics['voEnd'] = ep['vo_end']
    metrics['episodeFormat'] = ep['format']
    return issues, metrics


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--beats', required=True, help='episode.json (object or list) or legacy .tsx composition')
    ap.add_argument('--script', required=True)
    ap.add_argument('--words', required=True, help='words_by_line.txt or caption_pages_final.json')
    ap.add_argument('--line-starts', required=True)
    ap.add_argument('--cuts', required=True)
    ap.add_argument('--source-transcript')
    ap.add_argument('--source-meta')
    ap.add_argument('--chapters')
    ap.add_argument('--relevance')
    ap.add_argument('--vo-end', type=float, help='voice-over end seconds when the episode file does not carry it')
    ap.add_argument('--legacy', action='store_true', help='V3 data: apply LEGACY_OVERRIDES (no card-kind requirement)')
    ap.add_argument('--set', action='append', default=[], metavar='KEY=JSON', help='override a threshold for this run')
    ap.add_argument('--report', required=True)
    a = ap.parse_args(argv)
    paths = {k: getattr(a, k) for k in ('beats', 'script', 'words', 'line_starts', 'cuts', 'source_transcript', 'source_meta', 'chapters', 'relevance') if getattr(a, k)}
    try:
        thresholds = dict(THRESHOLDS)
        if a.legacy:
            thresholds.update(LEGACY_OVERRIDES)
        for kv in a.set:
            k, _, v = kv.partition('=')
            if k not in THRESHOLDS:
                raise ed.EpisodeFormatError('unknown threshold %r' % k)
            thresholds[k] = json.loads(v)
        script_lines = ed.load_script_lines(a.script)
        tokens = ed.load_words(a.words)
        line_starts = ed.load_line_starts(a.line_starts)
        cuts = ed.load_cuts(a.cuts)
        source = ed.load_source_text(a.source_transcript, a.source_meta, a.chapters)
        relevance = load_relevance(a.relevance) if a.relevance else None
        ep = ed.load_episode(a.beats, vo_end=a.vo_end, fallback_vo_end=line_starts[-1]['end'])
        hashes = {p: _sha(p) for p in paths.values()}
    except (ed.EpisodeFormatError, OSError, ValueError) as e:
        report = {'schema': SCHEMA, 'version': VERSION, 'pass': False,
                  'issues': [_issue('input', 'error', None, None, None, str(e))], 'metrics': {}, 'thresholds': {}, 'inputs': {}}
        Path(a.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    inp = Inputs(script_lines, tokens, line_starts, cuts, source, relevance, relevance_given=bool(a.relevance))
    issues, metrics = lint_content(ep, inp, thresholds)
    report = {'schema': SCHEMA, 'version': VERSION, 'pass': not any(i['severity'] == 'error' for i in issues),
              'issues': issues, 'metrics': metrics, 'thresholds': thresholds, 'inputs': hashes}
    out = json.dumps(report, ensure_ascii=False, indent=2)
    Path(a.report).write_text(out, encoding='utf-8')
    print(out)
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
