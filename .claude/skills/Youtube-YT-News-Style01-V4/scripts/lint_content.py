#!/usr/bin/env python3
"""Deterministic lint of the on-screen CONTENT of a YT-News episode (CF-A67 WP2a).

Complements lint_beats.py (geometry/hold). Offline, no network, no model calls, fail-closed:
a missing or unreadable input exits 2. issue = {code, severity:'error'|'warn', t, field, text, detail, ...};
only 'error' fails the run.

Checks: schema (delegated to episode_schema.mjs), provenance-number / -ordinal / -latin / -thai,
card-timing-*, presenter-share/-run, cta-length, punch-forbidden, stock-unverified, source-reuse, and
the shown-vs-said checks on source clips (evidence-missing, cue-mismatch, window-evidence-unavailable,
subject-not-in-window, evidence-weak, label-latin-not-in-window), typo-filler. Thresholds: content_thresholds.py.

What the evidence checks prove, plainly: that a subject term (a word of >= 4 characters, not a stopword) occurs in the ORIGINAL video's
transcript or in the OCR of the frames at the time the clip was cut from. They do NOT prove that the picture matches the narration; that needs
a judge (a model or a person). Chapter titles are never evidence. `report.metrics.evidence.matches` lists, per source beat and term, which
source (`ocr` / `transcript`) matched each word, so a human can audit it.
Structural episode rules (S01-S20, including S09 clip length, S12 punch, S20 last beat / CTA) belong to the engine
workstream's episode_schema.mjs; this file calls it and does not re-implement them. The only copy kept is
punch-forbidden for legacy (list / TSX) replay data, where there is no schema.

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
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import episode_data as ed
from content_thresholds import THRESHOLDS, LEGACY_OVERRIDES

SCHEMA = 'yt-news-v4-content-lint'
VERSION = 1

ORDINAL = re.compile(r'(?<![A-Za-z])(ขั้นตอนที่|รอบที่|ครั้งที่|ขั้นที่|ข้อที่|อันดับที่?|รุ่นที่|ตอนที่|เวอร์ชัน|Round|Step|Pass|Part)\s*(\d+)', re.IGNORECASE)
ENGLISH_ORDINALS = {'round', 'step', 'pass', 'part'}
# "8/10", "8 จาก 10", "8 ใน 10", "8 เต็ม 10", "8 of 10", "8 out of 10": one construct, the same provenance rule
FRACTION = re.compile(r'(?<![\d.,])(\d+(?:\.\d+)?)\s*(?:/|จาก|ใน|เต็ม|(?:out\s+of|of)\b)\s*(\d+(?:\.\d+)?)(?!\d)', re.IGNORECASE)
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

    def __init__(self, script_lines, tokens, line_starts, cuts, source=None, relevance=None, relevance_given=False,
                 evidence=None, frames=None, timed=None, chapters=None, legacy=False, frames_given=False, frame_counts=None):
        self.script_lines = [ed.norm_digits(l) for l in script_lines]
        self.script = '\n'.join(self.script_lines)
        self.script_nospace = re.sub(r'\s+', '', self.script)
        self.clock = ed.ScriptClock(script_lines, tokens)
        self.nscript = self.clock.nstream          # script with Thai number words replaced by digits
        self.nlines = self.clock.nlines
        self.line_starts = line_starts
        self.cuts = cuts
        self.source = {'numbers': '', 'all': '', 'title': '', 'meta': '', **(source or {})}
        self.evidence = evidence or []
        self.frames = frames or {}          # {(t, src): [ocr line, ...]}
        self.frames_given = frames_given    # a frame_checks report was supplied: every evidence entry must have frames in it
        self.frame_counts = frame_counts or {}   # {(t, src): number of evidence frames in the report}
        self.timed = timed or []            # timed transcript of the original video
        self.chapters = chapters or []      # [{start, end, title}]
        self.legacy = legacy
        self.relevance = relevance
        self.relevance_given = relevance_given
        corpus = self.script + '\n' + self.source['all']
        self.latin_corpus = {w.lower() for w in LATIN.findall(corpus)}


def _issue(code, severity, t, field, text, detail, **extra):
    d = {'code': code, 'severity': severity, 't': t, 'field': field, 'text': text, 'detail': detail}
    d.update(extra)
    return d


def _has_number(text, value):
    return ed.number_regex(value).search(text) is not None


def _fraction_in_script(inp, a, b, window):
    """Both numbers of a fraction occur in ONE script line, or in two ADJACENT lines no further apart than `window` characters
    (numeric view: Thai number words read as digits, so "3 เต็ม สิบ" and "3/10" are the same)."""
    ra, rb = ed.number_regex(a), ed.number_regex(b)
    lines = inp.nlines
    if any(ra.search(l) and rb.search(l) for l in lines):
        return True
    for i in range(len(lines) - 1):
        joined = lines[i] + '\n' + lines[i + 1]
        pa = [m.start() for m in ra.finditer(joined)]
        pb = [m.start() for m in rb.finditer(joined)]
        if any(abs(x - y) <= window for x in pa for y in pb):
            return True
    return False


def _fraction_in_source(src, a, b, window):
    pa = [m.start() for m in ed.number_regex(a).finditer(src)]
    pb = [m.start() for m in ed.number_regex(b).finditer(src)]
    return any(abs(x - y) <= window for x in pa for y in pb)


# ------------------------------ checks ---------------------------------------

thai_tokenizer = ed.thai_tokenizer


def iter_fields(ep):
    """Every on-screen string: (context_start, context_end, issue_t, (field, text, ws, we, kind)).

    Beat fields use their beat as context window; episode-level fields (cta, endcard.*, chrome) their own.
    """
    for b in ep['beats']:
        for f in ed.text_fields(b):
            yield b['t'], b['end'], b['t'], f
    for f in ed.episode_text_fields(ep):
        yield f[2], f[3], f[2], f


def _unit_after(text, end):
    """Unit word immediately after a number in on-screen text: first Thai word (newmm) or Latin word >= 2 letters."""
    rest = text[end:].lstrip()
    m = re.match(r'[A-Za-z]{2,}', rest)
    if m:
        return m[0]
    if rest and THAI_CHAR.match(rest):
        tok = thai_tokenizer()
        if tok:
            for t in tok(rest, engine='newmm'):
                if t.strip():
                    return t if THAI_CHAR.search(t) and len(t) >= 2 else None
    return None


def number_severity(raw, value, ntext, span, inp):
    """(severity, note) for a number that is not said anywhere.

    warn : leading-zero enumeration label ("01"), or a single significant digit that is not followed by a
           unit word occurring in the script (editorial count of listed items: "3 จุดเปลี่ยน", "RULE 7").
    error: >= 2 significant digits, a number containing , . %, or a single digit followed by a unit word
           that does occur in the script (the count then contradicts or is absent from what is said).
    """
    if re.fullmatch(r'0\d+', raw):
        return 'warn', ' (leading-zero enumeration label, warn only)'
    if len(re.sub(r'\D', '', value).lstrip('0')) >= 2 or any(c in raw for c in ',.%'):
        return 'error', ''
    unit = _unit_after(ntext, span[1])
    if unit and unit.casefold() in inp.script.casefold():
        return 'error', ' (single digit counting "%s", a noun the script uses)' % unit
    return 'warn', ' (single digit: editorial count, its unit noun is not in the script; warn only)'


def cross_stat_fractions(beat):
    """Stats whose `big` + `label` together form one fraction ("8" + "/10", "3" + "จาก 10 รอบ", "5" + "of 10").
    -> [(stat index, combined text, a, c)]; fractions that lie inside one field are found by numeric_tokens on that field."""
    out = []
    for i, st in enumerate(beat.get('stats') or []):
        if not isinstance(st, dict) or not isinstance(st.get('big'), str) or not isinstance(st.get('label'), str):
            continue
        big, label = st['big'].strip(), st['label'].strip()
        combined = big + ' ' + label
        for a, c, span in numeric_tokens(combined)['fractions']:
            if span[0] < len(big) < span[1]:          # crosses the boundary between the two fields
                out.append((i, combined, a, c))
    return out


def check_provenance(ep, inp, th, issues, metrics):
    """provenance-number/-ordinal/-latin/-thai (+ typo-filler). Numbers and ordinals are searched in the WHOLE script
    (Thai number words read as numbers) plus the source transcript/title/description. A fraction ("8/10", "8 เต็ม 10",
    "8 of 10", a stat's big + label) needs both numbers in one script line or two adjacent lines (see _fraction_in_script).
    The chrome fields in `chromeNumberFields` (breakingLabel, officialTag) get the number / ordinal checks only."""
    script_ords = {(ordinal_key(m[1]), str(int(m[2]))) for m in ORDINAL.finditer(inp.nscript)}
    thai_ord_numbers = {n for (key, n) in script_ords if key not in ENGLISH_ORDINALS}
    english_ords = script_ords | {(ordinal_key(m[1]), str(int(m[2]))) for m in ORDINAL.finditer(inp.source['all'])}
    allow = {w.lower() for w in th['latinAllowlist']}
    editorial = set(th['latinEditorialFields'])
    chrome_numbers = set(th['chromeNumberFields'])
    win = th['fractionSourceWindowChars']
    tokenizer = None
    thai_unavailable = False
    latin = {'editorial': 0, 'dataBearing': 0}
    typo = {'texts': 0, 'unsupported': 0, 'examples': []}
    typo_ts = {b['t'] for b in ep['beats'] if b.get('media') == 'typo'}
    # Numbers printed in the page's date label (e.g. "11 พ.ย. 2026") are known provenance for the end card ONLY
    # (its eyebrow repeats the month / year); they never excuse a number in a beat, stat, card, kicker or cta.
    date_label = (ep.get('top') or {}).get('dateLabel')
    date_numbers = {v for v, _, _ in numeric_tokens(date_label)['numbers']} if isinstance(date_label, str) else set()
    # fractions split over a stat's big + label: checked as ONE fraction; their two numbers are not checked again one by one
    skip = {}
    for b in ep['beats']:
        for i, combined, a, c in cross_stat_fractions(b):
            skip.setdefault((b['t'], 'stats[%d].big' % i), set()).add(a)
            skip.setdefault((b['t'], 'stats[%d].label' % i), set()).add(c)
            if not (_fraction_in_script(inp, a, c, win) or _fraction_in_source(inp.source['numbers'], a, c, win)):
                issues.append(_issue('provenance-number', 'error', b['t'], 'stats[%d]' % i, combined,
                                     'fraction %s/%s (big + label): %s and %s do not both occur in one script line or two adjacent lines (within %d chars) nor within %d chars in the source' % (a, c, a, c, win, win)))
    for ctx_t, ctx_end, it, (field, text, ws, we, kind) in iter_fields(ep):
        numbers_only = kind == 'chrome' and field in chrome_numbers
        if kind == 'chrome' and not numbers_only:
            continue
        ntext = ed.norm_digits(text)
        tk = numeric_tokens(text)
        skipped = skip.get((it, field), ())
        for value, raw, span in tk['numbers']:
            if value in skipped:
                continue
            if _has_number(inp.nscript, value) or _has_number(inp.source['numbers'], value):
                continue
            if field.startswith('endcard.') and value in date_numbers:
                continue
            sev, why = number_severity(raw, value, ntext, span, inp)
            issues.append(_issue('provenance-number', sev, it, field, text,
                                 'number %s is not said anywhere in the script (digits or Thai number words) nor in the source transcript/title/description%s' % (raw, why)))
        for a, c, _ in tk['fractions']:
            if not (_fraction_in_script(inp, a, c, win) or _fraction_in_source(inp.source['numbers'], a, c, win)):
                issues.append(_issue('provenance-number', 'error', it, field, text,
                                     'fraction %s/%s: %s and %s do not both occur in one script line or two adjacent lines (within %d chars) nor within %d chars in the source' % (a, c, a, c, win, win)))
        for raw_prefix, key, n, _ in tk['ordinals']:
            if key in ENGLISH_ORDINALS:
                if (key, n) in english_ords:
                    continue
                if n in thai_ord_numbers:
                    issues.append(_issue('provenance-ordinal', 'warn', it, field, text,
                                         'English ordinal "%s %s" is a translation of a spoken Thai ordinal %s (not said in English)' % (raw_prefix, n, n)))
                else:
                    issues.append(_issue('provenance-ordinal', 'error', it, field, text,
                                         'ordinal "%s %s" is never said (neither in English in script/source nor as a Thai ordinal)' % (raw_prefix, n)))
            elif (key, n) not in script_ords:
                issues.append(_issue('provenance-ordinal', 'error', it, field, text, 'ordinal "%s %s" is never said (script)' % (raw_prefix, n)))
        if numbers_only:
            continue                        # page chrome: its words need no provenance
        seen = set()
        for w in LATIN.findall(text):
            lw = w.lower()
            if len(w) < th['latinMinLetters'] or lw in allow or lw in seen:
                continue
            seen.add(lw)
            if lw not in inp.latin_corpus:
                latin['editorial' if field in editorial else 'dataBearing'] += 1
                issues.append(_issue('provenance-latin', 'warn', it, field, text,
                                     'Latin word "%s" not in script, source transcript/title/description/chapters or allowlist (may be a translation)' % w, word=w))
        is_typo_text = it in typo_ts and field.startswith(('cards[', 'items[', 'vs.'))
        if is_typo_text:
            typo['texts'] += 1
        if THAI_CHAR.search(text) and not thai_unavailable and field != 'cta' and not field.startswith('endcard.'):
            if tokenizer is None:
                tokenizer = thai_tokenizer()
                if tokenizer is None:
                    thai_unavailable = True
                    issues.append(_issue('provenance-thai-unavailable', 'warn', None, None, None, 'pythainlp not importable; Thai token share not checked'))
                    continue
            thai_tokens = [t for t in tokenizer(text, engine='newmm') if len(t) >= th['thaiTokenMinLength'] and THAI_CHAR.search(t)]
            if thai_tokens:
                found = [t for t in thai_tokens if t in inp.script_nospace]
                share = len(found) / len(thai_tokens)
                if share < th['thaiShareMin']:
                    missing = [t for t in thai_tokens if t not in found]
                    issues.append(_issue('provenance-thai', 'warn', it, field, text,
                                         'only %.2f of Thai tokens occur in the script (min %.2f); missing: %s' % (share, th['thaiShareMin'], ' '.join(missing)),
                                         share=round(share, 3)))
                    if is_typo_text:
                        typo['unsupported'] += 1
                        if len(typo['examples']) < 5:
                            typo['examples'].append({'t': it, 'field': field, 'text': text})
    metrics['latin'] = {**latin, 'warn': latin['editorial'] + latin['dataBearing'], 'error': 0}
    share = typo['unsupported'] / typo['texts'] if typo['texts'] else 0.0
    metrics['typoFiller'] = {'texts': typo['texts'], 'unsupported': typo['unsupported'], 'share': round(share, 4), 'maxShare': th['typoFillerMaxShare']}
    if typo['texts'] and not thai_unavailable and share > th['typoFillerMaxShare']:
        issues.append(_issue('typo-filler', 'error', None, None, None,
                             '%d of %d typo card / item texts (%.0f %%) have Thai words the script does not support (max %.0f %%); first: %s' % (
                                 typo['unsupported'], typo['texts'], share * 100, th['typoFillerMaxShare'] * 100,
                                 '; '.join('t=%.2f %s "%s"' % (e['t'], e['field'], e['text']) for e in typo['examples'])),
                             share=round(share, 4), unsupported=typo['unsupported'], texts=typo['texts']))


def _norm_name(s):
    return re.sub(r'[\s\-]+', '', s.lower())


def is_product_number(ntext, span, raw, inp, min_script_count=3):
    """True when the number with its adjacent Latin word (either side) is a product/version name:
    it occurs in the source title/description or at least `min_script_count` times in the script
    (case-insensitive, ignoring `-` and spaces), e.g. "4 Carbon", "Opus 5.5", "GPT-Image-2.6"."""
    if inp is None:
        return False
    left = re.search(r'([A-Za-z]+)[\s\-]*$', ntext[:span[0]])
    right = re.match(r'[\s\-]*([A-Za-z]+)', ntext[span[1]:])
    cands = []
    if left:
        cands.append(_norm_name(left[1] + raw.rstrip('%')))
    if right:
        cands.append(_norm_name(raw.rstrip('%') + right[1]))
    meta, script = _norm_name(inp.source.get('meta', '')), _norm_name(inp.nscript)
    return any(c in meta or script.count(c) >= min_script_count for c in cands)


def anchors(field, text, th, inp=None, counts=None):
    """Specific timing anchors of one on-screen string -> ([(label, regex, unit|None, view)], ambiguous_count).

    view 'num' = search the numeric view of the script (Thai number words read as digits), 'text' = literal script.
    (a) a number with >= anchorMinDigits digits, or containing , . %;
    (b) a number directly followed by a unit word (checked again at the spoken occurrence);
    (c) a non-numeric stat `big` of >= anchorMinBigChars characters.
    An ordinal phrase ("รอบที่ 65") counts as (b) mirrored: its prefix word is the adjacent word.
    Everything else is ambiguous and is only counted.
    """
    ntext = ed.norm_digits(text)
    tk = numeric_tokens(text)
    out, ambiguous = [], 0
    for raw_prefix, _, n, _ in tk['ordinals']:
        out.append(('%s %s' % (raw_prefix, n), re.compile(re.escape(raw_prefix) + r'\s*' + ed.number_regex(n).pattern, re.IGNORECASE), None, 'num'))
    for a, c, _ in tk['fractions']:
        out.append(('%s/%s' % (a, c), ed.number_regex(a), ('frac', c), 'num'))       # spoken as the numerator next to the denominator
    for value, raw, span in tk['numbers']:
        if is_product_number(ntext, span, raw, inp):
            if counts is not None:
                counts['product'] = counts.get('product', 0) + 1
            continue
        if len(re.sub(r'\D', '', value)) >= th['anchorMinDigits'] or any(c in raw for c in ',.%'):
            out.append((raw, ed.number_regex(value), None, 'num'))
            continue
        unit = _unit_after(ntext, span[1])
        if unit:
            out.append(('%s %s' % (raw, unit), ed.number_regex(value), unit, 'num'))
        else:
            ambiguous += 1
    if field.endswith('.big') and not re.search(r'\d', text) and len(text.strip()) >= th['anchorMinBigChars']:
        out.append((text.strip(), ed.text_regex(text), None, 'text'))
    return out, ambiguous


def _timing_anchors(b, field, text, th, inp, counts):
    """Anchors of one on-screen string, plus the fractions that a stat's `big` + `label` form together."""
    anc, amb = anchors(field, text, th, inp, counts)
    if field.endswith('.label') and field.startswith('stats['):
        i = int(field[len('stats['):field.index(']')])
        for si, combined, fa, fc_ in cross_stat_fractions(b):
            if si == i:
                anc.append(('%s/%s' % (fa, fc_), ed.number_regex(fa), ('frac', fc_), 'num'))
    return anc, amb


def check_timing(ep, inp, th, issues, metrics):
    """card-timing-*. Whole-beat labels (kind 'beat', and every text of the final beat) can only be
    gone-before-spoken (a label may recap something said earlier); timed items (stats, cards, items with
    `at`, lower) also get late / early with the tolerance, and card-timing-far when their number is spoken
    only further than timingMaxDistanceSeconds away. Recap beats (typo summary3 / final4) and whole-beat
    labels are exempt from -far: they may legitimately restate something said long before."""
    tol = th['timingToleranceSeconds']
    cache = {}
    checked = skipped = far = far_errors = ambiguous = product = 0
    seen = set()
    far_seen = set()
    last = ep['beats'][-1]
    win = th['fractionSourceWindowChars']
    for b in ep['beats']:
        recap = b.get('typo') in ('summary3', 'final4')
        for field, text, ws, we, kind in ed.text_fields(b):
            if field == 'cta':
                continue
            label_like = kind == 'beat' or b is last
            counts = {}
            anc, amb = _timing_anchors(b, field, text, th, inp, counts)
            ambiguous += amb
            product += counts.get('product', 0)
            for label, rx, unit, view in anc:
                key = (rx.pattern, rx.flags, unit, view)
                if key not in cache:
                    if view == 'num':
                        occ = [o for o in inp.clock.occurrences_numeric(rx) if o[2] is not None]
                        if isinstance(unit, tuple):       # fraction: the denominator must be spoken right next to the numerator
                            dpos = [m.start() for m in ed.number_regex(unit[1]).finditer(inp.nscript)]
                            occ = [o for o in occ if any(abs(d - (o[4] - len(o[1]))) <= win for d in dpos)]
                        elif unit:
                            occ = [o for o in occ if inp.nscript[o[4]:].lstrip().casefold().startswith(unit.casefold())]
                    else:
                        occ = [o for o in inp.clock.occurrences(rx) if o[2] is not None]
                    cache[key] = occ
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
                    fkey = (b['t'], field, label)
                    if not label_like and not recap and fkey not in far_seen:
                        far_seen.add(fkey)
                        far_errors += 1
                        issues.append(_issue('card-timing-far', 'error', b['t'], field, text,
                                             '"%s" is shown %.2f-%.2f but never spoken within %.0f s of that window (nearest spoken at %.2f, %.0f s away)' % (
                                                 label, ws, we, th['timingMaxDistanceSeconds'], s, dist(best)),
                                             anchor=label, spoken=round(s, 3), start=round(ws, 3), end=round(we, 3), distance=round(dist(best), 3)))
                    continue
                dkey = (b['t'], field, s)
                if dkey in seen:      # same number reached via both the number and the whole-`big` anchor
                    continue
                seen.add(dkey)
                info = dict(anchor=label, spoken=round(s, 3), start=round(ws, 3), end=round(we, 3))
                if we < s:
                    issues.append(_issue('card-timing-gone-before-spoken', 'error', b['t'], field, text,
                                         '"%s" visible %.2f-%.2f but spoken at %.2f (gone %.2f s early)' % (label, ws, we, s, s - we), error=round(s - we, 3), **info))
                elif label_like:
                    continue
                elif ws > s + tol:
                    issues.append(_issue('card-timing-late', 'error', b['t'], field, text,
                                         '"%s" appears at %.2f, %.2f s after it is spoken (%.2f; tolerance %.1f)' % (label, ws, ws - s, s, tol), error=round(ws - s, 3), **info))
                elif ws < s - tol:
                    issues.append(_issue('card-timing-early', 'error', b['t'], field, text,
                                         '"%s" appears at %.2f, %.2f s before it is spoken (%.2f; tolerance %.1f)' % (label, ws, s - ws, s, tol), error=round(s - ws, 3), **info))
    metrics['timing'] = {'anchorsChecked': checked, 'anchorsNeverSpoken': skipped, 'anchorsOnlySpokenFar': far, 'farErrors': far_errors,
                         'ambiguousAnchors': ambiguous, 'productNameAnchors': product, 'toleranceSeconds': tol,
                         'maxDistanceSeconds': th['timingMaxDistanceSeconds'],
                         'thaiNumberRunsInScript': len(inp.clock.number_runs),
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
        'runsOver7': [{'start': round(s, 3), 'end': round(e, 3), 'seconds': round(e - s, 3)} for s, e in runs if e - s >= th['presenterRunReportMin']],
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


def check_punch(ep, issues, schema_owns=False):
    """Punch is allowed only on presenter full-screen beats (mode 'full') and never at/after ctaT.

    Without ctaT (legacy data) the fallback is: no punch on the final beat.
    For a V4 episode object this is episode_schema.mjs rule S12 (reported by us as code `schema`), so
    `schema_owns` switches this copy off and the two can never disagree; it stays for legacy list / TSX replays.
    """
    if schema_owns:
        return
    last = ep['beats'][-1]
    cta_t = ep.get('cta_t')
    for b in ep['beats']:
        punches = b.get('punch')
        if not punches:
            continue
        if b.get('mode') == 'pip':
            issues.append(_issue('punch-forbidden', 'error', b['t'], 'punch', None,
                                 'punch on a pip beat (%s %s); only presenter full-screen beats may punch' % (b.get('media'), b.get('src', ''))))
        late = [p for p in punches if isinstance(p, dict) and cta_t is not None and (ed.num(p.get('at', p.get('t'))) or 0) >= cta_t]
        if late:
            issues.append(_issue('punch-forbidden', 'error', b['t'], 'punch', None, 'punch at %.2f, at or after ctaT %.2f' % (ed.num(late[0].get('at', late[0].get('t'))), cta_t)))
        elif cta_t is None and b is last:
            issues.append(_issue('punch-forbidden', 'error', b['t'], 'punch', None, 'punch on the final beat (no ctaT)'))


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


def stem(word):
    """Simple plural/suffix-insensitive stem: lowercase, drop one of ing/ed/es/s, then a trailing e."""
    w = word.lower()
    for suf in ('ing', 'ed', 'es', 's'):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[:-len(suf)]
            break
    if w.endswith('e') and len(w) > 3:
        w = w[:-1]
    return w


def _stems(text):
    return {stem(w) for w in re.findall(r'[A-Za-z0-9]+', text)}


def slug_terms(src):
    """--legacy fallback subject term: the src slug minus the `yt` prefix and tokens < 3 letters, as ONE term."""
    toks = [t for t in re.split(r'[_\-\s]+', src or '') if t]
    if toks and toks[0].lower() == 'yt':
        toks = toks[1:]
    toks = [t for t in toks if len(re.sub(r'[^A-Za-z]', '', t)) >= 3]
    return [' '.join(toks)] if toks else []


def _entry_for(evidence, t, src):
    for e in evidence:
        et = ed.num(e.get('t'))
        if et is not None and abs(et - t) < 0.05 and e.get('src') == src:
            return e
    return None


def _ocr_for(frames, t, src):
    for (ft, fsrc), lines in frames.items():
        if fsrc == src and abs(ft - t) < 0.05:
            return lines
    return None


def qualifying_tokens(term, th):
    """Words of a subject term that can serve as evidence: >= subjectTokenMinLetters characters, not a stopword, not a number."""
    stop = {w.lower() for w in th['subjectStopwords']}
    return [x for x in re.findall(r'[^\W_]+', term)
            if len(x) >= th['subjectTokenMinLetters'] and not x.isdigit() and x.lower() not in stop]


def _token_hits(token, parts):
    """Which evidence sources ('transcript' / 'ocr') contain `token` (stem-insensitive for Latin words)."""
    hits = []
    for name, text in parts:
        if not text:
            continue
        if token.isascii():
            ok = stem(token) in _stems(text)
        else:
            ok = token.lower() in text.lower()
        if ok:
            hits.append(name)
    return hits


def check_evidence(ep, inp, th, issues, metrics):
    """Shown-vs-said checks on source clip beats (see module docstring). The window is the ORIGINAL video's timed transcript around the
    shown range plus the OCR of the frames of the beat; chapter titles are not evidence of what is on screen."""
    pad = th['evidenceWindowPadSeconds']
    allow = {w.lower() for w in th['latinAllowlist']}
    title_words = {w.lower() for w in LATIN.findall(inp.source.get('title', ''))}
    m = {'sourceBeats': 0, 'withEvidence': 0, 'derivedFromSlug': 0, 'windowUnavailable': 0, 'weak': 0, 'matches': []}
    for b in ep['beats']:
        if b.get('origin') != 'source' or b.get('media') not in ('clip', 'broll'):
            continue
        m['sourceBeats'] += 1
        src, t = b.get('src'), b['t']
        entry = _entry_for(inp.evidence, t, src)
        if entry is None and not inp.legacy:
            issues.append(_issue('evidence-missing', 'error', t, 'src', src, 'no visual-evidence entry for beat t=%.2f src=%s' % (t, src)))
            continue
        weak = False
        if entry is not None:
            m['withEvidence'] += 1
            terms = [x for x in (entry.get('subject_terms') or []) if isinstance(x, str)]
            if inp.frames_given and not inp.frame_counts.get(_frames_key(inp.frame_counts, t, src), 0):
                issues.append(_issue('evidence-missing', 'error', t, 'frames', src,
                                     'the evidence entry names no frames: beat t=%.2f src=%s has no frames in the frame_checks report it must be judged from' % (t, src)))
                continue
            seen_txt = entry.get('seen')
            if not isinstance(seen_txt, str) or len(seen_txt.strip()) < th['evidenceSeenMinChars']:
                weak = True
                issues.append(_issue('evidence-weak', 'error', t, 'seen', seen_txt if isinstance(seen_txt, str) else None,
                                     '`seen` must describe what the frames show (a string of at least %d characters)' % th['evidenceSeenMinChars']))
            cue = entry.get('cue_line')
            if cue is not None:
                row = next((r for r in inp.line_starts if r['line'] == cue), None)
                if row is None:
                    issues.append(_issue('cue-mismatch', 'error', t, 'cue_line', str(cue), 'cue_line %s is not a script line' % cue))
                elif not (row['start'] < b['end'] and row['end'] > t):
                    issues.append(_issue('cue-mismatch', 'error', t, 'cue_line', str(cue),
                                         'cue_line %s spans %.2f-%.2f, outside the beat %.2f-%.2f' % (cue, row['start'], row['end'], t, b['end']),
                                         cue_span=[row['start'], row['end']]))
        else:
            terms = slug_terms(src)
            m['derivedFromSlug'] += 1
        # shown range in the ORIGINAL video
        clip = inp.cuts.get(src)
        s_in = ed.num(clip.get('source_in')) if isinstance(clip, dict) else None
        transcript = []
        s0 = s1 = None
        if s_in is not None:
            s0 = s_in + (ed.num(b.get('from')) or 0.0)
            s1 = s0 + (b['end'] - t)
            s_out = ed.num(clip.get('source_out'))
            if s_out is not None:
                s1 = min(s1, s_out)
            transcript = [r['text'] for r in inp.timed if r['start'] < s1 + pad and (r['end'] if r['end'] is not None else r['start']) > s0 - pad]
        ocr = _ocr_for(inp.frames, t, src) or []
        sources = [('transcript', '\n'.join(transcript)), ('ocr', '\n'.join(ocr))]
        window = '\n'.join(x for _, x in sources).strip()
        if not window:
            m['windowUnavailable'] += 1
            issues.append(_issue('window-evidence-unavailable', 'error', t, 'src', src,
                                 'no timed transcript or frame OCR text for the shown range of %s (original %s); chapter titles are not evidence' % (src, 'unknown' if s0 is None else '%.1f-%.1f' % (s0, s1))))
            continue
        wstems = _stems(window)
        usable = [(term, toks) for term, toks in ((term, qualifying_tokens(term, th)) for term in terms) if toks]
        beat_match = {'t': t, 'src': src, 'terms': []}
        for term, toks in usable:
            hit = {x: _token_hits(x, sources) for x in toks}
            beat_match['terms'].append({'term': term, 'tokens': hit, 'matched': all(hit.values())})
        m['matches'].append(beat_match)
        if not usable:
            if entry is not None:
                m['weak'] += 1
                issues.append(_issue('evidence-weak', 'error', t, 'subject_terms', ', '.join(terms),
                                     'no subject term has a qualifying word (>= %d characters, not a stopword, not a number)' % th['subjectTokenMinLetters']))
            else:
                issues.append(_issue('subject-not-in-window', 'error', t, 'subject_terms', ', '.join(terms),
                                     'no usable subject term (words >= %d characters) to check against the window' % th['subjectTokenMinLetters']))
        elif not any(x['matched'] for x in beat_match['terms']):
            issues.append(_issue('subject-not-in-window', 'error', t, 'subject_terms', ', '.join(terms),
                                 'no subject term has ALL its words in the window evidence (original %s +-%.0f s: transcript, frame OCR)' % ('%.1f-%.1f' % (s0, s1) if s0 is not None else 'range unknown', pad)))
        headline = b.get('headline')
        if isinstance(headline, str):
            for w in dict.fromkeys(LATIN.findall(headline)):
                lw = w.lower()
                if len(w) < th['labelLatinMinLetters'] or lw in allow or lw in title_words or stem(w) in wstems:
                    continue
                issues.append(_issue('label-latin-not-in-window', 'error', t, 'headline', headline,
                                     'headline word "%s" is not in the shown window evidence nor the source title' % w, word=w))
    metrics['evidence'] = m


def _frames_key(counts, t, src):
    for (ft, fsrc) in counts:
        if fsrc == src and abs(ft - t) < 0.05:
            return (ft, fsrc)
    return None


def run_schema(episode_path, captions_path, validator, timeout=60):
    """Run episode_schema.mjs validate -> (issues, summary). Raises EpisodeFormatError on exit 2 / unusable output."""
    cmd = ['node', str(validator), 'validate', str(episode_path)]
    if captions_path:
        cmd += ['--captions', str(captions_path)]
    cmd.append('--json')
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ed.EpisodeFormatError('cannot run schema validator: %s' % e)
    if proc.returncode == 2:
        raise ed.EpisodeFormatError('schema validator usage/IO error (exit 2): %s' % (proc.stderr.strip() or proc.stdout.strip())[:300])
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        raise ed.EpisodeFormatError('schema validator printed no JSON (exit %d): %s' % (proc.returncode, proc.stderr.strip()[:300]))
    issues = []
    for sev, key in (('error', 'errors'), ('warn', 'warnings')):
        for e in data.get(key) or []:
            if isinstance(e, dict):
                issues.append(_issue('schema', sev, None, e.get('path'), None, str(e.get('message', '')), path=e.get('path'), rule=e.get('rule')))
    if proc.returncode == 1 and not any(i['severity'] == 'error' for i in issues):
        issues.append(_issue('schema', 'error', None, None, None, 'validator reported invalid without error entries', rule=None, path=None))
    summary = {'ran': True, 'valid': proc.returncode == 0 and bool(data.get('valid', True)), 'schemaSha256': data.get('schemaSha256'),
               'errors': sum(i['severity'] == 'error' for i in issues), 'warnings': sum(i['severity'] == 'warn' for i in issues)}
    return issues, summary


def lint_content(ep, inp, thresholds=None):
    """Run every content check (not the schema step) -> (issues, metrics)."""
    th = {**THRESHOLDS, **(thresholds or {})}
    issues, metrics = [], {}
    check_provenance(ep, inp, th, issues, metrics)
    check_timing(ep, inp, th, issues, metrics)
    check_presenter(ep, th, issues, metrics)
    check_cta(ep, th, issues, metrics)
    check_punch(ep, issues, schema_owns=(ep['format'] == 'json-object' and not inp.legacy))
    check_stock(ep, inp, issues)
    check_source_reuse(ep, inp, th, issues)
    check_evidence(ep, inp, th, issues, metrics)
    metrics['beats'] = len(ep['beats'])
    metrics['voEnd'] = ep['vo_end']
    metrics['episodeFormat'] = ep['format']
    return issues, metrics


def count_codes(issues):
    counts = {}
    for i in issues:
        key = i['code'] if i['severity'] == 'error' else i['code'] + ' (warn)'
        counts[key] = counts.get(key, 0) + 1
    return counts


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--beats', required=True, help='episode.json (V4 object; or legacy list JSON / .tsx composition with --legacy)')
    ap.add_argument('--script', required=True)
    ap.add_argument('--words', required=True, help='words_by_line.txt or caption_pages_final.json')
    ap.add_argument('--line-starts', required=True)
    ap.add_argument('--cuts', required=True)
    ap.add_argument('--captions', help='captions JSON, passed through to episode_schema.mjs validate --captions')
    ap.add_argument('--source-transcript')
    ap.add_argument('--source-meta')
    ap.add_argument('--chapters')
    ap.add_argument('--relevance')
    ap.add_argument('--evidence', help='visual_evidence.json: [{t, src, cue_line, subject_terms[], seen}]')
    ap.add_argument('--frames-report', help='frame_checks.py cutaways report (OCR text per beat)')
    ap.add_argument('--source-timed', help='timed transcript of the ORIGINAL video: [{start,end,text}]')
    ap.add_argument('--schema-validator', help='path of episode_schema.mjs (default: next to this script)')
    ap.add_argument('--vo-end', type=float, help='voice-over end seconds when the episode file does not carry it')
    ap.add_argument('--legacy', action='store_true', help='V3 replay data: schema validator may be absent, legacy list/TSX accepted, '
                    'evidence not required (subject terms from the src slug)')
    ap.add_argument('--set', action='append', default=[], metavar='KEY=JSON', help='override a threshold for this run')
    ap.add_argument('--report', required=True)
    a = ap.parse_args(argv)
    validator = Path(a.schema_validator) if a.schema_validator else Path(__file__).resolve().parent / 'episode_schema.mjs'
    paths = {k: getattr(a, k) for k in ('beats', 'script', 'words', 'line_starts', 'cuts', 'captions', 'source_transcript', 'source_meta', 'chapters',
                                        'relevance', 'evidence', 'frames_report', 'source_timed') if getattr(a, k)}
    schema_issues, schema_summary = [], {'ran': False}
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
        evidence = ed.load_evidence(a.evidence) if a.evidence else []
        frames = ed.load_frames_report(a.frames_report) if a.frames_report else {}
        frame_counts = ed.load_frame_counts(a.frames_report) if a.frames_report else {}
        timed = ed.load_timed_transcript(a.source_timed) if a.source_timed else []
        chapters = ed.load_chapters(a.chapters) if a.chapters else []
        ep = ed.load_episode(a.beats, vo_end=a.vo_end, fallback_vo_end=line_starts[-1]['end'])
        if ep['format'] == 'json-object':
            if validator.exists():
                schema_issues, schema_summary = run_schema(a.beats, a.captions, validator)
                paths['schema_validator'] = str(validator)
            elif not a.legacy:
                schema_issues = [_issue('schema-validator-missing', 'error', None, None, str(validator), 'episode_schema.mjs not found; structural validation did not run')]
        elif not a.legacy:
            schema_issues = [_issue('schema', 'error', None, None, None, 'episode is not a V4 object JSON (%s); legacy formats need --legacy' % ep['format'])]
        hashes = {p: _sha(p) for p in paths.values()}
    except (ed.EpisodeFormatError, OSError, ValueError) as e:
        report = {'schema': SCHEMA, 'version': VERSION, 'pass': False,
                  'issues': [_issue('input', 'error', None, None, None, str(e))], 'metrics': {}, 'thresholds': {}, 'inputs': {}}
        Path(a.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    inp = Inputs(script_lines, tokens, line_starts, cuts, source, relevance, relevance_given=bool(a.relevance),
                 evidence=evidence, frames=frames, timed=timed, chapters=chapters, legacy=a.legacy,
                 frames_given=bool(a.frames_report), frame_counts=frame_counts)
    issues, metrics = lint_content(ep, inp, thresholds)
    issues = schema_issues + issues
    metrics['schema'] = schema_summary
    metrics['issueCounts'] = count_codes(issues)
    report = {'schema': SCHEMA, 'version': VERSION, 'pass': not any(i['severity'] == 'error' for i in issues),
              'issues': issues, 'metrics': metrics, 'thresholds': thresholds, 'inputs': hashes}
    out = json.dumps(report, ensure_ascii=False, indent=2)
    Path(a.report).write_text(out, encoding='utf-8')
    print(out)
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
