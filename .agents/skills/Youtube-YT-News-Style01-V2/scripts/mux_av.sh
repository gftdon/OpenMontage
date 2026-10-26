#!/bin/bash
# Mux a silent Remotion render with the avatar VO + a looping, VO-ducked music bed.
# Remotion renders carry NO audio — this step is mandatory.
#
#   mux_av.sh VISUAL.mp4 AVATAR_WITH_VO.mp4 BED.mp3 OUT.mp4 TOTAL_SEC VO_END_SEC [BED_VOL=0.22]
#
# Recipe (proven on the Fable/Mythos 5.1 news report):
#   - VO padded with silence to TOTAL_SEC (endcard tail)
#   - bed looped, trimmed to TOTAL_SEC, volume BED_VOL, 1.5s fade-in, 4.2s fade-out at VO_END
#   - bed sidechain-compressed by the VO (ducks under speech, breathes in pauses)
#   - amix normalize=0 so the VO level is untouched; video stream copied
# Accept: out duration == TOTAL_SEC (±0.1); volumedetect mean within ~1 dB of the
# source VO's own mean; max <= -1 dB.
set -euo pipefail
VISUAL="$1"; VO_SRC="$2"; BED="$3"; OUT="$4"; TOTAL="$5"; VO_END="$6"; BED_VOL="${7:-0.22}"

ffmpeg -y -v error -i "$VISUAL" -i "$VO_SRC" -stream_loop -1 -i "$BED" -filter_complex \
  "[1:a]apad=whole_dur=${TOTAL},asplit=2[vo][sc];[2:a]atrim=0:${TOTAL},afade=t=in:st=0:d=1.5,afade=t=out:st=${VO_END}:d=4.2,volume=${BED_VOL}[bed];[bed][sc]sidechaincompress=threshold=0.02:ratio=5:attack=40:release=600:makeup=1[duck];[vo][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]" \
  -map 0:v -map "[aout]" -c:v copy -c:a aac -b:a 192k -movflags +faststart "$OUT"

echo "MUX_DONE $OUT"
ffprobe -v error -show_entries format=duration,size -of csv=p=0 "$OUT"
echo "--- output loudness ---"
ffmpeg -v info -i "$OUT" -af volumedetect -f null - 2>&1 | grep -E 'mean_volume|max_volume'
echo "--- source VO loudness (reference) ---"
ffmpeg -v info -i "$VO_SRC" -af volumedetect -f null - 2>&1 | grep -E 'mean_volume|max_volume'
