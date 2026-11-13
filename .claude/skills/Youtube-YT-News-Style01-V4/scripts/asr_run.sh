#!/bin/bash
# asr_run.sh - the ONLY way to start a chain python script (asr_transcribe.py, asr_align.py, source_timed.py's whisper worker).
#
#   bash asr_run.sh <asr_transcribe.py|asr_align.py|source_timed.py> [arguments...]   verify, then run
#   bash asr_run.sh --verify                                                         verify only (exit 0 / 4)
#   bash asr_run.sh --write-manifest        HUMAN ONLY (setup_asr_venv.sh does it): (re)writes asr_venv.manifest.
#                                           The unattended agent NEVER runs this; a changed manifest changes the fingerprint.
#
# Why: the pins and checks inside python run inside the interpreter they check, so a wrapper python, a sitecustomize.py, a .pth
# line or an edited stdlib module would pass them.  This launcher verifies, from OUTSIDE python and with root-owned tools only
# (/usr/bin/find, sort, shasum, xargs, sed, diff, perl, env, grep, /bin/bash; absolute paths, never $PATH), that every file the
# chain executes or loads from outside the skill is exactly the one in asr_venv.manifest:
#   - the Cellar python binary it execs, the framework binary and libpython it loads,
#   - the whole stdlib tree (lib/python3.12 without its own site-packages),
#   - every file of the V4 venv's site-packages (no __pycache__, no dist-info RECORD / REQUESTED / INSTALLER / direct_url.json:
#     those are written by the installer and never executed).
# The file LIST is compared too, so an added sitecustomize.py / .pth / module / .pyc is refused, not only an edited one.
# Then it execs the Cellar python DIRECTLY (never venv/bin/python, never via pyvenv.cfg) with
#     /usr/bin/env -i HOME=<passwd home> PATH=<ffmpeg dir>:/usr/bin:/bin LANG=en_US.UTF-8 TMPDIR=/var/empty  python -I -S -B -X pycache_prefix=/var/empty
# (-I no PYTHON* variables / no cwd on sys.path; -S no site / .pth / sitecustomize; -B + pycache_prefix=/var/empty: no bytecode is
# ever read).  The chain scripts append the venv's site-packages to sys.path themselves.
# Not covered (listed in the result of the packet): brew shared libraries outside the python root (openssl, libmpdec, ...), ffmpeg
# (recorded in the fingerprint, not pinned), and a race between this check and the exec.
#
# Exit: 0 / the python script's own exit code; 2 usage; 4 verification failed or a prerequisite is missing (nothing was run).

# ---- start over with an empty environment (no BASH_ENV, exported functions, PATH, DYLD_*, PYTHON*, PERL5OPT ...)
if [ "${__ASR_RUN_CLEAN-}" != 1 ]; then
    builtin exec /usr/bin/env -i __ASR_RUN_CLEAN=1 /bin/bash --noprofile --norc "$0" "$@"
fi
unset __ASR_RUN_CLEAN
set -u -o pipefail
export LC_ALL=C

# ---- constants (a test rewrites PYROOT / VENV_ROOT in a temp COPY of this file to point it at copied trees; no env override)
PYROOT=/opt/homebrew/Cellar/python@3.12/3.12.15_1/Frameworks/Python.framework/Versions/3.12
HOME_DIR=$(/usr/bin/perl -e 'print((getpwuid($<))[7])')
VENV_ROOT="$HOME_DIR/.cache/yt-news-v4/asr-venv"
FFMPEG_CANDIDATES=(/opt/homebrew/bin/ffmpeg /usr/local/bin/ffmpeg /usr/bin/ffmpeg)
ENV_LANG=en_US.UTF-8
ENV_TMPDIR=/var/empty
PYBIN="$PYROOT/bin/python3.12"
SITE="$VENV_ROOT/lib/python3.12/site-packages"
CHAIN_SCRIPTS=(asr_transcribe.py asr_align.py source_timed.py)

HERE=${0%/*}
[ "$HERE" = "$0" ] && HERE=.
HERE=$(builtin cd "$HERE" && builtin pwd -P)
MANIFEST="$HERE/asr_venv.manifest"
HINT="run 'bash $HERE/setup_asr_venv.sh' (a human, not the agent); do not install, edit or rebuild anything yourself"

die() { echo "ERROR: $*" >&2; exit 4; }

# every path the manifest covers, absolute, one per line, sorted (the generator and the verifier use this same function)
list_files() {
    {
        /usr/bin/find "$PYROOT/lib/python3.12" \( -name __pycache__ -o -path "$PYROOT/lib/python3.12/site-packages" \) -prune -o \
            \( -type f -o -type l \) -print
        /usr/bin/find "$SITE" \( -name __pycache__ \) -prune -o \
            \( \( -type f -o -type l \) ! -name .DS_Store ! -path '*.dist-info/RECORD' ! -path '*.dist-info/REQUESTED' \
               ! -path '*.dist-info/INSTALLER' ! -path '*.dist-info/direct_url.json' -print \)
        printf '%s\n' "$PYBIN" "$PYROOT/Python" "$PYROOT/Resources/Python.app/Contents/MacOS/Python"
    } | /usr/bin/sort -u
}

# "<sha256>  @PY@/<path under the python root>" / "@VENV@/<path under the venv>", in list order
hash_lines() {
    list_files | /usr/bin/tr '\n' '\0' | /usr/bin/xargs -0 /usr/bin/shasum -a 256 |
        /usr/bin/sed -e "s|  $PYROOT/|  @PY@/|" -e "s|  $VENV_ROOT/|  @VENV@/|"
}

check_prerequisites() {
    [ -x "$PYBIN" ] || die "the pinned python $PYBIN is not there (brew upgrade?): $HINT"
    [ -d "$SITE" ] || die "the ASR venv $VENV_ROOT is not there: $HINT"
    [ ! -e "$PYROOT/bin/pyvenv.cfg" ] && [ ! -e "$PYROOT/pyvenv.cfg" ] || die "a pyvenv.cfg next to the python binary would redirect its prefix: $HINT"
}

find_ffmpeg() {
    local c
    for c in "${FFMPEG_CANDIDATES[@]}"; do
        if [ -f "$c" ] && [ -x "$c" ]; then echo "$c"; return 0; fi
    done
    return 1
}

verify_manifest() {
    check_prerequisites
    [ -f "$MANIFEST" ] || die "$MANIFEST is missing: $HINT"
    local out rc
    out=$(/usr/bin/diff <(/usr/bin/grep -v '^#' "$MANIFEST") <(hash_lines) 2>&1)
    rc=$?
    if [ $rc -ne 0 ]; then
        # first differing paths, e.g. "< hash  @PY@/lib/python3.12/csv.py" (pinned) / "> hash  @PY@/lib/python3.12/csv.py" (found)
        die "the interpreter / stdlib / ASR venv differ from $MANIFEST; first differences: $(echo "$out" | /usr/bin/grep '^[<>]' | /usr/bin/head -n 6 | /usr/bin/tr '\n' ';') -- $HINT"
    fi
}

case "${1-}" in
    --write-manifest)
        check_prerequisites
        body=$(hash_lines) || die "cannot hash the python / venv files"
        [ -n "$body" ] || die "nothing to pin under $PYROOT / $SITE"
        {
            echo "# asr_venv.manifest - sha256 of every file the ASR chain executes or loads from outside the skill (see asr_run.sh)."
            echo "# python root @PY@ = $PYROOT"
            echo "# venv root   @VENV@ = <passwd home>/.cache/yt-news-v4/asr-venv"
            echo "# Written ONLY by a human: bash asr_run.sh --write-manifest (setup_asr_venv.sh does it). The agent never runs it."
            echo "$body"
        } > "$MANIFEST.tmp.$$" && /bin/mv "$MANIFEST.tmp.$$" "$MANIFEST" || die "cannot write $MANIFEST"
        echo "wrote $MANIFEST: $(echo "$body" | /usr/bin/wc -l | /usr/bin/tr -d ' ') files"
        exit 0
        ;;
    --verify)
        verify_manifest
        echo "ok: interpreter, stdlib and ASR venv match $MANIFEST"
        exit 0
        ;;
    '' | -*)
        echo "usage: bash asr_run.sh <${CHAIN_SCRIPTS[*]}> [arguments...] | --verify | --write-manifest (human only)" >&2
        exit 2
        ;;
esac

SCRIPT=$1
shift
ok=0
for c in "${CHAIN_SCRIPTS[@]}"; do [ "$SCRIPT" = "$c" ] && ok=1; done
[ $ok = 1 ] || { echo "ERROR: $SCRIPT is not a chain script (${CHAIN_SCRIPTS[*]})" >&2; exit 2; }
[ -f "$HERE/$SCRIPT" ] || die "$HERE/$SCRIPT not found"

verify_manifest
MSHA=$(/usr/bin/shasum -a 256 < "$MANIFEST") || die "cannot hash $MANIFEST"
MSHA=${MSHA%% *}
FF=$(find_ffmpeg) && PATHV="${FF%/*}:/usr/bin:/bin" || PATHV=/usr/bin:/bin

builtin exec /usr/bin/env -i HOME="$HOME_DIR" PATH="$PATHV" LANG="$ENV_LANG" TMPDIR="$ENV_TMPDIR" \
    "$PYBIN" -I -S -B -X pycache_prefix=/var/empty -X "asr_manifest_sha256=$MSHA" "$HERE/$SCRIPT" "$@"
