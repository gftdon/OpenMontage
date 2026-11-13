#!/bin/bash
# word_timing.sh — offline word timing from the REAL audio, as a RESUMABLE, DETACHED job so it is safe under a
# ~10-minute command limit (one deterministic whisper pass over an 11-minute clip takes ~2.5-3 min, a repair rung less):
#   1. asr_transcribe.py  deterministic whisper pass + FIXED repair ladder (R0 full pass, R1 re-decode of defect regions)
#                         -> raw_asr.json (exit 5 = still defective after the ladder)
#   2. asr_align.py       the exact script aligned onto those word times -> caption_pages.json
# Both are started ONLY through asr_run.sh (the launcher): it verifies, from outside python and with root-owned tools only, the
# Cellar python binary, the stdlib and every file of the V4 ASR venv (<passwd home>/.cache/yt-news-v4/asr-venv, built by a human
# with setup_asr_venv.sh) against asr_venv.manifest, then execs that python directly as
#   env -i HOME=<passwd home> PATH=<ffmpeg dir>:/usr/bin:/bin LANG=en_US.UTF-8 TMPDIR=/var/empty  python -I -S -B -X pycache_prefix=/var/empty
# i.e. isolated (no PYTHON* variables, nothing from the cwd), no site / .pth / sitecustomize, no bytecode is ever read or written
# (/var/empty is root-owned and empty, so every module is compiled from its source: a planted __pycache__/*.pyc cannot replace
# the tools), and nothing of the caller's environment ($HOME, $PATH, DYLD_*, HF_*, ...) reaches the decoder.  The home directory
# comes from the passwd entry (never $HOME) and ffmpeg is the first executable of /opt/homebrew/bin, /usr/local/bin, /usr/bin
# ($PATH is never searched).  The model, its snapshot, the decoder file hashes, the decode params and the ladder are constants
# inside asr_transcribe.py: there are no options or environment overrides for them.  Every helper this script runs is an
# absolute path (/bin, /usr/bin): nothing is looked up through $PATH.
#
#   word_timing.sh <avatar.mp4|wav> <script.txt> <out_dir> [--max-wait SEC]
#   word_timing.sh <avatar.mp4|wav> <script.txt> <out_dir> --cancel
#
# Outputs in <out_dir>:
#   vo16k.wav                16 kHz mono 16-bit extract of the audio (what is decoded)
#   raw_asr.json             raw whisper words + model / decoder / params / rung identity (asr_transcribe.py)
#   asr_rung_<R>.json        per-rung checkpoints (a killed job resumes after the last finished rung)
#   caption_pages.json       [{start,end,words:[{w,s,e}]}]  (asr_align.py: temp name, then renamed)
#   word_timing.log          the job's stdout/stderr (one RUNG line per rung, DEFECT lines)
#   word_timing.job.json     {pid,key,started,...} of the running job
#   word_timing.done.json    {key,output,output_sha256,raw,raw_sha256,rungs,wall_seconds,model,...} once finished.
#                            PROGRESS INFORMATION ONLY: finalize re-derives the pages and re-checks them, it never
#                            trusts this file
#   word_timing.failed.json  {rung,reason,regions,defects,key} when the timing is still defective after the ladder
#
# Job key = sha256(audio sha256, script sha256, sha256 of asr_transcribe.py, asr_align.py, timing_defects.py, asr_run.sh, asr_venv.manifest,
#                 sha256 of the CURRENT `asr_run.sh asr_transcribe.py --fingerprint` output).  So after an OS / ffmpeg / mlx / venv update the
#                 same command is a new job: the old outputs are removed and the audio is transcribed again.  An unreadable fingerprint = exit 4.
#   done file with this key + output present        -> print paths, exit 0 at once
#   job.json names a LIVE pid with this key         -> wait for it
#   live job with ANOTHER key in this out_dir       -> exit 3 (use --cancel or another out_dir)
#   failed file with this key                       -> print its DEFECT lines, exit 5 at once (never re-run)
#   otherwise                                       -> start the job detached (nohup + new session), wait
# Waiting polls at most --max-wait seconds (default 420):
#   done -> exit 0 | ladder exhausted -> exit 5 + DEFECT lines | job died otherwise -> exit 1 + log tail |
#   still running -> prints "WORD_TIMING INCOMPLETE job=<pid>" and exits 75 (= call again with the same arguments).
# --cancel stops ONLY the job recorded in word_timing.job.json (never any other process).
#
# OFFLINE ENFORCED: asr_transcribe.py sets HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 itself, and the model
# is loaded from its pinned snapshot directory in <passwd home>/.cache/huggingface/hub, so nothing is ever downloaded.
# `asr_run.sh asr_transcribe.py --check` verifies the interpreter / stdlib / venv manifest, ffmpeg, model cache and pins BEFORE a
# job starts.
#
# A new job first removes the previous run's raw_asr.json, caption_pages.json, done and failed files, so a failed run
# (exit 1/2/4/5) never leaves an old result behind.  Per-rung checkpoints (asr_rung_*.json) stay: a killed job of the SAME
# inputs resumes after its last finished rung, checkpoints of other inputs are ignored.
#
# Exit: 0 ok, 1 job failed (log tail printed), 2 bad arguments/input, 3 other-key job running,
#       4 tool / venv / model / pin / ffmpeg problem (nothing downloaded, nothing started),
#       5 word timing still defective after the fixed repair ladder: DEFECT lines printed (token, time, measured value,
#         limit). Deterministic — calling again with the same inputs prints the same failure and exits 5 at once; it is
#         NEVER retried automatically. Do not hand-edit timing files: stop and report the DEFECT lines.
#       75 still running (call again).
set -uo pipefail

SELF_DIR="${BASH_SOURCE[0]%/*}"; [ "$SELF_DIR" = "${BASH_SOURCE[0]}" ] && SELF_DIR=.
HERE="$(builtin cd "$SELF_DIR" && builtin pwd)"
SELF="$HERE/${BASH_SOURCE[0]##*/}"
# The account's home from the passwd entry, NEVER $HOME (redirecting HOME used to redirect the venv).  env -i: PERL5OPT & co cannot
# steer the lookup.  The job-mechanics tests rewrite exactly this line in a COPY of the script (see test_word_timing.py).
PW_HOME="$(/usr/bin/env -i /usr/bin/perl -e 'print((getpwuid($<))[7])')"
LAUNCHER="$HERE/asr_run.sh"
TRANSCRIBE="$HERE/asr_transcribe.py"; ALIGN="$HERE/asr_align.py"; DEFECTS_PY="$HERE/timing_defects.py"; MANIFEST="$HERE/asr_venv.manifest"
# = FFMPEG_CANDIDATES of asr_run.sh / asr_transcribe.py / asr_align.py / source_timed.py (a test asserts they are the same)
FFMPEG_CANDIDATES=(/opt/homebrew/bin/ffmpeg /usr/local/bin/ffmpeg /usr/bin/ffmpeg)
FFMPEG=""; for _c in "${FFMPEG_CANDIDATES[@]}"; do
  if [ -f "$_c" ] && [ -x "$_c" ]; then FFMPEG="$_c"; break; fi
done
# run "$@" under the minimal environment (the same one asr_run.sh gives the python chain); used for the ffmpeg extraction only
asr_env() { /usr/bin/env -i HOME="$PW_HOME" PATH="${FFMPEG%/*}:/usr/bin:/bin" LANG=en_US.UTF-8 TMPDIR=/var/empty "$@"; }
# the python chain: through the launcher, never directly
asr_py() { /usr/bin/env -u BASH_ENV -u ENV /bin/bash "$LAUNCHER" "$@"; }

# shasum is a perl script: PERL5OPT & co of the caller must not run code in it
NOPERLENV=(/usr/bin/env -u PERL5OPT -u PERL5LIB -u PERLLIB -u PERL5DB -u BASH_ENV -u ENV -u PYTHONPATH -u PYTHONSTARTUP -u PYTHONHOME)
sha_file() { "${NOPERLENV[@]}" /usr/bin/shasum -a 256 "$1" | /usr/bin/cut -d' ' -f1; }
sha_str()  { printf '%s' "$1" | "${NOPERLENV[@]}" /usr/bin/shasum -a 256 | /usr/bin/cut -d' ' -f1; }
jget()     { /usr/bin/python3 -I -B -c 'import json,sys
try:
    d=json.load(open(sys.argv[1])); v=d.get(sys.argv[2],"")
    print(v if v is not None else "")
except Exception:
    print("")' "$1" "$2"; }

# ---------------------------------------------------------------- detached job body
if [ "${1:-}" = "--_job" ]; then
  KEY="$2"; AUDIO="$3"; SCRIPT="$4"; OUT="$5"
  WAV="$OUT/vo16k.wav"; PAGES="$OUT/caption_pages.json"; RAW="$OUT/raw_asr.json"; FAILED="$OUT/word_timing.failed.json"
  START=$(/bin/date +%s)
  echo "job start $(/bin/date '+%F %T') key=$KEY"
  asr_env "$FFMPEG" -v error -y -i "$AUDIO" -vn -map_metadata -1 -ac 1 -ar 16000 -c:a pcm_s16le -fflags +bitexact -flags:a +bitexact "$WAV" \
    || { echo "ERROR: ffmpeg could not extract audio from $AUDIO" >&2; exit 2; }
  asr_py asr_transcribe.py --wav "$WAV" --script "$SCRIPT" --out-dir "$OUT"; RC=$?
  if [ $RC -eq 5 ]; then
    /usr/bin/python3 -I -B - "$FAILED" "$KEY" <<'PYEOF' || exit 1
import json, os, sys
path, key = sys.argv[1:3]
d = json.load(open(path, encoding='utf-8'))
d['key'] = key
tmp = path + '.tmp'
open(tmp, 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=1) + '\n')
os.replace(tmp, path)
PYEOF
    echo "ERROR: word timing still defective after the repair ladder (exit 5) after $(( $(/bin/date +%s) - START )) s" >&2
    exit 5
  fi
  if [ $RC -ne 0 ] || [ ! -s "$RAW" ]; then
    echo "ERROR: transcription failed (exit $RC) after $(( $(/bin/date +%s) - START )) s" >&2
    [ "$RC" -ne 0 ] && exit "$RC"
    exit 1
  fi
  asr_py asr_align.py --raw "$RAW" --script "$SCRIPT" --out "$PAGES"; RC=$?
  if [ $RC -ne 0 ] || [ ! -s "$PAGES" ]; then
    echo "ERROR: alignment failed (exit $RC) after $(( $(/bin/date +%s) - START )) s" >&2
    [ "$RC" -ne 0 ] && exit "$RC"
    exit 1
  fi
  WALL=$(( $(/bin/date +%s) - START ))
  /usr/bin/python3 -I -B - "$OUT" "$KEY" "$PAGES" "$RAW" "$WALL" "$(sha_file "$PAGES")" "$(sha_file "$RAW")" <<'PYEOF' || exit 1
import json, os, sys, time
out, key, pages, raw, wall, sha, raw_sha = sys.argv[1:8]
r = json.load(open(raw, encoding='utf-8'))
d = {'key': key, 'output': pages, 'output_sha256': sha, 'raw': raw, 'raw_sha256': raw_sha, 'rungs': r.get('rungs'),
     'wall_seconds': int(wall), 'model': (r.get('model') or {}).get('id'), 'finished': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
tmp = os.path.join(out, 'word_timing.done.json.tmp')
json.dump(d, open(tmp, 'w'), indent=1)
os.replace(tmp, os.path.join(out, 'word_timing.done.json'))
PYEOF
  echo "job done in ${WALL}s"
  exit 0
fi

# ---------------------------------------------------------------- arguments
MAXWAIT=420; CANCEL=0; POS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --max-wait) [ $# -ge 2 ] && [[ "$2" =~ ^[0-9]+$ ]] || { echo "ERROR: --max-wait needs a whole number of seconds" >&2; exit 2; }
                MAXWAIT="$2"; shift 2;;
    --cancel)   CANCEL=1; shift;;
    -*)         echo "ERROR: unknown option $1 (the tools take no extra arguments)" >&2; exit 2;;
    *)          POS+=("$1"); shift;;
  esac
done
if [ ${#POS[@]} -ne 3 ]; then
  echo "usage: word_timing.sh <avatar.mp4|wav> <script.txt> <out_dir> [--max-wait SEC] [--cancel]" >&2
  exit 2
fi
AUDIO="${POS[0]}"; SCRIPT="${POS[1]}"; OUT="${POS[2]}"
JOB="$OUT/word_timing.job.json"; DONE="$OUT/word_timing.done.json"; LOG="$OUT/word_timing.log"
PAGES="$OUT/caption_pages.json"; WAV="$OUT/vo16k.wav"; FAILED="$OUT/word_timing.failed.json"

job_alive() {  # pid is alive AND is one of our --_job processes (guards against pid reuse)
  local pid="$1"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  /bin/ps -p "$pid" -o command= 2>/dev/null | /usr/bin/grep -q -- '--_job'
}

# ---------------------------------------------------------------- --cancel
if [ $CANCEL -eq 1 ]; then
  PID="$(jget "$JOB" pid)"
  if [ -n "$PID" ] && job_alive "$PID"; then
    PG="$(/bin/ps -o pgid= -p "$PID" 2>/dev/null | /usr/bin/tr -d ' ')"
    if [ "$PG" = "$PID" ]; then kill -TERM -- "-$PID" 2>/dev/null; else kill -TERM "$PID" 2>/dev/null; fi
    for _ in 1 2 3 4 5 6 7 8 9 10; do job_alive "$PID" || break; /bin/sleep 0.5; done
    if job_alive "$PID"; then
      if [ "$PG" = "$PID" ]; then kill -KILL -- "-$PID" 2>/dev/null; else kill -KILL "$PID" 2>/dev/null; fi
    fi
    /bin/rm -f "$JOB"
    echo "cancelled job $PID"
  else
    echo "no running job in $OUT"
  fi
  exit 0
fi

[ -f "$AUDIO" ]  || { echo "ERROR: audio/video not found: $AUDIO" >&2; exit 2; }
[ -s "$SCRIPT" ] || { echo "ERROR: script not found or empty: $SCRIPT" >&2; exit 2; }

# ---------------------------------------------------------------- tool / venv / model / pins (exit 4, nothing started)
[ -n "$PW_HOME" ] && [ -d "$PW_HOME" ] || { echo "ERROR: cannot find the account's home directory (passwd entry)" >&2; exit 4; }
[ -n "$FFMPEG" ] || { echo "ERROR: ffmpeg not found in /opt/homebrew/bin, /usr/local/bin or /usr/bin (the caller's PATH is not searched)" >&2; exit 4; }
[ -x /usr/bin/python3 ] || { echo "ERROR: /usr/bin/python3 not found (the json helpers of this script)" >&2; exit 4; }
for f in "$LAUNCHER" "$TRANSCRIBE" "$ALIGN" "$DEFECTS_PY" "$MANIFEST"; do
  [ -f "$f" ] || { echo "ERROR: $f is missing" >&2; exit 4; }
done
CHECK="$(asr_py asr_transcribe.py --check 2>&1)"; RC=$?
if [ $RC -ne 0 ]; then
  echo "$CHECK" >&2
  echo "ERROR: word timing environment check failed (asr_run.sh asr_transcribe.py --check exit $RC). Nothing was downloaded or started; do not install or edit anything, stop and report." >&2
  exit 4
fi

# The CURRENT toolchain fingerprint (OS release, ffmpeg, mlx, venv manifest, ... = the identity fields of raw_asr.json) is part of the
# key: after an OS / ffmpeg / mlx / venv change the SAME command gets a new key, so the stale outputs below are removed and the job
# re-transcribes (without it the old done file would keep answering "done" and finalize would keep refusing the old fingerprint).
# If the fingerprint cannot be read that is exit 4 with its message, never "unchanged".
# Only STDOUT is hashed: a warning on stderr (which can differ on every call) must never change the key, or the job would restart
# forever.  stderr is read only for the message of a failure (the call is repeated then, with stderr folded in).
FP="$(asr_py asr_transcribe.py --fingerprint 2>/dev/null)"; RC=$?
if [ $RC -ne 0 ] || [ -z "$FP" ]; then
  asr_py asr_transcribe.py --fingerprint 2>&1 >/dev/null | /usr/bin/head -c 4000 >&2
  echo "ERROR: the toolchain fingerprint could not be read (asr_run.sh asr_transcribe.py --fingerprint exit $RC). Nothing was downloaded or started; do not install or edit anything, stop and report." >&2
  exit 4
fi

KEY="$(sha_str "$(sha_file "$AUDIO")
$(sha_file "$SCRIPT")
$(sha_file "$TRANSCRIBE")
$(sha_file "$ALIGN")
$(sha_file "$DEFECTS_PY")
$(sha_file "$LAUNCHER")
$(sha_file "$MANIFEST")
$(sha_str "$FP")")"

/bin/mkdir -p "$OUT" || { echo "ERROR: cannot create $OUT" >&2; exit 2; }

print_done() {
  echo "key:   $KEY"
  echo "model: $(jget "$DONE" model)"
  echo "wall:  $(jget "$DONE" wall_seconds) s (of the job)"
  echo "wav:   $WAV"
  echo "raw:   $OUT/raw_asr.json"
  echo "pages: $PAGES"
  echo "log:   $LOG"
  echo "done:  $DONE"
}
# progress information only (finalize re-derives the pages), but it must not report "done" for pages that were edited afterwards
done_ok()   { [ -f "$DONE" ] && [ "$(jget "$DONE" key)" = "$KEY" ] && [ -s "$PAGES" ] && [ "$(jget "$DONE" output_sha256)" = "$(sha_file "$PAGES")" ]; }
failed_ok() { [ -f "$FAILED" ] && [ "$(jget "$FAILED" key)" = "$KEY" ]; }
print_failed() {
  /usr/bin/python3 -I -B - "$FAILED" <<'PYEOF' >&2
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
for x in d.get('defects') or []:
    at = '%.3f' % x['start'] if isinstance(x.get('start'), (int, float)) else 'n/a'
    print('DEFECT %s at %ss token="%s" value=%s limit=%s' % (x.get('code'), at, x.get('token'), x.get('value'), x.get('limit')))
print('rung %s (%s), regions %s' % (d.get('rung'), d.get('reason'), d.get('regions')))
PYEOF
  echo "WORD_TIMING FAILED (exit 5): the word timing is still defective after the fixed repair ladder ($FAILED)." >&2
  echo "This is deterministic: do not call again, do not edit timing files by hand; stop the step and report the DEFECT lines." >&2
}

wait_job() {
  local pid="$1" deadline=$((SECONDS + MAXWAIT))
  while true; do
    if done_ok; then print_done; exit 0; fi
    if ! job_alive "$pid"; then
      /bin/sleep 0.5
      if done_ok; then print_done; exit 0; fi
      if failed_ok; then print_failed; exit 5; fi
      echo "ERROR: word timing job $pid ended without a done file; last lines of $LOG:" >&2
      /usr/bin/tail -n 15 "$LOG" >&2
      exit 1
    fi
    if [ $SECONDS -ge $deadline ]; then
      echo "WORD_TIMING INCOMPLETE job=$pid"
      echo "still running (log: $LOG); call again with the same arguments"
      exit 75
    fi
    /bin/sleep 0.5
  done
}

# ---------------------------------------------------------------- decide: done / wait / failed / start
if done_ok; then print_done; exit 0; fi

if [ -f "$JOB" ]; then
  OLD_PID="$(jget "$JOB" pid)"; OLD_KEY="$(jget "$JOB" key)"
  if [ -n "$OLD_PID" ] && job_alive "$OLD_PID"; then
    if [ "$OLD_KEY" = "$KEY" ]; then
      echo "waiting for running job $OLD_PID"
      wait_job "$OLD_PID"
    fi
    echo "ERROR: a job with a different key (audio/script/tool changed) is still running in $OUT (pid $OLD_PID). Wait for it, run with --cancel, or use another out_dir." >&2
    exit 3
  fi
fi

if failed_ok; then print_failed; exit 5; fi

/bin/rm -f "$DONE" "$FAILED" "$OUT/raw_asr.json" "$PAGES" "$OUT"/caption_pages.json.tmp.* "$OUT"/raw_asr.json.tmp.*   # never leave the previous run's result behind
: > "$LOG"
# (the detached launcher: PERL5OPT / BASH_ENV / PYTHON* of the caller must not run code in it either; the chain itself runs under env -i)
/usr/bin/nohup "${NOPERLENV[@]}" /usr/bin/perl -MPOSIX -e 'POSIX::setsid(); exec @ARGV' /bin/bash "$SELF" --_job "$KEY" "$AUDIO" "$SCRIPT" "$OUT" >>"$LOG" 2>&1 </dev/null &
PID=$!
disown "$PID" 2>/dev/null || true
/usr/bin/python3 -I -B - "$JOB" "$PID" "$KEY" "$AUDIO" "$SCRIPT" <<'PYEOF'
import json, os, sys, time
job, pid, key, audio, script = sys.argv[1:6]
d = {'pid': int(pid), 'key': key, 'started': int(time.time()), 'started_iso': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
     'audio': audio, 'script': script}
tmp = job + '.tmp'
json.dump(d, open(tmp, 'w'), indent=1)
os.replace(tmp, job)
PYEOF
echo "started word timing job $PID (detached; log: $LOG)"
wait_job "$PID"
