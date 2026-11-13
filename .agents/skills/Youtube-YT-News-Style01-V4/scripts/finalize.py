#!/usr/bin/env python3
"""finalize.py - the ONLY way to hand over the final video of a YT-News V4 episode.

  finalize.py --project projects/<slug> --deliver <output.mp4> [--composer remotion-composer]
              [--repo-root <git top level>] [--manifest <json>] [--check]
  finalize.py --check --project </abs/agent/projects/slug> --public-root </abs/agent/remotion-composer/public>
              [--work-dir <empty or new dir>] --deliver <output.mp4> ...          (clean-checkout check, see below)

Order of work: (1) integrity of the gate files (gates_lock, exit 3), (2) the gates are RUN fresh (long ones
first), (3) the reports of the long jobs (layout sweep, render, mux, final duration) are VERIFIED by hash binding,
(4) only if every one of them passes the final mp4 is copied to --deliver and a delivery receipt is written.  There
is deliberately NO flag and NO environment variable that skips or downgrades a gate.

PRINCIPLE (CF-A67): what finalize decides is recomputed from primary inputs (avatar, script, source video, final mp4,
clips) with the tools under the lock.  Files the agent writes (reports, receipts, markers, evidence, caches) are claims;
where finalize still has to read one (the layout sweep report, the render / mux receipts, visual_evidence.json) it binds
it by hashes it computes itself.  A delivery receipt is NOT a certification (its `certification` field says so).

CLEAN-CHECKOUT CHECK (`--check` only): an outside system runs finalize from a clean checkout of a pinned commit after
the agent's session ended.  `--public-root` names the agent's remotion-composer/public (media of the episode + fonts),
`--project` may then be an absolute path anywhere; code, lock, engine and node_modules always come from the RUNNING
checkout.  In this mode (also whenever a --check project lies outside the repository) nothing is written into the
project or the public root: fresh reports and check.json go to --work-dir (default: a new temp dir, printed at the
end) and the agent's own qc/finalize/* files are never read.  A real delivery refuses --public-root / --work-dir and
a project outside the repository (exit 2).

ONE deadline covers the whole invocation (TOTAL_BUDGET_SEC for a delivery, CHECK_TOTAL_BUDGET_SEC for --check; lock/git
checks + gates + verification + copy); when it runs out the command ends with exit 4 and a FAILED file (--check:
check.json) that names the phase.  The tools (node, ffmpeg, ffprobe, git, swift) are resolved once, from fixed candidate
lists (never $PATH), to absolute realpaths and the gates run with an environment built from scratch (gate_env).

THE OUTSIDE --check INVOCATION (exact; the docs copy this block):
  /usr/bin/env -i <PY> -I <C>/.claude/skills/Youtube-YT-News-Style01-V4/scripts/finalize.py --check \
      --project <A>/projects/<slug> --public-root <A>/remotion-composer/public --deliver <the delivered .mp4> \
      --copy-root <A>/projects [--copy-root <another projects-type dir> ...] --work-dir <empty or new dir>
  <C>  a clean checkout of the pinned commit (remotion-composer/node_modules installed); <A> the agent's checkout (read only).
  <PY> a python >= 3.12 venv interpreter with numpy, PIL, pythainlp (e.g. the repo's .venv python), run with -I and WITHOUT -S:
       finalize hands that venv's site-packages (sysconfig purelib/platlib) to every python gate, which runs `<PY> -I -S -B`.
  env -i: nothing of the caller's environment is needed or passed on.  Every child gets an environment built from scratch:
       HOME (passwd entry), PATH (the directories of the fixed tools + /usr/bin:/bin), LANG=en_US.UTF-8, TMPDIR (a private dir
       of this run).  Tools come from fixed candidate lists (TOOL_CANDIDATES), never from $PATH; check.json records each
       realpath + version and the python (executable, prefix, site dirs).
  --copy-root is MANDATORY in --check (exit 4 without it): each is a projects-type dir whose sub-directories are other episodes;
       lint_content.py compares this episode against them (+ this skill dir + <C>/remotion-composer/src).  A project whose avatar
       is the same file (sha256) is skipped as a re-do of this video: a V4 project's avatar is <root>/../remotion-composer/public/
       <assetDir>/<avatarFile> of its artifacts/episode.json, otherwise any *.mp4 in it; an unknown identity is never skipped.
  PASS = exit 0 AND check.json `certified_final_sha256` == the sha256 of the delivered file (`delivered_path`): --check binds
       the result to that file (regular file, == renders/final.mp4 the gates checked == the receipt's claim, the receipt's
       bound_inputs == the current hashes).

Exit codes (precedence): 3 integrity > 4 tool/gate missing, crash or timeout > 2 stale/missing report or bad
input > 1 quality failure; 0 delivered (or --check: everything would pass).
A relative --project is resolved against the repository root (git top level of this skill), --deliver against
the current directory.  --composer must be <repo root>/remotion-composer (anything else is exit 3).
"""
import argparse
import ast
import atexit
import concurrent.futures
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import pwd
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import wave

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / 'scripts'
LOCK_FILE = SCRIPTS_DIR / 'gates.lock.json'

COMP = 'YtNewsStyle01V4'                  # the single composition; there is no --comp
RECEIPT_SCHEMA = 'yt-news-v4-delivery-receipt'
# version 2 (CF-A67): + certification, self_reported, input_hashes, relevance {...} (replaces relevance_status).  Readers of
# older receipts (certified_pair) only use schema + delivered.sha256, which every version carries.
RECEIPT_VERSION = 2
# the inputs a receipt binds (`bound_inputs`); finalize --check requires the receipt beside the delivered file to carry exactly these
# keys with the CURRENT sha256 of each file (the delivery was made from these very inputs)
RECEIPT_BOUND_KEYS = ('episode', 'script', 'source_script', 'srt', 'words', 'line_starts', 'word_raw', 'word_pages', 'caption_options',
                      'captions', 'visual', 'final')
FAILED_SCHEMA = 'yt-news-v4-finalize-failed'
CHECK_SCHEMA = 'yt-news-v4-finalize-check'
CHECK_VERSION = 2                          # version 2: + mode / work_dir / public_root, relevance {...} (replaces relevance_status)
CERTIFICATION = ('not a certification: valid only after finalize.py --check from a clean checkout of the pinned commit passes')
RELEVANCE_NOTE = 'not used as evidence (stock/AI footage is not allowed in unattended mode)'
# One deadline for the whole invocation; unattended commands are killed after ~10 min.  The gates may only use the
# time up to TOTAL - POST_RESERVE; the rest is kept for verification + delivery.  A delivery copy is only started
# with DELIVER_RESERVE_SEC left.  Worst case wall time = budget + the 5 s kill grace of one child.
TOTAL_BUDGET_SEC = 450
# `--check` (also the clean-checkout check of the outside system) has its own constant budget; phase B adds a transcription lane
CHECK_TOTAL_BUDGET_SEC = 600
POST_RESERVE_SEC = 90
DELIVER_RESERVE_SEC = 20
GIT_TIMEOUT_SEC = 20
MAX_WORKERS = 3
STALE_TOLERANCE_NS = 2_000_000_000
RUN_LOCK_NAME = '.finalize.lock'
RUN_LOCK_STALE_SEC = 15 * 60     # only a guard against pid reuse: a lock whose pid is dead is stale at once
FRAME_TOLERANCE_SEC = 0.04       # final duration vs totalDurationSec
TOOL_NAMES = ('node', 'ffmpeg', 'ffprobe', 'git', 'swift')
REQUIRED_TOOLS = TOOL_NAMES      # all of them: swift = macOS Vision OCR of the frames gate (no OCR = no watermark/promo check)
GATE_LANG = 'en_US.UTF-8'
# python gates: `<this interpreter> -I -S -B -c GATE_BOOT <site dirs> <script> <args>`.  -I: no PYTHON* variables, no cwd / script
# dir / user site; -S: no site.py, so no .pth line and no sitecustomize of any directory runs.  GATE_BOOT puts the script's own
# directory first (its sibling modules) and appends THIS interpreter's site-packages (gate_site_dirs, sysconfig purelib/platlib of
# the venv finalize runs in) explicitly, then runs the script as __main__ with its argv.
GATE_PY_FLAGS = ('-I', '-S', '-B')
GATE_BOOT = ("import runpy,sys;a=sys.argv;sys.path[:0]=[a[2].rpartition('/')[0]];sys.path+=[p for p in a[1].split(':') if p];"
             "sys.argv=a[2:];runpy.run_path(a[2],run_name='__main__')")
# composer-relative files whose current hashes the layout manifest and the render receipt must carry (CF-A66, 5fe7699)
ENGINE_REL = 'src/YtNewsStyle01V4.tsx'
ENTRY_REL = 'src/ytNewsStyle01V4.entry.tsx'
EXPECTED_PIX_FMT = 'yuv420p'
# environment (the same checks run first in a real run and in `--preflight`)
PY_MODULES = ('numpy', 'PIL', 'pythainlp')          # the gates run under THIS interpreter (sys.executable)
# what qc_layout.mjs / render_episode.mjs load lazily from <composer>/node_modules (createRequire(<composer>/package.json)(name))
# plus `remotion` itself, imported by the engine bundle; each must be installed as <composer>/node_modules/<name>/package.json
COMPOSER_PACKAGES = ('remotion', '@remotion/bundler', '@remotion/renderer')
# the exact files YtNewsStyle01V4.tsx loads (render-blocking; a failed load cancels the render), relative to <composer>/public
FONT_FILES = ('fonts/Kanit-Bold.ttf', 'fonts/Kanit-ExtraBold.ttf')


def passwd_home():
    """The home directory of the account running finalize, from the passwd entry (never $HOME, never Path.home())."""
    return pwd.getpwuid(os.getuid()).pw_dir


# every tool from a FIXED candidate list, first executable wins; $PATH is never searched (under `env -i` there is none).  node: the
# owner's node first (<passwd home>/.local/bin/node -> ~/.local/share/node/v22.x, the one the agent session's PATH finds), then
# Homebrew / /usr/local.  ffmpeg: the word-timing chain's own list (the same binary everywhere).  The resolved realpath + version
# of each is recorded in check.json / the receipt (`tools`).
TOOL_CANDIDATES = {
    'node': (passwd_home() + '/.local/bin/node', '/opt/homebrew/bin/node', '/usr/local/bin/node'),
    'ffmpeg': ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/usr/bin/ffmpeg'),
    'ffprobe': ('/opt/homebrew/bin/ffprobe', '/usr/local/bin/ffprobe', '/usr/bin/ffprobe'),
    'git': ('/usr/bin/git', '/opt/homebrew/bin/git', '/usr/local/bin/git'),
    'swift': ('/usr/bin/swift', '/opt/homebrew/bin/swift', '/usr/local/bin/swift'),
}


# word timing (CF-A67 phases B + C): the chain word_timing.sh runs (asr_transcribe.py -> raw_asr.json, asr_align.py ->
# caption_pages.json) is re-checked from its PRIMARY inputs (the avatar audio, script.txt, the raw words); word_timing.done.json is
# never read for a verdict.  The chain's python is reached ONLY through its launcher: `/bin/bash <SCRIPTS_DIR>/asr_run.sh <script>
# ...` (asr_cmd), which verifies asr_venv.manifest (interpreter, stdlib, venv) from outside python and execs the pinned python with
# -I -S -B under env -i; finalize knows no interpreter or venv path of the chain.  timing_defects.py (stdlib only, not a launcher
# script) runs under finalize's OWN interpreter: sys.executable DEFECTS_FLAGS (-S: no site-packages, so it cannot pick up a
# third-party module).  Every child gets asr_env() (= asr_transcribe.minimal_env, built from scratch, never os.environ).
ASR_SETUP_HINT = 'run `bash %s/scripts/setup_asr_venv.sh` — a human, not the agent; do not install anything'
ASR_RUN = SCRIPTS_DIR / 'asr_run.sh'       # the launcher of the certified checkout; tests point this seam at a fake launcher FILE
SYSTEM_BASH = '/bin/bash'                  # never a bash from $PATH
DEFECTS_FLAGS = ('-I', '-S', '-B', '-X', 'pycache_prefix=/var/empty')
ASR_LANG = 'en_US.UTF-8'                   # = asr_transcribe.ENV_LANG
ASR_TMPDIR = '/var/empty'                  # = asr_transcribe.ENV_TMPDIR (the chain writes only into its --out / --out-dir)
# first executable wins, $PATH is never searched (= asr_transcribe.FFMPEG_CANDIDATES and the loop in word_timing.sh): the wav finalize
# extracts must come from the same ffmpeg binary the chain used (the fingerprint names it)
CHAIN_FFMPEG_CANDIDATES = TOOL_CANDIDATES['ffmpeg']
CHAIN_CODE_FILES = ('asr_transcribe.py', 'asr_align.py', 'timing_defects.py', 'asr_run.sh')   # = asr_transcribe.CODE_FILES (raw `code`)
# asr_transcribe.PARAMS as raw_asr.json stores it (tuples become lists); a test reads PARAMS from the script source and compares
ASR_PARAMS = {'language': 'th', 'temperature': [0.0], 'condition_on_previous_text': False, 'word_timestamps': True}
RAW_ASR_SCHEMA, RAW_ASR_VERSION = 'yt-news-v4-raw-asr', 1
WAV_RATE = 16000
# the exact extraction of word_timing.sh step 1 (word_timing.sh:69); measured on the proof avatar 2026-11-13: two extractions were
# byte-identical (20,713,516 B, 0.72 / 0.40 s), and on the four new-chain audios the result equals raw.audio.wav_sha256 and the
# chain's own vo16k.wav (0.39 .. 0.71 s each)
WAV_EXTRACT = ('-v', 'error', '-y', '-i', '{avatar}', '-vn', '-map_metadata', '-1', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le',
               '-fflags', '+bitexact', '-flags:a', '+bitexact', '{wav}')
TOOLCHAIN_MSG = 'the transcription toolchain differs from production'
CHECK_TIMEOUT_MSG = ('timeout: --check did not finish within %d s — re-run when no render / GPU job is running (this is not a content '
                     'failure)')
ASR_ENV_CHECK_LIMIT = 120                  # `asr_run.sh asr_transcribe.py --check [--deep]` (environment check, every mode)
# audio binding of the RAW words (`word-timing` gate).  Silences and the interior margins come from timing_check.py THRESHOLDS
# (silence_noise_db, silence_min_s, silenceInteriorLeadS, silenceInteriorTrailS, maxInSilenceShare; loaded from its source, never
# copied).  Rules (lead decision 2026-11-13):
#   (a) raw words >= BIND_MIN_WORD_S lying inside a silence's interior [start + lead, end - trail]: share <= maxInSilenceShare (0.5 %)
#   (b) speech gaps / overlong raw words: timing_defects.py raw rules (raw-gap, raw-word-too-long; it gets --wav), no rule here
#   (c) speech (outside the silences) before the first raw word and after the last <= BIND_EDGE_SPEECH_MAX_S
# Measured on the four new-chain audios (V261111 647 s, clip2 337 s, V261110_002 418 s, V261110_001 496 s): (a) 0 of 4133 / 2223 /
# 2528 / 3365 words = 0.000 % (the LITERAL "wholly inside a silence" gave 0.80 .. 1.86 %: every hit lay within 0.4 s of a silence
# edge); (c) before 0.00 s on all four, after 0.18 / 0.46 / 0.29 / 0.14 s.  Negatives: all raw times +1.0 s -> (a) 1.16 .. 3.28 %,
# (c) 1.00 s before; the raw of another audio -> (a) 1.03 .. 2.73 %.
BIND_MIN_WORD_S = 0.05
BIND_EDGE_SPEECH_MAX_S = 0.75
# music-presence gate (fresh, on renders/final.mp4): the mean volume of the final file just after the voice ends.
# Measured on real files, window voEnd+0.5 ... +2.5 s (ffmpeg volumedetect mean_volume): four finals WITH music -27.3, -27.6,
# -29.4, -29.5 dB; a correct mix whose window falls on the fading last 2 s of the LOOPED approved bed -56.1, -60.9, -61.8 dB (worst
# case measured; -51.5 across the loop seam); the real mux with a silent bed (voice only) -91.0 dB.  -75 locked by lead 2026-11-12.
MUSIC_PRESENCE_MIN_MEAN_DB = -75.0
MUSIC_PRESENCE_START_AFTER_VO = 0.5       # the avatar audio ends at voEndSec; start a little later, the bed is still fading out
MUSIC_PRESENCE_END_AFTER_VO = 2.5
MUSIC_PRESENCE_MIN_WINDOW = 1.0           # a shorter window measures too little
# mirrors `afade=t=out:st=${VO_END}:d=4.2` in mux_av.sh (a test reads the script and compares); END_AFTER_VO must stay <= 0.6 x this,
# so that the whole window lies in the part of the fade where the bed is still clearly audible
MUX_FADE_OUT_SECONDS = 4.2
# voEndSec is compared with the real length of the avatar audio before the window is measured: a voEndSec earlier than the real end
# of speech would make the window measure speech, not the bed.  The avatar is ctx.avatar (the file the mux receipt's avatar.sha256 is
# bound to, see verify_mux_receipt), not a path read from a receipt.
VO_END_AVATAR_TOLERANCE = 0.25
# mux_av.sh mixes the bed at this fixed volume (`VOL=0.22` in the script, a test compares); the mux receipt must carry it
MUX_BED_VOLUME = 0.22
MUX_RECEIPT_VERSION = 2                    # mux receipts carry total / vo_end / bed_volume since version 2
MUX_EPISODE_TOLERANCE = 0.01
MUSIC_PRESENCE_END_MARGIN = 0.1           # the window stops this far before the end of the file
# mux-audio (fresh gate): the AUDIO of the final is rebuilt from the avatar + the bed + episode total/voEndSec exactly as mux_av.sh
# does (mix graph below, loudnorm pass 1 -> linear pass 2, AAC 192k) and compared with the final's audio.  Measured on the proof run
# V261111_001 (2026-11-13, ffmpeg 8.1.1): two rebuilds were BYTE-IDENTICAL to the final's audio stream (decoded residual 0, the SNR
# clamp 360.8 dB); negatives: bed volume 0.30 -> 28.79 dB, 0.50 -> 18.55 dB, voice shifted +40 ms -> -2.97 dB, +500 ms -> -2.99 dB.
# 60 dB sits far above every negative; an honest mux with the same ffmpeg reproduces bit for bit (a different ffmpeg build may not:
# then the gate fails closed and names the ffmpeg version).
MUX_AUDIO_MIN_SNR_DB = 60.0
MUX_AUDIO_MAX_LENGTH_DIFF = 2048          # samples per channel (a few AAC frames); the rebuilt and the final audio must be this close
# mux_av.sh's filter graph with ${TOTAL} ${VO_END} ${VOL} as placeholders (a test reads the script and compares the text)
MUX_GRAPH = ('[0:a]apad=whole_dur=${TOTAL},asplit=2[vo][sc];[1:a]atrim=0:${TOTAL},afade=t=in:st=0:d=1.5,afade=t=out:st=${VO_END}:d=4.2,'
             'volume=${VOL}[bed];[bed][sc]sidechaincompress=threshold=0.02:ratio=5:attack=40:release=600:makeup=1[duck];'
             '[vo][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]')
MUX_LOUDNORM = 'loudnorm=I=-14:TP=-1.5:LRA=20'
# cuts (fresh gate): every clip the episode shows is bound to _cuts.json by bytes AND by picture.  Picture check, for EVERY footage
# beat at three points of the range the episode really shows (one frame early in the clip would let an agent splice other footage
# in after it and show that part with a later `from`): clip time p = from + CUT_EDGE_SEC, the middle, from + shown - CUT_EDGE_SEC,
# where shown = min(next beat t - t, the clip's usable length) and the usable length is the engine's
# L = max(1, floor((brollDur - from) * fps) - 2) frames (YtNewsStyle01V4.tsx Footage: source clips never loop, they hold the last
# frame); a range of <= 2 x CUT_EDGE_SEC is checked at its middle only.  The grey CUT_THUMB thumbnail (area-scaled) of the staged
# clip at p vs every source frame in [source_in + p + WINDOW_LO, source_in + p + WINDOW_HI]; distance = the smallest mean absolute
# difference (0..255).  The window is needed because cut_clips.sh resamples to 25 fps: the clip frame at t is the source frame 1-2
# frames (33-67 ms) earlier.  Measured on the proof run V261111_001 (VP9 1080p30 source, 2026-11-13): phase A (28 clips, one frame
# at 1.0 s) true 0.01 .. 0.23, false (source_in +/- 10 s) >= 5.15; phase B (44 footage beats x 3 points = 132 frames) true max
# 0.13 / 0.26 / 0.26 at from+0.5 / middle / end-0.5, false min 3.57 / 2.30 / 3.06 (all three lowest: yt_studio_ui, a nearly static
# screen).  1.5 sits 5.8x above the worst true and 1.5x below the closest false distance.  Wall time of the 132 checks: 10.9 s (4 threads).
CUT_EDGE_SEC = 0.5
CUT_WINDOW_LO, CUT_WINDOW_HI = -0.30, 0.20
CUT_THUMB = (64, 36)
CUT_PICTURE_MAX_DIFF = 1.5
CUT_WORKERS = 4

# =================================================================================================================
# CONTRACT with the other team's scripts (CF-A66, commit 5fe7699).  EVERY field / flag name of those scripts that
# finalize depends on lives in this section; if their code changes, change it here only.
# Verified against the real files at 5fe7699; where code and gate-spec disagreed the CODE wins (see the notes).
# =================================================================================================================
# -- qc_layout / qc_report.mjs : layout report v3 (<project>/qc/layout/report.json) -----------------------------
#    keys used: schema, version, status ("finished"), pass, complete, requestedCount, fullPlanCount, compositionId,
#    runId, manifestHash, manifestPath (RELATIVE to the layout --out dir, as qc_layout.mjs writes it), reusedFrames.
#    The V4 bundle is built from its OWN entry (src/ytNewsStyle01V4.entry.tsx), never from Root.tsx / index.tsx.
LAYOUT_REPORT_SCHEMA = 'yt-news-layout-report'
LAYOUT_REPORT_VERSION = 3
# -- qc_manifest.mjs : run manifest + manifestHash() (we call the JS function; canonical JSON is NOT re-implemented).
#    sourceHashes keys used: episode.json, captions.json, scripts/gates.lock.json, src/YtNewsStyle01V4.tsx (ENGINE_REL),
#    src/ytNewsStyle01V4.entry.tsx (ENTRY_REL) are re-hashed here in Python; in addition (CF-A67) the WHOLE sourceHashes object must
#    equal computeSourceHashes() run fresh on the running checkout (qc_manifest.mjs: import closure, assets references, scripts/qc_*,
#    the package-lock, ...), and mediaDigest / fontsDigest must equal digestDir() (media_digest.mjs) of <public>/<assetDir> and
#    <public>/fonts computed fresh WITHOUT a hash cache (qc/layout/cache/media-hash.json and every other cache are never read: a cache
#    entry is keyed by size/mtime/inode and an agent can make it lie).  The render receipt's mediaDigest / fontsDigest /
#    mediaDigestMethod must equal the same fresh digests.
RUN_MANIFEST_SCHEMA = 'yt-news-v4-run-manifest'
QC_MANIFEST_SCRIPT = 'qc_manifest.mjs'
MANIFEST_KEY_EPISODE = 'episode.json'            # keys of manifest.sourceHashes (computeSourceHashes)
MANIFEST_KEY_CAPTIONS = 'captions.json'
MANIFEST_KEY_LOCK = 'scripts/gates.lock.json'
# -- render_episode.mjs : render receipt <visual>.receipt.json (RECEIPT_FIELDS; written next to the output file as
#    `<out>.receipt.json`).  keys used: schema, schemaVersion, compositionId, draft (must be false), hasAudio (must be
#    false), outputSha256 (the visual), episodeJsonSha256, captionsJsonSha256, gatesLockSha256 (null without a lock),
#    gateManifestHash, gateRunId, renderId, width, height, fps, frameCount (checked against ffprobe of the visual),
#    engineSha256, entrySha256 and entryClosure ({"src/<file>": sha256} of the entry and every file it imports; each must
#    equal the current composer file).  rootTsxSha256 / indexTsxSha256 no longer exist.  The render reads public/ from
#    <composer>/public.  outputSha256 only binds THIS file to its receipt: two renders of the same sources are NOT
#    byte-identical, so nothing here compares or expects equal hashes across renders.
RENDER_RECEIPT_SUFFIX = '.receipt.json'
RENDER_RECEIPT_SCHEMA = 'yt-news-v4-render-receipt'
# -- episode.json (episode_schema.mjs): top level voEndSec, totalDurationSec, assetDir, avatarFile.  The media of an
#    episode live in <composer>/public/<assetDir>/ (broll/<src>.mp4, <avatarFile>): same convention as qc_layout.mjs
#    and render_episode.mjs (path.join(composer, 'public')).
# -- qc_final_pixels.mjs : `node qc_final_pixels.mjs <video.mp4> <out-dir> [--vo-end s]` (positional out-dir; the
#    gate-spec/coordinator note said --out-dir, the CODE rejects it as "unknown option"); report <out-dir>/final-pixels.json
#    with videoSha256 + certified + pass; exit 0 pass / 1 dips / 2 error.  --allow-draft is NEVER passed.
# -- episode_schema.mjs : `validate <episode> --captions <captions> --public <composer>/public --json` -> stdout
#    {valid, errors[{path,rule,message}], warnings, schemaSha256}; exit 0 valid / 1 invalid / 2 usage-IO (also a
#    --public directory that does not exist).  --public turns on the S07-file rule (every media file must exist).
# -- gate_integrity.mjs : `<composer-dir> --json --skill-dir <dir> --require-lock` -> stdout {ok, issues[{id,message}],
#    warnings, lock}, exit 0 / 3 refused / 2 usage.  Without --require-lock a missing lock is only a WARNING, so it is
#    always passed.  Its lock check needs the skill dir to sit at <repo>/.claude|.agents/skills/<skill>.  Exit 3 is an
#    INTEGRITY refusal (class 3 -> finalize exit 3).  Issue ids: engine-drift, entry-drift, entry-registration,
#    entry-closure, gates-lock*.  `<composer> --list-external` prints the repo-relative files the lock must pin (see below).
# -- gates_lock.py (ours) : the files the lock must pin under "external" are never typed by hand: gates_lock.py runs
#    `node <skill>/scripts/gate_integrity.mjs <repo>/remotion-composer --list-external` (one repo-relative path per line) in
#    write AND verify, so finalize refuses a lock that lacks one ("external-not-locked", exit 3); node / the script missing
#    ("tool-missing", exit 4) or an empty / failing list ("required-external-unavailable", exit 3) fail closed too.
# -- lint_content.py : --captions (same file as the schema gate) and --evidence / --frames-report / --source-timed (optional;
#    lint itself reports evidence-missing, window-evidence-unavailable, cue-mismatch when a source beat lacks them, so passing
#    what exists never hides an error).  --relevance is NOT passed (CF-A67): artifacts/relevance.json is evidence for nothing
#    (stock / AI footage is never allowed in unattended mode, lint_content fails every non-source footage beat:
#    stock-not-allowed); finalize only records its presence + sha256 (`relevance` in check.json / the receipt, RELEVANCE_NOTE).
# -- frame_checks.py cutaways : --media-root <public>/<assetDir>/broll (the files the render really uses); no --cache-dir (the OCR
#    program is compiled into a private temp dir on every run, never taken from a cache)
# -- face_box.py (CF-A67 W4) : `check --avatar <avatar> --episode <episode.json> --report <report>`, exit 0 pass / 1 fail / 2 usage /
#    4 tool failure or its 120 s limit; report {schema yt-news-v4-face-box, avatar_sha256, frames, verdict {pass, face_box, min_share,
#    frames_with_face, recommended, ...}}.  The `face-box` gate also requires verdict.face_box == episode.avatarFaceBox (read here)
#    and avatar_sha256 == the avatar finalize hashed itself.  "cannot measure" is never a pass (face_box exits 1 or 4).
# -- cut_manifest.py / broll_plan.cut_record : _cuts.json {"clips": {<src>: {origin, source_sha256, source_in, source_out, path,
#    sha256, duration, ...}}}; sha256 = the cut clip file, source_sha256 = the source video.  The `cuts` gate binds every footage
#    beat's staged clip (<public>/<assetDir>/broll/<src>.mp4) to it: sha256(staged) == sha256, source_sha256 == sha256(<project>/
#    assets/ytsource/source.mp4), and the picture check (CUT_* constants) proves, at three points of every footage beat's SHOWN range,
#    that the clip shows the source at source_in + clip time (source_in also steers the source-transcript window the content lint
#    reads).  episode.json `from` (default 0), `brollDur` and `fps` are read as the engine reads them.  cut_record's source_path /
#    path are never used.
# -- timing_check.py : --audio <avatar media the words were measured on> --words <words_by_line.txt> --line-starts
#    <line_starts.json> --srt <project>/assets/avatar.srt (required here: without --srt the `srt-copied` check would not
#    run); exit 0/1/2/4
# -- srt_to_script.py : `--srt S --script SRC --strict --out O`, exit 0 ok / 1 SRT text differs from the source script
# -- words_by_line.py <pages> <script> (stdout) / line_starts.py --pages P --script S --out O / caption_join.mjs
#    --tokens P --script S --options <caption-options.json> --out O : the commands of SKILL step 2, re-run by the
#    `derived` gate; their outputs must be byte-identical to the artifacts
# -- word timing chain (word_timing.sh -> asr_run.sh -> asr_transcribe.py -> asr_align.py; timing_defects.py), CF-A67 phases B/C.
#    Invocation: `/bin/bash <SCRIPTS_DIR>/asr_run.sh <asr_transcribe.py|asr_align.py> ...` (asr_cmd) under asr_env() = {HOME passwd,
#    PATH <chain ffmpeg dir>:/usr/bin:/bin, LANG en_US.UTF-8, TMPDIR /var/empty} (= asr_transcribe.minimal_env).  The launcher
#    re-execs itself under env -i, verifies asr_venv.manifest (interpreter, stdlib, venv site-packages) with root-owned tools,
#    exit 4 + the first differing file on a mismatch, then execs the pinned python -I -S -B with the manifest marker; started any
#    other way, asr_transcribe / asr_align refuse with exit 4.  It runs ONLY its CHAIN_SCRIPTS: timing_defects.py (stdlib only)
#    is run by finalize as `sys.executable -I -S -B -X pycache_prefix=/var/empty <SCRIPTS_DIR>/timing_defects.py ...` (defects_cmd).
#    * <dir>/raw_asr.json (word_raw) {schema yt-news-v4-raw-asr, version 1, audio {wav_sha256, duration = samples / 16000},
#      script_sha256 (sha256 of script.txt's bytes), params, code {asr_transcribe.py, asr_align.py, timing_defects.py, asr_run.sh},
#      <fingerprint keys>, rungs, segments [{start, end, text, compression_ratio, ..., words [{word, start, end}]}]}: no clock
#      values, same input -> same bytes.  The fingerprint is whatever `asr_transcribe.py --fingerprint` prints (an opaque nested
#      dict, compared leaf by leaf with compare_fingerprint(), a copy of asr_transcribe.compare_fingerprint that a test checks
#      against the script's source; finalize runs under the project venv and must not import asr_transcribe).  Its keys are the
#      keys of the CURRENT --fingerprint output (none hard-coded here); the recorded value of each is raw[key] (`venv` =
#      {manifest_sha256, python}: another manifest = another toolchain).
#    * `asr_transcribe.py --check` exit 0 / 4 (manifest, model cache, pins; loads nothing) = the `word-timing` environment check,
#      every mode; finalize --check adds `--deep` (sha256 of the ~3 GB weights content, ~10 s); `--fingerprint` exit 0 (JSON on
#      stdout) / 4; `--wav W --script S --out-dir D` exit 0 / 2 / 4 / 5 (ladder exhausted,
#      DEFECT lines) -- only the `asr-recheck` gate (--check) runs it, in a NEW EMPTY dir.
#    * `asr_align.py --raw R --script S --out O` exit 0 / 2 / 4: pure, byte-identical pages for the same raw + script.
#    * `timing_defects.py --pages P --raw R --wav W --report O` exit 0 none / 1 defects (report `defects` [{code, start, end,
#      token, value, limit}]) / 2 usage or unreadable input.
#    * word_timing.done.json: progress information only (in SELF_REPORTED), never read.
# -- mux_av.sh (ours) : <final>.mux.json {visual, avatar, bed, final: {path (absolute), sha256}}; the video is stream-copied
#    (-c:v copy) so the video packets of final.mp4 must equal those of visual.mp4.  The V4 render is yuv420p + bt709
#    (ENCODER in render_episode.mjs): ffprobe pix_fmt of BOTH files must be yuv420p; pix_fmt / color_space / color_range of the
#    final go into the delivery receipt
# -- frame_checks.py cutaways : needs swift/swiftc (Vision OCR); without it the command exits 4 ("OCR is never skipped
#    silently"), and finalize refuses to start without `swift` on PATH (REQUIRED_TOOLS)
# -- environment_checks() : tools, python modules, composer packages, fonts, gate lock are checked first by a real run, by
#    `--check` and by `--preflight` (same function), `word-timing` (`asr_run.sh asr_transcribe.py --check`, `--check --deep` under
#    finalize --check) included: a delivery runs asr_align.py through the launcher and --check transcribes.  ONE intentional
#    difference: `music-library` is `--preflight`-only.  finalize never runs word_timing.sh.
# -- fetch_broll.py --music : <bed>.source.json {schema "yt-news-v4-music-source", provider, track_id, track_title, url,
#    query, sha256, fetched_at}; sha256 must equal the bed file's sha256.  The music bed is checked INSIDE THE `mux` RECORD
#    (there is no separate `music` record: every failure below is reported as `mux` / status `stale` / exit 2, in its reason).
#    The bed is the file the MUX RECEIPT names (bed.path + bed.sha256, re-hashed); after resolving symlinks it must be a
#    regular file under <project>/assets/audio/ (else "music bed must be a file under <project>/assets/audio/ (got <path>)");
#    the sidecar is read beside that path.  Order of the music check:
#      1. the skill's OWN scripts/music_library.json (SCRIPTS_DIR; never a path from the sidecar / project / environment) is
#         loaded FIRST; unreadable / invalid fails the check for EVERY provider ("... scripts/music_library.json cannot be used").
#      2. list NOT empty -> only provider "music_library" is accepted: the bed's sha256 must be a track of the list and the
#         sidecar's library_file and license must equal that entry ("... is not in the approved music library ...").  A
#         "pixabay_music" sidecar is refused ("provider pixabay_music is not accepted while the approved music library has
#         tracks"), even when the bytes happen to be an approved track.  The library FILE in music_library/ is NOT needed at
#         delivery time (the bed is already in the project).
#      3. list EMPTY -> "pixabay_music" is accepted (the record above, nothing more); "music_library" fails (not in the list).
#      4. any other provider fails closed.
#    The delivery receipt `music` entry = provider, bed_sha256, track_id, track_title, url, sidecar {path, sha256} and, for the
#    library: library_file, license, origin, approved_by, approved_on, manifest_sha256 (+ sidecar_manifest_sha256).
# -- music-presence (fresh gate, in a real run and in --check, listed right after `loudness`): mean_volume of renders/final.mp4
#    (ffmpeg -ss <start> -t <len> -i final.mp4 -vn -af volumedetect -f null -) in the window voEndSec+0.5 ... min(voEndSec+2.5,
#    duration-0.1), voEndSec from artifacts/episode.json (Ctx.ep['vo_end']).  PASS when the mean is above
#    MUSIC_PRESENCE_MIN_MEAN_DB (-75.0).  It proves ONLY that there is sound after the voice ends, i.e. that a bed was muxed in at
#    all (a voice-only mux measures -91 dB).  It does NOT prove that the sound is the approved bed (the `mux` record binds that),
#    nor that music is present throughout the video.  Before measuring, voEndSec must match the audio length of the avatar
#    (ctx.avatar, the file the mux receipt's avatar.sha256 is bound to) within VO_END_AVATAR_TOLERANCE (0.25 s), else the window
#    could measure speech.  Exit classes: window < 1.0 s, no audio stream in the final, silence, voEndSec != avatar length = 1
#    (quality); ffprobe / ffmpeg failing to run, unparsable output, timeout = 4; a missing avatar file = 2 (required input, like
#    the `timing` gate).  The record carries mean_db, window [start, end], threshold_db, avatar_audio_seconds; the delivery
#    receipt carries `music_presence` {mean_db, window_start, window_end} (next to the `music` entry).
# -- mux receipt (mux_av.sh, version 2): {schema, version, visual, avatar, bed, final, total, vo_end, bed_volume, created_at}.
#    mux_av.sh takes exactly 6 arguments (the bed volume is the constant VOL=0.22 in the script).  verify_mux_receipt requires
#    version 2, bed_volume == MUX_BED_VOLUME, |vo_end - episode voEndSec| <= 0.01 and |total - episode totalDurationSec| <= 0.01;
#    a missing field (an older receipt) or a mismatch fails the `mux` record (stale, exit 2): run mux_av.sh again.
# -- mux-audio (fresh gate, CF-A67): re-runs the audio half of mux_av.sh into <reports>/mux-audio/ (MUX_GRAPH with the EPISODE's
#    totalDurationSec / voEndSec and MUX_BED_VOLUME, `-ar 48000 -c:a pcm_f32le` mix.wav, MUX_LOUDNORM pass 1 parsed with
#    parse_loudnorm (a mirror of measure_loudness.parse_loudnorm, a test compares), linear pass 2, `-c:a aac -ar 48000 -b:a 192k`) from the avatar and the bed file the mux receipt
#    names (it must be a regular file under <project>/assets/audio; its provenance is the `mux` record's job), then compares: audio
#    streamhash equal = pass, else decoded PCM SNR >= MUX_AUDIO_MIN_SNR_DB.  It proves the final's audio IS that mix (bed volume, fade,
#    voice timing); a receipt that claims 0.22 while the mix used another volume fails here.  mix.wav (~250 MB) is deleted afterwards.
# -- music-library (`--preflight` ONLY; a real run and --check do not run it): at least one track of
#    scripts/music_library.json must be usable (music_library.check_library status "ok").  The online source (Pixabay) is
#    refused at the time of writing, so the library is the one music source every run can rely on; failing at step 0 is
#    cheaper than failing at the music step an hour in.  Empty / invalid manifest or no usable file = exit 4 class.
# =================================================================================================================

# -- conventions (override ONLY via the manifest, and only the keys in OVERRIDABLE) ----------------------------
# key -> default path (relative to the project).  Required unless the key is in OPTIONAL_KEYS (missing = exit 2).
DEFAULT_PATHS = {
    'episode': 'artifacts/episode.json',
    'script': 'artifacts/script.txt',
    'source_script': 'artifacts/source_script.txt',      # required: the `script` gate rebuilds script.txt from it
    'srt': 'assets/avatar.srt',                          # required: vendor SRT (script rebuild + srt-copied check)
    'words': 'artifacts/words_by_line.txt',
    'line_starts': 'artifacts/line_starts.json',
    'word_pages': 'artifacts/word_timing/caption_pages.json',   # required, not overridable: asr_align.py output (re-derived)
    'word_raw': 'artifacts/word_timing/raw_asr.json',           # required, not overridable: asr_transcribe.py output (the raw words)
    'caption_options': 'artifacts/caption-options.json',        # required, not overridable: only endTime/lexicalOverrides
    'captions': 'artifacts/caption-joined.json',
    'cuts': 'artifacts/_cuts.json',
    'source_transcript': 'assets/ytsource/transcript.txt',  # optional
    'source_timed': 'assets/ytsource/transcript_timed.json',  # optional (lint_content treats absence as "no timed transcript")
    'evidence': 'artifacts/visual_evidence.json',            # optional (lint_content fails source beats that lack an entry)
    'chapters': 'assets/ytsource/chapters.txt',              # optional
    'relevance': 'artifacts/relevance.json',                 # optional; evidence for NOTHING: only its presence + sha256 are recorded
    'source_video': 'assets/ytsource/source.mp4',            # optional, not overridable: required by the `cuts` gate once a clip is shown
    'layout_report': 'qc/layout/report.json',
    'visual': 'renders/visual.mp4',
    'final': 'renders/final.mp4',
    'reports': 'qc/finalize',
}
OPTIONAL_KEYS = {'source_transcript', 'source_timed', 'evidence', 'chapters', 'relevance', 'source_video'}
# claims of the agent: files the agent writes (or fetches) that finalize READS but no gate re-derives (receipt `self_reported`;
# default paths, relative to the project).  visual_evidence.json: the content lint reads it as the agent's statement of what each
# source beat shows; source_script.txt + avatar.srt: the `script` / `captions` / `timing` gates build on them (script.txt is
# re-derived FROM them, they are not); transcript.txt / chapters.txt / transcript_timed.json: the content lint's source text
# (source_timed.py output, never re-run by finalize); relevance.json: presence + sha256 only (RELEVANCE_NOTE); <music bed>
# .source.json: its sha256 field is checked against the bed, its provenance (provider, track, url) is not; final-review.md:
# the agent's own review; word_timing.done.json: word_timing.sh's progress note, never read for a verdict.
SELF_REPORTED_KEYS = ('evidence', 'source_script', 'srt', 'source_transcript', 'chapters', 'source_timed', 'relevance')
SELF_REPORTED = tuple(DEFAULT_PATHS[k] for k in SELF_REPORTED_KEYS) + (
    '<music bed>.source.json', 'qc/final-review.md', 'artifacts/word_timing/word_timing.done.json')
# overridable = inputs the agent (or the fetch step) produces; gate-owned outputs, receipts and the raw timing are never
OVERRIDABLE = {'script', 'source_script', 'srt', 'words', 'line_starts', 'cuts', 'source_transcript', 'source_timed',
               'evidence', 'chapters'}
FORBIDDEN_OVERRIDES = set(DEFAULT_PATHS) - OVERRIDABLE
# derived-from-episode inputs (not path keys): avatar = <composer>/public/<assetDir>/<avatarFile>,
# broll_root = <composer>/public/<assetDir>/broll.  <dir of word_pages>/word_timing.done.json is never an input (SELF_REPORTED).

# -- gate registry (data-driven; long gates first so they start first) -----------------------------------------
# name, interp ('python'|'node'), script (file in this scripts dir), args (templates; {key} = project path,
# {report}, {reports}, {vo_end}, {composer}, {public}, {avatar}, {broll_root}, {skill}), optional_args [[flag,key]]
# (only when the file exists), inputs (required path keys, also hashed into the receipt; 'avatar' is the derived input
# above), needs (episode values that must be readable), need_dirs (ctx attributes that must be
# directories), report (template), limit (s), required, validate (extra validator name), stdout_report (finalize stores
# the tool's stdout JSON at `report`), pass_key (report key that must be True), exit_classes (extra exit code -> class),
# after [gate names] (start only when those gates have FINISHED; if one did not pass this gate is 'blocked' with the
# same exit class and does not run), dep_args [[flag, gate name]] (the report that gate wrote in THIS run),
# runner (a gate that runs several commands / compares files and writes its own report; scripts = the files it needs),
# check_only (runs in `--check` only, never in a delivery; such gates run in their own lane, see run()).
GATES = [
    dict(name='asr-recheck', runner='asr_recheck', check_only=True,
         scripts=['asr_transcribe.py', 'asr_align.py', 'timing_defects.py'], optional_args=[],
         inputs=['avatar', 'word_raw', 'word_pages', 'script'], needs=['asset_dir', 'avatar_file'],
         report='{reports}/asr-recheck.json', limit=540, required=True),
    dict(name='frames', interp='python', script='frame_checks.py',
         args=['cutaways', '--beats', '{episode}', '--cuts', '{cuts}', '--frames-dir', '{reports}/frames',
               '--report', '{report}', '--media-root', '{broll_root}'],
         optional_args=[], inputs=['episode', 'cuts'], needs=['asset_dir'], need_dirs=['broll_root'],
         report='{reports}/frames.json', limit=150, required=True),
    dict(name='final-av', interp='python', script='final_av_checks.py',
         args=['{final}', '--report', '{report}', '--ignore-from', '{vo_end}'],
         optional_args=[], inputs=['final'], needs=['vo_end'],
         report='{reports}/final-av.json', limit=120, required=True),
    dict(name='final-pixels', interp='node', script='qc_final_pixels.mjs',
         args=['{final}', '{reports}/final-pixels', '--vo-end', '{vo_end}'], optional_args=[],
         inputs=['final'], needs=['vo_end'], report='{reports}/final-pixels/final-pixels.json',
         limit=120, required=True, validate='final_pixels'),
    dict(name='mux-audio', runner='mux_audio', scripts=[], optional_args=[],
         inputs=['final', 'avatar', 'episode'], needs=['vo_end', 'total'], report='{reports}/mux-audio.json', limit=150, required=True),
    dict(name='loudness', interp='python', script='measure_loudness.py', args=['{final}', '--report', '{report}'],
         optional_args=[], inputs=['final'], needs=[], report='{reports}/final-audio.json',
         limit=60, required=True),
    dict(name='music-presence', runner='music_presence', optional_args=[], inputs=['final', 'avatar'], needs=['vo_end'],
         report='{reports}/music-presence.json', limit=30, required=True),
    dict(name='face-box', runner='face_box', scripts=['face_box.py', 'face_vision.swift'], optional_args=[],
         inputs=['episode', 'avatar'], needs=[], report='{reports}/face-box.json', limit=150, required=True),
    dict(name='cuts', runner='cuts', scripts=[], optional_args=[], inputs=['episode', 'cuts'], needs=[],
         report='{reports}/cuts.json', limit=60, required=True),
    dict(name='word-timing', runner='word_timing', scripts=['asr_transcribe.py', 'asr_align.py', 'timing_defects.py', 'timing_check.py'],
         optional_args=[], inputs=['avatar', 'word_raw', 'word_pages', 'script'], needs=['asset_dir', 'avatar_file'],
         report='{reports}/word-timing.json', limit=120, required=True),
    dict(name='timing', interp='python', script='timing_check.py',
         args=['--audio', '{avatar}', '--words', '{words}', '--line-starts', '{line_starts}', '--srt', '{srt}',
               '--report', '{report}'],
         optional_args=[], inputs=['avatar', 'words', 'line_starts', 'srt'], needs=['asset_dir', 'avatar_file'],
         report='{reports}/timing.json', limit=120, required=True),
    dict(name='schema', interp='node', script='episode_schema.mjs',
         args=['validate', '{episode}', '--captions', '{captions}', '--public', '{public}', '--json'],
         optional_args=[], inputs=['episode', 'captions'], needs=[], report='{reports}/schema.json', limit=30,
         required=True, stdout_report=True, pass_key='valid'),
    dict(name='gate-integrity', interp='node', script='gate_integrity.mjs',
         args=['{composer}', '--json', '--skill-dir', '{skill}', '--require-lock'], optional_args=[], inputs=[],
         needs=[], report='{reports}/gate-integrity.json', limit=60, required=True,
         stdout_report=True, pass_key='ok', exit_classes={3: 3}),
    dict(name='beats', interp='python', script='lint_beats.py', args=['{episode}', '--report', '{report}'],
         optional_args=[], inputs=['episode'], needs=[], report='{reports}/beats.json',
         limit=30, required=True),
    dict(name='content', interp='python', script='lint_content.py',
         args=['--beats', '{episode}', '--script', '{script}', '--words', '{words}', '--line-starts', '{line_starts}',
               '--cuts', '{cuts}', '--captions', '{captions}', '--report', '{report}'],
         optional_args=[['--source-transcript', 'source_transcript'], ['--chapters', 'chapters'],
                        ['--evidence', 'evidence'], ['--source-timed', 'source_timed']],
         inputs=['episode', 'script', 'words', 'line_starts', 'cuts', 'captions'], needs=[],
         report='{reports}/content.json', limit=60, required=True,
         after=['frames'], dep_args=[['--frames-report', 'frames']], copy_args=True, validate='copy_search'),
    dict(name='captions', interp='python', script='lint_captions.py',
         args=['--script', '{script}', '--pages', '{captions}', '--source-script', '{source_script}', '--report', '{report}'],
         optional_args=[], inputs=['script', 'captions', 'source_script'],
         needs=[], report='{reports}/captions.json', limit=60, required=True),
    dict(name='script', runner='script', scripts=['srt_to_script.py'], optional_args=[],
         inputs=['srt', 'source_script', 'script'], needs=[], report='{reports}/script.json', limit=30, required=True),
    dict(name='derived', runner='derived', scripts=['words_by_line.py', 'line_starts.py', 'caption_join.mjs'], optional_args=[],
         inputs=['word_pages', 'caption_options', 'script', 'words', 'line_starts', 'captions'],
         needs=['vo_end'], report='{reports}/derived.json', limit=90, required=True),
]

STATUS_BY_CLASS = {1: 'fail', 2: 'bad-input', 3: 'integrity', 4: 'missing'}


def active_gates(check):
    """The fresh gates of this mode: a delivery never runs a check_only gate."""
    return [g for g in GATES if check or not g.get('check_only')]
RESTORE_HINT = 'restore the skill files from git HEAD; never edit or regenerate gates.lock.json'


# ---------------------------------------------------------------- helpers
def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


class Hasher:
    """Memoised sha256 per resolved path; recheck() detects files that changed during the run."""

    def __init__(self):
        self.memo = {}

    def __call__(self, path):
        key = str(Path(path).resolve())
        if key not in self.memo:
            self.memo[key] = sha256_file(key)
        return self.memo[key]

    def recheck(self):
        changed = []
        for key, old in self.memo.items():
            try:
                new = sha256_file(key)
            except OSError:
                new = None
            if new != old:
                changed.append(key)
        return changed


def load_sibling(name):
    """Load scripts/<name>.py from source (no pycache involved)."""
    import types
    src = (SCRIPTS_DIR / (name + '.py')).read_text()
    mod = types.ModuleType(name)
    mod.__file__ = str(SCRIPTS_DIR / (name + '.py'))
    exec(compile(src, mod.__file__, 'exec'), mod.__dict__)
    return mod


def read_json(path):
    try:
        return json.loads(Path(path).read_text()), None
    except FileNotFoundError:
        return None, 'missing'
    except (OSError, ValueError) as e:
        return None, 'unreadable: %s' % e


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float('inf')


def valid_sha(v):
    return isinstance(v, str) and re.fullmatch(r'[0-9a-fA-F]{64}', v) is not None


def tail(text, n=1500):
    return text[-n:] if text else ''


def remove_quiet(p):
    try:
        os.unlink(p)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def write_json_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    os.replace(tmp, path)


def inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- child process hygiene
ACTIVE_PGIDS = set()
_ACTIVE_LOCK = threading.Lock()
STOP = threading.Event()          # set by SIGTERM/SIGINT: no child may be started afterwards


class Terminated(Exception):
    def __init__(self, message='terminated', signum=None):
        super().__init__(message)
        self.signum = signum


class BudgetExceeded(Exception):
    def __init__(self, phase, message=None):
        super().__init__(message or 'time budget exhausted during phase "%s"' % phase)
        self.phase = phase


def kill_all():
    with _ACTIVE_LOCK:
        pgids = list(ACTIVE_PGIDS)
    for pg in pgids:
        try:
            os.killpg(pg, signal.SIGKILL)      # only process groups WE started
        except OSError:
            pass


atexit.register(kill_all)


def _on_signal(signum, _frame):
    STOP.set()
    kill_all()
    raise Terminated('terminated by signal %d' % signum, signum)


class Deadline:
    """One monotonic deadline for the whole invocation."""

    def __init__(self, total):
        self.total = total
        self.end = time.monotonic() + total

    def remaining(self, reserve=0.0):
        return self.end - time.monotonic() - reserve

    def expired(self):
        return self.remaining() <= 0


# ---------------------------------------------------------------- tools (resolved once, absolute realpaths)
def resolve_tools():
    """{name: realpath | None} from TOOL_CANDIDATES (never $PATH)."""
    out = {}
    for name in TOOL_NAMES:
        found = next((c for c in TOOL_CANDIDATES[name] if os.path.isfile(c) and os.access(c, os.X_OK)), None)
        out[name] = os.path.realpath(found) if found else None
    return out


def tool_path_env(tools):
    dirs = []
    for name in TOOL_NAMES:
        if tools.get(name):
            d = os.path.dirname(tools[name])
            if d not in dirs:
                dirs.append(d)
    return ':'.join(dirs + ['/usr/bin', '/bin'])


def gate_env(tools, tmpdir):
    """The ONLY environment a gate gets: built from scratch, nothing of os.environ (NODE_OPTIONS, PYTHON*, DYLD_*, GIT_*, ...).
    tmpdir: the run's private temp dir (removed when the run ends)."""
    return {'HOME': passwd_home(), 'PATH': tool_path_env(tools), 'LANG': GATE_LANG, 'TMPDIR': str(tmpdir)}


def git_env():
    """git's environment, built from scratch (no GIT_* / config redirection of the caller)."""
    return {'HOME': passwd_home(), 'PATH': '/usr/bin:/bin', 'LANG': GATE_LANG, 'GIT_OPTIONAL_LOCKS': '0', 'GIT_NO_REPLACE_OBJECTS': '1'}


def gate_site_dirs():
    """THIS interpreter's site-packages (sysconfig purelib + platlib of sys.prefix, existing dirs, in that order): what a python gate
    appends to sys.path explicitly (it runs -S).  Valid only when finalize itself runs WITH site (under -S, sys.prefix is the base
    interpreter's, not the venv's: environment_checks refuses that)."""
    import sysconfig
    out = []
    for key in ('purelib', 'platlib'):
        p = sysconfig.get_paths().get(key)
        if p and os.path.isdir(p) and p not in out:
            out.append(p)
    return out


def python_info():
    """The interpreter the python gates run under (check.json / receipt `tools.python`)."""
    return {'path': os.path.realpath(sys.executable), 'executable': sys.executable, 'version': platform.python_version(),
            'prefix': sys.prefix, 'base_prefix': sys.base_prefix, 'no_site': bool(sys.flags.no_site),
            'gate_flags': list(GATE_PY_FLAGS), 'site_dirs': gate_site_dirs()}


def git_run(tools, repo_root, *args, deadline=None):
    timeout = GIT_TIMEOUT_SEC
    if deadline is not None:
        timeout = min(timeout, deadline.remaining())
        if timeout <= 0:
            raise subprocess.TimeoutExpired('git', 0)
    return subprocess.run([tools.get('git') or 'git', '-c', 'core.fsmonitor=false', '-C', str(repo_root), *args],
                          capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, env=git_env())


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


# ---------------------------------------------------------------- context
class BadInput(Exception):
    pass


def first_symlink(path, start=None):
    """The first component of `path` AS GIVEN (never resolved; a '..' is walked as written) that is a symbolic link (lstat), or None.
    start: an already-resolved directory `path` lies in lexically; only the components below it are examined.  A component that
    does not exist ends the walk (nothing below it can be a link)."""
    parts = Path(path).parts
    skip = len(Path(start).parts) if start is not None and parts[:len(Path(start).parts)] == Path(start).parts else 1
    cur = Path(parts[0])
    for i, part in enumerate(parts[1:], 1):
        cur = cur / part
        if i < skip:
            continue
        try:
            st = os.lstat(cur)
        except OSError:
            return None
        if stat.S_ISLNK(st.st_mode):
            return cur
    return None


def linked_reports(args, repo_root):
    """True when <project as given>/qc/finalize goes through a symbolic link (nothing may be written there)."""
    given = Path(args.project)
    lex = lexical_path(given, repo_root if not given.is_absolute() else os.getcwd()) / DEFAULT_PATHS['reports']
    return first_symlink(lex, None if given.is_absolute() else Path(repo_root)) is not None


def lexical_path(given, base):
    """`given` made absolute against `base` WITHOUT resolving or normalising it (the path a symlink check must look at)."""
    p = Path(given)
    return p if p.is_absolute() else Path(base) / p


def symlink_refusal(what, path, start=None):
    link = first_symlink(path, start)
    if link is None:
        return None
    try:
        target = os.readlink(link)
    except OSError:
        target = '?'
    return ('%s %s goes through the symbolic link %s -> %s: finalize reads only real directories and files of the project (a link '
            'could make another project count as this one); pass the real path / copy the file instead' % (what, path, link, target))


def project_dir(args, repo_root):
    p = Path(args.project)
    return (p if p.is_absolute() else Path(repo_root) / p).resolve()


def public_dir(args, repo_root):
    """The public/ the episode's media come from: --public-root (only with --check) or <repo>/<composer>/public."""
    if getattr(args, 'public_root', None):
        return Path(args.public_root).resolve()
    return (Path(repo_root) / args.composer).resolve() / 'public'


def external_check(args, repo_root):
    """True for the clean-checkout check: --check with --public-root / --work-dir, or a --check project outside the repository.
    In that mode nothing is written into the project or the public root (reports + check.json go to the work dir)."""
    if not getattr(args, 'check', False):
        return False
    if getattr(args, 'public_root', None) or getattr(args, 'work_dir', None):
        return True
    return repo_root is not None and not inside(project_dir(args, repo_root), repo_root)


class Ctx:
    def __init__(self, args, repo_root, deliver, tools=None, work_dir=None):
        """work_dir: the clean-checkout check's output directory (None = reports go to <project>/qc/finalize)."""
        self.repo_root = repo_root
        self.tools = tools or {n: None for n in TOOL_NAMES}
        # B9: no symlink anywhere in the project path as given (below the repo root for a relative one), checked BEFORE resolving
        given = Path(args.project)
        lex_project = lexical_path(given, repo_root if not given.is_absolute() else os.getcwd())
        why = symlink_refusal('--project', lex_project, None if given.is_absolute() else Path(repo_root))
        if why:
            raise BadInput(why)
        self.project = project_dir(args, repo_root)
        check = bool(getattr(args, 'check', False))
        if not check and not inside(self.project, repo_root):
            raise BadInput('--project %s is outside the repository %s: only finalize.py --check accepts a project outside the '
                           'repository (a delivery reads the media this repository rendered)' % (self.project, repo_root))
        self.comp = COMP
        self.deliver = deliver
        self.hash = Hasher()
        self.composer = (self.repo_root / args.composer).resolve()     # code, engine, node_modules: ALWAYS the running checkout
        self.work_dir = Path(work_dir).resolve() if work_dir else None
        self.budget = CHECK_TOTAL_BUDGET_SEC if check else TOTAL_BUDGET_SEC
        # projects-type roots the content lint searches for a copied episode: --check takes them from the outside system
        # (--copy-root, mandatory, checked in run() before any gate); a delivery uses the project's own parent dir (its siblings)
        self.copy_roots = ([Path(r).resolve() for r in (getattr(args, 'copy_root', None) or [])] if check else [self.project.parent])
        self.tmp = None             # the run's private temp dir: TMPDIR of every gate + finalize's capture files (set by run())
        self.manifest_sha = None
        cfg = dict(DEFAULT_PATHS)
        explicit = set()
        mp = Path(args.manifest).resolve() if args.manifest else self.project / 'artifacts' / 'finalize.json'
        why = None if args.manifest else symlink_refusal('the path manifest', mp, self.project)
        if why:
            raise BadInput(why)
        if args.manifest or mp.is_file():
            data, err = read_json(mp)
            if err or not isinstance(data, dict):
                raise BadInput('manifest %s is %s' % (mp, err or 'not a JSON object'))
            unknown = sorted(set(data) - set(DEFAULT_PATHS))
            if unknown:
                raise BadInput('manifest has unknown keys: %s' % ', '.join(unknown))
            forbidden = sorted(set(data) & FORBIDDEN_OVERRIDES)
            if forbidden:
                raise BadInput('manifest may not override: %s' % ', '.join(forbidden))
            for k, v in data.items():
                if not (isinstance(v, str) and v):
                    raise BadInput('manifest key %s has an invalid value' % k)
                if Path(v).is_absolute() or '..' in Path(v).parts:
                    raise BadInput('manifest key %s: absolute paths and ".." are not allowed (%s)' % (k, v))
                cfg[k] = v
                explicit.add(k)
            self.manifest_sha = sha256_file(mp)
        self.paths = {}
        for k, v in cfg.items():
            why = symlink_refusal('%s (%s)' % (k, v), self.project / v, self.project)
            if why:
                raise BadInput(why)
            self.paths[k] = (self.project / v).resolve()
            if not inside(self.paths[k], self.project):
                raise BadInput('%s resolves outside the project: %s' % (k, self.paths[k]))
        for k in explicit & OPTIONAL_KEYS:
            if not self.paths[k].is_file():
                raise BadInput('manifest sets optional %s but %s does not exist' % (k, self.paths[k]))
        # the agent's own qc/finalize/* is never read nor written in the clean-checkout check: its fresh reports live in the work dir
        self.reports = self.work_dir if self.work_dir else self.paths['reports']
        if self.deliver.suffix.lower() != '.mp4':
            raise BadInput('--deliver must be an .mp4 path')
        # same convention as qc_layout.mjs / render_episode.mjs (<composer>/public), or the agent's public/ given by --public-root
        pr = getattr(args, 'public_root', None)
        why = (symlink_refusal('--public-root', lexical_path(pr, os.getcwd())) if pr else
               symlink_refusal('the public root', Path(repo_root) / args.composer / 'public', Path(repo_root)))
        if why:
            raise BadInput(why)
        self.public = public_dir(args, repo_root)
        if not self.public.is_dir():
            raise BadInput('the public root %s is not a directory' % self.public)
        if self.work_dir is not None:
            for name, d in (('project', self.project), ('public root', self.public)):
                if inside(self.work_dir, d):
                    raise BadInput('--work-dir %s is inside the %s %s: the check must not write there' % (self.work_dir, name, d))
        self.ep = {'vo_end': None, 'total': None, 'asset_dir': None, 'avatar_file': None, 'error': None}
        self.avatar = None
        self.broll_root = None
        self._read_episode()
        if self.ep['asset_dir']:
            self.broll_root = self.public / self.ep['asset_dir'] / 'broll'
            if self.ep['avatar_file']:
                self.avatar = self.public / self.ep['asset_dir'] / self.ep['avatar_file']
        self.word_done = self.paths['word_pages'].parent / 'word_timing.done.json'     # never read (SELF_REPORTED)
        self.extra = {'avatar': self.avatar}
        self.word_timing = None             # set by the word-timing gate: {raw: {path, sha256}, fingerprint} for the receipt
        self._fp_lock = threading.Lock()
        self._fingerprint = None

    def _read_episode(self):
        data, err = read_json(self.paths['episode'])
        if err or not isinstance(data, dict):
            self.ep['error'] = 'episode.json is %s' % (err or 'not a JSON object')
            return
        for key, name in (('vo_end', 'voEndSec'), ('total', 'totalDurationSec')):
            v = data.get(name)
            if is_num(v) and v > 0:
                self.ep[key] = float(v)
        for key, name in (('asset_dir', 'assetDir'), ('avatar_file', 'avatarFile')):
            v = data.get(name)
            if isinstance(v, str) and v and '/' not in v and '..' not in v:
                self.ep[key] = v
        if self.ep['vo_end'] is None or self.ep['total'] is None:
            self.ep['error'] = 'episode.json has no valid voEndSec / totalDurationSec'

    def rel(self, p):
        try:
            return Path(p).resolve().relative_to(self.repo_root).as_posix()
        except ValueError:
            return str(Path(p).resolve())

    def receipt_path(self, key, suffix):
        return Path(str(self.paths[key]) + suffix)

    def input_files(self):
        files = [p for p in self.paths.values()] + [p for p in self.extra.values() if p is not None]
        files += [LOCK_FILE, Path(str(self.paths['visual']) + RENDER_RECEIPT_SUFFIX), Path(str(self.paths['final']) + '.mux.json')]
        return files

    def deliver_collision(self):
        """-> message when the deliver path is (a link to / the same file as) any input of the run."""
        target = Path(os.path.realpath(self.deliver))
        for f in self.input_files():
            try:
                same = Path(os.path.realpath(f)) == target or (os.path.exists(f) and os.path.exists(self.deliver)
                                                               and os.path.samefile(f, self.deliver))
            except OSError:
                same = False
            if same:
                return '--deliver resolves to an input file of this run: %s' % self.rel(f)
        return None


# ---------------------------------------------------------------- reports: issue summaries
ISSUE_CODE_KEYS = ('code', 'rule', 'id', 'kind')
ISSUE_TEXT_KEYS = ('detail', 'message', 'reason')
ISSUE_TIME_KEYS = ('startSec', 'start_sec', 't', 'sec', 'time', 'start', 'at')
ISSUE_COMMAND_KEYS = ('command', 'rerun', 'cmd')
ISSUE_SEVERITY_KEYS = ('severity', 'level')
SEVERITY_RANK = {'error': 0, 'fail': 0, 'critical': 0, 'unrated': 1, 'warn': 2, 'warning': 2, 'info': 3, 'note': 3}


def issue_severity(it):
    """-> the lower-case severity of an issue dict, or None."""
    if not isinstance(it, dict):
        return None
    v = next((it[k] for k in ISSUE_SEVERITY_KEYS if isinstance(it.get(k), str) and it[k]), None)
    return v.lower() if v else None


DETAIL_MAX = 300            # free-text details only; a command is never shortened
OCCURRENCES_SHOWN = 3


def _scalar(v):
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, float):
        return ('%.2f' % v).rstrip('0').rstrip('.')
    if isinstance(v, (int, str)):
        return str(v) if not isinstance(v, str) else (v if len(v) <= 60 else v[:57] + '...')
    return None


def _occurrence(it, skip):
    """One issue without detail text as a compact `@12.3s key=value ...` (scalar fields only, the time first)."""
    parts = []
    t_key = next((k for k in ISSUE_TIME_KEYS if isinstance(it.get(k), (int, float)) and not isinstance(it.get(k), bool)), None)
    if t_key:
        parts.append('@%ss' % _scalar(it[t_key]))
    for k, v in it.items():
        if k in skip or k == t_key or k in ISSUE_COMMAND_KEYS:
            continue
        sv = _scalar(v)
        if sv is not None:
            parts.append('%s=%s' % (k, sv))
    return ' '.join(parts)


def summarize_issues(data, limit=3):
    """Console lines for the issues of a report.  An issue with a detail text prints `code: detail (@where)`; issues without
    one are grouped by their code/kind and print the count plus the first few occurrences with all their scalar fields
    (time and measured values), so a bare `- dips` is never printed.  Commands inside an issue are printed in full.
    Severity (ISSUE_SEVERITY_KEYS; an item of an `errors` list without one counts as an error): every line of every list is
    ranked errors first, then unrated, then warnings / info (file order inside a rank) BEFORE the `limit` cut, and each list that
    carries severities starts with a count line per severity: a report whose first issues are warnings never hides its errors."""
    out = []
    if not isinstance(data, dict):
        return out
    heads, lines = [], []                    # lines: (rank, sequence, text)
    seq = 0
    skip = set(ISSUE_CODE_KEYS) | set(ISSUE_TEXT_KEYS)
    for key in ('issues', 'errors', 'dips', 'problems'):
        items = data.get(key)
        if not isinstance(items, list):
            continue
        sev = [issue_severity(it) or ('error' if key == 'errors' else None) for it in items]
        if any(issue_severity(it) is not None for it in items):
            counts = {}
            for s in sev:
                counts[s or 'unrated'] = counts.get(s or 'unrated', 0) + 1
            order = sorted(counts, key=lambda s: (SEVERITY_RANK.get(s, 1), s))
            heads.append('%s: %s' % (key, ', '.join('%d %s' % (counts[s], s) for s in order)))
        groups = {}                          # (rank, code) -> (first sequence, [items])
        for it, s in zip(items, sev):
            rank = SEVERITY_RANK.get(s or 'unrated', 1)
            seq += 1
            if not isinstance(it, dict):
                lines.append((rank, seq, str(it)[:DETAIL_MAX]))
                continue
            code = next((it[k] for k in ISSUE_CODE_KEYS if it.get(k)), key)
            detail = next((it[k] for k in ISSUE_TEXT_KEYS if it.get(k)), '')
            for ck in ISSUE_COMMAND_KEYS:
                if isinstance(it.get(ck), str) and it[ck]:
                    lines.append((rank, seq, 'rerun (copy this whole line): %s' % it[ck]))
            if detail:
                text = '%s: %s' % (code, str(detail)[:DETAIL_MAX])
                where = it.get('path') or it.get('beat') or it.get('t') or it.get('start')
                if where not in (None, ''):
                    text += ' (@%s)' % (where,)
                lines.append((rank, seq, text))
            else:
                groups.setdefault((rank, str(code)), (seq, []))[1].append(it)
        for (rank, code), (first, its) in groups.items():
            shown = ['[%s]' % _occurrence(it, skip) for it in its[:OCCURRENCES_SHOWN]]
            more = '' if len(its) <= OCCURRENCES_SHOWN else ' ... +%d more' % (len(its) - OCCURRENCES_SHOWN)
            lines.append((rank, first, '%s x%d, first %d: %s%s' % (code, len(its), len(shown), ' '.join(shown), more)))
    out = heads + [t for _, _, t in sorted(lines, key=lambda x: (x[0], x[1]))]
    if not out and isinstance(data.get('error'), str):
        out.append('error: ' + data['error'][:DETAIL_MAX])
    return out[:max(limit, 1)] if limit else out


# ---------------------------------------------------------------- fresh gates
def final_pixels_validator(report, ctx):
    probs = []
    if report.get('videoSha256') != ctx.hash(ctx.paths['final']):
        probs.append((2, 'final-pixels report is bound to a different video (videoSha256 mismatch)'))
    if report.get('certified') is not True:
        probs.append((1, 'final-pixels report is not certified (certified != true)'))
    return probs


VALIDATORS = {'final_pixels': final_pixels_validator,
              'copy_search': lambda data, ctx: [(1, m) for m in copy_search_problems(data, ctx)]}
GATE_BY_NAME = {g['name']: g for g in GATES}


def copy_search_problems(data, ctx):
    """The content lint's report must say where it searched for a copied episode: a `copy_search` block whose projects-type roots
    are EXACTLY the roots finalize passed (realpaths; a delivery: the project's parent, --check: every --copy-root) and that is
    complete.  -> messages (each a class-1 failure of the `content` record)."""
    cs = data.get('copy_search') if isinstance(data, dict) else None
    if not isinstance(cs, dict):
        return ['the content lint report has no copy_search block: where it looked for a copied episode is unknown, so a copy '
                'cannot be ruled out']
    out = []
    roots = cs.get('roots') if isinstance(cs.get('roots'), list) else []
    got = {r.get('path') for r in roots if isinstance(r, dict) and r.get('kind') == 'projects'}
    want = {str(r) for r in ctx.copy_roots}
    if got != want:
        out.append('the copy search did not cover exactly the projects roots finalize passed: missing %s, unexpected %s'
                   % (sorted(want - got) or 'none', sorted(got - want, key=str) or 'none'))
    if cs.get('incomplete') is not False:
        out.append('the copy search is incomplete (copy_search.incomplete = %r): the run cannot be certified until the search '
                   'completes; stop and report' % cs.get('incomplete'))
    return out


def gate_report_path(name, ctx):
    return Path(GATE_BY_NAME[name]['report'].format(reports=ctx.reports))


def input_path(ctx, key):
    return ctx.extra[key] if key in ctx.extra else ctx.paths[key]


def dependency_block(gate, deps):
    """-> (class, message) when a gate this one waits for did not pass, else None."""
    for name in gate.get('after', []):
        rec = (deps or {}).get(name)
        if rec is None:
            return 4, 'blocked: %s did not run' % name
        if rec['status'] != 'pass':
            return (rec['cls'] or 4), 'blocked: the %s gate did not pass (%s); its report is needed first' % (name, rec['status'])
    return None


def build_command(gate, ctx, deps=None):
    """Return (argv-without-interpreter, report path, input paths, problems).  deps: {gate name: finished record};
    None while only the inputs are being collected (dependent reports are added by run_gate)."""
    report = Path(gate['report'].format(reports=ctx.reports))
    ph = {k: str(v) for k, v in ctx.paths.items()}
    ph.update(report=str(report), reports=str(ctx.reports), composer=str(ctx.composer), skill=str(SKILL_DIR),
              public=str(ctx.public), avatar='' if ctx.avatar is None else str(ctx.avatar),
              broll_root='' if ctx.broll_root is None else str(ctx.broll_root),
              vo_end='' if ctx.ep['vo_end'] is None else repr(ctx.ep['vo_end']))
    problems, inputs = [], []
    for key in gate['inputs']:
        path = input_path(ctx, key)
        if path is None:
            problems.append('required input %s missing: episode.json has no assetDir/avatarFile' % key)
        elif not path.is_file():
            problems.append('required input %s missing: %s' % (key, ctx.rel(path)))
        else:
            inputs.append(path)
    for need in gate.get('needs', []):
        if ctx.ep.get(need) is None:
            problems.append('%s unavailable: %s' % (need, ctx.ep['error'] or 'not in episode.json'))
    argv = [a.format(**ph) for a in gate.get('args', [])]
    for flag, key in gate.get('optional_args', []):
        if ctx.paths[key].is_file():
            argv += [flag, str(ctx.paths[key])]
            inputs.append(ctx.paths[key])
    if gate.get('copy_args'):            # every projects-type copy root (--check: the outside system's; a delivery: the project's
        for root in ctx.copy_roots:      # parent dir) + our avatar (a project with the SAME avatar file is a re-do, not a copy)
            argv += ['--copy-root', str(root)]
        if ctx.avatar is not None and ctx.avatar.is_file():
            argv += ['--avatar', str(ctx.avatar)]
    for name in gate.get('need_dirs', []):
        d = getattr(ctx, name)
        if d is None or not d.is_dir():
            problems.append('%s is not a directory: %s' % (name, 'unknown (no assetDir)' if d is None else ctx.rel(d)))
    if deps is not None:
        for flag, name in gate.get('dep_args', []):
            dep_report = gate_report_path(name, ctx)
            if not dep_report.is_file():
                problems.append('blocked: the %s gate wrote no report at %s' % (name, ctx.rel(dep_report)))
            else:
                argv += [flag, str(dep_report)]
                inputs.append(dep_report)
    return argv, report, inputs, problems


def record(gate, status, cls, reason, report=None, code=None, seconds=0.0, inputs=None, out='', kind='fresh',
           extra=None, command=None, issues=None):
    r = {'name': gate['name'], 'kind': kind, 'required': gate.get('required', True), 'status': status,
         'cls': cls, 'exit': code, 'seconds': round(seconds, 2), 'report': report, 'reason': reason,
         'inputs': inputs or {}, 'output_tail': tail(out)}
    if command:
        r['command'] = command
    if issues:
        r['issues'] = issues
    if extra:
        r.update(extra)
    return r


def class_for_exit(gate, code):
    if code < 0:
        return 4                                   # killed by a signal: infrastructure, not quality
    mapping = {1: 1, 2: 2, 4: 4}
    mapping.update(gate.get('exit_classes', {}))
    return mapping.get(code, 4)                    # unknown exit code: infrastructure


def spawn(cmd, ctx, limit, env):
    """Run one child in its own process group (killed with its leftovers).  Nothing is started once STOP is set.
    -> dict(code, stdout bytes, stderr str, timed_out, cancelled, seconds, start_ns)"""
    res = {'code': None, 'stdout': b'', 'stderr': '', 'timed_out': False, 'cancelled': False, 'seconds': 0.0,
           'start_ns': time.time_ns()}
    if STOP.is_set():
        res['cancelled'] = True
        return res
    t0 = time.monotonic()
    tmp = getattr(ctx, 'tmp', None)
    with tempfile.TemporaryFile(dir=tmp) as fo, tempfile.TemporaryFile(dir=tmp) as fe:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe, env=env, cwd=str(ctx.repo_root),
                                start_new_session=True)
        with _ACTIVE_LOCK:
            ACTIVE_PGIDS.add(proc.pid)
        try:
            if STOP.is_set():                         # terminated between the check and the registration
                res['cancelled'] = True
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    pass
            try:
                proc.wait(timeout=limit)
            except subprocess.TimeoutExpired:
                res['timed_out'] = True
                try:
                    os.killpg(proc.pid, signal.SIGKILL)    # our own process group only
                except OSError:
                    pass
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            try:
                os.killpg(proc.pid, signal.SIGKILL)        # leftovers of a gate that exited (background children)
            except OSError:
                pass
        finally:
            with _ACTIVE_LOCK:
                ACTIVE_PGIDS.discard(proc.pid)
        fo.seek(0)
        res['stdout'] = fo.read(50_000_000)
        fe.seek(0)
        res['stderr'] = fe.read(5_000_000).decode('utf-8', 'replace')
    res['seconds'] = time.monotonic() - t0
    res['code'] = proc.returncode
    if STOP.is_set():
        res['cancelled'] = True
    return res


def gate_scripts(gate):
    return gate.get('scripts') or ([gate['script']] if gate.get('script') else [])


def interps_needed(gate):
    """The tool each gate file runs under (.py: this python, .swift: swift, anything else: node) + the tools a runner calls."""
    scripts = gate_scripts(gate)
    out = {'python' if s.endswith('.py') else 'swift' if s.endswith('.swift') else 'node' for s in scripts}
    return out | set(RUNNER_TOOLS.get(gate.get('runner'), ()))


def exe_for(ctx, script_name):
    path = str(SCRIPTS_DIR / script_name)
    if script_name.endswith('.py'):
        return [sys.executable, *GATE_PY_FLAGS, '-c', GATE_BOOT, ':'.join(gate_site_dirs()), path]
    return [ctx.tools.get('node') or 'node', path]


def step_problem(gate, base, res, label, limit):
    """A failed child of a runner gate -> record, or None when it exited 0."""
    out = (res['stdout'].decode('utf-8', 'replace')[-3000:] + ('\n' if res['stdout'] and res['stderr'] else '') + res['stderr'])
    b = dict(base, seconds=res['seconds'], out=out)
    if res['cancelled']:
        return record(gate, 'crashed', 4, 'cancelled: finalize was terminated', **dict(b, code=None))
    if res['timed_out']:
        return record(gate, 'timeout', 4, 'timeout: %s exceeded the %.0fs limit of the gate' % (label, limit), **dict(b, code=None))
    code = res['code']
    if code < 0:
        return record(gate, 'crashed', 4, '%s was killed by signal %d' % (label, -code), **dict(b, code=code))
    if code == 0:
        return None
    if code in (1, 2):
        return record(gate, STATUS_BY_CLASS[code], code, '%s exited with code %d' % (label, code), **dict(b, code=code))
    return record(gate, 'crashed', 4, '%s exited with unexpected code %d' % (label, code), **dict(b, code=code))


def finish_runner(gate, ctx, base, report, data, fail_reason, issues=None, cls=1):
    """The runner gate writes its own report (finalize is the author; the tools only wrote their outputs)."""
    write_json_atomic(report, data)
    b = dict(base)
    b['inputs'] = dict(base['inputs'])
    b['inputs'][ctx.rel(report)] = ctx.hash(report)
    if data.get('pass') is True:
        return record(gate, 'pass', 0, '', **b)
    return record(gate, STATUS_BY_CLASS[cls], cls, fail_reason, issues=issues, **b)


def runner_script(gate, ctx, base, report, limit, env):
    """srt_to_script.py --strict re-run; the result must be byte-identical to artifacts/script.txt."""
    P = ctx.paths
    out = ctx.reports / 'script.rebuilt.txt'
    remove_quiet(out)
    cmd = exe_for(ctx, 'srt_to_script.py') + ['--srt', str(P['srt']), '--script', str(P['source_script']), '--strict', '--out', str(out)]
    base['command'] = shlex.join(cmd)
    res = spawn(cmd, ctx, limit, env)
    bad = step_problem(gate, base, res, 'srt_to_script.py', limit)
    if bad:
        if res['code'] == 1 and not res['timed_out'] and not res['cancelled']:
            bad['reason'] = ('the SRT text differs from the source script (srt_to_script.py --strict exit 1): the voice-over '
                             'is not the script; fix the source or the audio, do not edit script.txt')
        return bad
    if not out.is_file():
        return record(gate, 'stale', 2, 'srt_to_script.py exited 0 but wrote no output', **base)
    equal = out.read_bytes() == P['script'].read_bytes()
    data = {'schema': 'yt-news-v4-script-rebuild', 'version': 1, 'pass': equal, 'equal': equal,
            'rebuilt': ctx.rel(out), 'rebuiltSha256': ctx.hash(out), 'script': ctx.rel(P['script']),
            'scriptSha256': ctx.hash(P['script'])}
    msg = ('%s is not what srt_to_script.py --strict rebuilds from %s + %s (see %s): regenerate it with that command, never '
           'edit it by hand' % (ctx.rel(P['script']), ctx.rel(P['srt']), ctx.rel(P['source_script']), ctx.rel(out)))
    return finish_runner(gate, ctx, dict(base, seconds=res['seconds'], code=0), report, data, msg)


def check_caption_options(ctx):
    """caption-options.json: ONLY endTime (== voEndSec within 0.01 s) and optionally lexicalOverrides (list of strings)."""
    data, err = read_json(ctx.paths['caption_options'])
    if err or not isinstance(data, dict):
        return ['caption-options.json is %s' % (err or 'not a JSON object')], {}
    p = []
    extra_keys = sorted(set(data) - {'endTime', 'lexicalOverrides'})
    if extra_keys:
        p.append('caption-options.json may only contain endTime and lexicalOverrides (found: %s)' % ', '.join(extra_keys))
    end = data.get('endTime')
    if not is_num(end):
        p.append('caption-options.json endTime is missing or not a number')
    elif ctx.ep['vo_end'] is not None and abs(end - ctx.ep['vo_end']) > 0.01 + 1e-9:
        p.append('caption-options.json endTime %s differs from episode voEndSec %s by more than 0.01 s' % (end, ctx.ep['vo_end']))
    lex = data.get('lexicalOverrides')
    if 'lexicalOverrides' in data and not (isinstance(lex, list) and all(isinstance(x, str) and x for x in lex)):
        p.append('caption-options.json lexicalOverrides must be a list of non-empty strings')
    return p, data


def runner_derived(gate, ctx, base, report, limit, env):
    """Re-run the commands of SKILL step 2 from caption_pages.json (which the `word-timing` gate re-derives from raw_asr.json);
    every artifact must be byte-identical.  word_timing.done.json is never read."""
    P = ctx.paths
    ddir = ctx.reports / 'derived'
    shutil.rmtree(ddir, ignore_errors=True)
    ddir.mkdir(parents=True, exist_ok=True)
    problems, opts = check_caption_options(ctx)
    outs = {'words': ddir / 'words_by_line.txt', 'line_starts': ddir / 'line_starts.json', 'captions': ddir / 'caption-joined.json'}
    steps = [
        ('words_by_line.py', [str(P['word_pages']), str(P['script'])], outs['words']),
        ('line_starts.py', ['--pages', str(P['word_pages']), '--script', str(P['script']), '--out', str(outs['line_starts'])], None),
        ('caption_join.mjs', ['--tokens', str(P['word_pages']), '--script', str(P['script']), '--options', str(P['caption_options']),
                              '--out', str(outs['captions'])], None),
    ]
    base['command'] = ' && '.join(shlex.join(exe_for(ctx, n) + a) for n, a, _ in steps)
    data = {'schema': 'yt-news-v4-derived-check', 'version': 2, 'pass': False, 'captionOptions': opts, 'comparisons': []}
    if problems:
        data['problems'] = problems
        return finish_runner(gate, ctx, base, report, data, '; '.join(problems), issues=problems)
    t_end = time.monotonic() + limit
    total = 0.0
    for name, args, stdout_to in steps:
        left = t_end - time.monotonic()
        if left < 1:
            return record(gate, 'timeout', 4, 'timeout: the derived gate exceeded its %.0fs limit' % limit, **dict(base, seconds=total))
        res = spawn(exe_for(ctx, name) + args, ctx, left, env)
        total += res['seconds']
        bad = step_problem(gate, base, res, name, limit)
        if bad:
            if bad['cls'] == 1:
                bad['reason'] += (' (the raw word timing %s does not produce the artifacts: regenerate them, never hand-edit)'
                                  % ctx.rel(P['word_pages']))
            return bad
        if stdout_to is not None:
            stdout_to.write_bytes(res['stdout'])
    mism = []
    for key, derived in outs.items():
        art = P[key]
        got = derived.read_bytes() if derived.is_file() else None
        equal = got is not None and got == art.read_bytes()
        data['comparisons'].append({'derived': ctx.rel(derived), 'artifact': ctx.rel(art), 'equal': equal,
                                    'derivedSha256': ctx.hash(derived) if derived.is_file() else None, 'artifactSha256': ctx.hash(art)})
        if not equal:
            mism.append('%s is not byte-identical to what the step-2 command derives from %s (%s)'
                        % (ctx.rel(art), ctx.rel(P['word_pages']), ctx.rel(derived)))
    data['pass'] = not mism
    if mism:
        data['problems'] = mism
    return finish_runner(gate, ctx, dict(base, seconds=total, code=0), report, data, '; '.join(mism), issues=mism)


_MEAN_VOLUME = re.compile(r'mean_volume:\s*(-?inf|-?\d+(?:\.\d+)?)\s*dB')


def runner_music_presence(gate, ctx, base, report, limit, env):
    """Is there sound in the final file after the voice ends?  (see the CONTRACT comment: what this does and does not prove)"""
    final, vo = ctx.paths['final'], ctx.ep['vo_end']
    ffmpeg, ffprobe = ctx.tools.get('ffmpeg'), ctx.tools.get('ffprobe')
    if not ffmpeg or not ffprobe:
        return record(gate, 'missing', 4, '%s not found on PATH' % ('ffmpeg' if not ffmpeg else 'ffprobe'), **base)
    started = time.monotonic()

    def left():
        return limit - (time.monotonic() - started)

    def fail(status, cls, reason, extra=None, out=''):
        data = {'schema': 'yt-news-v4-music-presence', 'pass': False, 'reason': reason, 'threshold_db': MUSIC_PRESENCE_MIN_MEAN_DB,
                'videoSha256': ctx.hash(final)}
        data.update(extra or {})
        return finish_music(gate, ctx, base, report, data, status, cls, reason, extra, out, time.monotonic() - started)

    probe = spawn([ffprobe, '-v', 'error', '-show_entries', 'stream=codec_type:format=duration', '-of', 'json', str(final)], ctx, max(left(), 1), env)
    if probe['cancelled'] or probe['timed_out'] or probe['code'] != 0:
        why = 'cancelled: finalize was terminated' if probe['cancelled'] else 'ffprobe timed out' if probe['timed_out'] else \
            'ffprobe could not read %s (exit %s)' % (ctx.rel(final), probe['code'])
        return fail('crashed' if probe['cancelled'] else 'timeout' if probe['timed_out'] else 'crashed', 4, why)
    try:
        info = json.loads(probe['stdout'].decode('utf-8', 'replace'))
        duration = float(info['format']['duration'])
        has_audio = any(st.get('codec_type') == 'audio' for st in info.get('streams', []))
    except (ValueError, KeyError, TypeError):
        return fail('crashed', 4, 'cannot read the duration of %s' % ctx.rel(final))
    if not has_audio:      # a mux defect (the mix is missing), not a tool failure
        return fail('fail', 1, 'the final file has no audio stream; run the mux (mux_av.sh) again')
    # voEndSec vs the real length of the avatar audio (the audio stream; the container duration when it has none)
    ap = spawn([ffprobe, '-v', 'error', '-show_entries', 'stream=codec_type,duration:format=duration', '-of', 'json', str(ctx.avatar)],
               ctx, max(left(), 1), env)
    if ap['cancelled'] or ap['timed_out']:
        return fail('crashed' if ap['cancelled'] else 'timeout', 4, 'cancelled: finalize was terminated' if ap['cancelled']
                    else 'ffprobe timed out on the avatar %s' % ctx.rel(ctx.avatar))
    try:
        if ap['code'] != 0:
            raise ValueError('ffprobe exited %s' % ap['code'])
        ainfo = json.loads(ap['stdout'].decode('utf-8', 'replace'))
        audio = [float(st['duration']) for st in ainfo.get('streams', [])
                 if st.get('codec_type') == 'audio' and str(st.get('duration', 'N/A')).replace('.', '', 1).isdigit()]
        avatar_audio = audio[0] if audio else float(ainfo['format']['duration'])
    except (ValueError, KeyError, TypeError) as e:     # ffprobe ran, the avatar is not readable media: bad input (class 2), like a missing avatar
        return fail('bad-input', 2, 'cannot read the audio length of the avatar %s: %s' % (ctx.rel(ctx.avatar), e))
    if abs(vo - avatar_audio) > VO_END_AVATAR_TOLERANCE + 1e-9:
        return fail('fail', 1, 'voEndSec %s does not match the avatar audio length %.2f s (tolerance %s s): the window after the voice cannot be '
                    'trusted; set voEndSec to the avatar\'s real length (SKILL.md step 4) and rebuild' % (vo, avatar_audio, VO_END_AVATAR_TOLERANCE),
                    {'avatar_audio_seconds': round(avatar_audio, 3)})
    start = vo + MUSIC_PRESENCE_START_AFTER_VO
    end = min(vo + MUSIC_PRESENCE_END_AFTER_VO, duration - MUSIC_PRESENCE_END_MARGIN)
    window = [round(start, 3), round(end, 3)]
    avx = {'avatar_audio_seconds': round(avatar_audio, 3)}
    if end - start < MUSIC_PRESENCE_MIN_WINDOW:
        need = MUSIC_PRESENCE_START_AFTER_VO + MUSIC_PRESENCE_MIN_WINDOW + MUSIC_PRESENCE_END_MARGIN
        return fail('fail', 1, 'only %.2f s of the final file is left after the voice ends (voEndSec %s, duration %.2f); at least %.1f s is '
                    'needed to measure that the music bed is present' % (max(duration - vo, 0.0), vo, duration, need),
                    dict(avx, window=window, duration=round(duration, 3)))
    res = spawn([ffmpeg, '-nostdin', '-hide_banner', '-ss', '%.3f' % start, '-t', '%.3f' % (end - start), '-i', str(final), '-vn',
                 '-af', 'volumedetect', '-f', 'null', '-'], ctx, max(left(), 1), env)
    out = res['stderr']
    if res['cancelled']:
        return fail('crashed', 4, 'cancelled: finalize was terminated', dict(avx, window=window), out)
    if res['timed_out']:
        return fail('timeout', 4, 'timeout: the volume measurement exceeded the %.0fs limit of the gate' % limit, dict(avx, window=window), out)
    if res['code'] != 0:
        return fail('crashed', 4, 'ffmpeg volumedetect exited with code %s' % res['code'], dict(avx, window=window), out)
    found = _MEAN_VOLUME.search(out)
    if not found:
        return fail('crashed', 4, 'cannot read mean_volume from the ffmpeg volumedetect output', dict(avx, window=window), out)
    silent = found.group(1).endswith('inf')
    mean = None if silent else float(found.group(1))
    shown = '-inf' if silent else '%.1f' % mean
    where = '%.2f\u2013%.2f s' % (start, end)
    extra = dict(avx, mean_db=mean, window=window, threshold_db=MUSIC_PRESENCE_MIN_MEAN_DB)
    if silent or mean <= MUSIC_PRESENCE_MIN_MEAN_DB:
        return fail('fail', 1, 'the final file is silent after the voice ends (mean %s dB in %s, must be above %.1f dB): the music bed is '
                    'missing from the mix; run the music step and the mux again' % (shown, where, MUSIC_PRESENCE_MIN_MEAN_DB), extra, out)
    detail = 'mean %s dB in %s (must be above %.1f dB)' % (shown, where, MUSIC_PRESENCE_MIN_MEAN_DB)
    data = {'schema': 'yt-news-v4-music-presence', 'pass': True, 'detail': detail, 'videoSha256': ctx.hash(final), **extra}
    return finish_music(gate, ctx, base, report, data, 'pass', 0, '', dict(extra, detail=detail), out, time.monotonic() - started)


def finish_music(gate, ctx, base, report, data, status, cls, reason, extra, out, seconds):
    write_json_atomic(report, data)
    b = dict(base, seconds=seconds, out=out)
    b['inputs'] = dict(base['inputs'])
    b['inputs'][ctx.rel(report)] = ctx.hash(report)
    b['command'] = 'ffmpeg -ss <voEndSec+%.1f> -t <window> -i %s -vn -af volumedetect -f null -' % (MUSIC_PRESENCE_START_AFTER_VO, ctx.rel(ctx.paths['final']))
    return record(gate, status, cls, reason, extra=extra or None, **b)


def worst_class(classes):
    """3 > 4 > 2 > 1 (the exit precedence) of a non-empty iterable of classes."""
    s = set(classes)
    return next(c for c in (3, 4, 2, 1) if c in s)


def child_out(res):
    return res['stdout'].decode('utf-8', 'replace')[-3000:] + ('\n' if res['stdout'] and res['stderr'] else '') + res['stderr']


def runner_face_box(gate, ctx, base, report, limit, env):
    """face_box.py check: the presenter's face in the avatar the episode uses must lie inside episode.avatarFaceBox.  The verdict is
    face_box.py's (measured fresh from the avatar file); finalize additionally binds the report to the avatar bytes it hashed and to
    the avatarFaceBox it read itself.  Never a pass without a fresh measurement."""
    avatar, episode = ctx.avatar, ctx.paths['episode']
    cmd = exe_for(ctx, 'face_box.py') + ['check', '--avatar', str(avatar), '--episode', str(episode), '--report', str(report)]
    base['command'] = shlex.join(cmd)
    res = spawn(cmd, ctx, limit, env)
    b = dict(base, seconds=res['seconds'], out=child_out(res), code=res['code'])
    if res['cancelled']:
        return record(gate, 'crashed', 4, 'cancelled: finalize was terminated', **dict(b, code=None))
    if res['timed_out']:
        return record(gate, 'timeout', 4, 'timeout: face_box.py exceeded the %.0fs limit of the gate' % limit, **dict(b, code=None))
    code = res['code']
    stdout = [ln for ln in res['stdout'].decode('utf-8', 'replace').splitlines() if ln.strip()]
    errline = (res['stderr'].strip().splitlines() or [''])[-1][:300]
    data = None
    if report.is_file() and report.stat().st_mtime_ns >= res['start_ns'] - STALE_TOLERANCE_NS:
        data, _err = read_json(report)
    verdict = data.get('verdict') if isinstance(data, dict) else None
    # (the verdict's own `reason` goes in as verdict_reason: the record's `reason` is finalize's sentence)
    extra = (dict({k: verdict.get(k) for k in ('min_share', 'frames_with_face', 'threshold', 'recommended')},
                  verdict_reason=verdict.get('reason')) if isinstance(verdict, dict) else None)
    if code < 0:
        return record(gate, 'crashed', 4, 'face_box.py was killed by signal %d' % -code, **b)
    if code == 4:
        return record(gate, 'missing', 4, 'face_box.py could not measure the avatar (tool failure or its time limit): %s' % errline, **b)
    if code == 2:
        return record(gate, 'bad-input', 2, 'face_box.py refused its input: %s' % errline, **b)
    if code == 1:
        why = next((ln for ln in stdout if ln.startswith('face-box FAIL')), 'face-box FAIL (exit 1)')
        return record(gate, 'fail', 1, why, issues=[ln for ln in stdout if not ln.startswith('face-box FAIL')][:6], extra=extra, **b)
    if code != 0:
        return record(gate, 'crashed', 4, 'face_box.py exited with unexpected code %d' % code, **b)
    probs = []
    if not isinstance(data, dict):
        probs.append((2, 'face_box.py exited 0 but wrote no fresh report at %s' % ctx.rel(report)))
    else:
        if data.get('schema') != 'yt-news-v4-face-box':
            probs.append((2, 'face-box report schema is %r' % data.get('schema')))
        if not (isinstance(verdict, dict) and verdict.get('pass') is True):
            probs.append((1, 'face-box report verdict.pass != true'))
        if data.get('avatar_sha256') != ctx.hash(avatar):
            probs.append((2, 'face-box report was measured on another file than the avatar %s (avatar_sha256 differs)' % ctx.rel(avatar)))
        ep_box = (read_json(episode)[0] or {}).get('avatarFaceBox')
        if not isinstance(verdict, dict) or verdict.get('face_box') != ep_box:
            probs.append((2, 'face-box report checked another box than episode.json avatarFaceBox'))
    if probs:
        cls = worst_class(c for c, _ in probs)
        return record(gate, STATUS_BY_CLASS[cls] if cls != 2 else 'stale', cls, '; '.join(m for _, m in probs), extra=extra, **b)
    b['inputs'] = dict(base['inputs'])
    b['inputs'][ctx.rel(report)] = ctx.hash(report)
    return record(gate, 'pass', 0, '', extra=extra, **b)


def footage_srcs(episode_path):
    """The src of every beat that shows a footage file (media broll / clip), in first-use order -- the same selection as
    frame_checks.py cutaways.  -> (srcs, error)"""
    data, err = read_json(episode_path)
    beats = data.get('beats') if isinstance(data, dict) else data if isinstance(data, list) else None
    if err or not isinstance(beats, list):
        return None, 'episode.json is %s' % (err or 'not an episode (no beats list)')
    out = []
    for b in beats:
        if isinstance(b, dict) and b.get('media') in ('broll', 'clip') and isinstance(b.get('src'), str) and b['src'] and b['src'] not in out:
            out.append(b['src'])
    return out, None


def gray_frames(ctx, env, path, start, duration, timeout):
    """Grey CUT_THUMB thumbnails (area-scaled) decoded by ffmpeg: ONE frame at `start` (duration None) or every frame of
    [start, start + duration].  -> (frames, error, class)"""
    w, h = CUT_THUMB
    cmd = [ctx.tools.get('ffmpeg'), '-nostdin', '-v', 'error', '-ss', '%.3f' % max(start, 0.0), '-i', str(path)]
    cmd += ['-frames:v', '1'] if duration is None else ['-t', '%.3f' % duration]
    cmd += ['-an', '-vf', 'scale=%d:%d:flags=area,format=gray' % (w, h), '-f', 'rawvideo', '-']
    res = spawn(cmd, ctx, max(min(timeout, 60), 1), env)
    if res['cancelled']:
        return None, 'cancelled: finalize was terminated', 4
    if res['timed_out']:
        return None, 'ffmpeg timed out decoding %s' % ctx.rel(path), 4
    if res['code'] != 0:
        return None, 'ffmpeg cannot decode %s at %.2f s: %s' % (ctx.rel(path), start, tail(res['stderr'], 200).strip()), 2
    n, raw = w * h, res['stdout']
    return [raw[i:i + n] for i in range(0, len(raw) - n + 1, n)], None, 0


def picture_distance(clip_frame, source_frames):
    """Smallest mean absolute grey difference (0..255) between the clip frame and any of the source frames."""
    n = len(clip_frame)
    return min(sum(abs(a - b) for a, b in zip(clip_frame, f)) / n for f in source_frames)


def shown_points(episode_path):
    """Every footage beat with the clip times the cuts gate checks: from + CUT_EDGE_SEC, the middle, from + shown - CUT_EDGE_SEC of
    the range the engine shows (Footage in YtNewsStyle01V4.tsx: trimBefore = round(from * fps), a source clip holds its last frame
    after L = max(1, floor((brollDur - from) * fps) - 2) frames; the beat lasts until the next beat's t, the last one until
    totalDurationSec).  -> ([{beat, t, src, from, shown, points}], error)"""
    data, err = read_json(episode_path)
    if err or not isinstance(data, dict) or not isinstance(data.get('beats'), list):
        return None, 'episode.json is %s' % (err or 'not an episode (no beats list)')
    beats, fps, dur, total = data['beats'], data.get('fps'), data.get('brollDur'), data.get('totalDurationSec')
    if not (is_num(fps) and fps > 0 and is_num(total)):
        return None, 'episode.json has no valid fps / totalDurationSec'
    out = []
    for i, b in enumerate(beats):
        if not (isinstance(b, dict) and b.get('media') in ('broll', 'clip') and isinstance(b.get('src'), str) and b['src']):
            continue
        src, fr = b['src'], b.get('from', 0)
        nxt = next((x.get('t') for x in beats[i + 1:] if isinstance(x, dict)), total)
        clip = dur.get(src) if isinstance(dur, dict) else None
        if not (is_num(fr) and fr >= 0 and is_num(b.get('t')) and is_num(nxt) and is_num(clip) and clip > 0):
            return None, 'beat %d (%s) has no valid t / from / next t / brollDur[%s]' % (i, src, src)
        usable = max(1, math.floor((clip - fr) * fps) - 2) / fps
        shown = min(nxt - b['t'], usable)
        if shown <= 0:
            return None, 'beat %d (%s) shows nothing (t %s, next %s)' % (i, src, b['t'], nxt)
        pts = ([fr + CUT_EDGE_SEC, fr + shown / 2, fr + shown - CUT_EDGE_SEC] if shown > 2 * CUT_EDGE_SEC else [fr + shown / 2])
        out.append({'beat': i, 't': b['t'], 'src': src, 'from': fr, 'shown': round(shown, 3), 'points': [round(p, 3) for p in pts]})
    return out, None


def runner_cuts(gate, ctx, base, report, limit, env):
    """Every clip the episode shows is bound to artifacts/_cuts.json (see the CONTRACT comment): bytes of the staged clip and of the
    project's source video, and the picture at three points of every footage beat's shown range.  Without a footage beat there is
    nothing to bind (pass, recorded)."""
    started = time.monotonic()
    P = ctx.paths
    data = {'schema': 'yt-news-v4-cuts-check', 'version': 2, 'pass': False, 'threshold': CUT_PICTURE_MAX_DIFF,
            'edgeSec': CUT_EDGE_SEC, 'window': [CUT_WINDOW_LO, CUT_WINDOW_HI], 'thumbnail': list(CUT_THUMB), 'clips': [], 'pictures': []}
    probs = []                                   # (class, message)

    def done():
        data['seconds'] = round(time.monotonic() - started, 2)
        if probs:
            data['problems'] = [m for _, m in probs]
            cls = worst_class(c for c, _ in probs)
            write_json_atomic(report, data)
            b = dict(base, seconds=data['seconds'])
            b['inputs'] = dict(base['inputs'])
            b['inputs'][ctx.rel(report)] = ctx.hash(report)
            msgs = [m for _, m in probs]
            reason = '; '.join(msgs[:4]) + (' ... (+%d more, see %s)' % (len(msgs) - 4, ctx.rel(report)) if len(msgs) > 4 else '')
            return record(gate, {1: 'fail', 2: 'stale', 4: 'missing'}.get(cls, 'fail'), cls, reason, issues=msgs[:12], **b)
        data['pass'] = True
        return finish_runner(gate, ctx, dict(base, seconds=data['seconds']), report, data, '')

    srcs, err = footage_srcs(P['episode'])
    if err:
        probs.append((2, err))
        return done()
    data['footageBeats'] = len(srcs)
    if not srcs:
        data['note'] = 'no beat shows a footage file: nothing to bind'
        return done()
    if not ctx.tools.get('ffmpeg'):
        return record(gate, 'missing', 4, 'ffmpeg not found on PATH', **base)
    cuts, err = read_json(P['cuts'])
    clips = cuts.get('clips') if isinstance(cuts, dict) else None
    if err or not isinstance(clips, dict):
        probs.append((2, '%s is %s: cut_clips.sh writes it (cut_manifest.py) for every clip it cuts'
                      % (ctx.rel(P['cuts']), err or 'not a cuts file ({"clips": {...}})')))
        return done()
    src_video = P['source_video']
    if not src_video.is_file():
        probs.append((2, 'the source video %s is missing: every shown clip must be cut from it' % ctx.rel(src_video)))
        return done()
    src_sha = ctx.hash(src_video)
    data['sourceVideo'] = {'path': ctx.rel(src_video), 'sha256': src_sha}
    again = 're-cut it with cut_clips.sh from %s and stage it again' % ctx.rel(src_video)
    jobs, bound = [], {}
    for src in srcs:
        staged = ctx.broll_root / (src + '.mp4') if ctx.broll_root is not None else None
        rec = clips.get(src)
        entry = {'src': src, 'staged': ctx.rel(staged) if staged else None}
        data['clips'].append(entry)
        if staged is None or not staged.is_file():
            probs.append((2, 'clip %s: the staged file %s is missing' % (src, entry['staged'] or '<public>/<assetDir>/broll/%s.mp4' % src)))
            continue
        entry['stagedSha256'] = ctx.hash(staged)
        if not isinstance(rec, dict):
            probs.append((2, 'clip %s has no record in %s: only clips cut from the source video may be shown; %s' % (src, ctx.rel(P['cuts']), again)))
            continue
        entry['cutSha256'], entry['sourceSha256'] = rec.get('sha256'), rec.get('source_sha256')
        if not (valid_sha(rec.get('sha256')) and rec['sha256'].lower() == entry['stagedSha256']):
            probs.append((2, 'clip %s: %s is not the file _cuts.json recorded (sha256 differs); %s' % (src, entry['staged'], again)))
        if not (valid_sha(rec.get('source_sha256')) and rec['source_sha256'].lower() == src_sha):
            probs.append((2, 'clip %s: _cuts.json says it was cut from another file than %s (source_sha256 differs); %s'
                          % (src, ctx.rel(src_video), again)))
        s_in = rec.get('source_in')
        if not (is_num(s_in) and s_in >= 0):
            probs.append((2, 'clip %s: _cuts.json has no valid source_in' % src))
            continue
        entry['sourceIn'] = s_in
        bound[src] = (entry, staged, float(s_in))
    shown, err = shown_points(P['episode'])
    if err:
        probs.append((2, err))
        return done()
    for sb in shown:
        if sb['src'] in bound:
            entry, staged, s_in = bound[sb['src']]
            for k, p in enumerate(sb['points']):
                jobs.append((entry, staged, s_in, sb, k, p))

    def picture(job):
        entry, staged, s_in, sb, k, p = job
        where = 'beat %d (t %s, from %s, shows %.2f s)' % (sb['beat'], sb['t'], sb['from'], sb['shown'])
        left = limit - (time.monotonic() - started)
        frames, e, c = gray_frames(ctx, env, staged, p, None, left)
        if e:
            return (c, 'clip %s, %s: %s' % (entry['src'], where, e)), None
        if not frames:
            return (2, 'clip %s, %s: no frame at %.2f s of %s (shorter than the shown range?)' % (entry['src'], where, p, entry['staged'])), None
        at = s_in + p
        seg, e, c = gray_frames(ctx, env, src_video, at + CUT_WINDOW_LO, CUT_WINDOW_HI - CUT_WINDOW_LO, limit - (time.monotonic() - started))
        if e:
            return (c, 'clip %s, %s: %s' % (entry['src'], where, e)), None
        if not seg:
            return (1, 'clip %s, %s: the source video has no picture at source_in + %.2f s = %.2f s: source_in %s is wrong; %s'
                    % (entry['src'], where, p, at, s_in, again)), None
        d = picture_distance(frames[0], seg)
        pic = {'src': entry['src'], 'beat': sb['beat'], 'point': k, 'clipSec': p, 'distance': round(d, 3), 'sourceFrames': len(seg),
               'sourceWindow': [round(max(at + CUT_WINDOW_LO, 0), 3), round(at + CUT_WINDOW_HI, 3)]}
        if d > CUT_PICTURE_MAX_DIFF:
            return (1, 'clip %s, %s, does not show the source video: picture distance %.2f > %.1f between %s at %.2f s and the source '
                    'around source_in %s + %.2f s = %.2f s (other footage spliced into the clip, or source_in is wrong); %s'
                    % (entry['src'], where, d, CUT_PICTURE_MAX_DIFF, entry['staged'], p, s_in, p, at, again)), pic
        return None, pic

    with concurrent.futures.ThreadPoolExecutor(max_workers=CUT_WORKERS) as ex:
        for prob, pic in ex.map(picture, jobs):
            if pic:
                data['pictures'].append(pic)
            if prob:
                probs.append(prob)
    data['pictureChecks'] = len(jobs)
    if time.monotonic() - started > limit:
        probs.append((4, 'timeout: the cuts gate exceeded its %.0fs limit' % limit))
    return done()


LOUDNORM_KEYS = ('input_i', 'input_tp', 'input_lra', 'input_thresh', 'target_offset')


def parse_loudnorm(text):
    """The loudnorm JSON of an ffmpeg stderr -> {input_i, ...} floats: the LAST complete object, exactly like
    measure_loudness.parse_loudnorm (which mux_av.sh uses to build its pass-2 filter; a test compares both on real ffmpeg output).
    Mirrored, not imported, because the `loudness` gate script must stay replaceable on its own.  Raises ValueError."""
    for raw in reversed(re.findall(r'\{[^{}]*\}', text)):
        try:
            d = json.loads(raw)
            out = {k: float(d[k]) for k in LOUDNORM_KEYS}
            if not all(math.isfinite(v) for v in out.values()):
                raise ValueError('nonfinite loudness / silent audio')
            return out
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
    raise ValueError('missing complete loudnorm JSON / no audio')


def mux_graph(total, vo_end, volume):
    return MUX_GRAPH.replace('${TOTAL}', repr(float(total))).replace('${VO_END}', repr(float(vo_end))).replace('${VOL}', repr(float(volume)))


def runner_mux_audio(gate, ctx, base, report, limit, env):
    """Rebuild the final's audio exactly as mux_av.sh does and compare (see the CONTRACT comment)."""
    started = time.monotonic()
    ffmpeg = ctx.tools.get('ffmpeg')
    final, avatar, total, vo = ctx.paths['final'], ctx.avatar, ctx.ep['total'], ctx.ep['vo_end']
    wd = ctx.reports / 'mux-audio'
    shutil.rmtree(wd, ignore_errors=True)
    wd.mkdir(parents=True, exist_ok=True)
    mix, m4a = wd / 'mix.wav', wd / 'rebuilt.m4a'
    data = {'schema': 'yt-news-v4-mux-audio', 'version': 1, 'pass': False, 'threshold_snr_db': MUX_AUDIO_MIN_SNR_DB,
            'total': total, 'vo_end': vo, 'bed_volume': MUX_BED_VOLUME, 'ffmpeg': ffmpeg, 'seconds': {}}
    b = dict(base)
    b['inputs'] = dict(base['inputs'])

    def left():
        return limit - (time.monotonic() - started)

    def end(status, cls, reason, out=''):
        for p in (mix, wd / 'rebuilt.f32', wd / 'final.f32'):
            remove_quiet(p)
        data['reason'] = reason or None
        write_json_atomic(report, data)
        bb = dict(b, seconds=time.monotonic() - started, out=out)
        bb['inputs'][ctx.rel(report)] = ctx.hash(report)
        extra = {k: data.get(k) for k in ('streamhash_equal', 'snr_db')}
        if status == 'pass':
            return record(gate, 'pass', 0, '', extra=extra, **bb)
        return record(gate, status, cls, reason, extra=extra, **bb)

    def step(label, cmd):
        if left() < 1:
            return None, ('timeout', 4, 'timeout: the mux-audio gate exceeded its %.0fs limit (at %s)' % (limit, label))
        t0 = time.monotonic()
        res = spawn(cmd, ctx, left(), env)
        data['seconds'][label] = round(time.monotonic() - t0, 2)
        if res['cancelled']:
            return None, ('crashed', 4, 'cancelled: finalize was terminated')
        if res['timed_out']:
            return None, ('timeout', 4, 'timeout: the mux-audio gate exceeded its %.0fs limit (at %s)' % (limit, label))
        if res['code'] != 0:
            return None, ('crashed', 4, 'ffmpeg (%s) exited with code %s: %s' % (label, res['code'], tail(res['stderr'], 300).strip()))
        return res, None

    # the bed: the file the mux receipt names, which must be a regular file under <project>/assets/audio (provenance: `mux` record)
    mr = ctx.receipt_path('final', '.mux.json')
    receipt, err = read_json(mr)
    bed = receipt.get('bed') if isinstance(receipt, dict) else None
    bed_path = Path(bed['path']) if isinstance(bed, dict) and isinstance(bed.get('path'), str) and bed['path'] else None
    audio_dir = ctx.project / 'assets' / 'audio'
    if err or bed_path is None:
        return end('bad-input', 2, 'cannot find the music bed: the mux receipt %s is %s' % (ctx.rel(mr), err or 'without bed.path'))
    b['inputs'][ctx.rel(mr)] = ctx.hash(mr)
    if not (bed_path.is_file() and inside(bed_path, audio_dir)):
        return end('bad-input', 2, 'the music bed %s named by the mux receipt is not a file under %s/' % (bed_path, ctx.rel(audio_dir)))
    data['bed'] = {'path': ctx.rel(bed_path), 'sha256': ctx.hash(bed_path)}
    data['avatar'] = {'path': ctx.rel(avatar), 'sha256': ctx.hash(avatar)}
    b['inputs'][ctx.rel(bed_path)] = data['bed']['sha256']
    # an input that is not readable audio is bad input (2); an ffmpeg failure after that is a tool failure (4)
    ffprobe = ctx.tools.get('ffprobe')
    for label, path in (('avatar', avatar), ('music bed', bed_path)):
        r, bad = step('probe-' + label.replace(' ', '-'), [ffprobe, '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=codec_type',
                                                          '-of', 'csv=p=0', str(path)])
        if bad and (bad[0] == 'timeout' or bad[2].startswith('cancelled')):
            return end(*bad)
        if bad or 'audio' not in r['stdout'].decode('utf-8', 'replace'):        # ffprobe ran and found no audio / could not read it
            return end('bad-input', 2, 'the %s %s has no readable audio stream' % (label, ctx.rel(path)))
    T = repr(float(total))
    _r, bad = step('mix', [ffmpeg, '-y', '-v', 'error', '-i', str(avatar), '-stream_loop', '-1', '-i', str(bed_path), '-filter_complex',
                           mux_graph(total, vo, MUX_BED_VOLUME), '-map', '[a]', '-t', T, '-ar', '48000', '-c:a', 'pcm_f32le', str(mix)])
    if bad:
        return end(*bad)
    r1, bad = step('loudnorm-pass1', [ffmpeg, '-hide_banner', '-nostats', '-i', str(mix), '-af', MUX_LOUDNORM + ':print_format=json',
                                      '-f', 'null', '-'])
    if bad:
        return end(*bad)
    try:
        d = parse_loudnorm(r1['stderr'])
    except ValueError as e:
        return end('crashed', 4, 'cannot read the loudnorm measurement of the rebuilt mix: %s' % e, r1['stderr'][-2000:])
    filt = MUX_LOUDNORM + ':linear=true:print_format=json:' + ':'.join(
        '%s=%s' % (a, d[k]) for a, k in (('measured_I', 'input_i'), ('measured_TP', 'input_tp'), ('measured_LRA', 'input_lra'),
                                         ('measured_thresh', 'input_thresh'), ('offset', 'target_offset')))
    data['filter'] = filt
    _r, bad = step('loudnorm-pass2', [ffmpeg, '-y', '-hide_banner', '-nostats', '-i', str(mix), '-af', filt, '-map', '0:a:0', '-t', T,
                                      '-c:a', 'aac', '-ar', '48000', '-b:a', '192k', '-vn', str(m4a)])
    if bad:
        return end(*bad)
    remove_quiet(mix)
    hashes = {}
    for label, path in (('rebuilt', m4a), ('final', final)):
        r, bad = step('streamhash-' + label, [ffmpeg, '-nostdin', '-v', 'error', '-i', str(path), '-map', '0:a:0', '-c', 'copy', '-f',
                                              'streamhash', '-hash', 'sha256', '-'])
        if bad:
            if label == 'final':
                return end('fail', 1, 'the final file %s has no readable audio stream; run the mux (mux_av.sh) again' % ctx.rel(final))
            return end(*bad)
        lines = [x.strip() for x in r['stdout'].decode('utf-8', 'replace').splitlines() if ',a,SHA256=' in x]
        hashes[label] = lines[0] if len(lines) == 1 else None
    data['rebuiltStreamhash'], data['finalStreamhash'] = hashes['rebuilt'], hashes['final']
    data['streamhash_equal'] = hashes['rebuilt'] is not None and hashes['rebuilt'] == hashes['final']
    if data['streamhash_equal']:
        data['snr_db'] = None                   # bit-identical: nothing to measure
        data['pass'] = True
        return end('pass', 0, '')
    # not bit-identical: decode both (files: the 50 MB stdout cap of spawn) and measure the residual
    pcm = {}
    for label, path in (('rebuilt', m4a), ('final', final)):
        out = wd / (label + '.f32')
        _r, bad = step('decode-' + label, [ffmpeg, '-nostdin', '-y', '-v', 'error', '-i', str(path), '-map', '0:a:0', '-ac', '2', '-ar', '48000',
                                           '-f', 'f32le', str(out)])
        if bad:
            return end(*bad)
        pcm[label] = out
    try:
        import numpy as np
        x = np.fromfile(str(pcm['rebuilt']), dtype='<f4')
        y = np.fromfile(str(pcm['final']), dtype='<f4')
    except Exception as e:  # noqa: BLE001
        return end('missing', 4, 'cannot compare the decoded audio (numpy): %s' % e)
    data['samples'] = {'rebuilt': int(len(x) // 2), 'final': int(len(y) // 2)}
    if abs(len(x) - len(y)) // 2 > MUX_AUDIO_MAX_LENGTH_DIFF:
        return end('fail', 1, 'the audio of %s is %.3f s long but the mux of the avatar + bed for totalDurationSec %s is %.3f s: the final '
                   'was not muxed from these inputs; run mux_av.sh again' % (ctx.rel(final), len(y) / 2 / 48000, total, len(x) / 2 / 48000))
    n = min(len(x), len(y))
    sig = res_e = 0.0
    for i in range(0, n, 1 << 22):
        j = min(i + (1 << 22), n)                    # both bounded by the shorter stream (the length check above allows a few samples)
        a, c = x[i:j].astype(np.float64), y[i:j].astype(np.float64)
        sig += float((c * c).sum())
        res_e += float(((c - a) ** 2).sum())
    snr = 10 * math.log10(max(sig, 1e-30) / max(res_e, 1e-30))
    data['snr_db'] = round(snr, 2)
    if snr < MUX_AUDIO_MIN_SNR_DB:
        return end('fail', 1, 'the audio of %s is not what mux_av.sh makes from the avatar + the bed %s + the episode\'s totalDurationSec %s / '
                   'voEndSec %s at bed volume %s (residual SNR %.1f dB, needs >= %.0f; an identical mux is bit-exact with the same ffmpeg %s): '
                   'run mux_av.sh again with exactly these inputs' % (ctx.rel(final), data['bed']['path'], total, vo, MUX_BED_VOLUME, snr,
                                                                       MUX_AUDIO_MIN_SNR_DB, ffmpeg))
    data['pass'] = True
    return end('pass', 0, '')


# ---------------------------------------------------------------- word timing (CF-A67 phase B, see the CONTRACT comment)
def chain_ffmpeg():
    return next((c for c in CHAIN_FFMPEG_CANDIDATES if os.path.isfile(c) and os.access(c, os.X_OK)), None)


def asr_env():
    """The ONLY environment a chain call, the wav extraction and timing_defects.py get: built from scratch, never from os.environ
    (= asr_transcribe.minimal_env; a test compares the two), so nothing of the caller (BASH_ENV, DYLD_*, HF_*, PYTHON*, ...) reaches
    /bin/bash, the launcher, the decoder or its libraries."""
    ff = chain_ffmpeg()
    return {'HOME': passwd_home(), 'PATH': (os.path.dirname(ff) + ':' if ff else '') + '/usr/bin:/bin', 'LANG': ASR_LANG,
            'TMPDIR': ASR_TMPDIR}


def asr_cmd(script, *args):
    """The ONE way finalize reaches the chain's python (--check [--deep], --fingerprint, asr_align, the re-transcription):
    /bin/bash <certified checkout>/scripts/asr_run.sh <script> <args>.  The script is named, not pathed: the launcher runs only its
    own CHAIN_SCRIPTS next to itself."""
    return [SYSTEM_BASH, str(ASR_RUN), script, *[str(a) for a in args]]


def defects_cmd(*args):
    """timing_defects.py of the certified checkout under finalize's own interpreter, no site-packages (stdlib only)."""
    return [sys.executable, *DEFECTS_FLAGS, str(SCRIPTS_DIR / 'timing_defects.py'), *[str(a) for a in args]]


def launcher_problem():
    """None, or why the launcher cannot even be started (the launcher's own checks -- venv, manifest, interpreter -- run when it
    is called and come back as its exit 4 + stderr)."""
    if not Path(ASR_RUN).is_file():
        return 'the ASR launcher %s is missing — %s' % (ASR_RUN, ASR_SETUP_HINT % SKILL_DIR)
    return None


def launcher_failure(what, res):
    """A chain call that exited non-zero: its exit code + the tail of its stderr (the launcher names the first differing manifest
    file, a missing venv, ...), plus the setup hint for a launcher refusal (exit 4) that does not carry one."""
    err = tail(res['stderr'].strip(), 500) or 'no message'
    msg = '%s exited %s: %s' % (what, res['code'], err)
    if res['code'] == 4 and 'setup_asr_venv.sh' not in err:
        msg += ' — %s' % (ASR_SETUP_HINT % SKILL_DIR)
    return msg


_FP_MISSING = object()


def _fp_show(v):
    if v is _FP_MISSING:
        return '<missing>'
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, sort_keys=True)


OS_UPDATE_HINT = ('hint: the OS was updated after this word timing was made — redo the word timing step and deliver again')


def compare_fingerprint(recorded, current):
    """A copy of asr_transcribe.compare_fingerprint (finalize must not import that module; a test runs both on the same inputs):
    one line per differing leaf, 'path: <recorded> (production) != <current> (this machine)'; a key on one side only differs.  When
    platform.release / platform.mac_ver differ, ONE more last line (OS_UPDATE_HINT) says to redo the word timing and deliver again."""
    out = []

    def walk(path, a, b):
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(set(a) | set(b), key=str):
                walk('%s.%s' % (path, k) if path else str(k), a.get(k, _FP_MISSING), b.get(k, _FP_MISSING))
        elif isinstance(a, list) and isinstance(b, list):
            for i in range(max(len(a), len(b))):
                walk('%s[%d]' % (path, i), a[i] if i < len(a) else _FP_MISSING, b[i] if i < len(b) else _FP_MISSING)
        elif a is _FP_MISSING or b is _FP_MISSING or type(a) is not type(b) or a != b:
            out.append('%s: %s (production) != %s (this machine)' % (path or 'fingerprint', _fp_show(a), _fp_show(b)))
    walk('', recorded, current)
    if any(l.startswith(('platform.release:', 'platform.mac_ver:')) for l in out):
        out.append(OS_UPDATE_HINT)                       # one extra line; the failure condition is unchanged (the leaves above already differ)
    return out


def machine_fingerprint(ctx, limit):
    """`asr_run.sh asr_transcribe.py --fingerprint` of THIS machine, run once per finalize run (both word-timing gates need it).
    -> (dict | None, error, class)"""
    with ctx._fp_lock:
        if ctx._fingerprint is None:
            ctx._fingerprint = _run_fingerprint(ctx, limit)
        return ctx._fingerprint


def _run_fingerprint(ctx, limit):
    bad = launcher_problem()
    if bad:
        return None, bad, 4
    res = spawn(asr_cmd('asr_transcribe.py', '--fingerprint'), ctx, limit, asr_env())
    if res['cancelled']:
        return None, 'cancelled: finalize was terminated', 4
    if res['timed_out']:
        return None, 'asr_transcribe.py --fingerprint exceeded %.0f s' % limit, 4
    if res['code'] != 0:
        return None, launcher_failure('asr_run.sh asr_transcribe.py --fingerprint', res), 4
    try:
        fp = json.loads(res['stdout'].decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        fp = None
    if not (isinstance(fp, dict) and fp):
        return None, 'asr_transcribe.py --fingerprint printed no fingerprint object', 4
    return fp, None, 0


def fingerprint_problem(ctx, raw, limit):
    """B2.4 precondition: the toolchain recorded in raw_asr.json == this machine's.  -> (recorded, problem | None, class)"""
    current, err, cls = machine_fingerprint(ctx, limit)
    if err:
        return None, 'cannot read the transcription toolchain of this machine: %s' % err, cls
    recorded = {k: raw.get(k, _FP_MISSING) for k in current}
    diff = compare_fingerprint(recorded, current)
    shown = {k: v for k, v in recorded.items() if v is not _FP_MISSING}
    if diff:
        leaves = [l for l in diff if l != OS_UPDATE_HINT]       # the hint is not a difference: it is shown after them, never cut off
        msg = '%s: %s' % (TOOLCHAIN_MSG, '; '.join(leaves[:6]) + (' ... (+%d more)' % (len(leaves) - 6) if len(leaves) > 6 else ''))
        return shown, msg + (' | %s' % OS_UPDATE_HINT if OS_UPDATE_HINT in diff else ''), 4
    return shown, None, 0


def extract_wav(ctx, wav, limit):
    """word_timing.sh step 1 with the chain's ffmpeg, from the avatar the episode uses (the agent's vo16k.wav is never read).
    -> (info {sha256, duration, bytes, seconds} | None, error, class)"""
    ff = chain_ffmpeg()
    if ff is None:
        return None, 'no ffmpeg at %s (the word-timing chain never searches $PATH)' % ', '.join(CHAIN_FFMPEG_CANDIDATES), 4
    res = spawn([ff] + [a.format(avatar=ctx.avatar, wav=wav) for a in WAV_EXTRACT], ctx, limit, asr_env())
    if res['cancelled']:
        return None, 'cancelled: finalize was terminated', 4
    if res['timed_out']:
        return None, 'the wav extraction exceeded %.0f s' % limit, 4
    if res['code'] != 0 or not wav.is_file():
        return None, 'ffmpeg could not extract the audio of %s: %s' % (ctx.rel(ctx.avatar), tail(res['stderr'].strip(), 300)), 2
    try:
        with wave.open(str(wav), 'rb') as w:
            ok = (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, WAV_RATE)
            frames = w.getnframes()
    except (OSError, EOFError, wave.Error) as e:
        return None, 'the extracted wav cannot be read: %s' % e, 4
    if not ok or frames == 0:
        return None, 'the extracted wav is not 16 kHz mono 16-bit PCM with samples', 4
    return {'sha256': sha256_file(wav), 'duration': frames / WAV_RATE, 'bytes': wav.stat().st_size,
            'seconds': round(res['seconds'], 2)}, None, 0


_TC_THRESHOLDS = []


def timing_check_thresholds():
    """silencedetect + interior-margin values from timing_check.py THRESHOLDS (the dict literal, read with ast.literal_eval from its
    source: never executed, never a second copy of the numbers)."""
    if not _TC_THRESHOLDS:
        tree = ast.parse((SCRIPTS_DIR / 'timing_check.py').read_text(encoding='utf-8'))
        node = next(n.value for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1
                    and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'THRESHOLDS')
        th = ast.literal_eval(node)
        _TC_THRESHOLDS.append({k: th[k] for k in ('silence_noise_db', 'silence_min_s', 'silenceInteriorLeadS', 'silenceInteriorTrailS',
                                                  'maxInSilenceShare')})
    return _TC_THRESHOLDS[0]


_TIMING_DEFECTS = []


def detect_silences(wav):
    """[(start, end)] of ffmpeg silencedetect by the chain's OWN parser, timing_defects.detect_silences (loaded from the certified
    checkout's source): a silence the audio ends in (no silence_end) is closed at the Duration ffmpeg prints, so a quiet tail is
    never counted as speech.  Same ffmpeg (chain_ffmpeg) and environment (asr_env) as the chain.  -> (silences | None, error, class)"""
    if STOP.is_set():
        return None, 'cancelled: finalize was terminated', 4
    try:
        if not _TIMING_DEFECTS:
            _TIMING_DEFECTS.append(load_sibling('timing_defects'))
        return [tuple(x) for x in _TIMING_DEFECTS[0].detect_silences(wav, ffmpeg=chain_ffmpeg(), env=asr_env())], None, 0
    except Exception as e:  # noqa: BLE001 - RuntimeError of the parser, a broken source: never a verdict
        return None, 'ffmpeg silencedetect failed on the extracted wav: %s' % (str(e) or type(e).__name__)[-300:], 4


def raw_words(raw):
    """[(start, end, word)] of every raw word in file order; None when a segment / word is malformed."""
    out = []
    segs = raw.get('segments')
    if not isinstance(segs, list):
        return None
    for s in segs:
        ws = s.get('words') if isinstance(s, dict) else None
        if not isinstance(ws, list):
            return None
        for w in ws:
            if not (isinstance(w, dict) and is_num(w.get('start')) and is_num(w.get('end'))
                    and math.isfinite(w['start']) and math.isfinite(w['end'])):
                return None
            out.append((float(w['start']), float(w['end']), w.get('word')))
    return out


def speech_spans(silences, duration):
    out, t = [], 0.0
    for a, b in sorted(silences):
        if a > t:
            out.append((t, a))
        t = max(t, b)
    if duration > t:
        out.append((t, duration))
    return out


def audio_binding(words, silences, duration, th):
    """Rules (a) and (c) of BIND_* on the RAW words vs the silences of the audio.  -> (metrics, problems)"""
    lead, trail, share_max = th['silenceInteriorLeadS'], th['silenceInteriorTrailS'], th['maxInSilenceShare']
    interiors = [(a + lead, b - trail) for a, b in silences if b - trail >= a + lead]
    elig = [w for w in words if w[1] - w[0] >= BIND_MIN_WORD_S]
    inside = [w for w in elig if any(lo <= w[0] and w[1] <= hi for lo, hi in interiors)]
    share = len(inside) / len(elig) if elig else 0.0
    speech = speech_spans(silences, duration)

    def speech_in(lo, hi):
        return sum(max(0.0, min(hi, b) - max(lo, a)) for a, b in speech)
    pre = speech_in(0.0, min(w[0] for w in words)) if words else duration
    post = speech_in(max(w[1] for w in words), duration) if words else duration
    m = {'silences': len(silences), 'eligibleWords': len(elig), 'wordsInSilence': len(inside), 'inSilenceShare': round(share, 5),
         'inSilenceShareMax': share_max, 'interior': [lead, trail], 'speechBeforeFirstWord': round(pre, 3),
         'speechAfterLastWord': round(post, 3), 'edgeSpeechMax': BIND_EDGE_SPEECH_MAX_S}
    p = []
    if not words:
        p.append('raw_asr.json has no word with a time: nothing binds it to the audio')
    if share > share_max:
        s, e, t = inside[0]
        p.append('%d of %d raw words (%.2f %%, limit %.1f %%) lie inside silences of the audio (first: %r %.2f-%.2f s): the words '
                 'are not where this audio has speech' % (len(inside), len(elig), 100 * share, 100 * share_max, t, s, e))
    for label, v in (('before the first', pre), ('after the last', post)):
        if v > BIND_EDGE_SPEECH_MAX_S:
            p.append('%.2f s of speech %s raw word (limit %.2f s): the words do not cover this audio' % (v, label, BIND_EDGE_SPEECH_MAX_S))
    return m, p


def page_words(text):
    data = json.loads(text)
    pages = data.get('pages') if isinstance(data, dict) else data
    return [(w.get('w'), w.get('s'), w.get('e')) for pg in pages for w in pg.get('words', [])]


def first_pages_diff(derived, artifact):
    """-> a sentence naming the first differing word (index, token, both start / end) of two caption_pages.json texts."""
    try:
        a, b = page_words(derived), page_words(artifact)
    except (ValueError, AttributeError, TypeError):
        return 'one of the files is not a caption_pages.json list'
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return 'first differing word #%d: %r %s-%s (re-derived) vs %r %s-%s (artifact)' % (i, x[0], x[1], x[2], y[0], y[1], y[2])
    if len(a) != len(b):
        return 'the re-derived pages have %d words, the artifact %d' % (len(a), len(b))
    return 'same words, different bytes (page boundaries or formatting differ)'


def first_raw_diff(new, agent):
    """-> a sentence naming the first difference of two raw_asr.json documents (segment / word, else the top-level key)."""
    try:
        a, b = json.loads(new), json.loads(agent)
    except ValueError:
        return 'one of the raw files is not JSON'
    if not (isinstance(a, dict) and isinstance(b, dict)):
        return 'one of the raw files is not a JSON object'
    sa, sb = a.get('segments') or [], b.get('segments') or []
    for i, (x, y) in enumerate(zip(sa, sb)):
        if x == y:
            continue
        wx, wy = (x.get('words') or []) if isinstance(x, dict) else [], (y.get('words') or []) if isinstance(y, dict) else []
        for j, (u, v) in enumerate(zip(wx, wy)):
            if u != v:
                return ('first differing raw word: segment %d word %d %r %s-%s (re-transcribed) vs %r %s-%s (agent)'
                        % (i, j, u.get('word'), u.get('start'), u.get('end'), v.get('word'), v.get('start'), v.get('end')))
        keys = sorted(k for k in set(x) | set(y) if x.get(k) != y.get(k))
        return 'first differing raw segment %d: %s' % (i, ', '.join(keys) or 'word count %d vs %d' % (len(wx), len(wy)))
    if len(sa) != len(sb):
        return 'the re-transcription has %d segments, the agent raw %d' % (len(sa), len(sb))
    keys = sorted(k for k in set(a) | set(b) if k != 'segments' and a.get(k) != b.get(k))
    return 'same segments; differing top-level keys: %s' % (', '.join(keys) or '(formatting only)')


def raw_header_problems(ctx, raw):
    """B2.3: schema / version, script sha256, the chain code of the RUNNING checkout, the pinned params.  -> [(class, message)]"""
    p = []
    if raw.get('schema') != RAW_ASR_SCHEMA or raw.get('version') != RAW_ASR_VERSION:
        p.append((2, 'raw_asr.json is not a %s v%d document (schema %r, version %r): run word_timing.sh with the current chain'
                  % (RAW_ASR_SCHEMA, RAW_ASR_VERSION, raw.get('schema'), raw.get('version'))))
        return p
    if raw.get('script_sha256') != ctx.hash(ctx.paths['script']):
        p.append((2, 'raw_asr.json was decoded for another script (script_sha256 differs from %s): run word_timing.sh again'
                  % ctx.rel(ctx.paths['script'])))
    code = raw.get('code')
    want = {n: ctx.hash(SCRIPTS_DIR / n) for n in CHAIN_CODE_FILES}
    if code != want:
        names = sorted(n for n in set(want) | set(code if isinstance(code, dict) else {}) if not isinstance(code, dict) or code.get(n) != want.get(n))
        p.append((2, 'raw_asr.json was made by other chain code than this checkout (%s differ): run word_timing.sh with the current '
                  'scripts' % ', '.join(names)))
    if raw.get('params') != ASR_PARAMS:
        p.append((2, 'raw_asr.json was decoded with other params %s (pinned: %s): run word_timing.sh'
                  % (json.dumps(raw.get('params'), sort_keys=True), json.dumps(ASR_PARAMS, sort_keys=True))))
    return p


def defect_line(d):
    if not isinstance(d, dict):
        return str(d)[:DETAIL_MAX]
    return '%s %r @%s-%s: %s (limit %s)' % (d.get('code'), d.get('token'), d.get('start'), d.get('end'), d.get('value'), d.get('limit'))


def runner_word_timing(gate, ctx, base, report, limit, env):
    """`word-timing` (delivery and --check): raw_asr.json is bound to this avatar's audio, to script.txt and to the chain code;
    its toolchain must be this machine's; caption_pages.json must be what asr_align.py derives from it; timing_defects.py (page +
    raw rules, with the wav) must find nothing; the raw words must sit where the audio has speech (rules a / c).  Nothing is
    transcribed here, and word_timing.done.json is never read."""
    started = time.monotonic()
    P = ctx.paths
    wd = ctx.reports / 'word-timing'
    shutil.rmtree(wd, ignore_errors=True)
    wd.mkdir(parents=True)
    data = {'schema': 'yt-news-v4-word-timing-check', 'version': 1, 'pass': False,
            'raw': {'path': ctx.rel(P['word_raw']), 'sha256': ctx.hash(P['word_raw'])}, 'steps': {}}

    def left():
        return max(limit - (time.monotonic() - started), 0.1)

    def end(cls, reason='', issues=None, status=None):
        data['seconds'] = round(time.monotonic() - started, 2)
        if cls:
            data['problems'] = [reason] + list(issues or [])
            write_json_atomic(report, data)
            b = dict(base, seconds=data['seconds'])
            b['inputs'] = dict(base['inputs'])
            b['inputs'][ctx.rel(report)] = ctx.hash(report)
            return record(gate, status or {1: 'fail', 2: 'stale', 4: 'missing'}.get(cls, 'fail'), cls, reason, issues=issues, **b)
        data['pass'] = True
        return finish_runner(gate, ctx, dict(base, seconds=data['seconds']), report, data, '')

    raw, err = read_json(P['word_raw'])
    if err or not isinstance(raw, dict):
        return end(2, '%s is %s: run word_timing.sh' % (ctx.rel(P['word_raw']), err or 'not a JSON object'))
    hp = raw_header_problems(ctx, raw)
    if hp:
        return end(worst_class(c for c, _ in hp), '; '.join(m for _, m in hp))
    words = raw_words(raw)
    audio = raw.get('audio') if isinstance(raw.get('audio'), dict) else {}
    if words is None or not is_num(audio.get('duration')):
        return end(2, '%s has malformed segments / words / audio: run word_timing.sh' % ctx.rel(P['word_raw']))
    # B2.2 the audio: extracted again from the avatar, byte for byte what the chain decodes
    wav = wd / 'vo16k.wav'
    info, err, cls = extract_wav(ctx, wav, left())
    if err:
        return end(cls, err)
    data['steps']['wav'] = info
    if audio.get('wav_sha256') != info['sha256'] or audio.get('duration') != info['duration']:
        return end(1, "raw_asr.json was not decoded from this presenter video's audio (wav sha256 %s / duration %s s recorded, %s / %s s "
                   'extracted from %s): run word_timing.sh on this avatar' % (str(audio.get('wav_sha256'))[:12], audio.get('duration'),
                                                                             info['sha256'][:12], info['duration'], ctx.rel(ctx.avatar)))
    # B2.4 the toolchain
    recorded, why, cls = fingerprint_problem(ctx, raw, left())
    if why:
        return end(cls, why)
    # B2.5 the pages, re-derived
    pages = wd / 'caption_pages.json'
    res = spawn(asr_cmd('asr_align.py', '--raw', P['word_raw'], '--script', P['script'], '--out', pages), ctx, left(), asr_env())
    data['steps']['align'] = {'seconds': round(res['seconds'], 2), 'exit': res['code']}
    if res['cancelled'] or res['timed_out']:
        return end(4, 'asr_align.py %s' % ('was cancelled' if res['cancelled'] else 'exceeded the gate limit'), status='timeout' if res['timed_out'] else 'crashed')
    if res['code'] != 0 or not pages.is_file():
        cls = 2 if res['code'] == 2 else 4
        return end(cls, launcher_failure('asr_run.sh asr_align.py', res))
    if pages.read_bytes() != P['word_pages'].read_bytes():
        why = first_pages_diff(pages.read_text(encoding='utf-8'), P['word_pages'].read_text(encoding='utf-8'))
        return end(1, 'caption_pages.json is not what asr_align.py derives from raw_asr.json: re-run word_timing.sh, never hand-edit (%s)' % why)
    # B2.6 defects (page rules + the raw rules, with the wav)
    rep = wd / 'timing-defects.json'
    res = spawn(defects_cmd('--pages', pages, '--raw', P['word_raw'], '--wav', wav, '--report', rep), ctx, left(), asr_env())
    data['steps']['defects'] = {'seconds': round(res['seconds'], 2), 'exit': res['code']}
    if res['cancelled'] or res['timed_out']:
        return end(4, 'timing_defects.py %s' % ('was cancelled' if res['cancelled'] else 'exceeded the gate limit'), status='timeout' if res['timed_out'] else 'crashed')
    if res['code'] == 1:
        doc, _e = read_json(rep)
        found = (doc or {}).get('defects') if isinstance(doc, dict) else None
        lines = [defect_line(d) for d in (found or [])] or [l for l in res['stdout'].decode('utf-8', 'replace').splitlines() if l.strip()][:12]
        data['defects'] = found
        return end(1, 'the word timing has %d defect(s) (timing_defects.py): %s; re-run word_timing.sh, never hand-edit'
                   % (len(found or lines), '; '.join(lines[:3])), issues=lines[:12])
    if res['code'] == 2:
        return end(2, 'timing_defects.py refused its input: %s' % tail(res['stderr'].strip(), 400))
    if res['code'] != 0:
        return end(4, 'timing_defects.py exited %s: %s' % (res['code'], tail(res['stderr'].strip(), 400)))
    # B2.7 audio binding of the raw words
    try:
        th = timing_check_thresholds()
    except Exception as e:  # noqa: BLE001
        return end(4, 'cannot read the silence thresholds of timing_check.py: %s' % e)
    sil, err, cls = detect_silences(wav)
    if err:
        return end(cls, err)
    metrics, probs = audio_binding(words, sil, info['duration'], th)
    data['binding'] = metrics
    if probs:
        return end(1, '; '.join(probs))
    ctx.word_timing = {'raw': dict(data['raw']), 'fingerprint': recorded}
    remove_quiet(wav)
    return end(0)


def runner_asr_recheck(gate, ctx, base, report, limit, env):
    """`asr-recheck` (--check only): re-transcribe the avatar audio with this machine's chain in a NEW EMPTY dir and require
    byte-identical raw_asr.json and caption_pages.json.  Precondition: the recorded toolchain == this machine's (else exit 4).
    No tolerance path.  Running out of time is status `timeout` (exit 4, `retry: when-idle`), never a pass."""
    started = time.monotonic()
    P = ctx.paths
    wd = ctx.reports / 'asr-recheck'
    shutil.rmtree(wd, ignore_errors=True)
    wd.mkdir(parents=True)
    data = {'schema': 'yt-news-v4-asr-recheck', 'version': 1, 'pass': False, 'steps': {}}

    def left():
        return max(limit - (time.monotonic() - started), 0.1)

    def end(cls, reason='', issues=None, status=None, extra=None):
        data['seconds'] = round(time.monotonic() - started, 2)
        if cls:
            data['problems'] = [reason] + list(issues or [])
            data.update(extra or {})
            write_json_atomic(report, data)
            b = dict(base, seconds=data['seconds'])
            b['inputs'] = dict(base['inputs'])
            b['inputs'][ctx.rel(report)] = ctx.hash(report)
            return record(gate, status or {1: 'fail', 2: 'stale', 4: 'missing'}.get(cls, 'fail'), cls, reason, issues=issues, extra=extra, **b)
        data['pass'] = True
        return finish_runner(gate, ctx, dict(base, seconds=data['seconds']), report, data, '')

    def timed_out(step):
        data['steps'][step + '_timed_out'] = True
        return end(4, CHECK_TIMEOUT_MSG % ctx.budget, status='timeout', extra={'retry': 'when-idle'})

    raw, err = read_json(P['word_raw'])
    if err or not isinstance(raw, dict):
        return end(2, '%s is %s: run word_timing.sh' % (ctx.rel(P['word_raw']), err or 'not a JSON object'))
    _rec, why, cls = fingerprint_problem(ctx, raw, left())
    if why:
        return end(cls, why)
    wav = wd / 'vo16k.wav'
    info, err, cls = extract_wav(ctx, wav, left())
    if err:
        return end(cls, err)
    data['steps']['wav'] = info
    out = wd / 'asr'
    out.mkdir()                                   # NEW: no checkpoint of anybody can be resumed
    if any(out.iterdir()):
        return end(4, 'the re-transcription dir %s is not empty' % out)
    res = spawn(asr_cmd('asr_transcribe.py', '--wav', wav, '--script', P['script'], '--out-dir', out), ctx, left(), asr_env())
    data['steps']['transcribe'] = {'seconds': round(res['seconds'], 2), 'exit': res['code']}
    if res['cancelled']:
        return end(4, 'cancelled: finalize was terminated', status='crashed')
    if res['timed_out']:
        return timed_out('transcribe')
    text = res['stdout'].decode('utf-8', 'replace') + '\n' + res['stderr']
    if res['code'] == 5:
        lines = [l.strip() for l in text.splitlines() if 'DEFECT' in l][:12]
        return end(1, 'the re-transcription is still defective after the fixed repair ladder (asr_transcribe.py exit 5): %s'
                   % ('; '.join(lines[:3]) or tail(text.strip(), 300)), issues=lines)
    if res['code'] != 0:
        return end(2 if res['code'] == 2 else 4, launcher_failure('asr_run.sh asr_transcribe.py', res))
    new_raw = out / 'raw_asr.json'
    if not new_raw.is_file():
        return end(4, 'asr_transcribe.py exited 0 but wrote no raw_asr.json')
    pages = out / 'caption_pages.json'
    res = spawn(asr_cmd('asr_align.py', '--raw', new_raw, '--script', P['script'], '--out', pages), ctx, left(), asr_env())
    data['steps']['align'] = {'seconds': round(res['seconds'], 2), 'exit': res['code']}
    if res['cancelled']:
        return end(4, 'cancelled: finalize was terminated', status='crashed')
    if res['timed_out']:
        return timed_out('align')
    if res['code'] != 0 or not pages.is_file():
        return end(2 if res['code'] == 2 else 4, launcher_failure('asr_run.sh asr_align.py', res))
    data['rawSha256'] = {'retranscribed': sha256_file(new_raw), 'agent': ctx.hash(P['word_raw'])}
    data['pagesSha256'] = {'retranscribed': sha256_file(pages), 'agent': ctx.hash(P['word_pages'])}
    probs = []
    if new_raw.read_bytes() != P['word_raw'].read_bytes():
        probs.append('raw_asr.json is not what this machine transcribes from the avatar audio (%s)'
                     % first_raw_diff(new_raw.read_text(encoding='utf-8'), P['word_raw'].read_text(encoding='utf-8')))
    if pages.read_bytes() != P['word_pages'].read_bytes():
        probs.append('caption_pages.json differs from the re-transcription (%s)'
                     % first_pages_diff(pages.read_text(encoding='utf-8'), P['word_pages'].read_text(encoding='utf-8')))
    if probs:
        return end(1, '; '.join(probs) + ': re-run word_timing.sh, never hand-edit')
    remove_quiet(wav)
    return end(0)


RUNNERS = {'script': runner_script, 'derived': runner_derived, 'music_presence': runner_music_presence, 'face_box': runner_face_box,
           'cuts': runner_cuts, 'mux_audio': runner_mux_audio, 'word_timing': runner_word_timing, 'asr_recheck': runner_asr_recheck}
# console label of a runner gate (its `command`), and the tools it calls besides its scripts (checked before it starts: missing = 4)
RUNNER_COMMANDS = {'music_presence': 'ffmpeg -af volumedetect', 'cuts': 'sha256 + ffmpeg (clip frame vs source frames at source_in)',
                   'mux_audio': 'mux_av.sh audio rebuild (ffmpeg mix + loudnorm x2 + aac) vs the final audio',
                   'word_timing': 'wav from the avatar + asr_run.sh asr_transcribe.py --fingerprint, asr_run.sh asr_align.py, timing_defects.py --wav + '
                                  'silencedetect (raw_asr.json re-checked, nothing transcribed)',
                   'asr_recheck': 'asr_run.sh asr_transcribe.py --wav (new empty dir) + asr_run.sh asr_align.py, byte-compared with the agent files'}
RUNNER_TOOLS = {'face_box': ('ffmpeg', 'ffprobe'), 'cuts': ('ffmpeg',), 'mux_audio': ('ffmpeg', 'ffprobe')}


def run_gate(gate, ctx, inputs, deadline, env, deps=None):
    """deadline: absolute time.monotonic() value the gates must be finished by."""
    deps = deps or {}
    argv, report, dep_paths, problems = build_command(gate, ctx, deps)
    inputs = dict(inputs)
    for path in dep_paths:
        inputs.setdefault(ctx.rel(path), ctx.hash(path))
    rel_report = ctx.rel(report)
    runner = gate.get('runner')
    scripts = gate_scripts(gate)
    if runner:
        cmd = ['<%s>' % gate['name']]
        command = RUNNER_COMMANDS.get(runner) or ' + '.join(scripts)
    else:
        cmd = exe_for(ctx, gate['script']) + argv
        command = shlex.join(cmd)
    base = dict(report=rel_report, inputs=inputs, command=command)
    for name in scripts:
        if not (SCRIPTS_DIR / name).is_file():
            return record(gate, 'missing', 4, 'gate script missing: %s' % name, **base)
    for interp in sorted(interps_needed(gate)):
        if interp != 'python' and not ctx.tools.get(interp):
            return record(gate, 'missing', 4, '%s not found at %s' % (interp, ', '.join(TOOL_CANDIDATES.get(interp, ()))), **base)
    block = dependency_block(gate, deps)
    if block:
        return record(gate, 'blocked', block[0], block[1], **base)
    if problems:
        return record(gate, 'bad-input', 2, '; '.join(problems), **base)
    report.parent.mkdir(parents=True, exist_ok=True)
    if report.exists():
        report.unlink()           # a report can only exist if THIS run wrote it
    remaining = deadline - time.monotonic()
    limit = min(gate['limit'], remaining)
    if limit < 1:
        return record(gate, 'timeout', 4, 'finalize time budget (%ds, phase gates) exhausted before the gate started' % ctx.budget, **base)
    if STOP.is_set():
        return record(gate, 'crashed', 4, 'cancelled: finalize was terminated', **base)
    if runner:
        return RUNNERS[runner](gate, ctx, base, report, limit, env)
    res = spawn(cmd, ctx, limit, env)
    start_ns = res['start_ns']
    stdout = res['stdout'].decode('utf-8', 'replace')
    secs, code = res['seconds'], res['code']
    out = (stdout + ('\n' if stdout and res['stderr'] else '') + res['stderr'])
    base.update(code=code, seconds=secs, out=out)
    if res['cancelled']:
        return record(gate, 'crashed', 4, 'cancelled: finalize was terminated', **{**base, 'code': None})
    if res['timed_out']:
        return record(gate, 'timeout', 4, 'timeout: gate exceeded its %.0fs limit' % limit, **{**base, 'code': None})
    if gate.get('stdout_report'):
        try:
            parsed = json.loads(stdout)
            if isinstance(parsed, dict):
                write_json_atomic(report, parsed)
        except (ValueError, OSError):
            pass
    data = None
    if report.is_file() and report.stat().st_mtime_ns >= start_ns - STALE_TOLERANCE_NS:
        data, _err = read_json(report)
    issues = summarize_issues(data)
    base['issues'] = issues
    if gate.get('copy_args') and isinstance(data, dict) and isinstance(data.get('copy_search'), dict):
        base['extra'] = {'copy_search': data['copy_search']}       # where the copy detector looked (check.json / receipt: information)
    if code != 0:
        cls = class_for_exit(gate, code)
        if code < 0:
            return record(gate, 'crashed', 4, 'gate was killed by signal %d' % -code, **base)
        if code in (1, 2, 4) or code in gate.get('exit_classes', {}):
            why = 'gate exited with code %d' % code
            if gate.get('copy_args') and code == 1:          # a content failure must still say where the copy search looked
                why = '; '.join([why] + copy_search_problems(data, ctx))
            return record(gate, STATUS_BY_CLASS[cls], cls, why, **base)
        return record(gate, 'crashed', 4, 'gate exited with unexpected code %d' % code, **base)
    # exit 0: the report must exist, be fresh, parse, and say pass:true
    if not report.is_file():
        return record(gate, 'stale', 2, 'exit 0 but no report was written at %s' % rel_report, **base)
    if report.stat().st_mtime_ns < start_ns - STALE_TOLERANCE_NS:
        return record(gate, 'stale', 2, 'report is older than this run (stale): %s' % rel_report, **base)
    if not isinstance(data, dict):
        return record(gate, 'stale', 2, 'report unreadable or not a JSON object: %s' % rel_report, **base)
    if data.get(gate.get('pass_key', 'pass')) is not True:
        return record(gate, 'fail', 1, 'report says %s != true' % gate.get('pass_key', 'pass'), **base)
    if gate.get('validate'):
        bad = VALIDATORS[gate['validate']](data, ctx)
        if bad:
            cls = 2 if any(c == 2 for c, _ in bad) else 1
            return record(gate, STATUS_BY_CLASS[cls], cls, '; '.join(m for _, m in bad), **base)
    base['inputs'] = dict(inputs)
    base['inputs'][rel_report] = ctx.hash(report)
    return record(gate, 'pass', 0, '', **base)


def purge_pycache(skill_dir):
    for dirpath, dirnames, _ in os.walk(skill_dir):
        for d in list(dirnames):
            if d == '__pycache__':
                shutil.rmtree(os.path.join(dirpath, d), ignore_errors=True)
                dirnames.remove(d)


# ---------------------------------------------------------------- verified reports
def time_left(deadline, cap):
    """Seconds a post-verification subprocess may use: min(cap, time left), or None when less than 1 s is left."""
    left = deadline.remaining()
    return None if left < 1 else min(cap, left)


def budget_msg(deadline, phase='post-verification'):
    return 'time budget (%ds) exhausted during phase "%s"' % (deadline.total, phase)


def node_manifest_hash(manifest_path, env, ctx, deadline):
    """manifestHash() computed by the OTHER team's JS (never re-implemented). -> (hash|None, error, class)"""
    qm = SCRIPTS_DIR / QC_MANIFEST_SCRIPT
    node = ctx.tools.get('node')
    if not qm.is_file():
        return None, '%s is missing from the skill (cannot recompute manifestHash)' % QC_MANIFEST_SCRIPT, 4
    if not node:
        return None, 'node not found on PATH (cannot recompute manifestHash)', 4
    timeout = time_left(deadline, 30)
    if timeout is None:
        return None, budget_msg(deadline), 4
    code = ("import {pathToFileURL} from 'node:url'; import fs from 'node:fs';"
            "const m = await import(pathToFileURL(process.argv[1]).href);"
            "console.log(m.manifestHash(JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))));")
    try:
        r = subprocess.run([node, '--input-type=module', '-e', code, str(qm), str(manifest_path)], capture_output=True,
                           text=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, 'manifestHash computation failed: %s' % e, 4
    h = r.stdout.strip()
    if r.returncode != 0 or not valid_sha(h):
        return None, 'manifestHash computation failed (exit %d): %s' % (r.returncode, tail(r.stderr, 300)), 4
    return h.lower(), None, 0


MEDIA_DIGEST_SCRIPT = 'media_digest.mjs'


def node_fresh_layout_hashes(ctx, env, deadline):
    """What the layout manifest must say, computed NOW by the other team's JS from the bytes: computeSourceHashes() of the running
    checkout + this episode/captions, digestDir() of <public>/<assetDir> and <public>/fonts WITHOUT a hash cache (no cacheFile:
    every file is read).  -> ({sourceHashes, media, fonts}|None, error, class)"""
    qm, md, node = SCRIPTS_DIR / QC_MANIFEST_SCRIPT, SCRIPTS_DIR / MEDIA_DIGEST_SCRIPT, ctx.tools.get('node')
    for f in (qm, md):
        if not f.is_file():
            return None, '%s is missing from the skill (cannot recompute the layout hashes)' % f.name, 4
    if not node:
        return None, 'node not found on PATH (cannot recompute the layout hashes)', 4
    if not ctx.ep['asset_dir']:
        return None, 'episode.json has no assetDir: the media digest cannot be computed', 2
    for key in ('episode', 'captions'):           # an input of the agent that is gone is the agent's problem (2), not a broken tool (4)
        if not ctx.paths[key].is_file():
            return None, 'the layout hashes cannot be recomputed: %s does not exist' % ctx.rel(ctx.paths[key]), 2
    timeout = time_left(deadline, 90)
    if timeout is None:
        return None, budget_msg(deadline), 4
    code = ("import {pathToFileURL} from 'node:url'; import fs from 'node:fs';"
            "const [qmp, mdp, composer, skill, episode, captions, media, fonts] = process.argv.slice(1);"
            "const qm = await import(pathToFileURL(qmp).href); const md = await import(pathToFileURL(mdp).href);"
            "const out = {sourceHashes: await qm.computeSourceHashes({composerDir: composer, skillDir: skill, episodePath: episode,"
            " captionsPath: captions})};"
            "out.media = fs.existsSync(media) ? await md.digestDir(media) : null;"
            "out.fonts = fs.existsSync(fonts) ? await md.digestDir(fonts) : null;"
            "console.log(JSON.stringify(out));")
    args = [str(qm), str(md), str(ctx.composer), str(SKILL_DIR), str(ctx.paths['episode']), str(ctx.paths['captions']),
            str(ctx.public / ctx.ep['asset_dir']), str(ctx.public / 'fonts')]
    try:
        r = subprocess.run([node, '--input-type=module', '-e', code, *args], capture_output=True, text=True, timeout=timeout, env=env,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, 'recomputing the layout hashes failed: %s' % e, 4
    try:
        out = json.loads(r.stdout) if r.returncode == 0 else None
    except ValueError:
        out = None
    if not (isinstance(out, dict) and isinstance(out.get('sourceHashes'), dict)):
        return None, 'recomputing the layout hashes failed (exit %d): %s' % (r.returncode, tail(r.stderr, 300)), 4
    return out, None, 0


def compare_digest(label, claimed, fresh, asset_dir=None):
    """A digest object of the layout manifest vs the fresh digestDir() result.  -> problems"""
    if fresh is None:
        return ['%s: the directory does not exist under the public root' % label]
    if not isinstance(claimed, dict):
        return ['run manifest has no %s' % label]
    p = []
    for k in ('method', 'digest', 'files', 'bytes'):
        if claimed.get(k) != fresh.get(k):
            p.append('layout was run on different media: run manifest %s.%s is %r but the files now give %r'
                     % (label, k, claimed.get(k) if k != 'digest' else str(claimed.get(k))[:12],
                        fresh.get(k) if k != 'digest' else str(fresh.get(k))[:12]))
            break
    if asset_dir is not None and claimed.get('assetDir') != asset_dir:
        p.append('run manifest %s.assetDir %r is not the episode assetDir %r' % (label, claimed.get('assetDir'), asset_dir))
    return p


def verify_layout(report_path, ctx, env, deadline):
    """-> (problems, tool_class, info, inputs).  tool_class 4 when the hash helper could not run."""
    report_path = Path(report_path)
    data, err = read_json(report_path)
    if err or not isinstance(data, dict):
        return ['layout report %s: %s' % (ctx.rel(report_path), err or 'not a JSON object')], 0, {}, {}
    p, info, inputs, tool = [], {}, {}, 0
    if data.get('schema') != LAYOUT_REPORT_SCHEMA:
        p.append('layout report schema is %r' % data.get('schema'))
    if data.get('version') != LAYOUT_REPORT_VERSION:
        p.append('layout report version is %r, expected %d' % (data.get('version'), LAYOUT_REPORT_VERSION))
    if data.get('status') != 'finished':
        p.append('layout status is %r, not "finished"' % data.get('status'))
    if data.get('pass') is not True:
        p.append('layout report pass != true')
    if data.get('complete') is not True:
        p.append('layout report is not complete')
    rc, fc = data.get('requestedCount'), data.get('fullPlanCount')
    if not (is_int(rc) and is_int(fc) and fc > 0 and rc == fc):
        p.append('layout requestedCount (%r) != fullPlanCount (%r)' % (rc, fc))
    if data.get('compositionId') != COMP:
        p.append('layout compositionId %r != %r' % (data.get('compositionId'), COMP))
    run_id, mhash = data.get('runId'), data.get('manifestHash')
    if not (isinstance(run_id, str) and run_id):
        p.append('layout report has no runId')
    if not valid_sha(mhash):
        p.append('layout report has no valid manifestHash')
    info = {'runId': run_id, 'manifestHash': mhash, 'reportSha256': ctx.hash(report_path), 'reusedFrames': data.get('reusedFrames')}
    inputs[ctx.rel(report_path)] = info['reportSha256']
    mp = data.get('manifestPath')
    if not (isinstance(mp, str) and mp):
        p.append('layout report has no manifestPath')
        return p, tool, info, inputs
    layout_dir = report_path.parent.resolve()
    mpath = Path(mp)
    mpath = (mpath if mpath.is_absolute() else layout_dir / mpath).resolve()
    if not inside(mpath, layout_dir):
        p.append('layout manifestPath is outside %s: %s' % (ctx.rel(layout_dir), mp))
        return p, tool, info, inputs
    manifest, merr = read_json(mpath)
    if merr or not isinstance(manifest, dict):
        p.append('layout run manifest %s: %s' % (ctx.rel(mpath), merr or 'not a JSON object'))
        return p, tool, info, inputs
    inputs[ctx.rel(mpath)] = ctx.hash(mpath)
    if manifest.get('schema') != RUN_MANIFEST_SCHEMA:
        p.append('run manifest schema is %r' % manifest.get('schema'))
    if manifest.get('compositionId') != COMP:
        p.append('run manifest compositionId is %r' % manifest.get('compositionId'))
    if manifest.get('runId') != run_id:
        p.append('run manifest runId differs from the report')
    hashes = manifest.get('sourceHashes')
    if not isinstance(hashes, dict):
        p.append('run manifest has no sourceHashes')
    else:
        for key, path in ((MANIFEST_KEY_EPISODE, ctx.paths['episode']), (MANIFEST_KEY_CAPTIONS, ctx.paths['captions']),
                          (MANIFEST_KEY_LOCK, LOCK_FILE), (ENGINE_REL, ctx.composer / ENGINE_REL),
                          (ENTRY_REL, ctx.composer / ENTRY_REL)):
            want = hashes.get(key)
            if not valid_sha(want):
                p.append('run manifest sourceHashes[%s] missing' % key)
            elif not Path(path).is_file() or ctx.hash(path) != want.lower():
                p.append('layout was run on a different %s (sourceHashes[%s] differs from the current file)' % (key, key))
    h, herr, tool = node_manifest_hash(mpath, env, ctx, deadline)
    if herr:
        p.append(herr)
    elif valid_sha(mhash) and h != mhash.lower():
        p.append('run manifest hash %s does not match report.manifestHash' % h[:12])
    # every claim of the manifest about its inputs, recomputed from the bytes (never from qc/layout/cache/media-hash.json)
    fresh, ferr, fcls = node_fresh_layout_hashes(ctx, env, deadline)
    if ferr:
        p.append(ferr)
        tool = max(tool, fcls) if fcls == 4 else tool
        return p, tool, info, inputs
    info['freshMedia'], info['freshFonts'] = fresh.get('media'), fresh.get('fonts')
    if isinstance(hashes, dict):
        now = fresh['sourceHashes']
        diff = sorted(k for k in set(hashes) | set(now) if hashes.get(k) != now.get(k))
        if diff:
            p.append('layout was run on different code or inputs than the running checkout + this episode: sourceHashes differ for %s'
                     % ', '.join(diff[:8]) + (' ... (+%d more)' % (len(diff) - 8) if len(diff) > 8 else ''))
    p += compare_digest('mediaDigest', manifest.get('mediaDigest'), fresh.get('media'), ctx.ep['asset_dir'])
    p += compare_digest('fontsDigest', manifest.get('fontsDigest'), fresh.get('fonts'))
    return p, tool, info, inputs


def parse_fps(text):
    try:
        a, _, b = str(text).partition('/')
        return float(a) / float(b or 1)
    except (ValueError, ZeroDivisionError):
        return None


def probe_video(ctx, path, env, deadline):
    """ffprobe of the first video stream WITHOUT decoding (packet count). -> (info|None, error, class)"""
    ffprobe = ctx.tools.get('ffprobe')
    if not ffprobe:
        return None, 'ffprobe not found', 4
    timeout = time_left(deadline, 60)
    if timeout is None:
        return None, budget_msg(deadline), 4
    try:
        r = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-count_packets', '-show_entries',
                            'stream=width,height,r_frame_rate,nb_read_packets,pix_fmt,color_space,color_range',
                            '-of', 'json', str(path)],
                           capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, env=env)
        s = json.loads(r.stdout)['streams'][0]
        info = {'width': int(s['width']), 'height': int(s['height']), 'fps': parse_fps(s['r_frame_rate']),
                'frames': int(s['nb_read_packets']), 'pix_fmt': s.get('pix_fmt'), 'color_space': s.get('color_space'),
                'color_range': s.get('color_range')}
    except subprocess.TimeoutExpired:
        return None, 'ffprobe timed out on %s' % ctx.rel(path), 4
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None, 'cannot probe the video stream of %s' % ctx.rel(path), 2
    if info['fps'] is None:
        return None, 'cannot read the frame rate of %s' % ctx.rel(path), 2
    return info, None, 0


def verify_video_format(ctx, probe_visual, probe_final):
    """The V4 render is yuv420p; mux_av.sh only copies it, so a different pix_fmt means the final was re-encoded."""
    p = []
    for label, path, probe in (('visual', ctx.paths['visual'], probe_visual), ('final', ctx.paths['final'], probe_final)):
        if probe is not None and probe['pix_fmt'] != EXPECTED_PIX_FMT:
            p.append('%s pix_fmt is %r, not %s: the final must not be re-encoded (mux_av.sh copies the visual stream as it was rendered)'
                     % (ctx.rel(path), probe['pix_fmt'], EXPECTED_PIX_FMT))
    return p


def verify_render_receipt(receipt_path, ctx, layout_info, probe=None):
    """Real contract (render_episode.mjs RECEIPT_FIELDS). -> (problems, info).  probe: ffprobe info of the visual file."""
    data, err = read_json(receipt_path)
    if err or not isinstance(data, dict):
        return ['render receipt %s: %s' % (ctx.rel(receipt_path), err or 'not a JSON object')], {}
    p = []
    h = ctx.hash
    visual = ctx.paths['visual']
    if data.get('schema') != RENDER_RECEIPT_SCHEMA:
        p.append('render receipt schema is %r' % data.get('schema'))
    if data.get('schemaVersion') != 1:
        p.append('render receipt schemaVersion is %r' % data.get('schemaVersion'))
    if data.get('compositionId') != COMP:
        p.append('render receipt compositionId is %r' % data.get('compositionId'))
    if data.get('draft') is not False:
        p.append('render receipt is a draft (or draft flag missing)')
    if data.get('hasAudio') is not False:
        p.append('render receipt hasAudio is not false')
    for key, path, label in (('outputSha256', visual, 'visual render'), ('episodeJsonSha256', ctx.paths['episode'], 'episode.json'),
                             ('captionsJsonSha256', ctx.paths['captions'], 'captions')):
        v = data.get(key)
        if not valid_sha(v):
            p.append('render receipt %s missing' % key)
        elif not Path(path).is_file() or h(path) != v.lower():
            p.append('render receipt %s does not match the current %s (stale render)' % (key, label))
    lock = data.get('gatesLockSha256')
    if not valid_sha(lock):
        p.append('render receipt gatesLockSha256 is null/invalid (render ran without a lock)')
    elif not LOCK_FILE.is_file() or h(LOCK_FILE) != lock.lower():
        p.append('render receipt gatesLockSha256 differs from the current gates.lock.json')
    for key, rel in (('engineSha256', ENGINE_REL), ('entrySha256', ENTRY_REL)):
        v, f = data.get(key), ctx.composer / rel
        if not valid_sha(v):
            p.append('render receipt %s missing' % key)
        elif not f.is_file() or h(f) != v.lower():
            p.append('render receipt %s does not match the current composer %s (rendered with another engine/entry)' % (key, rel))
    closure = data.get('entryClosure')
    if not (isinstance(closure, dict) and closure):
        p.append('render receipt entryClosure missing')
    else:
        for rel, v in sorted(closure.items()):
            f = (ctx.composer / rel) if isinstance(rel, str) and rel.startswith('src/') and '..' not in Path(rel).parts else None
            if f is None or not valid_sha(v):
                p.append('render receipt entryClosure has a bad entry %r' % (rel,))
            elif not f.is_file() or h(f) != v.lower():
                p.append('render receipt entryClosure[%s] does not match the current composer file' % rel)
        for rel in (ENGINE_REL, ENTRY_REL):
            if rel not in closure:
                p.append('render receipt entryClosure does not list %s' % rel)
    # the media / fonts the render staged (its receipt) must be the files there are now (digests computed fresh, no cache)
    for key, fresh in (('mediaDigest', layout_info.get('freshMedia')), ('fontsDigest', layout_info.get('freshFonts'))):
        if isinstance(fresh, dict) and data.get(key) != fresh.get('digest'):
            p.append('render receipt %s does not match the media under the public root now (rendered from other files)' % key)
    fm = layout_info.get('freshMedia')
    if isinstance(fm, dict) and data.get('mediaDigestMethod') != fm.get('method'):
        p.append('render receipt mediaDigestMethod %r is not %r' % (data.get('mediaDigestMethod'), fm.get('method')))
    if layout_info.get('manifestHash') and (data.get('gateManifestHash') or '').lower() != str(layout_info['manifestHash']).lower():
        p.append('render receipt gateManifestHash differs from the layout report manifestHash')
    if layout_info.get('runId') and data.get('gateRunId') != layout_info['runId']:
        p.append('render receipt gateRunId differs from the layout report runId')
    if probe is not None:
        for key in ('width', 'height'):
            if data.get(key) != probe[key]:
                p.append('render receipt %s %r does not match the visual file (%d)' % (key, data.get(key), probe[key]))
        if not (is_num(data.get('fps')) and abs(data['fps'] - probe['fps']) < 1e-3):
            p.append('render receipt fps %r does not match the visual file (%s)' % (data.get('fps'), round(probe['fps'], 3)))
        if data.get('frameCount') != probe['frames']:
            p.append('render receipt frameCount %r does not match the visual file (%d frames)' % (data.get('frameCount'), probe['frames']))
    return p, {'renderId': data.get('renderId'), 'receiptSha256': h(receipt_path)}


MUSIC_SCHEMA = 'yt-news-v4-music-source'
MUSIC_PROVIDER_ONLINE = 'pixabay_music'
MUSIC_PROVIDER_LIBRARY = 'music_library'      # == music_library.SIDECAR_PROVIDER
MUSIC_MANIFEST = SCRIPTS_DIR / 'music_library.json'       # the skill's own (locked) copy: the only manifest that counts


def load_music_manifest():
    """The skill's own approved-music list.  -> (helper module, manifest, None) or (None, None, error text)."""
    try:
        lib = load_sibling('music_library')
        return lib, lib.load_manifest(MUSIC_MANIFEST), None
    except Exception as e:  # noqa: BLE001 - MusicLibraryError, a missing helper, anything: fail closed
        return None, None, str(e) or type(e).__name__


def verify_library_music(lib, manifest, src, bed_sha):
    """provider music_library: the bed must be a track of the skill's own list.  -> (problems, receipt fields)"""
    short = bed_sha[:12]
    track = lib.find_track(manifest, bed_sha)
    if not isinstance(track, dict):
        return ['music bed %s is not in the approved music library (scripts/music_library.json)' % short], {}
    bad = [(k, src.get(k), track.get(f)) for k, f in (('library_file', 'file'), ('license', 'license')) if src.get(k) != track.get(f)]
    if bad:
        return ['music bed %s is not in the approved music library as described by its fetch record: %s'
                % (short, ', '.join('%s is %r but the manifest says %r' % b for b in bad))], {}
    fields = {'library_file': track.get('file'), 'track_title': track.get('title'), 'license': track.get('license'),
              'origin': track.get('origin'), 'approved_by': track.get('approved_by'), 'approved_on': track.get('approved_on'),
              'manifest_sha256': sha256_file(MUSIC_MANIFEST), 'sidecar_manifest_sha256': src.get('manifest_sha256')}
    return [], fields


def verify_mux_receipt(receipt_path, ctx):
    data, err = read_json(receipt_path)
    if err or not isinstance(data, dict):
        stem = ctx.paths['final'].with_suffix('')
        return ['mux receipt %s: %s (mux_av.sh writes it only after the loudness check passes; see %s.audio/final.json)'
                % (ctx.rel(receipt_path), err or 'not a JSON object', ctx.rel(stem))], {}
    p, info = [], {'receiptSha256': ctx.hash(receipt_path)}
    if data.get('schema') != 'yt-news-v4-mux-receipt':
        p.append('mux receipt has the wrong schema')
    again = 'run mux_av.sh again with <TOTAL>=<totalDurationSec> <VO_END>=<voEndSec>'
    if data.get('version') != MUX_RECEIPT_VERSION:
        p.append('mux receipt version is %r, expected %d (it was written by an older mux_av.sh); %s' % (data.get('version'), MUX_RECEIPT_VERSION, again))
    for key, ep_key, ep_name in (('vo_end', 'vo_end', 'voEndSec'), ('total', 'total', 'totalDurationSec')):
        v, want = data.get(key), ctx.ep[ep_key]
        if not is_num(v):
            p.append('mux receipt %s is missing (an old receipt); %s' % (key, again))
        elif want is not None and abs(v - want) > MUX_EPISODE_TOLERANCE + 1e-9:
            p.append('mux receipt %s %s does not match the episode %s %s; %s' % (key, v, ep_name, want, again))
    if data.get('bed_volume') != MUX_BED_VOLUME:
        p.append('mux receipt bed_volume is %r, not %s (the fixed mix setting of mux_av.sh); %s' % (data.get('bed_volume'), MUX_BED_VOLUME, again))
    avatar = ctx.avatar
    if avatar is None:
        p.append('episode.json has no assetDir/avatarFile; cannot bind the avatar')
    bed = data.get('bed')
    bed_path = Path(bed['path']) if isinstance(bed, dict) and isinstance(bed.get('path'), str) and bed['path'] else None
    for key, path in (('visual', ctx.paths['visual']), ('final', ctx.paths['final']), ('avatar', avatar), ('bed', bed_path)):
        if path is None:
            if key == 'bed':
                p.append('mux receipt bed.path missing')
            continue
        v = data.get(key)
        if not (isinstance(v, dict) and valid_sha(v.get('sha256'))):
            p.append('mux receipt %s.sha256 missing' % key)
        elif not Path(path).is_file() or ctx.hash(path) != v['sha256'].lower():
            p.append('mux receipt %s.sha256 does not match the current %s' % (key, ctx.rel(path)))
    audio_dir = ctx.project / 'assets' / 'audio'
    if bed_path is not None and bed_path.is_file() and not inside(bed_path, audio_dir):
        p.append('music bed must be a file under %s/ (got %s)' % (ctx.rel(audio_dir), bed_path))
    elif bed_path is not None and bed_path.is_file():
        sidecar = Path(str(bed_path) + '.source.json')
        src, serr = read_json(sidecar)
        bed_sha = ctx.hash(bed_path)
        lib, manifest, merr = load_music_manifest()                 # FIRST, whatever the provider says
        if merr:
            p.append('music bed %s is not in the approved music library: scripts/music_library.json cannot be used (%s)'
                     % (bed_sha[:12], merr))
        if serr or not isinstance(src, dict):
            p.append('music bed has no fetch record: %s is %s' % (ctx.rel(sidecar), serr or 'not a JSON object'))
        elif src.get('schema') != MUSIC_SCHEMA:
            p.append('music bed has no fetch record: %s schema is %r' % (ctx.rel(sidecar), src.get('schema')))
        elif not (valid_sha(src.get('sha256')) and src['sha256'].lower() == bed_sha):
            p.append('music bed has no fetch record: %s sha256 does not match %s' % (ctx.rel(sidecar), ctx.rel(bed_path)))
        else:
            provider = src.get('provider')
            info['music'] = {k: src.get(k) for k in ('provider', 'track_id', 'track_title', 'url')}
            info['music']['bed_sha256'] = bed_sha
            info['music']['sidecar'] = {'path': ctx.rel(sidecar), 'sha256': ctx.hash(sidecar)}
            if merr:
                pass                                                # already reported; no provider is accepted without the list
            elif provider == MUSIC_PROVIDER_LIBRARY:
                lp, fields = verify_library_music(lib, manifest, src, bed_sha)
                p += lp
                info['music'].update(fields)
            elif provider == MUSIC_PROVIDER_ONLINE:
                if manifest.get('tracks'):
                    p.append('music bed %s: provider %s is not accepted while the approved music library has tracks '
                             '(scripts/music_library.json); run the music step again' % (bed_sha[:12], MUSIC_PROVIDER_ONLINE))
            else:
                p.append('music bed %s has an unknown provider %r in %s (expected %s or %s)'
                         % (bed_sha[:12], provider, ctx.rel(sidecar), MUSIC_PROVIDER_ONLINE, MUSIC_PROVIDER_LIBRARY))
    return p, info


def stream_hash(ctx, path, env, deadline):
    """sha256 of the video packet stream: ffmpeg -c copy -f streamhash. -> (line|None, error, class)"""
    ffmpeg = ctx.tools.get('ffmpeg')
    if not ffmpeg:
        return None, 'ffmpeg not found', 4
    timeout = time_left(deadline, 60)
    if timeout is None:
        return None, budget_msg(deadline), 4
    try:
        r = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-i', str(path), '-map', '0:v:0', '-c', 'copy', '-f', 'streamhash',
                            '-hash', 'sha256', '-'], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        return None, 'ffmpeg streamhash timed out on %s' % ctx.rel(path), 4
    except OSError as e:
        return None, 'ffmpeg failed: %s' % e, 4
    lines = [x.strip() for x in r.stdout.splitlines() if x.strip().startswith('0,v,SHA256=')]
    if r.returncode != 0 or len(lines) != 1:
        return None, 'cannot hash the video stream of %s: %s' % (ctx.rel(path), tail(r.stderr, 200)), 2
    return lines[0], None, 0


def verify_mux_video(ctx, env, deadline):
    """mux_av.sh stream-copies the video (-c:v copy): final.mp4 must carry exactly the packets of visual.mp4."""
    a, err, cls = stream_hash(ctx, ctx.paths['visual'], env, deadline)
    if err:
        return [err], cls, {}
    b, err, cls = stream_hash(ctx, ctx.paths['final'], env, deadline)
    if err:
        return [err], cls, {}
    info = {'visualStream': a, 'finalStream': b}
    if a != b:
        return ['the video stream of %s differs from %s (mux_av.sh must only copy it): the final was not made from this visual'
                % (ctx.rel(ctx.paths['final']), ctx.rel(ctx.paths['visual']))], 2, info
    return [], 0, info


def verify_duration(ctx, env, deadline):
    final, total = ctx.paths['final'], ctx.ep['total']
    if total is None:
        return ['totalDurationSec unavailable: %s' % ctx.ep['error']], 2, {}
    ffprobe = ctx.tools.get('ffprobe')
    if not ffprobe:
        return ['ffprobe not found'], 4, {}
    timeout = time_left(deadline, 60)
    if timeout is None:
        return [budget_msg(deadline)], 4, {}
    try:
        r = subprocess.run([ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1',
                            str(final)], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, env=env)
        dur = float(r.stdout.strip())
    except subprocess.TimeoutExpired:
        return ['ffprobe timed out on %s' % ctx.rel(final)], 4, {}
    except (OSError, ValueError):
        return ['cannot read the duration of %s' % ctx.rel(final)], 2, {}
    info = {'duration': round(dur, 3), 'totalDurationSec': total}
    if abs(dur - total) > FRAME_TOLERANCE_SEC + 1e-3:
        return ['final duration %.3fs differs from totalDurationSec %.3fs by more than one frame (%.2fs)'
                % (dur, total, FRAME_TOLERANCE_SEC)], 2, info
    return [], 0, info


def verified_record(name, problems, ctx, report, inputs, cls=2, status='stale', extra=None):
    g = {'name': name, 'required': True}
    rel = ctx.rel(report) if report else None
    if problems:
        return record(g, status, cls, '; '.join(problems), rel, None, 0, inputs, kind='verified', extra=extra)
    return record(g, 'pass', 0, '', rel, None, 0, inputs, kind='verified', extra=extra)


def run_verified(ctx, env, deadline):
    h, P = ctx.hash, ctx.paths
    recs, summary_info = [], {}
    # layout
    lp = P['layout_report']
    probs, tool, linfo, linputs = verify_layout(lp, ctx, env, deadline)
    extra = {'runId': linfo.get('runId'), 'manifestHash': linfo.get('manifestHash'), 'reportSha256': linfo.get('reportSha256'),
             'reusedFrames': linfo.get('reusedFrames')} if linfo else None
    recs.append(verified_record('layout', probs, ctx, lp, linputs, cls=4 if tool == 4 else 2,
                                status='missing' if tool == 4 else 'stale', extra=extra))
    summary_info['layout'] = {k: linfo.get(k) for k in ('runId', 'manifestHash', 'reportSha256', 'reusedFrames')}
    # render receipt (+ its width/height/fps/frameCount against ffprobe of the visual file)
    rr = ctx.receipt_path('visual', RENDER_RECEIPT_SUFFIX)
    probe, perr, pcls = (None, 'visual file missing', 2) if not P['visual'].is_file() else probe_video(ctx, P['visual'], env, deadline)
    probs, rinfo = verify_render_receipt(rr, ctx, linfo, probe)
    if perr:
        probs.append(perr)
    inputs = {ctx.rel(p): h(p) for p in (P['visual'], P['episode'], P['captions'], rr, LOCK_FILE) if p.is_file()}
    recs.append(verified_record('render', probs, ctx, rr, inputs, cls=4 if (perr and pcls == 4) else 2,
                                status='missing' if (perr and pcls == 4) else 'stale', extra=rinfo or None))
    summary_info['render'] = rinfo
    # mux receipt (+ the music bed's fetch record)
    mr = ctx.receipt_path('final', '.mux.json')
    probs, minfo = verify_mux_receipt(mr, ctx)
    inputs = {ctx.rel(p): h(p) for p in (P['visual'], P['final'], mr) if p.is_file()}
    music = minfo.pop('music', None)
    recs.append(verified_record('mux', probs, ctx, mr, inputs, extra=dict(minfo, **({'music': music} if music else {})) or None))
    summary_info['mux'] = minfo
    summary_info['music'] = music
    # final video stream == visual video stream
    if P['visual'].is_file() and P['final'].is_file():
        probs, cls, vinfo = verify_mux_video(ctx, env, deadline)
    else:
        probs, cls, vinfo = ['visual or final video missing'], 2, {}
    recs.append(verified_record('mux-video', probs, ctx, P['final'], {ctx.rel(p): h(p) for p in (P['visual'], P['final']) if p.is_file()},
                                cls=cls or 2, status='missing' if cls == 4 else 'stale', extra=vinfo or None))
    # pixel format: yuv420p on both (a re-encode of the final is a quality failure); colour facts of the final go into the receipt
    fprobe, ferr, fcls = (None, 'final file missing', 2) if not P['final'].is_file() else probe_video(ctx, P['final'], env, deadline)
    if ferr or perr:
        err_cls = 4 if 4 in (pcls if perr else 0, fcls if ferr else 0) else 2
        recs.append(verified_record('video-format', [x for x in (perr, ferr) if x], ctx, P['final'], {}, cls=err_cls,
                                    status='missing' if err_cls == 4 else 'stale'))
        summary_info['video'] = None
    else:
        vf = {k: fprobe.get(k) for k in ('pix_fmt', 'color_space', 'color_range')}
        recs.append(verified_record('video-format', verify_video_format(ctx, probe, fprobe), ctx, P['final'],
                                    {ctx.rel(p): h(p) for p in (P['visual'], P['final'])}, cls=1, status='fail', extra=dict(vf)))
        summary_info['video'] = vf
    # final duration
    probs, cls, dinfo = verify_duration(ctx, env, deadline)
    recs.append(verified_record('final-duration', probs, ctx, P['final'], {ctx.rel(P['final']): h(P['final'])} if P['final'].is_file() else {},
                                cls=cls or 2, status='missing' if cls == 4 else 'stale', extra=dinfo or None))
    return recs, relevance_info(ctx), summary_info


def relevance_info(ctx):
    """artifacts/relevance.json is evidence for NOTHING (CF-A67: stock / AI footage is never allowed in unattended mode, the content lint
    fails every footage beat whose origin is not the source).  Its presence and bytes are only recorded, never read as a verdict."""
    rv = ctx.paths['relevance']
    present = rv.is_file()
    return {'path': ctx.rel(rv), 'present': present, 'sha256': ctx.hash(rv) if present else None, 'used_as_evidence': False,
            'note': RELEVANCE_NOTE}


# ---------------------------------------------------------------- outcome
def exit_class(records, extra_classes=()):
    classes = {r['cls'] for r in records if r['status'] != 'pass' and r.get('required', True)} | set(extra_classes)
    for c in (3, 4, 2, 1):          # 3 integrity > 4 infrastructure > 2 stale/bad input > 1 quality
        if c in classes:
            return c
    return 0


def public(rec, with_output):
    return {k: v for k, v in rec.items() if k != 'cls' and (with_output or k != 'output_tail')}


def summary(records):
    lines = []
    for r in records:
        ok = r['status'] == 'pass'
        lines.append('%-5s %-15s %-9s %6.1fs  %s' % ('PASS' if ok else 'FAIL', r['name'], r['kind'], r['seconds'],
                                                     '' if ok else '[%s] %s' % (r['status'], r['reason'])))
        if not ok:
            for i in r.get('issues') or []:
                lines.append('        - %s' % i)
            if r.get('report'):
                lines.append('        report: %s' % r['report'])
            if r.get('command'):         # never shortened or wrapped: it is meant to be copied
                lines.append('        rerun (copy the next line):')
                lines.append(r['command'])
    return '\n'.join(lines)


def tool_versions(tools):
    env = {'HOME': passwd_home(), 'PATH': '/usr/bin:/bin', 'LANG': GATE_LANG}

    def run(cmd):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL, env=env)
            return (r.stdout or r.stderr).strip().splitlines()[0][:200]
        except (OSError, subprocess.TimeoutExpired, IndexError):
            return None
    out = {'python': python_info()}
    for name, flag in (('node', '--version'), ('ffmpeg', '-version'), ('ffprobe', '-version'), ('git', '--version'),
                       ('swift', '--version')):
        path = tools.get(name)
        out[name] = {'path': path, 'version': run([path, flag]) if path else None}
    return out


def git_out(tools, repo_root, *args):
    try:
        r = git_run(tools, repo_root, *args)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def acquire_run_lock(reports_dir):
    """One finalize run per project.  A lock is stale when its pid is not alive (a killed run is retried at once); a lock
    of a live pid is honoured (RUN_LOCK_STALE_SEC only guards against pid reuse)."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    lock = reports_dir / RUN_LOCK_NAME
    for _ in range(3):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            with os.fdopen(fd, 'w') as f:
                f.write(json.dumps({'pid': os.getpid(), 'started_at': now_iso()}))
            return lock
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
                holder, _err = read_json(lock)
            except OSError:
                continue
            pid = holder.get('pid') if isinstance(holder, dict) else None
            if not is_int(pid):
                busy = age < 5                  # just created by a run that has not written its pid yet
            elif pid == os.getpid():
                busy = False
            else:
                busy = pid_alive(pid) and age <= RUN_LOCK_STALE_SEC
            if busy:
                raise BadInput('another finalize run is active (%s, pid %s, %.0fs old); wait for it to finish' % (lock, pid, age))
            remove_quiet(lock)
    raise BadInput('could not acquire %s' % lock)


def release_run_lock(lock):
    holder, _err = read_json(lock)
    if isinstance(holder, dict) and holder.get('pid') not in (None, os.getpid()):
        return                                  # not ours any more
    remove_quiet(lock)


CHECK_FILE = {'path': None, 'started_at': None}      # the check.json of THIS invocation (set once the marker is written)


def certified_pair(deliver, receipt_p):
    """True when <deliver> is a regular file that is exactly the mp4 a delivery receipt of ours vouches for."""
    try:
        if not stat.S_ISREG(os.lstat(deliver).st_mode):
            return False
        data, err = read_json(receipt_p)
        if err or not isinstance(data, dict) or data.get('schema') != RECEIPT_SCHEMA:
            return False
        want = (data.get('delivered') or {}).get('sha256')
        return valid_sha(want) and sha256_file(Path(deliver)) == want.lower()
    except OSError:
        return False


def copy_search_of(records):
    """The content lint's copy_search block of THIS run (information for check.json / the receipt), or None."""
    rec = next((r for r in records if r['name'] == 'content'), None)
    return rec.get('copy_search') if rec else None


def delivered_binding(ctx, deliver, receipt_p):
    """--check certifies ONE file: the delivered mp4.  It must be a regular file (lstat), and three values must agree: the sha256
    finalize computes of it, the sha256 of the renders/final.mp4 the gates checked (ctx.hash: hashed when the gates started, re-checked
    at the end) and the receipt's `delivered.sha256` (a claim, only compared).  The receipt's bound_inputs must name exactly
    RECEIPT_BOUND_KEYS with the CURRENT hashes.  -> record `delivered` (verified; pass, or stale = class 2)."""
    gate = {'name': 'delivered', 'required': True}
    info = {'path': str(deliver), 'sha256': None, 'final_sha256': None, 'receipt': str(receipt_p), 'receipt_sha256': None}
    problems = []
    try:
        if stat.S_ISREG(os.lstat(deliver).st_mode):
            info['sha256'] = sha256_file(deliver)
        else:
            problems.append('%s is not a regular file (a symlink / directory is never certified)' % deliver)
    except OSError as e:
        problems.append('cannot read the delivered file %s: %s' % (deliver, e))
    try:
        info['final_sha256'] = ctx.hash(ctx.paths['final'])
    except OSError as e:
        problems.append('cannot hash %s: %s' % (ctx.rel(ctx.paths['final']), e))
    if info['sha256'] and info['final_sha256'] and info['sha256'] != info['final_sha256']:
        problems.append('the delivered file (sha256 %s...) is not the %s the gates checked (sha256 %s...)'
                        % (info['sha256'][:12], ctx.rel(ctx.paths['final']), info['final_sha256'][:12]))
    data, err = read_json(receipt_p)
    if err or not isinstance(data, dict) or data.get('schema') != RECEIPT_SCHEMA:
        problems.append('no delivery receipt of finalize at %s (%s)' % (receipt_p, err or 'not a %s document' % RECEIPT_SCHEMA))
    else:
        claim = (data.get('delivered') or {}).get('sha256') if isinstance(data.get('delivered'), dict) else None
        info['receipt_sha256'] = claim if valid_sha(claim) else None
        if not valid_sha(claim) or claim.lower() != info['sha256']:
            problems.append('the receipt claims delivered sha256 %s, the delivered file is %s'
                            % (claim if valid_sha(claim) else repr(claim), info['sha256'] or 'unreadable'))
        bound = data.get('bound_inputs')
        if not isinstance(bound, dict) or set(bound) != set(RECEIPT_BOUND_KEYS):
            problems.append('the receipt\'s bound_inputs do not name exactly %s' % ', '.join(RECEIPT_BOUND_KEYS))
        else:
            differ = []
            for k in RECEIPT_BOUND_KEYS:
                want = bound[k].get('sha256') if isinstance(bound[k], dict) else None
                cur = ctx.hash(ctx.paths[k]) if ctx.paths[k].is_file() else None
                if not (valid_sha(want) and cur == want.lower()):
                    differ.append(k)
            if differ:
                problems.append('the receipt\'s bound_inputs differ from the current files: %s (that delivery was made from other '
                                'inputs)' % ', '.join(differ))
    if problems:
        return record(gate, 'stale', 2, '; '.join(problems), kind='verified', extra={'delivered': info})
    return record(gate, 'pass', 0, '', kind='verified', extra={'delivered': info})


def copy_root_problems(args):
    """--check only: the projects-type roots the copy detector must search (MANDATORY; a clean checkout has no projects/ of its
    own, so without them a copied episode would pass).  -> messages (exit 4, before any gate)."""
    roots = getattr(args, 'copy_root', None) or []
    if not roots:
        return ['copy-root: --check needs at least one --copy-root DIR (a projects-type dir whose sub-directories are the other '
                'episodes, e.g. <agent checkout>/projects): without it a copied episode cannot be found']
    return ['copy-root: %s does not exist or is not a directory' % r for r in roots if not Path(r).is_dir()]


def private_tmp(path):
    """A new, empty directory only this user can read (mode 0700); an old one of an earlier run is removed first."""
    path = Path(path)
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(mode=0o700, parents=True)
    os.chmod(path, 0o700)
    return path


def retire_output(deliver, receipt_p):
    """A run that does not deliver must not leave an mp4 at the deliver path that this run did not certify.
    -> (moved_to, previous_delivery_kept, error).  An mp4 + receipt pair of an earlier SUCCESSFUL delivery is never deleted:
    both are renamed to <deliver>.previous[.N] (+ .receipt.json).  Any other regular mp4 is renamed to <deliver>.uncertified[.N];
    a symlink is removed itself (never its target)."""
    try:
        if os.path.islink(deliver):
            os.unlink(deliver)
            return None, False, None
        if not os.path.lexists(deliver) or not stat.S_ISREG(os.lstat(deliver).st_mode):
            return None, False, None
        previous = certified_pair(deliver, receipt_p)
        base, n = str(deliver) + ('.previous' if previous else '.uncertified'), 0
        target = Path(base)
        while os.path.lexists(target) or (previous and os.path.lexists(str(target) + '.receipt.json')):
            n += 1
            target = Path('%s.%d' % (base, n))
        os.rename(deliver, target)
        if previous:
            os.rename(receipt_p, str(target) + '.receipt.json')
        return str(target), previous, None
    except FileNotFoundError:
        return None, False, None
    except OSError as e:
        return None, False, str(e)


def write_check_state(status, started_at, **extra):
    """check.json of this invocation: a `running` marker at the start, a terminal document at the end (or on a signal)."""
    path = CHECK_FILE['path']
    if path is None:
        return
    body = {'schema': CHECK_SCHEMA, 'version': CHECK_VERSION, 'skill': SKILL_DIR.name, 'composition': COMP, 'status': status,
            'pid': os.getpid(), 'started_at': started_at, 'would_deliver': False}
    body.update(extra)
    try:
        write_json_atomic(path, body)
    except OSError as e:
        print('cannot write %s: %s' % (path, e), file=sys.stderr)


def run_lock_held_by_other(reports_dir):
    holder, _err = read_json(Path(reports_dir) / RUN_LOCK_NAME)
    pid = holder.get('pid') if isinstance(holder, dict) else None
    return is_int(pid) and pid != os.getpid() and pid_alive(pid)


def git_toplevel(path, tools, deadline):
    r = git_run(tools, path, 'rev-parse', '--show-toplevel', deadline=deadline)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or 'not a git repository')
    return Path(r.stdout.strip()).resolve()


# ---------------------------------------------------------------- integrity + environment (shared by run() and --preflight)
def check_integrity(args, tools, deadline, state, on_root=None):
    """The skill's gate files against gates.lock.json (skill + mirror + externals) and git.  -> list of problems.  Fills
    state: repo_root, lock_mod, mirror, head, lock_sha."""
    problems = []
    state.update(lock_mod=None, mirror=[])
    try:
        repo_root = git_toplevel(SKILL_DIR, tools, deadline)
        state['repo_root'] = repo_root
        if on_root:
            on_root(repo_root)
        integ_end = time.monotonic() + min(60.0, max(deadline.remaining(), 0.0))
        if args.repo_root and Path(args.repo_root).resolve() != repo_root:
            problems.append('repo-root-mismatch: --repo-root %s is not the skill\'s git top level %s' % (args.repo_root, repo_root))
        if (repo_root / args.composer).resolve() != (repo_root / 'remotion-composer').resolve():
            problems.append('composer-mismatch: --composer %s is not %s' % (args.composer, repo_root / 'remotion-composer'))
        lock_mod = load_sibling('gates_lock')
        lock_mod.GIT_BIN = tools.get('git') or 'git'
        lock_mod.NODE_BIN = tools.get('node') or 'node'
        lock_mod.GIT_TIMEOUT = GIT_TIMEOUT_SEC
        state['lock_mod'] = lock_mod
        parent = SKILL_DIR.parent
        if parent.name == 'skills' and parent.parent.name in ('.claude', '.agents'):
            other = '.agents' if parent.parent.name == '.claude' else '.claude'
            state['mirror'] = [parent.parent.parent / other / 'skills' / SKILL_DIR.name]
        problems += lock_mod.verify(SKILL_DIR, repo_root, state['mirror'], None, integ_end)
        state['head'] = lock_mod.git_head(repo_root, integ_end)
        state['lock_sha'] = sha256_file(LOCK_FILE) if LOCK_FILE.is_file() else None
    except Terminated:
        raise
    except Exception as e:  # noqa: BLE001 - fail closed on anything
        problems.append('git-unavailable: %s' % e if 'git' in str(e).lower() else 'integrity-check-error: %s' % e)
    return problems


def asr_env_check(deep=False):
    """`word-timing` environment check: `/bin/bash asr_run.sh asr_transcribe.py --check` (a delivery / --preflight) or `--check
    --deep` (finalize --check: also the ~3 GB weights content) under asr_env().  The launcher verifies interpreter + stdlib + venv
    against asr_venv.manifest first; a missing launcher / venv / manifest is FAIL with the setup hint, and nothing is ever installed.
    -> (name, 'ok' | 'FAIL', detail with the seconds it took)."""
    bad = launcher_problem()
    if bad:
        return 'word-timing', 'FAIL', bad
    cmd = asr_cmd('asr_transcribe.py', '--check', *(['--deep'] if deep else []))
    label = 'asr_run.sh asr_transcribe.py --check%s' % (' --deep' if deep else '')
    t0 = time.monotonic()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=ASR_ENV_CHECK_LIMIT, stdin=subprocess.DEVNULL, env=asr_env(),
                           cwd=str(SCRIPTS_DIR))
    except subprocess.TimeoutExpired:
        return 'word-timing', 'FAIL', '%s did not finish within %d s' % (label, ASR_ENV_CHECK_LIMIT)
    except OSError as e:
        return 'word-timing', 'FAIL', 'cannot run %s: %s' % (label, e)
    secs = time.monotonic() - t0
    if r.returncode == 0:
        return 'word-timing', 'ok', '%s (%.1f s): %s' % (label, secs, (r.stdout.strip().splitlines() or ['ok'])[-1][:300])
    err = ' | '.join(l.strip() for l in r.stderr.strip().splitlines()[-4:]) or 'no message'
    hint = '' if 'setup_asr_venv.sh' in err else ' — %s' % (ASR_SETUP_HINT % SKILL_DIR)
    return 'word-timing', 'FAIL', '%s exited %d: %s (nothing is downloaded or installed)%s' % (label, r.returncode, err[:700], hint)


PY_MODULES_PROBE = ("import sys;sys.path+=[p for p in sys.argv[1].split(':') if p];bad=[]\n"
                    "for m in sys.argv[2:]:\n"
                    " try: __import__(m)\n"
                    " except Exception as e: bad.append('%s (%s)' % (m, (str(e).splitlines() or [type(e).__name__])[0][:80]))\n"
                    "print('; '.join(bad));sys.exit(1 if bad else 0)")


def python_modules_check(tools):
    """PY_MODULES imported by `<this python> -I -S -B` with this interpreter's site-packages appended (= a gate).  -> (status, detail)"""
    if sys.flags.no_site:
        return 'FAIL', ('finalize runs with -S: its venv cannot be found that way (sys.prefix is the base interpreter\'s); run it '
                        'with -I but without -S, the gates themselves run -I -S')
    cmd = [sys.executable, *GATE_PY_FLAGS, '-c', PY_MODULES_PROBE, ':'.join(gate_site_dirs()), *PY_MODULES]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
                           env={'HOME': passwd_home(), 'PATH': tool_path_env(tools), 'LANG': GATE_LANG}, cwd='/')
    except (OSError, subprocess.TimeoutExpired) as e:
        return 'FAIL', 'cannot run %s: %s' % (sys.executable, e)
    if r.returncode != 0:
        return 'FAIL', ('cannot import %s with %s -I -S + its site-packages: run finalize with the repo\'s .venv python'
                        % ((r.stdout.strip() or r.stderr.strip()[-200:]), os.path.realpath(sys.executable)))
    return 'ok', '%s importable with %s -I -S' % (', '.join(PY_MODULES), os.path.realpath(sys.executable))


def environment_checks(repo_root, composer_arg, tools, lock_problems, versions=False, preflight_only=True, public=None, deep=False):
    """Fail-closed environment checks, shared by a real run, `--check` and `finalize.py --preflight`.  Never raises, never touches
    the network, never loads a model.  -> [{name, status: ok|FAIL|skip, detail, cls}] in the order of the preflight listing.
    lock_problems: the problems check_integrity() found (None = not checked, an empty list = the lock verified).
    preflight_only: `music-library`, the ONLY intentional difference between `--preflight` (True) and a real run / `--check`
    (False; the delivery only needs the bed already in the project, not the library file).  `word-timing` (asr_run.sh
    asr_transcribe.py --check) runs in EVERY mode: a delivery re-derives the pages through the launcher and --check transcribes;
    deep=True (finalize --check only) adds --deep (the weights content).
    public: the public/ directory the run reads (the fonts check looks there): <composer>/public, or the agent's --public-root in the
    clean-checkout check (fonts are not tracked by git, a clean checkout has none of its own)."""
    out = []

    def add(name, status, detail, cls=0):
        out.append({'name': name, 'status': status, 'detail': detail, 'cls': cls if status == 'FAIL' else 0})

    # 1. tools (same resolver as the real run)
    vers = tool_versions(tools) if versions else {}
    for n in REQUIRED_TOOLS:
        if tools.get(n):
            v = (vers.get(n) or {}).get('version')
            add('tool-' + n, 'ok', '%s%s' % (tools[n], ' (%s)' % v if v else ''))
        else:
            add('tool-' + n, 'FAIL', 'not found at %s ($PATH is never searched)%s' % (', '.join(TOOL_CANDIDATES[n]), ' (macOS Vision OCR of the frames gate: no OCR = no watermark check)' if n == 'swift' else ''), 4)
    # 2. python modules, imported exactly the way a gate imports them: `<this python> -I -S -B` + gate_site_dirs() appended
    status, detail = python_modules_check(tools)
    add('python-modules', status, '%s (sys.prefix %s, site dirs %s)' % (detail, sys.prefix, ':'.join(gate_site_dirs()) or 'none'), 4)
    # 3. composer node_modules
    composer = (Path(repo_root) / composer_arg).resolve()
    nm = composer / 'node_modules'
    if not nm.is_dir():
        add('composer-node-modules', 'FAIL', '%s does not exist (the render / layout scripts load %s from it; never install packages '
            'during a run)' % (nm, ', '.join(COMPOSER_PACKAGES)), 4)
    else:
        absent = [n for n in COMPOSER_PACKAGES if not (nm / n / 'package.json').is_file()]
        add('composer-node-modules', 'FAIL' if absent else 'ok',
            ('%s lacks %s' % (nm, ', '.join(absent))) if absent else '%s has %s' % (nm, ', '.join(COMPOSER_PACKAGES)), 4)
    # 4. fonts the engine loads
    pub = Path(public) if public is not None else composer / 'public'
    absent = [f for f in FONT_FILES if not (pub / f).is_file() or (pub / f).stat().st_size == 0]
    add('fonts', 'FAIL' if absent else 'ok',
        ('missing or empty under %s: %s (the render loads them blocking; never download fonts during a run)' % (pub, ', '.join(absent)))
        if absent else '%s under %s' % (', '.join(FONT_FILES), pub), 4)
    # 5. gate lock (verified by check_integrity)
    if lock_problems is None:
        add('gate-lock', 'skip', 'not checked')
    elif lock_problems:
        tool_only = all(p.startswith('tool-missing:') for p in lock_problems)
        add('gate-lock', 'FAIL', ' | '.join(lock_problems[:4]) + (' | ...(%d more)' % (len(lock_problems) - 4) if len(lock_problems) > 4 else ''),
            4 if tool_only else 3)
    else:
        add('gate-lock', 'ok', 'lock present; skill, mirror and external files match it and git HEAD')
    # 6. the word-timing chain, EVERY mode (a delivery runs asr_align.py through the launcher, --check transcribes):
    #    `/bin/bash asr_run.sh asr_transcribe.py --check [--deep]` (manifest, model cache, pins; loads nothing, downloads nothing)
    name, status, detail = asr_env_check(deep)
    add(name, status, detail, 4)
    if not preflight_only:
        return out
    # 7. approved local music library (--preflight only): the online source is refused at the time of writing, so a usable
    #    library is what every run relies on; failing here is cheaper than at the music step an hour in
    try:
        lib = load_sibling('music_library')
        manifest = lib.load_manifest(MUSIC_MANIFEST)
        tracks = manifest.get('tracks') or []
        if not tracks:
            add('music-library', 'FAIL', 'music library is empty: no approved track in scripts/music_library.json', 4)
        else:
            res = lib.check_library(Path(repo_root), manifest)
            usable = [r for r in res if r.get('status') == 'ok']
            if usable:
                add('music-library', 'ok', '%d approved track(s) usable, first: %s' % (len(usable), usable[0].get('file')))
            else:
                add('music-library', 'FAIL', 'no approved track is usable: %s (library dir %s)'
                    % (', '.join('%s: %s' % (r.get('file'), r.get('status')) for r in res), lib.library_dir(Path(repo_root))), 4)
    except Exception as e:  # noqa: BLE001
        add('music-library', 'FAIL', 'music library cannot be used: %s' % (str(e) or type(e).__name__), 4)
    return out


def preflight(args):
    """`finalize.py --preflight`: print one line per check; exit 0 all ok, 3 integrity, 4 tool / dependency missing.
    A real run and `--check` execute the same environment_checks(), `word-timing` (asr_run.sh asr_transcribe.py --check; --check
    adds --deep) included; only `music-library` is preflight-only, on purpose."""
    deadline = Deadline(TOTAL_BUDGET_SEC)
    STOP.clear()
    tools = resolve_tools()
    state = {'repo_root': None}
    args.check = False
    problems = check_integrity(args, tools, deadline, state)
    repo_root = state['repo_root'] or Path(args.repo_root or '.').resolve()
    results = environment_checks(repo_root, args.composer, tools, problems, versions=True)
    for r in results:
        print('PREFLIGHT %s %s: %s' % (r['status'], r['name'], r['detail']))
    failed = [r for r in results if r['status'] == 'FAIL']
    code = 3 if any(r['cls'] == 3 for r in failed) else 4 if failed else 0
    print('PREFLIGHT PASS (exit 0): %d checks ok' % sum(1 for r in results if r['status'] == 'ok') if code == 0 else
          'PREFLIGHT FAIL (exit %d): %s' % (code, ', '.join(r['name'] for r in failed)))
    return code


# ---------------------------------------------------------------- main
def run(args):
    t_start, started = time.monotonic(), now_iso()
    budget = CHECK_TOTAL_BUDGET_SEC if args.check else TOTAL_BUDGET_SEC
    deadline = Deadline(budget)
    STOP.clear()
    CHECK_FILE.update(path=None, started_at=started)
    tools = resolve_tools()
    # deliver path: resolve only the parent directory, then lstat BEFORE anything else runs
    lexical = Path(os.path.abspath(args.deliver))
    deliver = lexical.parent.resolve() / lexical.name
    partial, receipt_p, failed_p = (Path(str(deliver) + s) for s in ('.partial', '.receipt.json', '.FAILED.json'))
    receipt_tmp = Path(str(receipt_p) + '.tmp')
    deliver_problem, preexisting = None, False
    try:
        st = os.lstat(deliver)
        if stat.S_ISREG(st.st_mode):
            preexisting = True
        else:
            deliver_problem = '%s exists and is a %s; refusing to deliver there' % (
                deliver, 'symlink' if stat.S_ISLNK(st.st_mode) else 'directory' if stat.S_ISDIR(st.st_mode) else 'special file')
    except FileNotFoundError:
        if args.check:              # --check certifies the delivered file: no file, nothing to certify
            deliver_problem = 'nothing to certify: the delivered file %s does not exist (--check binds its result to it)' % deliver
    except OSError as e:
        deliver_problem = 'cannot stat %s: %s' % (deliver, e)

    state = {'moved': None, 'check_path': None, 'lock': None, 'ctx': None, 'lock_sha': None, 'head': None, 'repo_root': None, 'collision': False,
             'external': False, 'work_dir': None, 'work_dir_error': None, 'certified_sha': None}

    def remaining_msg(phase):
        return 'time budget (%ds) exhausted during phase "%s"' % (budget, phase)

    def ensure_work_dir(root):
        """The clean-checkout check's output directory: --work-dir (must be empty or new, never inside the project or the public
        root -- checked BEFORE anything is created) or a new temp dir.  -> path or None (state['work_dir_error'] says why)"""
        if state['work_dir'] is not None or state['work_dir_error']:
            return state['work_dir']
        try:
            if args.work_dir:
                wd = Path(os.path.abspath(args.work_dir))
                proj = project_dir(args, root) if (root is not None or Path(args.project).is_absolute()) else None
                for name, d in (('project', proj), ('public root', Path(args.public_root).resolve() if args.public_root else None)):
                    if d is not None and inside(wd, d):
                        state['work_dir_error'] = '--work-dir %s is inside the %s %s: the check must not write there' % (wd, name, d)
                        return None
                if os.path.lexists(wd) and (not wd.is_dir() or wd.is_symlink() or any(wd.iterdir())):
                    state['work_dir_error'] = ('--work-dir %s must be an empty directory or not exist yet (a result of an earlier run must '
                                               'never be mistaken for this one)' % wd)
                    return None
                wd.mkdir(parents=True, exist_ok=True)
            else:
                wd = Path(tempfile.mkdtemp(prefix='yt-news-v4-check-'))
        except OSError as e:
            state['work_dir_error'] = 'cannot create the work dir: %s' % e
            return None
        state['work_dir'] = wd.resolve()
        return state['work_dir']

    def may_touch_deliver():
        """The deliver path may be cleaned up / moved aside only when it is certainly not an input of the run."""
        if state['collision']:
            return False
        if state['ctx'] is None and state['repo_root'] is not None:      # the context could not be built: be careful
            proj = Path(args.project)
            proj = proj if proj.is_absolute() else state['repo_root'] / proj
            if any(inside(deliver, d) for d in (proj, state['repo_root'] / 'remotion-composer' / 'public')):
                return False
        return True

    def finish(code, records, reasons, integrity=(), relevance=None, hint=None):
        ctx = state['ctx']
        body = {'skill': SKILL_DIR.name, 'composition': COMP, 'exit_code': code, 'started_at': started,
                'finished_at': now_iso(), 'seconds': round(time.monotonic() - t_start, 2),
                'git_head': state['head'], 'lock_sha256': state['lock_sha']}
        if args.check:
            # running out of time is exit 4 and must never read like a content failure: `retry` tells the outside system so
            timed_out = code == 4 and (any(r.get('status') == 'timeout' for r in records) or any('time budget' in x for x in reasons))
            body.update(retry='when-idle' if timed_out else None)
            body.update(schema=CHECK_SCHEMA, version=CHECK_VERSION, status='finished', pid=os.getpid(), would_deliver=(code == 0),
                        reasons=reasons, integrity_problems=list(integrity), relevance=relevance,
                        mode='clean-checkout' if state['external'] else 'in-repo', work_dir=str(state['work_dir']) if state['work_dir'] else None,
                        project=str(ctx.project) if ctx else None, public_root=str(ctx.public) if ctx else None,
                        delivered_path=str(deliver),
                        certified_final_sha256=state['certified_sha'] if code == 0 else None,
                        copy_roots=[str(Path(r).resolve()) for r in (args.copy_root or [])], copy_search=copy_search_of(records),
                        tools=tool_versions(tools), certification=CERTIFICATION, gates=[public(r, True) for r in records])
            rdir = None
            if state['work_dir_error']:
                pass                                    # an unusable work dir: nothing is written anywhere
            elif ctx is not None:
                rdir = ctx.reports
            elif state['external'] or (state['repo_root'] is None and (args.public_root or args.work_dir)):
                state['external'] = True
                rdir = ensure_work_dir(state['repo_root'])
                body.update(mode='clean-checkout', work_dir=str(rdir) if rdir else None)
            elif state['repo_root'] is not None and not linked_reports(args, state['repo_root']):   # never through a symlink (B9)
                proj = Path(args.project)
                rdir = (proj if proj.is_absolute() else state['repo_root'] / proj) / DEFAULT_PATHS['reports']
            if rdir is not None:
                try:
                    write_json_atomic(rdir / 'check.json', body)
                    state['check_path'] = rdir / 'check.json'
                except OSError as e:
                    print('cannot write check.json: %s' % e, file=sys.stderr)
        elif code != 0:
            previous_kept = False
            if may_touch_deliver():
                moved, previous_kept, err = retire_output(deliver, receipt_p)
                state['moved'] = moved
                if err:
                    reasons = reasons + ['could not move the pre-existing output aside: %s' % err]
                for p in (receipt_p, receipt_tmp, partial):
                    remove_quiet(p)
            body.update(schema=FAILED_SCHEMA, version=1, reasons=reasons, integrity_problems=list(integrity),
                        preexisting_output_not_certified=preexisting and not previous_kept,
                        preexisting_output_moved_to=state['moved'], previous_delivery_preserved=previous_kept,
                        deliver_path_problem=deliver_problem, gates=[public(r, True) for r in records])
            try:
                write_json_atomic(failed_p, body)
            except OSError as e:
                print('cannot write %s: %s' % (failed_p, e), file=sys.stderr)
        lines = [summary(records)] if records else []
        if code == 0:
            lines.append('CHECK PASS — nothing delivered' if args.check else 'FINALIZE PASS (exit 0)')
        else:
            lines.append('%s FAIL (exit %d): %s' % ('CHECK' if args.check else 'FINALIZE', code, ' | '.join(reasons[:6])))
            if hint:
                lines.append(hint)
            if not args.check:
                lines.append('  -> see %s' % failed_p)
        if args.check:
            cp = state['check_path']
            lines.append('CHECK RESULT FILE: %s' % (cp if cp else 'not written (%s)' % (
                state['work_dir_error'] or 'the repository or project could not be resolved')))
            if state['external'] and state['work_dir']:
                lines.append('CHECK WORK DIR: %s (the fresh reports of this check; nothing was written into the project or the public root)'
                             % state['work_dir'])
            lines.append('--check never writes %s; the result of this run is only in the file above' % failed_p)
        print('\n'.join(lines))
        return code

    # ---- 1. integrity (gate files); repo root is derived from the skill dir, never from the cwd
    def on_root(root):
        if args.check and external_check(args, root):      # clean-checkout check: everything this run writes goes to the work dir
            state['external'] = True
            wd = ensure_work_dir(root)
            if wd is not None:
                CHECK_FILE['path'] = wd / 'check.json'
                write_check_state('running', started, mode='clean-checkout', work_dir=str(wd))
            return
        if args.check and not linked_reports(args, root):    # (a symlinked project path is refused later; never written through)
            proj0 = Path(args.project)
            rdir0 = (proj0 if proj0.is_absolute() else root / proj0) / DEFAULT_PATHS['reports']
            if not run_lock_held_by_other(rdir0):          # never overwrite the file of a run that is still going
                CHECK_FILE['path'] = rdir0 / 'check.json'
                write_check_state('running', started)

    problems = check_integrity(args, tools, deadline, state, on_root)
    repo_root = state['repo_root'] or Path(args.repo_root or '.').resolve()
    lock_mod, mirror = state['lock_mod'], state['mirror']
    if problems:
        if deadline.expired():
            return finish(4, [], [remaining_msg('integrity')] + ['integrity: %s' % p for p in problems[:5]], problems)
        if all(p.startswith('tool-missing:') for p in problems):      # node / gate_integrity.mjs cannot list the required files
            return finish(4, [], ['integrity: %s' % p for p in problems[:20]], problems)
        return finish(3, [], ['integrity: %s' % p for p in problems[:20]], problems, hint=RESTORE_HINT)
    if deadline.expired():
        return finish(4, [], [remaining_msg('integrity')])
    if state['work_dir_error']:
        return finish(2, [], ['bad input: %s' % state['work_dir_error']])
    bad_env = [r for r in environment_checks(repo_root, args.composer, tools, [], preflight_only=False, public=public_dir(args, repo_root),
                                             deep=bool(args.check))
               if r['status'] == 'FAIL']
    bad_roots = copy_root_problems(args) if args.check else []
    if bad_env or bad_roots:         # the very checks `finalize.py --preflight` prints: they can never disagree
        return finish(4, [], ['environment: %s: %s (nothing was run)' % (r['name'], r['detail']) for r in bad_env[:6]]
                      + ['environment: %s (nothing was run)' % m for m in bad_roots])

    # ---- context, run lock, deliver path (class 2 problems; nothing has run yet)
    try:
        ctx = Ctx(args, repo_root, deliver, tools, work_dir=state['work_dir'] if state['external'] else None)
        state['ctx'] = ctx
    except (BadInput, OSError) as e:
        return finish(2, [], ['bad input: %s' % e])
    collision = ctx.deliver_collision()
    if collision is None:
        for d in (ctx.public / (ctx.ep['asset_dir'] or '\0'), ctx.project / 'assets', ctx.project / 'artifacts'):
            if inside(deliver, d):
                collision = '--deliver is inside an input directory of this run: %s' % ctx.rel(d)
                break
    if collision:
        state['collision'] = True
        return finish(2, [], ['bad input: ' + collision])
    try:
        state['lock'] = acquire_run_lock(ctx.reports)
    except (BadInput, OSError) as e:
        if args.check and CHECK_FILE['path'] is not None:      # our own `running` marker must not outlive this invocation
            write_check_state('finished', started, exit_code=2, reasons=['bad input: %s' % e])
        print('FINALIZE FAIL (exit 2): %s' % e)       # do not touch anything the other run may be using
        return 2
    try:
        if deliver_problem:
            return finish(2, [], ['bad input: ' + deliver_problem])
        if not args.check:
            # no stale failure / partial of an earlier attempt may sit beside the deliver path while this one runs.  A receipt is
            # kept ONLY when it is still the receipt of the mp4 beside it (a certified earlier delivery is never deleted here;
            # it is replaced when this run delivers, or renamed to <deliver>.previous when it does not).
            for p in (receipt_tmp, failed_p, partial):
                remove_quiet(p)
            if not certified_pair(deliver, receipt_p):
                remove_quiet(receipt_p)
        purge_pycache(SKILL_DIR)
        ctx.tmp = private_tmp(ctx.reports / 'gate-tmp')
        env = gate_env(tools, ctx.tmp)

        # ---- 2. fresh gates (parallel, bounded by the invocation deadline minus the post-verification reserve)
        gate_end = deadline.end - POST_RESERVE_SEC
        prepared = []
        for g in active_gates(args.check):
            _argv, _report, in_paths, _p = build_command(g, ctx)
            prepared.append((g, {ctx.rel(p): ctx.hash(p) for p in in_paths}))
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)
        # --check-only gates (the re-transcription, minutes long) run in their OWN lane, in parallel with every other gate
        lane = concurrent.futures.ThreadPoolExecutor(max_workers=1) if any(g.get('check_only') for g, _ in prepared) else None
        try:
            futs = {}
            for g, inp in prepared:
                if g.get('check_only'):
                    futs[g['name']] = lane.submit(run_gate, g, ctx, inp, gate_end, env)
            for g, inp in prepared:
                if not g.get('after') and not g.get('check_only'):
                    futs[g['name']] = ex.submit(run_gate, g, ctx, inp, gate_end, env)
            for g, inp in prepared:      # dependent gates start once the gates they wait for have finished
                if g.get('after'):
                    deps = {name: futs[name].result() for name in g['after']}
                    futs[g['name']] = ex.submit(run_gate, g, ctx, inp, gate_end, env, deps)
            records = [futs[g['name']].result() for g, _ in prepared]
        finally:
            ex.shutdown(wait=False, cancel_futures=True)      # nothing queued may start after a cancellation
            if lane is not None:
                lane.shutdown(wait=False, cancel_futures=True)

        # ---- 3. verified reports
        if deadline.expired():
            return finish(4, records, [remaining_msg('post-verification')])
        vrecs, relevance, vinfo = run_verified(ctx, env, deadline)
        records += vrecs
        if args.check:                  # the result is bound to the delivered file (a check of the project alone certifies nothing)
            records.append(delivered_binding(ctx, deliver, receipt_p))

        # ---- 4. result
        reasons = ['%s: %s' % (r['name'], r['reason']) for r in records if r['status'] != 'pass' and r.get('required', True)]
        code = exit_class(records)
        changed = ctx.hash.recheck()
        if changed:
            code = code if code in (3, 4) else max(code, 2)
            reasons.append('input changed while finalize was running: ' + ', '.join(ctx.rel(c) for c in changed))
        if deadline.remaining() < 1:
            return finish(4, records, [remaining_msg('integrity re-check')] + reasons[:5], (), relevance)
        try:
            again = lock_mod.verify(SKILL_DIR, repo_root, mirror, None, time.monotonic() + min(30.0, deadline.remaining()))
        except Terminated:
            raise
        except Exception as e:  # noqa: BLE001
            again = ['integrity-check-error: %s' % e]
        if again:
            return finish(3, records, ['integrity (re-check before delivery): %s' % p for p in again[:20]], again,
                          relevance, hint=RESTORE_HINT)
        if args.check and code == 0:
            # re-hash both files right before the pass: the certified sha256 is the one of the file as it is NOW
            d = next(r for r in records if r['name'] == 'delivered')['delivered']
            now = []
            for p in (deliver, ctx.paths['final']):
                try:
                    now.append(sha256_file(p) if stat.S_ISREG(os.lstat(p).st_mode) else None)
                except OSError:
                    now.append(None)
            if now != [d['sha256'], d['sha256']]:
                code = 2
                reasons.append('delivered: the delivered file or %s changed during the check (sha256 now %s / %s, checked %s)'
                               % (ctx.rel(ctx.paths['final']), now[0], now[1], d['sha256']))
            else:
                state['certified_sha'] = now[0]
        if code != 0 or args.check:
            return finish(code, records, reasons, (), relevance)
        if deadline.remaining() < DELIVER_RESERVE_SEC:
            return finish(4, records, ['%s (only %.0fs left, %ds are needed to copy and verify the delivery)'
                                       % (remaining_msg('deliver'), max(deadline.remaining(), 0), DELIVER_RESERVE_SEC)], (), relevance)
        return deliver_now(ctx, args, records, relevance, vinfo, state, deliver, partial, receipt_p, receipt_tmp,
                           t_start, started, finish, lexical, tools)
    finally:
        if state['ctx'] is not None and state['ctx'].tmp is not None:
            shutil.rmtree(state['ctx'].tmp, ignore_errors=True)
        if state['lock']:
            release_run_lock(state['lock'])


def input_hashes(ctx):
    """The primary inputs and the agent's statements a delivery rests on, hashed now (receipt key `input_hashes`): the avatar the
    episode uses, script.txt, the avatar SRT, the source transcript / video, the cuts file, visual_evidence.json (a claim of the
    agent, see SELF_REPORTED) and the frames report THIS run wrote.  An absent optional file is {path, sha256: null}."""
    out = {}
    for key, path in (('avatar', ctx.avatar), ('script', ctx.paths['script']), ('srt', ctx.paths['srt']),
                      ('source_transcript', ctx.paths['source_transcript']), ('source_video', ctx.paths['source_video']),
                      ('cuts', ctx.paths['cuts']), ('visual_evidence', ctx.paths['evidence']),
                      ('frames_report', gate_report_path('frames', ctx))):
        present = path is not None and Path(path).is_file()
        out[key] = {'path': ctx.rel(path) if path is not None else None, 'sha256': ctx.hash(path) if present else None}
    return out


def music_presence_receipt(records):
    rec = next((r for r in records if r['name'] == 'music-presence'), None)
    if rec is None or rec['status'] != 'pass':
        return None
    window = rec.get('window') or [None, None]
    return {'mean_db': rec.get('mean_db'), 'window_start': window[0], 'window_end': window[1]}


def deliver_now(ctx, args, records, relevance, vinfo, state, deliver, partial, receipt_p, receipt_tmp, t_start, started,
                finish, lexical, tools):
    """Order: copy -> partial; receipt -> its temp name; receipt renamed; the mp4 is renamed LAST, so an mp4 at the deliver
    path always has its receipt."""
    final = ctx.paths['final']
    final_sha = ctx.hash(final)
    replaced = False
    try:
        deliver.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(final, partial)
        if sha256_file(partial) != final_sha:
            raise OSError('copy verification failed (sha256 mismatch)')
        receipt = {'schema': RECEIPT_SCHEMA, 'version': RECEIPT_VERSION, 'skill': SKILL_DIR.name, 'composition': COMP,
                   'certification': CERTIFICATION,
                   'self_reported': list(SELF_REPORTED),
                   'delivered': {'path': str(deliver), 'sha256': final_sha, 'bytes': partial.stat().st_size},
                   'requested_deliver_path': str(lexical),
                   'git_head': state['head'], 'lock_sha256': state['lock_sha'],
                   'finalize_sha256': sha256_file(Path(__file__).resolve()),
                   'skill_tree': git_out(tools, ctx.repo_root, 'rev-parse', 'HEAD:' + SKILL_DIR.relative_to(ctx.repo_root).as_posix()),
                   'tools': tool_versions(tools),
                   'bound_inputs': {k: {'path': ctx.rel(ctx.paths[k]), 'sha256': ctx.hash(ctx.paths[k])} for k in RECEIPT_BOUND_KEYS},
                   'copy_roots': [str(r) for r in ctx.copy_roots], 'copy_search': copy_search_of(records),
                   'word_timing': ctx.word_timing,
                   'layout': vinfo.get('layout'), 'render': vinfo.get('render'), 'mux': vinfo.get('mux'),
                   'music': vinfo.get('music'), 'video': vinfo.get('video'),
                   'music_presence': music_presence_receipt(records),
                   'input_hashes': input_hashes(ctx),
                   'manifest_sha256': ctx.manifest_sha,
                   'gates': [public(r, False) for r in records], 'relevance': relevance,
                   'started_at': started, 'finished_at': now_iso(), 'seconds': round(time.monotonic() - t_start, 2)}
        receipt_tmp.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n')
        remove_quiet(deliver)               # a previous (uncertified) mp4 is never left beside the new receipt
        os.replace(receipt_tmp, receipt_p)
        os.replace(partial, deliver)        # LAST
        replaced = True
        if sha256_file(deliver) != final_sha:
            remove_quiet(deliver)
            remove_quiet(receipt_p)
            raise OSError('delivered file sha256 mismatch after replace')
    except OSError as e:
        for p in (partial, receipt_tmp, receipt_p) + ((deliver,) if replaced else ()):
            remove_quiet(p)
        return finish(2, records, ['delivery failed: %s' % e], (), relevance)
    print(summary(records))
    print('FINALIZE PASS (exit 0): delivered %s sha256=%s' % (deliver, final_sha[:12]))
    return 0


def crash(args, exc):
    """Any unexpected exception becomes exit 4 + FAILED.json (never a bare traceback with exit 1).  A SIGTERM / SIGINT
    (Terminated) is an interruption, not an internal error: it gets its own message and `status: terminated` in the file."""
    STOP.set()
    kill_all()
    interrupted = isinstance(exc, Terminated)
    text = ''.join(traceback.format_exception_only(type(exc), exc)).strip()
    if interrupted:
        what = str(exc) or 'terminated'
        reasons = ['interrupted: %s; nothing was delivered' % what]
        message = 'FINALIZE INTERRUPTED (exit 4): %s \u2014 nothing was delivered; re-run the same command' % what
    else:
        reasons = ['internal error: %s' % text]
        message = 'FINALIZE FAIL (exit 4): %s' % reasons[0]
    status = {'status': 'terminated', 'signal': exc.signum} if interrupted else {'status': 'crashed'}
    try:
        lexical = Path(os.path.abspath(args.deliver))
        deliver = lexical.parent.resolve() / lexical.name
        if args.check:
            write_check_state(status['status'], CHECK_FILE['started_at'], exit_code=4, reasons=reasons,
                              **({'signal': exc.signum} if interrupted else {}))
        else:
            receipt_p = str(deliver) + '.receipt.json'
            body = {'schema': FAILED_SCHEMA, 'version': 1, 'skill': SKILL_DIR.name, 'composition': COMP, 'exit_code': 4,
                    'reasons': reasons, 'gates': [], 'finished_at': now_iso(),
                    'preexisting_output_not_certified': deliver.is_file(), 'preexisting_output_moved_to': None,
                    'previous_delivery_preserved': False, **status}
            if not interrupted:
                body['traceback'] = tail(traceback.format_exc(), 3000)
            moved, kept, err = retire_output(deliver, receipt_p)
            body.update(preexisting_output_moved_to=moved, previous_delivery_preserved=kept)
            if kept:
                body['preexisting_output_not_certified'] = False
            if err:
                body['reasons'] = reasons + ['could not move the pre-existing output aside: %s' % err]
            for s_ in ('.receipt.json', '.receipt.json.tmp', '.partial'):
                remove_quiet(str(deliver) + s_)
            write_json_atomic(str(deliver) + '.FAILED.json', body)
    except Exception:  # noqa: BLE001
        pass
    print(message)
    return 4


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
    ap.add_argument('--project')
    ap.add_argument('--deliver')
    ap.add_argument('--preflight', action='store_true',
                    help='check the environment (tools, python modules, composer node_modules, fonts, gate lock, local whisper) and exit; '
                         'needs neither --project nor --deliver')
    ap.add_argument('--composer', default='remotion-composer', help='must be <repo root>/remotion-composer')
    ap.add_argument('--repo-root', default=None, help='optional; must equal the skill\'s git top level')
    ap.add_argument('--manifest')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--public-root', default=None,
                    help='--check only: the agent\'s remotion-composer/public (episode media + fonts); code, lock, engine and '
                         'node_modules still come from this checkout')
    ap.add_argument('--copy-root', action='append', default=None, metavar='DIR',
                    help='--check only, MANDATORY there (repeatable): a projects-type dir whose sub-directories are other episodes; '
                         'the content lint compares this episode against them (a delivery uses the project\'s own parent dir)')
    ap.add_argument('--work-dir', default=None,
                    help='--check only: where the fresh reports and check.json go (empty or new; default: a new temp dir, printed '
                         'at the end); nothing is written into the project or the public root')
    args = ap.parse_args(argv)
    if args.preflight:
        if args.project or args.deliver or args.check or args.manifest or args.public_root or args.work_dir or args.copy_root:
            ap.error('--preflight takes only --composer / --repo-root')
    elif not (args.project and args.deliver):
        ap.error('--project and --deliver are required (unless --preflight)')
    elif args.copy_root and not args.check:
        ap.error('--copy-root is a --check-only option (the outside system names the projects to compare against); a delivery '
                 'compares against the project\'s own parent dir')
    elif (args.public_root or args.work_dir) and not args.check:
        ap.error('--public-root / --work-dir are --check-only options: a real delivery reads the media of this repository and writes '
                 'its reports into the project')
    old = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            old[sig] = signal.signal(sig, _on_signal)
    try:
        return preflight(args) if args.preflight else run(args)
    except Exception as e:  # noqa: BLE001
        if args.preflight:
            print('PREFLIGHT FAIL (exit 4): %s' % ('interrupted: %s' % e if isinstance(e, Terminated) else 'internal error: %s' % e))
            return 4
        return crash(args, e)
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    sys.exit(main())
