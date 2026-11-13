#!/usr/bin/env python3
"""timing_defects.py — the ONE set of word-timing defect detectors (used by the repair ladder of asr_transcribe.py and,
later, by finalize).  Plain stdlib; runs under any python3.

  timing_defects.py --pages caption_pages.json [--raw raw_asr.json --wav vo16k.wav] --report out.json
      exit 0 = no defect, 1 = defects (one line each on stdout), 2 = usage / unreadable / malformed input.
      --raw REQUIRES --wav (the 16 kHz wav the raw was decoded from): the raw-level rules need the silences of the audio, and
      no caller may skip them silently (exit 2 without it).  The silences are computed here with ffmpeg silencedetect
      -35 dB / 0.35 s (the values of timing_check.py and asr_transcribe.py; ffmpeg from a fixed list, never $PATH).

  from timing_defects import find_defects
  find_defects(pages, raw=None, silences=None) -> [{code, start, end, token, value, limit}]   (sorted by start, code)

`pages` = the caption_pages.json list [{start, end, words:[{w, s, e}]}] (or a dict with a "pages" list of the same shape);
`raw` = the raw_asr.json document of asr_transcribe.py (`segments[].compression_ratio/start/end/text/words[]` and
`audio.duration` are read); `silences` = [(start, end)] of the audio (detect_silences), REQUIRED whenever `raw` is given (pass [] for "no silence"):
find_defects(pages, raw) without it raises ValueError, so no caller can skip the raw-gap rule silently.  Words are checked in file order across page
boundaries.

Rules (a defect = a place where the words cannot be trusted for a karaoke highlight; numbers measured 2026-11-12/13 on
the V4 references: clean A = V261111 647 s / 1,605 words, clean B = the 336 s sample clip / 810 words; defects = the
dry-run / wp6 outputs of the old chain):
  word-too-long  a word lasts > WORD_TOO_LONG_S
  word-slow      a word lasts > WORD_SLOW_S AND > WORD_SLOW_S_PER_CHAR seconds per code point (len(w))
  zero-run       >= ZERO_RUN_MIN consecutive words of length <= ZERO_LEN_S
  squeeze        >= SQUEEZE_LETTERS script letters (non-space code points) in words that lie entirely inside a
                 SQUEEZE_WINDOW_S window that starts at a word start
  raw-loop       a raw segment with compression_ratio > RAW_LOOP_CR (needs `raw`)
  raw-word-too-long  a raw whisper word (segments[].words[]) lasting > RAW_WORD_MAX_S (needs `raw`)
  raw-gap        more than RAW_GAP_MAX_SPEECH_S seconds of SPEECH (= not inside a silence) between consecutive raw word starts
                 (also audio start -> first start, last start -> audio end): whisper dropped words (needs `raw` + `silences`)
  non-finite     a time that is not a finite number
  out-of-range   a time < 0, or after the audio end (+ RANGE_TOL_S) when `raw` gives audio.duration
  non-monotonic  a word that ends before it starts, or starts before the previous word ended
Each defect's `value` is the measured number and `limit` the threshold it broke (`code` says which way).
"""
import argparse
import hashlib
import json
import math
import os
import pwd
import subprocess
import sys
import re

# -- word-too-long: clean A max 2.453 s ('1849'), clean B max 2.613 s (a 13-char model name).  Known defects:
#    single words of 6.24 / 7.70 / 7.94 / 8.84 / 9.93 s.  7.70 s (a 13-char word) is only 0.59 s/char, so only this rule
#    catches it.
WORD_TOO_LONG_S = 4.0
# -- word-slow: in both clean references every word > 1.5 s has <= 0.613 s/char (max over ALL words: 0.613 / 0.550).
#    Known defects: 1.25 s/char (a 2-char word of 2.50 s inside a loop; 6.24 s 5-char word), 1.47 s/char (8.84 s,
#    6 chars), 1.99 s/char (7.94 / 9.93 s 4-5 char words).
WORD_SLOW_S = 1.5
WORD_SLOW_S_PER_CHAR = 0.8
# -- zero-run: a zero-length word is one with e - s <= ZERO_LEN_S (times are rounded to 1 ms).  Clean A has 3 zero-length
#    words: one run of 2 (@292.9) + one single; clean B has none.  The known defect is a run of 15 (@292.9 of the wp6
#    test pages); the dry-run's 5 zero words are single (runs of 1) inside a squeeze, which `squeeze` reports.
#    Smallest run length that passes both clean references and flags the known run: 3 (any of 3..15 would; 3 is used).
ZERO_LEN_S = 0.001
ZERO_RUN_MIN = 3
EPS = 1e-6              # float noise of differences of 3-decimal times (6.051 - 6.05 > 0.001 in binary)
# -- squeeze: max letters in any 0.25 s window: clean A 8, clean B 7.  Known defects: 297 letters / 66 words @300.54,
#    22 / 4 @320.83 (dry-run), 70 / 15 @292.9 (wp6 test pages), 88 / 18 @287.46, 37 / 12 @571.01, 55 / 12 @572.12
#    (wp6 chunked pages).
SQUEEZE_LETTERS = 20
SQUEEZE_WINDOW_S = 0.25
# -- raw-loop: temperature 0 + no conditioning (the pinned params): max segment compression_ratio 2.47 on the 647 s
#    clip, none > 3.0.  Known loop (default params): segment 294.48-319.82 s, compression_ratio 36.8.
RAW_LOOP_CR = 3.0
# -- raw-word-too-long: honest raws (4 audios, temperature 0, no conditioning): longest raw word 0.84-1.12 s.  Defect: one token '์'
#    spanning 119.82-129.12 s (9.3 s) while the words spoken there were missing.
RAW_WORD_MAX_S = 4.0
# -- raw-gap: speech between consecutive raw word starts (silences removed): honest max 1.64 s (V261111 647 s), 1.14 s (336 s sample
#    clip).  Defects: 4.17 s and 6.78 s (whisper dropouts: no raw word for 38.48-46.20 s of real speech).  A long legitimate pause
#    is a silence and does not count.
RAW_GAP_MAX_SPEECH_S = 3.0
# -- silences: the values of timing_check.py THRESHOLDS silence_noise_db / silence_min_s (asr_transcribe.py uses this function too)
SILENCE_NOISE_DB = -35
SILENCE_MIN_S = 0.35
FFMPEG_CANDIDATES = ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/usr/bin/ffmpeg')   # same list as asr_transcribe.py; $PATH is never searched
# -- out-of-range: whisper may place the last word end slightly after the last sample; more than this is an error.
RANGE_TOL_S = 0.5

TOKEN_MAX = 60          # defect `token` text is cut to this many code points (the report must stay readable)
REPORT_SCHEMA = 'yt-news-v4-timing-defects'


def _letters(w):
    return sum(1 for c in w if not c.isspace())


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _finite(x):
    return _num(x) and math.isfinite(x)


def _cut(text):
    return text if len(text) <= TOKEN_MAX else text[:TOKEN_MAX - 1] + '…'


def flatten(pages):
    """pages (list, or {"pages": list}) -> [(w, s, e)] in file order.  Raises ValueError on a malformed structure."""
    if isinstance(pages, dict):
        pages = pages.get('pages')
    if not isinstance(pages, list):
        raise ValueError('pages must be a list of {start, end, words}')
    out = []
    for pi, p in enumerate(pages):
        if not isinstance(p, dict) or not isinstance(p.get('words'), list):
            raise ValueError('page %d has no "words" list' % pi)
        for wi, w in enumerate(p['words']):
            if not isinstance(w, dict) or not isinstance(w.get('w'), str) or 's' not in w or 'e' not in w:
                raise ValueError('page %d word %d is not {w: str, s, e}' % (pi, wi))
            if not _num(w['s']) or not _num(w['e']):
                raise ValueError('page %d word %d: s / e must be numbers' % (pi, wi))
            out.append((w['w'], w['s'], w['e']))
    if not out:
        raise ValueError('pages contain no words')
    return out


def _defect(code, start, end, token, value, limit):
    return {'code': code, 'start': round(start, 3) if _finite(start) else None,
            'end': round(end, 3) if _finite(end) else None, 'token': _cut(token),
            'value': round(value, 3) if _finite(value) else (str(value) if _num(value) else value), 'limit': limit}


def _raw_words(raw):
    """[(word, start, end)] of every raw word in file order; ValueError on a malformed structure"""
    out = []
    for si, seg in enumerate(raw['segments']):
        if not isinstance(seg, dict):
            raise ValueError('raw segment %d is not an object' % si)
        for wi, w in enumerate(seg.get('words') or []):
            if not (isinstance(w, dict) and _finite(w.get('start')) and _finite(w.get('end'))):
                raise ValueError('raw segment %d word %d has no finite start / end' % (si, wi))
            out.append((str(w.get('word', '')), float(w['start']), float(w['end'])))
    return out


def _speech_between(a, b, silences):
    """seconds of [a, b] that are not inside a silence"""
    inside = 0.0
    for s0, s1 in silences:
        inside += max(0.0, min(b, s1) - max(a, s0))
    return (b - a) - inside


def find_defects(pages, raw=None, silences=None):
    """-> [{code, start, end, token, value, limit}] sorted by (start, code); [] = clean.  ValueError on malformed input.
    silences: [(start, end)] from detect_silences(), required with `raw` (ValueError otherwise: the raw-gap rule must never be
    skipped by accident)."""
    words = flatten(pages)
    duration = None
    if raw is not None and silences is None:
        raise ValueError('find_defects(raw=...) needs silences=[...] (detect_silences of the wav; [] = none): the raw-gap rule cannot be skipped')
    if raw is not None:
        if not isinstance(raw, dict) or not isinstance(raw.get('segments'), list):
            raise ValueError('raw must be a raw_asr document with a "segments" list')
        d = (raw.get('audio') or {}).get('duration') if isinstance(raw.get('audio'), dict) else None
        duration = d if _finite(d) and d > 0 else None
    out = []

    # -- per-word: finiteness, range, order
    good = []                                   # indices of words with finite times (the other rules only use these)
    prev_e = None
    for i, (w, s, e) in enumerate(words):
        if not (_finite(s) and _finite(e)):
            out.append(_defect('non-finite', s, e, w, s if not _finite(s) else e, 'finite'))
            continue
        good.append(i)
        if s < 0 or e < 0:
            out.append(_defect('out-of-range', s, e, w, min(s, e), 0))
        elif duration is not None and e > duration + RANGE_TOL_S:
            out.append(_defect('out-of-range', s, e, w, e, round(duration + RANGE_TOL_S, 3)))
        if e < s - EPS:
            out.append(_defect('non-monotonic', s, e, w, e - s, 0))
        elif prev_e is not None and s < prev_e - EPS:
            out.append(_defect('non-monotonic', s, e, w, s - prev_e, 0))
        prev_e = e if prev_e is None else max(prev_e, e)

    # -- per-word duration
    for i in good:
        w, s, e = words[i]
        d = e - s
        if d > WORD_TOO_LONG_S + EPS:
            out.append(_defect('word-too-long', s, e, w, d, WORD_TOO_LONG_S))
        per = d / max(1, len(w))
        if d > WORD_SLOW_S + EPS and per > WORD_SLOW_S_PER_CHAR + EPS:
            out.append(_defect('word-slow', s, e, w, per, WORD_SLOW_S_PER_CHAR))

    # -- zero-length runs (consecutive in file order; a non-finite word breaks a run)
    run = []
    for i in list(good) + [None]:
        if i is not None and words[i][2] - words[i][1] <= ZERO_LEN_S + EPS and (not run or run[-1] == i - 1):
            run.append(i)
            continue
        if len(run) >= ZERO_RUN_MIN:
            a, b = words[run[0]], words[run[-1]]
            out.append(_defect('zero-run', a[1], b[2], ' '.join(words[k][0] for k in run), len(run), ZERO_RUN_MIN))
        run = [i] if i is not None and words[i][2] - words[i][1] <= ZERO_LEN_S + EPS else []

    # -- squeeze: windows start at a word start; consecutive words that END inside the window count.  Reported
    #    windows do not overlap (the scan continues after the last word of a reported window).
    k = 0
    while k < len(good):
        i0 = good[k]
        s0 = words[i0][1]
        letters, j, last = 0, k, None
        while j < len(good) and words[good[j]][2] - s0 <= SQUEEZE_WINDOW_S + EPS:
            letters += _letters(words[good[j]][0])
            j += 1
            if letters >= SQUEEZE_LETTERS:
                last = j
        if last is not None:
            seg = [good[x] for x in range(k, j)]
            out.append(_defect('squeeze', s0, words[seg[-1]][2], ' '.join(words[x][0] for x in seg), letters, SQUEEZE_LETTERS))
            k = j
        else:
            k += 1

    # -- raw decoder loops
    if raw is not None:
        for si, seg in enumerate(raw['segments']):
            if not isinstance(seg, dict):
                raise ValueError('raw segment %d is not an object' % si)
            cr = seg.get('compression_ratio')
            if _finite(cr) and cr > RAW_LOOP_CR:
                out.append(_defect('raw-loop', seg.get('start'), seg.get('end'), str(seg.get('text') or ''), cr, RAW_LOOP_CR))

        words_raw = _raw_words(raw)
        for w, s, e in words_raw:
            if e - s > RAW_WORD_MAX_S + EPS:
                out.append(_defect('raw-word-too-long', s, e, w.strip(), e - s, RAW_WORD_MAX_S))
        sil = [(float(a), float(b)) for a, b in silences]
        marks = sorted(s for _, s, _ in words_raw)
        edges = ([0.0] if marks else []) + marks + ([duration] if duration is not None and marks and duration > marks[-1] else [])
        for a, b in zip(edges, edges[1:]):
            speech = _speech_between(a, b, sil)
            if speech > RAW_GAP_MAX_SPEECH_S + EPS:
                out.append(_defect('raw-gap', a, b, '(no raw word from %.2f to %.2f s)' % (a, b), speech, RAW_GAP_MAX_SPEECH_S))

    out.sort(key=lambda d: (d['start'] if d['start'] is not None else -1.0, d['code'], d['end'] if d['end'] is not None else -1.0))
    return out


def rules():
    return {'word_too_long_s': WORD_TOO_LONG_S, 'word_slow_s': WORD_SLOW_S, 'word_slow_s_per_char': WORD_SLOW_S_PER_CHAR,
            'zero_len_s': ZERO_LEN_S, 'zero_run_min': ZERO_RUN_MIN, 'squeeze_letters': SQUEEZE_LETTERS,
            'squeeze_window_s': SQUEEZE_WINDOW_S, 'raw_loop_cr': RAW_LOOP_CR, 'range_tol_s': RANGE_TOL_S,
            'raw_word_max_s': RAW_WORD_MAX_S, 'raw_gap_max_speech_s': RAW_GAP_MAX_SPEECH_S, 'silence_noise_db': SILENCE_NOISE_DB,
            'silence_min_s': SILENCE_MIN_S}


def resolve_ffmpeg():
    for c in FFMPEG_CANDIDATES:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def detect_silences(wav, ffmpeg=None, env=None):
    """[(start, end)] from ffmpeg silencedetect (parsed like timing_check.detect_silences).  ffmpeg / env: asr_transcribe.py passes its
    own resolved ffmpeg and minimal environment; the CLI uses the fixed list and {PATH, HOME, LANG} only.  RuntimeError on failure."""
    ffmpeg = ffmpeg or resolve_ffmpeg()
    if ffmpeg is None:
        raise RuntimeError('ffmpeg not found in %s' % ', '.join(FFMPEG_CANDIDATES))
    if env is None:
        env = {'PATH': os.path.dirname(ffmpeg) + ':/usr/bin:/bin', 'HOME': pwd.getpwuid(os.getuid()).pw_dir, 'LANG': 'en_US.UTF-8'}
    cmd = [ffmpeg, '-hide_banner', '-nostats', '-i', str(wav), '-vn', '-af',
           'silencedetect=noise=%sdB:d=%s' % (SILENCE_NOISE_DB, SILENCE_MIN_S), '-f', 'null', '-']
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    except OSError as e:
        raise RuntimeError('cannot run ffmpeg %s: %s' % (ffmpeg, e))
    if proc.returncode != 0:
        raise RuntimeError('ffmpeg silencedetect failed on %s: %s' % (wav, proc.stderr.strip()[-300:]))
    out, start = [], None
    for m in re.finditer(r'silence_(start|end):\s*(-?\d+(?:\.\d+)?)', proc.stderr):
        if m.group(1) == 'start':
            start = float(m.group(2))
        elif start is not None:
            out.append((max(start, 0.0), float(m.group(2))))
            start = None
    if start is not None:                       # the audio ends inside a silence: ffmpeg prints no silence_end for it
        dm = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', proc.stderr)
        if dm:
            end = int(dm.group(1)) * 3600 + int(dm.group(2)) * 60 + float(dm.group(3))
            if end > start:
                out.append((max(start, 0.0), end))
    return out


def describe(d):
    """One line for the agent: code, token, time, measured value, limit."""
    at = '%.3f' % d['start'] if d['start'] is not None else 'n/a'
    return 'DEFECT %s at %ss token="%s" value=%s limit=%s' % (d['code'], at, d['token'], d['value'], d['limit'])


def _write_atomic(path, text):
    tmp = '%s.tmp.%d' % (path, os.getpid())
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _sha(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description='word-timing defect detectors (exit 0 none, 1 defects, 2 usage/parse)')
    ap.add_argument('--pages', required=True, help='caption_pages.json')
    ap.add_argument('--raw', help='raw_asr.json (enables the raw-loop / raw-word-too-long / raw-gap rules and the audio-end range check); needs --wav')
    ap.add_argument('--wav', help='the 16 kHz wav the raw was decoded from (its silences feed the raw-gap rule); required with --raw')
    ap.add_argument('--report', required=True, help='JSON report to write')
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    if a.raw and not a.wav:
        print('ERROR: --raw needs --wav (the audio the raw was decoded from): the raw-gap rule measures speech against its silences '
              'and cannot be skipped', file=sys.stderr)
        return 2
    if a.wav and not a.raw:
        print('ERROR: --wav only makes sense with --raw', file=sys.stderr)
        return 2
    try:
        pages = json.load(open(a.pages, encoding='utf-8'))
        raw = json.load(open(a.raw, encoding='utf-8')) if a.raw else None
        silences = detect_silences(a.wav) if a.wav else None
        defects = find_defects(pages, raw, silences)
        nwords = len(flatten(pages))
    except RuntimeError as e:
        print('ERROR: %s' % e, file=sys.stderr)
        return 2
    except (OSError, ValueError) as e:
        print('ERROR: %s' % e, file=sys.stderr)
        return 2
    rep = {'schema': REPORT_SCHEMA, 'version': 1, 'pages': a.pages, 'pages_sha256': _sha(a.pages),
           'raw': a.raw, 'raw_sha256': _sha(a.raw) if a.raw else None, 'wav': a.wav, 'wav_sha256': _sha(a.wav) if a.wav else None,
           'words': nwords, 'rules': rules(),
           'ok': not defects, 'defects': defects}
    try:
        _write_atomic(a.report, json.dumps(rep, ensure_ascii=False, indent=1) + '\n')
    except OSError as e:
        print('ERROR: cannot write %s: %s' % (a.report, e), file=sys.stderr)
        return 2
    for d in defects:
        print(describe(d))
    print('%s: %d words, %d defect(s) -> %s' % ('OK' if not defects else 'DEFECTS', nwords, len(defects), a.report))
    return 1 if defects else 0


if __name__ == '__main__':
    sys.exit(main())
