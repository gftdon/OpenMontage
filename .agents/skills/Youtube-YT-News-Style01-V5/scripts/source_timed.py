#!/usr/bin/env python3
"""Timed transcript of the ORIGINAL (source) video, producible fully offline.

  source_timed.py from-vtt   <file.vtt>   --out transcript_timed.json
  source_timed.py from-json3 <file.json3> --out transcript_timed.json
  source_timed.py from-audio <source.mp4> --out transcript_timed.json [--lang en] [--model REPO]
                             [--start SEC] [--duration SEC]
  source_timed.py merge <part1.json> <part2.json> ... --out transcript_timed.json
                             (`merge part_*.json` is fine: the *.done.json markers of from-audio are ignored)

Output: [{"start": sec, "end": sec, "text": "..."}] with every segment <= ~8 s, sorted by start.

from-vtt / from-json3 read YouTube auto-subtitle files and drop the rolling-caption repeats.
from-audio runs the locally cached mlx-whisper model (same family the karaoke pipeline uses) with an
OFFLINE environment (HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1) and loads the model from its cache
snapshot directory, so a missing model fails fast instead of downloading. Interpreter and model cache are
FIXED paths under the passwd-database home (not $HOME): the V4 ASR venv <home>/.cache/yt-news-v4/asr-venv (built by a human with
setup_asr_venv.sh) and <home>/.cache/huggingface/hub. No environment variable (HOME, HF_HUB_CACHE, HF_HOME) redirects them, and
--model must be an HF repo id (owner/name, no wildcards) already in that cache (a directory path is refused, exit 2).
ffmpeg is the first executable of /opt/homebrew/bin, /usr/local/bin, /usr/bin (never $PATH) and runs under a minimal environment.
The whisper worker is started through asr_run.sh, which verifies the interpreter, the stdlib and the venv against the manifest
(outside python) and runs the Cellar python as `-I -S -B -X pycache_prefix=/var/empty` under `env -i` with a minimal environment
(HOME, PATH, LANG, TMPDIR), so PYTHONPATH / PYTHON* variables of the caller never reach it. --start/--duration transcribe
one window of the video (times stay in source-video seconds); `merge` joins the parts.
A finished from-audio leaves <out>.done.json (key = sha256 of audio + model + lang + window); calling it
again with the same arguments prints "already done" and returns at once.

Every malformed input ends as one `ERROR: ...` line on stderr (no traceback).
Exit codes: 0 ok, 2 bad input, 4 tool/model/venv missing or changed (nothing was downloaded), 1 other failure.
"""
import argparse
import glob
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
import tempfile

MAX_SEG = 8.0
DEFAULT_MODEL = 'mlx-community/whisper-large-v3-turbo'
OFFLINE_ENV = {'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'HF_DATASETS_OFFLINE': '1'}


class BadInput(Exception):
    pass


class ToolMissing(Exception):
    pass


# ---------------------------------------------------------------- shared helpers

def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float('inf')


def load_part(path):
    """One transcript part ([{start,end,text}], as written by from-vtt / from-json3 / from-audio) or BadInput."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except OSError as e:
        raise BadInput(f'{path}: {e.strerror or e}')
    except ValueError as e:
        raise BadInput(f'{path}: not valid JSON ({e})')
    if not isinstance(data, list):
        raise BadInput(f'{path}: not a part file (expected a JSON list of {{start,end,text}} segments)')
    for i, seg in enumerate(data):
        if not (isinstance(seg, dict) and isinstance(seg.get('text'), str) and _is_num(seg.get('start')) and _is_num(seg.get('end'))):
            raise BadInput(f'{path}: segment {i} is not {{start, end, text}} (not a part file)')
    return data


def _clean(text):
    return re.sub(r'\s+', ' ', text).strip()


def _split_long(start, end, text, max_seg=MAX_SEG):
    """Split an over-long segment at word boundaries, proportional to character position."""
    words = text.split()
    if end - start <= max_seg or len(words) < 2:
        return [{'start': round(start, 3), 'end': round(end, 3), 'text': text}]
    n = int(-(-(end - start) // max_seg))
    per = -(-len(words) // n)
    total = sum(len(w) + 1 for w in words)
    out, pos = [], 0
    for i in range(0, len(words), per):
        chunk = words[i:i + per]
        c0 = pos
        pos += sum(len(w) + 1 for w in chunk)
        out.append({'start': round(start + (end - start) * c0 / total, 3),
                    'end': round(start + (end - start) * pos / total, 3), 'text': ' '.join(chunk)})
    return out


def _finish(segs, max_seg=MAX_SEG):
    """Sort, drop empties, clamp overlaps (rolling captions) and enforce the length cap."""
    segs = [s for s in segs if s['text']]
    segs.sort(key=lambda s: (s['start'], s['end']))
    out = []
    for i, s in enumerate(segs):
        end = s['end']
        if i + 1 < len(segs) and segs[i + 1]['start'] < end:
            end = max(s['start'], segs[i + 1]['start'])
        if end <= s['start']:
            end = s['start'] + 0.01
        out.extend(_split_long(s['start'], end, s['text'], max_seg))
    return out


def split_whisper_segments(segments, max_seg=MAX_SEG):
    """mlx-whisper segments (with word timestamps when present) -> <= max_seg second segments.

    Long segments are cut at the last sentence/clause punctuation inside the window (when it lies past
    half the window), otherwise at the word that would overflow it."""
    out = []
    for seg in segments:
        words = [w for w in (seg.get('words') or []) if _clean(w.get('word', ''))]
        s0, s1 = float(seg['start']), float(seg['end'])
        if not words:
            text = _clean(seg.get('text', ''))
            out.extend(_split_long(s0, s1, text, max_seg) if text else [])
            continue
        cur = []
        for w in words:
            ws, we = float(w['start']), float(w['end'])
            if cur and we - cur[0][1] > max_seg:
                cut = None
                for k in range(len(cur) - 1, -1, -1):
                    if re.search(r'[.!?;:,]$', cur[k][0].strip()) and cur[k][2] - cur[0][1] > max_seg / 2:
                        cut = k + 1
                        break
                if cut is None:
                    cut = len(cur)
                head, cur = cur[:cut], cur[cut:]
                out.append({'start': round(head[0][1], 3), 'end': round(head[-1][2], 3),
                            'text': _clean(''.join(x[0] for x in head))})
            cur.append((w['word'], ws, we))
        if cur:
            out.append({'start': round(cur[0][1], 3), 'end': round(cur[-1][2], 3),
                        'text': _clean(''.join(x[0] for x in cur))})
    return [s for s in out if s['text']]


# ---------------------------------------------------------------- parsers

_TS = r'(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})'


def _ts(h, m, s, ms):
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_vtt(text):
    """WebVTT (YouTube auto-subs included) -> segments, rolling duplicates removed.

    YouTube repeats the previous caption line as the first line of the next cue (and emits ~10 ms
    "flash" cues that only repeat it); a line is kept only the first time it appears in consecutive cues."""
    segs, prev_lines = [], []
    # cues are separated by truly empty lines; YouTube's own " " line inside a cue is text, not a separator
    for block in re.split(r'\n\n+', text.replace('\r\n', '\n')):
        lines = [l for l in block.split('\n') if l.strip()]
        idx = next((i for i, l in enumerate(lines) if '-->' in l), None)
        if idx is None:
            continue
        m = re.match(r'\s*' + _TS + r'\s*-->\s*' + _TS, lines[idx])
        if not m:
            continue
        start, end = _ts(*m.group(1, 2, 3, 4)), _ts(*m.group(5, 6, 7, 8))
        cur = []
        for l in lines[idx + 1:]:
            t = _clean(re.sub(r'<[^>]+>', '', l))
            t = _clean(t.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&gt;', '>').replace('&lt;', '<'))
            if t:
                cur.append(t)
        new = [l for l in cur if l not in prev_lines]
        prev_lines = cur or prev_lines
        if new:
            segs.append({'start': start, 'end': end, 'text': ' '.join(new)})
    return _finish(segs)


def parse_json3(data):
    """YouTube json3 (events -> segs) -> segments, rolling duplicates removed."""
    if isinstance(data, (str, bytes)):
        data = json.loads(data)
    if not isinstance(data, dict) or not isinstance(data.get('events') or [], list):
        raise BadInput('not a YouTube json3 file (expected an object with an "events" list)')
    segs, last_text = [], ''
    for ev in data.get('events') or []:
        if not isinstance(ev, dict):
            raise BadInput('json3: every event must be an object')
        parts = ev.get('segs')
        if not parts or 'tStartMs' not in ev:
            continue
        if (not isinstance(parts, list) or not all(isinstance(p, dict) for p in parts)
                or not _is_num(ev['tStartMs']) or not _is_num(ev.get('dDurationMs') or 0)):
            raise BadInput('json3: malformed event (segs must be a list of objects, tStartMs / dDurationMs numbers)')
        text = _clean(''.join(p.get('utf8', '') for p in parts))
        if not text:
            continue
        start = ev['tStartMs'] / 1000.0
        end = start + (ev.get('dDurationMs') or 0) / 1000.0
        if text == last_text:
            continue
        if last_text and text.startswith(last_text):      # rolling: the old caption + new words
            text = _clean(text[len(last_text):])
            if not text:
                last_text = _clean(''.join(p.get('utf8', '') for p in parts))
                continue
        last_text = _clean(''.join(p.get('utf8', '') for p in parts))
        segs.append({'start': start, 'end': end, 'text': text})
    return _finish(segs)


# ---------------------------------------------------------------- local speech-to-text

# Fixed locations, same as word_timing.sh / asr_transcribe.py: no environment variable may redirect them. The home dir is
# read from the passwd database (NOT $HOME / expanduser: an agent can set HOME). Tests patch these module constants
# in-process, or run a temp COPY of the script with the two lines below rewritten; an agent cannot reach either seam.
PW_HOME = pwd.getpwuid(os.getuid()).pw_dir
VENV_DIR = os.path.join(PW_HOME, '.cache', 'yt-news-v4', 'asr-venv')               # = asr_transcribe.VENV_ROOT (a test asserts it)
SITE_DIR = os.path.join(VENV_DIR, 'lib', 'python3.12', 'site-packages')              # = asr_transcribe.SITE_DIR
HF_HUB_DIR = os.path.join(PW_HOME, '.cache', 'huggingface', 'hub')
LAUNCHER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'asr_run.sh')
FFMPEG_CANDIDATES = ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/usr/bin/ffmpeg')   # = asr_run.sh = asr_transcribe.py (a test asserts it)
MODEL_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$')


def resolve_ffmpeg():
    """the first executable of the fixed list ($PATH is never searched) or None"""
    for c in FFMPEG_CANDIDATES:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def minimal_env(ffmpeg):
    """the environment of every subprocess here: nothing of the caller's os.environ"""
    return {'HOME': PW_HOME, 'PATH': os.path.dirname(ffmpeg) + ':/usr/bin:/bin', 'LANG': 'en_US.UTF-8', 'TMPDIR': '/var/empty'}


def check_model_id(model):
    """--model must be an HF repo id (owner/name); anything else (a path, a glob, '*') is refused."""
    if not isinstance(model, str) or not MODEL_ID_RE.match(model):
        raise BadInput(f'--model {model!r} is not an HF repo id (owner/name, letters digits . _ - only). '
                       f'Use a model already cached: ls {HF_HUB_DIR}; do not pass paths or wildcards.')
    return model


def resolve_model_dir(repo):
    """Local snapshot dir of an HF repo id that is already in the fixed hub cache, or None. Never touches the network;
    a filesystem directory is NOT accepted as a model."""
    check_model_id(repo)
    owner, name = repo.split('/', 1)
    for snap in sorted(glob.glob(os.path.join(glob.escape(HF_HUB_DIR), 'models--' + glob.escape(owner) + '--' + glob.escape(name),
                                              'snapshots', '*'))):
        if os.path.exists(os.path.join(snap, 'config.json')) and (
                os.path.exists(os.path.join(snap, 'weights.safetensors')) or os.path.exists(os.path.join(snap, 'weights.npz'))):
            return snap
    return None


def _whisper_worker(wav, model_dir, lang, out_json):
    """Runs under asr_run.sh (python -I -S: no site-packages were processed): the V4 venv's are appended here; offline."""
    for k in OFFLINE_ENV:
        os.environ[k] = OFFLINE_ENV[k]
    sys.path.append(SITE_DIR)
    import mlx_whisper
    res = mlx_whisper.transcribe(wav, path_or_hf_repo=model_dir, language=lang, word_timestamps=True, verbose=False)
    segs = [{'start': s['start'], 'end': s['end'], 'text': s.get('text', ''),
             'words': [{'word': w['word'], 'start': w['start'], 'end': w['end']} for w in (s.get('words') or [])]}
            for s in res.get('segments', [])]
    Path(out_json).write_text(json.dumps(segs, ensure_ascii=False), encoding='utf-8')


def worker_invocation(launcher, ffmpeg, wav, model_dir, lang, out_json):
    """(argv, env) of the whisper worker: asr_run.sh verifies the interpreter / stdlib / venv and runs this file's `_whisper`
    mode under `python -I -S -B -X pycache_prefix=/var/empty` + `env -i`; the environment given here is built from scratch
    (nothing of the caller's os.environ)."""
    argv = ['/bin/bash', str(launcher), 'source_timed.py', '_whisper', wav, model_dir, lang, out_json]
    return argv, minimal_env(ffmpeg)


def from_audio(src, lang='en', model=DEFAULT_MODEL, start=None, duration=None):
    check_model_id(model)
    if not os.path.exists(src):
        raise BadInput(f'no such file: {src}')
    if not os.path.isfile(LAUNCHER):
        raise ToolMissing(f'{LAUNCHER} is missing. Nothing was downloaded or started: do not install anything, stop and report this error.')
    if not os.path.isdir(SITE_DIR):
        raise ToolMissing(f'the ASR venv {VENV_DIR} (mlx-whisper lives there) is not built. Nothing was downloaded or started: a human '
                          f'runs `bash {os.path.dirname(LAUNCHER)}/setup_asr_venv.sh`; do not install anything, stop and report this error.')
    model_dir = resolve_model_dir(model)
    if not model_dir:
        raise ToolMissing(f'speech model {model!r} is not in the local HF cache; not downloading. '
                          f'Cached models: ls ~/.cache/huggingface/hub')
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        raise ToolMissing('ffmpeg not found in ' + ', '.join(FFMPEG_CANDIDATES))
    with tempfile.TemporaryDirectory(prefix='source_timed_') as td:
        wav, raw = os.path.join(td, 'a.wav'), os.path.join(td, 'raw.json')
        cmd = [ffmpeg, '-v', 'error', '-y']
        if start:
            cmd += ['-ss', str(start)]
        cmd += ['-i', src]
        if duration:
            cmd += ['-t', str(duration)]
        cmd += ['-vn', '-ac', '1', '-ar', '16000', wav]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, env=minimal_env(ffmpeg))
        except FileNotFoundError:
            raise ToolMissing('ffmpeg not found')
        except subprocess.CalledProcessError as e:
            raise BadInput(f'ffmpeg could not read audio from {src}: {e.stderr[-300:]}')
        argv, env = worker_invocation(LAUNCHER, ffmpeg, wav, model_dir, lang, raw)
        proc = subprocess.run(argv, env=env, capture_output=True, text=True)
        if proc.returncode == 4:          # the launcher refused (interpreter / stdlib / venv differ from the manifest, or a prerequisite is missing)
            raise ToolMissing('the ASR toolchain check failed; nothing was run: ' + (proc.stderr or proc.stdout)[-1500:])
        if proc.returncode != 0 or not os.path.exists(raw):
            raise RuntimeError('speech-to-text failed:\n' + (proc.stderr or proc.stdout)[-1500:])
        segs = json.loads(Path(raw).read_text(encoding='utf-8'))
    out = split_whisper_segments(segs)
    off = float(start or 0)
    for s in out:
        s['start'], s['end'] = round(s['start'] + off, 3), round(s['end'] + off, 3)
    return out


def audio_job_key(src, model, lang, start, duration):
    """Same idea as word_timing.sh: sha256 of the audio file + the model id (+ language and the window,
    so two --start/--duration chunks of one file never share a key)."""
    h = hashlib.sha256()
    with open(src, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return hashlib.sha256(f'{h.hexdigest()}\n{model}\n{lang}\n{start or 0}\n{duration or 0}'.encode()).hexdigest()


def done_path(out):
    return str(out) + '.done.json'


def already_done(out, key):
    try:
        d = json.loads(Path(done_path(out)).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return d.get('key') == key and Path(out).is_file() and Path(out).stat().st_size > 0


def merge_parts(parts, max_seg=MAX_SEG):
    """Join transcripts of consecutive windows; a segment starting before the previous window's last
    segment ended is trimmed/dropped when it repeats the same text."""
    segs = [s for p in parts for s in p]
    segs.sort(key=lambda s: (s['start'], s['end']))
    out = []
    for s in segs:
        if out and s['start'] < out[-1]['end'] and _clean(s['text']).lower() == _clean(out[-1]['text']).lower():
            continue
        out.append(dict(s))
    return _finish(out, max_seg)


# ---------------------------------------------------------------- CLI

def _write(out_path, segs):
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(segs, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'wrote {len(segs)} segments ({segs[-1]["end"] if segs else 0:.1f} s covered) -> {out_path}')


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == '_whisper':        # internal: runs under asr_run.sh
        _whisper_worker(*argv[1:5])
        return 0
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('from-vtt', 'from-json3'):
        p = sub.add_parser(name)
        p.add_argument('file')
        p.add_argument('--out', required=True)
    p = sub.add_parser('from-audio')
    p.add_argument('file')
    p.add_argument('--out', required=True)
    p.add_argument('--lang', default='en')
    p.add_argument('--model', default=DEFAULT_MODEL)
    p.add_argument('--start', type=float)
    p.add_argument('--duration', type=float)
    p = sub.add_parser('merge')
    p.add_argument('files', nargs='+')
    p.add_argument('--out', required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == 'from-vtt':
            segs = parse_vtt(Path(a.file).read_text(encoding='utf-8-sig'))
        elif a.cmd == 'from-json3':
            segs = parse_json3(Path(a.file).read_text(encoding='utf-8'))
        elif a.cmd == 'merge':
            files = [f for f in a.files if not Path(f).name.endswith('.done.json')]   # from-audio markers match `part_*.json`
            if not files:
                raise BadInput('merge: no part files left (only *.done.json markers were given)')
            segs = merge_parts([load_part(f) for f in files])
        else:
            check_model_id(a.model)
            if not os.path.exists(a.file):
                raise BadInput(f'no such file: {a.file}')
            key = audio_job_key(a.file, a.model, a.lang, a.start, a.duration)
            if already_done(a.out, key):                    # same audio + model + window: calling twice is free
                print(f'already done (key {key[:12]}): {a.out}')
                return 0
            segs = from_audio(a.file, a.lang, a.model, a.start, a.duration)
        if not segs:
            raise BadInput('no caption text found in the input')
    except (BadInput, OSError, ValueError) as e:      # ValueError: bad JSON / undecodable text
        print(f'ERROR: {e}', file=sys.stderr)
        return 2
    except ToolMissing as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 4
    except RuntimeError as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 1
    _write(a.out, segs)
    if a.cmd == 'from-audio':
        Path(done_path(a.out)).write_text(json.dumps({'key': key, 'output': a.out, 'model': a.model, 'lang': a.lang,
                                                      'start': a.start, 'duration': a.duration,
                                                      'segments': len(segs)}, indent=1) + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
