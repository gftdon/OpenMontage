#!/usr/bin/env python3
"""Shared loader for the content lint (lint_content.py) and cue_times.py.

ALL knowledge of the episode file format lives in the "FORMAT ADAPTER" section.
The V4 episode schema (assets/episode.schema.json, validated by episode_schema.mjs) is owned by the engine
workstream; when its field names change only that section (and its tests) should need edits.
tests/test_real_fixtures.py runs this loader against the engine's own fixtures and a real V4 episode.

Formats accepted by load_episode():
  * object JSON  yt-news-v4-episode/1: {"voEndSec","totalDurationSec","ctaT","cta","endcard","beats":[...],...}  (V4, primary)
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
# Every episode field-name assumption is in this section. Primary format: V4
# `episode.json` ("yt-news-v4-episode/1", assets/episode.schema.json). Legacy V3 list JSON /
# TSX (stats[].t, cards[].t, lower.t, cardKind, ...) stays readable for replay.
#
# V4 beat: t, mode full|pip, media broll|clip|typo, layout stage|wide, src, from, origin,
#   srcCrop, kicker, headline, sub, stats[{at,dur,big?,label}], punch[{at,..}],
#   typo card|summary3|final4|vs, cards[{at,lines[]}], items[{at,text}],
#   vs{left{title,badge,lines[]},right{..},conclusion}, lower{at,dur,title,sub}
# V4 top level: voEndSec, totalDurationSec, ctaT, cta, endcard{eyebrow,titleA,titleB,cta},
#   brand, dateLabel, breakingLabel, officialTag, page{domain,path}, brollDur, beats[]
BEAT_TEXT_KEYS = ('kicker', 'headline', 'sub')          # visible for the whole beat
START_KEYS = ('at', 't')                                 # item start: V4 `at`, legacy `t`
DURATION_KEY = 'dur'                                     # item duration -> [start, start+dur)
LOWER_DEFAULT_DUR = 6.0                                  # legacy (V3) lower-third default
META_VO_END_KEYS = ('voEndSec', 'voEnd', 'vo_end', 'VO_END_SEC')
META_TOTAL_KEYS = ('totalDurationSec', 'TOTAL_DURATION_SEC')
META_END_CARD_KEYS = ('endCardSeconds', 'end_card_seconds', 'endCard')   # legacy: seconds
META_CTA_KEYS = ('cta', 'CTA')
META_CTA_T_KEYS = ('ctaT', 'CTA_T')
DEFAULT_END_CARD_SECONDS = 4.0
CHROME_KEYS = ('brand', 'dateLabel', 'breakingLabel', 'officialTag')      # constant page chrome
ENDCARD_KEYS = ('eyebrow', 'titleA', 'titleB', 'cta')
VS_SIDE_KEYS = ('title', 'badge')
ITEM_TEXT_KEYS = ('text', 'label', 'title')                                # when an item is a dict


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
    """Visible window of a timed item. `dur` present -> [start, start+dur) (not cut at the beat end)."""
    start = _item_start(item, default_start)
    dur = num(item.get(DURATION_KEY)) if isinstance(item, dict) else None
    if dur is not None and dur > 0:
        return start, start + dur
    if default_dur is not None:
        return start, start + default_dur
    return start, default_end


def beat_items(beat):
    """Typography items of a beat as a list of str / {at?, text} (summary3 / final4)."""
    v = beat.get('items')
    return [x for x in v if _item_text(x)] if isinstance(v, list) else []


def text_fields(beat):
    """List of (field_name, text, start, end, kind) for every on-screen string of a beat.

    kind 'beat'  : kicker/headline/sub, vs.* and items without their own `at` (whole beat)
    kind 'timed' : stats, cards, items with `at`, lower
    Windows: stats / lower with `dur` -> [at, at+dur); cards -> [at, next card's at or beat end);
    items -> [at, beat end); legacy stats with only `t` -> until beat end.
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
    for j, item in enumerate(beat_items(beat)):
        txt = _item_text(item)
        if isinstance(item, dict) and _item_start(item, None) is not None:
            ws, we = _item_window(item, t, end)
            out.append(('items[%d]' % j, txt, ws, we, 'timed'))
        else:
            out.append(('items[%d]' % j, txt, t, end, 'beat'))
    vs = beat.get('vs')
    if isinstance(vs, dict):
        for side in ('left', 'right'):
            sd = vs.get(side)
            if not isinstance(sd, dict):
                continue
            for k in VS_SIDE_KEYS:
                if isinstance(sd.get(k), str) and sd[k].strip():
                    out.append(('vs.%s.%s' % (side, k), sd[k].strip(), t, end, 'beat'))
            if isinstance(sd.get('lines'), list):
                for j, line in enumerate(sd['lines']):
                    if _item_text(line):
                        out.append(('vs.%s.lines[%d]' % (side, j), _item_text(line), t, end, 'beat'))
        if isinstance(vs.get('conclusion'), str) and vs['conclusion'].strip():
            out.append(('vs.conclusion', vs['conclusion'].strip(), t, end, 'beat'))
    cta = beat.get('cta')       # legacy only: a beat-level cta
    if isinstance(cta, dict):
        cta = _item_text(cta)
    if isinstance(cta, str) and cta.strip():
        out.append(('cta', cta.strip(), t, end, 'beat'))
    return out


def episode_text_fields(ep):
    """Top-level text of the episode as (field_name, text, start, end, kind).

    kind 'chrome' (brand, dateLabel, breakingLabel, officialTag, page.*): constant page chrome, whole video.
    cta: kind 'timed', window [ctaT, voEndSec].   endcard.*: kind 'beat', window [voEndSec, voEndSec+end card].
    """
    top = ep.get('top') or {}
    vo = ep['vo_end']
    out = []
    for k in CHROME_KEYS:
        if isinstance(top.get(k), str) and top[k].strip():
            out.append((k, top[k].strip(), 0.0, vo, 'chrome'))
    page = top.get('page')
    if isinstance(page, dict):
        for k in ('domain', 'path'):
            if isinstance(page.get(k), str) and page[k].strip():
                out.append(('page.' + k, page[k].strip(), 0.0, vo, 'chrome'))
    cta = episode_cta(ep)
    if cta and ep.get('cta'):
        cta_t = ep.get('cta_t')
        out.append(('cta', cta, cta_t if cta_t is not None else vo, vo, 'timed'))
    endcard = top.get('endcard')
    if isinstance(endcard, dict):
        total = ep.get('end_card_seconds') or DEFAULT_END_CARD_SECONDS
        for k in ENDCARD_KEYS:
            if isinstance(endcard.get(k), str) and endcard[k].strip():
                out.append(('endcard.' + k, endcard[k].strip(), vo, vo + total, 'beat'))
    return out


def episode_cta(ep):
    """CTA text (closing question), from episode-level `cta` or a legacy beat-level `cta`; '' when absent."""
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
    vo = num(first(META_VO_END_KEYS))
    total = num(first(META_TOTAL_KEYS))
    end_card = num(first(META_END_CARD_KEYS))
    if end_card is None and vo is not None and total is not None:
        end_card = total - vo
    return {
        'vo_end': vo,
        'end_card_seconds': end_card,
        'cta': first(META_CTA_KEYS),
        'cta_t': num(first(META_CTA_T_KEYS)),
        'broll_dur': data.get('brollDur'),
        'top': data,
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
        'cta': meta.get('cta'), 'cta_t': meta.get('cta_t'), 'broll_dur': meta.get('broll_dur'),
        'top': meta.get('top') or {}, 'format': fmt,
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
    meta = {'vo_end': vo, 'end_card_seconds': (total - vo) if vo is not None and total is not None else None,
            'cta_t': constant('CTA_T')}
    return _finish(beats, meta, 'tsx', vo_end, fallback_vo_end)


# ----------------------------- visible picture region ------------------------------

SOURCE_W, SOURCE_H = 1920, 1080                       # srcCrop coordinates and the engine's video element are always 1920x1080
PICTURE_BOX = {'stage': (1138, 640), 'wide': (1280, 720)}   # engine LANES split.picture / wide.picture


def visible_region(layout, src_w, src_h, crop):
    """Part of a source clip that the viewer actually sees -> (x, y, w, h) in PIXELS OF THE FILE (src_w x src_h).

    The engine (YtNewsStyle01V4.tsx srcCropStyle) stretches the file to 1920x1080 (objectFit fill), takes `crop` (a srcCrop dict in
    1920x1080 space; None = the whole frame) and cover-fits it into the picture box of the layout: s = max(boxW/cropW, boxH/cropH),
    so the visible region is (boxW/s, boxH/s), centred on the crop. Results are floats, in file pixels (for a 1920x1080 file they
    equal score_relevance.visible_region). Fails closed with ValueError: unknown layout, bad / non-positive resolution, a crop that
    is not {x,y,w,h} of finite numbers, has w/h <= 0 or leaves the 1920x1080 frame. Never falls back to the whole frame.
    """
    box = PICTURE_BOX.get(layout) if isinstance(layout, str) else None
    if box is None:
        raise ValueError('unknown layout %r (expected one of %s)' % (layout, ', '.join(sorted(PICTURE_BOX))))
    for name, v in (('width', src_w), ('height', src_h)):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
            raise ValueError('bad source %s %r' % (name, v))
    if crop is None:
        cx, cy, cw, ch = 0.0, 0.0, float(SOURCE_W), float(SOURCE_H)
    else:
        vals = [num(crop.get(k)) if isinstance(crop, dict) else None for k in 'xywh']
        if any(v is None for v in vals):
            raise ValueError('srcCrop must be {x, y, w, h} of finite numbers, got %r' % (crop,))
        cx, cy, cw, ch = vals
        if cw <= 0 or ch <= 0 or cx < 0 or cy < 0 or cx + cw > SOURCE_W + 1e-6 or cy + ch > SOURCE_H + 1e-6:
            raise ValueError('srcCrop %r is outside the %dx%d frame' % (crop, SOURCE_W, SOURCE_H))
    scale = max(box[0] / cw, box[1] / ch)
    w0, h0 = box[0] / scale, box[1] / scale
    x0, y0 = cx + (cw - w0) / 2, cy + (ch - h0) / 2
    sx, sy = src_w / SOURCE_W, src_h / SOURCE_H
    return (x0 * sx, y0 * sy, w0 * sx, h0 * sy)


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
    """Source material as {'numbers': transcript+title+description, 'all': +chapters, 'title': title, 'meta': title+description}.

    Chapters are excluded from number provenance (their timestamps would match any number).
    """
    parts = [_read_optional(transcript)]
    title = ''
    meta_parts = []
    if meta:
        try:
            m = json.loads(_read_optional(meta))
        except ValueError as e:
            raise EpisodeFormatError('invalid source meta JSON %s: %s' % (meta, e))
        for k in ('title', 'description', 'description_full'):
            if isinstance(m.get(k), str):
                parts.append(m[k])
                meta_parts.append(m[k])
        if isinstance(m.get('title'), str):
            title = m['title']
    numbers = norm_digits('\n'.join(parts))
    return {'numbers': numbers, 'all': numbers + '\n' + _read_optional(chapters), 'title': title,
            'meta': norm_digits('\n'.join(meta_parts))}


_CHAPTER = re.compile(r'^\s*((?:\d+:)?\d+:\d{2}(?:\.\d+)?|\d+(?:\.\d+)?)\s+(\S.*?)\s*$')


def _clock_seconds(text):
    if ':' in text:
        secs = 0.0
        for part in text.split(':'):
            secs = secs * 60 + float(part)
        return secs
    return float(text)


def load_chapters(path):
    """chapters.txt (`  130.0  Title` or `2:10 Title` per line) -> sorted [{'start','end','title'}] (last end = inf)."""
    rows = []
    for line in _read_optional(path).split('\n'):
        m = _CHAPTER.match(line)
        if m:
            rows.append({'start': _clock_seconds(m[1]), 'title': m[2]})
    rows.sort(key=lambda r: r['start'])
    for i, r in enumerate(rows):
        r['end'] = rows[i + 1]['start'] if i + 1 < len(rows) else float('inf')
    return rows


def _read_json(path, what):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise EpisodeFormatError('cannot read %s %s: %s' % (what, path, e))


def load_timed_transcript(path):
    """Timed transcript of the ORIGINAL video: [{start,end,text}] (also {segments|transcript:[..]}, s/e keys)."""
    data = _read_json(path, 'timed transcript')
    if isinstance(data, dict):
        data = data.get('segments') or data.get('transcript') or data.get('chunks') or []
    rows = []
    for r in data if isinstance(data, list) else []:
        if not isinstance(r, dict) or not isinstance(r.get('text'), str):
            continue
        s = num(r.get('start', r.get('s')))
        e = num(r.get('end', r.get('e')))
        if s is not None:
            rows.append({'start': s, 'end': e if e is not None else s, 'text': r['text']})
    return rows


def load_evidence(path):
    """visual_evidence.json: [{t, src, cue_line, subject_terms[], seen}] (also {entries|evidence:[..]})."""
    data = _read_json(path, 'evidence')
    if isinstance(data, dict):
        data = data.get('entries') or data.get('evidence') or []
    if not isinstance(data, list):
        raise EpisodeFormatError('evidence must be a list of entries')
    return [r for r in data if isinstance(r, dict)]


def load_frames_report(path):
    """frame_checks.py `cutaways` report -> {(round(t,2), src): [ocr line, ...]}. Read defensively."""
    data = _read_json(path, 'frames report')
    beats = data.get('beats') if isinstance(data, dict) else None
    out = {}
    for b in beats if isinstance(beats, list) else []:
        if not isinstance(b, dict):
            continue
        t = num(b.get('t'))
        if t is None:
            continue
        lines = []
        for f in b.get('frames') or []:
            ocr = f.get('ocr') if isinstance(f, dict) else None
            if isinstance(ocr, list):
                lines += [x for x in ocr if isinstance(x, str)]
        out[(round(t, 2), b.get('src'))] = lines
    return out


def load_frame_counts(path):
    """frame_checks.py `cutaways` report -> {(round(t,2), src): number of evidence frames extracted for that beat}."""
    data = _read_json(path, 'frames report')
    beats = data.get('beats') if isinstance(data, dict) else None
    out = {}
    for b in beats if isinstance(beats, list) else []:
        t = num(b.get('t')) if isinstance(b, dict) else None
        if t is not None:
            out[(round(t, 2), b.get('src'))] = len([f for f in (b.get('frames') or []) if isinstance(f, dict)])
    return out


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


# ------------------------- Thai number words ---------------------------------
NUM_WORDS = ('ศูนย์', 'หนึ่ง', 'เอ็ด', 'สอง', 'ยี่', 'สาม', 'สี่', 'ห้า', 'หก', 'เจ็ด', 'แปด', 'เก้า', 'สิบ', 'ร้อย', 'พัน', 'หมื่น', 'แสน', 'ล้าน')
DIGIT_WORDS = {'ศูนย์': '0', 'หนึ่ง': '1', 'สอง': '2', 'สาม': '3', 'สี่': '4', 'ห้า': '5', 'หก': '6', 'เจ็ด': '7', 'แปด': '8', 'เก้า': '9'}
_NUM_BODY = re.compile('(?:' + '|'.join(sorted(NUM_WORDS, key=len, reverse=True)) + ')+')
_DIGIT_RUN = re.compile('(?:' + '|'.join(sorted(DIGIT_WORDS, key=len, reverse=True)) + ')+')
_DIGIT_ONE = re.compile('|'.join(sorted(DIGIT_WORDS, key=len, reverse=True)))
_THAI_TOKENIZER = []


def thai_tokenizer():
    """pythainlp newmm word_tokenize, or None when pythainlp is not importable (cached)."""
    if not _THAI_TOKENIZER:
        try:
            from pythainlp.tokenize import word_tokenize
            _THAI_TOKENIZER.append(word_tokenize)
        except ImportError:
            _THAI_TOKENIZER.append(None)
    return _THAI_TOKENIZER[0]


def _fmt_number(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v)


def _words_to_number(words):
    """Run of Thai number words -> normalised value string ('13000', '3.5') or None (never raises)."""
    try:
        from pythainlp.util import thaiword_to_num
    except ImportError:
        return None
    try:
        if words.count('จุด') > 1:
            return None
        if 'จุด' in words:
            head, tail = words.split('จุด')
            if not head or not _DIGIT_RUN.fullmatch(tail):
                return None
            whole = _fmt_number(thaiword_to_num(head))
            return whole + '.' + ''.join(DIGIT_WORDS[w] for w in _DIGIT_ONE.findall(tail))
        return _fmt_number(thaiword_to_num(words))
    except Exception:   # thaiword_to_num raises ValueError on ill-formed runs ("สองสาม")
        return None


def thai_number_runs(line):
    """Maximal runs of Thai number words in one script line -> [(start, end, value_str)].

    Works on newmm tokens, so "สามารถ" (can) or "สี่เหลี่ยม" (square) are never read as numbers.
    A token counts if it is made only of number words (a leading ordinal marker "ที่" is allowed:
    "ที่สี่" -> สี่). Adjacent tokens form a run; จุด + digit words give decimals; a run that
    thaiword_to_num rejects ("สองสาม" = a couple) is skipped.
    """
    tok = thai_tokenizer()
    if tok is None or not THAI_RUN_HINT.search(line):
        return []
    items, pos = [], 0
    for t in tok(line, engine='newmm'):
        s, pos = pos, pos + len(t)
        if t == 'จุด':
            items.append((s, pos, 'จุด'))
        elif _NUM_BODY.fullmatch(t):
            items.append((s, pos, t))
        elif t.startswith('ที่') and _NUM_BODY.fullmatch(t[len('ที่'):]):
            items.append((s + len('ที่'), pos, t[len('ที่'):]))
        else:
            items.append(None)
    runs, cur = [], []
    for it in items + [None]:
        if it is not None and (not cur or cur[-1][1] == it[0]):
            cur.append(it)
            continue
        if cur:
            while cur and cur[0][2] == 'จุด':
                cur = cur[1:]
            while cur and cur[-1][2] == 'จุด':
                cur = cur[:-1]
            if cur:
                v = _words_to_number(''.join(c[2] for c in cur))
                if v is not None:
                    runs.append((cur[0][0], cur[-1][1], v))
        cur = [it] if it is not None else []
    return runs


THAI_RUN_HINT = re.compile('|'.join(NUM_WORDS))


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
        self._build_numeric_view()
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

    def _build_numeric_view(self):
        """nstream: the script with every Thai number-word run replaced by its digits.

        nlines/nstream mirror lines/stream; nmap[i] is the index in `stream` of nstream[i] (a replaced run
        maps all its digits to the run's first character, so it keeps the time of its first token).
        """
        self.nlines, self.nmap = [], []
        self.number_runs = []          # (line_no, start_char, end_char, value) in `stream` coordinates
        for n, line in enumerate(self.lines, 1):
            base = self.offsets[n - 1]
            out, cursor = [], 0
            for rs, re_, val in thai_number_runs(line):
                out.append(line[cursor:rs])
                self.nmap += range(base + cursor, base + rs)
                out.append(val)
                self.nmap += [base + rs] * len(val)
                self.number_runs.append((n, base + rs, base + re_, val))
                cursor = re_
            out.append(line[cursor:])
            self.nmap += range(base + cursor, base + len(line))
            self.nlines.append(''.join(out))
            if n < len(self.lines):
                self.nmap.append(base + len(line))     # the joining newline
        self.nstream = '\n'.join(self.nlines)

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

    def occurrences_numeric(self, pattern):
        """Like occurrences() on the numeric view: [(orig_start_char, matched, time|None, line, nstream_end)]."""
        out = []
        for m in pattern.finditer(self.nstream):
            orig = self.nmap[m.start()]
            out.append((orig, m.group(0), self.time_at(orig), self.line_of(orig), m.end()))
        return out

    def occurrences(self, pattern):
        """[(start_char, matched_text, spoken_time|None, line)] for every match of a compiled regex."""
        out = []
        for m in pattern.finditer(self.stream):
            out.append((m.start(), m.group(0), self.time_at(m.start()), self.line_of(m.start())))
        return out
