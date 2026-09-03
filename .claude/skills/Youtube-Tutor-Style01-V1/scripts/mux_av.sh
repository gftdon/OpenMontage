#!/bin/bash
# Mux a silent Remotion render with the avatar VO + a looping music bed,
# then print verification numbers (duration, loudness).
#
# Remotion renders carry NO audio, ever — this step is mandatory.
#
# Usage:
#   mux_av.sh VISUAL.mp4 AVATAR_WITH_VO.mp4 BED.mp3 OUT.mp4 TOTAL_SEC VO_END_SEC
#
# Recipe (proven on GoogleFlowYT EP.1):
#   - VO padded with silence to TOTAL_SEC (endcard tail)
#   - bed looped, trimmed to TOTAL_SEC, volume 0.15 (~14 dB under VO),
#     1.2s fade-in, 4s fade-out starting at VO_END_SEC
#   - amix normalize=0 so VO level is NOT ducked by the mix
#   - video stream copied untouched (no re-encode)
#
# Acceptance: out duration == TOTAL_SEC (+/- 0.1), volumedetect mean within
# ~1 dB of the source VO's own mean, max <= -1 dB.
set -euo pipefail

VISUAL="$1"; VO_SRC="$2"; BED="$3"; OUT="$4"; TOTAL="$5"; VO_END="$6"

ffmpeg -y -v error -i "$VISUAL" -i "$VO_SRC" -stream_loop -1 -i "$BED" -filter_complex \
  "[1:a]apad=whole_dur=${TOTAL}[vo];[2:a]atrim=0:${TOTAL},afade=t=in:st=0:d=1.2,afade=t=out:st=${VO_END}:d=4,volume=0.15[m];[vo][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]" \
  -map 0:v -map "[aout]" -c:v copy -c:a aac -b:a 192k -movflags +faststart "$OUT"

echo "MUX_DONE $OUT"
ffprobe -v error -show_entries format=duration,size -of csv=p=0 "$OUT"
echo "--- output loudness ---"
ffmpeg -v info -i "$OUT" -af volumedetect -f null - 2>&1 | grep -E 'mean_volume|max_volume'
echo "--- source VO loudness (reference) ---"
ffmpeg -v info -i "$VO_SRC" -af volumedetect -f null - 2>&1 | grep -E 'mean_volume|max_volume'
