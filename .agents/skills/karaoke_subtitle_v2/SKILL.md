---
name: karaoke_subtitle_v2
description: Add word-by-word gold-glow karaoke subtitles (Kanit ExtraBold, glass pill, spring animation — the HermesBotReelV2 look) to a Remotion composition, synced from the video's own audio with exact script wording. Use whenever the user wants karaoke subtitles / ซับคาราโอเกะ / ตัวหนังสือไล่สีตามเสียง in a Remotion reel, wants captions "เหมือนคลิป Hermes ล่าสุด" or "แบบ v2", or needs word-level Thai caption timing data (caption pages JSON / TS module) for any Remotion composition. This is the Remotion-overlay counterpart of the older PNG-burn karaoke-subtitle skill — prefer it whenever the deliverable is rendered with Remotion.
---

# Karaoke Subtitle v2 (Remotion Gold-Glow)

Produces the exact subtitle treatment from the Hermes Bot Mode v2 reel:
short phrase pages in a frosted glass pill, bottom-center, where the spoken
word pops gold (#FDE68A on a #F59E0B glow, scale 1.10) while spoken words stay
white and upcoming words sit dim. Kanit ExtraBold 40 px, page enters with a
spring. Timing is word-level, measured from the video's own audio by
mlx-whisper, with the on-screen text aligned char-by-char onto the exact
script so Thai wording is never at the mercy of ASR spelling.

The style is locked — match it, don't redesign per-run.

## Inputs you need

1. **The video** (for its audio track), and
2. **The exact script** — ideally the `transcript.srt` the VO was recorded
   from, or a plain `.txt` with one spoken line per row, in order. If given an
   SRT, strip it to plain lines first (cue text only, no index/timestamp rows).

If the user only has the video, don't fall back to raw ASR text — exact
wording is the whole point of this skill. Ask for the script, or transcribe
first, show the user the lines, and use the confirmed text as `script.txt`.

## Pipeline (3 commands)

Work in a scratch dir under `projects/<name>/` (assets + artifacts stay with
the production). Replace `$SKILL` with this skill's directory
(`.Codex/skills/karaoke_subtitle_v2`).

### 1. Extract the VO audio

```bash
ffmpeg -v error -i "INPUT.mp4" -vn -ac 1 -ar 16000 -y vo.wav
```

### 2. Word-level timing + exact-wording alignment

Uses the karaoke venv (mlx-whisper + pythainlp) — NOT the project `.venv`.
First-ever run downloads the ~1.6 GB Whisper model once.

```bash
~/.cache/karaoke-subtitle/venv/bin/python "$SKILL/scripts/extract_timing.py" \
  --wav vo.wav --script script.txt --out caption_pages.json
```

Sanity-check the `aligned N script line(s) (X correct chars vs Y ASR chars)`
line — X/Y should be within ~1% of each other. A big gap means the script
doesn't match the audio; fix the script, don't force it.

### 3. Sentence-safe repaging + TypeScript module

```bash
python3 "$SKILL/scripts/repage.py" \
  --pages caption_pages.json --script script.txt \
  --out-pages caption_pages_final.json \
  --out-ts ../../remotion-composer/src/<myReel>Captions.ts
```

This splits pages at script-line boundaries (Thai has no spaces — a page that
crosses a sentence seam welds words into false compounds) and hard-fails with
`SPAN!` lines if any page isn't a verbatim substring of one script line. Zero
violations is the only acceptable result. More page flips is fine — the gold
highlight carries continuity.

## Wire it into the composition

Copy `assets/KaraokeCaptionLane.tsx` into `remotion-composer/src/` (once per
project — if it's already there, reuse it). Font files
`public/fonts/Kanit-ExtraBold.ttf` + `Kanit-Bold.ttf` already ship with this
repo's remotion-composer; the component loads them via `delayRender`.

```tsx
import { KaraokeCaptionLane, useThaiFonts } from "./KaraokeCaptionLane";
import { CAPTION_PAGES } from "./<myReel>Captions";

export const MyReel: React.FC = () => {
  useThaiFonts();                       // top of the root component
  // ...
  return (
    <div style={{ /* your 1080x1920 stage */ }}>
      {/* scenes… */}
      <KaraokeCaptionLane pages={CAPTION_PAGES} hideAfterSec={VO_END_SEC} />
      {/* endcard (higher zIndex) after VO_END_SEC */}
    </div>
  );
};
```

- `hideAfterSec` — pass the VO end so captions disappear under the endcard.
- `bottomPx` — default 300 (design px). Keep ≥300 on 9:16 social reels:
  260 grazes the platform caption band. Only lower it for non-platform use.
- zIndex 50 — below endcards/overlays (100), above video zones.

The design space is **1080×1920**. Rendering at 720×1280? Keep the component
at 1080 design px inside a scale wrapper (as HermesBotReel v1 did), or scale
`bottomPx`/font proportionally — never eyeball it.

## Verify before declaring done

1. `npx remotion still <Comp> out/qa.png --frame=<f>` at 4–6 spread times,
   plus one frame per beat boundary if the reel has beats.
2. Eyeball: gold word is the word actually spoken at that time; Thai vowels /
   tone marks sit correctly (Kanit loaded — tofu or misplaced marks mean
   `useThaiFonts()` wasn't called); pill doesn't collide with faces, name
   tags, or scoreboard corners.
3. Remotion renders are **silent** — re-mux the original audio after render:
   `ffmpeg -i graphics.mp4 -i source.mp4 -map 0:v -map 1:a -c:v copy -c:a aac -b:a 192k out.mp4`
   (no `-shortest` if an endcard extends past the VO).
4. `volumedetect` the final file — mean should match the source VO within
   ~1 dB (unless a music bed was added downstream).

## Gotchas learned the hard way

- **Never skip repage.py** — the welds are invisible in the JSON and obvious
  to every Thai viewer. The substring assertion is the cheap regression test.
- Latin/Thai spacing inside a page is handled by the component (space only
  where a token starts/ends with a Latin letter or digit) — don't pre-insert
  spaces in the data.
- Keep every visual a pure function of `frame` — no CSS `transition` on the
  words; the pop comes from swapping `transform` per frame.
- Long pages wrap (max-width 900, flex-wrap). If a page exceeds ~2 lines,
  lower `--max-words`/`--max-chars` in step 2 and re-run 2–3.
- mlx-whisper timing is slightly nondeterministic run-to-run (observed up to
  ~0.25 s word drift between two runs of the same audio; text is stable).
  Don't diff two extractions to "prove" correctness — verify the final render
  with still frames instead.
- The component file documents the full locked style in its header comment —
  point there if someone wants to tweak a color; change defaults in the
  shared asset, not a fork, so every future reel stays identical.
