#!/usr/bin/env python3
"""Shared loader for the content lint (lint_content.py) and cue_times.py.

ALL knowledge of the episode file format lives in the "FORMAT ADAPTER" section.
The V4 episode schema is owned by the engine workstream and is not final; when
field names change only that section (and its tests) should need edits.

Formats accepted by load_episode():
  * object JSON  {"beats":[...], "endCardSeconds":..., "cta":..., "voEnd":..., "brollDur":{...}}  (V4, primary)
  * list JSON    [beat, beat, ...]                                                                  (legacy replay)
  * .tsx composition with `const BEATS = [...]`, VO_END_SEC, TOTAL_DURATION_SEC                     (legacy, via broll_ledger.parse_beats, same as lint_beats.py)

Timing conventions (seconds, absolute on the voice-over clock):
  * beat window  = [t, end]   (end = next beat's t; last beat = voice-over end)
  * V4 item (stat / card / lower / typo item) with `at` and/or `dur`:   [at, at+dur]   (NOT cut at the beat end)
  * legacy item with only `t`: stats run to the beat end, cards to the next card's t / beat end,
    lower for lower.dur (default 6 s).
"""
import bisect
import difflib
import json
import math
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

THAI_DIGITS = str.maketrans('๐๑๒๓๔๕๖๗๘๙', '0123456789')


class EpisodeFormatError(ValueError):
    """Bad or unrecognised episode / input file."""


def norm_digits(text):
    """Thai digits -> Arabic. One-to-one, so character offsets are preserved."""
    return text.translate(THAI_DIGITS)


def num(v):
    if isinstance(v, bool):
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


# ============================ FORMAT ADAPTER =================================
# Every V4 field-name assumption is in this section. Keep it self-contained.
BEAT_TEXT_KEYS = ('kicker', 'headline', 'sub')          # visible for the whole beat
START_KEYS = ('at', 't')                                 # item start: V4 `at`, legacy `t`
DURATION_KEY = 'dur'                                     # item duration (V4; legacy lower.dur)
LOWER_DEFAULT_DUR = 6.0                                  # legacy lower-third default
META_VO_END_KEYS = ('voEnd', 'vo_end', 'voEndSec', 'VO_END_SEC')
META_END_CARD_KEYS = ('endCardSeconds', 'end_card_seconds', 'endCard')
META_CTA_KEYS = ('cta', 'CTA')
CARD_KIND_PATHS = (('cardKind',), ('card', 'kind'), ('typo', 'kind'))       # typo card kind
CARD_ITEMS_PATHS = (('items',), ('card', 'items'), ('typo', 'items'))       # typo card items
CARD_TITLE_PATHS = (('card', 'title'), ('typo', 'title'))
ITEM_TEXT_KEYS = ('text', 'label', 'title')                                  # when an item is a dict


def _dig(obj, path):
    for key in path:
        if not isinstance(obj, dict) or key not in obj:
            return None
        obj = obj[key]
    return obj


def typo_card(beat):
    """Return {'kind': str|None, 'items': [item,...]} for a typography card beat.

    kind from cardKind / card.kind / typo.kind (falling back to the first cards[].kind);
    items from items / card.items / typo.items, each a string or {text,...} dict.
    """
    kind = next((v for v in (_dig(beat, p) for p in CARD_KIND_PATHS) if isinstance(v, str) and v), None)
    if kind is None and isinstance(beat.get('cards'), list):
        kind = next((c.get('kind') for c in beat['cards'] if isinstance(c, dict) and isinstance(c.get('kind'), str) and c['kind']), None)
    items = []
    for p in CARD_ITEMS_PATHS:
        v = _dig(beat, p)
        if isinstance(v, list):
            items = [x for x in v if _item_text(x)]
            break
    return {'kind': kind, 'items': items}


def _item_text(item):
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for k in ITEM_TEXT_KEYS:
            if isinstance(item.get(k), str) and item[k].strip():
                return item[k].strip()
    return ''


def _item_start(item, default):
    if isinstance(item, dict):
        for k in START_KEYS:
            n = num(item.get(k))
            if n is not None:
                return n
    return default


def _item_window(item, default_start, default_end=None, default_dur=None):
    """Visible window of a timed item. `dur` present -> [start, start+dur]."""
    start = _item_start(item, default_start)
    dur = num(item.get(DURATION_KEY)) if isinstance(item, dict) else None
    if dur is not None and dur > 0:
        return start, start + dur
    if default_dur is not None:
        return start, start + default_dur
    return start, default_end


def text_fields(beat):
    """List of (field_name, text, start, end, kind) for every on-screen string of a beat.

    kind 'beat'  : kicker/headline/sub and typo items without their own timing (whole beat)
    kind 'timed' : stats, cards, lower, timed typo items
    The beat must carry numeric `t` and `end`.
    """
    t, end = beat['t'], beat['end']
    out = []
    for k in BEAT_TEXT_KEYS:
        v = beat.get(k)
        if isinstance(v, str) and v.strip():
            out.append((k, v.strip(), t, end, 'beat'))
    lower = beat.get('lower')
    if isinstance(lower, dict):
        ws, we = _item_window(lower, t, default_dur=LOWER_DEFAULT_DUR)
        for k in ('title', 'sub'):
            if isinstance(lower.get(k), str) and lower[k].strip():
                out.append(('lower.' + k, lower[k].strip(), ws, we, 'timed'))
    stats = beat.get('stats')
    if isinstance(stats, list):
        for i, s in enumerate(stats):
            if not isinstance(s, dict):
                continue
            ws, we = _item_window(s, t, end)
            for k in ('big', 'label'):
                if isinstance(s.get(k), str) and s[k].strip():
                    out.append(('stats[%d].%s' % (i, k), s[k].strip(), ws, we, 'timed'))
    cards = beat.get('cards')
    if isinstance(cards, list):
        starts = [_item_start(c, t) if isinstance(c, dict) else t for c in cards]
        for i, c in enumerate(cards):
            if isinstance(c, str):
                c = {'lines': [c]}
            if not isinstance(c, dict):
                continue
            nxt = starts[i + 1] if i + 1 < len(cards) else end
            ws, we = _item_window(c, t, nxt)
            strings = []
            for key in ('lines', 'items'):
                v = c.get(key)
                if isinstance(v, list):
                    strings += [('cards[%d].%s[%d]' % (i, key, j), _item_text(x)) for j, x in enumerate(v)]
            for key in ('text', 'title'):
                if isinstance(c.get(key), str):
                    strings.append(('cards[%d].%s' % (i, key), c[key].strip()))
            out += [(f, s, ws, we, 'timed') for f, s in strings if s]
    for p in CARD_TITLE_PATHS:
        v = _dig(beat, p)
        if isinstance(v, str) and v.strip():
            out.append(('.'.join(p), v.strip(), t, end, 'beat'))
    for j, item in enumerate(typo_card(beat)['items']):
        txt = _item_text(item)
        if isinstance(item, dict) and any(isinstance(item.get(k), (int, float)) for k in START_KEYS + (DURATION_KEY,)):
            ws, we = _item_window(item, t, end)
            out.append(('items[%d]' % j, txt, ws, we, 'timed'))
        else:
            out.append(('items[%d]' % j, txt, t, end, 'beat'))
    cta = beat.get('cta')
    if isinstance(cta, dict):
        cta = _item_text(cta)
    if isinstance(cta, str) and cta.strip():
        out.append(('cta', cta.strip(), t, end, 'beat'))
    return out


def episode_cta(ep):
    """CTA text (end card), from episode-level `cta` or a beat-level `cta`; '' when absent."""
    cta = ep.get('cta')
    if isinstance(cta, dict):
        cta = _item_text(cta)
    if isinstance(cta, str) and cta.strip():
        return cta.strip()
    for b in ep['beats']:
        for f in text_fields(b):
            if f[0] == 'cta':
                return f[1]
    return ''


def _meta_from_object(data):
    def first(keys):
        for k in keys:
            if k in data:
                return data[k]
        return None
    return {
        'vo_end': num(first(META_VO_END_KEYS)),
        'end_card_seconds': num(first(META_END_CARD_KEYS)),
        'cta': first(META_CTA_KEYS),
        'broll_dur': data.get('brollDur'),
    }
# ========================== END FORMAT ADAPTER ===============================


def _plain(v):
    """broll_ledger.Raw tokens -> float / bool / str (nested)."""
    import broll_ledger as bl
    if isinstance(v, bl.Raw):
        s = str(v)
        if s in ('true', 'false'):
            return s == 'true'
        n = num(s)
        return n if n is not None else s
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


def _finish(beats, meta, fmt, vo_end_override, fallback_vo_end):
    if not isinstance(beats, list) or not beats:
        raise EpisodeFormatError('episode has no beats')
    clean = []
    for i, b in enumerate(beats):
        if not isinstance(b, dict):
            raise EpisodeFormatError('beat %d is not an object' % i)
        t = num(b.get('t'))
        if t is None or t < 0:
            raise EpisodeFormatError('beat %d has no valid t' % i)
        clean.append({**b, 't': t})
    clean.sort(key=lambda b: b['t'])
    vo_end = meta.get('vo_end')
    if vo_end is None:
        vo_end = vo_end_override
    if vo_end is None:
        vo_end = num(clean[-1].get('end'))
    if vo_end is None:
        vo_end = fallback_vo_end
    if vo_end is None or vo_end <= clean[-1]['t']:
        raise EpisodeFormatError('voice-over end unknown or not after the last beat (use --vo-end)')
    for i, b in enumerate(clean):
        nxt = clean[i + 1]['t'] if i + 1 < len(clean) else vo_end
        b['end'] = nxt
    return {
        'beats': clean, 'vo_end': vo_end, 'end_card_seconds': meta.get('end_card_seconds'),
        'cta': meta.get('cta'), 'broll_dur': meta.get('broll_dur'), 'format': fmt,
    }


def load_episode(path, vo_end=None, fallback_vo_end=None):
    """Load an episode (object JSON / list JSON / TSX) -> normalised dict.

    Returns {'beats':[{t,end,...}], 'vo_end', 'end_card_seconds', 'cta', 'broll_dur', 'format'}.
    vo_end precedence: file value, `vo_end` argument, last beat's explicit end, `fallback_vo_end`.
    """
    p = Path(path)
    try:
        text = p.read_text(encoding='utf-8')
    except OSError as e:
        raise EpisodeFormatError('cannot read %s: %s' % (path, e))
    if p.suffix.lower() in ('.tsx', '.ts', '.jsx', '.js'):
        return _from_tsx(text, vo_end, fallback_vo_end)
    try:
        data = json.loads(text)
    except ValueError as e:
        raise EpisodeFormatError('invalid JSON in %s: %s' % (path, e))
    if isinstance(data, list):
        return _finish(data, {}, 'json-list', vo_end, fallback_vo_end)
    if isinstance(data, dict) and isinstance(data.get('beats'), list):
        return _finish(data['beats'], _meta_from_object(data), 'json-object', vo_end, fallback_vo_end)
    raise EpisodeFormatError('episode JSON must be a list of beats or an object with a "beats" array')


def _from_tsx(text, vo_end, fallback_vo_end):
    import broll_ledger as bl
    try:
        beats = _plain(bl.parse_beats(text))
    except bl.BeatsParseError as e:
        raise EpisodeFormatError('TSX BEATS not parseable: %s' % e)

    def constant(name):
        m = re.search(r'const\s+' + name + r'\s*=\s*([\d.]+)\s*;', text)
        return float(m[1]) if m else None
    vo, total = constant('VO_END_SEC'), constant('TOTAL_DURATION_SEC')
    meta = {'vo_end': vo, 'end_card_seconds': (total - vo) if vo is not None and total is not None else None}
    return _finish(beats, meta, 'tsx', vo_end, fallback_vo_end)


# ------------------------------ script / words -------------------------------

def load_script_lines(path):
    try:
        text = Path(path).read_text(encoding='utf-8')
    except OSError as e:
        raise EpisodeFormatError('cannot read script %s: %s' % (path, e))
    lines = text.split('\n')
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        raise EpisodeFormatError('script is empty: %s' % path)
    return lines


_WORD_TOKEN = re.compile(r'(.+?)@(\d+(?:\.\d+)?)(?:\s+|$)')


def load_words(path):
    """Word timing -> list of {'text','start','end'|None,'line'|None}.

    words_by_line.txt:  `L<n>: word@time word@time ...` (a token may contain spaces)
    caption_pages_final.json: [{words:[{w,s,e}]}] or [{chunks:[{tokens:[{w,s,e}]}]}] (no line info)
    """
    try:
        text = Path(path).read_text(encoding='utf-8')
    except OSError as e:
        raise EpisodeFormatError('cannot read words %s: %s' % (path, e))
    tokens = []
    if text.lstrip().startswith(('[', '{')):
        try:
            pages = json.loads(text)
        except ValueError as e:
            raise EpisodeFormatError('invalid words JSON %s: %s' % (path, e))
        if isinstance(pages, dict):
            pages = pages.get('pages') or []
        for page in pages:
            words = page.get('words')
            if words is None:
                words = [tk for ch in page.get('chunks', []) for tk in ch.get('tokens', [])]
            for w in words:
                s = num(w.get('s'))
                if isinstance(w.get('w'), str) and s is not None:
                    tokens.append({'text': w['w'], 'start': s, 'end': num(w.get('e')), 'line': None})
    else:
        for raw in text.split('\n'):
            m = re.match(r'L(\d+):\s?(.*)$', raw.rstrip('\r'))
            if not m:
                continue
            line = int(m[1])
            found = _WORD_TOKEN.findall(m[2])
            for k, (w, s) in enumerate(found):
                nxt = float(found[k + 1][1]) if k + 1 < len(found) else None
                tokens.append({'text': w, 'start': float(s), 'end': nxt, 'line': line})
    if not tokens:
        raise EpisodeFormatError('no word timing tokens in %s' % path)
    return tokens


def load_line_starts(path):
    try:
        rows = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise EpisodeFormatError('cannot read line starts %s: %s' % (path, e))
    out = []
    for r in rows if isinstance(rows, list) else []:
        line, s, e = r.get('line'), num(r.get('start')), num(r.get('end'))
        if isinstance(line, int) and s is not None and e is not None:
            out.append({'line': line, 'start': s, 'end': e, 'text': r.get('text', '')})
    if not out:
        raise EpisodeFormatError('no usable rows in line starts %s' % path)
    return sorted(out, key=lambda r: r['line'])


def load_cuts(path):
    """_cuts.json -> {slug: {source_in, source_out, ...}} (accepts {clips:{...}} or the bare map)."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise EpisodeFormatError('cannot read cuts %s: %s' % (path, e))
    clips = data.get('clips', data) if isinstance(data, dict) else None
    if not isinstance(clips, dict):
        raise EpisodeFormatError('cuts must be an object with `clips`')
    return clips


def _read_optional(path):
    if not path:
        return ''
    try:
        return Path(path).read_text(encoding='utf-8')
    except OSError as e:
        raise EpisodeFormatError('cannot read %s: %s' % (path, e))


def load_source_text(transcript=None, meta=None, chapters=None):
    """Source material as {'numbers': transcript+title+description, 'all': +chapters}.

    Chapters are excluded from number provenance (their timestamps would match any number).
    """
    parts = [_read_optional(transcript)]
    if meta:
        try:
            m = json.loads(_read_optional(meta))
        except ValueError as e:
            raise EpisodeFormatError('invalid source meta JSON %s: %s' % (meta, e))
        for k in ('title', 'description', 'description_full'):
            if isinstance(m.get(k), str):
                parts.append(m[k])
    numbers = norm_digits('\n'.join(parts))
    return {'numbers': numbers, 'all': numbers + '\n' + _read_optional(chapters)}


# ----------------------------- text-search helpers ---------------------------

def number_regex(value):
    """Regex matching the number `value` (e.g. '13000', '3.5') as a whole number.

    Commas may sit between any digits ("13,000"), digit boundaries are enforced so
    '5' does not match inside '15', '2.5' or '5,000'.
    """
    body = ',?'.join(re.escape(c) for c in value)
    return re.compile(r'(?<!\d)(?<!\d[.,])' + body + r'(?!\d)(?![.,]\d)')


def text_regex(text):
    """Case-insensitive, whitespace-tolerant literal search pattern."""
    chars = [re.escape(c) for c in re.sub(r'\s+', '', norm_digits(text))]
    return re.compile(r'\s*'.join(chars), re.IGNORECASE)


class ScriptClock:
    """Maps every script character to the start time of the word-timing token that carries it."""

    def __init__(self, script_lines, tokens):
        self.lines = [norm_digits(l) for l in script_lines]
        self.stream = '\n'.join(self.lines)
        self.offsets = []
        pos = 0
        for l in self.lines:
            self.offsets.append(pos)
            pos += len(l) + 1
        self.times = [None] * len(self.stream)
        self.misaligned_lines = []
        self.unmatched_chars = 0
        if any(t['line'] is not None for t in tokens):
            by_line = {}
            for t in tokens:
                by_line.setdefault(t['line'], []).append(t)
            for n, line in enumerate(self.lines, 1):
                positions = [self.offsets[n - 1] + i for i, c in enumerate(line) if not c.isspace()]
                if not positions:
                    continue
                exact = self._align(positions, by_line.get(n, []))
                if not exact:
                    self.misaligned_lines.append(n)
        else:
            positions = [i for i, c in enumerate(self.stream) if not c.isspace()]
            self._align(positions, tokens)

    def _align(self, positions, tokens):
        s = ''.join(self.stream[i] for i in positions).lower()
        tchars, ttimes = [], []
        for tk in tokens:
            c = re.sub(r'\s+', '', tk['text']).lower()
            tchars.append(c)
            ttimes += [tk['start']] * len(c)
        tstr = ''.join(tchars)
        if s == tstr:
            for i, p in enumerate(positions):
                self.times[p] = ttimes[i]
            return True
        last = None
        sm = difflib.SequenceMatcher(None, s, tstr, autojunk=False)
        mapped = {}
        for a, b, size in sm.get_matching_blocks():
            for k in range(size):
                mapped[a + k] = ttimes[b + k]
        for i, p in enumerate(positions):
            if i in mapped:
                last = mapped[i]
                self.times[p] = last
            else:
                self.unmatched_chars += 1
                self.times[p] = last
        return False

    def time_at(self, idx):
        return self.times[idx] if 0 <= idx < len(self.times) else None

    def line_of(self, idx):
        return bisect.bisect_right(self.offsets, idx)  # 1-based script line number

    def occurrences(self, pattern):
        """[(start_char, matched_text, spoken_time|None, line)] for every match of a compiled regex."""
        out = []
        for m in pattern.finditer(self.stream):
            out.append((m.start(), m.group(0), self.time_at(m.start()), self.line_of(m.start())))
        return out
