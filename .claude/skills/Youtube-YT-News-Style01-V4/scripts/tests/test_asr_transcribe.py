"""asr_transcribe.py: pins, raw_asr.json contract, and the fixed repair ladder.  Whisper is never run here: the model
call is replaced by passing a fake to run_ladder(..., transcribe_fn=fake, env_info=...).  The wav is synthetic (440 Hz
tone where the fake "speaks", digital silence in between) so the real ffmpeg silencedetect plans the repair regions."""
import ast
import hashlib
import json
import os
from pathlib import Path
import pwd
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock
import wave

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import asr_transcribe as at  # noqa: E402
import asr_align as aa  # noqa: E402
import timing_defects as td  # noqa: E402

SR = 16000
# how the chain is started (the scripts refuse otherwise): the Cellar python that asr_run.sh pins, directly (these tests are not
# about the launcher, test_asr_run.py is) with the four flags the launcher adds + the marker of the manifest it verified
PYROOT = re.search(r'^PYROOT=(.*)$', (SCRIPTS / 'asr_run.sh').read_text(encoding='utf-8'), re.M).group(1)
PYBIN = Path(PYROOT) / 'bin' / 'python3.12'
MANIFEST_SHA = hashlib.sha256((SCRIPTS / at.MANIFEST_NAME).read_bytes()).hexdigest() if (SCRIPTS / at.MANIFEST_NAME).exists() else '0' * 64
BASE_RUN = [str(PYBIN), '-I', '-S', '-B', '-X', 'pycache_prefix=/var/empty']
RUN = [*BASE_RUN, '-X', 'asr_manifest_sha256=' + MANIFEST_SHA]
PW_HOME = pwd.getpwuid(os.getuid()).pw_dir
HAVE_CHAIN = PYBIN.exists() and (Path(at.SITE_DIR) / 'pythainlp').is_dir()          # the real V4 venv (the scripts append it themselves)


def chain_pythainlp_version():
    """the pythainlp the CHAIN will see = the V4 venv's (its dist-info), never the test runner's interpreter: the launcher runs the chain
    from the V4 venv, and asr_align.py exits 4 when raw_asr.json was written with another tokenizer version"""
    found = sorted(Path(at.SITE_DIR).glob('pythainlp-*.dist-info'))
    if len(found) == 1:
        return found[0].name[len('pythainlp-'):-len('.dist-info')]
    import pythainlp
    return pythainlp.__version__                                                  # no V4 venv here: the CLI tests are skipped anyway


CHAIN_PYTHAINLP = chain_pythainlp_version()
NATO = ('alpha bravo charlie delta echo foxtrot golf hotel india juliett kilo lima mike november oscar papa quebec '
        'romeo sierra tango uniform victor whiskey xray yankee zulu one two three').split()
ENV = {'model': {'id': at.MODEL_ID, 'snapshot': 'fake-snapshot',
                 'files': {'config.json': 'a' * 40, 'weights.npz': 'b' * 64}},
       'mlx_whisper': {'version': 'fake', 'files': {'decoding.py': 'c' * 64}},
       'mlx': {'version': '0.0.1', 'mlx-metal': '0.0.1'},
       'tokenizer': {'pythainlp': CHAIN_PYTHAINLP},
       'platform': {'system': 'Darwin', 'release': '1.0', 'machine': 'arm64', 'mac_ver': '99.0', 'cpu': 'Fake M9'},
       'ffmpeg': {'realpath': '/fake/bin/ffmpeg', 'sha256': 'd' * 64, 'version': 'ffmpeg version 0.0 Fake'},
       'venv': {'manifest_sha256': '3' * 64, 'python': '3.12.0 (fake)'},
       'snapshot_dir': '/should/never/reach/the/raw/file', 'site_dir': '/should/never/reach/the/raw/site'}


def make_wav(path, tone_spans, total):
    t = np.arange(int(round(total * SR))) / SR
    sig = np.zeros_like(t)
    for a, b in tone_spans:
        m = (t >= a) & (t < b)
        sig[m] = 0.4 * np.sin(2 * np.pi * 440 * t[m])
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((sig * 32767).astype('<i2').tobytes())


def wseg(words):
    """[(word, s, e)] -> one whisper-style segment (with fields raw_asr.json must drop)"""
    ws = [{'word': ' ' + w, 'start': s, 'end': e, 'probability': 0.9} for w, s, e in words]
    return {'id': 0, 'seek': 0, 'tokens': [1, 2], 'temperature': 0.0, 'start': words[0][1], 'end': words[-1][2],
            'text': ''.join(w['word'] for w in ws), 'compression_ratio': 1.3, 'avg_logprob': -0.25,
            'no_speech_prob': 0.02, 'words': ws}


def run_of(names, t0, dur=0.5, gap=0.45):
    out, t = [], t0
    for n in names:
        out.append((n, round(t, 2), round(t + dur, 2)))
        t += dur + gap
    return out


# timeline of the main fixture (40 s): tone 0-10, 11-18, 18.6-30, 31-40; silences 10-11, 18-18.6, 30-31
TONES = [(0.0, 10.0), (11.0, 18.0), (18.6, 30.0), (31.0, 40.0)]
BLOCK1 = run_of(NATO[0:10], 0.2)                      # ends 9.25
BLOCK2 = run_of(NATO[10:17], 11.2)                    # ends 17.4
# a word ends where the next one starts (apply_script), so speech must be continuous: < 3 s of speech between raw starts (raw-gap)
BLOCK3_OK = [('romeo', 18.8, 19.3), ('sierra', 21.7, 22.2), ('tango', 24.6, 25.1), ('uniform', 27.5, 28.0)]
BLOCK3_BAD = [('romeo', 18.8, 19.3), ('sierra', 19.5, 27.42), ('tango', 27.6, 28.1), ('uniform', 28.3, 28.8)]  # sierra 8.1 s
BLOCK4 = run_of(NATO[21:29], 31.2)                    # ends 38.35
SCRIPT_WORDS = [w for w, _, _ in BLOCK1 + BLOCK2 + BLOCK3_OK + BLOCK4]


class Fake:
    """records every call; full-length calls get `full`, shorter (region) calls get region_fn(n_samples)"""
    def __init__(self, full_len, full, region_fn=None, fail_region=False, full_len_override=None):
        self.full_len, self.full, self.region_fn, self.fail_region = full_len, full, region_fn, fail_region
        self.full_len_override = full_len_override      # -1: every call is a "region" call (so fail_region kills even the first pass)
        self.calls = []

    def __call__(self, samples):
        self.calls.append(np.array(samples, copy=True))
        if len(samples) == self.full_len and self.full_len_override is None:
            return {'segments': self.full}
        if self.fail_region:
            raise RuntimeError('killed while decoding a region')
        return {'segments': self.region_fn(len(samples))}


def region_words(n_samples, long_word=False):
    """the fake re-decode of the 18.3-30.5 region in LOCAL time"""
    if long_word:
        words = [('romeo', 0.6, 1.1), ('sierra', 1.3, 9.2), ('tango', 9.4, 9.9), ('uniform', 10.1, 10.6)]
    else:
        words = [('romeo', 0.6, 1.1), ('sierra', 3.4, 3.9), ('tango', 6.3, 6.8), ('uniform', 9.2, 9.7)]
    assert n_samples / SR > 10.7, n_samples
    return [wseg(words)]


class LadderBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.wav = self.d / 'vo16k.wav'
        make_wav(self.wav, TONES, 40.0)
        self.script = self.d / 'script.txt'
        self.script.write_text(' '.join(SCRIPT_WORDS[:10]) + '\n' + ' '.join(SCRIPT_WORDS[10:21]) + '\n'
                               + ' '.join(SCRIPT_WORDS[21:]) + '\n', encoding='utf-8')
        self.n = 40 * SR

    def tearDown(self):
        self.tmp.cleanup()

    def out(self, name='out'):
        p = self.d / name
        p.mkdir(exist_ok=True)
        return p

    def full(self, bad=True):
        return [wseg(BLOCK1), wseg(BLOCK2), wseg(BLOCK3_BAD if bad else BLOCK3_OK), wseg(BLOCK4)]

    def ladder(self, fake, out):
        return at.run_ladder(self.wav, self.script, out, transcribe_fn=fake, env_info=ENV)

    def raw(self, out):
        return json.loads((out / at.RAW_NAME).read_text(encoding='utf-8'))


class RawContractTests(LadderBase):
    def test_clean_r0_raw_schema_and_byte_identical_reruns(self):
        fakes, texts = [], []
        for name in ('a', 'b'):
            fake = Fake(self.n, self.full(bad=False))
            self.assertEqual(0, self.ladder(fake, self.out(name)))
            fakes.append(fake)
            texts.append((self.out(name) / at.RAW_NAME).read_bytes())
            time.sleep(1.1)                                   # a clock value anywhere would now differ
        self.assertEqual(texts[0], texts[1])
        self.assertEqual([1, 1], [len(f.calls) for f in fakes])
        self.assertEqual(self.n, len(fakes[0].calls[0]))
        raw = self.raw(self.out('a'))
        self.assertEqual(['schema', 'version', 'audio', 'script_sha256', 'model', 'mlx_whisper', 'mlx', 'tokenizer',
                          'platform', 'ffmpeg', 'venv', 'params', 'code', 'rungs', 'segments'], list(raw))
        self.assertEqual(('yt-news-v4-raw-asr', 1), (raw['schema'], raw['version']))
        self.assertEqual(ENV['ffmpeg'], raw['ffmpeg'])
        self.assertEqual(ENV['venv'], raw['venv'])
        self.assertEqual({'wav_sha256': at.sha_file(self.wav), 'duration': 40.0}, raw['audio'])
        self.assertEqual(at.sha_file(self.script), raw['script_sha256'])
        self.assertEqual({'language': 'th', 'temperature': [0.0], 'condition_on_previous_text': False,
                          'word_timestamps': True}, raw['params'])
        self.assertEqual([{'rung': 'R0', 'regions': [[0.0, 40.0]], 'seconds': 40.0}], raw['rungs'])
        seg = raw['segments'][0]
        self.assertEqual(['start', 'end', 'text', 'compression_ratio', 'avg_logprob', 'no_speech_prob', 'rung', 'words'], list(seg))
        self.assertEqual('R0', seg['rung'])
        self.assertEqual({'word': ' alpha', 'start': 0.2, 'end': 0.7}, seg['words'][0])
        self.assertFalse((self.out('a') / at.FAILED_NAME).exists())
        self.assertEqual([], [p.name for p in self.out('a').iterdir() if '.tmp' in p.name])
        # the CLI aligner accepts the file and re-derives the same pages the ladder checked
        pages = self.d / 'pages.json'
        r = subprocess.run([*RUN, str(SCRIPTS / 'asr_align.py'), '--raw', str(self.out('a') / at.RAW_NAME),
                            '--script', str(self.script), '--out', str(pages)], capture_output=True, text=True)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(SCRIPT_WORDS, [w['w'] for p in json.loads(pages.read_text(encoding='utf-8')) for w in p['words']])

    def test_samples_are_int16_over_32768(self):
        samples, sha, dur = at.read_wav(self.wav)
        with wave.open(str(self.wav), 'rb') as w:
            ints = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2')
        self.assertEqual(np.float32, samples.dtype)
        self.assertTrue(np.array_equal(ints.astype(np.float32) / 32768.0, samples))
        self.assertEqual(40.0, dur)

    def test_wav_must_be_16k_mono_16bit(self):
        for ch, rate in ((2, 16000), (1, 44100)):
            p = self.d / ('w%d_%d.wav' % (ch, rate))
            with wave.open(str(p), 'wb') as w:
                w.setnchannels(ch)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(b'\x00\x00' * ch * 100)
            with self.assertRaises(at.InputError):
                at.read_wav(p)
        with self.assertRaises(at.InputError):
            at.read_wav(self.script)


class LadderTests(LadderBase):
    def test_r1_re_decodes_the_defect_region_between_silences(self):
        fake = Fake(self.n, self.full(), region_fn=region_words)
        out = self.out()
        self.assertEqual(0, self.ladder(fake, out))
        raw = self.raw(out)
        self.assertEqual(['R0', 'R1'], [r['rung'] for r in raw['rungs']])
        (lo, hi), = raw['rungs'][1]['regions']
        self.assertAlmostEqual(18.3, lo, delta=0.03)          # midpoint of the 18.0-18.6 silence (pad 3 s -> 16.5)
        self.assertAlmostEqual(30.5, hi, delta=0.03)          # midpoint of the 30-31 silence
        self.assertEqual(round(hi - lo, 2), raw['rungs'][1]['seconds'])
        self.assertEqual(2, len(fake.calls))
        samples, _, _ = at.read_wav(self.wav)
        self.assertTrue(np.array_equal(samples[int(round(lo * SR)):int(round(hi * SR))], fake.calls[1]))
        r1 = [s for s in raw['segments'] if s['rung'] == 'R1']
        self.assertEqual([(' romeo', round(0.6 + lo, 2)), (' sierra', round(3.4 + lo, 2)), (' tango', round(6.3 + lo, 2)),
                          (' uniform', round(9.2 + lo, 2))], [(w['word'], w['start']) for s in r1 for w in s['words']])
        r0_words = [(w['word'], w['start'], w['end']) for s in raw['segments'] if s['rung'] == 'R0' for w in s['words']]
        self.assertEqual([(' ' + w, s, e) for w, s, e in BLOCK1 + BLOCK2 + BLOCK4], r0_words)
        starts = [s['words'][0]['start'] for s in raw['segments']]
        self.assertEqual(sorted(starts), starts)
        pages, _ = aa.align(raw, self.script.read_text(encoding='utf-8').splitlines())
        self.assertEqual([], td.find_defects(pages, raw, at.detect_silences(self.wav)))

    def test_still_defective_after_r1_exits_5_with_a_failure_report(self):
        fake = Fake(self.n, self.full(), region_fn=lambda n: region_words(n, long_word=True))
        out = self.out()
        with _Capture() as cap:
            self.assertEqual(5, self.ladder(fake, out))
        self.assertFalse((out / at.RAW_NAME).exists())
        failed = json.loads((out / at.FAILED_NAME).read_text(encoding='utf-8'))
        self.assertEqual(('yt-news-v4-word-timing-failed', 'R1'), (failed['schema'], failed['rung']))
        self.assertTrue(failed['reason'].startswith('exhausted; '), failed['reason'])
        self.assertIn('raw-gap: > 3 s of non-silent audio without words - music or effects in the presenter track are not supported; '
                      'this is not retryable', failed['reason'])                      # N3: the explicit unrepairable-raw-gap message
        self.assertEqual(1, len(failed['regions']))
        codes = {d['code'] for d in failed['defects']}
        self.assertEqual({'word-too-long', 'word-slow', 'raw-word-too-long', 'raw-gap'}, codes)      # the page rules and the raw rules
        d = [x for x in failed['defects'] if x['code'] == 'word-too-long'][0]
        self.assertEqual('sierra', d['token'])
        self.assertEqual(4.0, d['limit'])
        self.assertGreater(d['value'], 6.0)            # 8.1 s raw span minus the share of the leading space
        self.assertIn('DEFECT word-too-long at %.3fs token="sierra" value=%s limit=4.0' % (d['start'], d['value']), cap.text)
        self.assertIn('WORD_TIMING FAILED at rung R1', cap.text)
        self.assertIn('music or effects in the presenter track are not supported', cap.text)

    def test_success_after_a_failure_removes_the_failure_report(self):
        out = self.out()
        with _Capture():
            self.assertEqual(5, self.ladder(Fake(self.n, self.full(), region_fn=lambda n: region_words(n, True)), out))
        self.script.write_text(self.script.read_text(encoding='utf-8') + '\n', encoding='utf-8')   # new input
        self.assertEqual(0, self.ladder(Fake(self.n, self.full(), region_fn=region_words), out))
        self.assertFalse((out / at.FAILED_NAME).exists())

    def test_too_many_regions_is_systemic_and_nothing_is_re_decoded(self):
        make_wav(self.wav, [(0.0, 120.0)], 120.0)            # no silence at all: regions are the +-3 s pads
        words, names, t = [], iter(NATO * 4), 1.0
        for k in range(7):                                    # 7 long words ~14 s apart -> 7 separate regions
            for _ in range(10):
                words.append((next(names), round(t, 2), round(t + 0.5, 2)))
                t += 0.95
            words.append((next(names), round(t, 2), round(t + 4.5, 2)))
            t += 4.7
        for _ in range(4):
            words.append((next(names), round(t, 2), round(t + 0.5, 2)))
            t += 0.95
        self.script.write_text(' '.join(w for w, _, _ in words) + '\n', encoding='utf-8')
        fake = Fake(120 * SR, [wseg(words)], region_fn=lambda n: self.fail('a systemic plan must not decode'))
        out = self.out()
        with _Capture() as cap:
            self.assertEqual(5, self.ladder(fake, out))
        self.assertEqual(1, len(fake.calls))
        failed = json.loads((out / at.FAILED_NAME).read_text(encoding='utf-8'))
        self.assertEqual('R1', failed['rung'])
        self.assertTrue(failed['reason'].startswith('systemic'))
        self.assertEqual(7, len(failed['regions']))
        self.assertGreaterEqual(len(failed['defects']), 7)
        self.assertIn('systemic', cap.text)

    def test_killed_job_resumes_after_the_last_finished_rung(self):
        out = self.out()
        with self.assertRaises(at.ToolError):
            self.ladder(Fake(self.n, self.full(), fail_region=True), out)
        self.assertTrue((out / 'asr_rung_R0.json').exists())
        self.assertFalse((out / at.RAW_NAME).exists())
        fake = Fake(self.n, self.full(), region_fn=region_words)
        self.assertEqual(0, self.ladder(fake, out))
        self.assertEqual([False], [len(c) == self.n for c in fake.calls])     # only the region was decoded
        again = Fake(self.n, self.full(), region_fn=region_words)
        self.assertEqual(0, self.ladder(again, out))
        self.assertEqual([], again.calls)                                     # both rungs resumed
        clean = self.out('uninterrupted')
        self.assertEqual(0, self.ladder(Fake(self.n, self.full(), region_fn=region_words), clean))
        self.assertEqual((clean / at.RAW_NAME).read_bytes(), (out / at.RAW_NAME).read_bytes())

    def test_checkpoint_of_other_inputs_is_not_reused(self):
        out = self.out()
        self.assertEqual(0, self.ladder(Fake(self.n, self.full(bad=False)), out))
        make_wav(self.wav, [(0.0, 9.0), (11.0, 18.0), (18.6, 30.0), (31.0, 40.0)], 40.0)   # other audio
        fake = Fake(self.n, self.full(bad=False))
        self.assertEqual(0, self.ladder(fake, out))
        self.assertEqual(1, len(fake.calls))
        ck = json.loads((out / 'asr_rung_R0.json').read_text(encoding='utf-8'))
        ck['key'] = '0' * 64                                                   # a checkpoint with another key
        (out / 'asr_rung_R0.json').write_text(json.dumps(ck), encoding='utf-8')
        fake = Fake(self.n, self.full(bad=False))
        self.assertEqual(0, self.ladder(fake, out))
        self.assertEqual(1, len(fake.calls))

    def test_a_failed_run_never_leaves_the_previous_runs_result_behind(self):
        out = self.out()
        self.assertEqual(0, self.ladder(Fake(self.n, self.full(bad=False)), out))
        self.assertTrue((out / at.RAW_NAME).exists())
        (out / at.FAILED_NAME).write_text('{"stale": true}')
        make_wav(self.wav, [(0.0, 9.5), (11.0, 18.0), (18.6, 30.0), (31.0, 40.0)], 40.0)           # other audio: no checkpoint applies
        with self.assertRaises(at.ToolError):                                  # exit 4: the decoder dies
            self.ladder(Fake(self.n, self.full(), fail_region=True, full_len_override=-1), out)
        self.assertFalse((out / at.RAW_NAME).exists())
        self.assertFalse((out / at.FAILED_NAME).exists())
        # exit 5 (ladder exhausted): the old raw is gone, only the failure report exists
        self.assertEqual(0, self.ladder(Fake(self.n, self.full(bad=False)), self.out('b')))
        self.assertTrue((self.out('b') / at.RAW_NAME).exists())
        self.script.write_text(self.script.read_text(encoding='utf-8') + '\n', encoding='utf-8')
        make_wav(self.wav, TONES, 40.0)
        with _Capture():
            self.assertEqual(5, self.ladder(Fake(self.n, self.full(), region_fn=lambda n: region_words(n, True)), self.out('b')))
        self.assertFalse((self.out('b') / at.RAW_NAME).exists())
        self.assertTrue((self.out('b') / at.FAILED_NAME).exists())
        # exit 2 (unusable input): nothing stale either
        self.assertEqual(0, self.ladder(Fake(self.n, self.full(bad=False)), self.out('c')))
        self.assertTrue((self.out('c') / at.RAW_NAME).exists())
        self.wav.write_bytes(b'not a wav')
        with self.assertRaises(at.InputError):
            self.ladder(Fake(self.n, self.full()), self.out('c'))
        self.assertFalse((self.out('c') / at.RAW_NAME).exists())

    def dropout_full(self):
        """R0 where whisper dropped 'sierra' and 'tango': nothing is recognised between 18.8 s and 27.5 s although the tone (speech) runs"""
        keep = [w for w in BLOCK3_OK if w[0] in ('romeo', 'uniform')]
        return [wseg(BLOCK1), wseg(BLOCK2), wseg(keep), wseg(BLOCK4)]

    def test_a_whisper_dropout_is_a_raw_gap_and_r1_repairs_it(self):
        fake = Fake(self.n, self.dropout_full(), region_fn=region_words)
        out = self.out()
        with _Capture() as cap:
            self.assertEqual(0, self.ladder(fake, out))
        self.assertIn('DEFECT raw-gap at 18.800s', cap.text)                     # R0 reported it (and only R1 fixed it)
        raw = self.raw(out)
        self.assertEqual(['R0', 'R1'], [r['rung'] for r in raw['rungs']])
        (lo, hi), = raw['rungs'][1]['regions']
        self.assertLessEqual(lo, 18.8)
        self.assertGreaterEqual(hi, 27.5)
        self.assertEqual(2, len(fake.calls))
        words = [w['word'].strip() for s in raw['segments'] for w in s['words']]
        self.assertIn('sierra', words)
        self.assertIn('tango', words)
        pages, _ = aa.align(raw, self.script.read_text(encoding='utf-8').splitlines())
        self.assertEqual([], td.find_defects(pages, raw, at.detect_silences(self.wav)))

    def test_a_dropout_that_the_re_decode_does_not_recover_is_exit_5(self):
        dropout_again = lambda n: [wseg([('romeo', 0.6, 1.1), ('uniform', 9.2, 9.7)])]          # R1 loses the same words
        out = self.out()
        with _Capture() as cap:
            self.assertEqual(5, self.ladder(Fake(self.n, self.dropout_full(), region_fn=dropout_again), out))
        failed = json.loads((out / at.FAILED_NAME).read_text(encoding='utf-8'))
        self.assertEqual('R1', failed['rung'])
        self.assertEqual({'raw-gap'}, {d['code'] for d in failed['defects']} - {'word-too-long', 'word-slow', 'squeeze', 'zero-run'})
        self.assertIn('DEFECT raw-gap', cap.text)
        self.assertFalse((out / at.RAW_NAME).exists())

    def test_a_single_huge_raw_token_is_a_raw_word_too_long_and_r1_repairs_it(self):
        full = self.full(bad=False)
        full[2] = wseg([('romeo', 18.8, 19.3), ('sierra', 21.7, 27.2), ('tango', 27.3, 27.8), ('uniform', 27.9, 28.4)])   # 5.5 s raw word
        out = self.out()
        with _Capture() as cap:
            self.assertEqual(0, self.ladder(Fake(self.n, full, region_fn=region_words), out))
        self.assertIn('DEFECT raw-word-too-long', cap.text)
        self.assertEqual(['R0', 'R1'], [r['rung'] for r in self.raw(out)['rungs']])

    def test_r1_that_creates_a_new_defect_outside_its_region_is_exit_5(self):
        """the re-decoded region fixes the old defect, but its last word (a 5.4 s raw span) runs past the region end into audio R1
        never touched (the next R0 word starts at 31.2 s, the region ends at 30.5 s): the WHOLE result is checked again, so a
        defect that reaches outside [lo, hi] fails the rung"""
        def region(n):
            return [wseg([('romeo', 0.6, 1.1), ('sierra', 3.3, 3.9), ('tango', 6.4, 6.9), ('uniform', 9.3, 14.7)])]
        out = self.out()
        with _Capture() as cap:
            self.assertEqual(5, self.ladder(Fake(self.n, self.full(), region_fn=region), out))
        self.assertFalse((out / at.RAW_NAME).exists())
        failed = json.loads((out / at.FAILED_NAME).read_text(encoding='utf-8'))
        (lo, hi), = failed['regions']
        self.assertEqual('R1', failed['rung'])
        self.assertTrue(failed['defects'])
        self.assertTrue(any(d['end'] > hi for d in failed['defects']), failed['defects'])               # reaches beyond the region
        self.assertFalse(any(d['token'] == 'sierra' for d in failed['defects']))                          # the old defect was repaired
        self.assertIn('WORD_TIMING FAILED at rung R1', cap.text)

    def test_fake_decoder_requires_its_identity(self):
        with self.assertRaises(ValueError):
            at.run_ladder(self.wav, self.script, self.out(), transcribe_fn=Fake(self.n, self.full()))


class PlanTests(unittest.TestCase):
    def d(self, s, e, code='word-too-long'):
        return {'code': code, 'start': s, 'end': e}

    def test_pad_then_snap_to_nearest_silence_midpoint_that_keeps_the_defect_inside(self):
        sil = [(40.0, 41.0), (50.4, 51.0), (53.8, 54.2), (55.8, 56.2), (70.0, 71.0)]       # midpoints 40.5 50.7 54 56 70.5
        # defect 50.0-55.0 -> pad 47.0-58.0.  Left: 50.7 is the nearest midpoint (3.7 s) but lies inside the defect, so
        # 40.5 (6.5 s) is used.  Right: 54.0 is inside the defect, 70.5 is 12.5 s away (> 10 s) -> 56.0 (inward is fine).
        self.assertEqual([[40.5, 56.0]], at.plan_regions([self.d(50.0, 55.0)], sil, 100.0))
        self.assertEqual([[47.0, 58.0]], at.plan_regions([self.d(50.0, 55.0)], [(50.4, 51.0), (53.8, 54.2)], 100.0))

    def test_no_silence_in_reach_keeps_the_pad_and_clamps_to_the_audio(self):
        self.assertEqual([[0.0, 9.0]], at.plan_regions([self.d(1.0, 6.0)], [(30.0, 31.0)], 100.0))
        self.assertEqual([[93.0, 98.4]], at.plan_regions([self.d(96.0, 98.4)], [], 98.4))

    def test_overlapping_regions_merge_and_edges_sit_on_a_10_ms_grid(self):
        regs = at.plan_regions([self.d(10.0, 11.0), self.d(14.0, 15.003), self.d(40.0, 41.0, 'squeeze')], [], 100.0)
        self.assertEqual([[7.0, 18.01], [37.0, 44.0]], regs)

    def test_regions_are_clamped_to_the_audio_and_never_empty(self):
        self.assertEqual([[0.0, 4.0]], at.plan_regions([self.d(-5.0, 1.0)], [], 100.0))           # a defect before 0
        self.assertEqual([[92.0, 100.0]], at.plan_regions([self.d(95.0, 130.0)], [], 100.0))       # a defect past the end
        regs = at.plan_regions([self.d(95.0, 98.0)], [(98.0, 98.43)], 98.436)
        self.assertLessEqual(regs[-1][1], 98.436)                                                   # not on the 10 ms grid past the end
        for s, e in ((0.0, 0.0), (99.9, 99.95), (-3.0, -1.0), (50.0, 50.0), (10.0, 5.0)):           # reversed / empty spans too
            for lo, hi in at.plan_regions([self.d(s, e)], [], 100.0):
                self.assertTrue(0.0 <= lo < hi <= 100.0, (s, e, lo, hi))
        for s, e in ((120.0, 121.0), (104.0, 140.0), (-9.0, -8.0)):                                  # wholly outside the audio
            with self.assertRaises(at.Systemic, msg=(s, e)) as cm:
                at.plan_regions([self.d(s, e)], [], 100.0)
            self.assertIn('outside the audio', str(cm.exception))

    def test_limits_are_systemic(self):
        seven = [self.d(10.0 + 20 * k, 11.0 + 20 * k) for k in range(7)]
        with self.assertRaises(at.Systemic) as cm:
            at.plan_regions(seven, [], 400.0)
        self.assertEqual(7, len(cm.exception.regions))
        self.assertEqual(6, len(at.plan_regions(seven[:6], [], 400.0)))
        with self.assertRaises(at.Systemic):
            at.plan_regions([self.d(10.0, 125.0)], [], 400.0)            # 121 s > 120 s
        self.assertEqual([[7.0, 120.0]], at.plan_regions([self.d(10.0, 117.0)], [], 400.0))
        with self.assertRaises(at.Systemic):
            at.plan_regions([{'code': 'non-finite', 'start': None, 'end': None}], [], 400.0)


class SpliceTests(unittest.TestCase):
    def test_words_in_regions_are_replaced_and_segments_split_around_them(self):
        old = [{'start': 0.0, 'end': 6.0, 'text': 'x', 'compression_ratio': 1.0, 'rung': 'R0',
                'words': [{'word': 'a', 'start': 0.0, 'end': 1.0}, {'word': 'b', 'start': 2.0, 'end': 3.0},
                          {'word': 'c', 'start': 4.0, 'end': 4.4}, {'word': 'd', 'start': 5.0, 'end': 6.0}]},
               {'start': 2.2, 'end': 2.4, 'text': 'loop', 'compression_ratio': 9.0, 'rung': 'R0', 'words': []},
               {'start': 8.0, 'end': 9.0, 'text': '', 'compression_ratio': 1.0, 'rung': 'R0', 'words': []}]
        new = [{'start': 1.5, 'end': 4.6, 'text': 'B C', 'compression_ratio': 1.1, 'rung': 'R1',
                'words': [{'word': 'B', 'start': 1.5, 'end': 2.5}, {'word': 'C', 'start': 3.0, 'end': 4.6},
                          {'word': 'Z', 'start': 4.7, 'end': 5.6}]}]          # Z's midpoint 5.15 is outside 1.8-4.6
        out = at.splice(old, [[1.8, 4.6]], new)
        self.assertEqual([['a'], ['B', 'C'], ['d'], []], [[w['word'] for w in s['words']] for s in out])
        self.assertEqual(['R0', 'R1', 'R0', 'R0'], [s['rung'] for s in out])
        self.assertEqual((0.0, 1.0, 'a'), (out[0]['start'], out[0]['end'], out[0]['text']))
        self.assertEqual(1.0, out[0]['compression_ratio'])
        self.assertEqual((1.5, 4.6), (out[1]['start'], out[1]['end']))


class PinTests(unittest.TestCase):
    def test_pins_are_constants(self):
        self.assertEqual('mlx-community/whisper-large-v3-mlx', at.MODEL_ID)
        self.assertEqual('49e6aa286ad60c14352c404340ded53710378a11', at.MODEL_SNAPSHOT)
        self.assertEqual(Path(PW_HOME) / '.cache' / 'huggingface' / 'hub', at.HF_HUB)
        self.assertEqual(Path(PW_HOME) / '.cache' / 'yt-news-v4' / 'asr-venv', at.VENV_ROOT)
        self.assertEqual(at.VENV_ROOT / 'lib' / 'python3.12' / 'site-packages', at.SITE_DIR)
        self.assertEqual({'config.json': '2c626df3c540bdc0287b11725441d10e1af73680',
                          'weights.npz': '05ff791ce3630fae47e7c51004e9666204d786246ec07cac6110af768099b40d'}, at.MODEL_BLOBS)
        self.assertEqual('asr_venv.manifest', at.MANIFEST_NAME)
        self.assertEqual(('-I', '-S', '-B', '-X', 'pycache_prefix=/var/empty'), at.RUN_FLAGS)
        self.assertTrue(hasattr(at, 'VENV_PINS') is False)           # the pins of the venv are the manifest's, checked outside python
        self.assertEqual({'transcribe.py', 'decoding.py', 'timing.py', 'audio.py'}, set(at.MLX_WHISPER_FILES))
        self.assertTrue(all(len(v) == 64 for v in at.MLX_WHISPER_FILES.values()))
        self.assertEqual({'language': 'th', 'temperature': (0.0,), 'condition_on_previous_text': False,
                          'word_timestamps': True}, at.PARAMS)

    def test_no_environment_or_home_use_outside_the_two_allowed_sites(self):
        """AST walk (a grep for environ.get would miss os.environ[...], Path.home(), expanduser, `from os import environ`)"""
        allowed = {'asr_transcribe.py': ['not env_is_minimal(os.environ)', "os.environ[_k] = '1'"],
                   'asr_align.py': ['os.environ'], 'timing_defects.py': []}
        for name, sites_ok in allowed.items():
            src = (SCRIPTS / name).read_text(encoding='utf-8')
            tree = ast.parse(src)
            sites = []
            for n in ast.walk(tree):
                if isinstance(n, ast.Attribute) and n.attr in ('environ', 'getenv', 'getenvb', 'putenv', 'home', 'expanduser', 'expandvars'):
                    sites.append(n)
                if isinstance(n, ast.Name) and n.id in ('environ', 'getenv', 'expanduser', 'expandvars'):
                    sites.append(n)
                if isinstance(n, ast.ImportFrom) and n.module in ('os', 'os.path') and any(a.name in ('environ', 'getenv', 'expanduser') for a in n.names):
                    sites.append(n)
            lines = sorted({src.splitlines()[n.lineno - 1].strip() for n in sites})
            self.assertEqual(len(sites_ok), len(lines), '%s: %s' % (name, lines))
            for ok in sites_ok:
                self.assertTrue(any(ok in l for l in lines), '%s: %r not among %s' % (name, ok, lines))

    def test_a_planted_environment_function_would_be_caught_by_the_walk(self):
        tree = ast.parse('import os\nx = os.environ["A"]\ny = os.getenv("B")\nfrom pathlib import Path\nz = Path.home()\nw = os.path.expanduser("~")\n')
        hits = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in ('environ', 'getenv', 'home', 'expanduser')]
        self.assertEqual(4, len(hits))

    def test_pin_mismatch_and_missing_model_are_named(self):
        with tempfile.TemporaryDirectory() as d:
            pkg = Path(d) / 'mlx_whisper'
            pkg.mkdir()
            for n in at.MLX_WHISPER_FILES:
                (pkg / n).write_text('# not the pinned file\n')
            (pkg / 'timing.py').unlink()
            info, problems = at.check_environment(hub=Path(d) / 'hub', mlx_pkg=pkg, venv=False)
            text = '\n'.join(problems)
            self.assertIn('mlx_whisper/decoding.py sha256', text)
            self.assertIn('mlx_whisper/timing.py is missing', text)
            self.assertIn('is not in the local HF cache', text)
            snap = Path(d) / 'hub' / 'models--mlx-community--whisper-large-v3-mlx' / 'snapshots' / at.MODEL_SNAPSHOT
            snap.mkdir(parents=True)
            (snap / 'config.json').write_text('{}')
            (snap / 'weights.npz').write_text('x')
            info, problems = at.check_environment(hub=Path(d) / 'hub', mlx_pkg=pkg, venv=False)
            self.assertNotIn('local HF cache', '\n'.join(problems))
            other = snap.parent / 'another-commit'                         # a different snapshot does not count
            snap.rename(other)
            info, problems = at.check_environment(hub=Path(d) / 'hub', mlx_pkg=pkg, venv=False)
            self.assertIn('is not in the local HF cache', '\n'.join(problems))

    @unittest.skipUnless(HAVE_CHAIN, 'the pinned python / the V4 ASR venv are not on this machine')
    def test_installed_venv_matches_the_pins(self):
        r = subprocess.run([*RUN, str(SCRIPTS / 'asr_transcribe.py'), '--check'], capture_output=True, text=True)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn(at.MODEL_SNAPSHOT, r.stdout)
        self.assertIn('pinned by manifest %s' % MANIFEST_SHA[:12], r.stdout)

    def test_the_model_blob_names_are_pinned(self):
        """N2: a snapshot that links to ANOTHER blob than the pinned one is refused, naming the file"""
        with tempfile.TemporaryDirectory() as d:
            hub, snap = ModelBlobTests().hub(d)
            pkg = ModelBlobTests().pkg(d)
            _, problems = at.check_environment(hub=hub, mlx_pkg=pkg, venv=False)                   # default pins: the real blob names
            text = '\n'.join(problems)
            self.assertIn('model file config.json is the blob %s, not the pinned %s' % ('1' * 40, at.MODEL_BLOBS['config.json']), text)
            self.assertIn('model file weights.npz is the blob %s, not the pinned %s' % ('2' * 64, at.MODEL_BLOBS['weights.npz']), text)
            _, problems = at.check_environment(hub=hub, mlx_pkg=pkg, venv=False, blobs={'config.json': '1' * 40, 'weights.npz': '2' * 64})
            self.assertFalse([p for p in problems if 'model file' in p], problems)
            _, problems = at.check_environment(hub=hub, mlx_pkg=pkg, venv=False, blobs={'config.json': '1' * 40, 'weights.npz': '3' * 64})
            self.assertTrue(any('weights.npz is the blob' in p for p in problems), problems)

    def test_deep_check_hashes_the_weights_content_with_shasum(self):
        with tempfile.TemporaryDirectory() as d:
            hub, snap = ModelBlobTests().hub(d)
            blob = Path(os.path.realpath(snap / 'weights.npz'))
            sha = hashlib.sha256(blob.read_bytes()).hexdigest()
            self.assertEqual([], at.weights_problems(snap, {'weights.npz': sha}))
            bad = at.weights_problems(snap, {'weights.npz': '0' * 64})
            self.assertEqual(1, len(bad))
            self.assertIn('hashes to %s, not %s' % (sha, '0' * 64), bad[0])
            blob.write_text('tampered weights')                                       # same blob name, other content
            self.assertEqual(1, len(at.weights_problems(snap, {'weights.npz': sha})))
            # check_environment only hashes in deep mode, and not when something else is already wrong
            blob.write_text('weights')
            calls = []
            with mock.patch.object(at, 'weights_problems', lambda *a, **k: calls.append(a) or []):
                _, problems = at.check_environment(hub=hub, mlx_pkg=ModelBlobTests().pkg(d), venv=False, deep=True)
                self.assertTrue(problems)                                             # the fake decoder files do not match their pins
                self.assertEqual([], calls)                                           # so the 3 GB hash is not even started

    def test_deep_needs_check_and_the_launcher_marker_is_required(self):
        def cli(*args, flags=RUN):
            return subprocess.run([*flags, str(SCRIPTS / 'asr_transcribe.py'), *args], capture_output=True, text=True)
        self.assertEqual(2, cli('--deep').returncode)
        self.assertEqual(2, cli('--deep', '--fingerprint').returncode)
        r = cli('--check', flags=BASE_RUN)                                            # right flags, but not started by asr_run.sh
        self.assertEqual(4, r.returncode)
        self.assertIn('not started through the launcher', r.stderr)
        r = cli('--check', flags=[*BASE_RUN, '-X', 'asr_manifest_sha256=' + '0' * 64])  # the marker of another manifest
        self.assertEqual(4, r.returncode)
        self.assertIn('not started through the launcher', r.stderr)

    def test_cli_has_no_override_options_and_bad_args_are_exit_2(self):
        def cli(*args):
            return subprocess.run([*RUN, str(SCRIPTS / 'asr_transcribe.py'), *args], capture_output=True, text=True)
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / 'a.wav'
            make_wav(wav, [(0.0, 1.0)], 1.0)
            script = Path(d) / 's.txt'
            script.write_text('x\n')
            for extra in (['--model', 'other/model'], ['--temperature', '0.2'], ['--snapshot', 'x']):
                self.assertEqual(2, cli('--wav', str(wav), '--script', str(script), '--out-dir', d, *extra).returncode)
            self.assertEqual(2, cli('--wav', str(wav)).returncode)
            self.assertEqual(2, cli('--wav', str(Path(d) / 'missing.wav'), '--script', str(script), '--out-dir', d).returncode)


def _fp(**over):
    """a fingerprint built from the fake env (code hashes of the real chain files)"""
    fp = at.fingerprint(ENV)
    fp.update(over)
    return fp


class FingerprintTests(LadderBase):
    def test_raw_carries_the_whole_fingerprint_and_no_path_or_clock(self):
        texts = []
        for name in ('a', 'b'):
            self.assertEqual(0, self.ladder(Fake(self.n, self.full(bad=False)), self.out(name)))
            texts.append((self.out(name) / at.RAW_NAME).read_bytes())
            time.sleep(1.1)
        self.assertEqual(texts[0], texts[1])
        raw = self.raw(self.out('a'))
        self.assertEqual(set(at.FINGERPRINT_KEYS), {'model', 'mlx_whisper', 'mlx', 'tokenizer', 'platform', 'ffmpeg', 'venv', 'params', 'code'})
        for k in at.FINGERPRINT_KEYS:
            self.assertIn(k, raw)
        self.assertEqual(ENV['model']['files'], raw['model']['files'])
        self.assertEqual(ENV['mlx'], raw['mlx'])
        self.assertEqual(ENV['platform'], raw['platform'])
        self.assertEqual(set(at.CODE_FILES), set(raw['code']))
        self.assertEqual({n: at.sha_file(SCRIPTS / n) for n in at.CODE_FILES}, raw['code'])
        text = texts[0].decode('utf-8')
        for forbidden in (str(self.d), 'should/never/reach', 'snapshot_dir', 'site_dir', 'venv_tops', PW_HOME, Path(PW_HOME).name):
            self.assertNotIn(forbidden, text)

    def test_fingerprint_is_the_identity_part_of_the_written_raw(self):
        self.assertEqual(0, self.ladder(Fake(self.n, self.full(bad=False)), self.out()))
        raw = self.raw(self.out())
        self.assertEqual({k: raw[k] for k in at.FINGERPRINT_KEYS}, json.loads(json.dumps(at.fingerprint(ENV))))
        self.assertEqual(set(at.FINGERPRINT_KEYS), set(at.fingerprint(ENV)))

    def test_every_fingerprint_field_changes_the_rung_checkpoint_key(self):
        """a resumed rung from another toolchain would be silently reused otherwise: EVERY leaf of EVERY FINGERPRINT_KEYS entry
        (env-derived ones via env_info, params via PARAMS, code via the chain files) must invalidate the R0 checkpoint"""
        def leaves(obj, path=()):
            if isinstance(obj, dict):
                for k in sorted(obj):
                    yield from leaves(obj[k], path + (k,))
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    yield from leaves(v, path + (i,))
            else:
                yield path

        def put(obj, path, value):
            for k in path[:-1]:
                obj = obj[k]
            obj[path[-1]] = value

        base = self.out()
        self.assertEqual(0, self.ladder(Fake(self.n, self.full(bad=False)), base))
        visited, checked = set(), 0

        def assert_invalidated(label, env=ENV, params=None, here=None):
            fake = Fake(self.n, self.full(bad=False))
            patches = []
            if params is not None:
                patches.append(mock.patch.object(at, 'PARAMS', params))
            if here is not None:
                patches.append(mock.patch.object(at, 'HERE', here))
            for pt in patches:
                pt.start()
            try:
                self.assertEqual(0, at.run_ladder(self.wav, self.script, base, transcribe_fn=fake, env_info=env))
            finally:
                for pt in patches:
                    pt.stop()
            self.assertEqual(1, len(fake.calls), '%s did not invalidate the checkpoint' % label)
            # and the SAME identity again is a resume (the test would pass vacuously if every run re-decoded)
            again = Fake(self.n, self.full(bad=False))
            for pt in patches:
                pt.start()
            try:
                self.assertEqual(0, at.run_ladder(self.wav, self.script, base, transcribe_fn=again, env_info=env))
            finally:
                for pt in patches:
                    pt.stop()
            self.assertEqual(0, len(again.calls), '%s: an unchanged identity was decoded again' % label)
            self.assertEqual(0, self.ladder(Fake(self.n, self.full(bad=False)), base))                 # back to the baseline identity

        fp = at.fingerprint(ENV)
        for key in at.FINGERPRINT_KEYS:
            for path in leaves(fp[key]):
                visited.add(key)
                label = '%s.%s' % (key, '.'.join(str(x) for x in path))
                if key == 'params':
                    params = json.loads(json.dumps(fp['params']))
                    old = params
                    for k in path:
                        old = old[k]
                    put(params, path, 'x' if isinstance(old, str) else (not old if isinstance(old, bool) else 9.5))
                    params = {k: tuple(v) if isinstance(v, list) else v for k, v in params.items()}
                    assert_invalidated(label, params=params)
                elif key == 'code':
                    with tempfile.TemporaryDirectory() as d:
                        for n in at.CODE_FILES:
                            shutil.copy(SCRIPTS / n, Path(d) / n)
                        with open(Path(d) / path[0], 'a') as f:
                            f.write('\n# changed\n')
                        assert_invalidated(label, here=Path(d))
                else:
                    env = json.loads(json.dumps(ENV))
                    put(env[key], path, 'changed-value')
                    assert_invalidated(label, env=env)
                checked += 1
        self.assertEqual(set(at.FINGERPRINT_KEYS), visited)                                           # no key skipped
        self.assertGreater(checked, 20)
        # a field that is NOT part of the fingerprint must not matter (paths of the environment)
        env = json.loads(json.dumps(ENV))
        env['snapshot_dir'] = '/somewhere/else'
        fake = Fake(self.n, self.full(bad=False))
        self.assertEqual(0, at.run_ladder(self.wav, self.script, base, transcribe_fn=fake, env_info=env))
        self.assertEqual(0, len(fake.calls))


class CompareTests(unittest.TestCase):
    def test_identical_is_empty(self):
        self.assertEqual([], at.compare_fingerprint(_fp(), json.loads(json.dumps(_fp()))))

    def test_one_changed_leaf_gives_one_line_naming_both_values(self):
        cur = json.loads(json.dumps(_fp()))
        cur['mlx']['version'] = '0.31.3'
        rec = json.loads(json.dumps(_fp()))
        rec['mlx']['version'] = '0.31.2'
        self.assertEqual(['mlx.version: 0.31.2 (production) != 0.31.3 (this machine)'], at.compare_fingerprint(rec, cur))

    def test_missing_key_on_either_side_is_a_difference(self):
        rec, cur = json.loads(json.dumps(_fp())), json.loads(json.dumps(_fp()))
        del cur['mlx']['mlx-metal']
        self.assertEqual(['mlx.mlx-metal: 0.0.1 (production) != <missing> (this machine)'], at.compare_fingerprint(rec, cur))
        self.assertEqual(['mlx.mlx-metal: <missing> (production) != 0.0.1 (this machine)'], at.compare_fingerprint(cur, rec))
        del cur['platform']
        lines = at.compare_fingerprint(rec, cur)
        self.assertEqual(2, len(lines))              # the whole missing platform block + mlx-metal
        self.assertTrue(any(l.startswith('platform: {') and l.endswith('!= <missing> (this machine)') for l in lines), lines)

    def test_nested_dict_and_list_differences_are_found(self):
        rec = {'a': {'b': [1, 2, {'c': 'x'}]}, 'p': {'t': [0.0]}}
        cur = {'a': {'b': [1, 3, {'c': 'y'}, 4]}, 'p': {'t': [0.0]}}
        self.assertEqual(['a.b[1]: 2 (production) != 3 (this machine)',
                          'a.b[2].c: x (production) != y (this machine)',
                          'a.b[3]: <missing> (production) != 4 (this machine)'], at.compare_fingerprint(rec, cur))
        self.assertEqual(['x: 1 (production) != true (this machine)'], at.compare_fingerprint({'x': 1}, {'x': True}))
        self.assertEqual(['x: {"a": 1} (production) != null (this machine)'], at.compare_fingerprint({'x': {'a': 1}}, {'x': None}))

    def test_an_os_update_adds_one_explicit_hint_line_and_nothing_else_does(self):
        """item 9: platform.release / platform.mac_ver differ -> ONE extra last line; the leaf lines and the failure condition are unchanged"""
        base = _fp()
        for leaves in ({'release': '99.0'}, {'mac_ver': '99.1'}, {'release': '99.0', 'mac_ver': '99.1'}):
            cur = _fp(platform=dict(ENV['platform'], **leaves))
            lines = at.compare_fingerprint(base, cur)
            self.assertEqual(len(leaves) + 1, len(lines), lines)
            self.assertEqual(at.OS_UPDATE_HINT, lines[-1])
            self.assertEqual(1, lines.count(at.OS_UPDATE_HINT))
            for k in leaves:
                self.assertTrue(any(l.startswith('platform.%s: ' % k) and ' (production) != ' in l for l in lines), lines)
        self.assertEqual('hint: the OS was updated after this word timing was made \u2014 redo the word timing step and deliver again', at.OS_UPDATE_HINT)
        for leaves in ({'cpu': 'Other M9'}, {'machine': 'x86_64'}, {'system': 'Linux'}):                      # other platform leaves: no hint
            lines = at.compare_fingerprint(base, _fp(platform=dict(ENV['platform'], **leaves)))
            self.assertEqual(1, len(lines))
            self.assertNotIn(at.OS_UPDATE_HINT, lines)
        self.assertEqual([], at.compare_fingerprint(base, _fp()))                                           # identical: still empty, no hint

    def test_a_changed_chain_file_hash_or_param_is_a_difference(self):
        cur = _fp(code={n: '0' * 64 for n in at.CODE_FILES})
        self.assertEqual(len(at.CODE_FILES), len(at.compare_fingerprint(_fp(), cur)))
        cur = _fp(params={'language': 'en', 'temperature': [0.0], 'condition_on_previous_text': False, 'word_timestamps': True})
        self.assertEqual(['params.language: th (production) != en (this machine)'], at.compare_fingerprint(_fp(), cur))


class ModelBlobTests(unittest.TestCase):
    def hub(self, d, link_weights=True, link_config=True):
        hub = Path(d) / 'hub'
        model = hub / 'models--mlx-community--whisper-large-v3-mlx'
        snap = model / 'snapshots' / at.MODEL_SNAPSHOT
        (model / 'blobs').mkdir(parents=True)
        snap.mkdir(parents=True)
        (model / 'blobs' / ('1' * 40)).write_text('{}')
        (model / 'blobs' / ('2' * 64)).write_text('weights')
        for name, blob, link in (('config.json', '1' * 40, link_config), ('weights.npz', '2' * 64, link_weights)):
            if link:
                (snap / name).symlink_to('../../blobs/' + blob)
            else:
                (snap / name).write_text('hand edited')
        return hub, snap

    def pkg(self, d):
        pkg = Path(d) / 'mlx_whisper'
        pkg.mkdir()
        for n in at.MLX_WHISPER_FILES:
            (pkg / n).write_text('x')
        return pkg

    def test_blob_names_are_recorded_for_linked_files(self):
        with tempfile.TemporaryDirectory() as d:
            hub, snap = self.hub(d)
            info, problems = at.check_environment(hub=hub, mlx_pkg=self.pkg(d), venv=False, blobs={'config.json': '1' * 40, 'weights.npz': '2' * 64})
            self.assertEqual({'config.json': '1' * 40, 'weights.npz': '2' * 64}, info['model']['files'])
            self.assertFalse([p for p in problems if 'model file' in p or 'local HF cache' in p], problems)

    PINS = {'config.json': '1' * 40, 'weights.npz': '2' * 64}
    CONFIG_SHA = hashlib.sha256(b'{}').hexdigest()                                    # the fake hub's config.json content

    def env(self, d, hub, **kw):
        kw.setdefault('blobs', self.PINS)
        kw.setdefault('config_sha256', self.CONFIG_SHA)
        pkg = Path(d) / 'mlx_whisper'
        return at.check_environment(hub=hub, mlx_pkg=pkg if pkg.exists() else self.pkg(d), venv=False, **kw)

    def test_a_stray_file_in_the_snapshot_is_refused_by_name(self):
        """item 7: a weights.safetensors next to weights.npz (or any other file) changes what the decoder loads"""
        for name in ('weights.safetensors', 'tokenizer.json', 'config.json.orig', 'extra'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                hub, snap = self.hub(d)
                _, problems = self.env(d, hub)
                self.assertEqual([], [p for p in problems if 'snapshot' in p and 'pinned' in p], problems)      # the control: clean snapshot
                (snap / name).write_text('x')
                _, problems = self.env(d, hub)
                self.assertTrue(any('not pinned: %s' % name in p for p in problems), problems)

    def test_the_repo_readme_and_gitattributes_are_allowed_only_as_their_pinned_blobs(self):
        with tempfile.TemporaryDirectory() as d:
            hub, snap = self.hub(d)
            blobs = snap.parent.parent / 'blobs'
            for name, blob in (('README.md', '3' * 40), ('.gitattributes', '4' * 40)):
                (blobs / blob).write_text('x')
                (snap / name).symlink_to('../../blobs/' + blob)
            extras = {'README.md': '3' * 40, '.gitattributes': '4' * 40}
            _, problems = self.env(d, hub, extras=extras)
            self.assertEqual([], [p for p in problems if 'not pinned:' in p or 'snapshot file' in p], problems)
            _, problems = self.env(d, hub, extras=dict(extras, **{'README.md': '9' * 40}))                  # another blob than the pinned one
            self.assertTrue(any('snapshot file README.md is not the pinned blob' in p for p in problems), problems)
            _, problems = self.env(d, hub, extras={'README.md': '3' * 40})                                  # .gitattributes is not in the allowed set
            self.assertTrue(any('not pinned: .gitattributes' in p for p in problems), problems)
        self.assertEqual({'.gitattributes', 'README.md'}, set(at.MODEL_SNAPSHOT_EXTRAS))                    # what the real snapshot holds besides the two

    def test_config_json_content_is_hashed_every_time(self):
        with tempfile.TemporaryDirectory() as d:
            hub, snap = self.hub(d)
            _, problems = self.env(d, hub)
            self.assertEqual([], [p for p in problems if 'config.json' in p], problems)
            blob = Path(os.path.realpath(snap / 'config.json'))
            blob.write_text('{"n_mels": 80}')                                          # same blob NAME, other content
            _, problems = self.env(d, hub)
            self.assertTrue(any('config.json content hashes to %s' % hashlib.sha256(b'{"n_mels": 80}').hexdigest() in p for p in problems), problems)
            _, problems = self.env(d, hub, config_sha256='0' * 64)
            self.assertTrue(any('not the pinned %s' % ('0' * 64) in p for p in problems), problems)
        self.assertEqual(64, len(at.MODEL_CONFIG_SHA256))
        real = Path(at.HF_HUB) / 'models--mlx-community--whisper-large-v3-mlx' / 'snapshots' / at.MODEL_SNAPSHOT / 'config.json'
        if real.exists():
            self.assertEqual(at.MODEL_CONFIG_SHA256, hashlib.sha256(real.read_bytes()).hexdigest())      # the pin is the real file's content

    def test_regular_file_in_the_snapshot_is_null_and_a_problem(self):
        for kw, name in (({'link_weights': False}, 'weights.npz'), ({'link_config': False}, 'config.json')):
            with tempfile.TemporaryDirectory() as d:
                hub, snap = self.hub(d, **kw)
                info, problems = at.check_environment(hub=hub, mlx_pkg=self.pkg(d), venv=False)
                self.assertIsNone(info['model']['files'][name])
                self.assertTrue(any(('model file %s is not a link' % name) in p for p in problems), problems)

    def test_link_pointing_outside_blobs_is_a_problem(self):
        with tempfile.TemporaryDirectory() as d:
            hub, snap = self.hub(d)
            elsewhere = Path(d) / 'elsewhere.npz'
            elsewhere.write_text('other weights')
            (snap / 'weights.npz').unlink()
            (snap / 'weights.npz').symlink_to(elsewhere)
            info, problems = at.check_environment(hub=hub, mlx_pkg=self.pkg(d), venv=False)
            self.assertIsNone(info['model']['files']['weights.npz'])
            self.assertTrue(any('model file weights.npz is not a link' in p for p in problems), problems)

    def test_missing_chip_name_is_a_problem(self):
        orig = at._cpu_brand
        at._cpu_brand = lambda: None
        try:
            plat, problems = at.platform_identity()
        finally:
            at._cpu_brand = orig
        self.assertIsNone(plat['cpu'])
        self.assertTrue(any('chip name' in p for p in problems))
        plat, problems = at.platform_identity()
        self.assertEqual(['system', 'release', 'machine', 'mac_ver', 'cpu'], list(plat))
        self.assertEqual([], problems if sys.platform == 'darwin' else [])

    def test_mlx_distribution_missing_is_a_problem(self):
        orig = at.importlib.metadata.version

        def fake(name):
            if name == 'mlx':
                raise at.importlib.metadata.PackageNotFoundError(name)
            if name == 'mlx-metal':
                return '1.2.3'
            return orig(name)
        at.importlib.metadata.version = fake
        try:
            ident, problems = at.mlx_identity()
        finally:
            at.importlib.metadata.version = orig
        self.assertEqual({'version': None, 'mlx-metal': '1.2.3'}, ident)
        self.assertEqual(['mlx distribution metadata not found'], problems)


class FingerprintCliTests(unittest.TestCase):
    def run_main(self, argv, env_result):
        import io
        import contextlib
        orig = at.check_environment
        at.check_environment = lambda *a, **k: env_result
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = at.main(argv)
        finally:
            at.check_environment = orig
        return rc, out.getvalue(), err.getvalue()

    def test_prints_the_fingerprint_json_and_exits_0(self):
        rc, out, err = self.run_main(['--fingerprint'], (json.loads(json.dumps(ENV)), []))
        self.assertEqual((0, ''), (rc, err))
        self.assertEqual(at.fingerprint(ENV), json.loads(out))
        self.assertEqual(json.dumps(at.fingerprint(ENV), ensure_ascii=False, sort_keys=True) + '\n', out)
        self.assertNotIn('snapshot_dir', out)

    def test_problems_exit_4_with_empty_stdout(self):
        rc, out, err = self.run_main(['--fingerprint'], (json.loads(json.dumps(ENV)), ['model file weights.npz is not a link']))
        self.assertEqual(4, rc)
        self.assertEqual('', out)
        self.assertIn('ERROR: model file weights.npz is not a link', err)

    def test_check_also_covers_the_new_problems_and_the_two_modes_do_not_mix(self):
        rc, out, err = self.run_main(['--check'], (json.loads(json.dumps(ENV)), ['cannot read the chip name']))
        self.assertEqual((4, ''), (rc, out))
        self.assertIn('chip name', err)
        rc, out, err = self.run_main(['--check', '--fingerprint'], (json.loads(json.dumps(ENV)), []))
        self.assertEqual((2, ''), (rc, out))

    @unittest.skipUnless(HAVE_CHAIN, 'the pinned python / the V4 ASR venv are not on this machine')
    def test_real_venv_fingerprint_is_complete_stable_and_independent_of_the_callers_environment(self):
        def fp(env=None):
            r = subprocess.run([*RUN, str(SCRIPTS / 'asr_transcribe.py'), '--fingerprint'], capture_output=True, text=True, env=env)
            self.assertEqual(0, r.returncode, r.stderr)
            return r.stdout
        a = fp()
        self.assertEqual(a, fp())
        doc = json.loads(a)
        self.assertEqual(sorted(at.FINGERPRINT_KEYS), list(doc))
        self.assertTrue(all(doc['model']['files'].values()))
        self.assertTrue(doc['mlx']['version'] and doc['platform']['cpu'])
        self.assertTrue(doc['ffmpeg']['sha256'] and doc['ffmpeg']['version'].startswith('ffmpeg version'))
        self.assertEqual(MANIFEST_SHA, doc['venv']['manifest_sha256'])        # the manifest the launcher verified
        self.assertTrue(doc['venv']['python'].startswith('3.12.'))
        self.assertEqual(set(at.CODE_FILES), set(doc['code']))
        self.assertNotIn(PW_HOME, a)
        hostile = {'HOME': '/nonexistent-home', 'PATH': '/nonexistent', 'PYTHONPATH': '/nonexistent', 'HF_HOME': '/nonexistent',
                   'NUMBA_CACHE_DIR': '/nonexistent', 'MLX_X': '1', 'OMP_NUM_THREADS': '1', 'LANG': 'C'}
        self.assertEqual(a, fp(hostile))                               # the same bytes: HOME / PATH / the rest are never consulted


class ManifestIdentityTests(unittest.TestCase):
    """N1: the pins of the interpreter / stdlib / venv are the manifest's (asr_run.sh verifies it outside python); python only
    records its sha256 in the fingerprint and insists on having been started by the launcher"""

    def test_identity_is_the_manifest_hash_and_the_interpreter_version(self):
        ident, problems = at.venv_identity()
        self.assertEqual([], problems)
        self.assertEqual({'manifest_sha256': MANIFEST_SHA, 'python': sys.version}, ident)

    def test_a_missing_manifest_is_a_problem_naming_the_setup_script(self):
        with mock.patch.object(at, 'MANIFEST_NAME', 'no-such.manifest'):
            ident, problems = at.venv_identity()
            self.assertIsNone(ident['manifest_sha256'])
            self.assertEqual(1, len(problems))
            self.assertIn('no-such.manifest is missing', problems[0])
            self.assertIn('setup_asr_venv.sh', problems[0])
            self.assertIn('a human, not the agent', problems[0])
            self.assertTrue(at.launcher_problems())

    def test_the_launcher_marker_must_be_the_sha_of_the_manifest(self):
        with mock.patch.object(sys, '_xoptions', {}):
            self.assertIn('not started through the launcher', at.launcher_problems()[0])
        with mock.patch.object(sys, '_xoptions', {'asr_manifest_sha256': '0' * 64}):
            self.assertTrue(at.launcher_problems())
        with mock.patch.object(sys, '_xoptions', {'asr_manifest_sha256': MANIFEST_SHA}):
            self.assertEqual([], at.launcher_problems())

    def test_the_fingerprint_carries_the_manifest_hash_and_changes_with_it(self):
        a = at.fingerprint(ENV)
        b = at.fingerprint(dict(ENV, venv={'manifest_sha256': '4' * 64, 'python': ENV['venv']['python']}))
        self.assertEqual(['venv.manifest_sha256: %s (production) != %s (this machine)' % ('3' * 64, '4' * 64)], at.compare_fingerprint(a, b))
        self.assertIn('asr_run.sh', a['code'])                                        # the launcher is part of the toolchain identity


class ClosureTests(unittest.TestCase):
    """closure_problems: after the decode every loaded module must be stdlib, the V4 venv site-packages (every file of it is in the
    manifest) or a chain script"""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.site = Path(self.tmp.name) / 'site'
        (self.site / 'numpy').mkdir(parents=True)
        (self.site / 'numpy' / '__init__.py').write_text('')
        (self.site / 'evil').mkdir()
        (self.site / 'evil' / '__init__.py').write_text('')
        self.info = {'site_dir': str(self.site)}

    def tearDown(self):
        self.tmp.cleanup()

    def mod(self, path):
        return types.SimpleNamespace(__file__=str(path))

    def test_stdlib_venv_site_and_chain_scripts_are_fine(self):
        mods = {'json': self.mod(json.__file__), 'numpy': self.mod(self.site / 'numpy' / '__init__.py'),
                'asr_align': self.mod(SCRIPTS / 'asr_align.py'), '__main__': self.mod(SCRIPTS / 'asr_transcribe.py'),
                'builtin': types.SimpleNamespace(), 'frozen': types.SimpleNamespace(__file__=None)}
        self.assertEqual([], at.closure_problems(self.info, modules=mods, paths=[]))

    def test_other_script_or_a_file_outside_the_known_places_is_named(self):
        other = Path(self.tmp.name) / 'timing_defects.py'
        other.write_text('')
        mods = {'elsewhere': self.mod(other),
                'bad_chain': self.mod(SCRIPTS / 'tests' / 'test_asr_align.py'),
                'basesite': self.mod(Path(at.sysconfig.get_path('stdlib')) / 'site-packages' / 'pip' / '__init__.py')}
        problems = at.closure_problems(self.info, modules=mods, paths=[])
        self.assertEqual(3, len(problems), problems)
        for name in mods:
            self.assertTrue(any(p.startswith('module %s was loaded from' % name) for p in problems), (name, problems))

    def test_python_zip_on_sys_path_is_allowed_only_while_the_file_is_absent(self):
        """item 3: python puts <prefix>/lib/python312.zip on sys.path even when it does not exist (the real run does: a first version
        that refused the entry failed every correct job).  A file, directory or symlink there is code outside the manifest: refused."""
        root = Path(self.tmp.name) / 'prefix' / 'lib'
        stdlib = root / ('python%d.%d' % sys.version_info[:2])
        (stdlib / 'lib-dynload').mkdir(parents=True)
        zipname = root / ('python%d%d.zip' % sys.version_info[:2])
        paths = [str(zipname), str(stdlib), str(stdlib / 'lib-dynload')]
        with mock.patch.object(at.sysconfig, 'get_path', lambda name, *a, **k: str(stdlib)):
            self.assertEqual([], at.closure_problems(self.info, modules={}, paths=paths))            # absent: the default sys.path
            for kind in ('file', 'directory', 'dangling symlink'):
                with self.subTest(kind=kind):
                    if kind == 'file':
                        zipname.write_bytes(b'PK')
                    elif kind == 'directory':
                        zipname.mkdir()
                    else:
                        zipname.symlink_to(root / 'nowhere')
                    try:
                        problems = at.closure_problems(self.info, modules={}, paths=paths)
                    finally:
                        if zipname.is_dir() and not zipname.is_symlink():
                            zipname.rmdir()
                        else:
                            zipname.unlink()
                    self.assertEqual(1, len(problems), problems)
                    self.assertIn(str(zipname), problems[0])

    def test_sys_path_may_only_hold_the_stdlib_the_site_dir_and_this_skill(self):
        stdlib = at.sysconfig.get_path('stdlib')
        ok = [stdlib, stdlib + '/lib-dynload', str(self.site), str(SCRIPTS)]
        self.assertEqual([], at.closure_problems(self.info, modules={}, paths=ok))
        cwd = os.getcwd()
        os.chdir(self.tmp.name)                       # '' on sys.path = the cwd: refused, whatever the cwd is
        try:
            problems = at.closure_problems(self.info, modules={}, paths=ok + [self.tmp.name + '/elsewhere', ''])
        finally:
            os.chdir(cwd)
        self.assertEqual(2, len(problems), problems)
        self.assertTrue(all(p.startswith('sys.path holds') for p in problems))

    def test_the_real_ladder_refuses_when_the_closure_check_fails(self):
        """run_ladder calls closure_problems after a REAL decode (transcribe_fn=None); a fake decoder skips it"""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            wav, script = d / 'a.wav', d / 's.txt'
            make_wav(wav, [(0.0, 4.0)], 5.0)
            script.write_text('alpha bravo charlie\n')
            seg = [wseg([('alpha', 0.2, 0.7), ('bravo', 1.2, 1.7), ('charlie', 2.2, 2.7)])]
            info = dict(ENV, site_dir=str(self.site))
            with mock.patch.object(at, 'check_environment', lambda *a, **k: (info, [])), \
                    mock.patch.object(at, 'mlx_transcribe_fn', lambda snap: (lambda samples: {'segments': seg})), \
                    mock.patch.object(at, 'closure_problems', lambda info: ['module torch was loaded from /x']):
                with self.assertRaises(at.ToolError) as cm:
                    at.run_ladder(wav, script, d)
            self.assertIn('module torch was loaded from /x', str(cm.exception))
            self.assertFalse((d / at.RAW_NAME).exists())
            with mock.patch.object(at, 'check_environment', lambda *a, **k: (info, [])), \
                    mock.patch.object(at, 'mlx_transcribe_fn', lambda snap: (lambda samples: {'segments': seg})), \
                    mock.patch.object(at, 'closure_problems', lambda info: []):
                self.assertEqual(0, at.run_ladder(wav, script, d))
            self.assertTrue((d / at.RAW_NAME).exists())


class EnvironmentTests(unittest.TestCase):
    def test_home_comes_from_the_passwd_entry_never_from_HOME(self):
        with mock.patch.dict(os.environ, {'HOME': '/nonexistent-home'}):
            self.assertEqual(PW_HOME, at.user_home())
            self.assertEqual(PW_HOME, at.minimal_env()['HOME'])
        self.assertEqual(PW_HOME, at.USER_HOME)
        self.assertEqual(str(Path(PW_HOME) / '.cache' / 'huggingface' / 'hub'), str(at.HF_HUB))

    def test_minimal_env_has_exactly_four_keys_and_ffmpeg_dir_first_in_path(self):
        env = at.minimal_env()
        self.assertEqual(['HOME', 'PATH', 'LANG', 'TMPDIR'], list(env))
        self.assertEqual('/var/empty', env['TMPDIR'])               # root-owned and empty: nothing can be written or planted there
        self.assertEqual('en_US.UTF-8', env['LANG'])
        ff = at.resolve_ffmpeg()
        self.assertEqual(os.path.dirname(ff) + ':/usr/bin:/bin', env['PATH'])
        with mock.patch.object(at, 'FFMPEG_CANDIDATES', ('/nonexistent/ffmpeg',)):
            self.assertEqual('/usr/bin:/bin', at.minimal_env()['PATH'])

    def test_env_is_minimal_accepts_only_that_environment(self):
        mini = at.minimal_env()
        self.assertTrue(at.env_is_minimal(mini))
        self.assertTrue(at.env_is_minimal(dict(mini, __CF_USER_TEXT_ENCODING='0x1F5:0x0:0x0')))       # added by macOS itself
        for bad in (dict(mini, HOME='/elsewhere'), dict(mini, PATH='/tmp/evil:' + mini['PATH']), dict(mini, LANG='C'),
                    dict(mini, DYLD_INSERT_LIBRARIES='/x'), dict(mini, PYTHONPATH='/x'), dict(mini, HF_HOME='/x'),
                    dict(mini, NUMBA_CACHE_DIR='/x'), {k: v for k, v in mini.items() if k != 'TMPDIR'}, dict(mini, TMPDIR='/any/other/tmp'), dict(mini, LC_CTYPE='C.UTF-8'), {}):
            self.assertFalse(at.env_is_minimal(bad), bad)

    def test_ffmpeg_is_never_looked_up_in_PATH(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / 'ffmpeg'
            fake.write_text('#!/bin/sh\necho "ffmpeg version 0 FAKE"\n')
            fake.chmod(0o755)
            with mock.patch.dict(os.environ, {'PATH': d + ':' + os.environ.get('PATH', '')}):
                self.assertNotEqual(str(fake), at.resolve_ffmpeg())
                ident, problems = at.ffmpeg_identity()
            self.assertEqual([], problems)
            self.assertNotIn('FAKE', ident['version'])
            with mock.patch.object(at, 'FFMPEG_CANDIDATES', ('/nonexistent/ffmpeg',)):
                self.assertIsNone(at.resolve_ffmpeg())
                ident, problems = at.ffmpeg_identity()
                self.assertIsNone(ident)
                self.assertIn('ffmpeg not found in /nonexistent/ffmpeg', problems[0])

    def test_ffmpeg_identity_is_realpath_hash_and_first_version_line(self):
        ident, problems = at.ffmpeg_identity()
        self.assertEqual([], problems)
        self.assertEqual(['realpath', 'sha256', 'version'], list(ident))
        self.assertEqual(at.sha_file(os.path.realpath(at.resolve_ffmpeg())), ident['sha256'])
        self.assertTrue(ident['version'].startswith('ffmpeg version'))
        self.assertNotIn('\n', ident['version'])
        self.assertEqual(os.path.realpath(at.resolve_ffmpeg()).replace(PW_HOME, '~', 1), ident['realpath'])

    def test_tilde_keeps_the_user_name_out_of_pins_and_raw(self):
        self.assertEqual('~/.local/x', at._tilde(PW_HOME + '/.local/x'))
        self.assertEqual('/opt/homebrew/bin/x', at._tilde('/opt/homebrew/bin/x'))
        self.assertEqual(PW_HOME + 'x', at._tilde(PW_HOME + 'x'))                  # a sibling dir that only shares the prefix

    def test_ffmpeg_and_sysctl_subprocesses_get_the_minimal_environment(self):
        seen = []
        real = subprocess.run

        def spy(cmd, *a, **k):
            seen.append((cmd[0], k.get('env')))
            return real(cmd, *a, **k)
        with mock.patch.object(at.subprocess, 'run', spy):
            at.ffmpeg_identity()
            at._cpu_brand()
            with tempfile.TemporaryDirectory() as d:
                make_wav(Path(d) / 'a.wav', [(0.0, 1.0)], 1.0)
                at.detect_silences(Path(d) / 'a.wav')
        self.assertEqual(3, len(seen))
        for cmd, env in seen:
            self.assertIsNotNone(env, cmd)
            self.assertEqual(set(at.ENV_KEYS), set(env), cmd)
            self.assertEqual(PW_HOME, env['HOME'])

    def test_offline_variables_are_set_by_the_module_itself(self):
        code = 'import sys, os; sys.path.insert(0, %r); import asr_transcribe; print(os.environ["HF_HUB_OFFLINE"], os.environ["TRANSFORMERS_OFFLINE"], os.environ["HF_DATASETS_OFFLINE"])' % str(SCRIPTS)
        r = subprocess.run([*RUN, '-c', code], capture_output=True, text=True, env={'HF_HUB_OFFLINE': '0', 'PATH': '/usr/bin:/bin'})
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual('1 1 1', r.stdout.strip())


class BytecodeGuardTests(unittest.TestCase):
    def cli(self, flags, *args, env=None):
        return subprocess.run([str(PYBIN), *flags, str(SCRIPTS / 'asr_transcribe.py'), *args], capture_output=True, text=True, env=env)

    def test_refuses_with_exit_4_and_the_exact_command_unless_isolated_no_bytecode_and_pycache_prefix(self):
        for flags in ([], ['-B'], ['-I'], ['-I', '-B'], ['-B', '-X', 'pycache_prefix=/var/empty'], ['-I', '-X', 'pycache_prefix=/var/empty'],
                      ['-I', '-B', '-X', 'pycache_prefix=/tmp'],
                      ['-I', '-B', '-X', 'pycache_prefix=/var/empty'],              # everything but -S: sitecustomize / .pth would run first
                      ['-I', '-S', '-X', 'pycache_prefix=/var/empty'], ['-S', '-B', '-X', 'pycache_prefix=/var/empty'],
                      ['-I', '-S', '-B', '-X', 'pycache_prefix=/tmp']):
            for args in (['--check'], ['--fingerprint'], ['--wav', 'x', '--script', 'y', '--out-dir', 'z']):
                with self.subTest(flags=flags, args=args):
                    r = self.cli(flags, *args)
                    self.assertEqual(4, r.returncode, r.stderr)
                    self.assertEqual('', r.stdout)
                    self.assertIn('without site processing (-S)', r.stderr)
                    self.assertIn('Start it only through the launcher: /bin/bash', r.stderr)
                    self.assertIn('asr_run.sh asr_transcribe.py', r.stderr)

    def test_the_guard_is_the_first_statement_after_the_docstring_and_imports_only_sys(self):
        tree = ast.parse((SCRIPTS / 'asr_transcribe.py').read_text(encoding='utf-8'))
        body = tree.body
        self.assertIsInstance(body[0], ast.Expr)                                    # the docstring
        self.assertIsInstance(body[1], ast.Import)
        self.assertEqual(['sys'], [a.name for a in body[1].names])
        self.assertEqual(['RUN_FLAGS'], [t.id for t in body[2].targets])
        guard = body[3]
        self.assertIsInstance(guard, ast.If)
        self.assertIn('sys.pycache_prefix', ast.unparse(guard.test))
        self.assertIn('sys.flags.isolated', ast.unparse(guard.test))
        self.assertIn('sys.dont_write_bytecode', ast.unparse(guard.test))
        self.assertIn('sys.flags.no_site', ast.unparse(guard.test))                 # -S: no site / .pth / sitecustomize processing
        for stmt in body[:4]:                                                       # nothing but sys is imported before the guard
            self.assertFalse(isinstance(stmt, (ast.Import, ast.ImportFrom)) and any(a.name != 'sys' for a in stmt.names))
        a_tree = ast.parse((SCRIPTS / 'asr_align.py').read_text(encoding='utf-8'))
        self.assertEqual(['sys'], [a.name for a in a_tree.body[1].names])
        self.assertIn('sys.pycache_prefix', ast.unparse(a_tree.body[3].test))
        self.assertIn('sys.flags.no_site', ast.unparse(a_tree.body[3].test))

    def test_a_planted_pyc_is_read_without_the_flags_and_never_with_them(self):
        """The falsification of the reviewer: compile a MODIFIED copy of timing_defects.py (find_defects returns []) into
        __pycache__ as an unchecked-hash pyc, restore the real source.  Without the flags the planted pyc wins; with
        -I -B -X pycache_prefix=/var/empty the real source is compiled and runs."""
        with tempfile.TemporaryDirectory() as d:
            work = Path(d) / 'scripts'
            work.mkdir()
            shutil.copy(SCRIPTS / 'timing_defects.py', work / 'timing_defects.py')
            src = (work / 'timing_defects.py').read_text(encoding='utf-8')
            evil = src.replace('    words = flatten(pages)\n    duration = None', '    return []\n    words = flatten(pages)\n    duration = None')
            self.assertNotEqual(src, evil)
            (work / 'evil.py').write_text(evil, encoding='utf-8')
            pyc = Path(py_compile.compile(str(work / 'evil.py'), cfile=str(work / '__pycache__' / ('timing_defects.%s.pyc' % sys.implementation.cache_tag)),
                                          invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH))
            (work / 'evil.py').unlink()
            self.assertTrue(pyc.exists())
            probe = ('import sys; sys.path.insert(0, %r); import timing_defects as t\n'
                     'print(len(t.find_defects([{"start":0,"end":9,"words":[{"w":"x","s":0,"e":9.0}]}])))' % str(work))
            plain = subprocess.run([sys.executable, '-c', probe], capture_output=True, text=True, env={'PATH': '/usr/bin:/bin'})
            self.assertEqual(0, plain.returncode, plain.stderr)
            self.assertEqual('0', plain.stdout.strip(), 'without the flags the planted pyc was NOT read: the test proves nothing')
            guarded = subprocess.run([*RUN, '-c', probe], capture_output=True, text=True, env={'PATH': '/usr/bin:/bin'})
            self.assertEqual(0, guarded.returncode, guarded.stderr)
            real_count = len(td.find_defects([{'start': 0, 'end': 9, 'words': [{'w': 'x', 's': 0, 'e': 9.0}]}]))
            self.assertGreater(real_count, 0)                                  # a 9 s word is a defect for the real detector
            self.assertEqual(str(real_count), guarded.stdout.strip(), 'the planted pyc was read although pycache_prefix=/var/empty')
            self.assertEqual(['timing_defects.%s.pyc' % sys.implementation.cache_tag], [p.name for p in (work / '__pycache__').iterdir()])

    def test_site_processing_runs_sitecustomize_without_dash_S_and_never_with_it(self):
        """why -S: a sitecustomize.py on the path runs before any check unless site processing is off (PYTHONPATH stands in for a
        site dir here; a .pth line is processed by the same `site` module)"""
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'sitecustomize.py').write_text('import sys; sys.stdout.write("SITECUSTOMIZE RAN\\n")\n', encoding='utf-8')
            env = {'PATH': '/usr/bin:/bin', 'PYTHONPATH': d}
            plain = subprocess.run([str(PYBIN), '-B', '-c', 'pass'], capture_output=True, text=True, env=env)
            self.assertIn('SITECUSTOMIZE RAN', plain.stdout, 'the control did not run sitecustomize: the test proves nothing')
            guarded = subprocess.run([str(PYBIN), '-S', '-B', '-c', 'pass'], capture_output=True, text=True, env=env)
            self.assertEqual('', guarded.stdout)

    def test_var_empty_is_root_owned_so_nothing_can_be_planted_there(self):
        st = os.stat('/var/empty')
        self.assertEqual(0, st.st_uid)
        self.assertFalse(os.access('/var/empty', os.W_OK) and os.getuid() != 0)


class _Capture:
    """capture print() output of the module under test"""
    def __enter__(self):
        import io
        import contextlib
        self.buf = io.StringIO()
        self.cm = contextlib.redirect_stdout(self.buf)
        self.cm.__enter__()
        return self

    def __exit__(self, *exc):
        self.cm.__exit__(*exc)
        self.text = self.buf.getvalue()
        return False


if __name__ == '__main__':
    unittest.main()
