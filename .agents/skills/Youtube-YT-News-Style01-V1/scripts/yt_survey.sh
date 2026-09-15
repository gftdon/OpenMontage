#!/bin/bash
# yt_survey.sh — download a YouTube source video and build the recon materials
# used to pick clip ranges: chapter list + tiled contact sheets.
#
#   yt_survey.sh YOUTUBE_URL OUT_DIR
#
# Outputs in OUT_DIR:
#   source.mp4          1080p mp4 (merge), the cut master
#   chapters.txt        "start_time  title" per YouTube chapter (empty if none)
#   survey/sheetA.jpg   tiles every ~85 s from t=0    (whole-arc overview)
#   survey/sheetB.jpg   same grid offset by 42 s      (catches what A missed)
#
# Next step after running: view sheetA/B, then pull single frames at chapter
# midpoints (ffmpeg -ss T -i source.mp4 -frames:v 1) to place cut ranges.
set -euo pipefail
URL="$1"; OUT="$2"
mkdir -p "$OUT/survey"

yt-dlp "$URL" -f "bestvideo[height<=1080]+bestaudio/best[height<=1080]" \
  --merge-output-format mp4 -o "$OUT/source.%(ext)s"

yt-dlp "$URL" --dump-json --no-download | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('# title:', d['title'])
print('# duration:', d['duration'], 'uploader:', d.get('uploader'))
for c in (d.get('chapters') or []):
    print(f\"{c['start_time']:>8.1f}  {c['title']}\")
" | tee "$OUT/chapters.txt"

DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT/source.mp4")
echo "# probed duration: $DUR"

# contact sheets: one tile every 85 s, two offsets. fps=1/85 over a ~13 min
# video gives <= 12 tiles; for longer videos lower the rate (tiles cap at 12).
ffmpeg -v error -i "$OUT/source.mp4" -vf "fps=1/85,scale=480:270,tile=4x3" \
  -frames:v 1 "$OUT/survey/sheetA.jpg" -y
ffmpeg -v error -ss 42 -i "$OUT/source.mp4" -vf "fps=1/85,scale=480:270,tile=4x3" \
  -frames:v 1 "$OUT/survey/sheetB.jpg" -y

echo "SURVEY_DONE $OUT"
