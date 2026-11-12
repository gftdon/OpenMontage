#!/bin/bash
# VISUAL AVATAR_WITH_VO BED OUT TOTAL_SEC VO_END_SEC [BED_VOL=.22]
# Preserve the V2 ducked mix, then normalize twice and measure FINAL AAC MP4.
set -euo pipefail
VISUAL="$1"; VO="$2"; BED="$3"; OUT="$4"; TOTAL="$5"; VO_END="$6"; VOL="${7:-0.22}"
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="${OUT%.mp4}.audio"
rm -f "${OUT}.mux.json"   # a receipt only ever describes a mux that completed in THIS run
mkdir -p "$WORK"
ffmpeg -y -v error -i "$VO" -stream_loop -1 -i "$BED" -filter_complex \
 "[0:a]apad=whole_dur=${TOTAL},asplit=2[vo][sc];[1:a]atrim=0:${TOTAL},afade=t=in:st=0:d=1.5,afade=t=out:st=${VO_END}:d=4.2,volume=${VOL}[bed];[bed][sc]sidechaincompress=threshold=0.02:ratio=5:attack=40:release=600:makeup=1[duck];[vo][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]" \
 -map '[a]' -t "$TOTAL" -ar 48000 -c:a pcm_f32le "$WORK/mix.wav"
ffmpeg -hide_banner -nostats -i "$WORK/mix.wav" -af loudnorm=I=-14:TP=-1.5:LRA=20:print_format=json -f null - 2> "$WORK/pass1.log"
python3 - "$HERE" "$WORK" <<'PY'
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]);from measure_loudness import parse_loudnorm
w=Path(sys.argv[2]);d=parse_loudnorm((w/'pass1.log').read_text());(w/'pass1.json').write_text(json.dumps(d,indent=2))
f='loudnorm=I=-14:TP=-1.5:LRA=20:linear=true:print_format=json:'+':'.join(f'{a}={d[b]}' for a,b in [('measured_I','input_i'),('measured_TP','input_tp'),('measured_LRA','input_lra'),('measured_thresh','input_thresh'),('offset','target_offset')])
(w/'filter.txt').write_text(f)
PY
FILTER="$(<"$WORK/filter.txt")"
ffmpeg -y -hide_banner -nostats -i "$VISUAL" -i "$WORK/mix.wav" -af "$FILTER" -map 0:v:0 -map 1:a:0 -t "$TOTAL" -c:v copy -c:a aac -ar 48000 -b:a 192k -movflags +faststart "$OUT" 2> "$WORK/pass2.log"
python3 - "$HERE" "$WORK" <<'PY'
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]);from measure_loudness import parse_loudnorm
w=Path(sys.argv[2]);text=(w/'pass2.log').read_text();d=parse_loudnorm(text)
if d.get('normalization_type') not in ('linear','dynamic'):raise ValueError('missing normalization mode')
d['warnings']=['linear normalization fell back to dynamic; final measured metrics remain the acceptance gate'] if d['normalization_type']=='dynamic' else []
if d['warnings']:print('WARNING: '+d['warnings'][0],file=sys.stderr)
(w/'pass2.json').write_text(json.dumps(d,indent=2))
PY
python3 "$HERE/measure_loudness.py" "$OUT" --report "$WORK/final.json"
# Mux receipt: binds visual + avatar VO + bed + final by sha256 (verified later by finalize.py).
RECEIPT="${OUT}.mux.json"
python3 - "$RECEIPT" "$VISUAL" "$VO" "$BED" "$OUT" \
  "$(shasum -a 256 "$VISUAL" | cut -d' ' -f1)" "$(shasum -a 256 "$VO" | cut -d' ' -f1)" \
  "$(shasum -a 256 "$BED" | cut -d' ' -f1)" "$(shasum -a 256 "$OUT" | cut -d' ' -f1)" <<'PY'
import datetime,json,os,sys
rcpt,visual,vo,bed,out,sv,sa,sb,sf=sys.argv[1:10]
ent=lambda p,h:{'path':os.path.abspath(p),'sha256':h}
d={'schema':'yt-news-v4-mux-receipt','version':1,'visual':ent(visual,sv),'avatar':ent(vo,sa),'bed':ent(bed,sb),
   'final':ent(out,sf),'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}
tmp=rcpt+'.tmp';open(tmp,'w').write(json.dumps(d,indent=2)+'\n');os.replace(tmp,rcpt)
PY
printf 'MUX_DONE %s\n' "$OUT"
