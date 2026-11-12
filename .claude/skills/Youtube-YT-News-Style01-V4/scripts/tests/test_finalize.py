import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
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

JS_INTEGRITY = JS_HEAD.replace('__NAME__', 'gate_integrity') + r'''
const ok = b.ok !== false;
console.log(JSON.stringify({ ok, issues: ok ? [] : [{ id: 'engine-drift', message: 'engine differs from reference' }], warnings: [] }));
process.exit(b.exit !== undefined ? b.exit : (ok ? 0 : 3));
'''

# faithful copy of the real qc_manifest.mjs canonicalJSON / manifestHash (fixture; the real file is not available here)
JS_MANIFEST = r'''
import { createHash } from 'node:crypto';
export function canonicalJSON(value) {
  if (value === null || typeof value !== 'object') {
    const text = JSON.stringify(value);
    if (text === undefined) throw new TypeError('canonicalJSON: unsupported value ' + String(value));
    return text;
  }
  if (Array.isArray(value)) return '[' + value.map(v => (v === undefined ? 'null' : canonicalJSON(v))).join(',') + ']';
  const keys = Object.keys(value).filter(k => value[k] !== undefined).sort();
  return '{' + keys.map(k => JSON.stringify(k) + ':' + canonicalJSON(value[k])).join(',') + '}';
}
export function manifestHash(manifest) {
  return createHash('sha256').update(canonicalJSON(manifest)).digest('hex');
}
'''

STUB_FILES = {'lint_beats.py': PY_STUB, 'lint_content.py': PY_STUB, 'lint_captions.py': PY_STUB,
              'frame_checks.py': PY_STUB, 'measure_loudness.py': PY_STUB, 'qc_final_pixels.mjs': JS_PIXELS,
              'episode_schema.mjs': JS_SCHEMA, 'gate_integrity.mjs': JS_INTEGRITY, 'qc_manifest.mjs': JS_MANIFEST}
ALL_GATES = ['frames', 'final-av', 'final-pixels', 'loudness', 'schema', 'gate-integrity', 'beats', 'content', 'captions']
ALL_RECORDS = ALL_GATES + ['layout', 'render', 'mux', 'final-duration', 'relevance']
STEM = {'beats': 'lint_beats', 'content': 'lint_content', 'captions': 'lint_captions', 'frames': 'frame_checks',
        'loudness': 'measure_loudness', 'final-pixels': 'qc_final_pixels', 'schema': 'episode_schema',
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


def setUpModule():
    global PROJECT_TEMPLATE
    if not HAVE_FFMPEG:
        return
    t = Path(tempfile.mkdtemp(prefix='finalize-proj-'))
    p = t / 'p1'
    for d in ('artifacts', 'assets/broll', 'assets/ytsource', 'renders', 'qc/finalize'):
        (p / d).mkdir(parents=True)
    (p / 'artifacts' / 'episode.json').write_text(json.dumps({
        'schema': 'yt-news-v4-episode/1', 'assetDir': 'ep1', 'avatarFile': 'avatar.mp4', 'fps': 25, 'voEndSec': 2.0,
        'totalDurationSec': 3.0, 'beats': [{'t': 0}]}))
    (p / 'artifacts' / 'caption-joined.json').write_text(json.dumps({'pages': []}))
    for n in ('script.txt', 'words_by_line.txt', 'source_script.txt'):
        (p / 'artifacts' / n).write_text('hello\n')
    (p / 'artifacts' / 'line_starts.json').write_text('[0]')
    (p / 'artifacts' / '_cuts.json').write_text('[]')
    (p / 'assets' / 'broll' / 'a.mp4').write_bytes(b'x')
    (p / 'assets' / 'ytsource' / 'transcript.txt').write_text('transcript\n')
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=320x240:r=25:d=2', '-pix_fmt', 'yuv420p', str(p / 'renders' / 'visual.mp4'))
    # final = 2 s of motion + the V4 end card (1 s solid dark static frame) -> exactly totalDurationSec 3.0
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=320x240:r=25:d=2', '-f', 'lavfi', '-i', 'color=c=0x101018:s=320x240:r=25:d=1',
           '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0', '-pix_fmt', 'yuv420p', str(p / 'renders' / 'final.mp4'))
    PROJECT_TEMPLATE = t


def tearDownModule():
    if PROJECT_TEMPLATE:
        shutil.rmtree(PROJECT_TEMPLATE, ignore_errors=True)


def write_receipts(repo, run_id=RUN_ID):
    """Layout report v3 + run manifest, render receipt and mux receipt in the shapes the real writers produce."""
    proj = repo / 'projects' / 'p1'
    lock = repo / '.claude' / 'skills' / NAME / 'scripts' / 'gates.lock.json'
    ep, cap = proj / 'artifacts' / 'episode.json', proj / 'artifacts' / 'caption-joined.json'
    vis, fin = proj / 'renders' / 'visual.mp4', proj / 'renders' / 'final.mp4'
    avatar = repo / 'remotion-composer' / 'public' / 'ep1' / 'avatar.mp4'
    rd = proj / 'qc' / 'layout' / 'runs' / run_id
    rd.mkdir(parents=True, exist_ok=True)
    manifest = {'schema': 'yt-news-v4-run-manifest', 'version': 1, 'runId': run_id, 'compositionId': COMP,
                'sourceHashes': {'episode.json': sha(ep), 'captions.json': sha(cap), 'src/Root.tsx': 'a' * 64,
                                 'scripts/gates.lock.json': sha(lock)},
                'mediaDigest': {'method': 'sha256-per-file-v1', 'assetDir': 'ep1', 'digest': 'b' * 64, 'files': 3, 'bytes': 99},
                'fontsDigest': {'method': 'sha256-per-file-v1', 'digest': 'c' * 64}, 'bundleKey': 'k-1',
                'planSha256': 'd' * 64, 'frames': [0, 25, 50], 'thresholdsSha256': 'e' * 64}
    (rd / 'run-manifest.json').write_text(json.dumps(manifest, indent=2))
    mhash = hashlib.sha256(canon(manifest).encode()).hexdigest()
    report = {'schema': 'yt-news-layout-report', 'version': 3, 'compositionId': COMP, 'runId': run_id,
              'startedAt': '2026-11-12T00:00:00Z', 'status': 'finished', 'manifestHash': mhash,
              'manifestPath': str(rd / 'run-manifest.json'), 'planSha256': 'd' * 64,
              'fullPlanFrames': [0, 25, 50], 'fullPlanCount': 3, 'requestedFrames': [0, 25, 50], 'requestedCount': 3,
              'measuredCount': 3, 'reusedFrames': 0, 'resumed': False, 'invocations': [], 'wallSecondsTotal': 1.5,
              'warnings': [], 'manifestConsistent': True, 'complete': True, 'diagnosticPass': True, 'pass': True,
              'issues': [], 'actualVideo': True}
    (proj / 'qc' / 'layout' / 'report.json').write_text(json.dumps(report, indent=2))
    receipt = {'schema': 'yt-news-v4-render-receipt', 'schemaVersion': 1, 'compositionId': COMP, 'renderId': 'render-1',
               'draft': False, 'outputPath': str(vis), 'outputFileName': 'visual.mp4', 'outputSha256': sha(vis),
               'outputBytes': vis.stat().st_size, 'frameCount': 50, 'durationInFrames': 50, 'fps': 25, 'width': 1920,
               'height': 1080, 'codec': 'h264', 'pixelFormat': 'yuv420p', 'hasAudio': False,
               'episodeJsonSha256': sha(ep), 'captionsJsonSha256': sha(cap), 'engineSha256': 'a' * 64,
               'engineReferenceSha256': 'a' * 64, 'rootTsxSha256': 'a' * 64, 'indexTsxSha256': 'a' * 64,
               'fontsDigest': 'c' * 64, 'mediaDigest': 'b' * 64, 'mediaDigestMethod': 'sha256-per-file-v1',
               'gatesLockSha256': sha(lock), 'gateReportPath': str(proj / 'qc' / 'layout' / 'report.json'),
               'gateReportSha256': sha(proj / 'qc' / 'layout' / 'report.json'), 'gateRunId': run_id,
               'gateManifestHash': mhash, 'gateCheckedAtStart': 't0', 'gateCheckedAtConcat': 't1', 'segments': [],
               'tools': {}, 'startedAt': 't0', 'finishedAt': 't1', 'wallSecondsTotal': 3, 'invocations': []}
    Path(str(vis) + '.receipt.json').write_text(json.dumps(receipt, indent=2))
    mux = {'schema': 'yt-news-v4-mux-receipt', 'version': 1, 'visual': {'path': str(vis), 'sha256': sha(vis)},
           'avatar': {'path': str(avatar), 'sha256': sha(avatar)}, 'bed': {'path': 'bed.wav', 'sha256': 'f' * 64},
           'final': {'path': str(fin), 'sha256': sha(fin)}, 'created_at': 't'}
    Path(str(fin) + '.mux.json').write_text(json.dumps(mux, indent=2))
    return mhash


def make_repo(tmp, omit=(), skill_files=None):
    repo = Path(tmp) / 'repo'
    skill = repo / '.claude' / 'skills' / NAME
    (skill / 'scripts' / 'tests').mkdir(parents=True)
    for f in ('finalize.py', 'gates_lock.py', 'final_av_checks.py'):
        shutil.copy(SCRIPTS / f, skill / 'scripts' / f)
    (skill / 'scripts' / 'qc_thresholds.json').write_text('{}')
    (skill / 'scripts' / 'tests' / 'fixture_test.py').write_text('# locked test file\n')
    (skill / 'SKILL.md').write_text('fake\n')
    for name, body in STUB_FILES.items():
        if name not in omit:
            (skill / 'scripts' / name).write_text(body)
    for rel, body in (skill_files or {}).items():
        (skill / rel).write_text(body)
    sh(tmp, 'git', 'init', '-q', str(repo))
    sh(repo, 'git', 'config', 'user.email', 't@t')
    sh(repo, 'git', 'config', 'user.name', 't')
    sh(repo, 'git', 'config', 'commit.gpgsign', 'false')
    (repo / '.gitignore').write_text('__pycache__/\nprojects/\nout/\n.stub_*\nremotion-composer/\n')
    (skill / 'scripts' / 'gates.lock.json').write_bytes(_gl.lock_bytes(_gl.build_lock(skill, repo, [])))
    shutil.copytree(skill, repo / '.agents' / 'skills' / NAME)
    sh(repo, 'git', 'add', '-A')
    sh(repo, 'git', 'commit', '-q', '-m', 'init')
    shutil.copytree(PROJECT_TEMPLATE / 'p1', repo / 'projects' / 'p1')
    (repo / 'remotion-composer' / 'public' / 'ep1').mkdir(parents=True)
    (repo / 'remotion-composer' / 'public' / 'ep1' / 'avatar.mp4').write_bytes(b'AVATAR')
    write_receipts(repo)
    return repo


_counter = [0]


@unittest.skipUnless(HAVE_FFMPEG and HAVE_NODE, 'ffmpeg and node required')
class FinalizeBase(unittest.TestCase):
    omit = ()

    def setUp(self):
        self.tmp = str(Path(tempfile.mkdtemp(prefix='finalize-')).resolve())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = make_repo(self.tmp, self.omit)
        self.proj = self.repo / 'projects' / 'p1'
        self.rdir = self.proj / 'qc' / 'finalize'
        self.deliver = self.repo / 'out' / 'episode.mp4'
        self.skill = self.repo / '.claude' / 'skills' / NAME
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
        self.assertEqual([str(self.proj / 'assets' / 'broll')], [frames[i + 1] for i, x in enumerate(frames) if x == '--media-root'])
        self.assertEqual(['validate', ep, '--captions', cap, '--json'], self.argv_of('episode_schema'))
        self.assertEqual([str(self.repo / 'remotion-composer'), '--json', '--skill-dir', str(self.skill)],
                         self.argv_of('gate_integrity'))
        # voEndSec is passed to the end-card aware gates; --allow-draft is never passed; out-dir is positional
        px = self.argv_of('qc_final_pixels')
        self.assertEqual([str(self.fin), str(self.rdir / 'final-pixels'), '--vo-end', '2.0'], px)
        self.assertFalse(any('allow-draft' in a for g in self.module().GATES for a in g['args']))
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
        self.assertNotIn('os.environ.get', src)
        self.assertNotIn('getenv', src)

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

    def test_total_budget_exhausted(self):
        def patch(m):
            m.TOTAL_BUDGET_SEC = 0
        self.assertEqual(4, self.run_fin(patch=patch))
        self.assertTrue(all(g['status'] == 'timeout' for g in self.failed()['gates'] if g['kind'] == 'fresh'))

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

    def test_gate_integrity_refusal_is_a_quality_failure_not_finalize_3(self):
        self.behavior(gate_integrity={'ok': False})
        self.assertEqual(1, self.run_fin())
        g = self.gate(self.failed(), 'gate-integrity')
        self.assertEqual('fail', g['status'])
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
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=320x240:r=25:d=0.4', '-vf', 'tpad=stop_mode=clone:stop_duration=2.6',
               '-pix_fmt', 'yuv420p', str(self.fin))
        write_receipts(self.repo)
        self.assertEqual(1, self.run_fin())
        self.assertEqual('fail', self.gate(self.failed(), 'final-av')['status'])
        self.assertNotDelivered()

    def test_final_duration_must_match_total_duration(self):
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=320x240:r=25:d=4', '-pix_fmt', 'yuv420p', str(self.fin))
        write_receipts(self.repo)
        self.assertEqual(2, self.run_fin())
        g = self.gate(self.failed(), 'final-duration')
        self.assertEqual('stale', g['status'])
        self.assertIn('totalDurationSec', g['reason'])

    def test_final_duration_within_one_frame_is_accepted(self):
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=320x240:r=25:d=3.02', '-pix_fmt', 'yuv420p', str(self.fin))
        write_receipts(self.repo)
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
    omit = ('qc_final_pixels.mjs', 'episode_schema.mjs', 'gate_integrity.mjs')

    def test_new_gate_scripts_missing_count_as_missing(self):
        self.assertEqual(4, self.run_fin())
        for name in ('final-pixels', 'schema', 'gate-integrity'):
            self.assertEqual('missing', self.gate(self.failed(), name)['status'], name)


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
        lock = _gl.lock_bytes(_gl.build_lock(self.skill, self.repo, []))
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
        mh, err, cls = m.node_manifest_hash(self.manifest_path(), dict(os.environ))
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
        shutil.copy(self.proj / 'renders' / 'visual.mp4', self.fin)
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
        self.assertTrue(self.deliver.is_symlink())
        self.assertEqual(b'TARGET', target.read_bytes())
        self.assertIn('symlink', ' '.join(self.failed()['reasons']))
        self.deliver.unlink()
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
        for key in ('episode', 'captions', 'visual', 'final', 'layout_report', 'reports', 'relevance'):
            self.manifest({key: 'artifacts/x'})
            self.assertEqual(2, self.run_fin(), key)
            self.assertIn('may not override', ' '.join(self.failed()['reasons']))

    def test_unknown_key_and_missing_optional(self):
        self.manifest({'skip_gates': True})
        self.assertEqual(2, self.run_fin())
        self.assertIn('unknown keys', self.failed()['reasons'][0])
        self.manifest({'chapters': 'assets/ytsource/nope.txt'})
        self.assertEqual(2, self.run_fin())
        self.assertNotDelivered()


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
