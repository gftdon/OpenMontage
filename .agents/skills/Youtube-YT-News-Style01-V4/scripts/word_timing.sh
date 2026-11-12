#!/bin/bash
# word_timing.sh — offline word timing from the REAL audio (forced alignment of the exact script onto
# Whisper's own timestamps), the same call the pipeline uses in Step 2 — as a RESUMABLE, DETACHED job so
# it is safe under a ~10-minute command limit (the real alignment takes ~6 min for an 11-minute avatar clip):
#
#   word_timing.sh <avatar.mp4|wav> <script.txt> <out_dir> [--max-wait SEC] [-- extra extract_timing.py args]
#   word_timing.sh <avatar.mp4|wav> <script.txt> <out_dir> --cancel
#
# Outputs in <out_dir>:
#   vo16k.wav               16 kHz mono extract of the audio
#   caption_pages.json      [{start,end,words:[{w,s,e}]}]  (written to a temp name, then renamed)
#   word_timing.log         the job's stdout/stderr
#   word_timing.job.json    {pid,key,started,...} of the running job
#   word_timing.done.json   {key,output,output_sha256,wall_seconds,model,...} once finished
#
# Job key = sha256(audio sha256, script sha256, extract_timing.py sha256, model id, extra args).
#   done file with this key + output present        -> print paths, exit 0 at once
#   job.json names a LIVE pid with this key         -> wait for it
#   live job with ANOTHER key in this out_dir       -> exit 3 (use --cancel or another out_dir)
#   otherwise                                       -> start the alignment detached (nohup + new session), wait
# Waiting polls at most --max-wait seconds (default 420):
#   done -> exit 0 | job died without a done file -> exit 1 + log tail | still running ->
#   prints "WORD_TIMING INCOMPLETE job=<pid>" and exits 75 (= call again with the same arguments).
# --cancel stops ONLY the job recorded in word_timing.job.json (never any other process).
#
# OFFLINE ENFORCED: HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1; mlx_whisper resolves its
# model with huggingface_hub.snapshot_download, which then only reads the local cache, so a missing model
# fails fast instead of downloading (~3 GB). The cache is also checked before the job starts.
#
# Env overrides: KARAOKE_VENV (default ~/.cache/karaoke-subtitle/venv), EXTRACT_TIMING (path to the tool;
# default the karaoke_subtitle_v2 skill next to this skill, then the openMontage-video-production copy),
# WHISPER_MODEL (default mlx-community/whisper-large-v3-mlx = extract_timing.py's own default).
# Tests only: WORD_TIMING_CMD_FOR_TEST=<command taking --wav W --script S --out O> replaces the real tool.
#
# Exit: 0 ok, 1 job failed, 2 bad arguments/input, 3 other-key job running, 4 tool / venv / model / ffmpeg
# missing (nothing downloaded), 75 still running (call again).
set -uo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
HERE="$(dirname "$SELF")"

sha_file() { if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | cut -d' ' -f1; else sha256sum "$1" | cut -d' ' -f1; fi; }
sha_str()  { if command -v shasum >/dev/null 2>&1; then printf '%s' "$1" | shasum -a 256 | cut -d' ' -f1; else printf '%s' "$1" | sha256sum | cut -d' ' -f1; fi; }
jget()     { python3 -c 'import json,sys
try:
    d=json.load(open(sys.argv[1])); v=d.get(sys.argv[2],"")
    print(v if v is not None else "")
except Exception:
    print("")' "$1" "$2"; }

# ---------------------------------------------------------------- detached job body
if [ "${1:-}" = "--_job" ]; then
  shift
  KEY="$1"; AUDIO="$2"; SCRIPT="$3"; OUT="$4"; MODEL="$5"; shift 5
  [ "${1:-}" = "--" ] && shift
  WAV="$OUT/vo16k.wav"; PAGES="$OUT/caption_pages.json"; TMP="$OUT/caption_pages.json.tmp.$$"
  START=$(date +%s)
  echo "job start $(date '+%F %T') key=$KEY model=$MODEL"
  ffmpeg -v error -y -i "$AUDIO" -vn -ac 1 -ar 16000 "$WAV" || { echo "ERROR: ffmpeg could not extract audio from $AUDIO" >&2; exit 2; }
  if [ -n "${WORD_TIMING_CMD_FOR_TEST:-}" ]; then
    "$WORD_TIMING_CMD_FOR_TEST" --wav "$WAV" --script "$SCRIPT" --out "$TMP"; RC=$?
  else
    "$WT_PYBIN" "$WT_TOOL" --wav "$WAV" --script "$SCRIPT" --out "$TMP" --model "$MODEL" "$@"; RC=$?
  fi
  if [ $RC -ne 0 ] || [ ! -s "$TMP" ]; then
    rm -f "$TMP"
    echo "ERROR: alignment failed (exit $RC) after $(( $(date +%s) - START )) s" >&2
    [ "$RC" -ne 0 ] && exit "$RC"
    exit 1
  fi
  mv -f "$TMP" "$PAGES" || exit 1
  WALL=$(( $(date +%s) - START ))
  python3 - "$OUT" "$KEY" "$PAGES" "$MODEL" "$WALL" "$(sha_file "$PAGES")" <<'PYEOF'
import json, os, sys, time
out, key, pages, model, wall, sha = sys.argv[1:7]
d = {'key': key, 'output': pages, 'output_sha256': sha, 'wall_seconds': int(wall), 'model': model,
     'finished': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
tmp = os.path.join(out, 'word_timing.done.json.tmp')
json.dump(d, open(tmp, 'w'), indent=1)
os.replace(tmp, os.path.join(out, 'word_timing.done.json'))
PYEOF
  echo "job done in ${WALL}s"
  exit 0
fi

# ---------------------------------------------------------------- arguments
MAXWAIT=420; CANCEL=0; POS=(); EXTRA=()
while [ $# -gt 0 ]; do
  case "$1" in
    --max-wait) [ $# -ge 2 ] && [[ "$2" =~ ^[0-9]+$ ]] || { echo "ERROR: --max-wait needs a whole number of seconds" >&2; exit 2; }
                MAXWAIT="$2"; shift 2;;
    --cancel)   CANCEL=1; shift;;
    --)         shift; EXTRA=("$@"); break;;
    *)          POS+=("$1"); shift;;
  esac
done
if [ ${#POS[@]} -ne 3 ]; then
  echo "usage: word_timing.sh <avatar.mp4|wav> <script.txt> <out_dir> [--max-wait SEC] [--cancel] [-- extra extract_timing.py args]" >&2
  exit 2
fi
AUDIO="${POS[0]}"; SCRIPT="${POS[1]}"; OUT="${POS[2]}"
JOB="$OUT/word_timing.job.json"; DONE="$OUT/word_timing.done.json"; LOG="$OUT/word_timing.log"
PAGES="$OUT/caption_pages.json"; WAV="$OUT/vo16k.wav"

job_alive() {  # pid is alive AND is one of our --_job processes (guards against pid reuse)
  local pid="$1"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  ps -p "$pid" -o command= 2>/dev/null | grep -q -- '--_job'
}

# ---------------------------------------------------------------- --cancel
if [ $CANCEL -eq 1 ]; then
  PID="$(jget "$JOB" pid)"
  if [ -n "$PID" ] && job_alive "$PID"; then
    PG="$(ps -o pgid= -p "$PID" 2>/dev/null | tr -d ' ')"
    if [ "$PG" = "$PID" ]; then kill -TERM -- "-$PID" 2>/dev/null; else kill -TERM "$PID" 2>/dev/null; fi
    for _ in 1 2 3 4 5 6 7 8 9 10; do job_alive "$PID" || break; sleep 0.5; done
    if job_alive "$PID"; then
      if [ "$PG" = "$PID" ]; then kill -KILL -- "-$PID" 2>/dev/null; else kill -KILL "$PID" 2>/dev/null; fi
    fi
    rm -f "$JOB"
    echo "cancelled job $PID"
  else
    echo "no running job in $OUT"
  fi
  exit 0
fi

[ -f "$AUDIO" ]  || { echo "ERROR: audio/video not found: $AUDIO" >&2; exit 2; }
[ -s "$SCRIPT" ] || { echo "ERROR: script not found or empty: $SCRIPT" >&2; exit 2; }

# ---------------------------------------------------------------- tool / venv / model (exit 4, nothing downloaded)
command -v ffmpeg >/dev/null 2>&1 || { echo "ERROR: ffmpeg not found on PATH" >&2; exit 4; }
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found on PATH" >&2; exit 4; }
if [ -n "${WORD_TIMING_CMD_FOR_TEST:-}" ]; then
  MODEL="test-model"; TOOL_ID="test-cmd:$(sha_str "$WORD_TIMING_CMD_FOR_TEST")"
  [ -f "$WORD_TIMING_CMD_FOR_TEST" ] && TOOL_ID="test-cmd:$(sha_file "$WORD_TIMING_CMD_FOR_TEST")"
else
  VENV="${KARAOKE_VENV:-$HOME/.cache/karaoke-subtitle/venv}"
  PYBIN="$VENV/bin/python"
  MODEL="${WHISPER_MODEL:-mlx-community/whisper-large-v3-mlx}"
  [ -x "$PYBIN" ] || { echo "ERROR: karaoke venv python missing: $PYBIN (mlx-whisper + pythainlp live there; run bash ~/.claude/skills/karaoke-subtitle/scripts/setup.sh). Nothing was downloaded." >&2; exit 4; }
  TOOL="${EXTRACT_TIMING:-}"
  if [ -z "$TOOL" ]; then
    for c in "$HERE/../../karaoke_subtitle_v2/scripts/extract_timing.py" \
             "/Volumes/Ext_SS990Pro/Dev/openMontage-video-production/.claude/skills/karaoke_subtitle_v2/scripts/extract_timing.py"; do
      [ -f "$c" ] && { TOOL="$c"; break; }
    done
  fi
  [ -n "$TOOL" ] && [ -f "$TOOL" ] || { echo "ERROR: extract_timing.py not found (set EXTRACT_TIMING)" >&2; exit 4; }
  HUB="${HF_HUB_CACHE:-${HF_HOME:-$HOME/.cache/huggingface}/hub}"
  FOUND=""
  for snap in "$HUB/models--${MODEL//\//--}"/snapshots/*; do
    [ -f "$snap/config.json" ] && { [ -e "$snap/weights.safetensors" ] || [ -e "$snap/weights.npz" ]; } && FOUND="$snap" && break
  done
  [ -n "$FOUND" ] || { echo "ERROR: speech model $MODEL is not in the local HF cache ($HUB); not downloading. Cached: $(ls "$HUB" 2>/dev/null | grep '^models--' | tr '\n' ' ')" >&2; exit 4; }
  TOOL_ID="$(sha_file "$TOOL")"
  export WT_PYBIN="$PYBIN" WT_TOOL="$TOOL"
fi
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1

KEY="$(sha_str "$(sha_file "$AUDIO")
$(sha_file "$SCRIPT")
$TOOL_ID
$MODEL
${EXTRA[*]:-}")"

mkdir -p "$OUT" || { echo "ERROR: cannot create $OUT" >&2; exit 2; }

print_done() {
  echo "key:   $KEY"
  echo "model: $MODEL"
  echo "wall:  $(jget "$DONE" wall_seconds) s (of the job)"
  echo "wav:   $WAV"
  echo "pages: $PAGES"
  echo "log:   $LOG"
  echo "done:  $DONE"
}
done_ok() { [ -f "$DONE" ] && [ "$(jget "$DONE" key)" = "$KEY" ] && [ -s "$PAGES" ]; }

wait_job() {
  local pid="$1" deadline=$((SECONDS + MAXWAIT))
  while true; do
    if done_ok; then print_done; exit 0; fi
    if ! job_alive "$pid"; then
      sleep 0.5
      if done_ok; then print_done; exit 0; fi
      echo "ERROR: alignment job $pid ended without a done file; last lines of $LOG:" >&2
      tail -n 15 "$LOG" >&2
      exit 1
    fi
    if [ $SECONDS -ge $deadline ]; then
      echo "WORD_TIMING INCOMPLETE job=$pid"
      echo "still running (log: $LOG); call again with the same arguments"
      exit 75
    fi
    sleep 0.5
  done
}

# ---------------------------------------------------------------- decide: done / wait / start
if done_ok; then print_done; exit 0; fi

if [ -f "$JOB" ]; then
  OLD_PID="$(jget "$JOB" pid)"; OLD_KEY="$(jget "$JOB" key)"
  if [ -n "$OLD_PID" ] && job_alive "$OLD_PID"; then
    if [ "$OLD_KEY" = "$KEY" ]; then
      echo "waiting for running job $OLD_PID"
      wait_job "$OLD_PID"
    fi
    echo "ERROR: a job with a different key (audio/script/tool/model changed) is still running in $OUT (pid $OLD_PID). Wait for it, run with --cancel, or use another out_dir." >&2
    exit 3
  fi
fi

rm -f "$DONE" "$OUT"/caption_pages.json.tmp.*
: > "$LOG"
nohup perl -MPOSIX -e 'POSIX::setsid(); exec @ARGV' bash "$SELF" --_job "$KEY" "$AUDIO" "$SCRIPT" "$OUT" "$MODEL" -- "${EXTRA[@]+"${EXTRA[@]}"}" >>"$LOG" 2>&1 </dev/null &
PID=$!
disown "$PID" 2>/dev/null || true
python3 - "$JOB" "$PID" "$KEY" "$AUDIO" "$SCRIPT" "$MODEL" <<'PYEOF'
import json, os, sys, time
job, pid, key, audio, script, model = sys.argv[1:7]
d = {'pid': int(pid), 'key': key, 'started': int(time.time()), 'started_iso': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
     'audio': audio, 'script': script, 'model': model}
tmp = job + '.tmp'
json.dump(d, open(tmp, 'w'), indent=1)
os.replace(tmp, job)
PYEOF
echo "started alignment job $PID (detached; log: $LOG)"
wait_job "$PID"
