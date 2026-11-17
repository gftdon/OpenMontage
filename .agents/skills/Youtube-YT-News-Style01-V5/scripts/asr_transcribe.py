#!/usr/bin/env python3
"""asr_transcribe.py — step 1 of the word-timing chain: voice-over wav -> raw whisper words (raw_asr.json), decoded
deterministically, checked with timing_defects.py after aligning the script in-process (asr_align.py), and repaired by
a FIXED ladder.  No CLI / environment overrides of the model, the decoder or the ladder.

  bash asr_run.sh asr_transcribe.py --wav vo16k.wav --script script.txt --out-dir <dir>
  bash asr_run.sh asr_transcribe.py --check          (toolchain / model cache / pins only; loads nothing)
  bash asr_run.sh asr_transcribe.py --check --deep   (also sha256 of the ~3 GB weights file against its blob name; for the checker only)
  bash asr_run.sh asr_transcribe.py --fingerprint    (prints the toolchain fingerprint as JSON; loads nothing)

Exit: 0 ok (<dir>/raw_asr.json written), 2 bad arguments / input (the wav must be 16 kHz mono 16-bit PCM),
      4 tool / venv / model / pin problem (nothing is downloaded: HF_HUB_OFFLINE=1; --fingerprint prints nothing then;
        also: not started through asr_run.sh, see below),
      5 ladder exhausted
      (<dir>/word_timing.failed.json written, one DEFECT line per remaining defect; deterministic, so never retry).

Started ONLY through asr_run.sh.  That launcher (root-owned tools, absolute paths, no python) first verifies the manifest
asr_venv.manifest: sha256 of every file of the Cellar python it will exec, of the stdlib tree and of the whole V4 venv
site-packages (so a wrapper python, a sitecustomize.py, a .pth line, an edited stdlib module or a new module is refused
BEFORE any python code runs), then execs the Cellar python binary directly as
  env -i HOME=<passwd home> PATH=<ffmpeg dir>:/usr/bin:/bin LANG=en_US.UTF-8 TMPDIR=/var/empty  python -I -S -B -X pycache_prefix=/var/empty
-I: no PYTHON* variables, no cwd / script dir on sys.path; -S: no site / .pth / sitecustomize processing, the venv is never
used as an interpreter (this file appends the V4 venv's site-packages itself); -B + pycache_prefix=/var/empty (root-owned,
empty): no bytecode is ever read, so every module is compiled from its source.  Run as __main__ this file refuses (exit 4,
before it imports anything but sys) unless all four hold, and it re-runs itself ONCE under the minimal environment if the
caller's differs (a second mismatch is exit 4; macOS adds __CF_USER_TEXT_ENCODING).

Pins (a mismatch is exit 4 naming the file): model MODEL_ID at snapshot MODEL_SNAPSHOT under <passwd home>/.cache/huggingface/hub
(HF_HOME / HF_HUB_CACHE / $HOME are deliberately ignored) with the blob names MODEL_BLOBS of config.json and the weights, the
sha256 of the installed mlx_whisper transcribe.py / decoding.py / timing.py / audio.py, and the decode params PARAMS
(temperature 0 only, no conditioning on the previous window: two full passes over the same 647 s audio gave the same
5,695 tokens and no repetition loop; the library defaults did not).  The bytes of the interpreter, the stdlib and the venv
are pinned by the manifest (checked by asr_run.sh, outside python); the fingerprint carries the manifest's sha256.  After the
decode every loaded module must come from the stdlib, the V4 venv site-packages or this skill's scripts (closure_problems).

Ladder (first rung whose result has no defect wins):
  R0  the whole wav.
  R1  regions = every remaining defect span +- R1_PAD_S; each edge moved to the midpoint of the nearest silence (ffmpeg
      silencedetect -35 dB / 0.35 s, the values of timing_check.py) that keeps the defect inside, at most R1_SNAP_S away;
      overlapping regions merged; more than R1_MAX_REGIONS regions or more than R1_MAX_TOTAL_S seconds = systemic ->
      exit 5 without decoding.  Each region is re-decoded from the exact sample slice of the wav (same params, times +
      the region offset); the previous rung's words whose midpoint lies in a region are replaced by the region's words
      whose midpoint lies in it.
  A further rung is one more (name, function) entry in RUNGS (function(ctx, prev) -> (rung entry, segments)).

raw_asr.json = {schema 'yt-news-v4-raw-asr', version 1, audio:{wav_sha256, duration}, script_sha256,
  model:{id, snapshot, files:{config.json / weights file: blob name in the HF cache (the blob's sha256 for LFS files)}},
  mlx_whisper:{version, files:{name: sha256}}, mlx:{version[, mlx-metal]}, tokenizer:{pythainlp},
  platform:{system, release, machine, mac_ver, cpu}, ffmpeg:{realpath, sha256, version (first line of -version)},
  venv:{manifest_sha256, python: sys.version}, params, code:{chain file: sha256},
  rungs:[{rung, regions:[[s, e]], seconds}],
  segments:[{start, end, text, compression_ratio, avg_logprob, no_speech_prob, rung, words:[{word, start, end}]}]}
  `seconds` = seconds of AUDIO decoded by that rung (not wall time).  No clock values, no absolute path, no user name
  anywhere: same input -> same bytes.
Fingerprint = the toolchain identity part of that file (model, mlx_whisper, mlx, tokenizer, platform, ffmpeg, venv, params, code), one
  definition (fingerprint()) used for the file header, the rung keys and `--fingerprint`; compare_fingerprint() lists the
  differing leaves.  A checker that re-transcribes and demands identical bytes must first demand an identical fingerprint.
Resume: each finished rung is written atomically to <dir>/asr_rung_<name>.json with a key over its inputs (wav, pins,
  code of this chain, and for rungs after R0 the script); a killed job continues after the last finished rung.
Tests replace the model call only: run_ladder(wav, script, out_dir, transcribe_fn=fake, env_info={...}).
"""
import sys

# ---- guard: nothing but `sys` has been imported yet.  No bytecode, no site processing (see the docstring).
RUN_FLAGS = ('-I', '-S', '-B', '-X', 'pycache_prefix=/var/empty')
if __name__ == '__main__' and not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
                                   and sys.pycache_prefix == '/var/empty'):
    sys.stderr.write('ERROR: refusing to run: python was not started isolated (-I), without site processing (-S) and without '
                     'bytecode (-B -X pycache_prefix=/var/empty).  Start it only through the launcher: '
                     '/bin/bash %s/asr_run.sh %s <arguments>\n' % (sys.argv[0].rpartition('/')[0] or '.', sys.argv[0].rpartition('/')[2]))
    sys.exit(4)

import os  # noqa: E402
import pwd  # noqa: E402
from pathlib import Path  # noqa: E402

FFMPEG_CANDIDATES = ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/usr/bin/ffmpeg')   # first executable wins; $PATH is never searched
ENV_LANG = 'en_US.UTF-8'
ENV_TMPDIR = '/var/empty'
ENV_KEYS = ('HOME', 'PATH', 'LANG', 'TMPDIR')
OS_ADDED_ENV = ('__CF_USER_TEXT_ENCODING',)       # macOS puts this into every process; it is only an encoding hint


def user_home():
    """The home directory of the account that runs this process, from the passwd entry (never $HOME)."""
    return pwd.getpwuid(os.getuid()).pw_dir


USER_HOME = user_home()


def resolve_ffmpeg():
    """-> the ffmpeg this chain uses (a fixed list of locations, not $PATH) or None."""
    for c in FFMPEG_CANDIDATES:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def minimal_env():
    """The ONLY environment the decoder, ffmpeg and their libraries ever see (asr_run.sh builds the same one)."""
    ff = resolve_ffmpeg()
    path = (os.path.dirname(ff) + ':' if ff else '') + '/usr/bin:/bin'
    return {'HOME': USER_HOME, 'PATH': path, 'LANG': ENV_LANG, 'TMPDIR': ENV_TMPDIR}


def env_is_minimal(env_mapping):
    """True when `env_mapping` is exactly minimal_env() (every value compared) plus what macOS adds itself."""
    env = {k: v for k, v in dict(env_mapping).items() if k not in OS_ADDED_ENV}
    return env == minimal_env()


if __name__ == '__main__' and not env_is_minimal(os.environ):
    # the caller's environment must not steer the chain: start over ONCE under the minimal one (same interpreter, same flags)
    if 'asr_reexec' in sys._xoptions:
        sys.stderr.write('ERROR: the environment is still not the minimal one after a restart; stop and report this.\n')
        sys.exit(4)
    _marker = ['-X', 'asr_manifest_sha256=' + sys._xoptions['asr_manifest_sha256']] if 'asr_manifest_sha256' in sys._xoptions else []
    os.execve(sys.executable, [sys.executable, *RUN_FLAGS, '-X', 'asr_reexec=1', *_marker, os.path.abspath(sys.argv[0]), *sys.argv[1:]],
              minimal_env())

# The V4 venv is never an interpreter: its site-packages are appended here (-S: nothing processed them).  Fixed path, no override.
VENV_ROOT = Path(USER_HOME) / '.cache' / 'yt-news-v4' / 'asr-venv'
SITE_DIR = VENV_ROOT / 'lib' / 'python3.12' / 'site-packages'
if __name__ == '__main__':
    sys.path.append(str(SITE_DIR))

for _k in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'HF_DATASETS_OFFLINE'):   # before anything can import huggingface_hub
    os.environ[_k] = '1'

import argparse  # noqa: E402
import hashlib  # noqa: E402
import importlib.metadata  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import platform  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import sysconfig  # noqa: E402
import time  # noqa: E402
import wave  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import asr_align  # noqa: E402
import timing_defects  # noqa: E402

# ---------------------------------------------------------------- pins (no overrides)
MODEL_ID = 'mlx-community/whisper-large-v3-mlx'
MODEL_SNAPSHOT = '49e6aa286ad60c14352c404340ded53710378a11'          # the snapshot dir in the local HF cache (2026-08-19)
HF_HUB = Path(USER_HOME) / '.cache' / 'huggingface' / 'hub'
MANIFEST_NAME = 'asr_venv.manifest'                                    # sha256 of the interpreter, stdlib and venv files (asr_run.sh verifies it)
SETUP_HINT = ('run `bash %s/setup_asr_venv.sh` (a human, not the agent) - do not install, edit or rebuild anything yourself'
              % Path(__file__).resolve().parent)
MLX_WHISPER_FILES = {                                                  # mlx-whisper 0.4.3 as installed in the venv
    'transcribe.py': '21f015e0d56c5e6194d07d86d772730940fff52d8f06d55838ae92ebccc24fbb',
    'decoding.py': 'fae5828b2d80760e6dbcd5a51d7704769dca67cad5d559085d0a08d40964e616',
    'timing.py': '2736c2bf19f2ebbaa521dae9deb3748c6b5d5f319af729f4078dc2b0769822cd',
    'audio.py': '1be84770852520df7c980376e133155b9a0b127ed59f28a297df0a96987b12eb',
}
PARAMS = {'language': 'th', 'temperature': (0.0,), 'condition_on_previous_text': False, 'word_timestamps': True}
SAMPLE_RATE = 16000                                                    # mlx_whisper.audio.SAMPLE_RATE
SILENCE_NOISE_DB = -35                                                 # = timing_check.py THRESHOLDS silence_noise_db (= timing_defects.SILENCE_NOISE_DB)
SILENCE_MIN_S = 0.35                                                   # = timing_check.py THRESHOLDS silence_min_s (= timing_defects.SILENCE_MIN_S)
R1_PAD_S = 3.0
R1_SNAP_S = 10.0
R1_MAX_REGIONS = 6
R1_MAX_TOTAL_S = 120.0
# The blob names of the model files in the HF cache (the cache keeps every file as a symlink into <model dir>/blobs/<name>; for the
# 3 GB LFS weights the name IS the sha256 of the content, `--check --deep` hashes the content to prove it; config.json is a git blob,
# its name is the git sha1).  A different name = a different model file: exit 4, restore the cache, never edit the pin.
MODEL_BLOBS = {
    'config.json': '2c626df3c540bdc0287b11725441d10e1af73680',
    'weights.npz': '05ff791ce3630fae47e7c51004e9666204d786246ec07cac6110af768099b40d',
}
# config.json is small: its CONTENT is hashed on every run (normal mode and --check) and compared with this sha256.
MODEL_CONFIG_SHA256 = '34982ce6ae286095000f82ae9583b3431639e8b092bf60c961f203745e6500e3'
# The snapshot dir holds exactly these files and no other (a stray weights.safetensors, an extra config, a tokenizer file ... would
# change what the decoder loads).  The first two are the loaded ones (MODEL_BLOBS); the last two are the repo's README and
# .gitattributes, which the decoder never reads, pinned by blob name only so that the real snapshot is not refused.
MODEL_SNAPSHOT_EXTRAS = {
    '.gitattributes': 'a6344aac8c09253b3b630fb776ae94478aa0275b',
    'README.md': 'aa6058f979bed0dce9307e6e2ce8c0764824f855',
}
# What the chain executes from outside this skill (the Cellar python, its stdlib, the 26 distributions of the V4 venv, measured
# 2026-11-13: 1,681 modules loaded by a real decode) is pinned by asr_venv.manifest and checked by asr_run.sh, outside python.
RAW_SCHEMA = asr_align.RAW_SCHEMA
RAW_NAME = 'raw_asr.json'
FAILED_NAME = 'word_timing.failed.json'
FAILED_SCHEMA = 'yt-news-v4-word-timing-failed'
CKPT_SCHEMA = 'yt-news-v4-asr-rung'
CODE_FILES = ('asr_transcribe.py', 'asr_align.py', 'timing_defects.py', 'asr_run.sh')


class InputError(Exception):
    """exit 2"""


class ToolError(Exception):
    """exit 4"""


class Systemic(Exception):
    """the ladder must stop: exit 5"""
    def __init__(self, msg, regions=()):
        super().__init__(msg)
        self.regions = [list(r) for r in regions]


def sha_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def sha_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- environment / pins
def _cpu_brand():
    """chip name (sysctl machdep.cpu.brand_string) or None"""
    try:
        proc = subprocess.run(['/usr/sbin/sysctl', '-n', 'machdep.cpu.brand_string'], capture_output=True, text=True, timeout=5,
                              env=minimal_env())
    except (OSError, subprocess.SubprocessError):
        return None
    out = proc.stdout.strip()
    return out if proc.returncode == 0 and out else None


def platform_identity():
    """-> ({system, release, machine, mac_ver, cpu}, problems).  A macOS / Metal update may change GPU kernels, so the OS
    and the chip are part of "the same toolchain"."""
    cpu = _cpu_brand()
    ident = {'system': platform.system(), 'release': platform.release(), 'machine': platform.machine(),
             'mac_ver': platform.mac_ver()[0], 'cpu': cpu}
    problems = [] if cpu else ['cannot read the chip name (sysctl -n machdep.cpu.brand_string failed)']
    return ident, problems


def mlx_identity():
    """-> ({version[, 'mlx-metal': version]}, problems): the mlx array library that runs the decoder (mlx-metal only when
    that distribution is installed)."""
    ident, problems = {}, []
    try:
        ident['version'] = importlib.metadata.version('mlx')
    except importlib.metadata.PackageNotFoundError:
        ident['version'] = None
        problems.append('mlx distribution metadata not found')
    try:
        ident['mlx-metal'] = importlib.metadata.version('mlx-metal')
    except importlib.metadata.PackageNotFoundError:
        pass
    return ident, problems


def model_files(snap, hub):
    """-> ({file name: blob name}, problems) for config.json and the weights file(s) present in the snapshot dir.  The HF
    cache keeps every file as a symlink into <model dir>/blobs/<name> (LFS: the sha256 of the content, git files: the
    git blob sha1), so the blob name identifies the content without hashing 3 GB.  A regular file or a link pointing
    elsewhere means the cache was edited by hand: null + problem."""
    blobs = (Path(hub) / ('models--' + MODEL_ID.replace('/', '--')) / 'blobs').resolve()
    out, problems = {}, []
    for name in ('config.json', 'weights.npz', 'weights.safetensors'):
        f = Path(snap) / name
        if not (f.exists() or f.is_symlink()):
            continue
        target = Path(os.path.realpath(f))
        if f.is_symlink() and target.parent == blobs and target.is_file():
            out[name] = target.name
        else:
            out[name] = None
            problems.append('model file %s is not a link into the HF cache blobs dir (%s): the cache was modified by hand; '
                            'restore it with the original download, do not edit the pin' % (name, blobs))
    return out, problems


def _tilde(path):
    """a path under the passwd home as ~/..., so no user name enters a pin or the raw file"""
    path = str(path)
    return '~' + path[len(USER_HOME):] if path == USER_HOME or path.startswith(USER_HOME + os.sep) else path


def ffmpeg_identity():
    """-> ({realpath, sha256, version}, problems): the ffmpeg whose silencedetect decides the R1 region edges and which cuts
    the wav.  Resolved once from a fixed list (never $PATH)."""
    path = resolve_ffmpeg()
    if path is None:
        return None, ['ffmpeg not found in %s (silencedetect of the repair rung)' % ', '.join(FFMPEG_CANDIDATES)]
    real = os.path.realpath(path)
    try:
        sha = sha_file(real)
        proc = subprocess.run([path, '-version'], capture_output=True, text=True, timeout=20, env=minimal_env())
        first = proc.stdout.splitlines()[0].strip() if proc.returncode == 0 and proc.stdout.strip() else None
    except (OSError, subprocess.SubprocessError) as e:
        return None, ['cannot identify ffmpeg %s: %s' % (path, e)]
    if not first:
        return None, ['ffmpeg -version printed nothing (%s)' % path]
    return {'realpath': _tilde(real), 'sha256': sha, 'version': first}, []


def venv_identity():
    """-> ({manifest_sha256, python}, problems): what pins the interpreter, the stdlib and the venv is the manifest, verified by
    asr_run.sh outside python; the fingerprint carries the manifest's sha256 (and which interpreter ran), so another manifest
    is a visible toolchain change."""
    ident = {'manifest_sha256': None, 'python': sys.version}
    try:
        ident['manifest_sha256'] = sha_file(HERE / MANIFEST_NAME)
    except OSError:
        return ident, ['%s is missing next to this script: %s' % (MANIFEST_NAME, SETUP_HINT)]
    return ident, []


def launcher_problems():
    """-> [problem]: python must have been started by asr_run.sh, which passes the sha256 of the manifest it just verified
    (-X asr_manifest_sha256=...).  Accident protection (the flag could be typed by hand); the verification itself is the
    launcher's, outside python."""
    ident, problems = venv_identity()
    if problems:
        return problems
    if sys._xoptions.get('asr_manifest_sha256') != ident['manifest_sha256']:
        return ['not started through the launcher (asr_run.sh verifies the interpreter, the stdlib and the venv against %s first): '
                'run  /bin/bash %s/asr_run.sh %s <arguments>' % (MANIFEST_NAME, HERE, Path(sys.argv[0]).name)]
    return []


def closure_problems(info, modules=None, paths=None):
    """After a real decode: every loaded module must come from the stdlib, from the V4 venv site-packages (every file of it is in
    the manifest) or from this skill's chain scripts, and sys.path may only hold those places.  -> [problem]."""
    site = Path(os.path.realpath(info['site_dir']))
    stdlib = Path(os.path.realpath(sysconfig.get_path('stdlib')))
    chain = {os.path.realpath(HERE / n) for n in CODE_FILES}
    out = []
    for name, mod in sorted((sys.modules if modules is None else modules).items()):
        f = getattr(mod, '__file__', None)
        if not f:
            continue
        real = Path(os.path.realpath(f))
        if str(real) in chain:
            continue
        try:
            rel = real.relative_to(stdlib)
            if rel.parts and rel.parts[0] != 'site-packages':
                continue
        except ValueError:
            pass
        try:
            real.relative_to(site)
            continue
        except ValueError:
            pass
        out.append('module %s was loaded from %s, which is neither the stdlib, the ASR venv nor a chain script' % (name, real))
    allowed = {stdlib, stdlib / 'lib-dynload', site, Path(os.path.realpath(HERE))}
    # python always puts <prefix>/lib/python3NN.zip on sys.path, whether or not the file exists.  Absent = harmless (nothing to
    # import); present = code outside the manifest, which asr_run.sh already refuses, and so does this check.
    zipname = stdlib.parent / ('python%d%d.zip' % sys.version_info[:2])
    for entry in (sys.path if paths is None else paths):
        real_entry = Path(os.path.realpath(entry))
        if real_entry == zipname and not os.path.lexists(entry):
            continue
        if real_entry not in allowed:
            out.append('sys.path holds %s (not the stdlib, the ASR venv site-packages or this skill)' % entry)
    return out


def weights_problems(snap, blobs=None):
    """--check --deep: sha256 of the weights file content (~3 GB) with /usr/bin/shasum (root-owned, outside python) against its blob
    name, which is the sha256 LFS recorded.  -> [problem]."""
    blobs = MODEL_BLOBS if blobs is None else blobs
    want = blobs.get('weights.npz')
    f = Path(snap) / 'weights.npz'
    real = os.path.realpath(f)
    try:
        proc = subprocess.run(['/usr/bin/shasum', '-a', '256', real], capture_output=True, text=True, timeout=1800, env=minimal_env())
    except (OSError, subprocess.SubprocessError) as e:
        return ['cannot hash the model weights %s: %s' % (real, e)]
    got = proc.stdout.split()[0] if proc.returncode == 0 and proc.stdout.split() else None
    if got != want:
        return ['the content of the model weights %s hashes to %s, not %s (the blob name): the file was modified or is damaged; '
                'restore the HF cache from the original download, do not edit the pin' % (real, got, want)]
    return []


def check_environment(hub=HF_HUB, mlx_pkg=None, venv=True, blobs=None, deep=False, config_sha256=None, extras=None):
    """-> (env_info for raw_asr.json, problems).  Loads no model and runs no decoder.  hub / mlx_pkg / venv=False / blobs: unit
    tests only (the CLI and run_ladder always use the defaults: the fixed cache dir, the installed mlx_whisper package, the
    manifest, MODEL_BLOBS, MODEL_CONFIG_SHA256, MODEL_SNAPSHOT_EXTRAS; config_sha256 / extras are unit-test hooks too).  deep=True also
    hashes the weights content (--check --deep).  The snapshot dir must hold exactly the pinned files (item 7), and config.json's
    content is hashed every time.
    env_info['snapshot_dir'] / ['site_dir'] are for running the model and closure_problems only; fingerprint() never carries
    them (they are paths)."""
    blobs = MODEL_BLOBS if blobs is None else blobs
    config_sha256 = MODEL_CONFIG_SHA256 if config_sha256 is None else config_sha256
    extras = MODEL_SNAPSHOT_EXTRAS if extras is None else extras
    problems, files, version = [], {}, None
    if mlx_pkg is None:
        spec = importlib.util.find_spec('mlx_whisper')
        if spec is not None and spec.submodule_search_locations:
            mlx_pkg = Path(list(spec.submodule_search_locations)[0])
    if mlx_pkg is None:
        problems.append('mlx_whisper is not installed in the ASR venv %s: %s' % (VENV_ROOT, SETUP_HINT))
    else:
        pkg = Path(mlx_pkg)
        for name, want in MLX_WHISPER_FILES.items():
            try:
                got = sha_file(pkg / name)
            except OSError:
                problems.append('mlx_whisper/%s is missing in %s' % (name, pkg))
                continue
            files[name] = got
            if got != want:
                problems.append('mlx_whisper/%s sha256 %s does not match the pinned %s (the installed decoder changed: '
                                'restore mlx-whisper 0.4.3 in the venv; do not edit the pin)' % (name, got[:16], want[:16]))
        try:
            version = importlib.metadata.version('mlx-whisper')
        except importlib.metadata.PackageNotFoundError:
            problems.append('mlx-whisper distribution metadata not found')
    try:
        tok = asr_align.tokenizer_version()
    except asr_align.TokenizerError as e:
        tok = None
        problems.append(str(e))
    snap = Path(hub) / ('models--' + MODEL_ID.replace('/', '--')) / 'snapshots' / MODEL_SNAPSHOT
    if not ((snap / 'config.json').is_file() and ((snap / 'weights.npz').exists() or (snap / 'weights.safetensors').exists())):
        problems.append('speech model %s snapshot %s is not in the local HF cache (%s); not downloading' % (MODEL_ID, MODEL_SNAPSHOT, snap))
    mfiles, p = model_files(snap, hub)
    problems += p
    if snap.is_dir():
        for name in sorted(os.listdir(snap)):
            if name in blobs:
                continue
            if name in extras:                          # not loaded by the decoder: allowed, but only as the pinned blob
                target = os.path.realpath(snap / name)
                if os.path.basename(target) != extras[name]:
                    problems.append('snapshot file %s is not the pinned blob %s: restore the HF cache from the original download' % (name, extras[name]))
                continue
            problems.append('the model snapshot holds a file that is not pinned: %s (a stray weights / config / tokenizer file would change what '
                            'the decoder loads); remove nothing yourself: restore the HF cache from the original download' % name)
        cfg = snap / 'config.json'
        if cfg.is_file():
            got = sha_file(cfg)
            if got != config_sha256:
                problems.append('model config.json content hashes to %s, not the pinned %s (the decoder reads its hyper-parameters from it): '
                                'restore the HF cache from the original download, do not edit the pin' % (got, config_sha256))
    for name, want in sorted(blobs.items()):
        got = mfiles.get(name)
        if got is not None and got != want:
            problems.append('model file %s is the blob %s, not the pinned %s (a different file than the one the pins were made '
                            'with): restore the HF cache from the original download, do not edit the pin' % (name, got, want))
    if deep and not problems:
        problems += weights_problems(snap, blobs)
    mlx, p = mlx_identity()
    problems += p
    plat, p = platform_identity()
    problems += p
    ff, p = ffmpeg_identity()
    problems += p
    vident, site_dir = None, None
    if venv:
        vident, p = venv_identity()
        problems += p
        site_dir = str(SITE_DIR)
    info = {'model': {'id': MODEL_ID, 'snapshot': MODEL_SNAPSHOT, 'files': mfiles},
            'mlx_whisper': {'version': version, 'files': files},
            'mlx': mlx,
            'tokenizer': {'pythainlp': tok},
            'platform': plat,
            'ffmpeg': ff,
            'venv': vident,
            'snapshot_dir': str(snap), 'site_dir': site_dir}
    return info, problems


FINGERPRINT_KEYS = ('model', 'mlx_whisper', 'mlx', 'tokenizer', 'platform', 'ffmpeg', 'venv', 'params', 'code')


def fingerprint(info, params=None, code=None):
    """The identity of the transcription toolchain = exactly the identity fields raw_asr.json carries (model blobs,
    mlx-whisper files + version, mlx version, pythainlp, OS / chip, ffmpeg binary, the manifest of the interpreter + stdlib + venv
    (its sha256) and the interpreter version, decode params, sha256 of the chain's code files).  One definition for the raw header, the rung keys and --fingerprint.
    No absolute path of the user's home, no clock."""
    params = PARAMS if params is None else params
    if code is None:
        code = {n: sha_file(HERE / n) for n in CODE_FILES}
    out = {k: info[k] for k in FINGERPRINT_KEYS if k not in ('params', 'code')}
    out['params'] = {k: list(v) if isinstance(v, tuple) else v for k, v in params.items()}
    out['code'] = dict(code)
    return {k: out[k] for k in FINGERPRINT_KEYS}


_MISSING = object()


def _show(v):
    if v is _MISSING:
        return '<missing>'
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, sort_keys=True)


OS_UPDATE_HINT = ('hint: the OS was updated after this word timing was made — redo the word timing step and deliver again')


def compare_fingerprint(recorded, current):
    """-> one line per differing leaf, e.g. 'mlx.version: 0.31.2 (production) != 0.31.3 (this machine)'; [] = same.  A key
    present on one side only is a difference (fail closed).  When platform.release / platform.mac_ver differ, ONE more last line
    (OS_UPDATE_HINT) says to redo the word timing and deliver again."""
    out = []

    def walk(path, a, b):
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(set(a) | set(b), key=str):
                walk('%s.%s' % (path, k) if path else str(k), a.get(k, _MISSING), b.get(k, _MISSING))
        elif isinstance(a, list) and isinstance(b, list):
            for i in range(max(len(a), len(b))):
                walk('%s[%d]' % (path, i), a[i] if i < len(a) else _MISSING, b[i] if i < len(b) else _MISSING)
        elif a is _MISSING or b is _MISSING or type(a) is not type(b) or a != b:
            out.append('%s: %s (production) != %s (this machine)' % (path or 'fingerprint', _show(a), _show(b)))
    walk('', recorded, current)
    if any(l.startswith(('platform.release:', 'platform.mac_ver:')) for l in out):
        out.append(OS_UPDATE_HINT)                       # one extra line; the failure condition is unchanged (the leaves above already differ)
    return out


def mlx_transcribe_fn(snapshot_dir):
    """The ONLY model call: float32 samples (16 kHz mono) -> mlx_whisper result dict."""
    def fn(samples):
        import mlx_whisper
        return mlx_whisper.transcribe(samples, path_or_hf_repo=str(snapshot_dir), verbose=False,
                                      language=PARAMS['language'], temperature=PARAMS['temperature'],
                                      condition_on_previous_text=PARAMS['condition_on_previous_text'],
                                      word_timestamps=PARAMS['word_timestamps'])
    return fn


# ---------------------------------------------------------------- input
def read_wav(path):
    """-> (float32 samples exactly as mlx_whisper.audio.load_audio makes them: int16 / 32768, sha256, duration)."""
    import numpy as np
    try:
        with wave.open(str(path), 'rb') as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != SAMPLE_RATE or w.getcomptype() != 'NONE':
                raise InputError('%s is not a 16 kHz mono 16-bit PCM wav (channels %d, bytes %d, rate %d)'
                                 % (path, w.getnchannels(), w.getsampwidth(), w.getframerate()))
            frames = w.readframes(w.getnframes())
    except (OSError, EOFError, wave.Error) as e:
        raise InputError('cannot read wav %s: %s' % (path, e))
    samples = np.frombuffer(frames, dtype='<i2').astype(np.float32) / np.float32(32768.0)
    if samples.size == 0:
        raise InputError('%s has no samples' % path)
    return samples, sha_file(path), samples.size / SAMPLE_RATE


def detect_silences(wav):
    """[(start, end)] from ffmpeg silencedetect: the ONE definition lives in timing_defects.py (the raw-gap rule and R1 use it)."""
    try:
        return timing_defects.detect_silences(wav, resolve_ffmpeg(), minimal_env())
    except RuntimeError as e:
        raise ToolError(str(e))


# ---------------------------------------------------------------- raw records
def _f(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _t(x, offset):
    return float(x) if offset == 0 else round(float(x) + offset, 2)


def seg_record(s, offset, rung):
    return {'start': _t(s['start'], offset), 'end': _t(s['end'], offset), 'text': str(s.get('text', '')),
            'compression_ratio': _f(s.get('compression_ratio')), 'avg_logprob': _f(s.get('avg_logprob')),
            'no_speech_prob': _f(s.get('no_speech_prob')), 'rung': rung,
            'words': [{'word': str(w['word']), 'start': _t(w['start'], offset), 'end': _t(w['end'], offset)}
                      for w in (s.get('words') or [])]}


def decode(ctx, samples, offset, rung):
    try:
        result = ctx['transcribe_fn'](samples)
    except (InputError, ToolError):
        raise
    except Exception as e:  # noqa: BLE001 - the decoder is a tool; any crash is exit 4
        raise ToolError('transcription failed: %s: %s' % (type(e).__name__, e))
    if not isinstance(result, dict) or not isinstance(result.get('segments'), list):
        raise ToolError('transcription returned no segments list')
    return [seg_record(s, offset, rung) for s in result['segments']]


def _mid(w):
    return (w['start'] + w['end']) / 2.0


def _inside(t, regions):
    return any(lo <= t <= hi for lo, hi in regions)


def splice(old_segments, regions, new_segments):
    """old words whose midpoint lies in a region are dropped (a segment is split around them; a word-less segment goes by
    its own midpoint); new segments keep only their words whose midpoint lies in a region; result sorted by time."""
    kept = []
    for seg in old_segments:
        if not seg['words']:
            if not _inside((seg['start'] + seg['end']) / 2.0, regions):
                kept.append(seg)
            continue
        runs, run = [], []
        for w in seg['words']:
            if _inside(_mid(w), regions):
                if run:
                    runs.append(run)
                run = []
            else:
                run.append(w)
        if run:
            runs.append(run)
        for r in runs:
            if len(r) == len(seg['words']):
                kept.append(seg)
            else:
                kept.append(dict(seg, start=r[0]['start'], end=r[-1]['end'], text=''.join(w['word'] for w in r), words=r))
    fresh = []
    for seg in new_segments:
        ws = [w for w in seg['words'] if _inside(_mid(w), regions)]
        if ws:
            fresh.append(seg if len(ws) == len(seg['words']) else
                         dict(seg, start=ws[0]['start'], end=ws[-1]['end'], text=''.join(w['word'] for w in ws), words=ws))
    out = kept + fresh
    out.sort(key=lambda s: (s['words'][0]['start'] if s['words'] else s['start'], s['start']))
    return out


def plan_regions(defects, silences, duration):
    """Defects -> merged repair regions [[lo, hi]] (10 ms grid, always inside [0, duration] and never empty).  Systemic when a
    defect has no finite span, when a region would be empty (a defect outside the audio), or the plan exceeds R1_MAX_REGIONS /
    R1_MAX_TOTAL_S."""
    mids = sorted((a + b) / 2.0 for a, b in silences)
    regs = []
    for d in defects:
        s, e = d.get('start'), d.get('end')
        if s is None or e is None or not (math.isfinite(s) and math.isfinite(e)):
            raise Systemic('defect %s has no finite time span; a region cannot be planned' % d.get('code'))
        s, e = min(s, e), max(s, e)
        lo, hi = max(0.0, s - R1_PAD_S), e + R1_PAD_S
        left = [m for m in mids if m <= s and abs(m - lo) <= R1_SNAP_S]
        right = [m for m in mids if m >= e and abs(m - hi) <= R1_SNAP_S]
        if left:
            lo = min(left, key=lambda m: (abs(m - lo), m))
        if right:
            hi = min(right, key=lambda m: (abs(m - hi), m))
        lo = math.floor(lo * 100 + 1e-6) / 100.0                      # 10 ms grid, then clamp to the audio [0, duration]
        hi = math.ceil(hi * 100 - 1e-6) / 100.0
        lo, hi = min(max(lo, 0.0), duration), min(max(hi, 0.0), duration)
        if lo >= hi:
            raise Systemic('defect %s at %s s lies outside the audio [0, %.2f] s: no region to re-decode' % (d.get('code'), s, duration), regs)
        regs.append([lo, hi])
    regs.sort()
    merged = []
    for lo, hi in regs:
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    total = round(sum(hi - lo for lo, hi in merged), 2)
    if len(merged) > R1_MAX_REGIONS or total > R1_MAX_TOTAL_S:
        raise Systemic('%d region(s), %.2f s in total (limits %d regions, %.0f s): the timing problem is systemic, '
                       'not local' % (len(merged), total, R1_MAX_REGIONS, R1_MAX_TOTAL_S), merged)
    return merged


# ---------------------------------------------------------------- rungs
def rung_full(ctx, prev):
    segs = decode(ctx, ctx['samples'], 0, 'R0')
    return {'rung': 'R0', 'regions': [[0.0, ctx['duration']]], 'seconds': ctx['duration']}, segs


def rung_regions(ctx, prev):
    regions = plan_regions(prev['defects'], ctx['silences'](), ctx['duration'])
    fresh = []
    for lo, hi in regions:
        a, b = int(round(lo * SAMPLE_RATE)), int(round(hi * SAMPLE_RATE))
        log('  R1 region %.2f-%.2f s (%d samples)' % (lo, hi, b - a))
        fresh += decode(ctx, ctx['samples'][a:b], lo, 'R1')
    entry = {'rung': 'R1', 'regions': regions, 'seconds': round(sum(hi - lo for lo, hi in regions), 2)}
    return entry, splice(prev['segments'], regions, fresh)


RUNGS = (('R0', rung_full), ('R1', rung_regions))     # fixed order; the first defect-free result wins


# ---------------------------------------------------------------- files
def write_atomic(path, text):
    asr_align.write_atomic(str(path), text)


def dumps(doc):
    return json.dumps(doc, ensure_ascii=False, indent=1, allow_nan=False) + '\n'


def raw_doc(header, rungs, segments):
    doc = {'schema': RAW_SCHEMA, 'version': 1, 'audio': header['audio'], 'script_sha256': header['script_sha256']}
    doc.update({k: header[k] for k in FINGERPRINT_KEYS})
    doc.update(rungs=rungs, segments=segments)
    return doc


def rung_key(name, header, prev_key):
    ident = {'rung': name, 'prev': prev_key, 'audio': header['audio'], 'fingerprint': {k: header[k] for k in FINGERPRINT_KEYS}}
    if prev_key is not None:                      # rungs after R0 depend on the script (their regions come from it)
        ident['script_sha256'] = header['script_sha256']
    return sha_text(json.dumps(ident, sort_keys=True))


def load_ckpt(out_dir, name, key):
    p = Path(out_dir) / ('asr_rung_%s.json' % name)
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        if d.get('schema') != CKPT_SCHEMA or d.get('rung') != name or d.get('key') != key:
            return None
        if not isinstance(d.get('rungs'), list) or not isinstance(d.get('segments'), list):
            return None
        return {'rungs': d['rungs'], 'segments': d['segments']}
    except (OSError, ValueError, AttributeError):
        return None


def write_ckpt(out_dir, name, key, state):
    write_atomic(Path(out_dir) / ('asr_rung_%s.json' % name),
                 dumps({'schema': CKPT_SCHEMA, 'version': 1, 'rung': name, 'key': key,
                        'rungs': state['rungs'], 'segments': state['segments']}))


def annotate(defects, pages, anchors):
    """Add `anchored` = mean share of whisper-anchored characters of the words inside each word-based defect."""
    flat = [(w['s'], w['e']) for p in pages for w in p['words']]
    for d in defects:
        if d['code'].startswith('raw-') or d['start'] is None or d['end'] is None:
            continue
        vals = [a for (s, e), a in zip(flat, anchors) if a is not None and s >= d['start'] - 1e-9 and e <= d['end'] + 1e-9]
        d['anchored'] = round(sum(vals) / len(vals), 3) if vals else None
    return defects


def write_failed(out_dir, rung, reason, regions, defects):
    gaps = [d for d in defects if d.get('code') == 'raw-gap']
    if gaps:       # the repair rung re-decoded around it and still found no words: the sound there is not speech
        reason = ('%s; %d raw-gap: > %g s of non-silent audio without words - music or effects in the presenter track are not '
                  'supported; this is not retryable' % (reason, len(gaps), timing_defects.RAW_GAP_MAX_SPEECH_S))
    write_atomic(Path(out_dir) / FAILED_NAME,
                 dumps({'schema': FAILED_SCHEMA, 'version': 1, 'rung': rung, 'reason': reason,
                        'regions': regions, 'defects': defects}))
    for d in defects:
        log(timing_defects.describe(d))
    log('WORD_TIMING FAILED at rung %s (%s): %d defect(s) the fixed repair ladder could not fix -> %s. The result is '
        'deterministic: do not retry, do not edit timing files by hand; stop and report these lines.'
        % (rung, reason, len(defects), Path(out_dir) / FAILED_NAME))


# ---------------------------------------------------------------- ladder
def run_ladder(wav, script, out_dir, transcribe_fn=None, env_info=None):
    """-> 0 (raw_asr.json written) or 5 (word_timing.failed.json written).  Raises InputError (2) / ToolError (4).
    transcribe_fn / env_info: tests pass a fake decoder and its identity; the CLI passes neither (real model, pins)."""
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        raise InputError('out dir does not exist: %s' % out_dir)
    for stale in (RAW_NAME, FAILED_NAME):          # a failed run (exit 2 / 4 / 5) must never leave the previous run's result behind
        if (out_dir / stale).is_file() or (out_dir / stale).is_symlink():
            os.unlink(out_dir / stale)
    real = transcribe_fn is None
    if real:
        env_info, problems = check_environment()
        if problems:
            raise ToolError('; '.join(problems))
        transcribe_fn = mlx_transcribe_fn(env_info['snapshot_dir'])
    elif env_info is None:
        raise ValueError('a fake transcribe_fn needs env_info (model / mlx_whisper / mlx / tokenizer / platform identity)')
    samples, wav_sha, duration = read_wav(wav)
    try:
        lines = asr_align.read_script_lines(str(script))
    except (OSError, UnicodeDecodeError) as e:
        raise InputError('cannot read script %s: %s' % (script, e))
    if not any(l.strip() for l in lines):
        raise InputError('script %s has no text' % script)
    header = dict(fingerprint(env_info), audio={'wav_sha256': wav_sha, 'duration': duration}, script_sha256=sha_file(script))
    silences = []

    def get_silences():
        if not silences:
            silences.append(detect_silences(wav))
        return silences[0]

    ctx = {'samples': samples, 'duration': duration, 'transcribe_fn': transcribe_fn, 'silences': get_silences}
    prev, prev_key, last = None, None, None
    for name, fn in RUNGS:
        key = rung_key(name, header, prev_key)
        t0 = time.monotonic()
        state = load_ckpt(out_dir, name, key)
        if state is not None:
            log('RUNG %s: resumed from %s' % (name, out_dir / ('asr_rung_%s.json' % name)))
        else:
            try:
                entry, segments = fn(ctx, prev)
            except Systemic as e:
                write_failed(out_dir, name, 'systemic: %s' % e, e.regions, prev['defects'] if prev else [])
                return 5
            state = {'rungs': (prev['rungs'] if prev else []) + [entry], 'segments': segments}
            write_ckpt(out_dir, name, key, state)
        text = dumps(raw_doc(header, state['rungs'], state['segments']))
        doc = json.loads(text)                      # align exactly what is written (JSON round trip)
        pages, anchors = asr_align.align(doc, lines)
        defects = annotate(timing_defects.find_defects(pages, doc, get_silences()), pages, anchors)
        entry = state['rungs'][-1]
        if real:                                    # everything that could run has run (model, pythainlp): was it all pinned code?
            bad = closure_problems(env_info)
            if bad:
                raise ToolError('unexpected code was loaded: ' + '; '.join(bad[:5]) + ' (the ASR venv changed: do not edit anything; '
                                'ask the lead to re-pin)')
        log('RUNG %s: %d region(s), %.2f s of audio, wall %.1f s, %d defect(s)'
            % (name, len(entry['regions']), entry['seconds'], time.monotonic() - t0, len(defects)))
        for d in defects:
            log('  ' + timing_defects.describe(d))
        if not defects:
            write_atomic(out_dir / RAW_NAME, text)
            if (out_dir / FAILED_NAME).exists():
                os.unlink(out_dir / FAILED_NAME)
            log('raw words: %s (rungs %s)' % (out_dir / RAW_NAME, ', '.join(r['rung'] for r in state['rungs'])))
            return 0
        prev = {'rungs': state['rungs'], 'segments': state['segments'], 'defects': defects}
        prev_key, last = key, (name, entry['regions'])
    write_failed(out_dir, last[0], 'exhausted', last[1], prev['defects'])
    return 5


def main(argv=None):
    ap = argparse.ArgumentParser(description='deterministic whisper pass + fixed repair ladder -> raw_asr.json')
    ap.add_argument('--wav', help='16 kHz mono 16-bit PCM wav (word_timing.sh writes vo16k.wav)')
    ap.add_argument('--script', help='plain .txt of the spoken lines, in order')
    ap.add_argument('--out-dir', help='the word_timing dir (raw_asr.json, asr_rung_*.json, word_timing.failed.json)')
    ap.add_argument('--check', action='store_true', help='only verify venv / model cache / pins (exit 0 or 4)')
    ap.add_argument('--deep', action='store_true',
                    help='with --check: also sha256 the ~3 GB weights file against its blob name (for the checker; takes ~10 s)')
    ap.add_argument('--fingerprint', action='store_true',
                    help='print the toolchain fingerprint (the identity fields of raw_asr.json) as JSON; loads no model (exit 0 or 4)')
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    if a.check and a.fingerprint:
        print('ERROR: use --check or --fingerprint, not both', file=sys.stderr)
        return 2
    if a.deep and not a.check:
        print('ERROR: --deep only goes with --check', file=sys.stderr)
        return 2
    if a.fingerprint:
        info, problems = check_environment()
        if problems:
            for p in problems:
                print('ERROR: %s' % p, file=sys.stderr)
            return 4
        print(json.dumps(fingerprint(info), ensure_ascii=False, sort_keys=True))
        return 0
    if a.check:
        info, problems = check_environment(deep=a.deep)
        for p in problems:
            print('ERROR: %s' % p, file=sys.stderr)
        if not problems:
            print('ok: %s @ %s%s, mlx-whisper %s (4 files pinned), mlx %s, pythainlp %s, %s, %s, interpreter + stdlib + venv pinned '
                  'by manifest %s (verified by asr_run.sh)'
                  % (MODEL_ID, MODEL_SNAPSHOT, ' (weights content verified)' if a.deep else '', info['mlx_whisper']['version'],
                     info['mlx']['version'], info['tokenizer']['pythainlp'], info['platform']['cpu'],
                     info['ffmpeg']['version'].split(' Copyright')[0], info['venv']['manifest_sha256'][:12]))
        return 4 if problems else 0
    if not (a.wav and a.script and a.out_dir):
        print('ERROR: --wav, --script and --out-dir are required (or --check / --fingerprint)', file=sys.stderr)
        return 2
    for p, what in ((a.wav, 'wav'), (a.script, 'script')):
        if not Path(p).is_file():
            print('ERROR: %s not found: %s' % (what, p), file=sys.stderr)
            return 2
    try:
        return run_ladder(a.wav, a.script, a.out_dir)
    except InputError as e:
        print('ERROR: %s' % e, file=sys.stderr)
        return 2
    except (ToolError, asr_align.TokenizerError) as e:
        print('ERROR: %s' % e, file=sys.stderr)
        return 4
    except asr_align.InputError as e:
        print('ERROR: %s' % e, file=sys.stderr)
        return 2


if __name__ == '__main__':
    _bad = launcher_problems()
    if _bad:
        for _p in _bad:
            print('ERROR: %s' % _p, file=sys.stderr)
        sys.exit(4)
    sys.exit(main())
