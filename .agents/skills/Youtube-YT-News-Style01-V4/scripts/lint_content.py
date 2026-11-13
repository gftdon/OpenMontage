#!/usr/bin/env python3
"""Deterministic lint of the on-screen CONTENT of a YT-News episode (CF-A67 WP2a).

Complements lint_beats.py (geometry/hold). Offline, no network, no model calls, fail-closed:
a missing or unreadable input exits 2. issue = {code, severity:'error'|'warn', t, field, text, detail, ...};
only 'error' fails the run.

Checks: schema (delegated to episode_schema.mjs), provenance-number / -ordinal / -latin / -thai,
card-timing-*, presenter-share/-run, cta-length, punch-forbidden, stock-not-allowed, source-reuse, crop-trims-source, and
the shown-vs-said checks on source clips (evidence-missing, cue-mismatch, window-evidence-unavailable,
subject-not-in-window, evidence-weak, evidence-seen-duplicate, label-latin-not-in-window), typo-filler,
episode-copied. Thresholds: content_thresholds.py.

Hardening (CF-A67, the lint is run by an unattended agent that may take any shortcut): stock / AI footage is never allowed, a
relevance file is never evidence; srcCrop trimming an edge by more than CROP_TRIM_MAX_PERCENT is an error; two evidence entries with
the same `seen` text (after Unicode NFKC, removal of invisible characters and whitespace collapsing) are an error; an episode that shares
COPY_MAX_SHARE of its beats (same media, headline and footage, compared after normalisation) with another episode-format file (the skill
directory, or another project in a projects-type root), or whose beats make up COPY_MAX_SHARE of that file, is an error (episode-copied; at
least COPY_MIN_SAME beats). The episode itself must be a regular file inside its own project (episode-not-regular-file), and the search for
copies must finish (copy-search-incomplete); the walk reads regular files only and never follows a link.

Where the copy search looks (CF-A67 fix round 1; `projects/` is git-ignored, so a clean checkout has none of the other episodes):
  --copy-root DIR   (repeatable) a projects-type root: every immediate sub-directory is one project and is searched whole. A root that is not
                    an existing directory -> exit 4 + issue copy-root-missing (an environment failure, nothing was linted).
  no --copy-root    the default projects-type root is the parent of the episode's OWN project: the nearest ancestor directory named
                    `projects` of the episode path (as given, not resolved) with a project folder below it: <x>/projects/<project>/...
                    An episode that does not lie under such a folder has no projects-type root.
  always            this skill's directory and <checkout>/remotion-composer/src/*.json of the checkout this script lives in.
  The episode's own project (in the root that holds it) and its own file are never compared against.
  --avatar FILE     our avatar mp4. In projects-type roots ONLY a project whose avatar has the same content (sha256; only a file of the same
                    size is hashed) is skipped: re-doing the same video is allowed. A project's avatar is located as follows: when
                    <project>/artifacts/episode.json is a yt-news-v4-episode with assetDir + avatarFile, the file
                    <root>/../remotion-composer/public/<assetDir>/<avatarFile>. Otherwise (a non-V4 project): (a) every *.mp4 directly in
                    <root>/../remotion-composer/public/<project folder name>/ (the V2/V3 convention, assetDir = the project slug) and (b) every
                    *.mp4 inside the project folder EXCEPT below a directory named `public`, `render-bundle` or `bundle` (render bundles copy the
                    whole remotion-composer/public, so they hold the avatars of OTHER videos). An avatar that cannot be found / read is an
                    unknown identity and the project is NOT skipped. Hashing counts against the walk budget.
  The report carries copy_search = {roots: [{path, kind: skill|composer-src|projects, files, skipped_same_avatar: [project]}], incomplete}.
Exit codes: 0 pass, 1 content errors, 2 an input is missing / unreadable (also --avatar), 4 a --copy-root is not a directory.

What the evidence checks prove, plainly: that a subject term (a word of >= 4 characters, not a stopword) occurs in the ORIGINAL video's
transcript or in the OCR of the frames at the time the clip was cut from. They do NOT prove that the picture matches the narration; that needs
a judge (a model or a person). Chapter titles are never evidence. `report.metrics.evidence.matches` lists, per source beat and term, which
source (`ocr` / `transcript`) matched each word, so a human can audit it.
Structural episode rules (S01-S20, including S09 clip length, S12 punch, S20 last beat / CTA) belong to the engine
workstream's episode_schema.mjs; this file calls it and does not re-implement them. The only copy kept is
punch-forbidden for legacy (list / TSX) replay data, where there is no schema.

--relevance is still read (formats: see load_relevance) but ONLY to report it in metrics.relevance as "not used as evidence":
no verdict, however good, makes a stock / AI beat pass.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parent))
import episode_data as ed
from content_thresholds import (THRESHOLDS, LEGACY_OVERRIDES, CROP_TRIM_MAX_PERCENT, COPY_MAX_SHARE, COPY_MIN_SAME, COPY_MAX_FILE_BYTES,
                                COPY_WALK_BUDGET_SECONDS)

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
                 evidence=None, frames=None, timed=None, chapters=None, legacy=False, frames_given=False, frame_counts=None, copy_search=None):
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
        self.copy_search = copy_search      # see copy_search_for(); None = the episode-copied search is not run (library callers / unit tests)
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
    """card-timing-*. Whole-beat labels (kind 'beat', every text of the final beat, and a typo card beat's first card cards[0], whose
    start is pinned to the beat start by schema S14) can only be
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
            # Schema S14: a typo card beat's first card starts exactly at the beat start (cards[0].at == t), so it cannot be timed to the
            # spoken word: cards[0] is a whole-beat label (gone-before-spoken only, no early / late / far). cards[1..] keep the +-2 s rule.
            label_like = kind == 'beat' or b is last or (b.get('media') == 'typo' and field.startswith('cards[0].'))
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


def check_stock(ep, inp, issues, metrics):
    """stock-not-allowed (error, every case): a footage beat (media broll / clip) whose origin is not the source video. Stock / AI footage
    never passes, not even with a `verified` relevance verdict (a hand-written verdict file passed before CF-A67); the relevance file is only
    reported in metrics.relevance. The old code `stock-unverified` is gone (it meant "allowed with a verdict")."""
    rows = inp.relevance or []
    metrics['relevance'] = {'given': bool(inp.relevance_given), 'rows': len(rows), 'usedAsEvidence': False,
                            'note': 'a relevance file is not evidence: stock / ai footage is always an error'}
    for b in ep['beats']:
        if b.get('media') not in ('broll', 'clip') or b.get('origin') == 'source':
            continue
        origin = b.get('origin')
        issues.append(_issue('stock-not-allowed', 'error', b['t'], 'src', b.get('src'),
                             '%s footage (media %s, origin %s) is not allowed: only the source video may be shown; use source footage or a `typo` '
                             'text card built from the script (a relevance verdict does not change this)' % (
                                 origin if origin in ('stock', 'ai') else 'non-source', b.get('media'), repr(origin) if origin is not None else 'missing')))


def _edge_trims(x, y, w, h):
    """Percent of each side of the 1920x1080 frame that lies outside the rectangle (x, y, w, h)."""
    return {'left': x / ed.SOURCE_W * 100.0, 'right': (ed.SOURCE_W - (x + w)) / ed.SOURCE_W * 100.0,
            'top': y / ed.SOURCE_H * 100.0, 'bottom': (ed.SOURCE_H - (y + h)) / ed.SOURCE_H * 100.0}


def crop_visible_trims(layout, crop):
    """-> (trims, how): the percent of each side of the source frame the srcCrop REMOVES from what the viewer sees. The renderer cover-fits the
    crop into the picture box, so a crop whose shape is not the box's trims the other axis too: the VISIBLE region (ed.visible_region) is
    measured, relative to the visible region of the same layout without a crop (which is ~0 for the 16:9-ish boxes, and keeps a full-frame
    crop from being blamed for the box's own shape). Never less than the crop rectangle's own trims. `how` is 'visible', or 'rectangle'
    when the visible region cannot be computed (unknown layout, lanes file unusable): the rectangle alone, which is never more lenient than before."""
    x, y, w, h = (ed.num(crop.get(k)) for k in ('x', 'y', 'w', 'h'))
    rect = _edge_trims(x, y, w, h)
    try:
        vx, vy, vw, vh = ed.visible_region(layout, ed.SOURCE_W, ed.SOURCE_H, crop)
        bx, by, bw, bh = ed.visible_region(layout, ed.SOURCE_W, ed.SOURCE_H, None)
    except ValueError:
        return rect, 'rectangle'
    vis, base = _edge_trims(vx, vy, vw, vh), _edge_trims(bx, by, bw, bh)
    return {k: max(rect[k], vis[k] - max(base[k], 0.0)) for k in rect}, 'visible'


def check_crop_trims(ep, issues):
    """crop-trims-source (ERROR, no exceptions): a srcCrop that removes more than CROP_TRIM_MAX_PERCENT of an edge of the source frame from what
    the viewer sees (crop_visible_trims: the cover-fitted visible region, not only the crop rectangle). The default is no srcCrop (the whole
    source frame). A malformed srcCrop is the schema's business: skipped here."""
    for idx, b in enumerate(ep['beats']):
        crop = b.get('srcCrop')
        if not isinstance(crop, dict):
            continue
        x, y, w, h = (ed.num(crop.get(k)) for k in ('x', 'y', 'w', 'h'))
        if None in (x, y, w, h) or w <= 0 or h <= 0:
            continue
        trims, how = crop_visible_trims(b.get('layout'), crop)
        rect = _edge_trims(x, y, w, h)
        if not any(v > CROP_TRIM_MAX_PERCENT for v in trims.values()):
            continue
        t = b['t']
        at = (ed.num(b.get('from')) or 0.0) + (b['end'] - t) / 2.0        # middle of the shown range, in the source file
        src = b.get('src')
        asset_dir = ep.get('assetDir')                                    # top-level assetDir (set by main(); the loader does not carry it)
        media = ('remotion-composer/public/%s/broll/%s.mp4' % (asset_dir, src)) if isinstance(asset_dir, str) and asset_dir else '%s.mp4' % src
        pct = ' '.join('%s %.1f%%' % (k, trims[k]) for k in ('left', 'right', 'top', 'bottom'))
        cmd = 'ffmpeg -ss %.1f -i %s -frames:v 1 -vf "drawbox=x=%s:y=%s:w=%s:h=%s:color=red:t=4" crop_check.jpg' % (
            at, media, _fmt_num(x), _fmt_num(y), _fmt_num(w), _fmt_num(h))
        issues.append(_issue('crop-trims-source', 'error', t, 'srcCrop', src,
                             'beat %d (t=%.2f) srcCrop trims the source frame of %s: %s (limit %.1f%% per edge); to see what it cuts: %s; '
                             'remove srcCrop (default: show the whole source frame)' % (idx, t, src, pct, CROP_TRIM_MAX_PERCENT, cmd),
                             trimPercent={k: round(v, 2) for k, v in trims.items()}, measuredOn=how,
                             rectTrimPercent={k: round(v, 2) for k, v in rect.items()}))


def _fmt_t(t):
    return 'None' if t is None else '%g' % t


def _fmt_num(v):
    return '%d' % v if float(v).is_integer() else '%g' % v


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
    m = {'sourceBeats': 0, 'withEvidence': 0, 'derivedFromSlug': 0, 'windowUnavailable': 0, 'weak': 0, 'duplicateSeen': 0, 'matches': []}
    # evidence-seen-duplicate: one entry = one frame of one beat, so no two entries may carry the same `seen` text (whitespace collapsed and
    # trimmed, case-sensitive). The proof run wrote 28 distinct texts for 44 entries.
    first_seen = {}
    for e in inp.evidence:
        txt = e.get('seen')
        key = norm_text(txt) if isinstance(txt, str) else ''
        if not key:
            continue                                    # missing / empty `seen` is evidence-weak's business
        et = ed.num(e.get('t'))
        if key not in first_seen:
            first_seen[key] = (et, e.get('src'))
            continue
        m['duplicateSeen'] += 1
        ft, fsrc = first_seen[key]
        issues.append(_issue('evidence-seen-duplicate', 'error', et, 'seen', txt,
                             'evidence entry t=%s src=%s has the same `seen` text as the entry t=%s src=%s: each entry must describe what ITS OWN frames show '
                             '(look at the frames of this beat and write a new description)' % (_fmt_t(et), e.get('src'), _fmt_t(ft), fsrc),
                             other_t=ft, other_src=fsrc))
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


# ------------------------------ episode-copied ----------------------------------
#
# Contract (CF-A67 W2 / W2b): the episode fails when it shares too many beats with ONE other episode-format JSON file found under the skill
# directory or under another project of the repo. "The same beat" = same media AND same headline AND same footage, compared after
# normalisation (see norm_copy_text / footage identity below) so that renaming a clip, a zero-width character, a Unicode look-alike, a
# trailing full stop or a changed case does not hide a copy. Beat times, kicker, sub, cards are not part of it.

EPISODE_SCHEMA_PREFIX = 'yt-news-v4-episode'
COPY_SKIP_DIRS = {'node_modules', '.git', '__pycache__'}
COPY_BUNDLE_DIRS = {'public', 'render-bundle', 'bundle'}   # a render bundle copies the whole remotion-composer/public: its mp4 files say nothing about THIS project
COPY_CUTS_NAMES = ('_cuts.json', 'cuts.json')       # the clip table that sits next to an episode file (project artifacts/ or a fixture folder)
COPY_FOOTAGE_OVERLAP = 0.5                          # two clips of the same source video count as the same footage when they overlap by this
                                                    # share of the shorter one (an agent that re-cuts a copied clip by a second keeps the footage)
# Characters that render as nothing but are not Unicode category Cf: combining grapheme joiner, variation selectors, Mongolian free variation
# selectors, Hangul fillers. (Thai vowels / tone marks are category Mn and are NOT removed: they are letters of the text.)
_INVISIBLE = {0x034F, 0x115F, 0x1160, 0x3164, 0xFFA0} | set(range(0xFE00, 0xFE10)) | set(range(0x180B, 0x180F)) | set(range(0xE0100, 0xE01F0))


def _strip_invisible(s):
    return ''.join(c for c in s if unicodedata.category(c) != 'Cf' and ord(c) not in _INVISIBLE)


def norm_text(text):
    """One normalisation for every text comparison of this file: Unicode NFKC, every format character (category Cf: zero-width space /
    joiner / non-joiner, word joiner, BOM, soft hyphen, bidi marks ...) and the few invisible non-Cf marks removed, all whitespace collapsed to
    one space, trimmed. Case and punctuation are kept (evidence-seen-duplicate is case-sensitive by the lead's decision)."""
    s = unicodedata.normalize('NFKC', _strip_invisible(text))
    return re.sub(r'\s+', ' ', _strip_invisible(s)).strip()


def norm_copy_text(text):
    """norm_text, then Thai digits -> Arabic, case-folded, every punctuation character (category P*) and then ALL whitespace removed: the
    copy comparison must not be sidestepped by a full stop, a case change, a hyphen instead of a space, or an extra space."""
    s = ed.norm_digits(norm_text(text)).casefold()
    return ''.join(c for c in s if not c.isspace() and not unicodedata.category(c).startswith('P'))


def _footage_of(clip):
    """Identity of the FOOTAGE behind a clip table entry: (sha256 of the source video, source_in, source_out), or None when the entry does not
    carry all three. The name of a clip (`src`) is chosen by whoever cut it; the source video's hash and the span cut from it are not."""
    if not isinstance(clip, dict):
        return None
    sha, s_in, s_out = clip.get('source_sha256'), ed.num(clip.get('source_in')), ed.num(clip.get('source_out'))
    if not isinstance(sha, str) or not sha or s_in is None or s_out is None or s_out <= s_in:
        return None
    return (sha.lower(), s_in, s_out)


def _same_footage(a, b):
    if a is None or b is None or a[0] != b[0]:
        return False
    overlap = min(a[2], b[2]) - max(a[1], b[1])
    return overlap > 0 and overlap >= COPY_FOOTAGE_OVERLAP * min(a[2] - a[1], b[2] - b[1])


def beat_triples(beats, cuts=None):
    """-> [(media, src, headline, footage)] of every beat that has a src or a headline. media / src / headline are norm_copy_text-normalised;
    `footage` is the identity of the clip from `cuts` (a {slug: clip} table) or None. Beat times are NOT part of it: a legitimate re-edit of
    the same audio shares them."""
    out = []
    for b in beats:
        if not isinstance(b, dict):
            continue
        src = b.get('src')
        head = b.get('headline')
        src_raw = src if isinstance(src, str) else ''
        src = norm_copy_text(src_raw)
        head = norm_copy_text(head) if isinstance(head, str) else ''
        if not src and not head:
            continue
        media = b.get('media')
        footage = _footage_of(cuts.get(src_raw.strip())) if cuts and src_raw.strip() else None
        out.append((norm_copy_text(media) if isinstance(media, str) else '', src, head, footage))
    return out


def _sibling_cuts(path):
    """The clip table next to an episode file (_cuts.json / cuts.json in the same folder), {} when there is none or it is unusable."""
    for name in COPY_CUTS_NAMES:
        p = Path(path).parent / name
        try:
            st = os.lstat(str(p))
            if not stat.S_ISREG(st.st_mode) or st.st_size > COPY_MAX_FILE_BYTES:
                continue
            data = json.loads(p.read_text(encoding='utf-8'))
        except (OSError, ValueError, UnicodeDecodeError, RecursionError, MemoryError):
            continue
        clips = data.get('clips', data) if isinstance(data, dict) else None
        if isinstance(clips, dict):
            return clips
    return {}


def _beats_of(data):
    """The beats list of a parsed episode-format JSON, None when it is some other JSON."""
    if not isinstance(data, dict):
        return None
    beats, schema = data.get('beats'), data.get('schema')
    is_episode = (isinstance(schema, str) and schema.startswith(EPISODE_SCHEMA_PREFIX)) or isinstance(beats, list)
    if not is_episode or not isinstance(beats, list) or not all(isinstance(b, dict) for b in beats):
        return None
    return beats


def _read_regular(path):
    """Bytes of a REGULAR file of at most COPY_MAX_FILE_BYTES, never following a symlink and never blocking on a FIFO / device: opened
    O_NONBLOCK | O_NOFOLLOW and fstat-ed before the first read (a path swapped after the directory walk's lstat is caught here).
    Raises OSError (not a regular file / symlink) or ValueError (too large)."""
    fd = os.open(str(path), os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise OSError('not a regular file')
        if st.st_size > COPY_MAX_FILE_BYTES:
            raise ValueError('file too large')
        data = b''
        while len(data) <= COPY_MAX_FILE_BYTES:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            data += chunk
        if len(data) > COPY_MAX_FILE_BYTES:
            raise ValueError('file too large')
        return data
    finally:
        os.close(fd)


def _episode_beats(path, stats=None):
    """-> (beats, cuts) when `path` is an episode-format JSON, None when it is some other JSON.
    Pre-filter: the file is read whole (<= COPY_MAX_FILE_BYTES = 5 MB, a bigger .json is not an episode) and parsed only when its bytes contain
    the key `"beats"` (stats.parsed counts the files that were parsed): the main checkout's projects/ holds thousands of JSON files (transcripts, word timings, reports), and parsing them is
    the expensive part, reading them is not. Raises OSError / ValueError when the file cannot be read or parsed."""
    raw = _read_regular(path)
    if b'"beats"' not in raw:
        return None
    if stats is not None:
        stats['parsed'] += 1
    beats = _beats_of(json.loads(raw.decode('utf-8')))
    if beats is None:
        return None
    return beats, _sibling_cuts(path)


def _json_files(root, stats, deadline=None):
    """Every `*.json` regular file under `root`, symlinks never followed (neither directories nor files), FIFOs / devices / sockets never
    opened. Counted into `stats`: skipped_nonregular (symlink, FIFO, ...), unreadable_dirs (os.walk could not list them). Stops (stats.complete
    = False) when time.monotonic() passes `deadline`."""
    def onerror(_e):
        stats['unreadable_dirs'] += 1
    for dirpath, dirnames, filenames in os.walk(str(root), onerror=onerror, followlinks=False):
        if deadline is not None and time.monotonic() > deadline:
            stats['complete'] = False
            return
        dirnames[:] = sorted(d for d in dirnames if d not in COPY_SKIP_DIRS)
        for name in sorted(filenames):
            if not name.lower().endswith('.json'):
                continue
            p = os.path.join(dirpath, name)
            try:
                mode = os.lstat(p).st_mode
            except OSError:
                stats['unreadable_files'] += 1
                continue
            if not stat.S_ISREG(mode):
                stats['skipped_nonregular'] += 1
                continue
            yield p


def _lexical_project(beats_path, projects_dir):
    """-> (own_project, own_file, problem) from the episode path AS GIVEN (os.path.abspath, symlinks not resolved).
    Walks the lexical ancestors of the path looking for the projects dir (os.path.samefile, so a symlinked /tmp or a differently spelled
    mount does not matter). Below it, no component may be a symlink and the episode must be a regular file: otherwise `problem` says why.
    Outside the projects dir (or without one) only the file itself is checked."""
    lex = os.path.abspath(str(beats_path))
    own_project, rel_parts, anchor = None, None, None
    if projects_dir is not None:
        parts = Path(lex).parts
        for i in range(len(parts) - 1, 0, -1):
            cand = os.path.join(*parts[:i])
            try:
                if os.path.samefile(cand, str(projects_dir)):
                    anchor, rel_parts = cand, parts[i:]
                    break
            except OSError:
                continue
        if anchor is not None and len(rel_parts) >= 2:
            own_project = rel_parts[0]
    problem = None
    chain = []
    if anchor is not None and rel_parts:
        cur = anchor
        for part in rel_parts:
            cur = os.path.join(cur, part)
            chain.append(cur)
    else:
        chain = [lex]
    for p in chain:
        try:
            mode = os.lstat(p).st_mode
        except OSError:
            continue                                    # a missing file is the loader's problem (exit 2), not this check's
        if stat.S_ISLNK(mode):
            problem = '%s is a symbolic link' % p
            break
        if p == chain[-1] and not stat.S_ISREG(mode):
            problem = '%s is not a regular file' % p
    if anchor is not None and rel_parts:
        own_file = Path(os.path.realpath(str(projects_dir))) / Path(*rel_parts)
    else:
        own_file = Path(os.path.realpath(os.path.dirname(lex))) / os.path.basename(lex)
    return own_project, own_file, problem


class CopyRootError(ValueError):
    """A --copy-root that does not exist or is not a directory (lint exit 4, issue copy-root-missing)."""


class _OutOfTime(Exception):
    """The walk budget ran out while locating / hashing an avatar."""


def _default_projects_root(beats_path):
    """The default projects-type root: the parent of the episode's own project = the NEAREST lexical ancestor directory named `projects`
    that has a project folder and a file below it (<x>/projects/<project>/.../episode.json); None when the episode does not lie under one or
    that directory does not exist. Taken from the path as given (symlinks not resolved), like _lexical_project."""
    parts = Path(os.path.abspath(str(beats_path))).parts
    for i in range(len(parts) - 3, 0, -1):
        if parts[i] == 'projects':
            root = os.path.join(*parts[:i + 1])
            return root if os.path.isdir(root) else None
    return None


def _regular_size(path):
    """Size of a regular file (a symlink is not one), None otherwise / when unreadable."""
    try:
        st = os.lstat(str(path))
    except OSError:
        return None
    return st.st_size if stat.S_ISREG(st.st_mode) else None


def copy_search_for(beats_path, script_file=None, copy_roots=None, avatar=None):
    """The roots the episode-copied check searches for the episode at `beats_path` (see the module docstring): this skill's directory
    (`skill_dir`, found from __file__), <checkout>/remotion-composer/src (`composer_src`, when the skill sits in
    <checkout>/.claude|.agents/skills/<skill>/scripts) and the projects-type roots `projects_roots` (explicit `copy_roots`, or the default
    root of _default_projects_root; `projects_dir` = the first one, kept for older callers). An explicit root that is not a directory raises
    CopyRootError. `own_project` is the project folder the episode itself lives in, `own_root` the projects-type root that holds it (the
    project is skipped in that root only), `own_file` the episode file, `own_problem` a reason why the episode is not a regular file inside its
    own project (a symlink somewhere below the root, or not a regular file) or None. The project is taken from the path as given, NOT from
    where a symlink points: a symlinked episode must not make the project it points into "its own". `avatar` = {path, size, sha256} of our
    avatar mp4 or None (unreadable avatar: no project is skipped)."""
    here = Path(script_file or __file__).resolve()
    parents = here.parents
    skill_dir = parents[1]
    composer_src = None
    if len(parents) > 4 and parents[2].name == 'skills' and parents[3].name in ('.claude', '.agents'):
        cand = parents[4] / 'remotion-composer' / 'src'
        composer_src = cand if cand.is_dir() else None
    roots = []
    if copy_roots:
        seen = set()
        for r in copy_roots:
            if not Path(r).is_dir():
                raise CopyRootError(str(r))
            real = os.path.realpath(str(r))
            if real not in seen:
                seen.add(real)
                roots.append(Path(real))
    else:
        default = _default_projects_root(beats_path)
        if default:
            roots.append(Path(os.path.realpath(default)))
    results = [(r, _lexical_project(beats_path, r)) for r in roots]
    anchored = [(r, res) for r, res in results if res[0] is not None]
    if anchored:
        own_root, (own_project, own_file, problem) = anchored[0]
    else:
        own_root, own_project = None, None
        own_file, problem = results[0][1][1:] if results else _lexical_project(beats_path, None)[1:]
    av = None
    if avatar:
        try:
            st = os.stat(str(avatar))
            if stat.S_ISREG(st.st_mode):
                av = {'path': os.path.realpath(str(avatar)), 'size': st.st_size, 'sha256': None}     # OUR avatar may be a link (the task folder's); the hash opens the real file
        except OSError:
            av = None
    return {'skill_dir': skill_dir, 'projects_dir': roots[0] if roots else None, 'projects_roots': roots, 'own_root': own_root,
            'own_file': own_file, 'own_project': own_project, 'own_problem': problem, 'composer_src': composer_src, 'avatar': av}


def _root_records(search):
    """The `copy_search.roots` entries, in this order: the skill dir, the composer src, every projects-type root."""
    recs = []
    if search.get('skill_dir'):
        recs.append({'path': str(search['skill_dir']), 'kind': 'skill', 'files': 0, 'skipped_same_avatar': []})
    if search.get('composer_src'):
        recs.append({'path': str(search['composer_src']), 'kind': 'composer-src', 'files': 0, 'skipped_same_avatar': []})
    for r in _projects_roots(search):
        recs.append({'path': str(r), 'kind': 'projects', 'files': 0, 'skipped_same_avatar': []})
    return recs


def _projects_roots(search):
    roots = search.get('projects_roots')
    if roots is None:
        roots = [search['projects_dir']] if search.get('projects_dir') else []
    return [r for r in roots if r and Path(r).is_dir()]


def _file_digest(path, deadline=None):
    """sha256 (hex) of a regular file, never following a symlink; None when it cannot be read. Raises _OutOfTime past `deadline`."""
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        h = hashlib.sha256()
        while True:
            if deadline is not None and time.monotonic() > deadline:
                raise _OutOfTime()
            chunk = os.read(fd, 1 << 22)
            if not chunk:
                return h.hexdigest()
            h.update(chunk)
    except OSError:
        return None
    finally:
        os.close(fd)


def _v4_avatar_ref(project):
    """(assetDir, avatarFile) of <project>/artifacts/episode.json when it is a yt-news-v4-episode that names both, else None."""
    try:
        data = json.loads(_read_regular(Path(project) / 'artifacts' / 'episode.json').decode('utf-8'))
    except (OSError, ValueError, UnicodeDecodeError, RecursionError, MemoryError):
        return None
    if not isinstance(data, dict) or not str(data.get('schema', '')).startswith(EPISODE_SCHEMA_PREFIX):
        return None
    d, f = data.get('assetDir'), data.get('avatarFile')
    if isinstance(d, str) and d and isinstance(f, str) and f:
        return d, f
    return False                                       # a V4 episode without an avatar name: unknown identity (not the mp4 search)


def _avatar_candidates(project, proot, size, deadline):
    """The files that may be `project`'s avatar and have our avatar's size (an unknown avatar -> []); the rules are in the module docstring."""
    ref = _v4_avatar_ref(project)
    if ref is False:
        return []
    if ref:
        d, f = ref
        if os.path.isabs(d) or os.path.isabs(f) or '..' in Path(d).parts + Path(f).parts:
            return []
        p = Path(proot).parent / 'remotion-composer' / 'public' / d / f
        return [p] if _regular_size(p) == size else []
    found = []
    slug_dir = Path(proot).parent / 'remotion-composer' / 'public' / Path(project).name       # rule (a): assetDir = the project slug
    try:
        names = sorted(os.listdir(str(slug_dir)))
    except OSError:
        names = []
    for name in names:
        p = os.path.join(str(slug_dir), name)
        if name.lower().endswith('.mp4') and _regular_size(p) == size:
            found.append(p)
    for dirpath, dirnames, filenames in os.walk(str(project), followlinks=False):             # rule (b), bundle copies excluded
        if deadline is not None and time.monotonic() > deadline:
            raise _OutOfTime()
        dirnames[:] = sorted(x for x in dirnames if x not in COPY_SKIP_DIRS and x not in COPY_BUNDLE_DIRS)
        for name in sorted(filenames):
            if name.lower().endswith('.mp4'):
                p = os.path.join(dirpath, name)
                if _regular_size(p) == size:
                    found.append(p)
    return found


def _same_avatar_project(project, proot, avatar, deadline):
    """True when one of the project's avatar candidates has the same sha256 as ours. Unknown / unreadable -> False (the project is searched)."""
    for cand in _avatar_candidates(project, proot, avatar['size'], deadline):
        if avatar.get('sha256') is None:
            avatar['sha256'] = _file_digest(avatar['path'], deadline) or False
        if avatar['sha256'] is False:
            return False
        if _file_digest(cand, deadline) == avatar['sha256']:
            return True
    return False


def copy_candidates(search, stats, deadline=None):
    """Every .json (regular files only) under the skill dir, the composer src (not recursive) and, in every projects-type root, under
    <root>/<project>/ for every project but the episode's own (in the root that holds it) and every project that has our avatar
    (search['avatar'], see _same_avatar_project), minus the episode file itself. A project folder that is a symlink is not entered (counted in
    stats.skipped_nonregular). Per root counters go to stats['roots'] (_root_records)."""
    if stats.get('roots') is None:
        stats['roots'] = _root_records(search)
    recs = stats['roots']
    rec_skill = next((r for r in recs if r['kind'] == 'skill'), None)
    rec_composer = next((r for r in recs if r['kind'] == 'composer-src'), None)
    rec_projects = [r for r in recs if r['kind'] == 'projects']
    own_root = search.get('own_root', True)             # absent (older callers): the own project name applies to every root
    own_real = os.path.realpath(str(own_root)) if own_root not in (None, True) else None
    avatar = search.get('avatar')
    roots = []                                          # [(directory, record)]
    if search.get('skill_dir'):
        roots.append((Path(search['skill_dir']), rec_skill))
    for proot, rec in zip(_projects_roots(search), rec_projects):
        own_here = search.get('own_project') if own_root is True or (own_real and os.path.realpath(str(proot)) == own_real) else None
        try:
            children = sorted(Path(proot).iterdir())
        except OSError:
            stats['unreadable_dirs'] += 1
            children = []
        for child in children:
            if child.name == own_here:
                continue
            try:
                mode = os.lstat(str(child)).st_mode
            except OSError:
                stats['unreadable_dirs'] += 1
                continue
            if stat.S_ISLNK(mode):
                stats['skipped_nonregular'] += 1
            elif stat.S_ISDIR(mode):
                roots.append((child, rec, proot))
    own = search.get('own_file')
    own_abs = os.path.abspath(str(own)) if own else None
    own_file_real = os.path.realpath(str(own)) if own and not search.get('own_problem') else None

    def is_own(p):
        return own_abs is not None and (os.path.abspath(p) == own_abs or (own_file_real is not None and os.path.realpath(p) == own_file_real))
    cdir = search.get('composer_src')
    if cdir:                                    # <repo>/remotion-composer/src/*.json, NOT recursive; problems here are never counted
        try:
            names = sorted(os.listdir(str(cdir)))
        except OSError:
            names = []
        for name in names:
            p = os.path.join(str(cdir), name)
            if not name.lower().endswith('.json'):
                continue
            try:
                if not stat.S_ISREG(os.lstat(p).st_mode):
                    continue
            except OSError:
                continue
            if not is_own(p):
                if rec_composer is not None:
                    rec_composer['files'] += 1
                yield p
    for item in roots:
        root, rec = item[0], item[1]
        if len(item) == 3 and avatar:                   # a project of a projects-type root: skip it when it is the same video
            try:
                same = _same_avatar_project(root, item[2], avatar, deadline)
            except _OutOfTime:
                stats['complete'] = False
                return
            if same:
                rec['skipped_same_avatar'].append(root.name)
                continue
        for p in _json_files(root, stats, deadline):
            if not is_own(p):
                if rec is not None:
                    rec['files'] += 1
                yield p


def _matches(mine, theirs):
    """(same_mine, same_theirs): how many of my beats have a counterpart among theirs, and how many of theirs have one among mine.
    Counterpart = same media AND same headline AND (same normalised src OR same footage, see _same_footage)."""
    index = {}
    for tr in theirs:
        index.setdefault((tr[0], tr[2]), []).append(tr)

    def hit(a, b):
        return a[1] == b[1] or _same_footage(a[3], b[3])
    mine_idx = {}
    for tr in mine:
        mine_idx.setdefault((tr[0], tr[2]), []).append(tr)
    same_mine = sum(1 for tr in mine if any(hit(tr, o) for o in index.get((tr[0], tr[2]), ())))
    same_theirs = sum(1 for tr in theirs if any(hit(tr, o) for o in mine_idx.get((tr[0], tr[2]), ())))
    return same_mine, same_theirs


def _headline_matches(mine, theirs):
    """Second signal, (head_same_mine, head_n_mine, head_same_theirs, head_n_theirs): beats whose normalised headline (norm_copy_text) equals a
    headline of the other file, whatever the media and the clip name / footage are. Only beats that HAVE a headline count (also in the
    denominator). It catches a copy whose clips were renamed and re-cut: the words on screen are what a viewer sees."""
    hm = [tr[2] for tr in mine if tr[2]]
    ht = [tr[2] for tr in theirs if tr[2]]
    sm, st = set(hm), set(ht)
    return sum(1 for h in hm if h in st), len(hm), sum(1 for h in ht if h in sm), len(ht)


def _signal(same_mine, n_mine, same_theirs, n_theirs, max_share, min_same):
    share_mine = same_mine / n_mine if n_mine else 0.0
    share_theirs = same_theirs / n_theirs if n_theirs else 0.0
    flagged = bool(n_mine and share_mine >= max_share and same_mine >= min_same) or bool(n_theirs and share_theirs >= max_share and same_theirs >= min_same)
    return {'flagged': flagged, 'share_mine': share_mine, 'same_mine': same_mine, 'eligible_mine': n_mine,
            'share_theirs': share_theirs, 'same_theirs': same_theirs, 'eligible_theirs': n_theirs}


def check_copy(ep, search, issues, metrics, max_share=COPY_MAX_SHARE, cuts=None, min_same=COPY_MIN_SAME, budget=COPY_WALK_BUDGET_SECONDS):
    """episode-copied (error): at least `max_share` of this episode's beats (with a src or a headline) have a counterpart in ONE other
    episode-format file under the search roots (see copy_search_for / copy_candidates), OR at least `max_share` of THAT file's beats have one
    here (padding this episode with new beats does not dilute the copy), and at least `min_same` beats are the same. `cuts` = this episode's
    clip table ({slug: {source_sha256, source_in, source_out}}), used to compare the footage instead of the clip's name. `search` None = not run.
    Two signals, either one fires the same issue (`signals` lists which): the beat signal above, and the headline signal (_headline_matches:
    same normalised headline, whatever the media / clip / footage; same share and minimum). Search roots: the skill dir, every other
    <projects-type root>/<name>/ (copy_search_for; a project with our avatar is skipped), and <repo>/remotion-composer/src/*.json
    (non-recursive; other JSON there is skipped silently). metrics.copy.roots = the per-root counters (the report's copy_search.roots).
    episode-not-regular-file (error): the episode is a symlink / not a regular file / below a symlink inside projects/ (search['own_problem']).
    copy-search-incomplete (error): the walk ran out of `budget` seconds (a search that did not finish proves nothing)."""
    mine = beat_triples(ep['beats'], cuts)
    m = {'searched': search is not None, 'compared_files': 0, 'unreadable_files': 0, 'unreadable_dirs': 0, 'skipped_nonregular': 0,
         'skipped_large': 0, 'files_seen': 0, 'parsed': 0, 'complete': True, 'seconds': 0.0,
         'max_share': max_share, 'min_same': min_same, 'best_match': None, 'roots': _root_records(search) if search is not None else []}
    metrics['copy'] = m
    if search is None:
        return
    problem = search.get('own_problem')
    if problem:
        issues.append(_issue('episode-not-regular-file', 'error', None, None, str(search.get('own_file')),
                             'the episode must be a regular file inside its own project folder, not a link to another file (%s); '
                             'write the episode itself into <project>/artifacts/episode.json' % problem))
    if not mine:
        return
    started = time.monotonic()
    results = []
    for f in copy_candidates(search, m, started + budget):
        if time.monotonic() - started > budget:
            m['complete'] = False
            break
        silent = bool(search.get('composer_src')) and os.path.dirname(f) == str(search['composer_src'])     # composer src: only episodes take part
        if not silent:
            m['files_seen'] += 1
        try:
            got = _episode_beats(f, m)
        except ValueError as e:
            if silent:
                continue
            if 'too large' in str(e):
                m['skipped_large'] += 1
            else:
                m['unreadable_files'] += 1
            continue
        except (OSError, UnicodeDecodeError, RecursionError, MemoryError):
            if not silent:
                m['unreadable_files'] += 1
            continue
        if got is None:
            continue
        other_beats, other_cuts = got
        theirs = beat_triples(other_beats, other_cuts)
        if not theirs:
            continue
        m['compared_files'] += 1
        sm, st = _matches(mine, theirs)
        hsm, hnm, hst, hnt = _headline_matches(mine, theirs)
        sigs = {'beat': _signal(sm, len(mine), st, len(theirs), max_share, min_same),
                'headline': _signal(hsm, hnm, hst, hnt, max_share, min_same)}
        fired = [k for k, v in sigs.items() if v['flagged']]
        # the signal that decides (and is named in the message): the strongest one that fired, else the beat signal
        main = max(fired or ['beat'], key=lambda k: (max(sigs[k]['share_mine'], sigs[k]['share_theirs']), k == 'beat'))
        mm = sigs[main]
        if mm['share_theirs'] > mm['share_mine']:
            side = (mm['share_theirs'], mm['same_theirs'], mm['eligible_theirs'])
        else:
            side = (mm['share_mine'], mm['same_mine'], mm['eligible_mine'])
        results.append({'flag': bool(fired), 'file': str(f), 'share': side[0], 'same': side[1], 'eligible': side[2],
                        'share_mine': mm['share_mine'], 'same_mine': mm['same_mine'], 'eligible_mine': mm['eligible_mine'],
                        'share_theirs': mm['share_theirs'], 'same_theirs': mm['same_theirs'], 'eligible_theirs': mm['eligible_theirs'],
                        'signals': fired, 'by_signal': {k: {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in sigs.items()}})
    m['seconds'] = round(time.monotonic() - started, 3)
    if not m['complete']:
        issues.append(_issue('copy-search-incomplete', 'error', None, None, None,
                             'the search for a copied episode did not finish within %.0f s (%d files looked at): stop and report this; the run cannot '
                             'be certified until the copy search completes (do not change any file outside this project to make it finish)' % (budget, m['files_seen'])))
    if not results:
        return
    results.sort(key=lambda r: (not r['flag'], -r['share'], r['file']))
    best = results[0]
    m['best_match'] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in best.items() if k != 'flag'}
    over = [r for r in results if r['flag']]
    if over:
        issues.append(_issue('episode-copied', 'error', None, None, best['file'],
                             'this episode is a copy of %s: %d of its %d beats are also in that file (%.0f %%), and %d of that '
                             'file\'s %d beats are also here (%.0f %%) (limit %.0f %%, at least %d beats): an episode must be written from THIS '
                             'video\'s script and source, not copied from another episode; delete the copy and build the beats from the script' % (
                                 best['file'], best['same_mine'], best['eligible_mine'], best['share_mine'] * 100, best['same_theirs'],
                                 best['eligible_theirs'], best['share_theirs'] * 100, max_share * 100, min_same),
                             share=round(best['share'], 4), same=best['same'], eligible=best['eligible'],
                             share_mine=round(best['share_mine'], 4), share_theirs=round(best['share_theirs'], 4), signals=best['signals'],
                             others=[{'file': r['file'], 'share': round(r['share'], 4)} for r in over[1:6]]))


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
    check_stock(ep, inp, issues, metrics)
    check_source_reuse(ep, inp, th, issues)
    check_crop_trims(ep, issues)
    check_evidence(ep, inp, th, issues, metrics)
    check_copy(ep, inp.copy_search, issues, metrics, cuts=inp.cuts)
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
    ap.add_argument('--relevance', help='relevance report; only reported in metrics.relevance, never evidence (stock / ai footage is always an error)')
    ap.add_argument('--evidence', help='visual_evidence.json: [{t, src, cue_line, subject_terms[], seen}]')
    ap.add_argument('--frames-report', help='frame_checks.py cutaways report (OCR text per beat)')
    ap.add_argument('--source-timed', help='timed transcript of the ORIGINAL video: [{start,end,text}]')
    ap.add_argument('--schema-validator', help='path of episode_schema.mjs (default: next to this script)')
    ap.add_argument('--vo-end', type=float, help='voice-over end seconds when the episode file does not carry it')
    ap.add_argument('--legacy', action='store_true', help='V3 replay data: schema validator may be absent, legacy list/TSX accepted, '
                    'evidence not required (subject terms from the src slug)')
    ap.add_argument('--set', action='append', default=[], metavar='KEY=JSON', help='override a threshold for this run')
    ap.add_argument('--copy-root', action='append', default=[], metavar='DIR',
                    help='projects-type root of the episode-copied search (repeatable; every sub-directory is one project); '
                    'default: the parent of the episode\'s own project. Not a directory -> exit 4')
    ap.add_argument('--avatar', metavar='FILE', help='our avatar mp4: in --copy-root projects a project with the same avatar (sha256) is not compared '
                    '(re-doing the same video is allowed)')
    ap.add_argument('--report', required=True)
    a = ap.parse_args(argv)
    missing = [r for r in a.copy_root if not Path(r).is_dir()]
    if missing:
        msg = ('--copy-root %s does not exist or is not a directory: the search for a copied episode cannot run; stop and report this '
               '(the check passes the projects folder of the checkout)' % ', '.join(missing))
        report = {'schema': SCHEMA, 'version': VERSION, 'pass': False,
                  'issues': [_issue('copy-root-missing', 'error', None, None, missing[0], msg)], 'metrics': {}, 'thresholds': {}, 'inputs': {}}
        Path(a.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 4
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
            asset_dir = json.loads(Path(a.beats).read_text(encoding='utf-8')).get('assetDir')
            if isinstance(asset_dir, str):
                ep['assetDir'] = asset_dir
        if ep['format'] == 'json-object':
            if validator.exists():
                schema_issues, schema_summary = run_schema(a.beats, a.captions, validator)
                paths['schema_validator'] = str(validator)
            elif not a.legacy:
                schema_issues = [_issue('schema-validator-missing', 'error', None, None, str(validator), 'episode_schema.mjs not found; structural validation did not run')]
        elif not a.legacy:
            schema_issues = [_issue('schema', 'error', None, None, None, 'episode is not a V4 object JSON (%s); legacy formats need --legacy' % ep['format'])]
        if a.avatar and not Path(a.avatar).is_file():
            raise ed.EpisodeFormatError('--avatar %s is not a readable file' % a.avatar)
        hashes = {p: _sha(p) for p in paths.values()}
    except (ed.EpisodeFormatError, OSError, ValueError) as e:
        report = {'schema': SCHEMA, 'version': VERSION, 'pass': False,
                  'issues': [_issue('input', 'error', None, None, None, str(e))], 'metrics': {}, 'thresholds': {}, 'inputs': {}}
        Path(a.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    inp = Inputs(script_lines, tokens, line_starts, cuts, source, relevance, relevance_given=bool(a.relevance),
                 evidence=evidence, frames=frames, timed=timed, chapters=chapters, legacy=a.legacy,
                 frames_given=bool(a.frames_report), frame_counts=frame_counts,
                 copy_search=copy_search_for(a.beats, copy_roots=a.copy_root, avatar=a.avatar))
    issues, metrics = lint_content(ep, inp, thresholds)
    issues = schema_issues + issues
    metrics['schema'] = schema_summary
    metrics['issueCounts'] = count_codes(issues)
    copy_m = metrics.get('copy') or {}
    report = {'schema': SCHEMA, 'version': VERSION, 'pass': not any(i['severity'] == 'error' for i in issues),
              'issues': issues, 'metrics': metrics, 'thresholds': thresholds, 'inputs': hashes,
              'copy_search': {'roots': copy_m.get('roots', []), 'incomplete': not copy_m.get('complete', True)}}
    out = json.dumps(report, ensure_ascii=False, indent=2)
    Path(a.report).write_text(out, encoding='utf-8')
    print(out)
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
