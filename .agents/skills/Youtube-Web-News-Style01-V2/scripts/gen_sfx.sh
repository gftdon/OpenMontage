#!/bin/bash
# Build the SFX library with ElevenLabs text-to-sound-effects (eleven_text_to_sound_v2).
#   bash gen_sfx.sh OUT_DIR [PROMPTS.tsv]
# PROMPTS.tsv lines: name<TAB>duration_seconds<TAB>prompt   (default set below = what events.mjs expects)
# Needs ELEVENLABS_API_KEY in .env (run from the repo root). Existing files are skipped.
# API minimum duration is 0.5 s — shorter requests return HTTP 400.
set -u
set -a; . ./.env; set +a
OUT=${1:?OUT_DIR}; mkdir -p "$OUT"
PROMPTS=${2:-}
gen() { # name duration text
  local name=$1 dur=$2 text=$3
  [ -s "$OUT/$name.mp3" ] && { echo "skip $name"; return; }
  code=$(curl -s -o "$OUT/$name.mp3" -w "%{http_code}" -X POST "https://api.elevenlabs.io/v1/sound-generation" \
    -H "xi-api-key: $ELEVENLABS_API_KEY" -H "Content-Type: application/json" \
    -d "{\"text\": \"$text\", \"duration_seconds\": $dur, \"prompt_influence\": 0.6}")
  echo "$name HTTP $code $(stat -f%z "$OUT/$name.mp3" 2>/dev/null || stat -c%s "$OUT/$name.mp3") bytes"
  [ "$code" != "200" ] && rm -f "$OUT/$name.mp3"
}
if [ -n "$PROMPTS" ]; then
  while IFS=$'\t' read -r name dur text; do [ -n "$name" ] && gen "$name" "$dur" "$text"; done < "$PROMPTS"
else
  gen riser 2.5 "cinematic tension riser, rising whoosh building to a hit, clean, no music, broadcast news"
  gen impact 1.5 "deep cinematic impact hit with short sub boom and tight tail, clean, no music"
  gen sting 2.5 "modern news ident logo sting, bright synth hit with shimmer and short sub, clean, no melody"
  gen whoosh 0.8 "fast airy whoosh transition, clean, short"
  gen pop 0.5 "soft UI pop, rounded click, subtle, clean, single hit"
  gen tick 0.5 "tiny UI tick click, single, very short, clean"
  gen swoosh 0.6 "soft paper swipe highlight swoosh, subtle, short, clean"
  gen chapter 1.2 "short news chapter transition stinger, bright synth accent with soft impact, clean"
  gen morph 0.7 "smooth magnetic whoosh with a soft glassy tail, short, clean"
  gen typing 3.0 "fast mechanical keyboard typing, close mic, clean, no talking"
fi
for f in "$OUT"/*.mp3; do printf "%-12s %s s\n" "$(basename "$f")" "$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")"; done
