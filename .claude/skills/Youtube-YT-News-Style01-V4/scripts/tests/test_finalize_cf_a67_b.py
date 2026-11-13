"""finalize.py, CF-A67 W3 phase B: the word-timing chain is re-checked from its primary inputs.

`word-timing` (every mode): raw_asr.json bound to the avatar audio (wav extracted again), to script.txt, to the running chain
code and the pinned params; the recorded toolchain == this machine's (`--fingerprint`, else exit 4); caption_pages.json ==
what asr_align.py derives; timing_defects.py (with --wav) finds nothing; the raw words sit where the audio has speech (rules a
and c).  `asr-recheck` (--check only): a new transcription in a new empty dir must be byte-identical.  Also B8 (issue
summaries: errors first) and B9 (symbolic links are refused).  The fake ASR interpreter, the raw fixture and the project are
the ones of test_finalize.py (FinalizeBase.module() sets finalize's ASR_RUN seam to the fake launcher file).
"""
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import pwd
import shlex
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_finalize as tf                      # noqa: E402
from test_finalize import SCRIPTS, sha, ffmpeg  # noqa: E402
from test_finalize_cf_a67 import Base, tree_state  # noqa: E402

RAW_REL = 'projects/p1/artifacts/word_timing/raw_asr.json'
CHAIN_ENV = {'HOME', 'PATH', 'LANG', 'TMPDIR'}
LAUNCHER_SCRIPTS = ('asr_transcribe.py', 'asr_align.py', 'source_timed.py')
DEFECTS_FLAGS = ['-I', '-S', '-B', '-X', 'pycache_prefix=/var/empty']


def env_names(call):
    """The environment names a chain call received, without the two /bin/bash puts in itself (PWD, SHLVL) and the encoding hint
    macOS adds inside every process (even under `env -i`): none of them is something finalize passed."""
    return set(call['env']) - tf.BASH_OR_OS_ADDED


def setUpModule():
    tf.AVATAR_FILE.clear()
    tf.MUXED.clear()
    tf.setUpModule()


def tearDownModule():
    tf.tearDownModule()


def load_finalize():
    import importlib.util
    spec = importlib.util.spec_from_file_location('finalize_b_unit', SCRIPTS / 'finalize.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def chain_source(name):
    return (SCRIPTS / name).read_text(encoding='utf-8')


def chain_constant(name, const):
    """A module-level constant of a chain script, read with ast (the chain is never imported here)."""
    tree = ast.parse(chain_source(name))
    node = next(n.value for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name) and n.targets[0].id == const)
    return ast.literal_eval(node)


class ChainBase(Base):
    @property
    def raw(self):
        return self.proj / 'artifacts' / 'word_timing' / 'raw_asr.json'

    @property
    def pages(self):
        return self.proj / 'artifacts' / 'word_timing' / 'caption_pages.json'

    def again(self):
        for p in (self.deliver, Path(str(self.deliver) + '.receipt.json'), Path(str(self.deliver) + '.FAILED.json')):
            if p.exists():
                p.unlink()

    def check_doc(self):
        return json.loads((self.rdir / 'check.json').read_text())

    def check_gate(self, name):
        return next(g for g in self.check_doc()['gates'] if g['name'] == name)

    def transcriptions(self):
        return [c for c in self.asr_calls() if c['script'] == 'asr_transcribe.py' and '--wav' in c['argv']]

    def recorded_run(self, *extra):
        """Run finalize in-process with EVERY child command it starts recorded (spawn() and subprocess.run) -> (exit, [argv])."""
        cmds = []
        real_run = subprocess.run

        def rec_run(cmd, *a, **k):
            if isinstance(cmd, (list, tuple)):
                cmds.append([str(x) for x in cmd])
            return real_run(cmd, *a, **k)

        def patch(m):
            real_spawn = m.spawn

            def spawn(cmd, *a, **k):
                cmds.append([str(x) for x in cmd])
                return real_spawn(cmd, *a, **k)
            m.spawn = spawn
        with mock.patch.object(subprocess, 'run', rec_run):
            code = self.run_fin(*extra, patch=patch)
        return code, cmds

    def defects_argv(self):
        wd = self.rdir / 'word-timing'
        return [sys.executable, *DEFECTS_FLAGS, str(self.skill / 'scripts' / 'timing_defects.py'), '--pages', str(wd / 'caption_pages.json'),
                '--raw', str(self.raw), '--wav', str(wd / 'vo16k.wav'), '--report', str(wd / 'timing-defects.json')]

    def pages_with_a_zero_run(self):
        pages = json.loads(json.dumps(tf.PAGES))
        for w in pages[1]['words']:                  # 'second line here' all at 0.80-0.80: a run of 3 zero-length words
            w['s'] = w['e'] = 0.8
        return json.dumps(pages)


# ---------------------------------------------------------------------------------------------- B2 word-timing (delivery)
class WordTimingGateTests(ChainBase):
    def test_pass_binds_the_raw_and_the_receipt_records_its_sha_and_the_recorded_toolchain(self):
        self.assertEqual(0, self.run_fin(), self.out)
        g = self.gate_rec('word-timing')
        self.assertEqual('pass', g['status'])
        self.assertIn(RAW_REL, g['inputs'])
        self.assertNotIn('projects/p1/artifacts/word_timing/word_timing.done.json', g['inputs'])
        rc = self.receipt()
        self.assertEqual({'path': RAW_REL, 'sha256': sha(self.raw)}, rc['word_timing']['raw'])
        raw = json.loads(self.raw.read_text())
        fp = rc['word_timing']['fingerprint']
        self.assertEqual(set(tf.FAKE_FP) | {'params', 'code'}, set(fp))
        for k, v in fp.items():
            self.assertEqual(raw[k], v, k)
        self.assertIn('artifacts/word_timing/word_timing.done.json', rc['self_reported'])
        self.assertEqual({'path': RAW_REL, 'sha256': sha(self.raw)}, rc['bound_inputs']['word_raw'])
        rep = json.loads((self.rdir / 'word-timing.json').read_text())
        self.assertEqual(tf.WAV_INFO['wav_sha256'], rep['steps']['wav']['sha256'])
        self.assertEqual(tf.WAV_INFO['duration'], rep['steps']['wav']['duration'])
        b = rep['binding']
        self.assertEqual((0, 0.0), (b['wordsInSilence'], b['inSilenceShare']))
        self.assertEqual(0.0, b['speechBeforeFirstWord'])
        self.assertLessEqual(b['speechAfterLastWord'], 0.75)
        self.assertEqual([0.1, 0.4], b['interior'])                      # timing_check.py THRESHOLDS, read from its source
        self.assertFalse((self.rdir / 'word-timing' / 'vo16k.wav').exists())

    def test_a_delivery_never_transcribes_and_every_chain_call_is_isolated(self):
        self.assertEqual(0, self.run_fin(), self.out)
        calls = self.asr_calls()
        self.assertEqual(['asr_transcribe.py', 'asr_transcribe.py', 'asr_align.py'], [c['script'] for c in calls])
        self.assertEqual(['asr_transcribe.py', '--check'], calls[0]['argv'])            # no --deep in a delivery
        self.assertEqual(['asr_transcribe.py', '--fingerprint'], calls[1]['argv'])
        self.assertEqual([], self.transcriptions())
        self.assertNotIn('asr-recheck', [g['name'] for g in self.receipt()['gates']])
        home = pwd.getpwuid(os.getuid()).pw_dir
        for c in calls:
            self.assertEqual(CHAIN_ENV, env_names(c), c['script'])
            self.assertEqual(home, c['env']['HOME'])
            self.assertEqual(os.path.dirname(tf.CHAIN_FFMPEG) + ':/usr/bin:/bin', c['env']['PATH'])
            self.assertEqual(('en_US.UTF-8', '/var/empty'), (c['env']['LANG'], c['env']['TMPDIR']))

    def test_the_chain_python_is_reached_only_through_the_launcher_and_timing_defects_argv_is_pinned(self):
        for extra, n_chain in (((), 3), (('--check',), 5)):
            code, cmds = self.recorded_run(*extra)
            self.assertEqual(0, code, (extra, self.out))
            launcher = [c for c in cmds if c[:2] == ['/bin/bash', str(self.asr / 'asr_run.sh')]]
            self.assertEqual(n_chain, len(launcher), extra)      # delivery: check, fingerprint, align; --check: + transcribe, align
            for c in launcher:
                self.assertIn(c[2], LAUNCHER_SCRIPTS)            # a bare name: the launcher runs only its own scripts, next to itself
            for c in cmds:
                if c in launcher:
                    continue
                # never started directly (git / node commands that merely NAME the files, e.g. the integrity pathspec, run nothing)
                starts = os.path.basename(c[0]).startswith(('python', 'bash', 'sh', 'zsh', 'env')) or c[0].endswith(LAUNCHER_SCRIPTS)
                if starts:
                    self.assertFalse(any(x.endswith(n) for x in c for n in LAUNCHER_SCRIPTS), c)
                self.assertFalse(any('asr-venv' in x or 'karaoke' in x or '.cache/yt-news-v4' in x for x in c), c)
                if os.path.basename(c[0]).startswith('python'):
                    self.assertEqual(sys.executable, c[0], c)  # the only python finalize starts is its own
                self.assertNotIn(os.path.basename(c[0]), ('bash', 'sh', 'zsh'), c)   # the only shell is /bin/bash, for the launcher
            # timing_defects.py (stdlib only, not a launcher script): exactly this argv, finalize's interpreter, no site-packages
            started = [c for c in cmds if os.path.basename(c[0]).startswith(('python', 'bash')) and any(x.endswith('timing_defects.py') for x in c)]
            self.assertEqual([self.defects_argv()], started, extra)

    def test_the_done_marker_is_never_read(self):
        self.assertEqual(0, self.run_fin(), self.out)
        before = [(g['name'], g['status']) for g in self.receipt()['gates']]
        done = self.proj / 'artifacts' / 'word_timing' / 'word_timing.done.json'
        for text in ('{"output_sha256": "%s", "ok": false, "note": "edited"}' % ('0' * 64), None):
            self.again()
            if text is None:
                done.unlink()
            else:
                done.write_text(text)
            self.assertEqual(0, self.run_fin(), self.out)
            self.assertEqual(before, [(g['name'], g['status']) for g in self.receipt()['gates']])

    # -- B2.2 the audio
    def test_a_raw_of_another_audio_is_a_quality_failure(self):
        d = tf.WAV_INFO['duration']
        for audio in ({'wav_sha256': 'a' * 64, 'duration': d}, {'wav_sha256': tf.WAV_INFO['wav_sha256'], 'duration': d + 0.5}):
            self.again()
            self.set_raw(tf.raw_doc(audio=audio))
            self.assertEqual(1, self.run_fin(), (audio, self.out))
            g = self.gate_rec('word-timing')
            self.assertEqual('fail', g['status'])
            self.assertIn("raw_asr.json was not decoded from this presenter video's audio", g['reason'])
            self.assertIn('remotion-composer/public/ep1/avatar.mp4', g['reason'])

    def test_a_replaced_avatar_needs_a_new_raw(self):
        avatar = self.repo / 'remotion-composer' / 'public' / 'ep1' / 'avatar.mp4'
        ffmpeg('-f', 'lavfi', '-i', 'color=c=gray:s=320x180:r=25:d=2', '-f', 'lavfi', '-i', 'sine=frequency=500:sample_rate=48000:duration=2',
               '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(avatar))
        self.rebind()
        code = self.run_fin()
        self.assertNotEqual(0, code, self.out)
        g = self.gate_rec('word-timing')
        self.assertEqual('fail', g['status'])
        self.assertIn("not decoded from this presenter video's audio", g['reason'])
        self.again()
        self.rebind_raw()                                # word_timing.sh re-run on the new avatar: the binding holds again
        self.run_fin()
        self.assertEqual('pass', self.gate_rec('word-timing')['status'], self.out)

    # -- B2.3 header
    def test_a_raw_for_another_script_is_stale(self):
        self.set_raw(tf.raw_doc(script_sha='b' * 64))
        self.assertEqual(2, self.run_fin(), self.out)
        g = self.gate_rec('word-timing')
        self.assertEqual('stale', g['status'])
        self.assertIn('raw_asr.json was decoded for another script (script_sha256 differs from projects/p1/artifacts/script.txt)', g['reason'])

    def test_a_raw_made_by_other_chain_code_is_stale(self):
        doc = tf.raw_doc()
        doc['code']['asr_align.py'] = 'c' * 64
        self.set_raw(doc)
        self.assertEqual(2, self.run_fin(), self.out)
        g = self.gate_rec('word-timing')
        self.assertEqual('stale', g['status'])
        self.assertIn('raw_asr.json was made by other chain code than this checkout (asr_align.py differ)', g['reason'])

    def test_other_params_or_another_schema_are_stale(self):
        for over in ({'params': dict(tf.ASR_PARAMS, temperature=[0.0, 0.2])}, {'schema': 'other'}, {'version': 2}):
            self.again()
            self.set_raw(tf.raw_doc(**over))
            self.assertEqual(2, self.run_fin(), (over, self.out))
            self.assertEqual('stale', self.gate_rec('word-timing')['status'], over)

    # -- B2.4 the toolchain
    def test_a_toolchain_difference_is_exit_4_naming_the_differing_lines(self):
        self.asr_behavior(fingerprint_patch={'mlx': {'version': '0.32.0'}, 'newpart': {'x': 1}})
        self.assertEqual(4, self.run_fin(), self.out)
        g = self.gate_rec('word-timing')
        self.assertEqual('missing', g['status'])                       # class 4 (public records carry the status, not the class)
        self.assertIn('the transcription toolchain differs from production: ', g['reason'])
        self.assertIn('mlx.version: 0.31.2 (production) != 0.32.0 (this machine)', g['reason'])
        self.assertIn('newpart: <missing> (production) != {"x": 1} (this machine)', g['reason'])
        self.assertEqual([], self.transcriptions())

    def test_the_fingerprint_tool_failing_is_exit_4_never_a_pass(self):
        for beh in ({'exit': 4, 'stderr': 'ERROR: venv pins differ\n'}, {'stdout': 'not json'}):
            self.again()
            self.asr_behavior(fingerprint=dict(beh, **({'exit': 0} if 'exit' not in beh else {})))
            self.assertEqual(4, self.run_fin(), (beh, self.out))
            self.assertIn('cannot read the transcription toolchain of this machine', self.gate_rec('word-timing')['reason'])

    # -- B2.5 the pages
    def test_pages_hand_edited_by_10_ms_are_not_what_asr_align_derives(self):
        data = json.loads(self.pages.read_text())
        data[1]['words'][0]['s'] = round(data[1]['words'][0]['s'] + 0.01, 2)
        self.pages.write_text(json.dumps(data))
        code = self.run_fin()
        self.assertNotEqual(0, code, self.out)
        g = self.gate_rec('word-timing')
        self.assertEqual('fail', g['status'])
        self.assertIn('caption_pages.json is not what asr_align.py derives from raw_asr.json: re-run word_timing.sh, never hand-edit', g['reason'])
        self.assertIn("first differing word #3: 'second' 0.8-1.0 (re-derived) vs 'second' 0.81-1.0 (artifact)", g['reason'])

    def test_asr_align_refusing_is_stale_and_crashing_is_exit_4(self):
        for beh, code, status in (({'exit': 2, 'stderr': 'ERROR: script sha256 differs\n'}, 2, 'stale'), ({'exit': 3}, 4, 'missing')):
            self.again()
            self.asr_behavior(align=beh)
            self.assertEqual(code, self.run_fin(), (beh, self.out))
            g = self.gate_rec('word-timing')
            self.assertEqual(status, g['status'], (beh, g))
            self.assertIn('asr_align.py exited %d' % beh['exit'], g['reason'])

    # -- B2.6 defects
    def test_timing_defects_are_a_quality_failure_listing_them(self):
        # the REAL timing_defects.py on pages that asr_align (fake) derives from the raw: a run of three zero-length words
        text = self.pages_with_a_zero_run()
        self.set_raw(tf.raw_doc(), pages_text=text)
        self.pages.write_text(text)
        self.assertEqual(1, self.run_fin(), self.out)
        g = self.gate_rec('word-timing')
        self.assertEqual('fail', g['status'])
        self.assertIn('the word timing has 1 defect(s) (timing_defects.py): zero-run ', g['reason'])
        self.assertIn('re-run word_timing.sh, never hand-edit', g['reason'])
        rep = json.loads((self.rdir / 'word-timing' / 'timing-defects.json').read_text())
        self.assertEqual(['zero-run'], [d['code'] for d in rep['defects']])

    def test_timing_defects_refusing_its_input_is_stale(self):
        self.set_raw(tf.raw_doc(), pages_text='not json')       # what the (fake) align derives and the artifact agree on
        self.pages.write_text('not json')
        self.assertEqual(2, self.run_fin(), self.out)
        g = self.gate_rec('word-timing')
        self.assertEqual('stale', g['status'])
        self.assertIn('timing_defects.py refused its input', g['reason'])

    def test_timing_defects_runs_on_the_stdlib_alone(self):
        # 1. every import of the file (top level and inside functions) is a stdlib module: no third-party dependency can be added
        tree = ast.parse((self.skill / 'scripts' / 'timing_defects.py').read_text(encoding='utf-8'))
        mods = {a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        mods |= {n.module.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module}
        self.assertEqual(set(), mods - set(sys.stdlib_module_names), mods)
        # 2. it really runs with finalize's flags (-S: no site, no site-packages on sys.path) on the fixture's own pages + raw + wav
        m = self.module()
        wav = Path(self.tmp) / 'probe.wav'
        tf.chain_wav(self.repo / 'remotion-composer' / 'public' / 'ep1' / 'avatar.mp4', wav)
        rep = Path(self.tmp) / 'probe-defects.json'
        r = subprocess.run(m.defects_cmd('--pages', self.pages, '--raw', self.raw, '--wav', wav, '--report', rep), capture_output=True,
                           text=True, env=m.asr_env(), cwd=self.tmp, timeout=60)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIs(True, json.loads(rep.read_text())['ok'])
        probe = subprocess.run([sys.executable, *DEFECTS_FLAGS, '-c', 'import sys; print(sum("site-packages" in p for p in sys.path), '
                                '"site" in sys.modules)'], capture_output=True, text=True, env=m.asr_env(), timeout=30)
        self.assertEqual('0 False', probe.stdout.strip(), probe.stderr)

    def test_a_launcher_refusal_is_exit_4_with_its_own_message(self):
        msg = ("ERROR: the interpreter / stdlib / ASR venv differ from asr_venv.manifest; first differences: < 9a1c  "
               "@VENV@/lib/python3.12/site-packages/mlx/core.py; -- run 'bash /s/setup_asr_venv.sh' (a human, not the agent)\n")
        self.asr_behavior(fingerprint={'exit': 4, 'stderr': msg})
        self.assertEqual(4, self.run_fin(), self.out)
        g = self.gate_rec('word-timing')
        self.assertEqual('missing', g['status'])
        self.assertIn('asr_run.sh asr_transcribe.py --fingerprint exited 4: ERROR: the interpreter / stdlib / ASR venv differ from '
                      'asr_venv.manifest; first differences: < 9a1c  @VENV@/lib/python3.12/site-packages/mlx/core.py', g['reason'])
        self.assertEqual(1, g['reason'].count('setup_asr_venv.sh'))     # its own hint, not a second one

    # -- B2.7 binding, through the gate (rule c; rule a needs silences: AudioBindingTests)
    def test_raw_words_shifted_by_one_second_fail_the_binding(self):
        words = [(w['w'], round(w['s'] + 1.0, 3), round(w['e'] + 1.0, 3)) for pg in tf.PAGES for w in pg['words']]
        self.set_raw(tf.raw_doc(words=words))
        self.assertEqual(1, self.run_fin(), self.out)
        g = self.gate_rec('word-timing')
        self.assertEqual('fail', g['status'])
        self.assertIn('1.00 s of speech before the first raw word (limit 0.75 s): the words do not cover this audio', g['reason'])


# ---------------------------------------------------------------------------------------------- B2.7 rules (a) / (c), real silences
SPEECH_A = [(0.0, 2.0), (3.0, 5.0), (6.0, 8.5), (9.5, 11.5)]
SPEECH_B = [(0.0, 1.0), (1.6, 4.0), (5.0, 7.0), (8.0, 12.0)]


def speech_wav(path, spans, dur=12.0):
    on = '+'.join('between(t,%s,%s)' % (a, b) for a, b in spans)
    ffmpeg('-f', 'lavfi', '-i', "aevalsrc='gt(%s\\,0)*0.5*sin(2*PI*300*t)':s=16000:d=%s" % (on, dur), '-ac', '1', '-c:a', 'pcm_s16le',
           str(path))


def tiled_words(spans, step=0.25):
    out = []
    for a, b in spans:
        t = a
        while t + step <= b + 1e-9:
            out.append((round(t, 3), round(t + step, 3), 'w'))
            t += step
    return out


class AudioBindingTests(unittest.TestCase):
    """audio_binding() on silences that finalize's own detect_silences() measures on synthetic speech-like audio."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='binding-')).resolve()
        cls.m = load_finalize()
        cls.th = cls.m.timing_check_thresholds()
        ctx = types.SimpleNamespace(repo_root=cls.tmp)
        cls.sil = {}
        for name, spans in (('a', SPEECH_A), ('b', SPEECH_B)):
            wav = cls.tmp / name / 'vo16k.wav'
            wav.parent.mkdir()
            speech_wav(wav, spans)
            sil, err, _cls = cls.m.detect_silences(ctx, wav, cls.th, 30)
            assert err is None, err
            cls.sil[name] = sil

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def bind(self, words, audio='a'):
        return self.m.audio_binding(words, self.sil[audio], 12.0, self.th)

    def test_the_thresholds_are_the_ones_of_timing_check(self):
        th = chain_constant('timing_check.py', 'THRESHOLDS')
        for k in ('silence_noise_db', 'silence_min_s', 'silenceInteriorLeadS', 'silenceInteriorTrailS', 'maxInSilenceShare'):
            self.assertEqual(th[k], self.th[k], k)
        self.assertEqual((0.1, 0.4, 0.005), (self.th['silenceInteriorLeadS'], self.th['silenceInteriorTrailS'], self.th['maxInSilenceShare']))
        self.assertNotIn('0.005', ''.join(l for l in chain_source('finalize.py').splitlines() if not l.lstrip().startswith('#')))

    def test_the_silences_are_measured(self):
        self.assertEqual(4, len(self.sil['a']))         # 2-3, 5-6, 8.5-9.5, 11.5-12
        for (a, b), (x, y) in zip(self.sil['a'], [(2.0, 3.0), (5.0, 6.0), (8.5, 9.5), (11.5, 12.0)]):
            self.assertAlmostEqual(x, a, delta=0.05)
            self.assertAlmostEqual(y, b, delta=0.05)

    def test_honest_words_pass(self):
        m, p = self.bind(tiled_words(SPEECH_A))
        self.assertEqual([], p)
        self.assertEqual(0, m['wordsInSilence'])
        self.assertLessEqual(m['speechBeforeFirstWord'], 0.05)
        self.assertLessEqual(m['speechAfterLastWord'], 0.05)

    def test_words_shifted_by_one_second_fail_rule_a_and_rule_c(self):
        words = [(a + 1.0, b + 1.0, w) for a, b, w in tiled_words(SPEECH_A)]
        m, p = self.bind(words)
        self.assertGreater(m['inSilenceShare'], 0.005)
        self.assertTrue(any('lie inside silences of the audio' in x for x in p), p)
        self.assertTrue(any('of speech before the first raw word (limit 0.75 s)' in x for x in p), p)
        self.assertAlmostEqual(1.0, m['speechBeforeFirstWord'], delta=0.05)

    def test_the_raw_of_another_audio_fails(self):
        m, p = self.bind(tiled_words(SPEECH_B))
        self.assertTrue(any('lie inside silences of the audio' in x for x in p), p)
        self.assertGreater(m['inSilenceShare'], 0.005)

    def test_words_near_a_silence_edge_are_not_counted_only_its_interior(self):
        # a word overlapping the first 0.1 s / last 0.4 s of a silence is not "in silence" (timing_check's interior definition)
        words = tiled_words(SPEECH_A) + [(2.0, 2.09, 'edge'), (2.62, 2.95, 'edge')]
        m, p = self.bind(sorted(words))
        self.assertEqual(0, m['wordsInSilence'])
        self.assertEqual([], p)
        m, p = self.bind(sorted(tiled_words(SPEECH_A) + [(2.2, 2.5, 'inside')]))
        self.assertEqual(1, m['wordsInSilence'])

    def test_speech_after_the_last_word(self):
        words = [w for w in tiled_words(SPEECH_A) if w[1] <= 10.5]
        m, p = self.bind(words)
        self.assertAlmostEqual(1.0, m['speechAfterLastWord'], delta=0.05)
        self.assertTrue(any('after the last raw word (limit 0.75 s)' in x for x in p), p)


# ---------------------------------------------------------------------------------------------- B3 asr-recheck (--check)
class AsrRecheckTests(ChainBase):
    def test_check_retranscribes_into_a_new_empty_dir_and_passes_on_identical_bytes(self):
        self.assertEqual(0, self.run_fin('--check'), self.out)
        g = self.check_gate('asr-recheck')
        self.assertEqual('pass', g['status'])
        t = self.transcriptions()
        self.assertEqual(1, len(t))
        args = t[0]['argv']
        self.assertEqual('asr_transcribe.py', args[0])
        out = args[args.index('--out-dir') + 1]
        self.assertTrue(out.endswith('qc/finalize/asr-recheck/asr'), out)
        self.assertEqual([], t[0]['out_dir_entries'])                    # new and empty: no checkpoint can be resumed
        self.assertEqual(CHAIN_ENV, env_names(t[0]))
        self.assertEqual('pass', self.check_gate('word-timing')['status'])
        rep = json.loads((self.rdir / 'asr-recheck.json').read_text())
        self.assertEqual(rep['rawSha256']['retranscribed'], rep['rawSha256']['agent'])

    def test_a_stale_checkpoint_from_an_earlier_run_is_never_resumed(self):
        old = self.rdir / 'asr-recheck' / 'asr'
        old.mkdir(parents=True)
        (old / 'checkpoint.json').write_text('{}')
        self.assertEqual(0, self.run_fin('--check'), self.out)
        self.assertEqual([], self.transcriptions()[0]['out_dir_entries'])

    def test_a_byte_mismatch_names_the_first_differing_word(self):
        doc = json.loads(tf.RAW_TEXT[0])
        doc['segments'][0]['words'][1]['start'] = 0.31
        (self.asr / 'retranscribed.json').write_text(tf.raw_text(doc))
        self.assertEqual(1, self.run_fin('--check'), self.out)
        g = self.check_gate('asr-recheck')
        self.assertEqual('fail', g['status'])
        self.assertIn("raw_asr.json is not what this machine transcribes from the avatar audio (first differing raw word: segment 0 "
                      "word 1 'world' 0.31-0.6 (re-transcribed) vs 'world' 0.3-0.6 (agent))", g['reason'])
        self.assertTrue(g['reason'].endswith('re-run word_timing.sh, never hand-edit'), g['reason'])

    def test_a_difference_outside_the_words_is_named_too(self):
        doc = json.loads(tf.RAW_TEXT[0])
        doc['segments'][0]['avg_logprob'] = -0.25
        (self.asr / 'retranscribed.json').write_text(tf.raw_text(doc))
        self.assertEqual(1, self.run_fin('--check'), self.out)
        self.assertIn('first differing raw segment 0: avg_logprob', self.check_gate('asr-recheck')['reason'])

    def test_exit_5_still_defective_is_a_quality_failure_with_the_defect_lines(self):
        self.asr_behavior(transcribe={'exit': 5, 'stdout': 'R0 done\nDEFECT raw-gap 12.00-16.50 value 4.5 limit 3.0\n'})
        self.assertEqual(1, self.run_fin('--check'), self.out)
        g = self.check_gate('asr-recheck')
        self.assertEqual('fail', g['status'])
        self.assertIn('still defective after the fixed repair ladder (asr_transcribe.py exit 5): DEFECT raw-gap 12.00-16.50', g['reason'])
        self.assertEqual(['DEFECT raw-gap 12.00-16.50 value 4.5 limit 3.0'], g['issues'])

    def test_exit_4_of_the_transcription_is_a_tool_failure(self):
        self.asr_behavior(transcribe={'exit': 4, 'stderr': 'ERROR: model not cached\n'})
        self.assertEqual(4, self.run_fin('--check'), self.out)
        self.assertEqual('missing', self.check_gate('asr-recheck')['status'])

    def test_a_toolchain_difference_is_exit_4_and_nothing_is_transcribed(self):
        self.asr_behavior(fingerprint_patch={'model': dict(tf.FAKE_FP['model'], snapshot='0' * 40)})
        self.assertEqual(4, self.run_fin('--check'), self.out)
        for name in ('asr-recheck', 'word-timing'):
            g = self.check_gate(name)
            self.assertEqual('missing', g['status'], name)
            self.assertIn('the transcription toolchain differs from production: model.snapshot: ', g['reason'])
        self.assertEqual([], self.transcriptions())
        self.assertEqual(1, len([c for c in self.asr_calls() if '--fingerprint' in c['argv']]))   # measured once per run

    def test_running_out_of_time_is_timeout_exit_4_retry_when_idle(self):
        self.asr_behavior(transcribe={'sleep': 30})
        code = self.run_fin('--check', patch=lambda m: m.GATE_BY_NAME['asr-recheck'].update(limit=2))
        self.assertEqual(4, code, self.out)
        g = self.check_gate('asr-recheck')
        self.assertEqual('timeout', g['status'])
        self.assertEqual('when-idle', g['retry'])
        self.assertEqual('timeout: --check did not finish within 600 s — re-run when no render / GPU job is running (this is not a '
                         'content failure)', g['reason'])
        doc = self.check_doc()
        self.assertEqual((4, False), (doc['exit_code'], doc['would_deliver']))
        self.assertEqual('when-idle', doc['retry'])

    def test_the_recheck_runs_in_its_own_lane_beside_the_other_gates(self):
        self.asr_behavior(transcribe={'sleep': 3})
        self.behavior(lint_beats={'sleep': 3})
        import time
        t0 = time.monotonic()
        self.assertEqual(0, self.run_fin('--check'), self.out)
        self.assertLess(time.monotonic() - t0, 5.9)                      # 3 s + 3 s would be serial


# ---------------------------------------------------------------------------------------------- the chain's constants
def launcher_array(name):
    """A bash array constant of the landed asr_run.sh, e.g. FFMPEG_CANDIDATES=(a b c) -> ('a', 'b', 'c')."""
    line = next(l for l in chain_source('asr_run.sh').splitlines() if l.startswith(name + '=('))
    return tuple(shlex.split(line[len(name) + 2:line.rindex(')')]))


class ChainContractTests(unittest.TestCase):
    """finalize mirrors a few constants of the chain (it never imports it): each mirror must equal the LANDED chain's own value."""

    @classmethod
    def setUpClass(cls):
        cls.m = load_finalize()

    def test_ffmpeg_candidates_equal_the_launcher_the_chain_and_timing_defects(self):
        self.assertEqual(chain_constant('asr_transcribe.py', 'FFMPEG_CANDIDATES'), self.m.CHAIN_FFMPEG_CANDIDATES)
        self.assertEqual(chain_constant('timing_defects.py', 'FFMPEG_CANDIDATES'), self.m.CHAIN_FFMPEG_CANDIDATES)
        self.assertEqual(launcher_array('FFMPEG_CANDIDATES'), self.m.CHAIN_FFMPEG_CANDIDATES)

    def test_the_launcher_is_the_only_way_in(self):
        self.assertEqual(SCRIPTS / 'asr_run.sh', self.m.ASR_RUN)          # the certified checkout's own launcher
        self.assertEqual('/bin/bash', self.m.SYSTEM_BASH)
        self.assertEqual(['/bin/bash', str(SCRIPTS / 'asr_run.sh'), 'asr_align.py', '--raw', 'r'], self.m.asr_cmd('asr_align.py', '--raw', 'r'))
        self.assertEqual(('asr_transcribe.py', 'asr_align.py', 'source_timed.py'), launcher_array('CHAIN_SCRIPTS'))
        # timing_defects.py is not a launcher script; finalize runs it with the chain's own isolation flags under its interpreter
        self.assertNotIn('timing_defects.py', launcher_array('CHAIN_SCRIPTS'))
        self.assertEqual(chain_constant('asr_transcribe.py', 'RUN_FLAGS'), self.m.DEFECTS_FLAGS)
        self.assertEqual(chain_constant('asr_align.py', 'RUN_FLAGS'), self.m.DEFECTS_FLAGS)
        self.assertEqual([sys.executable, *DEFECTS_FLAGS, str(SCRIPTS / 'timing_defects.py'), '--pages', 'p'], self.m.defects_cmd('--pages', 'p'))
        exec_line = ' '.join(l.strip() for l in chain_source('asr_run.sh').splitlines() if '"$PYBIN"' in l and 'pycache_prefix' in l)
        self.assertIn('"$PYBIN" -I -S -B -X pycache_prefix=/var/empty', exec_line)
        # finalize knows no interpreter or venv of the chain, and starts no shell / python by bare name
        src = chain_source('finalize.py')
        for word in ('bin/python', 'karaoke', 'VENV_ROOT', '.cache/yt-news-v4', 'asr-venv'):
            self.assertNotIn(word, src)
        literals = {n.value for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        self.assertEqual(set(), literals & {'bash', 'sh', 'python3', 'python3.12'})      # ('python' is the interpreter KIND of a gate)
        for gone in ('ASR_PY', 'ASR_RUN_FLAGS', 'chain_venv_root', 'chain_asr_python', 'asr_python_problem'):
            self.assertFalse(hasattr(self.m, gone), gone)

    def test_the_environment_is_the_chains_minimal_env(self):
        tree = ast.parse(chain_source('asr_transcribe.py'))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'minimal_env')
        ret = next(n.value for n in ast.walk(fn) if isinstance(n, ast.Return))
        self.assertEqual({k.value for k in ret.keys}, set(self.m.asr_env()))
        self.assertEqual(chain_constant('asr_transcribe.py', 'ENV_LANG'), self.m.ASR_LANG)
        self.assertEqual(chain_constant('asr_transcribe.py', 'ENV_TMPDIR'), self.m.ASR_TMPDIR)
        ff = next(c for c in self.m.CHAIN_FFMPEG_CANDIDATES if os.access(c, os.X_OK))
        self.assertEqual({'HOME': pwd.getpwuid(os.getuid()).pw_dir, 'PATH': os.path.dirname(ff) + ':/usr/bin:/bin', 'LANG': 'en_US.UTF-8',
                          'TMPDIR': '/var/empty'}, self.m.asr_env())

    def test_params_code_files_schema_and_the_wav_extraction(self):
        self.assertEqual(json.loads(json.dumps(chain_constant('asr_transcribe.py', 'PARAMS'))), self.m.ASR_PARAMS)
        self.assertEqual(chain_constant('asr_transcribe.py', 'CODE_FILES'), self.m.CHAIN_CODE_FILES)
        self.assertIn('asr_run.sh', self.m.CHAIN_CODE_FILES)
        self.assertEqual(chain_constant('asr_align.py', 'RAW_SCHEMA'), self.m.RAW_ASR_SCHEMA)
        # the extraction line of word_timing.sh step 1, token for token
        line = next(l for l in chain_source('word_timing.sh').splitlines() if l.strip().startswith('asr_env "$FFMPEG"'))
        toks = shlex.split(line.split('||')[0].strip().rstrip('\\').strip(), posix=False)[2:]
        self.assertEqual([{'"$AUDIO"': '{avatar}', '"$WAV"': '{wav}'}.get(x, x) for x in toks], list(self.m.WAV_EXTRACT))
        self.assertEqual(['-v', 'error', '-y', '-i', '{avatar}', '-vn', '-map_metadata', '-1', '-ac', '1', '-ar', '16000', '-c:a',
                          'pcm_s16le', '-fflags', '+bitexact', '-flags:a', '+bitexact', '{wav}'], list(self.m.WAV_EXTRACT))

    def test_compare_fingerprint_is_the_chains_own(self):
        tree = ast.parse(chain_source('asr_transcribe.py'))
        keep = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in ('compare_fingerprint', '_show'))
                or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_MISSING' for t in n.targets))]
        self.assertEqual(3, len(keep))
        ns = {'json': json}
        exec(compile(ast.Module(body=keep, type_ignores=[]), 'asr_transcribe.py', 'exec'), ns)
        other_manifest = dict(tf.FAKE_FP, venv=dict(tf.FAKE_FP['venv'], manifest_sha256='c' * 64))
        cases = [({'a': 1}, {'a': 1}), ({'a': 1}, {'a': 2}), ({'a': {'b': [1, 2]}}, {'a': {'b': [1]}}), ({'a': 1}, {}),
                 ({}, {'x': {'y': 'z'}}), ({'v': '1'}, {'v': 1}), ({'l': [1, {'k': True}]}, {'l': [1, {'k': False}]}),
                 (dict(tf.FAKE_FP), dict(tf.FAKE_FP, mlx={'version': '0.32'})), (dict(tf.FAKE_FP), other_manifest),
                 (dict(tf.FAKE_FP, venv={'python': {'version': '3.12.0'}, 'distributions': {}}), dict(tf.FAKE_FP))]
        for a, b in cases:
            self.assertEqual(ns['compare_fingerprint'](a, b), self.m.compare_fingerprint(a, b), (a, b))
        self.assertEqual(['venv.manifest_sha256: %s (production) != %s (this machine)' % ('b' * 64, 'c' * 64)],
                         self.m.compare_fingerprint(dict(tf.FAKE_FP), other_manifest))

    def test_the_fingerprint_keys_of_a_real_raw_are_the_chains(self):
        self.assertEqual(set(chain_constant('asr_transcribe.py', 'FINGERPRINT_KEYS')), set(tf.FAKE_FP) | {'params', 'code'})


# ---------------------------------------------------------------------------------------------- B8 issue summaries
class IssueSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_finalize()

    def test_errors_first_then_warnings_with_counts(self):
        data = {'issues': [{'severity': 'warn', 'code': 'w1', 'detail': 'first warning'}, {'severity': 'warn', 'code': 'w2', 'detail': 'w'},
                           {'severity': 'warn', 'code': 'w3', 'detail': 'w'}, {'severity': 'error', 'code': 'e1', 'detail': 'the error'},
                           {'severity': 'error', 'code': 'e2', 'at': 3.0}, {'code': 'u1', 'detail': 'unrated'}]}
        out = self.m.summarize_issues(data, limit=0)
        self.assertEqual('issues: 2 error, 1 unrated, 3 warn', out[0])
        self.assertEqual(['e1: the error', 'e2 x1, first 1: [@3s severity=error]', 'u1: unrated', 'w1: first warning'], out[1:5])
        self.assertEqual(['issues: 2 error, 1 unrated, 3 warn', 'e1: the error', 'e2 x1, first 1: [@3s severity=error]'],
                         self.m.summarize_issues(data))           # the default 3 lines never end on a warning before an error

    def test_an_error_of_a_later_list_comes_before_a_warning_of_an_earlier_one(self):
        out = self.m.summarize_issues({'issues': [{'level': 'Warning', 'message': 'w'}] * 3, 'errors': [{'message': 'boom'}]})
        self.assertEqual(['issues: 3 warning', 'errors: boom', 'issues: w'], out)

    def test_without_severities_the_file_order_is_kept(self):
        out = self.m.summarize_issues({'issues': [{'code': 'a', 'detail': 'x'}, {'code': 'b', 't': 1.0}, {'code': 'c', 'detail': 'y'}]},
                                      limit=0)
        self.assertEqual(['a: x', 'b x1, first 1: [@1s]', 'c: y'], out)

    def test_a_gate_record_shows_its_errors_first(self):
        pass                                        # through a real gate: GateRecordSummaryTests


class GateRecordSummaryTests(ChainBase):
    def test_a_failed_gate_lists_its_error_before_its_warnings(self):
        self.behavior(lint_beats={'exit': 1, 'pass': False, 'issues': [
            {'severity': 'warn', 'code': 'pace', 'detail': 'slow'}, {'severity': 'warn', 'code': 'pace', 'detail': 'slow 2'},
            {'severity': 'warn', 'code': 'pace', 'detail': 'slow 3'}, {'severity': 'error', 'code': 'beat-gap', 'detail': 'gap at 3 s'}]})
        self.assertEqual(1, self.run_fin(), self.out)
        g = self.gate_rec('beats')
        self.assertEqual(['issues: 1 error, 3 warn', 'beat-gap: gap at 3 s', 'pace: slow'], g['issues'])


# ---------------------------------------------------------------------------------------------- B9 symbolic links
class SymlinkTests(ChainBase):
    def assertRefused(self, *argv, link=None):
        code = self.run_argv(argv)
        self.assertEqual(2, code, self.out)
        self.assertIn('goes through the symbolic link', self.out)
        if link is not None:
            self.assertIn(str(link), self.out)
        self.assertFalse(self.deliver.exists())

    def snapshot(self):
        return tree_state(self.proj)

    def test_a_symlinked_project_dir_is_refused_and_nothing_is_written_through_it(self):
        link = self.repo / 'projects' / 'p2'
        link.symlink_to(self.proj)
        before = self.snapshot()
        self.assertRefused('--project', 'projects/p2', '--deliver', self.deliver, link=link)
        self.assertRefused('--project', 'projects/p2', '--deliver', self.deliver, '--check', link=link)
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.proj / 'qc' / 'finalize' / 'check.json').exists())

    def test_a_symlinked_ancestor_below_the_repo_is_refused(self):
        link = self.repo / 'alias'
        link.symlink_to(self.repo / 'projects')
        before = self.snapshot()
        self.assertRefused('--project', 'alias/p1', '--deliver', self.deliver, link=link)
        self.assertRefused('--project', str(link / 'p1'), '--deliver', self.deliver, '--check', link=link)
        self.assertEqual(before, self.snapshot())

    def test_a_symlinked_artifacts_dir_is_refused_even_when_it_stays_inside_the_project(self):
        art = self.proj / 'artifacts'
        art.rename(self.proj / 'artifacts.real')
        art.symlink_to(self.proj / 'artifacts.real')
        self.assertRefused('--project', 'projects/p1', '--deliver', self.deliver, link=art)

    def test_a_symlinked_episode_json_is_refused(self):
        ep = self.proj / 'artifacts' / 'episode.json'
        ep.rename(self.proj / 'artifacts' / 'episode.real.json')
        ep.symlink_to(self.proj / 'artifacts' / 'episode.real.json')
        self.assertRefused('--project', 'projects/p1', '--deliver', self.deliver, link=ep)

    def test_a_symlinked_raw_asr_json_of_another_project_is_refused(self):
        other = Path(self.tmp) / 'elsewhere'
        other.mkdir()
        shutil.copy(self.raw, other / 'raw_asr.json')
        self.raw.unlink()
        self.raw.symlink_to(other / 'raw_asr.json')
        self.assertRefused('--project', 'projects/p1', '--deliver', self.deliver, link=self.raw)

    def test_clean_checkout_check_refuses_a_symlinked_project_or_public_root(self):
        wd = Path(self.tmp) / 'wd'
        wd.mkdir()
        public = self.repo / 'remotion-composer' / 'public'
        plink = Path(self.tmp) / 'proj-link'
        plink.symlink_to(self.proj)
        publink = Path(self.tmp) / 'public-link'
        publink.symlink_to(public)
        before = self.snapshot()
        self.assertRefused('--project', plink, '--deliver', self.deliver, '--check', '--public-root', public, '--work-dir', wd / '1', link=plink)
        self.assertRefused('--project', self.proj, '--deliver', self.deliver, '--check', '--public-root', publink, '--work-dir', wd / '2',
                           link=publink)
        self.assertEqual(before, self.snapshot())
        for n in ('1', '2'):                     # the refusal is the result of the run, in the work dir (never through the link)
            doc = json.loads((wd / n / 'check.json').read_text())
            self.assertEqual(2, doc['exit_code'])
            self.assertIn('goes through the symbolic link', ' '.join(doc['reasons']))

    def test_the_real_paths_still_pass(self):
        self.assertEqual(0, self.run_argv(['--project', 'projects/p1', '--deliver', self.deliver]), self.out)


if __name__ == '__main__':
    unittest.main()
