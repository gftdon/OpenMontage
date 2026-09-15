#!/bin/bash
# Transcode downloaded b-roll to the composition's working format, SEQUENTIALLY.
# (21 parallel 4K→1080p ffmpegs on one machine blew a 10-minute timeout; one at a
# time with -preset veryfast finishes the same set in ~3 min.)
#
#   transcode_broll.sh SRC_DIR OUT_DIR [name ...]     # names without .mp4; default = all mp4/webm in SRC_DIR
#
# Output: 1920x1080 (cover-crop, so vertical clips are usable), 25 fps, h264 CRF 19,
# silent, max 30 s. Skips outputs that already exist and are >= 7 s long.
set -uo pipefail
SRC="$1"; OUT="$2"; shift 2
mkdir -p "$OUT"
if [ $# -eq 0 ]; then set -- $(cd "$SRC" && ls *.mp4 *.webm 2>/dev/null | sed 's/\.[^.]*$//'); fi
for f in "$@"; do
  in=$(ls "$SRC/$f".mp4 "$SRC/$f".webm 2>/dev/null | head -1)
  [ -z "$in" ] && { echo "missing $f"; continue; }
  if ffprobe -v error "$OUT/$f.mp4" >/dev/null 2>&1 && [ "$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT/$f.mp4" | cut -d. -f1)" -ge 7 ]; then echo "ok $f"; continue; fi
  ffmpeg -v error -y -i "$in" -t 30 -vf "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=25" \
    -c:v libx264 -preset veryfast -crf 19 -pix_fmt yuv420p -an "$OUT/$f.mp4" && echo "done $f"
done
echo "--- durations (paste into BROLL_DUR) ---"
for m in "$OUT"/*.mp4; do printf "  %s: %s,\n" "$(basename "$m" .mp4)" "$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$m")"; done
