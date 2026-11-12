import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
NAME = 'FakeSkill'
COMP = 'YtNewsStyle01V4'
HAVE_FFMPEG = shutil.which('ffmpeg') is not None
HAVE_NODE = shutil.which('node') is not None

PY_STUB = r'''
import json, os, shutil, sys, time
from pathlib import Path
a = sys.argv[1:]
name = Path(sys.argv[0]).stem
def arg(flag):
    return a[a.index(flag) + 1] if flag in a else None
report = arg('--report')
rdir = Path(report).parent
beh = {}
if (rdir / 'stub_behavior.json').exists():
    beh = json.loads((rdir / 'stub_behavior.json').read_text())
b = beh.get(name, {})
(rdir / (name + '.argv.json')).write_text(json.dumps(a))
if b.get('sleep'):
    time.sleep(b['sleep'])
if b.get('mutate'):
    Path(b['mutate']).write_text(Path(b['mutate']).read_text() + ' ')
if b.get('write', True):
    Path(report).write_text(json.dumps({'pass': b.get('pass', True), 'issues': []}))
    if b.get('old'):
        t = time.time() - 3600
        os.utime(report, (t, t))
sys.exit(b.get('exit', 0))
'''

JS_STUB = r'''
import fs from 'node:fs';
import crypto from 'node:crypto';
import path from 'node:path';
const a = process.argv.slice(2);
const final = a[0];
const out = a[a.indexOf('--out-dir') + 1];
const rdir = path.dirname(out);
let beh = {};
try { beh = JSON.parse(fs.readFileSync(path.join(rdir, 'stub_behavior.json'))); } catch (e) {}
const b = beh['qc_final_pixels'] || {};
fs.mkdirSync(out, { recursive: true });
fs.writeFileSync(path.join(rdir, 'qc_final_pixels.argv.json'), JSON.stringify(a));
const sha = crypto.createHash('sha256').update(fs.readFileSync(final)).digest('hex');
if (b.write !== false) {
  fs.writeFileSync(path.join(out, 'final-pixels.json'), JSON.stringify({
    schema: 'yt-news-final-pixels', pass: b.pass !== false, dips: [], videoSha256: b.videoSha256 || sha,
    certified: b.certified !== false }));
}
process.exit(b.exit || 0);
'''

STUB_FILES = {'lint_beats.py': PY_STUB, 'lint_content.py': PY_STUB, 'lint_captions.py': PY_STUB,
              'frame_checks.py': PY_STUB, 'measure_loudness.py': PY_STUB, 'qc_final_pixels.mjs': JS_STUB}
GATE_STEMS = {'beats': 'lint_beats', 'content': 'lint_content', 'captions': 'lint_captions', 'frames': 'frame_checks',
              'loudness': 'measure_loudness', 'final-pixels': 'qc_final_pixels'}
ALL_GATES = ['beats', 'content', 'captions', 'frames', 'final-av', 'final-pixels', 'loudness']
ALL_RECORDS = ALL_GATES + ['layout', 'render', 'mux', 'relevance']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sh(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def ffmpeg(*args):
    subprocess.run(['ffmpeg', '-y', '-v', 'error', *args], check=True)


PROJECT_TEMPLATE = None


def setUpModule():
    global PROJECT_TEMPLATE
    if not HAVE_FFMPEG:
        return
    t = Path(tempfile.mkdtemp(prefix='finalize-proj-'))
    p = t / 'p1'
    for d in ('artifacts', 'assets/broll', 'assets/ytsource', 'renders', 'qc/finalize'):
        (p / d).mkdir(parents=True)
    (p / 'artifacts' / 'episode.json').write_text(json.dumps({'beats': [{'t': 0}]}))
    (p / 'artifacts' / 'caption-joined.json').write_text(json.dumps({'pages': []}))
    for n in ('script.txt', 'words_by_line.txt', 'source_script.txt'):
        (p / 'artifacts' / n).write_text('hello\n')
    (p / 'artifacts' / 'line_starts.json').write_text('[0]')
    (p / 'artifacts' / '_cuts.json').write_text('[]')
    (p / 'assets' / 'broll' / 'a.mp4').write_bytes(b'x')
    (p / 'assets' / 'ytsource' / 'transcript.txt').write_text('transcript\n')
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=320x240:r=25:d=2', '-pix_fmt', 'yuv420p', str(p / 'renders' / 'visual.mp4'))
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=320x240:r=25:d=3', '-pix_fmt', 'yuv420p', str(p / 'renders' / 'final.mp4'))
    PROJECT_TEMPLATE = t


def tearDownModule():
    if PROJECT_TEMPLATE:
        shutil.rmtree(PROJECT_TEMPLATE, ignore_errors=True)


def write_receipts(proj):
    """Consistent layout/render/mux receipts for the project at <repo>/projects/p1."""
    ep, cap = proj / 'artifacts' / 'episode.json', proj / 'artifacts' / 'caption-joined.json'
    vis, fin = proj / 'renders' / 'visual.mp4', proj / 'renders' / 'final.mp4'
    (proj / 'qc' / 'layout').mkdir(parents=True, exist_ok=True)
    (proj / 'qc' / 'layout' / 'report.json').write_text(json.dumps({
        'status': 'finished', 'pass': True, 'complete': True, 'requestedCount': 12, 'fullPlanCount': 12,
        'compositionId': COMP, 'sourceHashes': {'projects/p1/artifacts/episode.json': sha(ep),
                                                'projects/p1/artifacts/caption-joined.json': sha(cap)}}))
    Path(str(vis) + '.render.json').write_text(json.dumps({
        'compositionId': COMP, 'output': {'sha256': sha(vis)}, 'episode': {'sha256': sha(ep)},
        'captions': {'sha256': sha(cap)}}))
    Path(str(fin) + '.mux.json').write_text(json.dumps({
        'schema': 'yt-news-v4-mux-receipt', 'version': 1, 'visual': {'path': str(vis), 'sha256': sha(vis)},
        'final': {'path': str(fin), 'sha256': sha(fin)}}))


def make_repo(tmp, omit=()):
    import gates_lock_for_tests as gl
    repo = Path(tmp) / 'repo'
    skill = repo / '.claude' / 'skills' / NAME
    (skill / 'scripts').mkdir(parents=True)
    for f in ('finalize.py', 'gates_lock.py', 'final_av_checks.py'):
        shutil.copy(SCRIPTS / f, skill / 'scripts' / f)
    (skill / 'scripts' / 'qc_thresholds.json').write_text('{}')
    (skill / 'SKILL.md').write_text('fake\n')
    for name, body in STUB_FILES.items():
        if name not in omit:
            (skill / 'scripts' / name).write_text(body)
    sh(tmp, 'git', 'init', '-q', str(repo))
    sh(repo, 'git', 'config', 'user.email', 't@t')
    sh(repo, 'git', 'config', 'user.name', 't')
    sh(repo, 'git', 'config', 'commit.gpgsign', 'false')
    (repo / '.gitignore').write_text('__pycache__/\nprojects/\nout/\n')
    (skill / 'scripts' / 'gates.lock.json').write_bytes(gl.lock_bytes(gl.build_lock(skill, repo, [])))
    shutil.copytree(skill, repo / '.agents' / 'skills' / NAME)
    sh(repo, 'git', 'add', '-A')
    sh(repo, 'git', 'commit', '-q', '-m', 'init')
    shutil.copytree(PROJECT_TEMPLATE / 'p1', repo / 'projects' / 'p1')
    write_receipts(repo / 'projects' / 'p1')
    return repo


# gates_lock helper importable from tests (real module, loaded from its source file)
_spec = importlib.util.spec_from_file_location('gates_lock_for_tests', SCRIPTS / 'gates_lock.py')
_gl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gl)
sys.modules['gates_lock_for_tests'] = _gl

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

    # --- helpers
    def behavior(self, **kw):
        cur = {}
        f = self.rdir / 'stub_behavior.json'
        if f.exists():
            cur = json.loads(f.read_text())
        cur.update(kw)
        f.write_text(json.dumps(cur))

    def module(self):
        _counter[0] += 1
        spec = importlib.util.spec_from_file_location('finalize_t%d' % _counter[0], self.skill / 'scripts' / 'finalize.py')
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def run_fin(self, *extra, patch=None, deliver=None):
        m = self.module()
        if patch:
            patch(m)
        argv = ['--project', 'projects/p1', '--deliver', str(deliver or self.deliver), '--repo-root', str(self.repo), *extra]
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
        return json.loads((self.rdir / (stem + '.argv.json')).read_text())

    def assertNotDelivered(self):
        self.assertFalse(self.deliver.exists())
        self.assertFalse(Path(str(self.deliver) + '.receipt.json').exists())
        self.assertFalse(Path(str(self.deliver) + '.partial').exists())

    def layout_path(self):
        return self.proj / 'qc' / 'layout' / 'report.json'

    def render_path(self):
        return self.proj / 'renders' / 'visual.mp4.render.json'

    def mux_path(self):
        return self.proj / 'renders' / 'final.mp4.mux.json'


class HappyAndGateTests(FinalizeBase):
    def test_happy_path_cli_delivers_with_receipt(self):
        r = subprocess.run([sys.executable, str(self.skill / 'scripts' / 'finalize.py'), '--project', 'projects/p1',
                            '--deliver', str(self.deliver), '--repo-root', str(self.repo)],
                           capture_output=True, text=True, cwd=self.repo)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertEqual(sha(self.proj / 'renders' / 'final.mp4'), sha(self.deliver))
        rc = self.receipt()
        self.assertEqual('yt-news-v4-delivery-receipt', rc['schema'])
        self.assertEqual([g['name'] for g in rc['gates']], ALL_RECORDS)
        self.assertTrue(all(g['status'] == 'pass' for g in rc['gates']))
        self.assertEqual(sha(self.deliver), rc['delivered']['sha256'])
        self.assertEqual(self.deliver.stat().st_size, rc['delivered']['bytes'])
        for g in rc['gates']:
            if g['name'] != 'relevance':   # absent in this fixture
                self.assertTrue(g['inputs'], g['name'])
            for h in g['inputs'].values():
                self.assertEqual(64, len(h))
        self.assertIn('projects/p1/renders/final.mp4', self.gate(rc, 'final-av')['inputs'])
        self.assertIn('projects/p1/artifacts/episode.json', self.gate(rc, 'beats')['inputs'])
        self.assertEqual(sha(self.proj / 'artifacts' / 'episode.json'), rc['bound_inputs']['episode']['sha256'])
        self.assertEqual(sha(self.proj / 'artifacts' / 'caption-joined.json'), rc['bound_inputs']['captions']['sha256'])
        self.assertEqual(sha(self.skill / 'scripts' / 'gates.lock.json'), rc['lock_sha256'])
        head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=self.repo, capture_output=True, text=True).stdout.strip()
        self.assertEqual(head, rc['git_head'])
        self.assertEqual('absent', rc['relevance_status'])
        self.assertFalse(Path(str(self.deliver) + '.FAILED.json').exists())
        self.assertIn('FINALIZE PASS', r.stdout)

    def test_gate_arguments(self):
        self.assertEqual(0, self.run_fin())
        beats = self.argv_of('lint_beats')
        self.assertEqual(str(self.proj / 'artifacts' / 'episode.json'), beats[0])
        content = self.argv_of('lint_content')
        self.assertIn('--source-transcript', content)       # optional file exists
        self.assertNotIn('--chapters', content)             # optional file absent
        self.assertNotIn('--relevance', content)
        self.assertEqual(str(self.proj / 'artifacts' / 'episode.json'), content[content.index('--beats') + 1])
        self.assertIn('--source-script', self.argv_of('lint_captions'))
        self.assertEqual(str(self.proj / 'artifacts' / 'caption-joined.json'), self.argv_of('lint_captions')[self.argv_of('lint_captions').index('--pages') + 1])
        frames = self.argv_of('frame_checks')
        self.assertEqual('cutaways', frames[0])
        self.assertEqual([str(self.proj / 'assets' / 'broll')],
                         [frames[i + 1] for i, x in enumerate(frames) if x == '--media-root'])
        px = self.argv_of('qc_final_pixels')
        self.assertNotIn('--allow-draft', px)
        self.assertIn('--out-dir', px)
        self.assertFalse(any('allow-draft' in a for g in self.module().GATES for a in g['args']))

    def test_no_skip_switch(self):
        r = subprocess.run([sys.executable, str(self.skill / 'scripts' / 'finalize.py'), '--project', 'projects/p1',
                            '--deliver', str(self.deliver), '--repo-root', str(self.repo), '--skip-gates'],
                           capture_output=True, text=True)
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
        for g in ('lint_beats', 'lint_captions', 'frame_checks', 'measure_loudness', 'qc_final_pixels'):
            self.assertTrue((self.rdir / (g + '.argv.json')).exists(), g)
        self.assertEqual('pass', self.gate(f, 'beats')['status'])
        self.assertEqual('pass', self.gate(f, 'final-av')['status'])
        self.assertEqual(len(ALL_RECORDS), len(f['gates']))

    def test_report_pass_false_with_exit_0_fails(self):
        self.behavior(lint_beats={'exit': 0, 'pass': False})
        self.assertEqual(1, self.run_fin())
        self.assertNotDelivered()
        self.assertEqual('fail', self.gate(self.failed(), 'beats')['status'])

    def test_stale_report_from_previous_run_is_not_accepted(self):
        self.assertEqual(0, self.run_fin())
        self.deliver.unlink()
        self.behavior(lint_captions={'write': False})
        self.assertEqual(2, self.run_fin())
        self.assertNotDelivered()
        self.assertEqual('stale', self.gate(self.failed(), 'captions')['status'])

    def test_old_mtime_report_is_stale(self):
        self.behavior(measure_loudness={'old': True})
        self.assertEqual(2, self.run_fin())
        g = self.gate(self.failed(), 'loudness')
        self.assertEqual('stale', g['status'])
        self.assertIn('stale', g['reason'])

    def test_unparseable_report_fails(self):
        self.behavior(lint_beats={'write': False})
        (self.rdir / 'beats.json').write_text('{}')   # removed before the run, so still missing
        self.assertEqual(2, self.run_fin())

    def test_gate_crash_exit_code_is_quality(self):
        self.behavior(frame_checks={'exit': 7, 'write': False})
        self.assertEqual(1, self.run_fin())
        self.assertEqual('fail', self.gate(self.failed(), 'frames')['status'])

    def test_gate_exit_2_is_bad_input_class(self):
        self.behavior(frame_checks={'exit': 2, 'pass': False})
        self.assertEqual(2, self.run_fin())

    def test_gate_exit_4_is_tool_class(self):
        self.behavior(frame_checks={'exit': 4, 'pass': False})
        self.assertEqual(4, self.run_fin())

    def test_gate_timeout(self):
        self.behavior(lint_beats={'sleep': 8})
        def patch(m):
            next(g for g in m.GATES if g['name'] == 'beats')['limit'] = 1
        self.assertEqual(4, self.run_fin(patch=patch))
        self.assertNotDelivered()
        g = self.gate(self.failed(), 'beats')
        self.assertEqual('timeout', g['status'])
        self.assertIn('timeout', g['reason'])
        self.assertLess(g['seconds'], 6)

    def test_total_budget_exhausted(self):
        def patch(m):
            m.TOTAL_BUDGET_SEC = 0
        self.assertEqual(4, self.run_fin(patch=patch))
        self.assertTrue(all(g['status'] == 'timeout' for g in self.failed()['gates'] if g['kind'] == 'fresh'))

    def test_final_pixels_certified_false_is_quality(self):
        self.behavior(qc_final_pixels={'certified': False})
        self.assertEqual(1, self.run_fin())
        self.assertEqual('fail', self.gate(self.failed(), 'final-pixels')['status'])

    def test_final_pixels_wrong_video_hash_is_stale_class(self):
        self.behavior(qc_final_pixels={'videoSha256': '0' * 64})
        self.assertEqual(2, self.run_fin())
        self.assertEqual('bad-input', self.gate(self.failed(), 'final-pixels')['status'])

    def test_final_pixels_dark_frames_exit_1(self):
        self.behavior(qc_final_pixels={'exit': 1, 'pass': False})
        self.assertEqual(1, self.run_fin())

    def test_real_final_av_gate_fails_on_frozen_final(self):
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=320x240:r=25:d=1', '-vf', 'tpad=stop_mode=clone:stop_duration=3',
               '-pix_fmt', 'yuv420p', str(self.proj / 'renders' / 'final.mp4'))
        write_receipts(self.proj)
        self.assertEqual(1, self.run_fin())
        g = self.gate(self.failed(), 'final-av')
        self.assertEqual('fail', g['status'])
        self.assertNotDelivered()

    def test_input_mutated_during_run_is_rejected(self):
        self.behavior(lint_beats={'mutate': str(self.proj / 'artifacts' / 'script.txt')})
        self.assertEqual(2, self.run_fin())
        self.assertTrue(any('changed while finalize' in r for r in self.failed()['reasons']))
        self.assertNotDelivered()

    def test_missing_required_input_is_bad_input(self):
        (self.proj / 'artifacts' / 'words_by_line.txt').unlink()
        self.assertEqual(2, self.run_fin())
        self.assertEqual('bad-input', self.gate(self.failed(), 'content')['status'])
        self.assertFalse((self.rdir / 'lint_content.argv.json').exists())

    def test_missing_final_is_bad_input(self):
        (self.proj / 'renders' / 'final.mp4').unlink()
        self.assertEqual(2, self.run_fin())
        self.assertNotDelivered()


class MissingScriptTests(FinalizeBase):
    omit = ('lint_captions.py',)

    def test_registry_script_missing_is_exit_4(self):
        self.assertEqual(4, self.run_fin())
        self.assertNotDelivered()
        g = self.gate(self.failed(), 'captions')
        self.assertEqual('missing', g['status'])
        self.assertIn('lint_captions.py', g['reason'])
        self.assertTrue((self.rdir / 'lint_beats.argv.json').exists())   # others still ran

    def test_precedence_tool_missing_over_bad_input_and_quality(self):
        self.behavior(lint_beats={'exit': 1, 'pass': False})
        self.edit(self.layout_path(), lambda d: d.update(complete=False))
        self.assertEqual(4, self.run_fin())


class MissingNodeGateTests(FinalizeBase):
    omit = ('qc_final_pixels.mjs',)

    def test_final_pixels_script_missing_counts_as_missing(self):
        self.assertEqual(4, self.run_fin())
        self.assertEqual('missing', self.gate(self.failed(), 'final-pixels')['status'])


class IntegrityTests(FinalizeBase):
    def assertIntegrityFailure(self, extra_check=None):
        self.behavior(lint_beats={'exit': 1, 'pass': False})   # would be a quality fail; integrity must win
        self.assertEqual(3, self.run_fin())
        self.assertNotDelivered()
        f = self.failed()
        self.assertEqual(3, f['exit_code'])
        self.assertTrue(f['integrity_problems'])
        self.assertEqual([], f['gates'])
        for stem in GATE_STEMS.values():
            self.assertFalse((self.rdir / (stem + '.argv.json')).exists(), 'gate ran: ' + stem)
        self.assertFalse((self.rdir / 'final-av.json').exists())

    def test_locked_gate_modified(self):
        (self.skill / 'scripts' / 'lint_beats.py').write_text('import sys; sys.exit(0)\n')
        self.assertIntegrityFailure()
        self.assertTrue(any('file-changed' in p for p in self.failed()['integrity_problems']))

    def test_mirror_differs(self):
        (self.repo / '.agents' / 'skills' / NAME / 'SKILL.md').write_text('changed\n')
        self.assertIntegrityFailure()

    def test_mirror_missing(self):
        shutil.rmtree(self.repo / '.agents')
        self.assertIntegrityFailure()

    def test_lock_regenerated_not_committed(self):
        (self.skill / 'scripts' / 'lint_beats.py').write_text('import sys; sys.exit(0)\n')
        (self.repo / '.agents' / 'skills' / NAME / 'scripts' / 'lint_beats.py').write_text('import sys; sys.exit(0)\n')
        lock = _gl.lock_bytes(_gl.build_lock(self.skill, self.repo, []))
        (self.skill / 'scripts' / 'gates.lock.json').write_bytes(lock)
        (self.repo / '.agents' / 'skills' / NAME / 'scripts' / 'gates.lock.json').write_bytes(lock)
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

    def test_check_mode_reports_integrity_failure_without_touching_deliver(self):
        (self.skill / 'scripts' / 'lint_beats.py').write_text('x\n')
        self.assertEqual(3, self.run_fin('--check'))
        self.assertFalse(self.deliver.parent.exists())
        self.assertEqual(3, json.loads((self.rdir / 'check.json').read_text())['exit_code'])


class VerifiedReportTests(FinalizeBase):
    def assertExit(self, code, status, name):
        self.assertEqual(code, self.run_fin(), self.out)
        self.assertNotDelivered()
        self.assertEqual(status, self.gate(self.failed(), name)['status'])

    def test_layout_changed_source_hash(self):
        (self.proj / 'artifacts' / 'episode.json').write_text(json.dumps({'beats': [{'t': 1}]}))
        self.assertExit(2, 'stale', 'layout')
        self.assertIn('changed since the sweep', self.gate(self.failed(), 'layout')['reason'])

    def test_layout_incomplete(self):
        self.edit(self.layout_path(), lambda d: d.update(complete=False))
        self.assertExit(2, 'stale', 'layout')

    def test_layout_not_finished_or_not_pass(self):
        self.edit(self.layout_path(), lambda d: d.update(status='running'))
        self.assertExit(2, 'stale', 'layout')
        self.edit(self.layout_path(), lambda d: d.update(status='finished', **{'pass': False}))
        self.assertExit(2, 'stale', 'layout')

    def test_layout_counts_differ(self):
        self.edit(self.layout_path(), lambda d: d.update(requestedCount=5))
        self.assertExit(2, 'stale', 'layout')

    def test_layout_wrong_composition(self):
        self.edit(self.layout_path(), lambda d: d.update(compositionId='Other'))
        self.assertExit(2, 'stale', 'layout')

    def test_layout_missing(self):
        self.layout_path().unlink()
        self.assertExit(2, 'stale', 'layout')

    def test_layout_without_source_hashes_or_not_binding_episode(self):
        self.edit(self.layout_path(), lambda d: d.pop('sourceHashes'))
        self.assertExit(2, 'stale', 'layout')
        write_receipts(self.proj)
        self.edit(self.layout_path(), lambda d: d['sourceHashes'].pop('projects/p1/artifacts/episode.json'))
        self.assertExit(2, 'stale', 'layout')
        self.assertIn('does not bind', self.gate(self.failed(), 'layout')['reason'])

    def test_layout_reused_frames_requires_cache_manifest(self):
        self.edit(self.layout_path(), lambda d: d.update(reusedFrames=True))
        self.assertExit(2, 'stale', 'layout')
        self.edit(self.layout_path(), lambda d: d.update(cacheManifest={'frames': 3, 'dir': 'qc/layout/cache'}))
        self.assertEqual(0, self.run_fin(), self.out)
        g = self.gate(self.receipt(), 'layout')
        self.assertTrue(g['reused_frames'])
        self.assertEqual(64, len(g['cache_manifest_sha256']))

    def test_layout_absolute_source_paths_work(self):
        def absolute(d):
            d['sourceHashes'] = {str(self.proj / 'artifacts' / 'episode.json'): d['sourceHashes']['projects/p1/artifacts/episode.json'],
                                 'projects/p1/artifacts/caption-joined.json': d['sourceHashes']['projects/p1/artifacts/caption-joined.json']}
        self.edit(self.layout_path(), absolute)
        self.assertEqual(0, self.run_fin(), self.out)

    def test_render_receipt_sha_mismatch(self):
        self.edit(self.render_path(), lambda d: d['output'].update(sha256='1' * 64))
        self.assertExit(2, 'stale', 'render')

    def test_render_receipt_missing_or_wrong_composition(self):
        self.render_path().unlink()
        self.assertExit(2, 'stale', 'render')
        write_receipts(self.proj)
        self.edit(self.render_path(), lambda d: d.update(compositionId='Other'))
        self.assertExit(2, 'stale', 'render')

    def test_render_receipt_episode_or_captions_mismatch(self):
        self.edit(self.render_path(), lambda d: d['episode'].update(sha256='2' * 64))
        self.assertExit(2, 'stale', 'render')
        write_receipts(self.proj)
        self.edit(self.render_path(), lambda d: d['captions'].update(sha256='3' * 64))
        self.assertExit(2, 'stale', 'render')

    def test_render_receipt_tolerates_missing_episode_and_captions_fields(self):
        self.edit(self.render_path(), lambda d: (d.pop('episode'), d.pop('captions')))
        self.assertEqual(0, self.run_fin(), self.out)

    def test_verify_render_receipt_function_is_standalone(self):
        m = self.module()
        vis = self.proj / 'renders' / 'visual.mp4'
        ep, cap = self.proj / 'artifacts' / 'episode.json', self.proj / 'artifacts' / 'caption-joined.json'
        self.assertEqual([], m.verify_render_receipt(self.render_path(), COMP, vis, ep, cap, m.sha256_file))
        self.assertTrue(m.verify_render_receipt(self.proj / 'nope.json', COMP, vis, ep, cap, m.sha256_file))

    def test_mux_receipt_mismatch(self):
        self.edit(self.mux_path(), lambda d: d['final'].update(sha256='4' * 64))
        self.assertExit(2, 'stale', 'mux')
        write_receipts(self.proj)
        self.edit(self.mux_path(), lambda d: d['visual'].update(sha256='5' * 64))
        self.assertExit(2, 'stale', 'mux')

    def test_mux_receipt_missing_or_final_replaced(self):
        self.mux_path().unlink()
        self.assertExit(2, 'stale', 'mux')
        write_receipts(self.proj)
        shutil.copy(self.proj / 'renders' / 'visual.mp4', self.proj / 'renders' / 'final.mp4')   # agent swaps the final
        self.assertEqual(2, self.run_fin())
        self.assertEqual('stale', self.gate(self.failed(), 'mux')['status'])

    def test_relevance_failed_is_quality_failure(self):
        (self.proj / 'artifacts' / 'relevance.json').write_text(json.dumps({'verification_status': 'failed'}))
        self.assertExit(1, 'fail', 'relevance')

    def test_relevance_statuses_are_recorded(self):
        for status in ('verified', 'unverified'):
            (self.proj / 'artifacts' / 'relevance.json').write_text(json.dumps({'verification_status': status}))
            self.assertEqual(0, self.run_fin(), self.out)
            self.assertEqual(status, self.receipt()['relevance_status'])
            self.assertEqual(status, self.gate(self.receipt(), 'relevance')['verification_status'])
            self.assertIn('--relevance', self.argv_of('lint_content'))
            self.deliver.unlink()

    def test_relevance_unreadable(self):
        (self.proj / 'artifacts' / 'relevance.json').write_text('{oops')
        self.assertExit(2, 'stale', 'relevance')


class ResultHandlingTests(FinalizeBase):
    def test_preexisting_output_untouched_flag_recorded_stale_receipt_removed(self):
        self.deliver.parent.mkdir(parents=True)
        self.deliver.write_bytes(b'OLD VIDEO')
        Path(str(self.deliver) + '.receipt.json').write_text('{"stale": true}')
        Path(str(self.deliver) + '.partial').write_bytes(b'junk')
        self.behavior(lint_beats={'exit': 1, 'pass': False})
        self.assertEqual(1, self.run_fin())
        self.assertEqual(b'OLD VIDEO', self.deliver.read_bytes())
        self.assertFalse(Path(str(self.deliver) + '.receipt.json').exists())
        self.assertFalse(Path(str(self.deliver) + '.partial').exists())
        f = self.failed()
        self.assertTrue(f['preexisting_output_not_certified'])
        self.assertIn('seconds', f)

    def test_no_preexisting_flag_false(self):
        self.behavior(lint_beats={'exit': 1, 'pass': False})
        self.run_fin()
        self.assertFalse(self.failed()['preexisting_output_not_certified'])

    def test_success_replaces_old_output_and_clears_failed(self):
        self.deliver.parent.mkdir(parents=True)
        self.deliver.write_bytes(b'OLD')
        Path(str(self.deliver) + '.FAILED.json').write_text('{}')
        self.assertEqual(0, self.run_fin())
        self.assertEqual(sha(self.proj / 'renders' / 'final.mp4'), sha(self.deliver))
        self.assertFalse(Path(str(self.deliver) + '.FAILED.json').exists())
        self.assertFalse(Path(str(self.deliver) + '.partial').exists())

    def test_check_mode_never_touches_deliver(self):
        self.assertEqual(0, self.run_fin('--check'))
        self.assertFalse(self.deliver.exists())
        self.assertFalse(self.deliver.parent.exists())
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
        self.assertFalse(json.loads((self.rdir / 'check.json').read_text())['would_deliver'])

    def test_deliver_must_be_mp4_and_not_the_final(self):
        self.assertEqual(2, self.run_fin(deliver=self.repo / 'out' / 'episode.mov'))
        self.assertEqual(2, self.run_fin(deliver=self.proj / 'renders' / 'final.mp4'))

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

    def test_manifest_overrides_and_validation(self):
        (self.proj / 'artifacts' / 'finalize.json').write_text(json.dumps({'script': 'artifacts/other.txt'}))
        self.assertEqual(2, self.run_fin())      # required input missing
        shutil.copy(self.proj / 'artifacts' / 'script.txt', self.proj / 'artifacts' / 'other.txt')
        self.assertEqual(0, self.run_fin(), self.out)
        self.assertEqual(sha(self.proj / 'artifacts' / 'finalize.json'), self.receipt()['manifest_sha256'])
        self.assertTrue(self.argv_of('lint_content')[self.argv_of('lint_content').index('--script') + 1].endswith('other.txt'))
        self.deliver.unlink()
        (self.proj / 'artifacts' / 'finalize.json').write_text(json.dumps({'skip_gates': True}))
        self.assertEqual(2, self.run_fin())
        self.assertIn('unknown keys', self.failed()['reasons'][0])
        (self.proj / 'artifacts' / 'finalize.json').write_text(json.dumps({'relevance': 'artifacts/nope.json'}))
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
