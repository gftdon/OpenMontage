#!/bin/bash
# yt_survey.sh — download a YouTube source video and build the recon materials
# used to pick clip ranges: chapter list + tiled contact sheets.
#
#   yt_survey.sh YOUTUBE_URL OUT_DIR
#   yt_survey.sh --frames-only SOURCE.mp4 OUT_DIR     (only the dense contact sheets; no network)
#
# Outputs in OUT_DIR:
#   source.mp4          1080p mp4 (merge), the cut master
#   chapters.txt        "start_time  title" per YouTube chapter (empty if none)
#   survey/sheetA.jpg   tiles every ~85 s from t=0    (whole-arc overview)
#   survey/sheetB.jpg   same grid offset by 42 s      (catches what A missed)
#   transcript_timed.json  [{start,end,text}] from YouTube auto-subs when they can be fetched; if not,
#                       a WARNING says to run source_timed.py from-audio (local, offline, slow: not run here)
#   survey/dense/sheet_<start>-<end>.jpg  contact sheets over the WHOLE video: one tile every 10 s,
#                       6x5 tiles (5 minutes) per sheet, tiles 384x216, row-major left->right, top->bottom
#   survey/dense/index.json  per sheet: file, start/end seconds, and every tile's time (tile i = start + 10*i)
#
# Next step after running: view sheetA/B, then pull single frames at chapter
# midpoints (ffmpeg -ss T -i source.mp4 -frames:v 1) to place cut ranges.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# dense_frames SOURCE.mp4 OUT_DIR — time-addressable contact sheets for the whole video.
dense_frames() {
  local SRC="$1" OUT="$2" STEP=10 SPAN=300 DUR T0 T1 NAME
  local DENSE="$OUT/survey/dense"
  mkdir -p "$DENSE"
  rm -f "$DENSE"/sheet_*.jpg "$DENSE/index.json"
  DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$SRC")
  T0=0
  while python3 -c "import sys; sys.exit(0 if float('$T0') < float('$DUR') else 1)"; do
    T1=$(python3 -c "import math; print(min($T0 + $SPAN, math.ceil(float('$DUR'))))")
    NAME=$(printf 'sheet_%05d-%05d.jpg' "$T0" "$T1")
    # tile k of the sheet is the frame at T0 + STEP*k exactly (verified frame-for-frame): select takes the
    # first frame, then the first frame >= STEP s after the previous pick. (fps=1/STEP is NOT used: it
    # samples ~5 s late.)
    ffmpeg -v error -y -ss "$T0" -t "$SPAN" -i "$SRC" \
      -vf "select='isnan(prev_selected_t)+gte(t-prev_selected_t\,$STEP-0.01)',scale=384:216:force_original_aspect_ratio=decrease,pad=384:216:(ow-iw)/2:(oh-ih)/2,tile=6x5:padding=0" \
      -fps_mode passthrough -frames:v 1 -q:v 4 "$DENSE/$NAME"
    T0=$((T0 + SPAN))
  done
  python3 - "$DENSE" "$DUR" "$STEP" "$SPAN" <<'PYEOF'
import json, math, os, re, sys
dense, dur, step, span = sys.argv[1], float(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
sheets = []
for f in sorted(os.listdir(dense)):
    m = re.fullmatch(r'sheet_(\d+)-(\d+)\.jpg', f)
    if not m:
        continue
    a, b = int(m.group(1)), int(m.group(2))
    n = min(30, math.ceil((min(a + span, dur) - a) / step))
    sheets.append({'file': f, 'start': a, 'end': b,
                   'tiles': [{'i': i, 'row': i // 6, 'col': i % 6, 't': a + step * i} for i in range(n)]})
json.dump({'duration': round(dur, 3), 'interval_s': step, 'tile': {'w': 384, 'h': 216, 'cols': 6, 'rows': 5},
           'note': 'tile i of a sheet is the frame at start + interval_s * i; row-major from the top-left',
           'sheets': sheets}, open(os.path.join(dense, 'index.json'), 'w'), indent=1)
print(f'dense sheets: {len(sheets)} -> {dense}')
PYEOF
}

if [ "${1:-}" = "--frames-only" ]; then
  [ $# -eq 3 ] && [ -f "$2" ] || { echo "usage: yt_survey.sh --frames-only SOURCE.mp4 OUT_DIR" >&2; exit 2; }
  dense_frames "$2" "$3"
  echo "DENSE_DONE $3"
  exit 0
fi

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

# timed transcript of the source: YouTube auto-subs when they can be fetched (never fails the survey;
# YouTube may answer HTTP 429 and yt-dlp can still exit 0 without writing a file, so check for the file)
rm -f "$OUT"/subs.*.json3 "$OUT/transcript_timed.json"
yt-dlp "$URL" --skip-download --write-auto-subs --sub-langs en --sub-format json3 \
  -o "$OUT/subs.%(ext)s" >/dev/null 2>&1 || true
SUBS=$(ls "$OUT"/subs.*.json3 2>/dev/null | head -n 1 || true)
if [ -n "$SUBS" ] && python3 "$HERE/source_timed.py" from-json3 "$SUBS" --out "$OUT/transcript_timed.json"; then
  echo "# timed transcript: $OUT/transcript_timed.json (from $SUBS)"
else
  echo "WARNING: no usable YouTube subtitles (429/none) - no transcript_timed.json. Run (local, offline, a few minutes):" >&2
  echo "  python3 $HERE/source_timed.py from-audio $OUT/source.mp4 --out $OUT/transcript_timed.json" >&2
fi

# contact sheets: one tile every 85 s, two offsets. fps=1/85 over a ~13 min
# video gives <= 12 tiles; for longer videos lower the rate (tiles cap at 12).
ffmpeg -v error -i "$OUT/source.mp4" -vf "fps=1/85,scale=480:270,tile=4x3" \
  -frames:v 1 "$OUT/survey/sheetA.jpg" -y
ffmpeg -v error -ss 42 -i "$OUT/source.mp4" -vf "fps=1/85,scale=480:270,tile=4x3" \
  -frames:v 1 "$OUT/survey/sheetB.jpg" -y

dense_frames "$OUT/source.mp4" "$OUT"

echo "SURVEY_DONE $OUT"
