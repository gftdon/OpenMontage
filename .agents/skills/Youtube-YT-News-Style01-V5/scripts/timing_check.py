#!/usr/bin/env python3
"""Is this word timing really measured from the audio? (sync record for the on-screen cards)

  timing_check.py --audio avatar.mp4 --words words_by_line.txt|caption_pages_final.json
                  [--pages caption_pages.json] [--srt avatar.srt] [--line-starts line_starts.json] --report out.json

Principle: speech cannot START inside a silence. ffmpeg silencedetect finds the silences of the AUDIO; a
token whose start falls in the INTERIOR of one ([silence_start + 0.10, silence_end - 0.40]) is not where the
audio is speaking. Timing measured from this audio has (almost) none; timing shifted or hand-typed has many.

Errors (any one fails the check):
  tokens-in-silence  share of such tokens > maxInSilenceShare (0.5 %), or >= maxInSilencePerWindow (3) of them
                     inside any 30 s window  -> metrics.inSilence lists them (time + text, capped at 30)
  too-few-anchors    fewer than 10 detected silences or fewer than 200 tokens: cannot verify
  srt-copied         (--srt) >= 80 % of line starts sit within 0.05 s of an SRT cue start: taken from the SRT
  non-monotonic      token starts go backwards
  flat-run           >= 5 fine / 8 coarse consecutive tokens spaced exactly evenly (to 0.01 s) over > 1 s: hand-typed/interpolated
Warnings (never fail): tokens-in-silence-few (1+ offending tokens below the thresholds: a patched spot) and
  onset-mismatch (< 90 % of phrase starts have a silence-end onset within +-0.30 s; all onset metrics are kept
  as information: Whisper word starts lead the detected onset by ~0.2 s, so this is not a gate).

On pass the report is the sync record: {"schema":"yt-news-v4-timing-check","version":1,"pass":true,
"status":"accepted","metrics":{...},"inputs":{path: sha256},"thresholds":{...}}.
Exit 0 pass / 1 fail / 2 bad input / 4 ffmpeg missing.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import bisect
import re
import statistics
import subprocess
import sys

SCHEMA = 'yt-news-v4-timing-check'
VERSION = 1
THRESHOLDS = {
    'silence_noise_db': -35,        # silencedetect noise floor
    'silence_min_s': 0.35,          # silencedetect minimum silence
    'phrase_gap_ends_s': 0.45,      # token end -> next token start gap that implies a pause (ends available)
    'phrase_gap_starts_s': 1.2,     # token start -> next token start gap that implies a pause (starts only)
    'onset_tolerance_s': 0.30,      # phrase start <-> detected onset
    'min_match_ratio': 0.90,
    'minSilences': 10,                    # fewer detected silences -> cannot verify
    'minTokens': 200,                     # fewer tokens -> cannot verify
    'silenceInteriorLeadS': 0.10,         # interior = [silence_start + lead, silence_end - trail]
    'silenceInteriorTrailS': 0.40,
    'maxInSilenceShare': 0.005,
    'maxInSilencePerWindow': 3,
    'inSilenceWindowS': 30,
    'inSilenceListCap': 30,
    'srt_start_tolerance_s': 0.05,
    'srt_copied_ratio': 0.80,
    'flat_min_tokens': 5,
    'flat_min_tokens_coarse': 8,          # starts on a 0.1 s grid (words_by_line.txt): equal spacing happens by chance
    'flat_min_span_s': 1.0,
    'flat_spacing_tolerance_s': 0.0101,   # "exactly even to 0.01 s"
    'flat_min_spacing_s': 0.02,           # zero/duplicate starts are not an interpolation signature
    'contiguous_ends_ratio': 0.95,        # ends equal to next start for >= this share -> ends carry no pause info
}


class BadInput(Exception):
    pass


class FfmpegMissing(Exception):
    pass


# ------------------------------------------------------------------ inputs

def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _num(v, what):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise BadInput(f'{what}: expected a number, got {v!r}')
    return float(v)


def parse_words_txt(text):
    """`L<n>: word@time word@time ...` (tokens may contain spaces) -> tokens [{w,s,e:None,line}]."""
    toks = []
    for raw in text.splitlines():
        m = re.match(r'\s*L(\d+):\s*(.*)$', raw)
        if not m:
            continue
        for t in re.finditer(r'(\S.*?)@(-?\d+(?:\.\d+)?)(?=\s|$)', m.group(2)):
            toks.append({'w': t.group(1), 's': float(t.group(2)), 'e': None, 'line': int(m.group(1))})
    return toks


def parse_words_json(data):
    """caption_pages_final.json (pages[].chunks[].sourceTokens|tokens) or caption_pages.json
    (pages[].words) or a flat token list -> tokens [{w,s,e,line:None}]."""
    if isinstance(data, dict):
        data = data.get('pages') or data.get('words') or data.get('tokens') or []
    if not isinstance(data, list):
        raise BadInput('words json: expected a list of pages or tokens')
    toks = []

    def add(t):
        if not isinstance(t, dict) or 's' not in t:
            raise BadInput(f'words json: bad token {t!r}')
        toks.append({'w': str(t.get('w', '')), 's': _num(t['s'], 'token start'),
                     'e': _num(t['e'], 'token end') if t.get('e') is not None else None, 'line': None})

    for p in data:
        if isinstance(p, dict) and 'chunks' in p:
            for c in p['chunks']:
                for t in (c.get('sourceTokens') or c.get('tokens') or []):
                    add(t)
        elif isinstance(p, dict) and 'words' in p:
            for t in p['words']:
                add(t)
        elif isinstance(p, dict) and 'tokens' in p:
            for t in p['tokens']:
                add(t)
        else:
            add(p)
    return toks


def load_words(path):
    p = Path(path)
    if not p.is_file():
        raise BadInput(f'no such file: {path}')
    text = p.read_text(encoding='utf-8')
    if p.suffix.lower() == '.json':
        try:
            toks = parse_words_json(json.loads(text))
        except json.JSONDecodeError as e:
            raise BadInput(f'{path}: invalid JSON ({e})')
    else:
        toks = parse_words_txt(text)
    if not toks:
        raise BadInput(f'{path}: no word-timing tokens found')
    return toks


def load_pages(path):
    """Canonical caption_pages.json only: ordered pages[].words, never a fallback timing source."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(data, list) or not data:
            raise ValueError('expected a nonempty list of pages')
        tokens = []
        for i, page in enumerate(data):
            if not isinstance(page, dict) or not isinstance(page.get('words'), list):
                raise ValueError(f'page {i}: expected words list')
            for j, token in enumerate(page['words']):
                if not isinstance(token, dict) or not isinstance(token.get('w'), str) or not token['w']:
                    raise ValueError(f'page {i} word {j}: expected nonempty text')
                start = _num(token.get('s'), 'pages token start')
                end = _num(token.get('e'), 'pages token end')
                if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
                    raise ValueError(f'page {i} word {j}: invalid time range')
                tokens.append({'w': token['w'], 's': start, 'e': end, 'line': None})
        if not tokens:
            raise ValueError('no page words found')
        return tokens
    except (OSError, ValueError, TypeError, OverflowError, RecursionError, BadInput) as e:
        raise BadInput(f'pages {path}: {e}') from e


def timing_source_mismatch(tokens, pages):
    """Bind flattened identity/order and the exact legacy :.1f serialization (not an epsilon)."""
    if len(tokens) != len(pages):
        return {'code': 'timing-source-mismatch', 'fields': ['count'], 'index': min(len(tokens), len(pages)),
                'message': f'pages count {len(pages)} != words count {len(tokens)}'}
    for i, (word, page) in enumerate(zip(tokens, pages)):
        fields = [key for key in ('w', 's') if
                  (word[key] != page[key] if key == 'w' else word[key] != float(format(page[key], '.1f')))]
        if fields:
            return {'code': 'timing-source-mismatch', 'fields': fields, 'index': i,
                    'message': f'pages and words differ at index {i}: {", ".join(fields)}'}
    return None


def parse_srt_starts(text):
    out = []
    for m in re.finditer(r'(\d+):(\d{2}):(\d{2})[,.](\d{3})\s*-->', text):
        h, mi, s, ms = (int(x) for x in m.groups())
        out.append(h * 3600 + mi * 60 + s + ms / 1000)
    return out


def load_line_starts(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return {int(d['line']): float(d['start']) for d in data}
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise BadInput(f'{path}: not a line_starts.json ({e})')


# ------------------------------------------------------------------ audio

def detect_silences(audio, th=THRESHOLDS):
    """[(silence_start, silence_end)] from ffmpeg silencedetect (a silence that runs to the end of the file
    is closed by ffmpeg at EOF). `silence_end` of each is a speech onset."""
    cmd = ['ffmpeg', '-hide_banner', '-nostats', '-i', str(audio), '-vn', '-af',
           f"silencedetect=noise={th['silence_noise_db']}dB:d={th['silence_min_s']}", '-f', 'null', '-']
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise FfmpegMissing('ffmpeg not found on PATH')
    if proc.returncode != 0:
        raise BadInput(f'ffmpeg could not decode {audio}: {proc.stderr.strip()[-300:]}')
    out, start = [], None
    for m in re.finditer(r'silence_(start|end):\s*(-?\d+(?:\.\d+)?)', proc.stderr):
        if m.group(1) == 'start':
            start = float(m.group(2))
        elif start is not None:
            out.append((max(start, 0.0), float(m.group(2))))
            start = None
    return out


def tokens_in_silence(tokens, silences, th=THRESHOLDS):
    """[(index, token)] whose start lies in the interior of a silence."""
    interiors = sorted((a + th['silenceInteriorLeadS'], b - th['silenceInteriorTrailS']) for a, b in silences)
    interiors = [(lo, hi) for lo, hi in interiors if hi >= lo]
    los = [lo for lo, _ in interiors]
    out = []
    for i, t in enumerate(tokens):
        k = bisect.bisect_right(los, t['s']) - 1
        if k >= 0 and t['s'] <= interiors[k][1]:
            out.append((i, t))
    return out


def phrase_starts(tokens, th=THRESHOLDS):
    """Indexes of tokens that follow a pause. Returns (indexes, mode) with mode 'ends' or 'starts'."""
    pairs = [(a, b) for a, b in zip(tokens, tokens[1:]) if a['e'] is not None]
    contiguous = (sum(1 for a, b in pairs if abs(a['e'] - b['s']) <= 0.005) / len(pairs)) if pairs else 1.0
    use_ends = bool(pairs) and len(pairs) >= 0.5 * (len(tokens) - 1) and contiguous < th['contiguous_ends_ratio']
    out = []
    for i in range(1, len(tokens)):
        a, b = tokens[i - 1], tokens[i]
        gap = (b['s'] - a['e']) if use_ends and a['e'] is not None else (b['s'] - a['s'])
        if gap >= (th['phrase_gap_ends_s'] if use_ends else th['phrase_gap_starts_s']):
            out.append(i)
    return out, ('ends' if use_ends else 'starts')


def _pct(vals, q):
    vals = sorted(vals)
    if not vals:
        return None
    k = (len(vals) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def match_onsets(anchor_times, onsets, tol):
    rows = []
    for t in anchor_times:
        err = min((abs(t - o) for o in onsets), default=float('inf'))
        rows.append({'t': t, 'err': err, 'matched': err <= tol})
    return rows


def is_coarse(tokens):
    """True when (nearly) every start sits on a 0.1 s grid, i.e. the file was rounded to one decimal."""
    return bool(tokens) and sum(1 for t in tokens if abs(t['s'] * 10 - round(t['s'] * 10)) < 1e-6) >= 0.99 * len(tokens)


def find_flat_runs(tokens, th=THRESHOLDS):
    """Runs of >= flat_min_tokens consecutive tokens with the same start spacing (to 0.01 s), > flat_min_span_s.
    On a 0.1 s grid equal spacing is common by chance, so such files need flat_min_tokens_coarse tokens."""
    min_tokens = th['flat_min_tokens_coarse'] if is_coarse(tokens) else th['flat_min_tokens']
    runs, i, n = [], 0, len(tokens)
    while i < n - 1:
        d0 = tokens[i + 1]['s'] - tokens[i]['s']
        j = i + 1
        if d0 >= th['flat_min_spacing_s']:
            while j + 1 < n and abs((tokens[j + 1]['s'] - tokens[j]['s']) - d0) <= th['flat_spacing_tolerance_s']:
                j += 1
        count = j - i + 1
        span = tokens[j]['s'] - tokens[i]['s']
        if d0 >= th['flat_min_spacing_s'] and count >= min_tokens and span > th['flat_min_span_s']:
            runs.append({'first_index': i, 'last_index': j, 'tokens': count, 'start': tokens[i]['s'],
                         'end': tokens[j]['s'], 'spacing': round(d0, 3)})
            i = j + 1
        else:
            i += 1
    return runs


def analyse(tokens, silences, srt_starts=None, line_starts=None, th=THRESHOLDS, pages=None):
    """-> (errors, warnings, metrics). `silences` = [(start, end)]; onsets are the silence ends."""
    errors, warnings, metrics = [], [], {}
    onsets = [e for _, e in silences]
    metrics['tokens'] = len(tokens)
    metrics['onsets_detected'] = len(onsets)
    metrics['silences_detected'] = len(silences)

    # cannot verify
    if len(silences) < th['minSilences'] or len(tokens) < th['minTokens']:
        errors.append({'code': 'too-few-anchors',
                       'message': f'{len(silences)} silences detected (need >= {th["minSilences"]} detected silences) and '
                                  f'{len(tokens)} tokens (need >= {th["minTokens"]} tokens): cannot verify against the audio'})

    # tokens starting inside a silence
    bad = tokens_in_silence(tokens, silences, th)
    share = len(bad) / len(tokens) if tokens else 0.0
    listed = [{'index': i, 't': t['s'], 'w': t['w']} for i, t in bad[:th['inSilenceListCap']]]
    times = [t['s'] for _, t in bad]
    worst_window = max((bisect.bisect_right(times, x + th['inSilenceWindowS']) - j for j, x in enumerate(times)), default=0)
    by_share, by_window = share > th['maxInSilenceShare'], worst_window >= th['maxInSilencePerWindow']
    verdict = 'tokens-in-silence' if (by_share or by_window) else ('tokens-in-silence-few' if bad else 'ok')
    metrics['inSilence'] = {'share': round(share, 5), 'count': len(bad), 'tokens_total': len(tokens),
                            'silences': len(silences), 'max_in_one_window': worst_window,
                            'verdict': verdict, 'tokens': listed}
    if by_share or by_window:
        why = []
        if by_share:
            why.append(f'share {share:.2%} > {th["maxInSilenceShare"]:.1%}')
        if by_window:
            why.append(f'{worst_window} within one {th["inSilenceWindowS"]} s window (limit {th["maxInSilencePerWindow"] - 1})')
        errors.append({'code': 'tokens-in-silence',
                       'message': f'{len(bad)} of {len(tokens)} token starts fall inside a silence of the audio ({"; ".join(why)}; '
                                  f'window rule: >= {th["maxInSilencePerWindow"]} in {th["inSilenceWindowS"]} s): '
                                  'this timing is not where the audio speaks',
                       'tokens': listed})
    elif bad:
        warnings.append({'code': 'tokens-in-silence-few', 'severity': 'warn',
                         'message': f'{len(bad)} token start(s) fall inside a silence (below the failing thresholds): '
                                    'a locally patched spot? check them',
                         'tokens': listed})

    # monotonic
    back = [i for i in range(1, len(tokens)) if tokens[i]['s'] < tokens[i - 1]['s'] - 1e-9]
    if back:
        errors.append({'code': 'non-monotonic',
                       'message': f'{len(back)} token start(s) go backwards (first at index {back[0]}: '
                                  f"{tokens[back[0] - 1]['s']} -> {tokens[back[0]]['s']})",
                       'indexes': back[:20]})

    # Only flat-run uses full precision pages, after binding to the legacy timing.
    # A mismatch fails closed; it must never fall back to passing a different source.
    mismatch = timing_source_mismatch(tokens, pages) if pages is not None else None
    if mismatch:
        errors.append(mismatch)
    flat_tokens = pages if pages is not None else tokens
    min_tokens = th['flat_min_tokens_coarse'] if is_coarse(flat_tokens) else th['flat_min_tokens']
    runs = find_flat_runs(flat_tokens, th)
    metrics['flat_run_basis'] = 'pages' if pages is not None else 'words'
    metrics['flat_min_tokens_used'] = min_tokens
    metrics['flat_runs'] = len(runs)
    if runs:
        errors.append({'code': 'flat-run',
                       'message': f'{len(runs)} run(s) of >= {min_tokens} tokens evenly spaced to 0.01 s '
                                  f'(hand-typed or interpolated times), first at {runs[0]["start"]} s',
                       'runs': runs[:20]})

    # anchors / onsets
    idx, mode = phrase_starts(tokens, th)
    metrics['phrase_start_mode'] = mode
    metrics['phrase_starts'] = len(idx)
    if idx:
        rows = match_onsets([tokens[i]['s'] for i in idx], onsets, th['onset_tolerance_s'])
        for r, i in zip(rows, idx):
            r['index'], r['token'] = i, tokens[i]['w']
        ratio = sum(1 for r in rows if r['matched']) / len(rows)
        errs = [r['err'] for r in rows if r['err'] != float('inf')]
        signed = [r['t'] - min(onsets, key=lambda o: abs(r['t'] - o)) for r in rows if onsets]
        metrics.update({
            'resolution': '0.1s' if is_coarse(tokens) else 'fine',
            'onset_matched_ratio': round(ratio, 4),
            # informational only (not gating): where the misses are
            'onset_signed_error_median_s': round(statistics.median(signed), 3) if signed else None,
            'onset_ratio_within_0.5s': round(sum(1 for r in rows if r['err'] <= 0.5) / len(rows), 4),
            'onset_ratio_within_1s': round(sum(1 for r in rows if r['err'] <= 1.0) / len(rows), 4),
            'onset_abs_error_median_s': round(statistics.median(errs), 3) if errs else None,
            'onset_abs_error_p95_s': round(_pct(errs, 0.95), 3) if errs else None,
            'worst_anchors': [{'index': r['index'], 'token': r['token'], 't': r['t'],
                               'err': None if r['err'] == float('inf') else round(r['err'], 3)}
                              for r in sorted(rows, key=lambda r: -r['err'])[:10]],
        })
        if ratio < th['min_match_ratio']:
            warnings.append({'code': 'onset-mismatch', 'severity': 'warn',
                           'message': f'only {ratio:.1%} of {len(rows)} phrase starts have an audio onset within '
                                      f'+-{th["onset_tolerance_s"]} s (need {th["min_match_ratio"]:.0%}): '
                                      'informational: onset starts lead/lag by design, see inSilence for the gate'})

    # SRT
    if srt_starts is not None:
        if line_starts:
            cand, basis = sorted(line_starts.values()), 'line_starts'
        else:
            seen, cand = set(), []
            for t in tokens:
                if t['line'] is not None and t['line'] not in seen:
                    seen.add(t['line'])
                    cand.append(t['s'])
            basis = 'words_lines'
            if not cand:
                cand, basis = [tokens[i]['s'] for i in idx], 'phrase_starts'
        if not srt_starts:
            errors.append({'code': 'bad-srt', 'message': 'no cue starts found in the SRT'})
        elif cand:
            offs = [min((c - s for s in srt_starts), key=abs) for c in cand]     # words - srt
            near = sum(1 for o in offs if abs(o) <= th['srt_start_tolerance_s']) / len(offs)
            metrics['srt'] = {'basis': basis, 'candidates': len(cand), 'cues': len(srt_starts),
                              'within_tolerance_ratio': round(near, 4),
                              'offset_words_minus_srt_s': {'min': round(min(offs), 3),
                                                           'median': round(statistics.median(offs), 3),
                                                           'max': round(max(offs), 3)}}
            if near >= th['srt_copied_ratio']:
                errors.append({'code': 'srt-copied',
                               'message': f'{near:.0%} of {basis} sit within {th["srt_start_tolerance_s"]} s of an SRT cue '
                                          'start: the timing was taken from the SRT, not measured from the audio'})
    return errors, warnings, metrics


def build_report(inputs, tokens, silences, srt_starts, line_starts, pages=None):
    errors, warnings, metrics = analyse(tokens, silences, srt_starts, line_starts, pages=pages)
    ok = not errors
    return {'schema': SCHEMA, 'version': VERSION, 'pass': ok, 'status': 'accepted' if ok else 'rejected',
            'errors': errors, 'warnings': warnings, 'metrics': metrics, 'inputs': inputs, 'thresholds': THRESHOLDS}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--audio', required=True)
    ap.add_argument('--words', required=True)
    ap.add_argument('--pages', help='canonical caption_pages.json; bound full-precision source for flat-run only')
    ap.add_argument('--srt')
    ap.add_argument('--line-starts', help='line_starts.json [{line,start,...}] (when --words is a json without lines)')
    ap.add_argument('--report', required=True)
    a = ap.parse_args(argv)
    try:
        for f in (a.audio, a.words) + ((a.srt,) if a.srt else ()) + ((a.line_starts,) if a.line_starts else ()):
            if not Path(f).is_file():
                raise BadInput(f'no such file: {f}')
        tokens = load_words(a.words)
        pages = load_pages(a.pages) if a.pages is not None else None
        srt = parse_srt_starts(Path(a.srt).read_text(encoding='utf-8-sig')) if a.srt else None
        lines = load_line_starts(a.line_starts) if a.line_starts else None
        silences = detect_silences(a.audio)
        inputs = {str(Path(f)): _sha256(f) for f in [a.audio, a.words] + ([a.srt] if a.srt else []) + ([a.line_starts] if a.line_starts else []) + ([a.pages] if a.pages is not None else [])}
    except BadInput as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 2
    except FfmpegMissing as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 4
    report = build_report(inputs, tokens, silences, srt, lines, pages=pages)
    Path(a.report).parent.mkdir(parents=True, exist_ok=True)
    Path(a.report).write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    m = report['metrics']
    print(f"{'PASS' if report['pass'] else 'FAIL'} status={report['status']} tokens={m['tokens']} "
          f"in_silence={m['inSilence']['count']} ({m['inSilence']['share']:.3%}) silences={m['inSilence']['silences']} "
          f"onset_matched={m.get('onset_matched_ratio')}")
    for e in report['errors']:
        print(f"  ERROR {e['code']}: {e['message']}")
    for w in report['warnings']:
        print(f"  warn  {w['code']}: {w['message']}")
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
