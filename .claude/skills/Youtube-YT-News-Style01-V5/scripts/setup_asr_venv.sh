#!/bin/bash
# setup_asr_venv.sh — creates the V4 chain's OWN speech-recognition venv.   *** RUN BY A HUMAN, NEVER BY THE UNATTENDED AGENT ***
#
#   bash setup_asr_venv.sh            create <passwd home>/.cache/yt-news-v4/asr-venv and install the pinned distributions (needs network)
#   bash setup_asr_venv.sh --verify   only compare: nothing is created, changed or downloaded; exit 0 = the venv matches
#
# Why: the V4 word-timing chain (asr_transcribe.py) pins every byte of the code that runs.  It must not share a venv with any
# other tool: maintaining that other venv would silently break V4 (exit 4 on a pin mismatch).  This venv belongs to V4 alone.
#
# What it does, and nothing else:
#   - target: <home from the passwd entry, never $HOME>/.cache/yt-news-v4/asr-venv  (fixed; no option, no environment override)
#   - base interpreter: /opt/homebrew/opt/python@3.12/bin/python3.12, which must resolve to the Cellar python that asr_run.sh pins
#     (its PYROOT constant); after a `brew upgrade python@3.12` that constant is a code change for the lead, this script refuses
#   - installs EXACTLY the distributions listed in REQUIREMENTS below, at exactly those versions: --no-deps, binary wheels only
#     (--only-binary=:all:), from https://pypi.org/simple, --isolated (no pip config / PIP_* variables), --no-cache-dir (pip's
#     cache dir is not touched), --no-compile (no bytecode is written)
#   - REFUSES when the target exists and is not empty (prints how to remove it; this script never deletes anything)
#   - never writes outside the target and its parent <home>/.cache/yt-news-v4
#   - after a successful install it writes asr_venv.manifest (bash asr_run.sh --write-manifest): the sha256 of every file of the
#     Cellar python it pins, the stdlib and the venv's site-packages.  asr_run.sh refuses to run anything when a file differs.
#     --verify never writes the manifest.
# Exit: 0 ok, 2 bad arguments, 4 refused / tool missing / verify differs, 1 install failed (the half-made venv is left for you
# to inspect; remove it as printed before trying again).
set -uo pipefail

PW_HOME="$(/usr/bin/env -i /usr/bin/perl -e 'print((getpwuid($<))[7])')"       # the tests rewrite this line in a COPY (no env override)
TARGET="$PW_HOME/.cache/yt-news-v4/asr-venv"
BASE_PY=/opt/homebrew/opt/python@3.12/bin/python3.12
INDEX=https://pypi.org/simple
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQUIREMENTS='anyio==4.13.0
certifi==2026.5.20
charset-normalizer==3.4.7
click==8.4.1
filelock==3.29.0
h11==0.16.0
httpcore==1.0.9
httpx==0.28.1
huggingface-hub==1.17.0
idna==3.17
llvmlite==0.47.0
mlx==0.31.2
mlx-metal==0.31.2
mlx-whisper==0.4.3
numba==0.65.1
numpy==2.4.6
pygments==2.20.0
pythainlp==5.3.4
pyyaml==6.0.3
regex==2026.5.9
rich==15.0.0
scipy==1.17.1
setuptools==81.0.0
tiktoken==0.13.0
tqdm==4.67.3
typing-extensions==4.15.0'
CLEAN_ENV=(/usr/bin/env -i HOME="$PW_HOME" PATH=/usr/bin:/bin LANG=en_US.UTF-8)

MODE=install
case "${1:-}" in
  "") ;;
  --verify) MODE=verify ;;
  *) echo "usage: bash setup_asr_venv.sh [--verify]   (a HUMAN runs this, never the unattended agent)" >&2; exit 2 ;;
esac
[ $# -le 1 ] || { echo "usage: bash setup_asr_venv.sh [--verify]" >&2; exit 2; }
echo "*** setup_asr_venv.sh: for a HUMAN only. The unattended agent must never run or edit this, nor install anything itself. ***"
[ -n "$PW_HOME" ] && [ -d "$PW_HOME" ] || { echo "ERROR: cannot find the account's home directory (passwd entry)" >&2; exit 4; }
echo "target: $TARGET"

pinned_pyroot() {  # the python root asr_run.sh pins (its PYROOT= line)
  /usr/bin/sed -n 's/^PYROOT=\(.*\)$/\1/p' "$HERE/asr_run.sh" | /usr/bin/head -n 1
}

verify() {  # read-only: installed name==version vs REQUIREMENTS (from the *.dist-info dir names; no python is run), then asr_run.sh --verify
  local site="$TARGET/lib/python3.12/site-packages" want got line bad=0
  [ -d "$site" ] || { echo "VERIFY FAILED: $site does not exist (run: bash $HERE/setup_asr_venv.sh)" >&2; return 4; }
  norm() { /usr/bin/tr 'A-Z-' 'a-z_'; }
  want="$(printf '%s\n' "$REQUIREMENTS" | /usr/bin/sed 's/==/-/' | norm | /usr/bin/sort)"
  got="$(builtin cd "$site" && /bin/ls -1d ./*.dist-info 2>/dev/null | /usr/bin/sed -e 's|^\./||' -e 's|\.dist-info$||' | norm | /usr/bin/sort)"
  while IFS= read -r line; do
    printf '%s\n' "$got" | /usr/bin/grep -qxF "$line" || { echo "VERIFY FAILED: missing or other version: $line" >&2; bad=1; }
  done <<< "$want"
  # nothing but the pinned distributions and pip (ensurepip) may be installed
  while IFS= read -r line; do
    printf '%s\n' "$want" | /usr/bin/grep -qxF "$line" || case "$line" in pip_*) ;; *) echo "VERIFY FAILED: unexpected distribution: $line" >&2; bad=1 ;; esac
  done <<< "$got"
  if [ -f "$HERE/asr_run.sh" ]; then
    /bin/bash "$HERE/asr_run.sh" --verify >/dev/null || { echo "VERIFY FAILED: asr_run.sh --verify reports a difference from asr_venv.manifest (run it for details)" >&2; bad=1; }
  else
    echo "VERIFY FAILED: $HERE/asr_run.sh is missing" >&2; bad=1
  fi
  [ $bad -eq 0 ] && echo "VERIFY OK: $TARGET matches the pinned list and the manifest" || return 4
}

if [ "$MODE" = verify ]; then verify; exit $?; fi

[ -x "$BASE_PY" ] || { echo "ERROR: base interpreter $BASE_PY not found (brew install python@3.12)" >&2; exit 4; }
[ -f "$HERE/asr_run.sh" ] || { echo "ERROR: $HERE/asr_run.sh is missing" >&2; exit 4; }
PINNED="$(pinned_pyroot)"; BASE_ROOT="$(builtin cd "$(/usr/bin/dirname "$(/usr/bin/readlink -f "$BASE_PY" 2>/dev/null || echo "$BASE_PY")")/.." 2>/dev/null && builtin pwd -P)"
[ -n "$PINNED" ] && [ "$PINNED" = "$BASE_ROOT" ] || { echo "REFUSED: $BASE_PY resolves to '$BASE_ROOT' but asr_run.sh pins PYROOT='$PINNED'. Re-pinning the interpreter is a code change (asr_run.sh PYROOT, then the manifest): ask the lead; nothing was created." >&2; exit 4; }
if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
  if [ -d "$TARGET" ] && [ -z "$(ls -A "$TARGET" 2>/dev/null)" ]; then :; else
    echo "REFUSED: $TARGET already exists and is not empty. This script never deletes anything." >&2
    echo "  to check it:   bash $HERE/setup_asr_venv.sh --verify" >&2
    echo "  to rebuild it: rm -rf '$TARGET'   (you, by hand; then run this script again)" >&2
    exit 4
  fi
fi
START=$(date +%s)
mkdir -p "$(dirname "$TARGET")" || { echo "ERROR: cannot create $(dirname "$TARGET")" >&2; exit 4; }
"${CLEAN_ENV[@]}" "$BASE_PY" -I -m venv "$TARGET" || { echo "ERROR: venv creation failed; remove '$TARGET' before retrying" >&2; exit 1; }
REQ="$(mktemp "$TARGET/requirements.XXXXXX")" || exit 1
printf '%s\n' "$REQUIREMENTS" > "$REQ"
"${CLEAN_ENV[@]}" "$TARGET/bin/python" -I -m pip install --isolated --no-cache-dir --no-compile --disable-pip-version-check \
    --no-deps --only-binary=:all: --index-url "$INDEX" -r "$REQ"
RC=$?
rm -f "$REQ"
[ $RC -eq 0 ] || { echo "ERROR: pip install failed (exit $RC); remove '$TARGET' before retrying" >&2; exit 1; }
echo "installed in $(( $(date +%s) - START )) s"
/bin/bash "$HERE/asr_run.sh" --write-manifest || { echo "ERROR: could not write the manifest" >&2; exit 1; }
verify
