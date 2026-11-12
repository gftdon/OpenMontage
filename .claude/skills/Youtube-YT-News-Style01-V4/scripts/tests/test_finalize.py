import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
NAME = 'FakeSkill'
REAL_NAME = 'Youtube-YT-News-Style01-V4'      # gate_integrity.mjs only accepts a lock written for this skill name
ENGINE_REL = 'remotion-composer/src/YtNewsStyle01V4.tsx'
# what `gate_integrity.mjs <composer> --list-external` prints (the real script, and the fake one of the temp skills)
EXTERNAL_PATHS = ['remotion-composer/src/YtNewsStyle01V4.tsx', 'remotion-composer/src/ytNewsStyle01V4.entry.tsx',
                  'remotion-composer/src/ytNewsStyle01V4Sample.json', 'remotion-composer/src/ytNewsStyle01V4SampleCaptions.json']
ENTRY_SRC = (SCRIPTS.parent / 'assets' / 'ytNewsStyle01V4.entry.reference.tsx').read_text()      # the real entry: the closure/registration are real
FIXTURES = SCRIPTS / 'tests' / 'fixtures' / 'episodes'
COMP = 'YtNewsStyle01V4'
HAVE_FFMPEG = shutil.which('ffmpeg') is not None
HAVE_NODE = shutil.which('node') is not None
RUN_ID = 'run-0001'

# ------------------------------------------------------------------------------------------ stubs
PY_STUB = r'''
import json, os, signal, subprocess, sys, time
from pathlib import Path
a = sys.argv[1:]
name = Path(sys.argv[0]).stem
cwd = Path.cwd()
def arg(flag):
    return a[a.index(flag) + 1] if flag in a else None
beh = {}
if (cwd / '.stub_behavior.json').exists():
    beh = json.loads((cwd / '.stub_behavior.json').read_text())
b = beh.get(name, {})
logs = cwd / '.stub_logs'
logs.mkdir(exist_ok=True)
(logs / (name + '.argv.json')).write_text(json.dumps(a))
(logs / (name + '.flags.json')).write_text(json.dumps({'ignore_environment': sys.flags.ignore_environment,
                                                       'no_user_site': sys.flags.no_user_site}))
(logs / (name + '.pid')).write_text(str(os.getpid()))
(logs / (name + '.env.json')).write_text(json.dumps({'PATH': os.environ.get('PATH'), 'GIT': [k for k in os.environ if k.startswith('GIT_')]}))
(logs / (name + '.start')).write_text(repr(time.time()))
(logs / (name + '.frames_report_existed')).write_text(json.dumps(Path(arg('--frames-report')).is_file() if arg('--frames-report') else None))
if b.get('sleep'):
    time.sleep(b['sleep'])
if b.get('mutate'):
    Path(b['mutate']).write_text(Path(b['mutate']).read_text() + ' ')
if b.get('touch_locked'):
    p = Path(sys.argv[0]).resolve().parent.parent / 'SKILL.md'
    p.write_text(p.read_text() + 'tampered\n')
if b.get('bg_child'):
    child = subprocess.Popen(['sleep', '60'])          # inherits stdout/stderr and the process group
    (logs / (name + '.child.pid')).write_text(str(child.pid))
if b.get('signal'):
    os.kill(os.getpid(), signal.SIGKILL)
report = arg('--report')
if report and b.get('write', True):
    Path(report).parent.mkdir(parents=True, exist_ok=True)
    Path(report).write_text(json.dumps({'pass': b.get('pass', True), 'issues': b.get('issues', [])}))
    if b.get('old'):
        t = time.time() - 3600
        os.utime(report, (t, t))
(logs / (name + '.end')).write_text(repr(time.time()))
sys.exit(b.get('exit', 0))
'''

JS_HEAD = r'''
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
const NAME = '__NAME__';
const a = process.argv.slice(2);
let b = {};
try { b = JSON.parse(fs.readFileSync(path.join(process.cwd(), '.stub_behavior.json'), 'utf8'))[NAME] || {}; } catch (e) {}
fs.mkdirSync('.stub_logs', { recursive: true });
fs.writeFileSync('.stub_logs/' + NAME + '.argv.json', JSON.stringify(a));
'''

JS_PIXELS = JS_HEAD.replace('__NAME__', 'qc_final_pixels') + r'''
const final = a[0];
const out = a[1];
fs.mkdirSync(out, { recursive: true });
const sha = crypto.createHash('sha256').update(fs.readFileSync(final)).digest('hex');
if (b.write !== false) {
  fs.writeFileSync(path.join(out, 'final-pixels.json'), JSON.stringify({
    schema: 'yt-news-final-pixels', version: 1, pass: b.pass !== false, dips: b.dips || [], videoSha256: b.videoSha256 || sha,
    certified: b.certified !== false }));
}
process.exit(b.exit || 0);
'''

JS_SCHEMA = JS_HEAD.replace('__NAME__', 'episode_schema') + r'''
const valid = b.valid !== false;
const errors = valid ? [] : (b.errors || [{ path: '/beats/0', rule: 'enum', message: 'bad mode' }]);
if (b.garbage) { console.log('not json'); } else { console.log(JSON.stringify({ valid, errors, warnings: [] })); }
process.exit(b.exit !== undefined ? b.exit : (valid ? 0 : 1));
'''

# `--list-external` is answered BEFORE any stub logging (it runs at lock-writing time, from any cwd).  FAKE_EXTERNAL_LIST (newline
# separated) replaces the list, FAKE_LIST_EXIT makes the command fail.
JS_INTEGRITY = r'''
if (process.argv.includes('--list-external')) {
  if (process.env.FAKE_LIST_EXIT) { console.error('fake list failure'); process.exit(Number(process.env.FAKE_LIST_EXIT)); }
  const list = process.env.FAKE_EXTERNAL_LIST !== undefined ? process.env.FAKE_EXTERNAL_LIST : __LIST__;
  if (list) console.log(list);
  process.exit(0);
}
'''.replace('__LIST__', json.dumps('\n'.join(EXTERNAL_PATHS))) + JS_HEAD.replace('__NAME__', 'gate_integrity') + r'''
const ok = b.ok !== false;
console.log(JSON.stringify({ ok, issues: ok ? [] : [{ id: 'engine-drift', message: 'engine differs from reference' }], warnings: [] }));
process.exit(b.exit !== undefined ? b.exit : (ok ? 0 : 3));
'''

# qc_manifest.mjs (canonical JSON + manifestHash), srt_to_script / words_by_line / line_starts / caption_join are NOT stubbed:
# the real files of this skill are copied into every fake skill (REAL_ALWAYS), so manifestHash and the derived gate are the real thing.
REAL_ALWAYS = ('qc_manifest.mjs', 'srt_to_script.py', 'words_by_line.py', 'line_starts.py', 'caption_join.mjs')

STUB_FILES = {'lint_beats.py': PY_STUB, 'lint_content.py': PY_STUB, 'lint_captions.py': PY_STUB,
              'frame_checks.py': PY_STUB, 'measure_loudness.py': PY_STUB, 'timing_check.py': PY_STUB, 'qc_final_pixels.mjs': JS_PIXELS,
              'episode_schema.mjs': JS_SCHEMA, 'gate_integrity.mjs': JS_INTEGRITY}
ALL_GATES = ['frames', 'final-av', 'final-pixels', 'loudness', 'music-presence', 'timing', 'schema', 'gate-integrity', 'beats', 'content', 'captions',
             'script', 'derived']
ALL_RECORDS = ALL_GATES + ['layout', 'render', 'mux', 'mux-video', 'video-format', 'final-duration', 'relevance']
STEM = {'beats': 'lint_beats', 'content': 'lint_content', 'captions': 'lint_captions', 'frames': 'frame_checks',
        'loudness': 'measure_loudness', 'timing': 'timing_check', 'final-pixels': 'qc_final_pixels', 'schema': 'episode_schema',
        'gate-integrity': 'gate_integrity'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canon(o):
    return json.dumps(o, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def sh(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def ffmpeg(*args):
    subprocess.run(['ffmpeg', '-y', '-v', 'error', *args], check=True)


# ------------------------------------------------------------------------------------------ fixtures
PROJECT_TEMPLATE = None
_gl_spec = importlib.util.spec_from_file_location('gates_lock_for_tests', SCRIPTS / 'gates_lock.py')
_gl = importlib.util.module_from_spec(_gl_spec)
_gl_spec.loader.exec_module(_gl)


SRT = ('1\n00:00:00,000 --> 00:00:00,800\nhello world today\n\n2\n00:00:00,800 --> 00:00:01,500\nsecond line here\n\n'
       '3\n00:00:01,500 --> 00:00:02,000\nthird line\n')
SOURCE_SCRIPT = 'hello world today\nsecond line here\nthird line\n'
PAGES = [{'start': 0.0, 'end': 0.8, 'words': [{'w': 'hello', 's': 0.0, 'e': 0.3}, {'w': 'world', 's': 0.3, 'e': 0.6},
                                              {'w': 'today', 's': 0.6, 'e': 0.8}]},
         {'start': 0.8, 'end': 1.5, 'words': [{'w': 'second', 's': 0.8, 'e': 1.0}, {'w': 'line', 's': 1.0, 'e': 1.2},
                                              {'w': 'here', 's': 1.2, 'e': 1.5}]},
         {'start': 1.5, 'end': 2.0, 'words': [{'w': 'third', 's': 1.5, 'e': 1.7}, {'w': 'line', 's': 1.7, 'e': 2.0}]}]


def run_tool(*cmd, stdout_to=None):
    r = subprocess.run(list(cmd), capture_output=True, check=True)
    if stdout_to:
        Path(stdout_to).write_bytes(r.stdout)


def derive_artifacts(p):
    """The commands of SKILL step 2 with the REAL scripts: srt -> script.txt, caption_pages.json -> words_by_line.txt,
    line_starts.json, caption-joined.json (byte-identical to what finalize's `derived` gate re-creates)."""
    a = p / 'artifacts'
    run_tool(sys.executable, '-B', str(SCRIPTS / 'srt_to_script.py'), '--srt', str(p / 'assets' / 'avatar.srt'), '--script',
             str(a / 'source_script.txt'), '--strict', '--out', str(a / 'script.txt'))
    pages = a / 'word_timing' / 'caption_pages.json'
    run_tool(sys.executable, '-B', str(SCRIPTS / 'words_by_line.py'), str(pages), str(a / 'script.txt'), stdout_to=a / 'words_by_line.txt')
    run_tool(sys.executable, '-B', str(SCRIPTS / 'line_starts.py'), '--pages', str(pages), '--script', str(a / 'script.txt'), '--out',
             str(a / 'line_starts.json'))
    run_tool('node', str(SCRIPTS / 'caption_join.mjs'), '--tokens', str(pages), '--script', str(a / 'script.txt'), '--options',
             str(a / 'caption-options.json'), '--out', str(a / 'caption-joined.json'))


def write_word_done(p):
    pages = p / 'artifacts' / 'word_timing' / 'caption_pages.json'
    (pages.parent / 'word_timing.done.json').write_text(json.dumps({
        'key': 'k' * 64, 'output': str(pages), 'output_sha256': sha(pages), 'wall_seconds': 1, 'model': 'test-model'}))


def probe_video(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_packets', '-show_entries',
                        'stream=width,height,r_frame_rate,nb_read_packets', '-of', 'json', str(path)], capture_output=True, text=True, check=True)
    s = json.loads(r.stdout)['streams'][0]
    a, b = s['r_frame_rate'].split('/')
    return {'width': int(s['width']), 'height': int(s['height']), 'fps': float(a) / float(b), 'frames': int(s['nb_read_packets'])}


TONE = 'sine=frequency=440:sample_rate=48000:duration=30'       # sound all the way: the voice, then the bed after it
VISUAL_ARGS = ['-f', 'lavfi', '-i', 'testsrc2=s=320x240:r=25:d=2', '-f', 'lavfi', '-i', 'color=c=0x101018:s=320x240:r=25:d=2',
               '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0']


def final_with_audio(proj, *video_args, audio=TONE, out=None):
    """final.mp4 = the packets of visual.mp4 (by default) + an audio track built from the lavfi source `audio` (None = no audio)."""
    visual = str(proj / 'renders' / 'visual.mp4')
    dest = str(out or proj / 'renders' / 'final.mp4')
    if audio is None:
        ffmpeg('-i', visual, *(video_args or ('-c:v', 'copy')), '-an', dest)
    else:
        ffmpeg('-i', visual, '-f', 'lavfi', '-i', audio, '-map', '0:v:0', '-map', '1:a:0', *(video_args or ('-c:v', 'copy')),
               '-c:a', 'aac', '-shortest', dest)


def make_videos(proj, visual_args=None, pix_fmt='yuv420p', audio=TONE):
    """visual.mp4 = 2 s of motion + the V4 end card (2 s solid dark static frame) -> exactly totalDurationSec 4.0 (voEndSec 2.0);
    final.mp4 = the same video packets (mux_av.sh stream-copies the video) + sound after the voice ends (the music-presence gate)."""
    ffmpeg(*(visual_args or VISUAL_ARGS), '-pix_fmt', pix_fmt, str(proj / 'renders' / 'visual.mp4'))
    final_with_audio(proj, audio=audio)


ENV_BACKUP = {}
ENV_DIR = []


def setUpModule():
    global PROJECT_TEMPLATE
    # a stubbed environment for the environment checks every real run starts with: stand-ins for numpy / PIL / pythainlp
    # (appended to sys.path and PYTHONPATH, so a real install still wins), a fake karaoke venv, extract_timing.py and HF cache
    env = Path(tempfile.mkdtemp(prefix='finalize-env-')).resolve()
    ENV_DIR.append(env)
    for mod in ('numpy', 'PIL', 'pythainlp'):
        (env / 'stubmods' / mod).mkdir(parents=True)
        (env / 'stubmods' / mod / '__init__.py').write_text('')
    sys.path.append(str(env / 'stubmods'))
    (env / 'venv' / 'bin').mkdir(parents=True)
    (env / 'venv' / 'bin' / 'python').write_text('#!/bin/sh\n')
    (env / 'venv' / 'bin' / 'python').chmod(0o755)
    (env / 'extract_timing.py').write_text('# stub\n')
    snap = env / 'hub' / 'models--mlx-community--whisper-large-v3-mlx' / 'snapshots' / 'abc'
    snap.mkdir(parents=True)
    (snap / 'config.json').write_text('{}')
    (snap / 'weights.safetensors').write_bytes(b'w')
    for k, v in (('PYTHONPATH', os.pathsep.join(x for x in (os.environ.get('PYTHONPATH'), str(env / 'stubmods')) if x)),
                 ('KARAOKE_VENV', str(env / 'venv')), ('EXTRACT_TIMING', str(env / 'extract_timing.py')), ('HF_HUB_CACHE', str(env / 'hub'))):
        ENV_BACKUP[k] = os.environ.get(k)
        os.environ[k] = v
    ENV_BACKUP.pop('WHISPER_MODEL', None)
    os.environ.pop('WHISPER_MODEL', None)
    if not (HAVE_FFMPEG and HAVE_NODE):
        return
    t = Path(tempfile.mkdtemp(prefix='finalize-proj-'))
    p = t / 'p1'
    for d in ('artifacts/word_timing', 'assets/broll', 'assets/ytsource', 'assets/audio', 'renders', 'qc/finalize'):
        (p / d).mkdir(parents=True)
    (p / 'artifacts' / 'episode.json').write_text(json.dumps({
        'schema': 'yt-news-v4-episode/1', 'assetDir': 'ep1', 'avatarFile': 'avatar.mp4', 'fps': 25, 'voEndSec': 2.0,
        'totalDurationSec': 4.0, 'beats': [{'t': 0}]}))
    (p / 'artifacts' / 'source_script.txt').write_text(SOURCE_SCRIPT)
    (p / 'assets' / 'avatar.srt').write_text(SRT)
    (p / 'artifacts' / 'word_timing' / 'caption_pages.json').write_text(json.dumps(PAGES))
    write_word_done(p)
    (p / 'artifacts' / 'caption-options.json').write_text(json.dumps({'endTime': 2.0}))
    derive_artifacts(p)
    (p / 'artifacts' / '_cuts.json').write_text('[]')
    (p / 'assets' / 'broll' / 'a.mp4').write_bytes(b'x')
    (p / 'assets' / 'ytsource' / 'transcript.txt').write_text('transcript\n')
    make_videos(p)
    PROJECT_TEMPLATE = t


def tearDownModule():
    for k, v in ENV_BACKUP.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    for env in ENV_DIR:
        if str(env / 'stubmods') in sys.path:
            sys.path.remove(str(env / 'stubmods'))
        shutil.rmtree(env, ignore_errors=True)
    if PROJECT_TEMPLATE:
        shutil.rmtree(PROJECT_TEMPLATE, ignore_errors=True)
    # nothing may be written into the locked skill tree (a stray tests/projects/... once ended up there)
    stray = [p for p in (SCRIPTS / 'tests' / 'projects', SCRIPTS / 'projects', SCRIPTS.parent / 'projects') if p.exists()]
    if stray:
        raise AssertionError('a test leaked files into the skill tree: %s' % stray)


LIB_BYTES = b'LIBRARY-TRACK-BYTES'
LIB_FILE = 'calm-tech.mp3'


def lib_track(**kw):
    d = {'sha256': hashlib.sha256(LIB_BYTES).hexdigest(), 'file': LIB_FILE, 'title': 'Calm Tech', 'license': 'CC0-1.0',
         'origin': 'https://example.test/calm', 'approved_by': 'owner', 'approved_on': '2026-11-12', 'duration_sec': 120}
    d.update(kw)
    return d


def online_sidecar(bed, **kw):
    """The sidecar of the retired online source (provider pixabay_music): accepted only while the approved list is EMPTY."""
    d = {'schema': 'yt-news-v4-music-source', 'provider': 'pixabay_music', 'track_id': '42', 'track_title': 'Calm Tech',
         'url': 'https://example.test/42', 'query': 'calm technology', 'sha256': sha(bed), 'fetched_at': '2026-11-12T00:00:00Z'}
    d.update(kw)
    return d


def library_sidecar(bed, **kw):
    """The sidecar fetch_broll.py writes: the approved library is the first and only source."""
    d = {'schema': 'yt-news-v4-music-source', 'provider': 'music_library', 'track_id': None, 'url': None, 'track_title': 'Calm Tech',
         'library_file': LIB_FILE, 'license': 'CC0-1.0', 'origin': 'https://example.test/calm', 'approved_by': 'owner',
         'approved_on': '2026-11-12', 'manifest_sha256': 'e' * 64, 'query': 'calm technology', 'fallback_reason': 'pixabay 403',
         'sha256': sha(bed), 'fetched_at': '2026-11-12T00:00:00Z'}
    d.update(kw)
    return d


def write_receipts(repo, run_id=RUN_ID, name=NAME, bed_bytes=None, sidecar=None):
    """Layout report v3 + run manifest, render receipt and mux receipt in the shapes the real writers produce."""
    proj = repo / 'projects' / 'p1'
    lock = repo / '.claude' / 'skills' / name / 'scripts' / 'gates.lock.json'
    ep, cap = proj / 'artifacts' / 'episode.json', proj / 'artifacts' / 'caption-joined.json'
    vis, fin = proj / 'renders' / 'visual.mp4', proj / 'renders' / 'final.mp4'
    composer = repo / 'remotion-composer'
    avatar = repo / 'remotion-composer' / 'public' / 'ep1' / 'avatar.mp4'
    rd = proj / 'qc' / 'layout' / 'runs' / run_id
    rd.mkdir(parents=True, exist_ok=True)
    bed = proj / 'assets' / 'audio' / 'bed.mp3'
    bed.parent.mkdir(parents=True, exist_ok=True)
    # the default bed is the real path: an approved library track + the library sidecar.  A fixture with an EMPTY approved list
    # (make_repo drops .stub_online_bed) gets the retired online bed instead, the only kind an empty list accepts.
    online = (repo / '.stub_online_bed').exists()
    bed.write_bytes(bed_bytes if bed_bytes is not None else (b'BED-MUSIC' if online else LIB_BYTES))
    side = sidecar(bed) if callable(sidecar) else sidecar or (online_sidecar(bed) if online else library_sidecar(bed))
    Path(str(bed) + '.source.json').write_text(json.dumps(side))
    manifest = {'schema': 'yt-news-v4-run-manifest', 'version': 1, 'runId': run_id, 'compositionId': COMP,
                'sourceHashes': {'episode.json': sha(ep), 'captions.json': sha(cap), 'scripts/gates.lock.json': sha(lock),
                                 'src/YtNewsStyle01V4.tsx': sha(composer / 'src' / 'YtNewsStyle01V4.tsx'),
                                 'src/ytNewsStyle01V4.entry.tsx': sha(composer / 'src' / 'ytNewsStyle01V4.entry.tsx'),
                                 'src/ytNewsStyle01V4Sample.json': sha(composer / 'src' / 'ytNewsStyle01V4Sample.json'),
                                 'src/ytNewsStyle01V4SampleCaptions.json': sha(composer / 'src' / 'ytNewsStyle01V4SampleCaptions.json')},
                'mediaDigest': {'method': 'sha256-per-file-v1', 'assetDir': 'ep1', 'digest': 'b' * 64, 'files': 3, 'bytes': 99},
                'fontsDigest': {'method': 'sha256-per-file-v1', 'digest': 'c' * 64}, 'bundleKey': 'k-1',
                'planSha256': 'd' * 64, 'frames': [0, 25, 50], 'thresholdsSha256': 'e' * 64}
    (rd / 'run-manifest.json').write_text(json.dumps(manifest, indent=2))
    mhash = hashlib.sha256(canon(manifest).encode()).hexdigest()
    report = {'schema': 'yt-news-layout-report', 'version': 3, 'compositionId': COMP, 'runId': run_id,
              'startedAt': '2026-11-12T00:00:00Z', 'status': 'finished', 'manifestHash': mhash,
              # qc_layout.mjs writes it RELATIVE to the --out dir (path.relative(out, manifestPath))
              'manifestPath': 'runs/%s/run-manifest.json' % run_id, 'planSha256': 'd' * 64,
              'fullPlanFrames': [0, 25, 50], 'fullPlanCount': 3, 'requestedFrames': [0, 25, 50], 'requestedCount': 3,
              'measuredCount': 3, 'reusedFrames': 0, 'resumed': False, 'invocations': [], 'wallSecondsTotal': 1.5,
              'warnings': [], 'manifestConsistent': True, 'complete': True, 'diagnosticPass': True, 'pass': True,
              'issues': [], 'actualVideo': True}
    (proj / 'qc' / 'layout' / 'report.json').write_text(json.dumps(report, indent=2))
    facts = probe_video(vis)
    receipt = {'schema': 'yt-news-v4-render-receipt', 'schemaVersion': 1, 'compositionId': COMP, 'renderId': 'render-1',
               'draft': False, 'outputPath': str(vis), 'outputFileName': 'visual.mp4', 'outputSha256': sha(vis),
               'outputBytes': vis.stat().st_size, 'frameCount': facts['frames'], 'durationInFrames': facts['frames'],
               'fps': facts['fps'], 'width': facts['width'],
               'height': facts['height'], 'codec': 'h264', 'pixelFormat': 'yuv420p', 'hasAudio': False,
               'episodeJsonSha256': sha(ep), 'captionsJsonSha256': sha(cap),
               'engineSha256': sha(composer / 'src' / 'YtNewsStyle01V4.tsx'), 'engineReferenceSha256': 'a' * 64,
               'entrySha256': sha(composer / 'src' / 'ytNewsStyle01V4.entry.tsx'), 'entryReferenceSha256': 'a' * 64,
               'entryClosure': {'src/' + n: sha(composer / 'src' / n) for n in ('YtNewsStyle01V4.tsx', 'ytNewsStyle01V4.entry.tsx',
                                                                                  'ytNewsStyle01V4Sample.json', 'ytNewsStyle01V4SampleCaptions.json')},
               'fontsDigest': 'c' * 64, 'mediaDigest': 'b' * 64, 'mediaDigestMethod': 'sha256-per-file-v1',
               'gatesLockSha256': sha(lock), 'gateReportPath': str(proj / 'qc' / 'layout' / 'report.json'),
               'gateReportSha256': sha(proj / 'qc' / 'layout' / 'report.json'), 'gateRunId': run_id,
               'gateManifestHash': mhash, 'gateCheckedAtStart': 't0', 'gateCheckedAtConcat': 't1', 'segments': [],
               'tools': {}, 'startedAt': 't0', 'finishedAt': 't1', 'wallSecondsTotal': 3, 'invocations': []}
    Path(str(vis) + '.receipt.json').write_text(json.dumps(receipt, indent=2))
    mux = {'schema': 'yt-news-v4-mux-receipt', 'version': 1, 'visual': {'path': str(vis), 'sha256': sha(vis)},
           'avatar': {'path': str(avatar), 'sha256': sha(avatar)}, 'bed': {'path': str(bed), 'sha256': sha(bed)},
           'final': {'path': str(fin), 'sha256': sha(fin)}, 'created_at': 't'}
    Path(str(fin) + '.mux.json').write_text(json.dumps(mux, indent=2))
    return mhash


ENGINE_SRC = 'export const YtNewsStyle01V4 = () => null;\nexport const calculateYtNewsStyle01V4Metadata = () => ({});\n'
ROOT_SRC = ('import { YtNewsStyle01V4, calculateYtNewsStyle01V4Metadata } from "./YtNewsStyle01V4";\n'
            'export const Root = () => (\n  <Composition id="YtNewsStyle01V4" component={YtNewsStyle01V4} width={1920} height={1080} '
            'calculateMetadata={calculateYtNewsStyle01V4Metadata} />\n);\n')
REAL_NODE = ('episode_schema.mjs', 'gate_integrity.mjs')


def make_repo(tmp, omit=(), skill_files=None, name=NAME, real=(), external=(), required=None, library_tracks=None, manifest_text=None):
    """real: names of node scripts to copy from the real skill instead of the stub (the real engine team files)."""
    repo = Path(tmp) / 'repo'
    skill = repo / '.claude' / 'skills' / name
    (skill / 'scripts' / 'tests').mkdir(parents=True)
    for f in ('finalize.py', 'gates_lock.py', 'final_av_checks.py', 'music_library.py'):
        shutil.copy(SCRIPTS / f, skill / 'scripts' / f)
    # the skill's own (locked) approved-music manifest + the library files it lists (outside the skill, like music_library/)
    tracks = [lib_track()] if library_tracks is None else library_tracks
    (skill / 'scripts' / 'music_library.json').write_text(manifest_text if manifest_text is not None else json.dumps(
        {'schema': 'yt-news-v4-music-library', 'version': 1, 'tracks': tracks}))
    if library_tracks == [] and manifest_text is None:
        (Path(tmp) / 'repo').mkdir(parents=True, exist_ok=True)
        (Path(tmp) / 'repo' / '.stub_online_bed').write_text('an empty approved list: the default bed is the online one\n')
    (Path(tmp) / 'repo' / 'music_library').mkdir(parents=True, exist_ok=True)
    (Path(tmp) / 'repo' / 'music_library' / LIB_FILE).write_bytes(LIB_BYTES)
    (skill / 'scripts' / 'qc_thresholds.json').write_text('{}')
    (skill / 'scripts' / 'tests' / 'fixture_test.py').write_text('# locked test file\n')
    (skill / 'SKILL.md').write_text('fake\n')
    for fname in REAL_ALWAYS:
        if fname not in omit:
            shutil.copy(SCRIPTS / fname, skill / 'scripts' / fname)
    for fname, body in STUB_FILES.items():
        if fname in real:
            shutil.copy(SCRIPTS / fname, skill / 'scripts' / fname)
        elif fname not in omit:
            (skill / 'scripts' / fname).write_text(body)
    for rel, body in (skill_files or {}).items():
        (skill / rel).write_text(body)
    (repo / 'remotion-composer' / 'src').mkdir(parents=True)
    (repo / 'remotion-composer' / 'src' / 'YtNewsStyle01V4.tsx').write_text(ENGINE_SRC)
    (repo / 'remotion-composer' / 'src' / 'Root.tsx').write_text(ROOT_SRC)          # another pipeline's file: not V4, not locked
    (repo / 'remotion-composer' / 'src' / 'ytNewsStyle01V4.entry.tsx').write_text(ENTRY_SRC)
    (repo / 'remotion-composer' / 'src' / 'ytNewsStyle01V4Sample.json').write_text('{}\n')
    (repo / 'remotion-composer' / 'src' / 'ytNewsStyle01V4SampleCaptions.json').write_text('{}\n')
    (skill / 'assets').mkdir(exist_ok=True)
    (skill / 'assets' / 'ytNewsStyle01V4.entry.reference.tsx').write_text(ENTRY_SRC)
    (skill / 'assets' / 'YtNewsStyle01V4.reference.tsx').write_text(ENGINE_SRC)     # identical: no engine drift
    if 'episode_schema.mjs' in real:        # the real validator reads its JSON schema from <skill>/assets
        shutil.copy(SCRIPTS.parent / 'assets' / 'episode.schema.json', skill / 'assets' / 'episode.schema.json')
    sh(tmp, 'git', 'init', '-q', str(repo))
    sh(repo, 'git', 'config', 'user.email', 't@t')
    sh(repo, 'git', 'config', 'user.name', 't')
    sh(repo, 'git', 'config', 'commit.gpgsign', 'false')
    (repo / '.gitignore').write_text('__pycache__/\nprojects/\nout/\nout-b/\n.stub_*\nremotion-composer/public/\nmusic_library/\n')
    sh(repo, 'git', 'add', '-A')            # a lock is only written over files git tracks
    if required is None and 'gate_integrity.mjs' in omit:
        required = EXTERNAL_PATHS               # no script to ask: the lock is built from the known list
    (skill / 'scripts' / 'gates.lock.json').write_bytes(_gl.lock_bytes(_gl.build_lock(skill, repo, list(external), required=required)))
    shutil.copytree(skill, repo / '.agents' / 'skills' / name)
    sh(repo, 'git', 'add', '-A')
    sh(repo, 'git', 'commit', '-q', '-m', 'init')
    shutil.copytree(PROJECT_TEMPLATE / 'p1', repo / 'projects' / 'p1')
    (repo / 'remotion-composer' / 'public' / 'ep1' / 'broll').mkdir(parents=True)
    (repo / 'remotion-composer' / 'public' / 'ep1' / 'broll' / 'a.mp4').write_bytes(b'x')
    (repo / 'remotion-composer' / 'public' / 'ep1' / 'avatar.mp4').write_bytes(b'AVATAR')
    (repo / 'remotion-composer' / 'public' / 'fonts').mkdir(parents=True)
    for font in ('Kanit-Bold.ttf', 'Kanit-ExtraBold.ttf'):
        (repo / 'remotion-composer' / 'public' / 'fonts' / font).write_bytes(b'FONT')
    for pkg in ('remotion', '@remotion/bundler', '@remotion/renderer'):
        (repo / 'remotion-composer' / 'node_modules' / pkg).mkdir(parents=True)
        (repo / 'remotion-composer' / 'node_modules' / pkg / 'package.json').write_text('{}')
    write_receipts(repo, name=name)
    return repo


_counter = [0]


@unittest.skipUnless(HAVE_FFMPEG and HAVE_NODE, 'ffmpeg and node required')
class FinalizeBase(unittest.TestCase):
    omit = ()
    name = NAME
    real = ()
    external = ()               # extra externals (the required ones are always locked unless required=() is set)
    required = None
    library_tracks = None       # None = one usable approved track; [] = an empty library
    manifest_text = None        # a raw manifest text (e.g. invalid JSON), written before the lock is made

    def setUp(self):
        self.tmp = str(Path(tempfile.mkdtemp(prefix='finalize-')).resolve())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = make_repo(self.tmp, self.omit, name=self.name, real=self.real, external=self.external, required=self.required,
                              library_tracks=self.library_tracks, manifest_text=self.manifest_text)
        self.proj = self.repo / 'projects' / 'p1'
        self.rdir = self.proj / 'qc' / 'finalize'
        self.deliver = self.repo / 'out' / 'episode.mp4'
        self.skill = self.repo / '.claude' / 'skills' / self.name
        self.fin = self.proj / 'renders' / 'final.mp4'

    # --- helpers
    def behavior(self, **kw):
        f = self.repo / '.stub_behavior.json'
        cur = json.loads(f.read_text()) if f.exists() else {}
        cur.update(kw)
        f.write_text(json.dumps(cur))

    def module(self):
        _counter[0] += 1
        spec = importlib.util.spec_from_file_location('finalize_t%d' % _counter[0], self.skill / 'scripts' / 'finalize.py')
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def run_fin(self, *extra, patch=None, deliver=None, check_args=True):
        m = self.module()
        if patch:
            patch(m)
        argv = ['--project', 'projects/p1', '--deliver', str(deliver or self.deliver), *extra]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = m.main(argv)
        self.out = buf.getvalue()
        return code

    def failed(self):
        return json.loads(Path(str(self.deliver) + '.FAILED.json').read_text())

    def receipt(self):
        return json.loads(Path(str(self.deliver) + '.receipt.json').read_text())

    def gate(self, doc, name):
        return next(g for g in doc['gates'] if g['name'] == name)

    def edit(self, path, fn):
        p = Path(path)
        d = json.loads(p.read_text())
        fn(d)
        p.write_text(json.dumps(d))

    def set_videos(self, visual_args, pix_fmt='yuv420p'):
        """Replace visual.mp4 (and final.mp4 = its packets) and re-write the receipts that describe them."""
        make_videos(self.proj, visual_args, pix_fmt)
        write_receipts(self.repo, name=self.name)

    def argv_of(self, stem):
        return json.loads((self.repo / '.stub_logs' / (stem + '.argv.json')).read_text())

    def ran(self, stem):
        return (self.repo / '.stub_logs' / (stem + '.argv.json')).exists()

    def assertNotDelivered(self):
        self.assertFalse(self.deliver.exists())
        self.assertFalse(Path(str(self.deliver) + '.receipt.json').exists())
        self.assertFalse(Path(str(self.deliver) + '.partial').exists())

    def layout_path(self):
        return self.proj / 'qc' / 'layout' / 'report.json'

    def manifest_path(self):
        return self.proj / 'qc' / 'layout' / 'runs' / RUN_ID / 'run-manifest.json'

    def render_path(self):
        return self.proj / 'renders' / 'visual.mp4.receipt.json'

    def mux_path(self):
        return self.proj / 'renders' / 'final.mp4.mux.json'

    def assertExit(self, code, status, name):
        self.assertEqual(code, self.run_fin(), self.out)
        self.assertNotDelivered()
        self.assertEqual(status, self.gate(self.failed(), name)['status'])


class HappyAndGateTests(FinalizeBase):
    def test_happy_path_cli_from_a_subdirectory(self):
        r = subprocess.run([sys.executable, str(self.skill / 'scripts' / 'finalize.py'), '--project', 'projects/p1',
                            '--deliver', str(self.deliver)],
                           capture_output=True, text=True, cwd=self.repo / 'projects')
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertEqual(sha(self.fin), sha(self.deliver))
        rc = self.receipt()
        self.assertEqual('yt-news-v4-delivery-receipt', rc['schema'])
        self.assertEqual(ALL_RECORDS, [g['name'] for g in rc['gates']])
        self.assertTrue(all(g['status'] == 'pass' for g in rc['gates']))
        self.assertEqual(sha(self.deliver), rc['delivered']['sha256'])
        self.assertEqual(self.deliver.stat().st_size, rc['delivered']['bytes'])
        for g in rc['gates']:
            if g['name'] != 'relevance':
                self.assertTrue(g['inputs'], g['name'])
            for h in g['inputs'].values():
                self.assertEqual(64, len(h))
        self.assertIn('projects/p1/renders/final.mp4', self.gate(rc, 'final-av')['inputs'])
        self.assertIn('projects/p1/artifacts/episode.json', self.gate(rc, 'beats')['inputs'])
        self.assertEqual(sha(self.proj / 'artifacts' / 'episode.json'), rc['bound_inputs']['episode']['sha256'])
        self.assertEqual(sha(self.proj / 'artifacts' / 'caption-joined.json'), rc['bound_inputs']['captions']['sha256'])
        self.assertEqual(sha(self.skill / 'scripts' / 'gates.lock.json'), rc['lock_sha256'])
        head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=self.repo, capture_output=True, text=True).stdout.strip()
        tree = subprocess.run(['git', 'rev-parse', 'HEAD:.claude/skills/' + NAME], cwd=self.repo, capture_output=True,
                              text=True).stdout.strip()
        self.assertEqual(head, rc['git_head'])
        self.assertEqual(tree, rc['skill_tree'])
        self.assertEqual(sha(self.skill / 'scripts' / 'finalize.py'), rc['finalize_sha256'])
        self.assertEqual(str(self.deliver), rc['requested_deliver_path'])
        for tool in ('python', 'node', 'ffmpeg', 'git'):
            self.assertTrue(rc['tools'][tool]['path'], tool)
        self.assertEqual(RUN_ID, rc['layout']['runId'])
        self.assertEqual(sha(self.layout_path()), rc['layout']['reportSha256'])
        self.assertEqual(0, rc['layout']['reusedFrames'])
        self.assertEqual(64, len(rc['layout']['manifestHash']))
        self.assertEqual('render-1', rc['render']['renderId'])
        self.assertEqual(sha(self.render_path()), rc['render']['receiptSha256'])
        self.assertEqual(sha(self.mux_path()), rc['mux']['receiptSha256'])
        self.assertEqual('absent', rc['relevance_status'])
        self.assertFalse(Path(str(self.deliver) + '.FAILED.json').exists())
        self.assertFalse(Path(str(self.deliver) + '.receipt.json.tmp').exists())
        self.assertFalse((self.rdir / '.finalize.lock').exists())
        self.assertIn('FINALIZE PASS', r.stdout)

    def test_repo_root_optional_but_must_match(self):
        self.assertEqual(0, self.run_fin('--repo-root', str(self.repo)), self.out)
        self.deliver.unlink()
        self.assertEqual(3, self.run_fin('--repo-root', str(self.tmp)))

    def test_gate_arguments_and_interpreter_flags(self):
        self.assertEqual(0, self.run_fin(), self.out)
        ep, cap = str(self.proj / 'artifacts' / 'episode.json'), str(self.proj / 'artifacts' / 'caption-joined.json')
        self.assertEqual(ep, self.argv_of('lint_beats')[0])
        content = self.argv_of('lint_content')
        self.assertIn('--source-transcript', content)
        self.assertNotIn('--chapters', content)
        self.assertNotIn('--relevance', content)             # absent relevance is not passed
        self.assertEqual(ep, content[content.index('--beats') + 1])
        self.assertIn('--source-script', self.argv_of('lint_captions'))
        self.assertEqual(cap, self.argv_of('lint_captions')[self.argv_of('lint_captions').index('--pages') + 1])
        frames = self.argv_of('frame_checks')
        self.assertEqual('cutaways', frames[0])
        # the files the render really uses: <composer>/public/<assetDir>/broll, NOT the project's assets/broll copies
        self.assertEqual([str(self.repo / 'remotion-composer' / 'public' / 'ep1' / 'broll')],
                         [frames[i + 1] for i, x in enumerate(frames) if x == '--media-root'])
        public = str(self.repo / 'remotion-composer' / 'public')
        self.assertEqual(['validate', ep, '--captions', cap, '--public', public, '--json'], self.argv_of('episode_schema'))
        self.assertEqual([str(self.repo / 'remotion-composer'), '--json', '--skill-dir', str(self.skill), '--require-lock'],
                         self.argv_of('gate_integrity'))
        # voEndSec is passed to the end-card aware gates; --allow-draft is never passed; out-dir is positional
        px = self.argv_of('qc_final_pixels')
        self.assertEqual([str(self.fin), str(self.rdir / 'final-pixels'), '--vo-end', '2.0'], px)
        self.assertFalse(any('allow-draft' in a for g in self.module().GATES for a in g.get('args', [])))
        rep = json.loads((self.rdir / 'final-av.json').read_text())
        self.assertEqual(2.0, rep['params']['ignore_from'])
        flags = json.loads((self.repo / '.stub_logs' / 'lint_beats.flags.json').read_text())
        self.assertEqual({'ignore_environment': 1, 'no_user_site': 1}, flags)

    def test_long_gates_are_registered_first(self):
        names = [g['name'] for g in self.module().GATES]
        self.assertEqual(['frames', 'final-av', 'final-pixels', 'loudness'], names[:4])
        self.assertEqual(ALL_GATES, names)

    def test_no_skip_switch_and_no_comp_flag(self):
        for flag in (['--skip-gates'], ['--comp', 'Other']):
            r = subprocess.run([sys.executable, str(self.skill / 'scripts' / 'finalize.py'), '--project', 'projects/p1',
                                '--deliver', str(self.deliver), *flag], capture_output=True, text=True)
            self.assertEqual(2, r.returncode)
        self.assertFalse(self.deliver.exists())
        src = (SCRIPTS / 'finalize.py').read_text()
        self.assertNotIn('getenv', src)
        # the only environment variables read are the ones word_timing.sh itself honours (its venv / extractor / model cache),
        # for the word-timing PRE-FLIGHT check; none of them can skip, weaken or reconfigure a gate
        names = set(re.findall(r"os\.environ\.get\('([A-Z_]+)'", src))
        self.assertEqual({'HF_HUB_CACHE', 'HF_HOME', 'KARAOKE_VENV', 'WHISPER_MODEL', 'EXTRACT_TIMING'}, names)

    def test_gate_exit_1_fails_but_all_gates_run(self):
        self.behavior(lint_content={'exit': 1, 'pass': False})
        self.assertEqual(1, self.run_fin())
        self.assertNotDelivered()
        f = self.failed()
        self.assertEqual(1, f['exit_code'])
        self.assertEqual('fail', self.gate(f, 'content')['status'])
        self.assertTrue(any('content' in r for r in f['reasons']))
        for stem in STEM.values():
            self.assertTrue(self.ran(stem), stem)
        self.assertEqual(len(ALL_RECORDS), len(f['gates']))

    def test_failed_gate_shows_issues_report_and_rerun_command(self):
        issues = [{'code': 'hold', 'detail': 'too long', 't': 3.2}, {'code': 'origin', 'detail': 'bad'},
                  {'code': 'punch', 'detail': 'x'}, {'code': 'fourth', 'detail': 'not shown'}]
        self.behavior(lint_beats={'exit': 1, 'pass': False, 'issues': issues})
        self.assertEqual(1, self.run_fin())
        g = self.gate(self.failed(), 'beats')
        self.assertEqual(3, len(g['issues']))
        self.assertIn('hold: too long', g['issues'][0])
        self.assertIn('qc/finalize/beats.json', g['report'])
        self.assertIn('lint_beats.py', g['command'])
        self.assertIn('--report', g['command'])
        self.assertIn('hold: too long', self.out)
        self.assertIn('rerun', self.out)
        self.assertNotIn('not shown', self.out)

    def test_report_pass_false_with_exit_0_fails(self):
        self.behavior(lint_beats={'exit': 0, 'pass': False})
        self.assertEqual(1, self.run_fin())
        self.assertEqual('fail', self.gate(self.failed(), 'beats')['status'])

    def test_stale_report_from_previous_run_is_not_accepted(self):
        self.assertEqual(0, self.run_fin())
        self.deliver.unlink()
        self.behavior(lint_captions={'write': False})
        self.assertEqual(2, self.run_fin())
        self.assertEqual('stale', self.gate(self.failed(), 'captions')['status'])

    def test_old_mtime_report_is_stale(self):
        self.behavior(measure_loudness={'old': True})
        self.assertEqual(2, self.run_fin())
        g = self.gate(self.failed(), 'loudness')
        self.assertEqual('stale', g['status'])
        self.assertIn('stale', g['reason'])

    def test_exit_code_mapping(self):
        self.behavior(frame_checks={'exit': 2, 'pass': False})
        self.assertEqual(2, self.run_fin())
        self.behavior(frame_checks={'exit': 4, 'pass': False})
        self.assertEqual(4, self.run_fin())
        # unknown / crash exit codes are infrastructure (4), not quality
        self.behavior(frame_checks={'exit': 7, 'write': False})
        self.assertEqual(4, self.run_fin())
        self.assertEqual('crashed', self.gate(self.failed(), 'frames')['status'])

    def test_gate_killed_by_signal_is_class_4(self):
        self.behavior(lint_captions={'signal': True})
        self.assertEqual(4, self.run_fin())
        g = self.gate(self.failed(), 'captions')
        self.assertEqual('crashed', g['status'])
        self.assertIn('signal', g['reason'])

    def test_gate_timeout(self):
        self.behavior(lint_beats={'sleep': 8})
        def patch(m):
            next(g for g in m.GATES if g['name'] == 'beats')['limit'] = 1
        t0 = time.monotonic()
        self.assertEqual(4, self.run_fin(patch=patch))
        self.assertLess(time.monotonic() - t0, 7)
        g = self.gate(self.failed(), 'beats')
        self.assertEqual('timeout', g['status'])
        self.assertIn('timeout', g['reason'])

    def test_total_budget_exhausted_before_anything_runs_is_exit_4_naming_the_phase(self):
        def patch(m):
            m.TOTAL_BUDGET_SEC = 0
        self.assertEqual(4, self.run_fin(patch=patch))
        self.assertIn('phase "integrity"', ' '.join(self.failed()['reasons']))
        for stem in STEM.values():
            self.assertFalse(self.ran(stem), stem)

    def test_gate_phase_budget_cuts_the_gates_not_the_invocation(self):
        self.behavior(lint_beats={'sleep': 20}, measure_loudness={'sleep': 20})
        def patch(m):
            m.TOTAL_BUDGET_SEC = 6
            m.POST_RESERVE_SEC = 0
        t0 = time.monotonic()
        self.assertEqual(4, self.run_fin(patch=patch))
        self.assertLess(time.monotonic() - t0, 12)         # the invocation never outlives its deadline (plus kill grace)
        gates = {g['name']: g for g in self.failed()['gates']}
        self.assertEqual('timeout', gates['beats']['status'])
        self.assertEqual('timeout', gates['loudness']['status'])

    def test_budget_left_for_delivery_is_checked_and_names_the_phase(self):
        def patch(m):
            m.DELIVER_RESERVE_SEC = 10_000
        self.assertEqual(4, self.run_fin(patch=patch))
        self.assertNotDelivered()
        self.assertIn('phase "deliver"', ' '.join(self.failed()['reasons']))

    def test_post_verification_phase_is_bounded_by_the_same_deadline(self):
        def patch(m):
            m.TOTAL_BUDGET_SEC = 1000
            m.POST_RESERVE_SEC = 1000         # the gates get nothing: every gate times out, verification starts with the budget gone
        self.assertEqual(4, self.run_fin(patch=patch))
        self.assertNotDelivered()

    def test_background_child_holding_stdout_does_not_hang(self):
        self.behavior(lint_beats={'bg_child': True})
        t0 = time.monotonic()
        self.assertEqual(0, self.run_fin(), self.out)
        self.assertLess(time.monotonic() - t0, 20)
        pid = int((self.repo / '.stub_logs' / 'lint_beats.child.pid').read_text())
        time.sleep(0.3)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)          # leftover child of a gate is killed with its process group

    def test_sigterm_kills_gates_and_writes_failed_json(self):
        self.behavior(lint_beats={'sleep': 25})
        p = subprocess.Popen([sys.executable, str(self.skill / 'scripts' / 'finalize.py'), '--project', 'projects/p1',
                              '--deliver', str(self.deliver)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        pidfile = self.repo / '.stub_logs' / 'lint_beats.pid'
        for _ in range(100):
            if pidfile.exists():
                break
            time.sleep(0.1)
        self.assertTrue(pidfile.exists())
        gate_pid = int(pidfile.read_text())
        time.sleep(0.3)
        p.send_signal(signal.SIGTERM)
        out, err = p.communicate(timeout=20)
        self.assertEqual(4, p.returncode, out + err)
        time.sleep(0.3)
        with self.assertRaises(ProcessLookupError):
            os.kill(gate_pid, 0)
        self.assertIn('terminated', ' '.join(self.failed()['reasons']))
        self.assertNotDelivered()
        self.assertFalse((self.rdir / '.finalize.lock').exists())

    def test_schema_gate_invalid_is_quality_and_shows_errors(self):
        self.behavior(episode_schema={'valid': False})
        self.assertEqual(1, self.run_fin())
        g = self.gate(self.failed(), 'schema')
        self.assertEqual('fail', g['status'])
        self.assertTrue(any('enum' in i for i in g['issues']))
        saved = json.loads((self.rdir / 'schema.json').read_text())      # stdout captured into schema.json
        self.assertIs(False, saved['valid'])

    def test_schema_gate_valid_report_is_stored(self):
        self.assertEqual(0, self.run_fin(), self.out)
        self.assertIs(True, json.loads((self.rdir / 'schema.json').read_text())['valid'])

    def test_schema_gate_garbage_stdout_is_stale(self):
        self.behavior(episode_schema={'garbage': True, 'exit': 0})
        self.assertEqual(2, self.run_fin())
        self.assertEqual('stale', self.gate(self.failed(), 'schema')['status'])

    def test_schema_gate_usage_error_is_class_2(self):
        self.behavior(episode_schema={'valid': False, 'exit': 2})
        self.assertEqual(2, self.run_fin())

    def test_gate_integrity_refusal_is_integrity_class_3(self):
        self.behavior(gate_integrity={'ok': False}, lint_beats={'exit': 1, 'pass': False})
        self.assertEqual(3, self.run_fin())          # a bare class 3 is exit 3 (never 0), and wins over a quality failure
        self.assertNotDelivered()
        f = self.failed()
        self.assertEqual(3, f['exit_code'])
        g = self.gate(f, 'gate-integrity')
        self.assertEqual('integrity', g['status'])
        self.assertTrue(any('engine-drift' in i for i in g['issues']))

    def test_final_pixels_validation(self):
        self.behavior(qc_final_pixels={'certified': False})
        self.assertEqual(1, self.run_fin())
        self.behavior(qc_final_pixels={'videoSha256': '0' * 64})
        self.assertEqual(2, self.run_fin())
        self.assertEqual('bad-input', self.gate(self.failed(), 'final-pixels')['status'])
        self.behavior(qc_final_pixels={'exit': 1, 'pass': False})
        self.assertEqual(1, self.run_fin())

    def test_end_card_is_ignored_but_an_early_freeze_is_not(self):
        self.assertEqual(0, self.run_fin(), self.out)          # fixture ends with the dark static end card
        self.deliver.unlink()
        # a frozen segment BEFORE voEndSec (2.0) is still a failure
        self.set_videos(['-f', 'lavfi', '-i', 'testsrc2=s=320x240:r=25:d=0.4', '-vf', 'tpad=stop_mode=clone:stop_duration=3.6'])
        self.assertEqual(1, self.run_fin())
        self.assertEqual('fail', self.gate(self.failed(), 'final-av')['status'])
        self.assertNotDelivered()

    def test_final_duration_must_match_total_duration(self):
        self.set_videos(['-f', 'lavfi', '-i', 'testsrc2=s=320x240:r=25:d=3'])
        self.assertEqual(2, self.run_fin())
        g = self.gate(self.failed(), 'final-duration')
        self.assertEqual('stale', g['status'])
        self.assertIn('totalDurationSec', g['reason'])

    def test_final_duration_within_one_frame_is_accepted(self):
        self.set_videos(['-f', 'lavfi', '-i', 'testsrc2=s=320x240:r=25:d=4.02'])
        self.assertEqual(0, self.run_fin(), self.out)

    def test_input_mutated_during_run_is_rejected(self):
        self.behavior(lint_beats={'mutate': str(self.proj / 'artifacts' / 'script.txt')})
        self.assertEqual(2, self.run_fin())
        self.assertTrue(any('changed while finalize' in r for r in self.failed()['reasons']))

    def test_missing_required_input_is_bad_input(self):
        (self.proj / 'artifacts' / 'words_by_line.txt').unlink()
        self.assertEqual(2, self.run_fin())
        self.assertEqual('bad-input', self.gate(self.failed(), 'content')['status'])
        self.assertFalse(self.ran('lint_content'))

    def test_missing_final_is_bad_input(self):
        self.fin.unlink()
        self.assertEqual(2, self.run_fin())
        self.assertNotDelivered()

    def test_episode_without_vo_end_is_bad_input(self):
        self.edit(self.proj / 'artifacts' / 'episode.json', lambda d: d.pop('voEndSec'))
        write_receipts(self.repo)
        self.assertEqual(2, self.run_fin())
        self.assertEqual('bad-input', self.gate(self.failed(), 'final-av')['status'])


class MissingScriptTests(FinalizeBase):
    omit = ('lint_captions.py',)

    def test_registry_script_missing_is_exit_4(self):
        self.assertEqual(4, self.run_fin())
        self.assertNotDelivered()
        g = self.gate(self.failed(), 'captions')
        self.assertEqual('missing', g['status'])
        self.assertIn('lint_captions.py', g['reason'])
        self.assertTrue(self.ran('lint_beats'))

    def test_precedence_tool_missing_over_bad_input_and_quality(self):
        self.behavior(lint_beats={'exit': 1, 'pass': False})
        self.edit(self.layout_path(), lambda d: d.update(complete=False))
        self.assertEqual(4, self.run_fin())


class MissingNodeGateTests(FinalizeBase):
    omit = ('qc_final_pixels.mjs', 'episode_schema.mjs')

    def test_new_gate_scripts_missing_count_as_missing(self):
        self.assertEqual(4, self.run_fin())
        for name in ('final-pixels', 'schema'):
            self.assertEqual('missing', self.gate(self.failed(), name)['status'], name)


class MissingGateIntegrityScriptTests(FinalizeBase):
    omit = ('gate_integrity.mjs',)

    def test_without_gate_integrity_the_required_files_cannot_be_listed_exit_4_nothing_runs(self):
        self.assertEqual(4, self.run_fin())
        f = self.failed()
        self.assertTrue(any(p.startswith('tool-missing:') and 'gate_integrity.mjs' in p for p in f['integrity_problems']), f['integrity_problems'])
        self.assertEqual([], f['gates'])
        for stem in STEM.values():
            self.assertFalse(self.ran(stem), stem)


class MissingManifestHelperTests(FinalizeBase):
    omit = ('qc_manifest.mjs',)

    def test_qc_manifest_absent_is_class_4(self):
        self.assertEqual(4, self.run_fin())
        g = self.gate(self.failed(), 'layout')
        self.assertEqual('missing', g['status'])
        self.assertIn('qc_manifest.mjs', g['reason'])


class IntegrityTests(FinalizeBase):
    def assertIntegrityFailure(self):
        self.behavior(lint_beats={'exit': 1, 'pass': False})   # would be a quality fail; integrity must win
        self.assertEqual(3, self.run_fin())
        self.assertNotDelivered()
        f = self.failed()
        self.assertEqual(3, f['exit_code'])
        self.assertTrue(f['integrity_problems'])
        self.assertEqual([], f['gates'])
        for stem in STEM.values():
            self.assertFalse(self.ran(stem), 'gate ran: ' + stem)
        self.assertFalse((self.rdir / 'final-av.json').exists())
        self.assertIn('restore the skill files from git HEAD; never edit or regenerate gates.lock.json', self.out)

    def test_locked_gate_modified(self):
        (self.skill / 'scripts' / 'lint_beats.py').write_text('import sys; sys.exit(0)\n')
        self.assertIntegrityFailure()
        self.assertTrue(any('file-changed' in p for p in self.failed()['integrity_problems']))

    def test_locked_test_file_modified(self):
        (self.skill / 'scripts' / 'tests' / 'fixture_test.py').write_text('# weakened\n')
        self.assertIntegrityFailure()
        self.assertTrue(any('fixture_test.py' in p for p in self.failed()['integrity_problems']))

    def test_new_file_in_tests_dir_is_extra(self):
        (self.skill / 'scripts' / 'tests' / 'new_test.py').write_text('x\n')
        self.assertIntegrityFailure()

    def test_mirror_differs_or_missing(self):
        (self.repo / '.agents' / 'skills' / NAME / 'SKILL.md').write_text('changed\n')
        self.assertIntegrityFailure()

    def test_mirror_missing(self):
        shutil.rmtree(self.repo / '.agents')
        self.assertIntegrityFailure()

    def test_lock_regenerated_not_committed(self):
        for d in (self.skill, self.repo / '.agents' / 'skills' / NAME):
            (d / 'scripts' / 'lint_beats.py').write_text('import sys; sys.exit(0)\n')
        lock = _gl.lock_bytes(_gl.build_lock(self.skill, self.repo, [], required=EXTERNAL_PATHS))
        for d in (self.skill, self.repo / '.agents' / 'skills' / NAME):
            (d / 'scripts' / 'gates.lock.json').write_bytes(lock)
        self.assertIntegrityFailure()
        self.assertTrue(any('lock-differs-from-head' in p for p in self.failed()['integrity_problems']))

    def test_lock_missing(self):
        (self.skill / 'scripts' / 'gates.lock.json').unlink()
        self.assertIntegrityFailure()
        self.assertTrue(any('lock-missing' in p for p in self.failed()['integrity_problems']))

    def test_extra_file_in_skill(self):
        (self.skill / 'scripts' / 'helper.py').write_text('x\n')
        self.assertIntegrityFailure()

    def test_not_a_git_repo(self):
        shutil.rmtree(self.repo / '.git')
        self.assertIntegrityFailure()
        self.assertTrue(any('git-unavailable' in p for p in self.failed()['integrity_problems']))

    def test_locked_file_modified_during_the_run_is_exit_3(self):
        self.behavior(lint_beats={'touch_locked': True})
        self.assertEqual(3, self.run_fin(), self.out)
        self.assertNotDelivered()
        self.assertTrue(any('re-check' in r for r in self.failed()['reasons']))

    def test_check_mode_reports_integrity_failure_without_touching_deliver(self):
        (self.skill / 'scripts' / 'lint_beats.py').write_text('x\n')
        self.assertEqual(3, self.run_fin('--check'))
        self.assertFalse(self.deliver.parent.exists())
        self.assertEqual(3, json.loads((self.rdir / 'check.json').read_text())['exit_code'])


class LayoutTests(FinalizeBase):
    def test_layout_manifest_roundtrip_uses_real_node_hash(self):
        # fixture self-check: python canonical JSON == the node function used by finalize
        m = self.module()
        ctx = m.Ctx(type('A', (), {'project': str(self.proj), 'composer': 'remotion-composer', 'manifest': None})(), self.repo,
                    self.repo / 'out' / 'x.mp4', m.resolve_tools())
        mh, err, cls = m.node_manifest_hash(self.manifest_path(), m.gate_env(ctx.tools), ctx, m.Deadline(60))
        self.assertEqual((None, 0), (err, cls))
        self.assertEqual(json.loads(self.layout_path().read_text())['manifestHash'], mh)

    def test_changed_episode_or_captions_or_lock_in_manifest(self):
        self.edit(self.manifest_path(), lambda d: d['sourceHashes'].update({'episode.json': '1' * 64}))
        self.edit(self.layout_path(), lambda d: d.update(manifestHash=self._rehash()))
        self.assertExit(2, 'stale', 'layout')
        self.assertIn('episode.json', self.gate(self.failed(), 'layout')['reason'])
        write_receipts(self.repo)
        self.edit(self.manifest_path(), lambda d: d['sourceHashes'].update({'captions.json': '1' * 64}))
        self.edit(self.layout_path(), lambda d: d.update(manifestHash=self._rehash()))
        self.assertExit(2, 'stale', 'layout')
        write_receipts(self.repo)
        self.edit(self.manifest_path(), lambda d: d['sourceHashes'].update({'scripts/gates.lock.json': '1' * 64}))
        self.edit(self.layout_path(), lambda d: d.update(manifestHash=self._rehash()))
        self.assertExit(2, 'stale', 'layout')

    def _rehash(self):
        return hashlib.sha256(canon(json.loads(self.manifest_path().read_text())).encode()).hexdigest()

    def test_episode_changed_after_layout(self):
        self.edit(self.proj / 'artifacts' / 'episode.json', lambda d: d.update(beats=[{'t': 1}]))
        self.assertExit(2, 'stale', 'layout')

    def test_manifest_hash_mismatch(self):
        self.edit(self.layout_path(), lambda d: d.update(manifestHash='9' * 64))
        self.assertExit(2, 'stale', 'layout')
        self.assertIn('does not match', self.gate(self.failed(), 'layout')['reason'])

    def test_manifest_tampered_without_updating_report_hash(self):
        self.edit(self.manifest_path(), lambda d: d.update(bundleKey='other'))
        self.assertExit(2, 'stale', 'layout')

    def test_manifest_outside_layout_dir(self):
        outside = self.proj / 'elsewhere.json'
        shutil.copy(self.manifest_path(), outside)
        self.edit(self.layout_path(), lambda d: d.update(manifestPath=str(outside)))
        self.assertExit(2, 'stale', 'layout')
        self.assertIn('outside', self.gate(self.failed(), 'layout')['reason'])
        self.edit(self.layout_path(), lambda d: d.update(manifestPath='../../elsewhere.json'))
        self.assertExit(2, 'stale', 'layout')

    def test_relative_manifest_path_is_accepted(self):
        self.edit(self.layout_path(), lambda d: d.update(manifestPath='runs/%s/run-manifest.json' % RUN_ID))
        self.assertEqual(0, self.run_fin(), self.out)

    def test_manifest_wrong_schema_or_run_id(self):
        self.edit(self.manifest_path(), lambda d: d.update(schema='other'))
        self.edit(self.layout_path(), lambda d: d.update(manifestHash=self._rehash()))
        self.assertExit(2, 'stale', 'layout')
        write_receipts(self.repo)
        self.edit(self.manifest_path(), lambda d: d.update(runId='run-x'))
        self.edit(self.layout_path(), lambda d: d.update(manifestHash=self._rehash()))
        self.assertExit(2, 'stale', 'layout')

    def test_layout_report_fields(self):
        cases = [dict(complete=False), dict(status='running'), dict(status='incomplete'), {'pass': False}, dict(requestedCount=1),
                 dict(compositionId='Other'), dict(version=2), dict(schema='other'), dict(runId=''), dict(manifestPath=None)]
        for change in cases:
            write_receipts(self.repo)
            self.edit(self.layout_path(), lambda d, c=change: d.update(c))
            self.assertEqual(2, self.run_fin(), (change, self.out))
            self.assertEqual('stale', self.gate(self.failed(), 'layout')['status'], change)

    def test_layout_missing(self):
        self.layout_path().unlink()
        self.assertExit(2, 'stale', 'layout')

    def test_reused_frames_is_recorded_not_a_failure(self):
        self.edit(self.layout_path(), lambda d: d.update(reusedFrames=2, resumed=True))
        self.assertEqual(0, self.run_fin(), self.out)
        self.assertEqual(2, self.receipt()['layout']['reusedFrames'])
        self.assertEqual(2, self.gate(self.receipt(), 'layout')['reusedFrames'])


class RenderReceiptTests(FinalizeBase):
    def test_receipt_path_is_visual_dot_receipt(self):
        self.assertTrue(self.render_path().is_file())
        self.assertEqual(0, self.run_fin(), self.out)

    def test_each_required_field(self):
        cases = {
            'draft': lambda d: d.update(draft=True),
            'draft-missing': lambda d: d.pop('draft'),
            'null-lock': lambda d: d.update(gatesLockSha256=None),
            'wrong-lock': lambda d: d.update(gatesLockSha256='1' * 64),
            'manifest-hash': lambda d: d.update(gateManifestHash='2' * 64),
            'run-id': lambda d: d.update(gateRunId='other-run'),
            'audio': lambda d: d.update(hasAudio=True),
            'audio-missing': lambda d: d.pop('hasAudio'),
            'output-sha': lambda d: d.update(outputSha256='3' * 64),
            'episode-sha': lambda d: d.update(episodeJsonSha256='4' * 64),
            'episode-missing': lambda d: d.pop('episodeJsonSha256'),
            'captions-sha': lambda d: d.update(captionsJsonSha256='5' * 64),
            'captions-missing': lambda d: d.pop('captionsJsonSha256'),
            'composition': lambda d: d.update(compositionId='Other'),
            'schema': lambda d: d.update(schema='other'),
            'schema-version': lambda d: d.update(schemaVersion=2),
        }
        for label, fn in cases.items():
            write_receipts(self.repo)
            self.edit(self.render_path(), fn)
            self.assertEqual(2, self.run_fin(), (label, self.out))
            self.assertEqual('stale', self.gate(self.failed(), 'render')['status'], label)

    def test_missing_receipt(self):
        self.render_path().unlink()
        self.assertExit(2, 'stale', 'render')

    def test_visual_replaced_after_render(self):
        shutil.copy(self.fin, self.proj / 'renders' / 'visual.mp4')
        self.assertEqual(2, self.run_fin())
        self.assertEqual('stale', self.gate(self.failed(), 'render')['status'])

    def test_verify_render_receipt_is_one_function(self):
        m = self.module()
        self.assertTrue(callable(m.verify_render_receipt))


class MuxReceiptVerifyTests(FinalizeBase):
    def test_mux_mismatches(self):
        for key in ('final', 'visual', 'avatar'):
            write_receipts(self.repo)
            self.edit(self.mux_path(), lambda d, k=key: d[k].update(sha256='6' * 64))
            self.assertEqual(2, self.run_fin(), (key, self.out))
            self.assertEqual('stale', self.gate(self.failed(), 'mux')['status'], key)

    def test_avatar_file_changed_after_mux(self):
        (self.repo / 'remotion-composer' / 'public' / 'ep1' / 'avatar.mp4').write_bytes(b'OTHER')
        self.assertExit(2, 'stale', 'mux')
        self.assertIn('avatar', self.gate(self.failed(), 'mux')['reason'])

    def test_avatar_missing_from_receipt(self):
        self.edit(self.mux_path(), lambda d: d.pop('avatar'))
        self.assertExit(2, 'stale', 'mux')

    def test_missing_receipt_points_at_audio_report(self):
        self.mux_path().unlink()
        self.assertExit(2, 'stale', 'mux')
        self.assertIn('final.audio/final.json', self.gate(self.failed(), 'mux')['reason'])

    def test_final_replaced_after_mux(self):
        final_with_audio(self.proj, audio='sine=frequency=880:sample_rate=48000:duration=30')     # another mix than the one muxed
        self.assertEqual(2, self.run_fin())
        self.assertEqual('stale', self.gate(self.failed(), 'mux')['status'])


class RelevanceTests(FinalizeBase):
    def rel(self, content):
        (self.proj / 'artifacts' / 'relevance.json').write_text(content if isinstance(content, str) else json.dumps(content))

    def test_absent_is_recorded(self):
        self.assertEqual(0, self.run_fin(), self.out)
        self.assertEqual('absent', self.receipt()['relevance_status'])
        self.assertEqual('absent', self.gate(self.receipt(), 'relevance')['verification_status'])

    def test_verified_and_unverified_pass_and_are_passed_to_content_lint(self):
        for status in ('verified', 'unverified'):
            self.rel({'verification_status': status})
            self.assertEqual(0, self.run_fin(), self.out)
            self.assertEqual(status, self.receipt()['relevance_status'])
            self.assertIn('--relevance', self.argv_of('lint_content'))
            self.deliver.unlink()

    def test_failed_is_class_1(self):
        self.rel({'verification_status': 'failed'})
        self.assertExit(1, 'fail', 'relevance')

    def test_anything_else_is_class_2(self):
        for content in ({'verification_status': 'weird'}, {}, {'verification_status': None}, '{oops', '[]'):
            self.rel(content)
            self.assertEqual(2, self.run_fin(), (content, self.out))
            self.assertEqual('stale', self.gate(self.failed(), 'relevance')['status'])


class ResultHandlingTests(FinalizeBase):
    def test_preexisting_output_is_moved_aside_never_deleted(self):
        self.deliver.parent.mkdir(parents=True)
        self.deliver.write_bytes(b'OLD VIDEO')
        Path(str(self.deliver) + '.receipt.json').write_text('{"stale": true}')
        Path(str(self.deliver) + '.partial').write_bytes(b'junk')
        self.behavior(lint_beats={'exit': 1, 'pass': False})
        self.assertEqual(1, self.run_fin())
        self.assertFalse(self.deliver.exists())
        moved = Path(str(self.deliver) + '.uncertified')
        self.assertEqual(b'OLD VIDEO', moved.read_bytes())
        self.assertFalse(Path(str(self.deliver) + '.receipt.json').exists())
        self.assertFalse(Path(str(self.deliver) + '.partial').exists())
        f = self.failed()
        self.assertEqual(str(moved), f['preexisting_output_moved_to'])
        self.assertTrue(f['preexisting_output_not_certified'])
        # a second uncertified file never overwrites the first
        self.deliver.write_bytes(b'SECOND')
        self.assertEqual(1, self.run_fin())
        self.assertEqual(b'OLD VIDEO', moved.read_bytes())
        self.assertEqual(b'SECOND', Path(str(self.deliver) + '.uncertified.1').read_bytes())

    def test_no_preexisting_output(self):
        self.behavior(lint_beats={'exit': 1, 'pass': False})
        self.run_fin()
        self.assertIsNone(self.failed()['preexisting_output_moved_to'])
        self.assertFalse(self.failed()['preexisting_output_not_certified'])

    def test_success_replaces_old_output_and_clears_failed(self):
        self.deliver.parent.mkdir(parents=True)
        self.deliver.write_bytes(b'OLD')
        Path(str(self.deliver) + '.FAILED.json').write_text('{}')
        self.assertEqual(0, self.run_fin())
        self.assertEqual(sha(self.fin), sha(self.deliver))
        self.assertFalse(Path(str(self.deliver) + '.FAILED.json').exists())
        self.assertFalse(Path(str(self.deliver) + '.uncertified').exists())

    def test_check_mode_never_touches_deliver(self):
        self.assertEqual(0, self.run_fin('--check'))
        self.assertFalse(self.deliver.parent.exists())
        self.assertIn('CHECK PASS — nothing delivered', self.out)
        chk = json.loads((self.rdir / 'check.json').read_text())
        self.assertTrue(chk['would_deliver'])
        self.assertEqual(len(ALL_RECORDS), len(chk['gates']))

    def test_check_mode_failure_leaves_existing_files(self):
        self.deliver.parent.mkdir(parents=True)
        self.deliver.write_bytes(b'OLD')
        Path(str(self.deliver) + '.receipt.json').write_text('{"keep": true}')
        self.behavior(lint_beats={'exit': 1, 'pass': False})
        self.assertEqual(1, self.run_fin('--check'))
        self.assertEqual(b'OLD', self.deliver.read_bytes())
        self.assertEqual('{"keep": true}', Path(str(self.deliver) + '.receipt.json').read_text())
        self.assertFalse(Path(str(self.deliver) + '.FAILED.json').exists())
        self.assertFalse(Path(str(self.deliver) + '.uncertified').exists())

    def test_deliver_must_be_mp4_and_not_the_final(self):
        self.assertEqual(2, self.run_fin(deliver=self.repo / 'out' / 'episode.mov'))
        self.assertEqual(2, self.run_fin(deliver=self.fin))

    def test_deliver_symlink_or_directory_refused_before_any_gate(self):
        self.deliver.parent.mkdir(parents=True)
        target = Path(self.tmp) / 'elsewhere.mp4'
        target.write_bytes(b'TARGET')
        os.symlink(target, self.deliver)
        self.assertEqual(2, self.run_fin())
        self.assertFalse(self.ran('lint_beats'))
        self.assertFalse(os.path.lexists(self.deliver))          # the link is removed on failure: it could open an uncertified mp4
        self.assertEqual(b'TARGET', target.read_bytes())        # ... but never its target
        self.assertIn('symlink', ' '.join(self.failed()['reasons']))
        self.deliver.mkdir()
        self.assertEqual(2, self.run_fin())
        self.assertFalse(self.ran('lint_beats'))
        self.assertTrue(self.deliver.is_dir())
        self.assertIn('directory', ' '.join(self.failed()['reasons']))

    def test_deliver_parent_symlink_is_resolved_not_followed_at_the_leaf(self):
        real = Path(self.tmp) / 'realout'
        real.mkdir()
        link = Path(self.tmp) / 'linkout'
        os.symlink(real, link)
        self.assertEqual(0, self.run_fin(deliver=link / 'episode.mp4'), self.out)
        self.assertTrue((real / 'episode.mp4').is_file())
        self.assertEqual(str(real / 'episode.mp4'), self.receipt_at(real)['delivered']['path'])
        self.assertEqual(str(link / 'episode.mp4'), self.receipt_at(real)['requested_deliver_path'])

    def receipt_at(self, d):
        return json.loads((d / 'episode.mp4.receipt.json').read_text())

    def test_receipt_write_failure_after_mp4_rename_leaves_no_mp4(self):
        real_replace = os.replace
        def failing(src, dst, *a, **k):
            if str(dst).endswith('.receipt.json') and not str(dst).endswith('.FAILED.json'):
                raise OSError('disk full (simulated)')
            return real_replace(src, dst, *a, **k)
        with mock.patch('os.replace', side_effect=failing):
            code = self.run_fin()
        self.assertEqual(2, code, self.out)
        self.assertFalse(self.deliver.exists())
        self.assertFalse(Path(str(self.deliver) + '.receipt.json').exists())
        self.assertFalse(Path(str(self.deliver) + '.receipt.json.tmp').exists())
        self.assertFalse(Path(str(self.deliver) + '.partial').exists())
        self.assertIn('delivery failed', ' '.join(self.failed()['reasons']))

    def test_unexpected_exception_becomes_exit_4_with_failed_json(self):
        def patch(m):
            def boom(*a, **k):
                raise RuntimeError('kaboom')
            m.run_verified = boom
        self.deliver.parent.mkdir(parents=True)
        self.deliver.write_bytes(b'OLD')
        self.assertEqual(4, self.run_fin(patch=patch))
        f = self.failed()
        self.assertEqual(4, f['exit_code'])
        self.assertIn('kaboom', ' '.join(f['reasons']))
        self.assertFalse(self.deliver.exists())
        self.assertTrue(Path(str(self.deliver) + '.uncertified').exists())
        self.assertFalse((self.rdir / '.finalize.lock').exists())

    def test_failed_json_created_when_deliver_dir_missing(self):
        self.behavior(lint_beats={'exit': 1, 'pass': False})
        self.assertEqual(1, self.run_fin())
        self.assertTrue(Path(str(self.deliver) + '.FAILED.json').is_file())

    def test_summary_lists_every_gate(self):
        self.assertEqual(0, self.run_fin())
        for name in ALL_RECORDS:
            self.assertIn(name, self.out)
        self.assertIn('FINALIZE PASS', self.out)

    def test_precedence_quality_vs_stale(self):
        self.behavior(lint_beats={'exit': 1, 'pass': False})
        self.assertEqual(1, self.run_fin())
        self.edit(self.layout_path(), lambda d: d.update(complete=False))
        self.assertEqual(2, self.run_fin())


class RunLockTests(FinalizeBase):
    def test_concurrent_run_is_refused(self):
        self.rdir.mkdir(parents=True, exist_ok=True)
        lock = self.rdir / '.finalize.lock'
        lock.write_text('{"pid": 1}')
        self.deliver.parent.mkdir(parents=True)
        self.deliver.write_bytes(b'OTHER RUN OUTPUT')
        self.assertEqual(2, self.run_fin())
        self.assertIn('another finalize run', self.out)
        self.assertTrue(lock.exists())                      # not ours: left alone
        self.assertEqual(b'OTHER RUN OUTPUT', self.deliver.read_bytes())   # and so is the other run's output
        self.assertFalse(self.ran('lint_beats'))

    def test_stale_lock_is_replaced(self):
        self.rdir.mkdir(parents=True, exist_ok=True)
        lock = self.rdir / '.finalize.lock'
        lock.write_text('{"pid": 1}')
        old = time.time() - 16 * 60
        os.utime(lock, (old, old))
        self.assertEqual(0, self.run_fin(), self.out)
        self.assertFalse(lock.exists())

    def test_lock_released_after_failure(self):
        self.behavior(lint_beats={'exit': 1, 'pass': False})
        self.assertEqual(1, self.run_fin())
        self.assertFalse((self.rdir / '.finalize.lock').exists())


class ManifestOverrideTests(FinalizeBase):
    def manifest(self, data):
        (self.proj / 'artifacts' / 'finalize.json').write_text(json.dumps(data))

    def test_allowed_override_works_and_is_recorded(self):
        self.manifest({'script': 'artifacts/other.txt'})
        self.assertEqual(2, self.run_fin())      # required input missing
        shutil.copy(self.proj / 'artifacts' / 'script.txt', self.proj / 'artifacts' / 'other.txt')
        self.assertEqual(0, self.run_fin(), self.out)
        self.assertEqual(sha(self.proj / 'artifacts' / 'finalize.json'), self.receipt()['manifest_sha256'])
        c = self.argv_of('lint_content')
        self.assertTrue(c[c.index('--script') + 1].endswith('other.txt'))

    def test_absolute_and_dotdot_paths_are_rejected(self):
        for value in ('/etc/passwd', '../../../etc/passwd', 'artifacts/../../x'):
            self.manifest({'script': value})
            self.assertEqual(2, self.run_fin(), value)
            self.assertIn('not allowed', ' '.join(self.failed()['reasons']))
            self.assertFalse(self.ran('lint_content'))
        self.manifest({'media_roots': ['assets/broll', '/tmp']})
        self.assertEqual(2, self.run_fin())

    def test_symlink_escaping_the_project_is_rejected(self):
        outside = Path(self.tmp) / 'outside.txt'
        outside.write_text('x')
        os.symlink(outside, self.proj / 'artifacts' / 'linked.txt')
        self.manifest({'script': 'artifacts/linked.txt'})
        self.assertEqual(2, self.run_fin())
        self.assertIn('outside the project', ' '.join(self.failed()['reasons']))

    def test_forbidden_overrides(self):
        for key in ('episode', 'captions', 'visual', 'final', 'layout_report', 'reports', 'relevance', 'word_pages', 'caption_options'):
            self.manifest({key: 'artifacts/x'})
            self.assertEqual(2, self.run_fin(), key)
            self.assertIn('may not override', ' '.join(self.failed()['reasons']))
        self.manifest({'media_roots': ['assets/broll']})        # no longer a key at all: the frames gate checks the render's media
        self.assertEqual(2, self.run_fin())
        self.assertIn('unknown keys', self.failed()['reasons'][0])

    def test_unknown_key_and_missing_optional(self):
        self.manifest({'skip_gates': True})
        self.assertEqual(2, self.run_fin())
        self.assertIn('unknown keys', self.failed()['reasons'][0])
        self.manifest({'chapters': 'assets/ytsource/nope.txt'})
        self.assertEqual(2, self.run_fin())
        self.assertNotDelivered()


class ContentEvidenceTests(FinalizeBase):
    """The content gate must receive the visual evidence, the timed source transcript and the frames report of THIS run."""

    def write_optional(self):
        (self.proj / 'artifacts' / 'visual_evidence.json').write_text('[]')
        (self.proj / 'assets' / 'ytsource' / 'transcript_timed.json').write_text('[]')

    def flag(self, argv, name):
        return argv[argv.index(name) + 1]

    def test_content_gets_evidence_frames_report_and_source_timed(self):
        self.write_optional()
        self.assertEqual(0, self.run_fin(), self.out)
        c = self.argv_of('lint_content')
        self.assertEqual(str(self.proj / 'artifacts' / 'visual_evidence.json'), self.flag(c, '--evidence'))
        self.assertEqual(str(self.proj / 'assets' / 'ytsource' / 'transcript_timed.json'), self.flag(c, '--source-timed'))
        self.assertEqual(str(self.rdir / 'frames.json'), self.flag(c, '--frames-report'))
        # the report it was handed was written by the frames gate of this very run and existed when content started
        self.assertEqual('true', (self.repo / '.stub_logs' / 'lint_content.frames_report_existed').read_text())
        g = self.gate(self.receipt(), 'content')
        for rel in ('projects/p1/artifacts/visual_evidence.json', 'projects/p1/assets/ytsource/transcript_timed.json',
                    'projects/p1/qc/finalize/frames.json'):
            self.assertIn(rel, g['inputs'], rel)
        self.assertEqual(sha(self.rdir / 'frames.json'), g['inputs']['projects/p1/qc/finalize/frames.json'])

    def test_content_gets_the_same_captions_as_the_schema_gate(self):
        self.assertEqual(0, self.run_fin(), self.out)
        cap = str(self.proj / 'artifacts' / 'caption-joined.json')
        c = self.argv_of('lint_content')
        self.assertEqual(cap, self.flag(c, '--captions'))
        self.assertEqual(cap, self.argv_of('episode_schema')[self.argv_of('episode_schema').index('--captions') + 1])
        self.assertIn('projects/p1/artifacts/caption-joined.json', self.gate(self.receipt(), 'content')['inputs'])

    def test_missing_captions_is_bad_input_for_content(self):
        (self.proj / 'artifacts' / 'caption-joined.json').unlink()
        self.assertEqual(2, self.run_fin())
        self.assertEqual('bad-input', self.gate(self.failed(), 'content')['status'])
        self.assertFalse(self.ran('lint_content'))

    def test_absent_evidence_and_timed_transcript_are_left_to_lint_content(self):
        # an episode without source beats needs neither; one with source beats gets evidence-missing FROM lint_content
        self.assertEqual(0, self.run_fin(), self.out)
        c = self.argv_of('lint_content')
        self.assertNotIn('--evidence', c)
        self.assertNotIn('--source-timed', c)
        self.assertIn('--frames-report', c)
        self.deliver.unlink()
        self.behavior(lint_content={'exit': 1, 'pass': False, 'issues': [{'code': 'evidence-missing', 'detail': 'no entry'}]})
        self.assertEqual(1, self.run_fin())
        self.assertIn('evidence-missing', ' '.join(self.gate(self.failed(), 'content')['issues']))

    def test_content_starts_only_after_frames_finished(self):
        self.behavior(frame_checks={'sleep': 1.5})
        self.assertEqual(0, self.run_fin(), self.out)
        logs = self.repo / '.stub_logs'
        frames_end = float((logs / 'frame_checks.end').read_text())
        content_start = float((logs / 'lint_content.start').read_text())
        self.assertGreaterEqual(content_start, frames_end)
        # gates that do not depend on frames are not held back
        self.assertLess(float((logs / 'lint_beats.start').read_text()), frames_end)

    def test_failed_frames_gate_blocks_content_fail_closed(self):
        self.behavior(frame_checks={'exit': 1, 'pass': False})
        self.assertEqual(1, self.run_fin())
        self.assertNotDelivered()
        self.assertFalse(self.ran('lint_content'))
        f = self.failed()
        self.assertEqual('fail', self.gate(f, 'frames')['status'])
        g = self.gate(f, 'content')
        self.assertEqual('blocked', g['status'])
        self.assertIn('frames', g['reason'])
        self.assertTrue(any(r.startswith('content:') for r in f['reasons']))

    def test_frames_without_report_blocks_content_with_the_frames_class(self):
        self.behavior(frame_checks={'write': False})          # exit 0 but no report: stale -> class 2
        self.assertEqual(2, self.run_fin())
        self.assertFalse(self.ran('lint_content'))
        self.assertEqual('stale', self.gate(self.failed(), 'frames')['status'])
        self.assertEqual('blocked', self.gate(self.failed(), 'content')['status'])
        self.behavior(frame_checks={'exit': 4, 'pass': False})  # tool missing class 4 wins and is inherited
        self.assertEqual(4, self.run_fin())
        self.assertEqual('blocked', self.gate(self.failed(), 'content')['status'])

    def test_frames_report_from_a_previous_run_is_never_handed_over(self):
        self.assertEqual(0, self.run_fin(), self.out)
        self.deliver.unlink()
        self.behavior(frame_checks={'write': False})
        self.assertEqual(2, self.run_fin())
        self.assertFalse((self.rdir / 'frames.json').exists())   # removed before the gate started
        self.assertEqual('blocked', self.gate(self.failed(), 'content')['status'])

    def test_manifest_may_override_the_agent_inputs_but_not_the_frames_report(self):
        (self.proj / 'artifacts' / 'other_evidence.json').write_text('[]')
        (self.proj / 'artifacts' / 'finalize.json').write_text(json.dumps({'evidence': 'artifacts/other_evidence.json'}))
        self.assertEqual(0, self.run_fin(), self.out)
        c = self.argv_of('lint_content')
        self.assertTrue(self.flag(c, '--evidence').endswith('other_evidence.json'))
        for key in ('frames_report', 'frames'):
            (self.proj / 'artifacts' / 'finalize.json').write_text(json.dumps({key: 'artifacts/other_evidence.json'}))
            self.assertEqual(2, self.run_fin(), key)
            self.assertIn('unknown keys', self.failed()['reasons'][0])
        # an override that points at a missing optional file is an error, not a silent skip
        (self.proj / 'artifacts' / 'finalize.json').write_text(json.dumps({'source_timed': 'assets/ytsource/nope.json'}))
        self.assertEqual(2, self.run_fin())
        self.assertNotDelivered()


class TimingGateTests(FinalizeBase):
    def test_timing_gate_is_required_and_gets_the_avatar_audio_and_words(self):
        m = self.module()
        g = next(x for x in m.GATES if x['name'] == 'timing')
        self.assertTrue(g['required'])
        self.assertEqual('timing_check.py', g['script'])
        self.assertEqual(0, self.run_fin(), self.out)
        t = self.argv_of('timing_check')
        avatar = self.repo / 'remotion-composer' / 'public' / 'ep1' / 'avatar.mp4'
        self.assertEqual(str(avatar), t[t.index('--audio') + 1])
        self.assertEqual(str(self.proj / 'artifacts' / 'words_by_line.txt'), t[t.index('--words') + 1])
        self.assertEqual(str(self.rdir / 'timing.json'), t[t.index('--report') + 1])
        g = self.gate(self.receipt(), 'timing')
        self.assertEqual('pass', g['status'])
        self.assertEqual(sha(avatar), g['inputs']['remotion-composer/public/ep1/avatar.mp4'])
        self.assertIn('projects/p1/artifacts/words_by_line.txt', g['inputs'])

    def test_timing_gets_line_starts_and_the_srt(self):
        self.assertEqual(0, self.run_fin(), self.out)
        t = self.argv_of('timing_check')
        self.assertEqual(str(self.proj / 'artifacts' / 'line_starts.json'), t[t.index('--line-starts') + 1])
        self.assertEqual(str(self.proj / 'assets' / 'avatar.srt'), t[t.index('--srt') + 1])
        g = self.gate(self.receipt(), 'timing')
        self.assertIn('projects/p1/assets/avatar.srt', g['inputs'])
        self.assertIn('projects/p1/artifacts/line_starts.json', g['inputs'])

    def test_missing_srt_is_bad_input_never_a_skipped_check(self):
        (self.proj / 'assets' / 'avatar.srt').unlink()
        self.assertEqual(2, self.run_fin())
        for name in ('timing', 'script'):
            self.assertEqual('bad-input', self.gate(self.failed(), name)['status'], name)
        self.assertFalse(self.ran('timing_check'))

    def test_srt_path_is_overridable_and_a_missing_override_is_an_error(self):
        shutil.copy(self.proj / 'assets' / 'avatar.srt', self.proj / 'assets' / 'vendor.srt')
        (self.proj / 'artifacts' / 'finalize.json').write_text(json.dumps({'srt': 'assets/vendor.srt'}))
        self.assertEqual(0, self.run_fin(), self.out)
        t = self.argv_of('timing_check')
        self.assertTrue(t[t.index('--srt') + 1].endswith('vendor.srt'))
        (self.proj / 'artifacts' / 'finalize.json').write_text(json.dumps({'srt': 'assets/nope.srt'}))
        self.assertEqual(2, self.run_fin())
        self.assertNotDelivered()

    def test_missing_line_starts_is_bad_input_for_timing(self):
        (self.proj / 'artifacts' / 'line_starts.json').unlink()
        self.assertEqual(2, self.run_fin())
        self.assertEqual('bad-input', self.gate(self.failed(), 'timing')['status'])
        self.assertFalse(self.ran('timing_check'))

    def test_timing_rejection_is_a_quality_failure(self):
        self.behavior(timing_check={'exit': 1, 'pass': False, 'issues': [{'code': 'tokens-in-silence', 'detail': '3 tokens'}]})
        self.assertEqual(1, self.run_fin())
        g = self.gate(self.failed(), 'timing')
        self.assertEqual('fail', g['status'])
        self.assertIn('tokens-in-silence', g['issues'][0])
        self.assertNotDelivered()

    def test_report_pass_false_with_exit_0_fails(self):
        self.behavior(timing_check={'exit': 0, 'pass': False})
        self.assertEqual(1, self.run_fin())

    def test_missing_audio_file_is_bad_input_not_a_skip(self):
        (self.repo / 'remotion-composer' / 'public' / 'ep1' / 'avatar.mp4').unlink()
        self.assertEqual(2, self.run_fin())
        g = self.gate(self.failed(), 'timing')
        self.assertEqual('bad-input', g['status'])
        self.assertIn('avatar', g['reason'])
        self.assertFalse(self.ran('timing_check'))

    def test_episode_without_avatar_file_is_bad_input(self):
        self.edit(self.proj / 'artifacts' / 'episode.json', lambda d: d.pop('avatarFile'))
        write_receipts(self.repo)
        self.assertEqual(2, self.run_fin())
        self.assertEqual('bad-input', self.gate(self.failed(), 'timing')['status'])
        self.assertFalse(self.ran('timing_check'))

    def test_missing_words_file_is_bad_input(self):
        (self.proj / 'artifacts' / 'words_by_line.txt').unlink()
        self.assertEqual(2, self.run_fin())
        self.assertEqual('bad-input', self.gate(self.failed(), 'timing')['status'])

    def test_stale_timing_report_is_not_accepted(self):
        self.behavior(timing_check={'old': True})
        self.assertEqual(2, self.run_fin())
        self.assertEqual('stale', self.gate(self.failed(), 'timing')['status'])

    def test_timing_exit_codes(self):
        self.behavior(timing_check={'exit': 2, 'pass': False})
        self.assertEqual(2, self.run_fin())
        self.behavior(timing_check={'exit': 4, 'pass': False})      # ffmpeg missing
        self.assertEqual(4, self.run_fin())


class TimingScriptMissingTests(FinalizeBase):
    omit = ('timing_check.py',)

    def test_missing_timing_script_is_exit_4(self):
        self.assertEqual(4, self.run_fin())
        self.assertEqual('missing', self.gate(self.failed(), 'timing')['status'])


class RequiredExternalTests(FinalizeBase):
    required = ()           # the lock does not cover the engine file

    def test_the_list_is_never_typed_in_python(self):
        text = (SCRIPTS / 'gates_lock.py').read_text()
        self.assertNotIn('YtNewsStyle01V4', text)
        self.assertNotIn('ytNewsStyle01V4', text)
        self.assertFalse(hasattr(_gl, 'REQUIRED_EXTERNAL'))
        self.assertIn('--list-external', text)

    def test_lock_without_the_required_externals_is_exit_3_naming_them(self):
        self.behavior(lint_beats={'exit': 1, 'pass': False})      # integrity must win over a quality failure
        self.assertEqual(3, self.run_fin())
        self.assertNotDelivered()
        f = self.failed()
        self.assertEqual(3, f['exit_code'])
        for rel in EXTERNAL_PATHS:
            self.assertTrue(any(p.startswith('external-not-locked') and rel in p for p in f['integrity_problems']), (rel, f['integrity_problems']))
        self.assertEqual([], f['gates'])
        for stem in STEM.values():
            self.assertFalse(self.ran(stem), stem)

    def test_check_mode_also_refuses(self):
        self.assertEqual(3, self.run_fin('--check'))


class OtherExternalOnlyTests(FinalizeBase):
    required = ()
    external = ('remotion-composer/src/Root.tsx',)          # an external, but not the required ones

    def test_other_external_does_not_satisfy_the_requirement(self):
        self.assertEqual(3, self.run_fin())
        self.assertTrue(any('external-not-locked' in p for p in self.failed()['integrity_problems']))


class OnePathMissingFromTheLockTests(FinalizeBase):
    required = EXTERNAL_PATHS[:3]          # every path but the last sample JSON

    def test_a_lock_that_lacks_any_one_printed_path_is_exit_3(self):
        self.assertEqual(3, self.run_fin())
        probs = self.failed()['integrity_problems']
        self.assertEqual(['external-not-locked: ' + EXTERNAL_PATHS[3]], [p.split(' is not listed')[0] for p in probs])


class ExternalListCommandTests(FinalizeBase):
    """The required files come from `gate_integrity.mjs <composer> --list-external`; every way that command can fail is closed."""

    def run_with_env(self, **env):
        with mock.patch.dict(os.environ, env):
            return self.run_fin()

    def test_happy_lock_lists_every_printed_path(self):
        self.assertEqual(0, self.run_fin(), self.out)
        self.assertEqual(EXTERNAL_PATHS, list(json.loads((self.skill / 'scripts' / 'gates.lock.json').read_text())['external']))

    def test_a_path_the_command_prints_that_the_lock_lacks_is_exit_3(self):
        self.assertEqual(3, self.run_with_env(FAKE_EXTERNAL_LIST='\n'.join(EXTERNAL_PATHS + ['remotion-composer/src/newV4File.tsx'])))
        self.assertTrue(any('external-not-locked' in p and 'newV4File.tsx' in p for p in self.failed()['integrity_problems']))
        self.assertNotDelivered()

    def test_empty_list_is_exit_3(self):
        self.assertEqual(3, self.run_with_env(FAKE_EXTERNAL_LIST=''))
        self.assertTrue(any(p.startswith('required-external-unavailable:') and 'printed nothing' in p for p in self.failed()['integrity_problems']))

    def test_failing_command_is_exit_3(self):
        self.assertEqual(3, self.run_with_env(FAKE_LIST_EXIT='2'))
        self.assertTrue(any(p.startswith('required-external-unavailable:') and 'exited 2' in p for p in self.failed()['integrity_problems']))

    def test_unsafe_printed_paths_are_refused(self):
        for bad in ('/etc/passwd', '../outside.tsx'):
            self.assertEqual(3, self.run_with_env(FAKE_EXTERNAL_LIST=bad), bad)
            self.assertTrue(any('required-external-unavailable' in p for p in self.failed()['integrity_problems']), bad)

    def test_node_missing_is_class_4(self):
        real = None

        def patch(m):
            nonlocal real
            real = m.resolve_tools
            m.resolve_tools = lambda: dict(real(), node='/nonexistent/bin/node')
        self.assertEqual(4, self.run_fin(patch=patch))
        self.assertTrue(any(p.startswith('tool-missing:') for p in self.failed()['integrity_problems']))
        self.assertEqual([], self.failed()['gates'])

    def test_a_missing_list_is_never_mixed_with_a_real_integrity_problem_class_3_wins(self):
        (self.skill / 'scripts' / 'lint_beats.py').write_text('x\n')
        self.assertEqual(3, self.run_with_env(FAKE_EXTERNAL_LIST=''))


class EngineLockedHappyTests(FinalizeBase):
    def test_a_change_of_any_locked_external_is_exit_3(self):
        self.assertEqual(0, self.run_fin(), self.out)
        for rel in EXTERNAL_PATHS:
            self.deliver.unlink(missing_ok=True)
            f = self.repo / rel
            before = f.read_text()
            f.write_text(before + ('' if rel.endswith('.json') else '// tampered\n') + (' ' if rel.endswith('.json') else ''))
            self.assertEqual(3, self.run_fin(), rel)
            self.assertTrue(any('external-changed' in p and rel in p for p in self.failed()['integrity_problems']), rel)
            f.write_text(before)


@unittest.skipUnless(HAVE_FFMPEG and HAVE_NODE, 'node (and ffmpeg for the shared fixtures) required: the contract test runs the real .mjs')
class RealValidatorContractTests(FinalizeBase):
    """finalize's gate runner against the engine team's REAL episode_schema.mjs and gate_integrity.mjs (not stubs),
    fed with their own fixtures sample-v1.json + sample-captions.json.  Run through `--check`: the other gates of
    this tiny repo are irrelevant, only the two records below are asserted."""
    name = REAL_NAME
    real = REAL_NODE

    def setUp(self):
        super().setUp()
        shutil.copy(FIXTURES / 'valid' / 'sample-v1.json', self.proj / 'artifacts' / 'episode.json')
        shutil.copy(FIXTURES / 'captions' / 'sample-captions.json', self.proj / 'artifacts' / 'caption-joined.json')
        ep = json.loads((self.proj / 'artifacts' / 'episode.json').read_text())
        media = self.repo / 'remotion-composer' / 'public' / ep['assetDir']
        (media / 'broll').mkdir(parents=True)
        (media / ep['avatarFile']).write_bytes(b'AVATAR')
        for src in ep['brollDur']:
            (media / 'broll' / (src + '.mp4')).write_bytes(b'x')
        self.media = media

    def check_gates(self):
        self.run_fin('--check')
        doc = json.loads((self.rdir / 'check.json').read_text())
        return {g['name']: g for g in doc['gates']}

    def test_real_schema_and_integrity_pass_through_the_gate_runner(self):
        gates = self.check_gates()
        self.assertEqual('pass', gates['schema']['status'], gates['schema'])
        self.assertEqual('pass', gates['gate-integrity']['status'], gates['gate-integrity'])
        self.assertIs(True, json.loads((self.rdir / 'schema.json').read_text())['valid'])
        integrity = json.loads((self.rdir / 'gate-integrity.json').read_text())
        self.assertIs(True, integrity['ok'])
        self.assertEqual('ok', integrity['lock']['status'])
        self.assertEqual(4, integrity['lock']['external'])        # the engine, the entry and the two sample JSONs are covered by the lock
        cmd = gates['schema']['command']
        self.assertIn('--public', cmd)
        self.assertIn(str(self.repo / 'remotion-composer' / 'public'), cmd)
        self.assertIn('--require-lock', gates['gate-integrity']['command'])

    def test_real_schema_checks_that_the_media_files_exist(self):
        (self.media / 'broll' / 'photographer_for_images.mp4').unlink()      # S07-file only runs with --public
        g = self.check_gates()['schema']
        self.assertEqual('fail', g['status'])
        self.assertTrue(any('S07-file' in i for i in g['issues']), g['issues'])

    def test_real_schema_rejects_a_broken_episode(self):
        self.edit(self.proj / 'artifacts' / 'episode.json', lambda d: d['beats'][0].update(t=1))
        self.assertEqual('fail', self.check_gates()['schema']['status'])

    def test_the_lock_was_written_from_the_real_list_external_command(self):
        r = subprocess.run(['node', str(SCRIPTS / 'gate_integrity.mjs'), str(self.repo / 'remotion-composer'), '--list-external'],
                           capture_output=True, text=True, check=True)
        printed = r.stdout.split()
        self.assertEqual(EXTERNAL_PATHS, printed)                  # the fixture list mirrors the engine team's command today
        lock = json.loads((self.skill / 'scripts' / 'gates.lock.json').read_text())
        self.assertEqual(printed, list(lock['external']))

    def test_a_tampered_entry_never_reaches_the_gate_it_stops_at_the_lock(self):
        # the entry is a locked external: entry-drift / entry-registration / entry-closure are the second line behind it
        (self.repo / 'remotion-composer' / 'src' / 'ytNewsStyle01V4.entry.tsx').write_text('export const Root = () => null;\n')
        self.assertEqual(3, self.run_fin('--check'))
        doc = json.loads((self.rdir / 'check.json').read_text())
        self.assertTrue(any('ytNewsStyle01V4.entry.tsx' in p for p in doc['integrity_problems']), doc)

    def test_real_gate_integrity_reports_the_new_issue_ids_when_the_entry_is_wrong(self):
        # run the real command directly against a composer whose entry drifted, registers nothing and imports a foreign file
        (self.repo / 'remotion-composer' / 'src' / 'ytNewsStyle01V4.entry.tsx').write_text(
            'import "./Root";\nexport const Root = () => null;\n')
        r = subprocess.run(['node', str(self.skill / 'scripts' / 'gate_integrity.mjs'), str(self.repo / 'remotion-composer'), '--json',
                            '--skill-dir', str(self.skill), '--require-lock'], capture_output=True, text=True)
        self.assertEqual(3, r.returncode)
        ids = {i['id'] for i in json.loads(r.stdout)['issues']}
        self.assertTrue({'entry-drift', 'entry-registration', 'entry-closure'} <= ids, ids)
        self.assertNotIn('root-registration', ids)

    def test_without_composer_public_the_run_stops_at_the_environment_check_exit_4(self):
        # public/ (media + fonts) is git-ignored and only exists in the checkout that started the work: the fonts check comes
        # first, so the schema gate's S07-file rule is never reached with a missing public directory
        shutil.rmtree(self.repo / 'remotion-composer' / 'public')
        self.assertEqual(4, self.run_fin('--check'), self.out)
        doc = json.loads((self.rdir / 'check.json').read_text())
        self.assertTrue(any('environment: fonts' in r for r in doc['reasons']), doc['reasons'])
        self.assertEqual([], doc['gates'])


class ScriptGateTests(FinalizeBase):
    """`script`: srt_to_script.py --strict is re-run; the result must be byte-identical to artifacts/script.txt."""

    def test_script_gate_passes_and_is_recorded(self):
        self.assertEqual(0, self.run_fin(), self.out)
        g = self.gate(self.receipt(), 'script')
        self.assertEqual('pass', g['status'])
        for rel in ('projects/p1/assets/avatar.srt', 'projects/p1/artifacts/source_script.txt', 'projects/p1/artifacts/script.txt',
                    'projects/p1/qc/finalize/script.json'):
            self.assertIn(rel, g['inputs'])
        self.assertIn('--strict', g['command'])
        self.assertEqual((self.proj / 'artifacts' / 'script.txt').read_bytes(), (self.rdir / 'script.rebuilt.txt').read_bytes())
        self.assertIs(True, json.loads((self.rdir / 'script.json').read_text())['pass'])

    def test_hand_edited_script_is_a_quality_failure(self):
        sp = self.proj / 'artifacts' / 'script.txt'
        sp.write_text(sp.read_text().replace('hello', 'hullo'))
        self.assertEqual(1, self.run_fin(), self.out)
        g = self.gate(self.failed(), 'script')
        self.assertEqual('fail', g['status'])
        self.assertIn('never edit it by hand', g['reason'])
        self.assertIn('script.rebuilt.txt', g['reason'])
        self.assertNotDelivered()

    def test_trailing_newline_difference_is_a_difference(self):
        sp = self.proj / 'artifacts' / 'script.txt'
        sp.write_text(sp.read_text() + '\n')
        self.assertEqual(1, self.run_fin(), self.out)
        self.assertEqual('fail', self.gate(self.failed(), 'script')['status'])

    def test_srt_that_differs_from_the_source_script_fails_strict(self):
        srt = self.proj / 'assets' / 'avatar.srt'
        srt.write_text(srt.read_text().replace('third line', 'a different line'))
        self.assertEqual(1, self.run_fin(), self.out)
        g = self.gate(self.failed(), 'script')
        self.assertEqual('fail', g['status'])
        self.assertIn('differs from the source script', g['reason'])

    def test_missing_source_script_is_bad_input_not_a_skip(self):
        (self.proj / 'artifacts' / 'source_script.txt').unlink()
        self.assertEqual(2, self.run_fin())
        for name in ('script', 'captions'):
            self.assertEqual('bad-input', self.gate(self.failed(), name)['status'], name)
        self.assertFalse(self.ran('lint_captions'))

    def test_captions_gate_always_gets_the_source_script(self):
        self.assertEqual(0, self.run_fin(), self.out)
        c = self.argv_of('lint_captions')
        self.assertEqual(str(self.proj / 'artifacts' / 'source_script.txt'), c[c.index('--source-script') + 1])


class ScriptSrtToolMissingTests(FinalizeBase):
    omit = ('srt_to_script.py',)

    def test_missing_tool_is_exit_4(self):
        self.assertEqual(4, self.run_fin())
        self.assertEqual('missing', self.gate(self.failed(), 'script')['status'])


class DerivedGateTests(FinalizeBase):
    """`derived`: the commands of SKILL step 2 are re-run from the raw word timing; outputs must be byte-identical."""

    def art(self, name):
        return self.proj / 'artifacts' / name

    def test_derived_passes_and_records_every_comparison(self):
        self.assertEqual(0, self.run_fin(), self.out)
        g = self.gate(self.receipt(), 'derived')
        self.assertEqual('pass', g['status'])
        rep = json.loads((self.rdir / 'derived.json').read_text())
        self.assertTrue(rep['pass'])
        self.assertEqual(3, len(rep['comparisons']))
        self.assertTrue(all(c['equal'] for c in rep['comparisons']))
        self.assertEqual({'endTime': 2.0}, rep['captionOptions'])
        self.assertEqual(sha(self.art('word_timing/caption_pages.json')), rep['wordTimingDone']['output_sha256'])
        for rel in ('word_timing/caption_pages.json', 'word_timing/word_timing.done.json', 'caption-options.json'):
            self.assertIn('projects/p1/artifacts/' + rel, g['inputs'])
        for name in ('words_by_line.txt', 'line_starts.json', 'caption-joined.json'):
            self.assertEqual((self.art(name)).read_bytes(), (self.rdir / 'derived' / name).read_bytes(), name)

    def test_each_hand_edited_artifact_is_a_quality_failure_naming_the_file(self):
        edits = {'words_by_line.txt': lambda t: t.replace('hello@0.0', 'hello@0.2'),
                 'line_starts.json': lambda t: t.replace('"start": 0.0', '"start": 0.1'),
                 'caption-joined.json': lambda t: t.replace('"hello"', '"hullo"', 1)}
        for name, fn in edits.items():
            shutil.copy(PROJECT_TEMPLATE / 'p1' / 'artifacts' / name, self.art(name))
            before = self.art(name).read_text()
            self.art(name).write_text(fn(before))
            self.assertNotEqual(before, self.art(name).read_text(), name)
            write_receipts(self.repo)
            self.assertEqual(1, self.run_fin(), (name, self.out))
            g = self.gate(self.failed(), 'derived')
            self.assertEqual('fail', g['status'], name)
            self.assertIn('artifacts/' + name, g['reason'])
            self.assertIn('byte-identical', g['reason'])
            shutil.copy(PROJECT_TEMPLATE / 'p1' / 'artifacts' / name, self.art(name))

    def test_edited_word_pages_do_not_match_the_word_timing_receipt(self):
        pages = self.art('word_timing/caption_pages.json')
        data = json.loads(pages.read_text())
        data[0]['words'][0]['s'] = 0.05                 # a hand-shifted timing
        pages.write_text(json.dumps(data))
        self.assertEqual(1, self.run_fin(), self.out)
        g = self.gate(self.failed(), 'derived')
        self.assertEqual('fail', g['status'])
        self.assertIn('output_sha256', g['reason'])

    def test_missing_word_timing_receipt_or_pages_is_bad_input(self):
        (self.art('word_timing/word_timing.done.json')).unlink()
        self.assertEqual(2, self.run_fin())
        self.assertEqual('bad-input', self.gate(self.failed(), 'derived')['status'])
        write_word_done(self.proj)
        self.art('word_timing/caption_pages.json').unlink()
        self.assertEqual(2, self.run_fin())
        self.assertEqual('bad-input', self.gate(self.failed(), 'derived')['status'])

    def set_options(self, data):
        self.art('caption-options.json').write_text(data if isinstance(data, str) else json.dumps(data))

    def test_caption_options_may_only_hold_end_time_and_lexical_overrides(self):
        for bad in ({'endTime': 2.0, 'maxUnits': 5}, {'endTime': 2.0, 'phraseBounds': []}, {'lexicalOverrides': ['x']},
                    {'endTime': '2.0'}, {'endTime': 2.5}, {'endTime': 2.0, 'lexicalOverrides': 'x'},
                    {'endTime': 2.0, 'lexicalOverrides': [1]}, '[1]', '{oops'):
            self.set_options(bad)
            code = self.run_fin()
            self.assertIn(code, (1, 2), (bad, self.out))
            self.assertIn(self.gate(self.failed(), 'derived')['status'], ('fail', 'bad-input'), bad)
            self.assertNotDelivered()

    def test_end_time_must_equal_vo_end_within_a_hundredth(self):
        self.set_options({'endTime': 2.009})
        shutil.copy(self.art('caption-options.json'), self.art('caption-options.json.bak'))
        derive_artifacts(self.proj)                    # keep every artifact consistent: only the endTime rule is under test
        write_receipts(self.repo)
        self.assertEqual(0, self.run_fin(), self.out)
        self.deliver.unlink()
        self.set_options({'endTime': 2.02})
        derive_artifacts(self.proj)
        write_receipts(self.repo)
        self.assertEqual(1, self.run_fin(), self.out)
        self.assertIn('endTime', self.gate(self.failed(), 'derived')['reason'])

    def test_lexical_overrides_are_allowed_and_part_of_the_derivation(self):
        self.set_options({'endTime': 2.0, 'lexicalOverrides': ['hello world']})
        derive_artifacts(self.proj)
        write_receipts(self.repo)
        self.assertEqual(0, self.run_fin(), self.out)

    def test_caption_joined_not_derived_from_the_options_is_detected(self):
        self.set_options({'endTime': 2.0, 'lexicalOverrides': ['hello world']})      # artifact still built without the override
        self.assertEqual(1, self.run_fin(), self.out)
        self.assertIn('caption-joined.json', self.gate(self.failed(), 'derived')['reason'])

    def test_word_pages_and_options_are_not_overridable_and_required(self):
        for key in ('word_pages', 'caption_options'):
            (self.proj / 'artifacts' / 'finalize.json').write_text(json.dumps({key: 'artifacts/x'}))
            self.assertEqual(2, self.run_fin(), key)
            self.assertIn('may not override', ' '.join(self.failed()['reasons']))
        (self.proj / 'artifacts' / 'finalize.json').unlink()
        self.art('caption-options.json').unlink()
        self.assertEqual(2, self.run_fin())
        self.assertEqual('bad-input', self.gate(self.failed(), 'derived')['status'])


class DerivedToolMissingTests(FinalizeBase):
    omit = ('caption_join.mjs',)

    def test_missing_tool_is_exit_4(self):
        self.assertEqual(4, self.run_fin())
        self.assertEqual('missing', self.gate(self.failed(), 'derived')['status'])


class FramesMediaRootTests(FinalizeBase):
    def test_frames_check_the_files_the_render_uses_not_the_project_copies(self):
        (self.proj / 'assets' / 'broll' / 'only-in-project.mp4').write_bytes(b'p')
        self.assertEqual(0, self.run_fin(), self.out)
        f = self.argv_of('frame_checks')
        roots = [f[i + 1] for i, x in enumerate(f) if x == '--media-root']
        self.assertEqual([str(self.repo / 'remotion-composer' / 'public' / 'ep1' / 'broll')], roots)

    def test_missing_render_media_directory_is_bad_input_not_a_fallback(self):
        shutil.rmtree(self.repo / 'remotion-composer' / 'public' / 'ep1' / 'broll')
        self.assertEqual(2, self.run_fin())
        g = self.gate(self.failed(), 'frames')
        self.assertEqual('bad-input', g['status'])
        self.assertIn('broll_root', g['reason'])
        self.assertFalse(self.ran('frame_checks'))
        self.assertEqual('blocked', self.gate(self.failed(), 'content')['status'])


class MuxVideoAndReceiptFactsTests(FinalizeBase):
    def test_final_must_carry_the_video_packets_of_the_visual(self):
        # same picture, different encode: the sha of the final differs from the visual's stream
        final_with_audio(self.proj, '-c:v', 'libx264', '-crf', '30', '-pix_fmt', 'yuv420p')
        write_receipts(self.repo)
        self.assertEqual(2, self.run_fin(), self.out)
        g = self.gate(self.failed(), 'mux-video')
        self.assertEqual('stale', g['status'])
        self.assertIn('differs from', g['reason'])

    def test_final_with_a_different_number_of_frames_is_refused(self):
        final_with_audio(self.proj, '-c:v', 'copy', '-t', '2.5')
        write_receipts(self.repo)
        self.assertEqual(2, self.run_fin(), self.out)
        self.assertEqual('stale', self.gate(self.failed(), 'mux-video')['status'])

    def test_streamhash_of_a_real_mux_av_run_equals_the_visual(self):
        tmp = Path(self.tmp) / 'mux'
        tmp.mkdir()
        shutil.copy(self.proj / 'renders' / 'visual.mp4', tmp / 'visual.mp4')
        ffmpeg('-f', 'lavfi', '-i', 'anoisesrc=d=3:c=pink:a=0.3:r=48000', str(tmp / 'vo.wav'))
        ffmpeg('-f', 'lavfi', '-i', 'anoisesrc=d=3:c=brown:a=0.2:r=48000', str(tmp / 'bed.wav'))
        r = subprocess.run(['bash', str(SCRIPTS / 'mux_av.sh'), str(tmp / 'visual.mp4'), str(tmp / 'vo.wav'), str(tmp / 'bed.wav'),
                            str(tmp / 'final.mp4'), '4', '2'], capture_output=True, text=True, cwd=tmp)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        m = self.module()
        ctx = m.Ctx(type('A', (), {'project': str(self.proj), 'composer': 'remotion-composer', 'manifest': None})(), self.repo,
                    self.repo / 'out' / 'x.mp4', m.resolve_tools())
        dl = m.Deadline(120)
        env = m.gate_env(ctx.tools)
        a = m.stream_hash(ctx, tmp / 'visual.mp4', env, dl)
        b = m.stream_hash(ctx, tmp / 'final.mp4', env, dl)
        self.assertEqual((None, 0), (a[1], a[2]))
        self.assertEqual(a, b)                      # -c:v copy -t TOTAL keeps every packet

    def test_render_receipt_facts_must_match_ffprobe_of_the_visual(self):
        cases = {'width': 1920, 'height': 1080, 'fps': 30, 'frameCount': 50}
        for key, value in cases.items():
            write_receipts(self.repo)
            self.edit(self.render_path(), lambda d, k=key, v=value: d.update({k: v}))
            self.assertEqual(2, self.run_fin(), (key, self.out))
            g = self.gate(self.failed(), 'render')
            self.assertEqual('stale', g['status'], key)
            self.assertIn(key, g['reason'])


class VideoFormatTests(FinalizeBase):
    """Item 5: ffprobe pix_fmt of BOTH renders/visual.mp4 and renders/final.mp4 is yuv420p; the final's colour facts go into the receipt."""

    def test_delivered_receipt_records_pix_fmt_color_space_color_range_of_the_final(self):
        self.assertEqual(0, self.run_fin(), self.out)
        rc = self.receipt()
        self.assertEqual({'pix_fmt', 'color_space', 'color_range'}, set(rc['video']))
        self.assertEqual('yuv420p', rc['video']['pix_fmt'])
        g = self.gate(rc, 'video-format')
        self.assertEqual('pass', g['status'])

    def test_recorded_colour_facts_are_what_ffprobe_says_about_the_final(self):
        self.assertEqual(0, self.run_fin(), self.out)
        r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=pix_fmt,color_space,color_range',
                            '-of', 'json', str(self.fin)], capture_output=True, text=True, check=True)
        s = json.loads(r.stdout)['streams'][0]
        self.assertEqual({k: s.get(k) for k in ('pix_fmt', 'color_space', 'color_range')}, self.receipt()['video'])

    def test_a_visual_that_is_not_yuv420p_is_a_quality_failure_exit_1(self):
        self.set_videos(None, pix_fmt='yuv444p')            # the final is its stream copy, so the streams agree: only the format is wrong
        self.assertEqual(1, self.run_fin(), self.out)
        self.assertNotDelivered()
        g = self.gate(self.failed(), 'video-format')
        self.assertEqual('fail', g['status'])
        self.assertIn('visual.mp4 pix_fmt is', g['reason'])
        self.assertIn('yuv444p', g['reason'])
        self.assertIn('must not be re-encoded', g['reason'])

    def test_a_re_encoded_final_that_is_not_yuv420p_names_the_final(self):
        final_with_audio(self.proj, '-c:v', 'libx264', '-pix_fmt', 'yuv444p')
        write_receipts(self.repo)
        code = self.run_fin()
        self.assertEqual(2, code, self.out)                 # mux-video (the stream differs) is class 2 and wins over the class 1 format failure
        self.assertNotDelivered()
        f = self.failed()
        g = self.gate(f, 'video-format')
        self.assertEqual('fail', g['status'])
        self.assertIn('final.mp4 pix_fmt is', g['reason'])
        self.assertIn('must not be re-encoded', g['reason'])
        self.assertEqual('stale', self.gate(f, 'mux-video')['status'])

    def test_an_unprobable_final_is_not_a_format_pass(self):
        self.fin.write_bytes(b'not a video')
        self.assertNotEqual(0, self.run_fin(), self.out)
        self.assertNotDelivered()
        self.assertNotEqual('pass', self.gate(self.failed(), 'video-format')['status'])


class SwiftRequiredTests(FinalizeBase):
    """Item 6: swift (Vision OCR of the frames gate) is a required tool; finalize stops with class 4 before any gate runs."""

    def test_missing_swift_is_exit_4_and_nothing_ran(self):
        real = None

        def patch(m):
            nonlocal real
            real = m.resolve_tools
            m.resolve_tools = lambda: dict(real(), swift=None)
        self.behavior(lint_beats={'exit': 1, 'pass': False})      # a quality failure must not mask the tool problem
        self.assertEqual(4, self.run_fin(patch=patch), self.out)
        self.assertNotDelivered()
        f = self.failed()
        self.assertEqual(4, f['exit_code'])
        self.assertTrue(any('swift' in r for r in f['reasons']), f['reasons'])
        self.assertEqual([], f['gates'])
        for stem in STEM.values():
            self.assertFalse(self.ran(stem), stem)

    def test_swift_is_part_of_the_required_tools(self):
        m = self.module()
        self.assertIn('swift', m.REQUIRED_TOOLS)

    @unittest.skipUnless(importlib.util.find_spec('numpy') and importlib.util.find_spec('PIL'), 'frame_checks.py needs numpy and PIL in this interpreter')
    def test_the_real_frame_checks_cutaways_exits_4_when_neither_swift_nor_swiftc_exists(self):
        """Read-only check of frame_checks.py (not edited): no OCR is never a silent skip."""
        t = Path(self.tmp) / 'fc'
        (t / 'bin').mkdir(parents=True)
        (t / 'media').mkdir()
        for tool in ('ffmpeg', 'ffprobe'):
            os.symlink(shutil.which(tool), t / 'bin' / tool)
        ep = json.loads((FIXTURES / 'valid' / 'sample-v1.json').read_text())
        ep['beats'] = [b for b in ep['beats'] if b.get('media') not in ('broll', 'clip') or b['src'] == 'photographer_for_images']
        ep['brollDur'] = {'photographer_for_images': ep['brollDur']['photographer_for_images']}
        (t / 'ep.json').write_text(json.dumps(ep))
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=320x240:r=25:d=12', '-pix_fmt', 'yuv420p', str(t / 'media' / 'photographer_for_images.mp4'))
        r = subprocess.run([sys.executable, '-B', str(SCRIPTS / 'frame_checks.py'), 'cutaways', '--beats', str(t / 'ep.json'),
                            '--media-root', str(t / 'media'), '--frames-dir', str(t / 'fr'), '--episode-end', '30'],
                           capture_output=True, text=True, env={'PATH': str(t / 'bin'), 'HOME': os.environ.get('HOME', str(t))}, cwd=t)
        self.assertEqual(4, r.returncode, r.stdout + r.stderr)
        self.assertIn('swift / swiftc not found', r.stderr)


class RenderReceiptEngineBindingTests(FinalizeBase):
    """Items 1 and 2: the receipt binds the engine, the entry and the entry closure; outputSha256 only binds a file to its receipt."""

    def test_removed_fields_are_not_required_any_more(self):
        rc = json.loads(self.render_path().read_text())
        self.assertNotIn('rootTsxSha256', rc)
        self.assertNotIn('indexTsxSha256', rc)
        self.assertEqual(0, self.run_fin(), self.out)

    def test_each_engine_binding_field_is_required_and_checked(self):
        cases = {
            'engine-missing': lambda d: d.pop('engineSha256'),
            'engine-wrong': lambda d: d.update(engineSha256='1' * 64),
            'entry-missing': lambda d: d.pop('entrySha256'),
            'entry-wrong': lambda d: d.update(entrySha256='2' * 64),
            'closure-missing': lambda d: d.pop('entryClosure'),
            'closure-empty': lambda d: d.update(entryClosure={}),
            'closure-wrong-file': lambda d: d['entryClosure'].update({'src/ytNewsStyle01V4Sample.json': '3' * 64}),
            'closure-without-entry': lambda d: d['entryClosure'].pop('src/ytNewsStyle01V4.entry.tsx'),
            'closure-without-engine': lambda d: d['entryClosure'].pop('src/YtNewsStyle01V4.tsx'),
            'closure-escape': lambda d: d['entryClosure'].update({'src/../../etc/passwd': '4' * 64}),
        }
        for label, fn in cases.items():
            write_receipts(self.repo)
            self.edit(self.render_path(), fn)
            self.assertEqual(2, self.run_fin(), (label, self.out))
            self.assertEqual('stale', self.gate(self.failed(), 'render')['status'], label)

    def test_a_composer_file_changed_after_the_render_is_stale(self):
        (self.repo / 'remotion-composer' / 'src' / 'ytNewsStyle01V4Sample.json').write_text('{"a": 1}\n')
        # the lock (a locked external) already refuses this one; the receipt closure is the second line behind it
        self.assertEqual(3, self.run_fin(), self.out)

    def test_output_sha256_is_not_reproducible_a_re_render_with_a_different_hash_and_a_fresh_receipt_delivers(self):
        """A re-render of the same inputs gives a different outputSha256 (encoder output is not reproducible).  The receipt only binds a
        file to ITS receipt: a second render with a new hash and a new receipt is a normal, accepted state."""
        self.assertEqual(0, self.run_fin(), self.out)
        before = sha(self.proj / 'renders' / 'visual.mp4')
        self.deliver.unlink()
        Path(str(self.deliver) + '.receipt.json').unlink()
        self.set_videos([*VISUAL_ARGS, '-crf', '31'])
        self.assertNotEqual(before, sha(self.proj / 'renders' / 'visual.mp4'))
        self.assertEqual(0, self.run_fin(), self.out)

    def test_a_visual_re_rendered_without_a_new_receipt_is_stale(self):
        before = json.loads(self.render_path().read_text())['outputSha256']
        make_videos(self.proj, [*VISUAL_ARGS, '-crf', '33'])
        self.assertNotEqual(before, sha(self.proj / 'renders' / 'visual.mp4'))
        self.assertEqual(2, self.run_fin(), self.out)
        self.assertEqual('stale', self.gate(self.failed(), 'render')['status'])


class SkillTreeCoverageTests(FinalizeBase):
    """Item 4: every file of the skill tree (and of the .agents mirror) must be listed in gates.lock.json.
    COVERED: any regular file below the skill directory (scripts/, scripts/tests/, assets/, references/, SKILL.md ...), in both the
    .claude copy and the .agents mirror.  NOT covered (by design): __pycache__ directories (purged by finalize before the gates run),
    .DS_Store, the lock file itself (pinned by git HEAD and by the render receipt) and anything outside the two skill directories."""

    def mirror(self):
        return self.repo / '.agents' / 'skills' / self.name

    def test_a_new_file_in_scripts_is_file_extra(self):
        (self.skill / 'scripts' / 'new_helper.py').write_text('x = 1\n')
        self.behavior(lint_beats={'exit': 1, 'pass': False})
        self.assertEqual(3, self.run_fin(), self.out)
        self.assertTrue(any(p.startswith('file-extra') and 'scripts/new_helper.py' in p for p in self.failed()['integrity_problems']), self.failed())
        self.assertEqual([], self.failed()['gates'])

    def test_a_new_file_in_scripts_tests_is_file_extra(self):
        (self.skill / 'scripts' / 'tests' / 'test_new.py').write_text('x = 1\n')
        self.assertEqual(3, self.run_fin(), self.out)
        self.assertTrue(any(p.startswith('file-extra') and 'scripts/tests/test_new.py' in p for p in self.failed()['integrity_problems']))

    def test_a_new_file_in_assets_is_file_extra(self):
        (self.skill / 'assets' / 'new-asset.json').write_text('{}\n')
        self.assertEqual(3, self.run_fin(), self.out)
        self.assertTrue(any(p.startswith('file-extra') and 'assets/new-asset.json' in p for p in self.failed()['integrity_problems']))

    def test_a_new_file_in_the_agents_mirror_is_file_extra(self):
        for sub in ('scripts', 'scripts/tests', 'assets'):
            (self.mirror() / sub / 'mirror-only.txt').write_text('x\n')
            self.assertEqual(3, self.run_fin(), (sub, self.out))
            self.assertTrue(any(p.startswith('file-extra') and 'mirror-only.txt' in p and '.agents' in p for p in self.failed()['integrity_problems']),
                            (sub, self.failed()['integrity_problems']))
            (self.mirror() / sub / 'mirror-only.txt').unlink()
        self.assertEqual(0, self.run_fin(), self.out)

    def test_a_new_file_in_a_new_subdirectory_is_file_extra(self):
        (self.skill / 'extras').mkdir()
        (self.skill / 'extras' / 'x.md').write_text('x\n')
        self.assertEqual(3, self.run_fin(), self.out)
        self.assertTrue(any(p.startswith('file-extra') and 'extras/x.md' in p for p in self.failed()['integrity_problems']))

    def test_a_symlink_in_the_skill_tree_is_refused(self):
        os.symlink(self.skill / 'SKILL.md', self.skill / 'scripts' / 'link.py')
        self.assertEqual(3, self.run_fin(), self.out)

    def test_pycache_is_the_only_tolerated_extra_and_finalize_purges_it(self):
        pc = self.skill / 'scripts' / '__pycache__'
        pc.mkdir()
        (pc / 'x.cpython-312.pyc').write_bytes(b'\0')
        self.assertEqual(0, self.run_fin(), self.out)
        self.assertFalse(pc.exists())

    def test_the_lock_refuses_to_be_written_over_an_untracked_file(self):
        (self.skill / 'scripts' / 'untracked.py').write_text('x\n')
        with self.assertRaises(Exception):
            _gl.build_lock(self.skill, self.repo, [], required=EXTERNAL_PATHS)


REAL_DIPS = [  # the exact shape qc_final_pixels.mjs findDarkDips() writes into final-pixels.json
    {'startFrame': 21, 'endFrame': 22, 'startSec': 0.84, 'runFrames': 2, 'minY': 3.1, 'beforeY': 40.25, 'recoveredToY': 38.5, 'kind': 'flash'},
    {'startFrame': 150, 'endFrame': 153, 'startSec': 6, 'runFrames': 4, 'minY': 2, 'beforeY': 9.5, 'recoveredToY': 30, 'kind': 'dark-entry'},
    {'startFrame': 300, 'endFrame': 301, 'startSec': 12, 'runFrames': 2, 'minY': 1, 'beforeY': 33, 'recoveredToY': 31, 'kind': 'flash'},
    {'startFrame': 400, 'endFrame': 401, 'startSec': 16, 'runFrames': 2, 'minY': 1, 'beforeY': 33, 'recoveredToY': 31, 'kind': 'flash'},
    {'startFrame': 500, 'endFrame': 501, 'startSec': 20, 'runFrames': 2, 'minY': 1, 'beforeY': 33, 'recoveredToY': 31, 'kind': 'flash'},
]


class ConsoleSummaryTests(FinalizeBase):
    def test_final_pixels_failure_prints_kind_count_first_occurrences_with_time_and_values_and_the_report_path(self):
        self.behavior(qc_final_pixels={'exit': 1, 'pass': False, 'certified': False, 'dips': REAL_DIPS})
        self.assertEqual(1, self.run_fin(), self.out)
        lines = [l.strip() for l in self.out.splitlines()]
        self.assertNotIn('- dips', lines)
        flash = next(l for l in lines if l.startswith('- flash x4'))
        self.assertIn('first 3', flash)
        self.assertIn('[@0.84s startFrame=21 endFrame=22 runFrames=2 minY=3.1 beforeY=40.25 recoveredToY=38.5]', flash)
        self.assertIn('[@12s ', flash)
        self.assertIn('+1 more', flash)
        self.assertNotIn('@20s', flash)                    # only the first three occurrences
        entry = next(l for l in lines if l.startswith('- dark-entry x1'))
        self.assertIn('[@6s startFrame=150 endFrame=153 runFrames=4 minY=2 beforeY=9.5 recoveredToY=30]', entry)
        self.assertTrue(any(l.startswith('report:') and 'qc/finalize/final-pixels/final-pixels.json' in l for l in lines), self.out)
        g = self.gate(self.failed(), 'final-pixels')
        self.assertEqual(2, len(g['issues']))

    def test_issues_without_detail_print_their_scalar_fields_not_only_the_code(self):
        self.behavior(lint_beats={'exit': 1, 'pass': False, 'issues': [
            {'code': 'hold', 't': 3.2, 'seconds': 9.5, 'max': 6, 'nested': {'a': 1}}, {'code': 'hold', 'beat': 'S4', 'seconds': 8}]})
        self.assertEqual(1, self.run_fin(), self.out)
        line = next(l.strip() for l in self.out.splitlines() if l.strip().startswith('- hold x2'))
        self.assertIn('[@3.2s seconds=9.5 max=6]', line)           # nested objects are not scalars: skipped
        self.assertIn('[beat=S4 seconds=8]', line)

    def test_an_issue_with_detail_keeps_its_one_line_and_truncates_only_the_free_text(self):
        m = self.module()
        long_detail = 'x' * 500
        out = m.summarize_issues({'issues': [{'code': 'c', 'detail': long_detail, 't': 1.5}]})
        self.assertEqual(1, len(out))
        self.assertTrue(out[0].startswith('c: ' + 'x' * 300))
        self.assertNotIn('x' * 301, out[0])
        self.assertTrue(out[0].endswith('(@1.5)'))                 # the location survives the truncation

    def test_a_command_is_never_truncated_in_the_fail_output(self):
        m = self.module()
        command = 'node ' + ' '.join('--flag-%d=/very/long/path/segment/%s' % (i, 'z' * 20) for i in range(40))
        self.assertGreater(len(command), 900)
        rec = m.record({'name': 'g'}, 'fail', 1, 'boom', report='qc/finalize/g.json', command=command)
        text = m.summary([rec])
        self.assertIn('\n' + command + '\n', text + '\n')          # on its own line, whole
        self.assertIn('rerun (copy the next line):', text)
        out = m.summarize_issues({'issues': [{'code': 'c', 'detail': 'd', 'command': command}]}, limit=5)
        self.assertIn('rerun (copy this whole line): ' + command, out)

    def test_real_gate_output_carries_the_whole_command(self):
        self.behavior(lint_beats={'exit': 1, 'pass': False})
        self.assertEqual(1, self.run_fin(), self.out)
        cmd = self.gate(self.failed(), 'beats')['command']
        self.assertIn('\n' + cmd + '\n', self.out)


class CheckStateAndInterruptTests(FinalizeBase):
    def popen(self, *extra):
        return subprocess.Popen([sys.executable, '-B', str(self.skill / 'scripts' / 'finalize.py'), '--project', 'projects/p1',
                                 '--deliver', str(self.deliver), *extra], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def wait_for(self, path, secs=15):
        for _ in range(int(secs * 10)):
            if Path(path).exists():
                return True
            time.sleep(0.1)
        return False

    def sleepers(self):
        for stem in ('frame_checks', 'measure_loudness', 'timing_check'):
            (self.repo / '.stub_logs' / (stem + '.pid')).unlink(missing_ok=True)      # a pid file of an earlier run must not fool wait_for
        self.behavior(**{n: {'sleep': 25} for n in ('frame_checks', 'measure_loudness', 'timing_check')})

    def test_check_replaces_a_stale_check_json_with_a_running_marker_then_a_terminated_state(self):
        self.rdir.mkdir(parents=True, exist_ok=True)
        (self.rdir / 'check.json').write_text(json.dumps({'status': 'finished', 'would_deliver': True, 'exit_code': 0}))
        self.sleepers()
        p = self.popen('--check')
        self.assertTrue(self.wait_for(self.repo / '.stub_logs' / 'frame_checks.pid'), 'the gates did not start')
        marker = json.loads((self.rdir / 'check.json').read_text())
        self.assertEqual('running', marker['status'])
        self.assertEqual(p.pid, marker['pid'])
        self.assertIn('started_at', marker)
        self.assertIs(False, marker['would_deliver'])
        p.send_signal(signal.SIGTERM)
        out, err = p.communicate(timeout=30)
        self.assertEqual(4, p.returncode, out + err)
        state = json.loads((self.rdir / 'check.json').read_text())
        self.assertEqual('terminated', state['status'])
        self.assertEqual(signal.SIGTERM, state['signal'])
        self.assertEqual(4, state['exit_code'])
        self.assertIs(False, state['would_deliver'])
        self.assertFalse(Path(str(self.deliver) + '.FAILED.json').exists())      # --check never writes it, not even when interrupted

    def test_sigint_is_reported_as_an_interruption_too(self):
        self.sleepers()
        p = self.popen('--check')
        self.assertTrue(self.wait_for(self.repo / '.stub_logs' / 'frame_checks.pid'))
        p.send_signal(signal.SIGINT)
        out, err = p.communicate(timeout=30)
        self.assertEqual(4, p.returncode, out + err)
        self.assertEqual(signal.SIGINT, json.loads((self.rdir / 'check.json').read_text())['signal'])

    def test_signal_message_is_an_interruption_not_an_internal_error(self):
        self.sleepers()
        p = self.popen()
        self.assertTrue(self.wait_for(self.repo / '.stub_logs' / 'frame_checks.pid'))
        p.send_signal(signal.SIGTERM)
        out, err = p.communicate(timeout=30)
        self.assertEqual(4, p.returncode, out + err)
        self.assertIn('FINALIZE INTERRUPTED (exit 4): terminated by signal 15 \u2014 nothing was delivered; re-run the same command', out)
        self.assertNotIn('internal error', out)
        f = self.failed()
        self.assertEqual('terminated', f['status'])
        self.assertEqual(signal.SIGTERM, f['signal'])
        self.assertNotIn('traceback', f)

    def test_check_mode_finishes_with_the_result_path_and_the_no_failed_json_statement(self):
        self.behavior(lint_beats={'exit': 1, 'pass': False})
        self.assertEqual(1, self.run_fin('--check'), self.out)
        check = self.rdir / 'check.json'
        self.assertIn('CHECK RESULT FILE: %s' % check, self.out)
        self.assertIn('--check never writes %s' % (str(self.deliver) + '.FAILED.json'), self.out)
        self.assertEqual('finished', json.loads(check.read_text())['status'])
        self.assertFalse(Path(str(self.deliver) + '.FAILED.json').exists())
        self.assertTrue(self.out.rstrip().splitlines()[-2].startswith('CHECK RESULT FILE'))

    def test_check_pass_also_names_the_result_file(self):
        self.assertEqual(0, self.run_fin('--check'), self.out)
        self.assertIn('CHECK RESULT FILE: %s' % (self.rdir / 'check.json'), self.out)

    def test_an_integrity_failure_in_check_mode_overwrites_a_stale_check_json_and_says_where_it_is(self):
        self.rdir.mkdir(parents=True, exist_ok=True)
        (self.rdir / 'check.json').write_text(json.dumps({'status': 'finished', 'would_deliver': True, 'exit_code': 0}))
        (self.skill / 'scripts' / 'lint_beats.py').write_text('import sys; sys.exit(0)\n')
        self.assertEqual(3, self.run_fin('--check'), self.out)
        doc = json.loads((self.rdir / 'check.json').read_text())
        self.assertEqual((3, False), (doc['exit_code'], doc['would_deliver']))
        self.assertIn('CHECK RESULT FILE: %s' % (self.rdir / 'check.json'), self.out)

    def test_a_live_run_keeps_its_own_check_json_a_second_invocation_does_not_clobber_it(self):
        self.sleepers()
        first = self.popen('--check')
        self.assertTrue(self.wait_for(self.repo / '.stub_logs' / 'frame_checks.pid'))
        before = (self.rdir / 'check.json').read_text()
        second = self.popen('--check')
        out, err = second.communicate(timeout=30)
        self.assertEqual(2, second.returncode, out + err)
        self.assertEqual(first.pid, json.loads((self.rdir / 'check.json').read_text())['pid'])
        self.assertEqual(before, (self.rdir / 'check.json').read_text())
        first.send_signal(signal.SIGTERM)
        first.communicate(timeout=30)


class StaleDeliveryFilesTests(CheckStateAndInterruptTests):
    """A real run never leaves the result of an earlier attempt next to the deliver path while it runs."""

    def deliver_once(self):
        self.assertEqual(0, self.run_fin(), self.out)
        return self.deliver.read_bytes(), json.loads(Path(str(self.deliver) + '.receipt.json').read_text())

    def test_stale_failed_json_and_partials_are_gone_while_the_new_attempt_runs(self):
        self.deliver.parent.mkdir(parents=True)
        Path(str(self.deliver) + '.FAILED.json').write_text('{"exit_code": 1, "old": true}')
        Path(str(self.deliver) + '.partial').write_bytes(b'junk')
        Path(str(self.deliver) + '.receipt.json.tmp').write_text('{}')
        Path(str(self.deliver) + '.receipt.json').write_text('{"orphan": true}')           # a receipt of nothing
        self.sleepers()
        p = self.popen()
        self.assertTrue(self.wait_for(self.repo / '.stub_logs' / 'frame_checks.pid'))
        for suffix in ('.FAILED.json', '.partial', '.receipt.json.tmp', '.receipt.json'):
            self.assertFalse(Path(str(self.deliver) + suffix).exists(), suffix)
        p.send_signal(signal.SIGTERM)
        p.communicate(timeout=30)
        self.assertEqual('terminated', self.failed()['status'])

    def test_a_certified_earlier_delivery_survives_while_the_new_attempt_runs_and_is_preserved_when_it_is_interrupted(self):
        old_bytes, old_receipt = self.deliver_once()
        self.sleepers()
        p = self.popen()
        self.assertTrue(self.wait_for(self.repo / '.stub_logs' / 'frame_checks.pid'))
        self.assertEqual(old_bytes, self.deliver.read_bytes())                              # untouched during the run
        self.assertEqual(old_receipt, json.loads(Path(str(self.deliver) + '.receipt.json').read_text()))
        self.assertFalse(Path(str(self.deliver) + '.FAILED.json').exists())
        p.send_signal(signal.SIGTERM)
        p.communicate(timeout=30)
        # interrupted: the old pair is renamed, never deleted, and the deliver path holds no mp4 that this run did not certify
        self.assertFalse(self.deliver.exists())
        self.assertFalse(Path(str(self.deliver) + '.receipt.json').exists())
        prev = Path(str(self.deliver) + '.previous')
        self.assertEqual(old_bytes, prev.read_bytes())
        self.assertEqual(old_receipt, json.loads(Path(str(prev) + '.receipt.json').read_text()))
        f = self.failed()
        self.assertEqual(str(prev), f['preexisting_output_moved_to'])
        self.assertIs(True, f['previous_delivery_preserved'])
        self.assertIs(False, f['preexisting_output_not_certified'])

    def test_a_failed_attempt_preserves_the_certified_pair_as_previous_never_deletes_it(self):
        old_bytes, old_receipt = self.deliver_once()
        self.behavior(lint_beats={'exit': 1, 'pass': False})
        self.assertEqual(1, self.run_fin(), self.out)
        self.assertFalse(self.deliver.exists())
        prev = Path(str(self.deliver) + '.previous')
        self.assertEqual(old_bytes, prev.read_bytes())
        self.assertEqual(old_receipt, json.loads(Path(str(prev) + '.receipt.json').read_text()))
        self.assertIs(True, self.failed()['previous_delivery_preserved'])
        # a second failure never overwrites the first preserved pair
        self.behavior(lint_beats={'exit': 0, 'pass': True})
        self.assertEqual(0, self.run_fin(), self.out)
        self.behavior(lint_beats={'exit': 1, 'pass': False})
        self.assertEqual(1, self.run_fin(), self.out)
        self.assertEqual(old_bytes, prev.read_bytes())
        self.assertTrue(Path(str(self.deliver) + '.previous.1').exists())
        self.assertTrue(Path(str(self.deliver) + '.previous.1.receipt.json').exists())

    def test_a_successful_attempt_replaces_the_certified_pair_with_the_new_pair(self):
        old_bytes, old_receipt = self.deliver_once()
        self.assertEqual(0, self.run_fin(), self.out)
        self.assertEqual(old_bytes, self.deliver.read_bytes())
        self.assertFalse(Path(str(self.deliver) + '.previous').exists())
        new_receipt = json.loads(Path(str(self.deliver) + '.receipt.json').read_text())
        self.assertEqual(old_receipt['delivered']['sha256'], new_receipt['delivered']['sha256'])
        self.assertFalse(Path(str(self.deliver) + '.FAILED.json').exists())

    def test_an_mp4_whose_receipt_does_not_match_is_not_certified_and_goes_to_uncertified(self):
        self.deliver_once()
        self.deliver.write_bytes(b'SOMETHING ELSE')                      # the receipt now vouches for another file
        self.behavior(lint_beats={'exit': 1, 'pass': False})
        self.assertEqual(1, self.run_fin(), self.out)
        self.assertEqual(b'SOMETHING ELSE', Path(str(self.deliver) + '.uncertified').read_bytes())
        self.assertFalse(Path(str(self.deliver) + '.previous').exists())
        self.assertFalse(Path(str(self.deliver) + '.receipt.json').exists())
        self.assertIs(False, self.failed()['previous_delivery_preserved'])


class PreflightBase(FinalizeBase):
    """Helpers for the environment-check tests."""

    def run_pre(self, *extra, patch=None):
        m = self.module()
        if patch:
            patch(m)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = m.main(['--preflight', *extra])
        self.out = buf.getvalue()
        return code

    def lines(self):
        return [l for l in self.out.splitlines() if l.startswith('PREFLIGHT ')]

    def line(self, status, name):
        found = [l for l in self.lines() if l.startswith('PREFLIGHT %s %s:' % (status, name))]
        self.assertEqual(1, len(found), (status, name, self.out))
        return found[0]

    def without_tool(self, name):
        def patch(m):
            real = m.resolve_tools
            m.resolve_tools = lambda: dict(real(), **{name: None})
        return patch



class PreflightTests(PreflightBase):
    """`finalize.py --preflight`: the environment checks a real run starts with, printed one line per check."""

    def test_all_ok_exit_0_one_line_per_check_and_no_project_or_deliver_needed(self):
        self.assertEqual(0, self.run_pre(), self.out)
        names = ['tool-node', 'tool-ffmpeg', 'tool-ffprobe', 'tool-git', 'tool-swift', 'python-modules', 'composer-node-modules',
                 'fonts', 'gate-lock', 'word-timing', 'music-library']
        got = [l.split(' ', 3)[1:3] for l in self.lines()[:-1]]
        self.assertEqual([['ok', n + ':'] for n in names], got)
        self.assertTrue(self.lines()[-1].startswith('PREFLIGHT PASS (exit 0)'), self.out)
        self.assertNotIn('FAIL', self.out)
        for n in ('node', 'ffmpeg', 'ffprobe', 'git', 'swift'):
            self.assertIn(os.path.realpath(shutil.which(n)), self.line('ok', 'tool-' + n))          # realpath and version
        self.assertIn(os.path.realpath(sys.executable), self.line('ok', 'python-modules'))
        self.assertIn('not loaded', self.line('ok', 'word-timing'))
        # nothing is written: no reports directory, no check.json, no lock file of a run
        self.assertFalse((self.proj / 'qc' / 'finalize' / 'check.json').exists())

    def test_each_missing_tool_is_exit_4(self):
        for name in ('node', 'ffmpeg', 'ffprobe', 'git', 'swift'):
            code = self.run_pre(patch=self.without_tool(name))
            if name in ('node', 'git'):
                self.assertNotEqual(0, code, name)                  # the lock / list command cannot run without them either
                continue
            self.assertEqual(4, code, (name, self.out))
            self.assertIn('not found on PATH', self.line('FAIL', 'tool-' + name))
            self.assertTrue(self.lines()[-1].startswith('PREFLIGHT FAIL (exit 4)'), self.out)

    def test_missing_node_is_exit_4_not_ok(self):
        self.assertEqual(4, self.run_pre(patch=self.without_tool('node')), self.out)
        self.line('FAIL', 'tool-node')

    def test_python_modules_missing_names_the_interpreter_and_the_venv_hint(self):
        def patch(m):
            m.PY_MODULES = ('numpy', 'no_such_module_xyz')
        self.assertEqual(4, self.run_pre(patch=patch), self.out)
        line = self.line('FAIL', 'python-modules')
        self.assertIn('no_such_module_xyz', line)
        self.assertNotIn('cannot import numpy', line)
        self.assertIn(os.path.realpath(sys.executable), line)
        self.assertIn("run finalize with the repo's .venv python", line)

    def test_composer_node_modules_missing_or_incomplete(self):
        nm = self.repo / 'remotion-composer' / 'node_modules'
        shutil.rmtree(nm / '@remotion' / 'renderer')
        self.assertEqual(4, self.run_pre(), self.out)
        self.assertIn('@remotion/renderer', self.line('FAIL', 'composer-node-modules'))
        shutil.rmtree(nm)
        self.assertEqual(4, self.run_pre(), self.out)
        self.assertIn('does not exist', self.line('FAIL', 'composer-node-modules'))

    def test_every_package_the_engine_scripts_load_lazily_is_required(self):
        m = self.module()
        self.assertEqual(('remotion', '@remotion/bundler', '@remotion/renderer'), m.COMPOSER_PACKAGES)
        text = (SCRIPTS / 'render_episode.mjs').read_text() + (SCRIPTS / 'qc_layout.mjs').read_text()
        for pkg in ('@remotion/bundler', '@remotion/renderer'):
            self.assertIn("'%s'" % pkg, text)                       # read from the engine scripts: still what they load

    def test_fonts_missing_or_empty(self):
        fonts = self.repo / 'remotion-composer' / 'public' / 'fonts'
        (fonts / 'Kanit-ExtraBold.ttf').write_bytes(b'')
        self.assertEqual(4, self.run_pre(), self.out)
        self.assertIn('Kanit-ExtraBold.ttf', self.line('FAIL', 'fonts'))
        self.assertNotIn('Kanit-Bold.ttf,', self.line('FAIL', 'fonts'))
        shutil.rmtree(fonts)
        self.assertEqual(4, self.run_pre(), self.out)
        self.assertIn('Kanit-Bold.ttf', self.line('FAIL', 'fonts'))

    def test_the_font_list_is_what_the_engine_loads(self):
        engine = (SCRIPTS.parent.parent.parent.parent / 'remotion-composer' / 'src' / 'YtNewsStyle01V4.tsx')
        if not engine.is_file():
            self.skipTest('engine file not in this checkout')
        for font in self.module().FONT_FILES:
            self.assertIn('"%s"' % font, engine.read_text())

    def test_missing_lock_is_a_failure_here_too_exit_3(self):
        (self.skill / 'scripts' / 'gates.lock.json').unlink()
        self.assertEqual(3, self.run_pre(), self.out)
        self.assertIn('lock-missing', self.line('FAIL', 'gate-lock'))

    def test_a_tampered_skill_file_or_external_is_exit_3(self):
        (self.skill / 'scripts' / 'lint_beats.py').write_text('import sys; sys.exit(0)\n')
        self.assertEqual(3, self.run_pre(), self.out)
        self.assertIn('file-changed', self.line('FAIL', 'gate-lock'))
        (self.skill / 'scripts' / 'lint_beats.py').write_text(
            (self.repo / '.agents' / 'skills' / self.name / 'scripts' / 'lint_beats.py').read_text())
        (self.repo / 'remotion-composer' / 'src' / 'YtNewsStyle01V4.tsx').write_text('tampered\n')
        self.assertEqual(3, self.run_pre(), self.out)
        self.assertIn('external-changed', self.line('FAIL', 'gate-lock'))

    def test_a_mirror_difference_is_exit_3(self):
        (self.repo / '.agents' / 'skills' / self.name / 'SKILL.md').write_text('changed\n')
        self.assertEqual(3, self.run_pre(), self.out)

    def test_integrity_wins_over_a_missing_dependency(self):
        (self.skill / 'scripts' / 'gates.lock.json').unlink()
        shutil.rmtree(self.repo / 'remotion-composer' / 'public' / 'fonts')
        self.assertEqual(3, self.run_pre(), self.out)
        self.line('FAIL', 'gate-lock')
        self.line('FAIL', 'fonts')

    def test_word_timing_checks_the_venv_the_extractor_and_the_cached_model_without_loading_anything(self):
        env_dir = ENV_DIR[0]
        cases = {
            'venv': ({'KARAOKE_VENV': str(env_dir / 'no-venv')}, 'karaoke venv python missing'),
            'tool': ({'EXTRACT_TIMING': str(env_dir / 'missing.py')}, 'extract_timing.py not found'),
            'cache': ({'HF_HUB_CACHE': str(env_dir / 'empty-hub')}, 'is not in the local HF cache'),
            'model': ({'WHISPER_MODEL': 'someone/other-model'}, 'someone/other-model is not in the local HF cache'),
        }
        for label, (env, text) in cases.items():
            with mock.patch.dict(os.environ, env):
                self.assertEqual(4, self.run_pre(), (label, self.out))
            self.assertIn(text, self.line('FAIL', 'word-timing'), label)
        # an incomplete snapshot (no weights) does not count, exactly as in word_timing.sh
        snap = env_dir / 'hub2' / 'models--mlx-community--whisper-large-v3-mlx' / 'snapshots' / 'x'
        snap.mkdir(parents=True)
        (snap / 'config.json').write_text('{}')
        with mock.patch.dict(os.environ, {'HF_HUB_CACHE': str(env_dir / 'hub2')}):
            self.assertEqual(4, self.run_pre(), self.out)
        self.line('FAIL', 'word-timing')

    def test_music_library_ok_with_one_usable_track(self):
        self.assertEqual(0, self.run_pre(), self.out)
        self.assertEqual('PREFLIGHT ok music-library: 1 approved track(s) usable, first: calm-tech.mp3', self.line('ok', 'music-library'))

    def test_music_library_listed_but_file_missing_or_wrong_is_fail_exit_4(self):
        (self.repo / 'music_library' / LIB_FILE).unlink()
        self.assertEqual(4, self.run_pre(), self.out)
        line = self.line('FAIL', 'music-library')
        self.assertIn('no approved track is usable: calm-tech.mp3: missing', line)
        self.assertIn('library dir %s' % (self.repo / 'music_library'), line)
        (self.repo / 'music_library' / LIB_FILE).write_bytes(b'DIFFERENT BYTES')
        self.assertEqual(4, self.run_pre(), self.out)
        self.assertIn('calm-tech.mp3: sha-mismatch', self.line('FAIL', 'music-library'))

    def test_music_library_dir_override_is_honoured(self):
        other = Path(self.tmp) / 'elsewhere'
        other.mkdir()
        shutil.move(str(self.repo / 'music_library' / LIB_FILE), str(other / LIB_FILE))
        self.assertEqual(4, self.run_pre(), self.out)                       # the default directory no longer has it
        with mock.patch.dict(os.environ, {'MUSIC_LIBRARY_DIR': str(other)}):
            self.assertEqual(0, self.run_pre(), self.out)
            self.line('ok', 'music-library')
        with mock.patch.dict(os.environ, {'MUSIC_LIBRARY_DIR': 'relative/dir'}):
            self.assertEqual(4, self.run_pre(), self.out)
            self.assertIn('must be an absolute path', self.line('FAIL', 'music-library'))

    def test_preflight_takes_no_project_or_deliver(self):
        m = self.module()
        for extra in (['--project', 'projects/p1'], ['--deliver', str(self.deliver)], ['--check']):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                m.main(['--preflight', *extra])
            self.assertEqual(2, cm.exception.code, extra)

    def test_a_real_run_still_needs_project_and_deliver(self):
        m = self.module()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            m.main(['--project', 'projects/p1'])
        self.assertEqual(2, cm.exception.code)

    def test_composer_mismatch_is_reported_like_in_a_real_run(self):
        self.assertEqual(3, self.run_pre('--composer', 'elsewhere'), self.out)
        self.assertIn('composer-mismatch', self.line('FAIL', 'gate-lock'))

    def test_cli_prints_the_documented_lines_and_exits_0(self):
        r = subprocess.run([sys.executable, '-B', str(self.skill / 'scripts' / 'finalize.py'), '--preflight'], capture_output=True, text=True,
                           cwd=self.tmp)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertTrue(r.stdout.splitlines()[-1].startswith('PREFLIGHT PASS (exit 0)'))
        self.assertEqual(12, len([l for l in r.stdout.splitlines() if l.startswith('PREFLIGHT ')]))


class PreflightEmptyLibraryTests(PreflightBase):
    library_tracks = []

    def test_an_empty_manifest_is_fail_exit_4(self):
        self.assertEqual(4, self.run_pre(), self.out)
        self.assertEqual('PREFLIGHT FAIL music-library: music library is empty: no approved track in scripts/music_library.json',
                         self.line('FAIL', 'music-library'))
        self.assertTrue(self.lines()[-1].startswith('PREFLIGHT FAIL (exit 4): music-library'), self.out)

    def test_the_real_run_is_not_blocked_by_it(self):
        self.assertEqual(0, self.run_fin(), self.out)


class PreflightInvalidManifestTests(PreflightBase):
    manifest_text = 'not json at all'

    def test_an_invalid_manifest_is_fail_exit_4(self):
        self.assertEqual(4, self.run_pre(), self.out)
        self.assertIn('music library cannot be used', self.line('FAIL', 'music-library'))
        self.assertIn('not valid JSON', self.line('FAIL', 'music-library'))


class RealRunEnvironmentTests(PreflightBase):
    """The real run starts with the same checks (the same function): the two can never disagree."""

    def real_run(self):
        code = self.run_fin()
        return code, ' | '.join(self.failed()['reasons']) if Path(str(self.deliver) + '.FAILED.json').exists() else ''

    def assertRunStopsBeforeAnyGate(self, name):
        code, reasons = self.real_run()
        self.assertEqual(4, code, self.out)
        self.assertIn('environment: %s:' % name, reasons)
        self.assertEqual([], self.failed()['gates'])
        for stem in STEM.values():
            self.assertFalse(self.ran(stem), stem)
        self.assertNotDelivered()

    def test_missing_fonts_node_modules_whisper_each_stop_the_real_run_and_the_preflight_agrees(self):
        shutil.rmtree(self.repo / 'remotion-composer' / 'public' / 'fonts')
        self.assertEqual(4, self.run_pre(), self.out)
        self.assertRunStopsBeforeAnyGate('fonts')
        write_receipts(self.repo, name=self.name)
        (self.repo / 'remotion-composer' / 'public' / 'fonts').mkdir()
        for f in ('Kanit-Bold.ttf', 'Kanit-ExtraBold.ttf'):
            (self.repo / 'remotion-composer' / 'public' / 'fonts' / f).write_bytes(b'F')
        shutil.rmtree(self.repo / 'remotion-composer' / 'node_modules')
        self.assertEqual(4, self.run_pre(), self.out)
        self.assertRunStopsBeforeAnyGate('composer-node-modules')

    def test_missing_python_module_stops_the_real_run(self):
        m = self.module()
        m.PY_MODULES = ('no_such_module_xyz',)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = m.main(['--project', 'projects/p1', '--deliver', str(self.deliver)])
        self.assertEqual(4, code, buf.getvalue())
        self.assertIn("environment: python-modules:", ' | '.join(self.failed()['reasons']))
        self.assertIn('.venv python', ' | '.join(self.failed()['reasons']))

    def test_missing_whisper_cache_fails_the_preflight_but_never_blocks_a_real_run_or_a_check(self):
        # the one intentional difference: finalize never calls word_timing.sh, the timing / derived gates already vouch for the timing
        with mock.patch.dict(os.environ, {'HF_HUB_CACHE': str(ENV_DIR[0] / 'empty-hub'), 'KARAOKE_VENV': str(ENV_DIR[0] / 'no-venv')}):
            self.assertEqual(4, self.run_pre(), self.out)
            self.line('FAIL', 'word-timing')
            self.assertEqual(0, self.run_fin('--check'), self.out)
            self.assertEqual(0, self.run_fin(), self.out)
            self.assertNotIn('word-timing', self.out)

    def test_the_lock_failure_keeps_exit_3_in_both(self):
        (self.skill / 'scripts' / 'gates.lock.json').unlink()
        self.assertEqual(3, self.run_pre(), self.out)
        self.assertEqual(3, self.run_fin(), self.out)

    def test_ok_environment_passes_in_both(self):
        self.assertEqual(0, self.run_pre(), self.out)
        self.assertEqual(0, self.run_fin(), self.out)


class MusicPresenceTests(FinalizeBase):
    """music-presence: there must be sound in renders/final.mp4 after the voice ends (voEndSec 2.0, duration 4.0 here)."""

    def gate_rec(self, doc=None):
        return self.gate(doc or self.failed(), 'music-presence')

    def new_final(self, audio):
        final_with_audio(self.proj, audio=audio)
        write_receipts(self.repo, name=self.name)          # the mux receipt describes the new file

    def test_the_gate_sits_right_after_loudness(self):
        self.assertEqual(['frames', 'final-av', 'final-pixels', 'loudness', 'music-presence', 'timing'], [g['name'] for g in
                                                                                                          self.module().GATES][:6])

    def test_sound_after_the_voice_passes_and_the_record_the_report_and_the_receipt_carry_the_measurement(self):
        self.assertEqual(0, self.run_fin(), self.out)
        rc = self.receipt()
        g = self.gate_rec(rc)
        self.assertEqual('pass', g['status'])
        self.assertGreater(g['mean_db'], -60.0)
        self.assertEqual([2.5, 3.9], g['window'])
        self.assertEqual(-60.0, g['threshold_db'])
        self.assertRegex(g['detail'], r'^mean -?\d+\.\d dB in 2\.50\u20133\.90 s \(must be above -60\.0 dB\)$')
        self.assertEqual({'mean_db', 'window_start', 'window_end'}, set(rc['music_presence']))
        self.assertEqual((g['mean_db'], 2.5, 3.9), (rc['music_presence']['mean_db'], rc['music_presence']['window_start'], rc['music_presence']['window_end']))
        report = json.loads((self.rdir / 'music-presence.json').read_text())
        self.assertIs(True, report['pass'])
        self.assertEqual(sha(self.fin), report['videoSha256'])

    def test_the_gate_is_part_of_check_mode_and_its_check_json(self):
        self.assertEqual(0, self.run_fin('--check'), self.out)
        doc = json.loads((self.rdir / 'check.json').read_text())
        g = self.gate(doc, 'music-presence')
        self.assertEqual(('pass', 'fresh'), (g['status'], g['kind']))
        self.assertIn('mean_db', g)
        self.assertIn('music-presence', self.out)

    def test_digital_silence_after_the_voice_is_exit_1_with_the_reason(self):
        self.new_final('sine=frequency=440:sample_rate=48000:duration=2,apad=whole_dur=30')           # voice only, a silent bed
        self.assertEqual(1, self.run_fin(), self.out)
        self.assertNotDelivered()
        g = self.gate_rec()
        self.assertEqual('fail', g['status'])
        self.assertRegex(g['reason'], r'^the final file is silent after the voice ends \(mean (-91\.0|-inf) dB in 2\.50\u20133\.90 s, must be above -60\.0 dB\): '
                                       r'the music bed is missing from the mix; run the music step and the mux again$')
        self.assertTrue(any(r.startswith('music-presence: the final file is silent after the voice ends') for r in self.failed()['reasons']))

    def test_quiet_noise_about_minus_70_db_fails_and_about_minus_50_db_passes(self):
        self.new_final('anoisesrc=d=30:a=0.00055:r=48000')
        self.assertEqual(1, self.run_fin(), self.out)
        low = self.gate_rec()['mean_db']
        self.assertLess(low, -60.0)
        self.assertGreater(low, -85.0)
        self.new_final('anoisesrc=d=30:a=0.0055:r=48000')
        self.assertEqual(0, self.run_fin(), self.out)
        high = self.gate_rec(self.receipt())['mean_db']
        self.assertGreater(high, -60.0)
        self.assertLess(high, -40.0)

    def runner(self, vo_end):
        m = self.module()
        args = type('A', (), {'project': str(self.proj), 'composer': 'remotion-composer', 'manifest': None})()
        ctx = m.Ctx(args, self.repo, self.deliver, m.resolve_tools())
        ctx.ep['vo_end'] = vo_end
        gate = next(g for g in m.GATES if g['name'] == 'music-presence')
        report = ctx.reports / 'music-presence.json'
        base = dict(report=ctx.rel(report), inputs={}, command='x')
        return m.runner_music_presence(gate, ctx, base, report, 30, m.gate_env(ctx.tools))

    def test_a_tail_that_is_too_short_is_a_quality_failure_exit_1_with_the_reason(self):
        rec = self.runner(3.0)                         # 1.0 s left after the voice ends
        self.assertEqual(('fail', 1), (rec['status'], rec['cls']))
        self.assertEqual('only 1.00 s of the final file is left after the voice ends (voEndSec 3.0, duration 4.00); at least 1.6 s is needed to '
                         'measure that the music bed is present', rec['reason'])
        rec = self.runner(2.4)                         # window 2.9 .. 3.9 = 1.0 s: enough
        self.assertEqual('pass', rec['status'])

    def test_a_short_tail_through_the_whole_run_is_exit_1(self):
        def patch(m):
            m.MUSIC_PRESENCE_MIN_WINDOW = 2.0          # the same code path with the real fixture (window 1.4 s)
        self.assertEqual(1, self.run_fin(patch=patch), self.out)
        self.assertEqual('fail', self.gate_rec()['status'])
        self.assertIn('is left after the voice ends', self.gate_rec()['reason'])

    def test_a_final_without_an_audio_stream_is_exit_4(self):
        final_with_audio(self.proj, audio=None)
        write_receipts(self.repo, name=self.name)
        self.assertEqual(4, self.run_fin(), self.out)
        g = self.gate_rec()
        self.assertEqual('crashed', g['status'])
        self.assertIn('has no audio stream', g['reason'])

    def fake_ffmpeg(self, body):
        f = Path(self.tmp) / 'fake-ffmpeg'
        f.write_text('#!/bin/sh\n' + body)
        f.chmod(0o755)
        return str(f)

    def with_ffmpeg(self, path):
        def patch(m):
            real = m.resolve_tools
            m.resolve_tools = lambda: dict(real(), ffmpeg=path)
        return patch

    def test_ffmpeg_failing_or_unreadable_output_is_exit_4(self):
        self.assertEqual(4, self.run_fin(patch=self.with_ffmpeg(self.fake_ffmpeg('echo boom >&2\nexit 1\n'))), self.out)
        self.assertEqual('ffmpeg volumedetect exited with code 1', self.gate_rec()['reason'])
        self.assertEqual(4, self.run_fin(patch=self.with_ffmpeg(self.fake_ffmpeg('exit 0\n'))), self.out)
        self.assertEqual('cannot read mean_volume from the ffmpeg volumedetect output', self.gate_rec()['reason'])

    def test_a_timeout_of_the_measurement_is_exit_4(self):
        def patch(m):
            real = m.spawn

            def spawn(cmd, ctx, limit, env):
                if 'volumedetect' in cmd:
                    return {'code': None, 'stdout': b'', 'stderr': '', 'timed_out': True, 'cancelled': False, 'seconds': limit, 'start_ns': 0}
                return real(cmd, ctx, limit, env)
            m.spawn = spawn
        self.assertEqual(4, self.run_fin(patch=patch), self.out)
        g = self.gate_rec()
        self.assertEqual('timeout', g['status'])
        self.assertIn('exceeded the 30s limit', g['reason'])

    def test_exit_precedence_integrity_and_tool_failures_still_win_over_a_music_failure(self):
        self.new_final('sine=frequency=440:sample_rate=48000:duration=2,apad=whole_dur=30')
        self.edit(self.layout_path(), lambda d: d.update(complete=False))            # a class 2 problem as well
        self.assertEqual(2, self.run_fin(), self.out)
        self.assertEqual('fail', self.gate_rec()['status'])

    def test_the_constants_and_the_mux_script_still_agree(self):
        m = self.module()
        mux = (SCRIPTS / 'mux_av.sh').read_text()
        self.assertIn('afade=t=out:st=${VO_END}:d=4.2', mux)
        self.assertEqual(4.2, m.MUX_FADE_OUT_SECONDS)
        self.assertLessEqual(m.MUSIC_PRESENCE_END_AFTER_VO, 0.6 * m.MUX_FADE_OUT_SECONDS)
        self.assertEqual((-60.0, 0.5, 2.5, 1.0), (m.MUSIC_PRESENCE_MIN_MEAN_DB, m.MUSIC_PRESENCE_START_AFTER_VO,
                                                 m.MUSIC_PRESENCE_END_AFTER_VO, m.MUSIC_PRESENCE_MIN_WINDOW))


class MusicBedProvenanceTests(FinalizeBase):
    library_tracks = []          # the online record is accepted only while the approved list is empty

    def sidecar(self):
        return Path(str(self.proj / 'assets' / 'audio' / 'bed.mp3') + '.source.json')

    def test_music_provenance_is_copied_into_the_delivery_receipt(self):
        self.assertEqual(0, self.run_fin(), self.out)
        m = self.receipt()['music']
        self.assertEqual(('pixabay_music', '42', 'Calm Tech', 'https://example.test/42'),
                         (m['provider'], m['track_id'], m['track_title'], m['url']))
        self.assertEqual(sha(self.sidecar()), m['sidecar']['sha256'])
        self.assertEqual(sha(self.proj / 'assets' / 'audio' / 'bed.mp3'), m['bed_sha256'])
        self.assertEqual(m, self.gate(self.receipt(), 'mux')['music'])
        self.assertNotIn('library_file', m)                       # the online record carries no library fields

    def test_bed_without_a_fetch_record_is_refused(self):
        self.sidecar().unlink()
        self.assertEqual(2, self.run_fin())
        g = self.gate(self.failed(), 'mux')
        self.assertEqual('stale', g['status'])
        self.assertIn('music bed has no fetch record', g['reason'])
        self.assertNotDelivered()

    def test_sidecar_sha_must_equal_the_bed(self):
        self.edit(self.sidecar(), lambda d: d.update(sha256='1' * 64))
        self.assertEqual(2, self.run_fin())
        self.assertIn('music bed has no fetch record', self.gate(self.failed(), 'mux')['reason'])

    def test_wrong_schema_or_unreadable_sidecar_is_refused(self):
        self.edit(self.sidecar(), lambda d: d.update(schema='other'))
        self.assertEqual(2, self.run_fin())
        self.sidecar().write_text('{oops')
        self.assertEqual(2, self.run_fin())
        self.assertIn('music bed has no fetch record', self.gate(self.failed(), 'mux')['reason'])

    def test_a_bed_that_changed_after_the_mux_is_refused(self):
        (self.proj / 'assets' / 'audio' / 'bed.mp3').write_bytes(b'ANOTHER SONG')
        self.assertEqual(2, self.run_fin())
        self.assertIn('bed', self.gate(self.failed(), 'mux')['reason'])


class MusicLibraryBedTests(FinalizeBase):
    """provider music_library: the bed must be a track of the SKILL's own scripts/music_library.json."""

    def library_bed(self, bed_bytes=LIB_BYTES, **sidecar_kw):
        write_receipts(self.repo, name=self.name, bed_bytes=bed_bytes, sidecar=lambda bed: library_sidecar(bed, **sidecar_kw))

    def mux_reason(self):
        g = self.gate(self.failed(), 'mux')
        self.assertEqual('stale', g['status'])
        return g['reason']

    def test_a_bed_from_the_approved_library_passes_and_the_receipt_carries_the_reference(self):
        self.library_bed()
        self.assertEqual(0, self.run_fin(), self.out)
        m = self.receipt()['music']
        manifest = self.skill / 'scripts' / 'music_library.json'
        self.assertEqual('music_library', m['provider'])
        self.assertEqual(sha(self.proj / 'assets' / 'audio' / 'bed.mp3'), m['bed_sha256'])
        self.assertEqual((LIB_FILE, 'Calm Tech', 'CC0-1.0', 'https://example.test/calm', 'owner', '2026-11-12'),
                         (m['library_file'], m['track_title'], m['license'], m['origin'], m['approved_by'], m['approved_on']))
        self.assertEqual(sha(manifest), m['manifest_sha256'])                 # the locked manifest in force at delivery
        self.assertEqual('e' * 64, m['sidecar_manifest_sha256'])              # what the fetch step saw (may be older)
        self.assertIsNone(m['track_id'])
        self.assertIsNone(m['url'])
        self.assertEqual(m, self.gate(self.receipt(), 'mux')['music'])

    def test_a_bed_that_is_not_in_the_manifest_is_refused_naming_its_sha(self):
        self.library_bed(bed_bytes=b'SOME OTHER SONG')
        self.assertEqual(2, self.run_fin(), self.out)
        self.assertNotDelivered()
        sha12 = sha(self.proj / 'assets' / 'audio' / 'bed.mp3')[:12]
        self.assertEqual('music bed %s is not in the approved music library (scripts/music_library.json)' % sha12, self.mux_reason())

    def test_sidecar_library_file_or_license_that_differs_from_the_manifest_is_refused(self):
        for kw, text in (({'library_file': 'other.mp3'}, "library_file is 'other.mp3' but the manifest says 'calm-tech.mp3'"),
                         ({'license': 'CC-BY-4.0'}, "license is 'CC-BY-4.0' but the manifest says 'CC0-1.0'")):
            self.library_bed(**kw)
            self.assertEqual(2, self.run_fin(), (kw, self.out))
            reason = self.mux_reason()
            self.assertIn('is not in the approved music library as described by its fetch record', reason)
            self.assertIn(text, reason)
            self.assertIn(sha(self.proj / 'assets' / 'audio' / 'bed.mp3')[:12], reason)

    def test_no_list_outside_the_skill_can_make_a_bed_acceptable(self):
        other_bytes = b'SOME OTHER SONG'
        other = lib_track(sha256=hashlib.sha256(other_bytes).hexdigest(), file='other.mp3')
        decoy_text = json.dumps({'schema': 'yt-news-v4-music-library', 'version': 1, 'tracks': [other]})
        self.library_bed(bed_bytes=other_bytes, library_file='other.mp3', manifest_path=str(Path(self.tmp) / 'decoy.json'))
        sha12 = sha(self.proj / 'assets' / 'audio' / 'bed.mp3')[:12]
        expected = 'music bed %s is not in the approved music library (scripts/music_library.json)' % sha12
        # (a) a list copied into the project, beside the bed and at the project root
        (self.proj / 'assets' / 'audio' / 'music_library.json').write_text(decoy_text)
        (self.proj / 'music_library.json').write_text(decoy_text)
        self.assertEqual(2, self.run_fin(), self.out)
        self.assertEqual(expected, self.mux_reason())
        # (b) MUSIC_LIBRARY_DIR pointing at a folder that holds a different list (and the file it names)
        folder = Path(self.tmp) / 'other-library'
        folder.mkdir()
        (folder / 'music_library.json').write_text(decoy_text)
        (folder / 'other.mp3').write_bytes(other_bytes)
        with mock.patch.dict(os.environ, {'MUSIC_LIBRARY_DIR': str(folder)}):
            self.assertEqual(2, self.run_fin(), self.out)
        self.assertEqual(expected, self.mux_reason())                       # would be exit 0 if any list outside the skill counted
        # and the other way round: a good bed is accepted whatever the sidecar claims about a manifest path
        self.library_bed(manifest_path='/nonexistent/manifest.json')
        self.assertEqual(0, self.run_fin(), self.out)

    def test_an_online_sidecar_is_refused_while_the_approved_list_has_tracks(self):
        write_receipts(self.repo, name=self.name, bed_bytes=b'AN OLD PIXABAY BED', sidecar=online_sidecar)
        self.assertEqual(2, self.run_fin(), self.out)
        self.assertNotDelivered()
        sha12 = sha(self.proj / 'assets' / 'audio' / 'bed.mp3')[:12]
        self.assertEqual('music bed %s: provider pixabay_music is not accepted while the approved music library has tracks '
                         '(scripts/music_library.json); run the music step again' % sha12, self.mux_reason())

    def test_an_online_sidecar_is_refused_even_when_the_bytes_are_an_approved_track(self):
        write_receipts(self.repo, name=self.name, bed_bytes=LIB_BYTES, sidecar=online_sidecar)
        self.assertEqual(2, self.run_fin(), self.out)
        self.assertIn('provider pixabay_music is not accepted while the approved music library has tracks', self.mux_reason())

    def test_a_bed_outside_the_project_audio_directory_is_refused(self):
        write_receipts(self.repo, name=self.name)
        for where in (Path(self.tmp) / 'other-episode' / 'assets' / 'audio', self.repo / 'music_library'):
            where.mkdir(parents=True, exist_ok=True)
            bed = where / 'bed.mp3'
            bed.write_bytes(LIB_BYTES)
            Path(str(bed) + '.source.json').write_text(json.dumps(library_sidecar(bed)))
            self.edit(self.mux_path(), lambda d, b=bed: d['bed'].update(path=str(b), sha256=sha(b)))
            self.assertEqual(2, self.run_fin(), (where, self.out))
            self.assertIn('music bed must be a file under projects/p1/assets/audio/ (got %s)' % bed, self.mux_reason())

    def test_a_bed_that_is_a_symlink_pointing_outside_is_refused(self):
        write_receipts(self.repo, name=self.name)
        outside = Path(self.tmp) / 'outside-bed.mp3'
        outside.write_bytes(LIB_BYTES)
        bed = self.proj / 'assets' / 'audio' / 'bed.mp3'
        bed.unlink()
        os.symlink(outside, bed)
        self.assertEqual(2, self.run_fin(), self.out)
        self.assertIn('music bed must be a file under projects/p1/assets/audio/ (got %s)' % bed, self.mux_reason())

    def test_the_bed_in_the_project_audio_directory_is_accepted(self):
        self.assertEqual(0, self.run_fin(), self.out)
        self.assertIn('assets/audio/bed.mp3', self.receipt()['music']['sidecar']['path'])

    def test_an_unknown_or_missing_provider_fails_closed(self):
        for provider in ('spotify', 'pixabay', '', None):
            write_receipts(self.repo, name=self.name, sidecar=lambda bed, p=provider: dict(library_sidecar(bed), provider=p))
            self.assertEqual(2, self.run_fin(), (provider, self.out))
            self.assertIn('has an unknown provider %r' % (provider,), self.mux_reason())
            self.assertIn('expected pixabay_music or music_library', self.mux_reason())

    def test_a_valid_library_bed_still_delivers_when_the_library_directory_is_empty_or_gone(self):
        self.library_bed()
        shutil.rmtree(self.repo / 'music_library')                  # the library file is not needed at delivery time
        self.assertEqual(0, self.run_fin('--check'), self.out)
        self.assertEqual(0, self.run_fin(), self.out)
        (self.repo / 'music_library').mkdir()
        self.deliver.unlink()
        Path(str(self.deliver) + '.receipt.json').unlink()
        self.assertEqual(0, self.run_fin(), self.out)
        self.assertNotIn('music-library', self.out)                 # the check is preflight-only


class MusicLibraryInvalidManifestTests(FinalizeBase):
    manifest_text = '{"not": "a manifest"'

    def test_an_invalid_manifest_fails_the_music_check_for_every_provider(self):
        bed = self.proj / 'assets' / 'audio' / 'bed.mp3'
        for label, kw in (('library', {'bed_bytes': LIB_BYTES, 'sidecar': library_sidecar}),
                          ('online', {'bed_bytes': b'AN OLD PIXABAY BED', 'sidecar': online_sidecar})):
            write_receipts(self.repo, name=self.name, **kw)
            self.assertEqual(2, self.run_fin(), (label, self.out))
            self.assertNotDelivered()
            reason = self.gate(self.failed(), 'mux')['reason']
            self.assertIn('music bed %s is not in the approved music library: scripts/music_library.json cannot be used' % sha(bed)[:12],
                          reason, label)
            self.assertIn('not valid JSON', reason, label)


class MusicLibraryEmptyManifestRealRunTests(FinalizeBase):
    library_tracks = []

    def test_an_empty_library_does_not_stop_a_real_run_or_a_check(self):
        self.assertEqual(0, self.run_fin('--check'), self.out)
        self.assertEqual(0, self.run_fin(), self.out)
        self.assertEqual('pixabay_music', self.receipt()['music']['provider'])          # an empty list accepts the online record
        self.assertNotIn('music-library', self.out)

    def test_an_empty_manifest_refuses_a_library_bed(self):
        write_receipts(self.repo, name=self.name, bed_bytes=LIB_BYTES, sidecar=lambda bed: library_sidecar(bed))
        self.assertEqual(2, self.run_fin(), self.out)
        self.assertIn('is not in the approved music library (scripts/music_library.json)', self.gate(self.failed(), 'mux')['reason'])


class ComposerPathTests(FinalizeBase):
    def test_composer_must_be_the_repo_remotion_composer(self):
        shutil.copytree(self.repo / 'remotion-composer', self.repo / 'other-composer')
        self.assertEqual(3, self.run_fin('--composer', 'other-composer'))
        self.assertTrue(any('composer-mismatch' in p for p in self.failed()['integrity_problems']))
        for gates_ran in STEM.values():
            self.assertFalse(self.ran(gates_ran), gates_ran)
        self.assertEqual(3, self.run_fin('--composer', '/tmp'))
        self.deliver.parent.mkdir(exist_ok=True)

    def test_equivalent_spellings_of_the_default_are_accepted(self):
        self.assertEqual(0, self.run_fin('--composer', './remotion-composer/'), self.out)


class ToolResolutionTests(FinalizeBase):
    def test_tools_are_absolute_realpaths_recorded_in_the_receipt_and_the_path_is_minimal(self):
        self.assertEqual(0, self.run_fin(), self.out)
        tools = self.receipt()['tools']
        for name in ('node', 'ffmpeg', 'ffprobe', 'git'):
            self.assertEqual(os.path.realpath(shutil.which(name)), tools[name]['path'], name)
            self.assertTrue(tools[name]['version'], name)
        self.assertIn('swift', tools)
        self.assertEqual(os.path.realpath(sys.executable), tools['python']['path'])
        node_cmd = self.gate(self.receipt(), 'schema')['command']
        self.assertTrue(node_cmd.startswith(tools['node']['path']), node_cmd)
        env = json.loads((self.repo / '.stub_logs' / 'lint_beats.env.json').read_text())
        m = self.module()
        self.assertEqual(m.tool_path_env(m.resolve_tools()), env['PATH'])
        self.assertTrue(env['PATH'].endswith(':/usr/bin:/bin'))

    def test_git_environment_of_the_caller_is_ignored(self):
        bogus = str(Path(self.tmp) / 'nonexistent-git-dir')
        with mock.patch.dict(os.environ, {'GIT_DIR': bogus, 'GIT_INDEX_FILE': bogus + '/index', 'GIT_WORK_TREE': bogus,
                                          'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'core.fsmonitor', 'GIT_CONFIG_VALUE_0': 'true'}):
            self.assertEqual(0, self.run_fin(), self.out)
        env = json.loads((self.repo / '.stub_logs' / 'lint_beats.env.json').read_text())
        self.assertEqual([], [k for k in env['GIT'] if k.startswith('GIT_')])


class RunLockTests2(FinalizeBase):
    def test_lock_of_a_killed_run_does_not_block_the_retry(self):
        child = subprocess.Popen([sys.executable, '-c', 'pass'])
        child.wait()                                         # a pid that is certainly dead now
        self.rdir.mkdir(parents=True, exist_ok=True)
        (self.rdir / '.finalize.lock').write_text(json.dumps({'pid': child.pid, 'started_at': 'x'}))
        self.assertEqual(0, self.run_fin(), self.out)
        self.assertFalse((self.rdir / '.finalize.lock').exists())

    def test_lock_of_a_live_run_is_honoured(self):
        child = subprocess.Popen(['sleep', '30'])
        self.addCleanup(child.kill)
        self.rdir.mkdir(parents=True, exist_ok=True)
        (self.rdir / '.finalize.lock').write_text(json.dumps({'pid': child.pid, 'started_at': 'x'}))
        self.assertEqual(2, self.run_fin())
        self.assertIn('another finalize run', self.out)
        self.assertTrue((self.rdir / '.finalize.lock').exists())

    def test_unreadable_fresh_lock_is_treated_as_a_run_in_progress_and_an_old_one_as_stale(self):
        self.rdir.mkdir(parents=True, exist_ok=True)
        lock = self.rdir / '.finalize.lock'
        lock.write_text('')
        self.assertEqual(2, self.run_fin())
        old = time.time() - 60
        os.utime(lock, (old, old))
        self.assertEqual(0, self.run_fin(), self.out)

    def test_sigterm_starts_no_queued_gate_and_leaves_no_half_written_files(self):
        sleepers = ('frame_checks', 'measure_loudness', 'timing_check', 'lint_beats', 'lint_captions', 'lint_content')
        self.behavior(**{n: {'sleep': 25} for n in sleepers})
        self.deliver.parent.mkdir(parents=True)
        p = subprocess.Popen([sys.executable, str(self.skill / 'scripts' / 'finalize.py'), '--project', 'projects/p1',
                              '--deliver', str(self.deliver)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        logs = self.repo / '.stub_logs'
        want = [logs / (n + '.pid') for n in ('frame_checks', 'measure_loudness', 'timing_check')]
        for _ in range(150):
            if all(w.exists() for w in want):
                break
            time.sleep(0.1)
        self.assertTrue(all(w.exists() for w in want), 'the three running gates did not start')
        pids = [int(w.read_text()) for w in want]
        time.sleep(0.3)
        p.send_signal(signal.SIGTERM)
        out, err = p.communicate(timeout=30)
        self.assertEqual(4, p.returncode, out + err)
        time.sleep(1.0)                                      # a gate that was queued would have started by now
        for stem in ('lint_beats', 'lint_captions', 'lint_content'):
            self.assertFalse((logs / (stem + '.argv.json')).exists(), 'queued gate started after cancellation: ' + stem)
        for pid in pids:
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        self.assertFalse((self.rdir / '.finalize.lock').exists())
        self.assertFalse(self.deliver.exists())
        self.assertFalse(Path(str(self.deliver) + '.partial').exists())
        self.assertFalse(Path(str(self.deliver) + '.receipt.json').exists())
        self.assertIn('terminated', ' '.join(self.failed()['reasons']))


class DeliveryOrderAndPathTests(FinalizeBase):
    def test_receipt_is_in_place_before_the_mp4_and_the_mp4_is_renamed_last(self):
        real_replace = os.replace
        seen = []

        def spy(src, dst, *a, **k):
            seen.append(Path(dst).name)
            return real_replace(src, dst, *a, **k)
        with mock.patch('os.replace', side_effect=spy):
            self.assertEqual(0, self.run_fin(), self.out)
        order = [n for n in seen if n in ('episode.mp4', 'episode.mp4.receipt.json')]
        self.assertEqual(['episode.mp4.receipt.json', 'episode.mp4'], order)

    def test_failure_of_the_last_rename_leaves_neither_mp4_nor_receipt(self):
        real_replace = os.replace

        def failing(src, dst, *a, **k):
            if str(dst) == str(self.deliver):
                raise OSError('disk full (simulated)')
            return real_replace(src, dst, *a, **k)
        with mock.patch('os.replace', side_effect=failing):
            self.assertEqual(2, self.run_fin(), self.out)
        self.assertNotDelivered()

    def test_deliver_path_that_resolves_to_an_input_is_refused_and_the_input_is_untouched(self):
        before = {p: sha(p) for p in (self.fin, self.proj / 'renders' / 'visual.mp4', self.render_path(), self.mux_path())}
        for target in (self.fin, self.proj / 'renders' / 'visual.mp4'):
            self.assertEqual(2, self.run_fin(deliver=target), self.out)
            self.assertIn('input', ' '.join(self.failed_at(target)['reasons']))
        link = self.repo / 'out' / 'link.mp4'
        link.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(self.fin, link)
        self.assertEqual(2, self.run_fin(deliver=link), self.out)
        self.assertEqual(before, {p: sha(p) for p in before})
        self.assertTrue(self.fin.is_file() and not self.fin.is_symlink())

    def failed_at(self, target):
        return json.loads(Path(str(target) + '.FAILED.json').read_text())

    def test_deliver_inside_an_input_directory_is_refused(self):
        inside_media = self.repo / 'remotion-composer' / 'public' / 'ep1' / 'broll' / 'out.mp4'
        self.assertEqual(2, self.run_fin(deliver=inside_media), self.out)
        self.assertIn('input directory', ' '.join(self.failed_at(inside_media)['reasons']))

    def test_check_mode_outside_a_repo_never_writes_relative_to_the_cwd(self):
        shutil.rmtree(self.repo / '.git')
        cwd = Path(self.tmp) / 'cwd'
        cwd.mkdir()
        r = subprocess.run([sys.executable, str(self.skill / 'scripts' / 'finalize.py'), '--project', 'projects/p1', '--deliver',
                            str(self.deliver), '--check'], capture_output=True, text=True, cwd=cwd)
        self.assertEqual(3, r.returncode, r.stdout + r.stderr)
        self.assertEqual([], list(cwd.iterdir()))


class SecondDestinationTests(FinalizeBase):
    """SKILL.md: after the first `finalize.py --project P --deliver A` exits 0, an extra destination B is delivered by running
    finalize again with `--deliver B` (never cp).  The first delivery must stay exactly as it was."""

    def setUp(self):
        super().setUp()
        self.dest_b = self.repo / 'out-b' / 'second' / 'episode-b.mp4'

    def side_files(self, path):
        return sorted(p.name for p in Path(path).parent.iterdir() if p.name.startswith(Path(path).name))

    def snapshot_a(self):
        return {'mp4': self.deliver.read_bytes(), 'receipt': Path(str(self.deliver) + '.receipt.json').read_bytes(),
                'files': self.side_files(self.deliver)}

    def test_a_second_run_to_another_destination_delivers_b_and_leaves_a_untouched(self):
        self.assertEqual(0, self.run_fin(), self.out)                                       # (1) run to A
        self.assertTrue(self.deliver.is_file())
        self.assertTrue(Path(str(self.deliver) + '.receipt.json').is_file())
        a = self.snapshot_a()
        self.assertEqual(['episode.mp4', 'episode.mp4.receipt.json'], a['files'])
        self.assertEqual(0, self.run_fin(deliver=self.dest_b), self.out)                    # (2) same project, --deliver B
        receipt_b = Path(str(self.dest_b) + '.receipt.json')
        self.assertTrue(self.dest_b.is_file())
        self.assertTrue(receipt_b.is_file())
        self.assertEqual(a['mp4'], self.dest_b.read_bytes())                                # same bytes as A
        self.assertEqual(self.fin.read_bytes(), self.dest_b.read_bytes())
        self.assertEqual(a['mp4'], self.deliver.read_bytes())                              # A and its receipt are byte-identical
        self.assertEqual(a['receipt'], Path(str(self.deliver) + '.receipt.json').read_bytes())
        self.assertEqual(a['files'], self.side_files(self.deliver))                         # no .previous, no .FAILED.json beside A
        self.assertEqual(['episode-b.mp4', 'episode-b.mp4.receipt.json'], self.side_files(self.dest_b))
        rb = json.loads(receipt_b.read_text())
        self.assertEqual(str(self.dest_b), rb['delivered']['path'])                         # B's receipt describes B
        self.assertEqual(sha(self.dest_b), rb['delivered']['sha256'])
        self.assertEqual(json.loads(Path(str(self.deliver) + '.receipt.json').read_text())['delivered']['sha256'], rb['delivered']['sha256'])

    def test_a_failing_second_run_writes_failed_json_at_b_only_and_leaves_a_untouched(self):
        self.assertEqual(0, self.run_fin(), self.out)
        a = self.snapshot_a()
        self.behavior(lint_beats={'exit': 1, 'pass': False})                                # an existing way to force a gate failure
        code = self.run_fin(deliver=self.dest_b)                                            # (3) the second run fails
        self.assertNotEqual(0, code, self.out)
        self.assertEqual(1, code)
        failed_b = Path(str(self.dest_b) + '.FAILED.json')
        self.assertTrue(failed_b.is_file())
        self.assertEqual(1, json.loads(failed_b.read_text())['exit_code'])
        self.assertFalse(self.dest_b.exists())                                              # nothing at B
        self.assertFalse(Path(str(self.dest_b) + '.receipt.json').exists())
        self.assertEqual(a['mp4'], self.deliver.read_bytes())                              # A and its receipt untouched
        self.assertEqual(a['receipt'], Path(str(self.deliver) + '.receipt.json').read_bytes())
        self.assertEqual(a['files'], self.side_files(self.deliver))

    def test_after_the_failed_second_run_the_next_run_to_b_can_still_deliver(self):
        self.assertEqual(0, self.run_fin(), self.out)
        self.behavior(lint_beats={'exit': 1, 'pass': False})
        self.assertEqual(1, self.run_fin(deliver=self.dest_b), self.out)
        self.behavior(lint_beats={'exit': 0, 'pass': True})
        self.assertEqual(0, self.run_fin(deliver=self.dest_b), self.out)
        self.assertFalse(Path(str(self.dest_b) + '.FAILED.json').exists())                  # the stale failure is cleared by the success
        self.assertEqual(self.deliver.read_bytes(), self.dest_b.read_bytes())


class LockCoverageAndGitIndependenceTests(FinalizeBase):
    def commit_all(self, msg):
        sh(self.repo, 'git', 'add', '-A')
        sh(self.repo, 'git', 'commit', '-q', '--allow-empty', '-m', msg)

    def test_gates_lock_write_without_external_locks_the_required_files_and_finalize_accepts_it(self):
        lock = self.skill / 'scripts' / 'gates.lock.json'
        lock.unlink()
        r = subprocess.run([sys.executable, '-B', str(self.skill / 'scripts' / 'gates_lock.py'), 'write', '--skill-dir', str(self.skill),
                            '--repo-root', str(self.repo), '--out', str(lock)], capture_output=True, text=True)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertEqual(EXTERNAL_PATHS, list(json.loads(lock.read_text())['external']))
        shutil.copy(lock, self.repo / '.agents' / 'skills' / self.name / 'scripts' / 'gates.lock.json')
        self.commit_all('regenerated lock')
        self.assertEqual(0, self.run_fin(), self.out)

    def test_an_unrelated_commit_moves_head_without_touching_the_lock_or_the_receipt_validity(self):
        head0 = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=self.repo, capture_output=True, text=True).stdout.strip()
        (self.repo / 'README.md').write_text('unrelated\n')
        self.commit_all('unrelated')
        self.assertEqual(0, self.run_fin(), self.out)
        rc = self.receipt()
        self.assertNotEqual(head0, rc['git_head'])             # recorded for information only
        self.assertEqual(sha(self.skill / 'scripts' / 'gates.lock.json'), rc['lock_sha256'])

    def test_unrelated_dirty_and_untracked_files_do_not_matter(self):
        (self.repo / 'README.md').write_text('tracked\n')
        self.commit_all('readme')
        (self.repo / 'README.md').write_text('modified, uncommitted\n')
        (self.repo / 'remotion-composer' / 'src' / 'Root.tsx').write_text(ROOT_SRC + '// uncommitted\n')   # tracked, not locked
        (self.repo / 'notes.txt').write_text('untracked\n')
        (self.repo / 'other-skill').mkdir()
        (self.repo / 'other-skill' / 'x.py').write_text('untracked\n')
        self.assertEqual(0, self.run_fin(), self.out)

    def test_KNOWN_LIMITATION_gate_file_tampered_lock_regenerated_and_committed_is_not_detectable_locally(self):
        """DOCUMENTED LIMITATION, not a desired pass.  An agent that edits a gate file, regenerates gates.lock.json and
        commits both leaves a tree that is internally consistent, so finalize (which only compares the tree with its own lock
        and with git HEAD) cannot tell.  The consumer of the delivery receipt MUST compare the receipt's `lock_sha256`
        and `finalize_sha256` with the values pinned out of band (`git_head` is informational only: it moves with
        unrelated commits, lead decision 2026-11-12); this test asserts the CURRENT behaviour so that nobody mistakes the
        local check for that protection."""
        original = (self.skill / 'scripts' / 'lint_beats.py').read_text()
        orig_lock = sha(self.skill / 'scripts' / 'gates.lock.json')
        for d in (self.skill, self.repo / '.agents' / 'skills' / self.name):
            (d / 'scripts' / 'lint_beats.py').write_text(original + '\n# tampered\n')
        sh(self.repo, 'git', 'add', '-A')
        lock = _gl.lock_bytes(_gl.build_lock(self.skill, self.repo, [], required=EXTERNAL_PATHS))
        for d in (self.skill, self.repo / '.agents' / 'skills' / self.name):
            (d / 'scripts' / 'gates.lock.json').write_bytes(lock)
        self.commit_all('tamper + regenerate lock')
        self.assertEqual(2, self.run_fin(), self.out)          # the layout / render receipts are bound to the OLD lock: re-run them ...
        write_receipts(self.repo)                              # ... (what re-running layout + render under the new lock produces)
        self.assertEqual(0, self.run_fin(), self.out)          # CURRENT behaviour: delivered
        rc = self.receipt()
        self.assertNotEqual(orig_lock, rc['lock_sha256'])      # ... but the receipt shows the lock changed: pin and compare it
        self.assertEqual(sha(self.skill / 'scripts' / 'finalize.py'), rc['finalize_sha256'])
        self.assertTrue(rc['git_head'] and rc['skill_tree'])


@unittest.skipUnless(HAVE_FFMPEG, 'ffmpeg required')
class MuxReceiptTests(unittest.TestCase):
    def test_mux_av_writes_receipt_with_hashes(self):
        mux = SCRIPTS / 'mux_av.sh'
        tmp = Path(tempfile.mkdtemp(prefix='mux-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=320x240:r=25:d=6', '-pix_fmt', 'yuv420p', str(tmp / 'visual.mp4'))
        ffmpeg('-f', 'lavfi', '-i', 'anoisesrc=d=6:c=pink:a=0.3:r=48000', str(tmp / 'vo.wav'))
        ffmpeg('-f', 'lavfi', '-i', 'anoisesrc=d=3:c=brown:a=0.2:r=48000', str(tmp / 'bed.wav'))
        out = tmp / 'final.mp4'
        Path(str(out) + '.mux.json').write_text('{"stale": true}')
        r = subprocess.run(['bash', str(mux), str(tmp / 'visual.mp4'), str(tmp / 'vo.wav'), str(tmp / 'bed.wav'), str(out), '6', '5'],
                           capture_output=True, text=True, cwd=tmp)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        rc = json.loads(Path(str(out) + '.mux.json').read_text())
        self.assertEqual('yt-news-v4-mux-receipt', rc['schema'])
        self.assertEqual(1, rc['version'])
        for key, f in (('visual', 'visual.mp4'), ('avatar', 'vo.wav'), ('bed', 'bed.wav'), ('final', 'final.mp4')):
            self.assertEqual(str((tmp / f).resolve()), str(Path(rc[key]['path']).resolve()))
            self.assertEqual(sha(tmp / f), rc[key]['sha256'], key)
        self.assertIn('created_at', rc)
        self.assertIn('MUX_DONE', r.stdout)

    def test_failed_mux_leaves_no_receipt(self):
        mux = SCRIPTS / 'mux_av.sh'
        tmp = Path(tempfile.mkdtemp(prefix='mux-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        out = tmp / 'final.mp4'
        Path(str(out) + '.mux.json').write_text('{"stale": true}')
        r = subprocess.run(['bash', str(mux), str(tmp / 'nope.mp4'), str(tmp / 'nope.wav'), str(tmp / 'nope2.wav'), str(out), '6', '5'],
                           capture_output=True, text=True, cwd=tmp)
        self.assertNotEqual(0, r.returncode)
        self.assertFalse(Path(str(out) + '.mux.json').exists())


if __name__ == '__main__':
    unittest.main()
