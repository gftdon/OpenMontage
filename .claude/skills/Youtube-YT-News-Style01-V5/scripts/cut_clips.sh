#!/bin/bash
# cut_clips.sh — cut muted 1080p25 clips from the YouTube source and print
# brollDur-ready duration lines for episode.json.
#
#   cut_clips.sh SOURCE.mp4 OUT_DIR name:start:end [name:start:end ...]
#
# Example:
#   cut_clips.sh source.mp4 clips yt_fight:6:17 yt_pipeline:38:62
#
# Rules of thumb when choosing ranges (learned the hard way):
#   - pad the in-point 2-3 s before the visual you want; survey frames and the
#     renderer can disagree by about a second, and a beat that opens on a
#     transition/title card looks like a mistake
#   - make available duration after `from` LONGER than the beat; V4 broll/clip
#     both honor `from` and Loop uses floor((brollDur[src]-from)*25)-2 frames
#     (a source clip must not loop at all: schema rule S09)
#   - skip the source's sponsor/promo-code segments entirely
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
SRC="$1"; OUT="$2"; shift 2
mkdir -p "$OUT"
for spec in "$@"; do
  name="${spec%%:*}"; rest="${spec#*:}"
  start="${rest%%:*}"; end="${rest#*:}"
  ffmpeg -v error -ss "$start" -to "$end" -i "$SRC" -an -r 25 \
    -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -movflags +faststart \
    "$OUT/$name.mp4" -y
done
python3 -I "$SCRIPT_DIR/cut_manifest.py" "$SRC" "$OUT" "$@"
echo "--- paste into episode.json brollDur ---"
for spec in "$@"; do
  name="${spec%%:*}"
  dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT/$name.mp4")
  printf "  \"%s\": %.2f,\n" "$name" "$dur"
done
