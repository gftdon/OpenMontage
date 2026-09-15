#!/bin/bash
# Mux the silent Remotion render with the V2 soundtrack built by build_audio.py.
#   bash mux_v2.sh VISUAL.mp4 FINAL.wav OUT.mp4
# Accept: duration == events.json total ± 0.1 s; mean loudness within 1 dB of the source VO; max ≤ -0.4 dB.
set -euo pipefail
VISUAL=$1; AUDIO=$2; OUT=$3
ffmpeg -v error -y -i "$VISUAL" -i "$AUDIO" -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 192k -shortest -movflags +faststart "$OUT"
ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT" | sed 's/^/duration /'
ffprobe -v error -select_streams v -show_entries stream=width,height,r_frame_rate -of csv=p=0 "$OUT"
ffmpeg -v info -i "$OUT" -vn -af volumedetect -f null - 2>&1 | grep -E "mean_volume|max_volume" | sed 's/.*\] //'
