---
name: Youtube-Web-News-Style01-V2
description: Use when turning an AI-avatar presenter take (mp4 + SRT) and a public web page URL into a 16:9 YouTube news report that must hook in the first 3 seconds, keep people watching (teaser, chapters, tease chips, SFX, music dips) and make dense foreign news easy for Thai viewers (translation strips, glossary, explain cards, chart, มุมไทย). Triggers - "ทำวิดีโอข่าวจากหน้าเว็บ", "อ่านข่าวจากเว็บ + avatar", "web news V2", "ทำให้คนหยุดดู 3 วินาที / ดูนานขึ้น", "ย่อยข่าวให้เข้าใจง่าย", "presenter morphs to a right-side card with the real page". Not for 9:16 reels or for the plain V1 look without retention layers.
---

# Youtube-Web-News-Style01-V2 — avatar + live web page ➜ 16:9 news report with the retention framework

V2 = the V1 format (dark stage, real page captures with word-synced highlights,
presenter morphing to a 9:16 card on the right, karaoke captions) **plus** the
STOP / STAY / ONLY-HERE / EASY / MEASURE layers — all built from the same
avatar take, no re-recording. Reference implementation: engine
`remotion-composer/src/FableNewsYTV2.tsx` + episode data
`remotion-composer/src/fableNewsEpisodeV2.ts` (comp ids `FableNewsYTV2`,
`FableNewsThumb`); first episode `projects/fable-mythos-news-yt/renders/Claude_Fable_Mythos_51_News_16x9_V2.mp4`
(7:58, ~$0.30 generated shots, ~3 h wall clock incl. the first render).
Snapshots live in `assets/`. **Clone engine + episode module, swap the data;
never rebuild the format.**

What V2 adds (details: `references/retention-framework.md`, geometry and the
Beat schema: `references/format-spec.md`):

- **STOP** — pre-lap teaser cut from the presenter's own lines (number + brand +
  contrast word) over a generated hook shot with 112 px typography, ident sting,
  greeting skipped; frame 0 = thumbnail; 3 thumbnail variants.
- **STAY** — agenda scene, chapter pill + progress ticks + YouTube chapters,
  "ต่อไป ▶" tease chips on pivots, punchline full-frame cuts, explain cards
  instead of quote-card runs, SFX layer, music automation with dips, lint.
- **ONLY-HERE** — VERIFIED capture badge + stamp, terminal demo of a real run,
  3 generated signature shots, the page's table as an animated chart, มุมไทย card.
- **EASY** — Thai translation strip under every English highlight, glossary
  chips, flow / compare / list explain cards, win-vs-baseline chips.
- **MEASURE** — `events.mjs` lint before publish, `retention_map.py` after.

## Inputs (ask only for what's missing)

1. Avatar take (one continuous mp4, 1080p preferred), 2. SRT whose text is the
exact script (cue times untrusted), 3. page URL (public, loads in headless
Chromium), 4. branding (brand, date, endcard copy) and, for มุมไทย, the local
facts to verify (price, availability). Optional: a reference look.

Names, chosen once: `<slug>` project id (`projects/<slug>/`), `<mediaDir>` under
`remotion-composer/public/` (= `EPISODE.assetDir`), `<CompId>` PascalCase
(`LaunchNewsYTV2`, thumb comp `<CompId>Thumb`), `<name>` camelCase module prefix
(`src/<name>Captions.ts`, `src/<name>Web.ts`, `src/<name>EpisodeV2.ts`).

Infra assumed: `remotion-composer/` app, karaoke venv
`~/.cache/karaoke-subtitle/venv`, ffmpeg, playwright resolvable from
`~/node_modules`, `.env` with `PIXABAY_API_KEY`, `ELEVENLABS_API_KEY` (SFX),
`FAL_KEY` (Kling + FLUX), Kanit fonts in `public/fonts/`. Run every command from
the repo root with absolute paths when calls run in parallel.

## Pipeline at a glance

| # | Step | Output |
|---|------|--------|
| 0 | Workspace + governance | `projects/<slug>/…`, checkpoints, decision log (`references/governance.md`) |
| 1 | Probe + intake | avatar copied to `public/<mediaDir>/avatar_source.mp4`, `AV_CX` |
| 2 | Script + karaoke timing | `script.txt`, `<name>Captions.ts` |
| 3 | Whisper rebase | `line_starts.json`, word dump — the timing spine |
| 4 | Recon + **V2 beat design** | section→line map, teaser pick, BEATS, chapters, explain/gloss/th plan, SHOTS.json |
| 5 | Web capture | `sec_*.png`, `quote_NN.png`, `chart_N.png`, `<name>Web.ts` |
| 6 | B-roll, music, **SFX, generated shots** | `public/<mediaDir>/broll/*.mp4`, `bed.mp3`, `assets/sfx/*.mp3` |
| 7 | Composition | `<CompId>.tsx` (engine clone) + `<name>EpisodeV2.ts` (data) + Root.tsx |
| 8 | QA stills + lint | frames viewed, `v2_events.json` lint clean |
| 9 | Audio build + render + mux | `final.wav`, silent render, `renders/<name>_V2.mp4` |
| 10 | Deliver | thumbnails ×3, `chapters.txt`, frames from the muxed file, report; retention loop after publish |

Steps 0–3 and 5 are V1 procedures; they are repeated here in short form so this
skill is self-contained. `S=.claude/skills/Youtube-Web-News-Style01-V2/scripts`.

## Step 0 — Workspace + governance

`projects/<slug>/{artifacts,assets/{web,broll,audio,sfx,gen},renders}`, hybrid
pipeline checkpoints + decision log per `references/governance.md` (present
both composition runtimes in the composition-mode decision).

## Step 1 — Probe + intake

```bash
ffprobe -v error -select_streams v -show_entries stream=width,height,r_frame_rate,duration -of csv=p=0 AVATAR.mp4
mkdir -p remotion-composer/public/<mediaDir>/{broll,web}
cp AVATAR.mp4 remotion-composer/public/<mediaDir>/avatar_source.mp4      # COPY, never symlink
```

View 3 frames, measure the face midline → `AV_CX` (EP.1: 940); `AV_CY` stays 540.

## Step 2 — Script + karaoke timing

```bash
python3 $S/srt_to_script.py --srt SOURCE.srt --out projects/<slug>/artifacts/script.txt
ffmpeg -v error -i AVATAR.mp4 -vn -ac 1 -ar 16000 -y projects/<slug>/assets/audio/vo16k.wav
~/.cache/karaoke-subtitle/venv/bin/python .claude/skills/karaoke_subtitle_v2/scripts/extract_timing.py --wav projects/<slug>/assets/audio/vo16k.wav --script projects/<slug>/artifacts/script.txt --out projects/<slug>/artifacts/caption_pages.json
python3 .claude/skills/karaoke_subtitle_v2/scripts/repage.py --pages projects/<slug>/artifacts/caption_pages.json --script projects/<slug>/artifacts/script.txt --out-pages projects/<slug>/artifacts/caption_pages_final.json --out-ts remotion-composer/src/<name>Captions.ts
```

Accept `violations: 0`, aligned chars ≈ script chars. Start whisper first (≈3 min); do Step 4 recon meanwhile.

## Step 3 — Whisper rebase

```bash
python3 $S/line_starts.py --pages projects/<slug>/artifacts/caption_pages_final.json --script projects/<slug>/artifacts/script.txt --out projects/<slug>/artifacts/line_starts.json
python3 $S/words_by_line.py projects/<slug>/artifacts/caption_pages_final.json projects/<slug>/artifacts/script.txt 1 2 7 …   # word times per line
```

`TIMELINE.mainSrcEnd` = last word end + 0.3. Beat `t` = whisper line start;
chips / highlights / chapters / dips = the `s` of the exact word. Never type an
SRT time.

## Step 4 — Recon + V2 beat design

```bash
node $S/explore_page.mjs "<URL>"
npx playwright screenshot --full-page --viewport-size=1100,900 --wait-for-timeout=6000 "<URL>" full.png   # tile + view
```

Write, in this order, into `<name>EpisodeV2.ts` (clone `assets/fableNewsEpisodeV2.reference.ts`):

1. **Teaser**: pick the sentence(s) with number + brand + contrast word; snap the
   cuts to silence and keep the negation word:
   `python3 $S/snap_cuts.py projects/<slug>/assets/audio/vo16k.wav 117.7 122.0 125.6 …` →
   `TIMELINE.teaser` (2–3 ranges, 10–13 s total), `mainSrcStart` = first content word
   (skip "สวัสดีค่ะ"), `stingDur` 2.6, `endcardDur` 8.
2. **CHAPTERS** (6–9, ≥ 10 s apart, titles ≤ 4 Thai words) and `AGENDA` (≤ 5 chips
   at word times in the first line after the open).
3. **BEATS** following the V1 rules (≈ 7 beats/min, alternate media, company
   story = intro b-roll → quote card + chips) plus the V2 rules from
   `references/retention-framework.md`: `next` on every pivot full-beat (with a
   `tease` for something ≥ 60 s ahead), one punchline full cut per big story,
   never 3 quote cards in a row (2nd/3rd → `explain`), `chart` right after the
   table receipts beat, one `terminal` beat under the "best at X" claim, one
   generated shot in the teaser + one concept shot + the ident background,
   `th` on every English highlight, `gloss` on first mention of each jargon
   term, "มุมไทย" explain card before the CTA, `next.pill` subscribe cue on the
   closing full beat.
4. `SUMMARY3 / FINAL4 / VS (+ leftLines/rightLines) / CTA_T / MUSIC_DIPS` word times.
5. `EPISODE`: brand, date, page pill, `captureLabel` ("VERIFIED · จับภาพ <date>"),
   `sting`, `endcard` (+`next`), `thumbs` (3 headline pairs; accents verifiable on the page).
6. `projects/<slug>/artifacts/shots.json` for the generated shots (copy
   `assets/shots.example.json`: one hook shot, one concept shot, one ident
   background) and the terminal demo plan (a real task you will run in Step 6).
7. `projects/<slug>/artifacts/broll-queries.json` = `{"key": ["search query",
   "pixabay category"]}` — copy `assets/broll-queries.example.json` (it lists the
   category vocabulary); one key per b-roll `src` used in BEATS.

## Step 5 — Web capture

Write `projects/<slug>/artifacts/capture-config.json` from
`assets/capture-config.example.json` (sections anchored to headings, phrases,
tables, tabs, carousel), then:

```bash
node $S/capture_page.mjs projects/<slug>/artifacts/capture-config.json
cp projects/<slug>/assets/web/*.png remotion-composer/public/<mediaDir>/web/
```

Fix every `MISS` / `ANCHOR MISS` and re-run (rects and PNGs from one run).
Table rows come back as `table_rowN` with text → chart values (read them off
the capture crop, not the truncated text). Name the quote carousel `quote`
(files `quote_NN.png`); the sameness lint counts runs of any `<prefix>_NN`
captures, so other names still lint. Traps: `references/web-capture.md`.

**Page-hosted videos (official b-roll, the best ONLY-HERE material):** keep
`"downloadVideosTo": "projects/<slug>/assets/videos"` in the config; the run
writes `videos.json` + `page_video_N.<ext>`. View a frame of each, rename the
keepers to semantic names (`mv page_video_0.mp4 nipah.mp4`), transcode them with
`transcode_broll.sh projects/<slug>/assets/videos remotion-composer/public/<mediaDir>/broll nipah …`,
paste the printed `BROLL_DUR` lines, and present them as `clip` beats
(`clipFit: "contain"` for light renders, `"cover"` for dark/square footage).

## Step 6 — B-roll, music, SFX, generated shots, terminal run

```bash
.venv/bin/python $S/fetch_broll.py projects/<slug>/artifacts/broll-queries.json projects/<slug>/assets/broll --music "technology corporate inspiring background" projects/<slug>/assets/audio/bed.mp3
bash $S/transcode_broll.sh projects/<slug>/assets/broll remotion-composer/public/<mediaDir>/broll     # paste BROLL_DUR lines
bash $S/gen_sfx.sh projects/<slug>/assets/sfx                                                       # ElevenLabs SFX library (10 one-shots)
.venv/bin/python $S/gen_shots.py projects/<slug>/artifacts/shots.json projects/<slug>/assets/gen remotion-composer/public/<mediaDir>/broll images   # stills (IMAGE_TOOL=flux_image default)
.venv/bin/python $S/gen_shots.py … videos      # Kling i2v (t2v when no still) — run in background, ~1–2 min/clip, ≈$0.10 each
.venv/bin/python $S/gen_shots.py … transcode   # -> gen_<name>.mp4 1080p25 + BROLL_DUR lines
```

View a contact sheet of first frames (stock and generated) and replace wrong
picks. Before bundling, every `src` in BEATS must exist in the broll folder —
copy a stock clip onto a `gen_*` name as a placeholder if a generation is still
running. Announce paid generation (tool, provider, variant, count) before
running it. **Terminal demo:** run the real task now (a small repo with a real
bug, `pytest`, the fix, `pytest` again), keep the verbatim outputs for
`TERMINAL_DEMO.lines`; if `claude -p` nested returns 529, do the task in the
current session and tag the scene DEMO.

## Step 7 — Composition

```bash
cp remotion-composer/src/FableNewsYTV2.tsx remotion-composer/src/<CompId>.tsx
cp remotion-composer/src/fableNewsEpisodeV2.ts remotion-composer/src/<name>EpisodeV2.ts   # or from assets/
```

Engine clone — change only: component / metadata / thumb names (`FableNewsYTV2`
→ `<CompId>`, `FableNewsThumb` → `<CompId>Thumb`), the three imports
(`./<name>Captions`, `./<name>Web`, `./<name>EpisodeV2`), `AV_CX`. Episode
module — the import `./<name>Web` and every data block from Step 4 (`BROLL_DUR`
from the transcode output). Identifiers to rename in the engine clone:
`FableNewsYTV2`, `FableNewsYTV2Props`, `calculateFableNewsYTV2Metadata`,
`FableNewsThumb`, `FableNewsThumbProps`. Register both in `Root.tsx`:

```tsx
import { <CompId>, <CompId>Props, calculate<CompId>Metadata, <CompId>Thumb, <CompId>ThumbProps } from "./<CompId>";
<Composition id="<CompId>" component={<CompId>} durationInFrames={Math.ceil(480 * 25)} fps={25} width={1920} height={1080}
  defaultProps={{} as <CompId>Props} calculateMetadata={calculate<CompId>Metadata} />   {/* duration overridden by calculateMetadata */}
<Composition id="<CompId>Thumb" component={<CompId>Thumb} durationInFrames={2} fps={25} width={1920} height={1080}
  defaultProps={{ variant: "A", avatarSec: 3.0 } as <CompId>ThumbProps} />
```

(`type` aliases, not interfaces, or Remotion's `Record<string, unknown>` check
fails.) The thumb comp reads `EPISODE.thumbs` from the episode module; nothing
else to wire. Grep the clones for the previous episode's strings before
rendering; anything left outside the episode module is a bug in the engine —
fix it there.

## Step 8 — QA stills + lint

```bash
node $S/events.mjs remotion-composer <name>EpisodeV2 projects/<slug>/artifacts/v2_events.json   # LINT lines
node $S/stills.mjs <CompId> 12,62,112,<sting>,<open>,… remotion-composer/out/qa remotion-composer
```

Frame = `round(seconds × 25)` in **timeline** seconds (`v2_events.json` lists
every beat's `t`/`end` in timeline seconds): use `beat.t + 0.5` for the teaser
hook and the sting, `beat.t + 2` elsewhere, and `t + 0.2 / + 0.4` inside a
morph. Render at least: teaser 0.5 s / 2.5 s / quote strip, sting
mid, main open, agenda, terminal, table, chart, a pivot with `next`, each
explain layout, มุมไทย, the subscribe cue, endcard, and 3 morph frames. View
them 3×3. Lint must show: no quote run ≥ 3, gaps > 5 s only on pivots, beats
> 16 s only where the camera has ≥ 3 keys, events/min ≥ 25.

## Step 9 — Audio build + render + mux

```bash
.venv/bin/python $S/build_audio.py projects/<slug>/artifacts/v2_events.json AVATAR.mp4 projects/<slug>/assets/audio/bed.mp3 projects/<slug>/assets/sfx projects/<slug>/assets/audio/v2
cd remotion-composer && npx remotion render src/index.tsx <CompId> out/<name>_visual.mp4 --concurrency=5 --crf=18 && cd ..   # ≈ 10 min / 8-min video on M4 Pro
bash $S/mux_v2.sh remotion-composer/out/<name>_visual.mp4 projects/<slug>/assets/audio/v2/final.wav projects/<slug>/renders/<name>_V2.mp4
```

Accept: duration = `v2_events.json` `total` ± 0.1 s; mean loudness within 1 dB
of the source VO; max ≤ −0.4 dB; `final.wav` energy profile shows VO in every
teaser piece, near-silence under the sting, VO again at `mainDst`. Fix a scene
without a full re-render: `npx remotion render … --frames=a-b out/fix.mp4`, then
ffmpeg `trim`/`concat` the range into the visual and re-mux.

## Step 10 — Deliver

```bash
node $S/thumbs.mjs remotion-composer projects/<slug>/renders/thumbs <CompId>Thumb A,B,C 3.0   # + 1280×720 JPEGs
python3 $S/chapters.py projects/<slug>/artifacts/v2_events.json projects/<slug>/artifacts/chapters.txt --first "ตัวอย่างข่าว (Preview)" --last "สรุป + Subscribe"
```

Output looks like `assets/chapters.example.txt` (0:00 first, ≥ 10 s apart;
shorter chapters are merged into the previous one).

Extract ~18 frames from the **muxed** file (teaser, sting, every new scene
type, close, endcard), view them, then report: deliverable path + specs,
what each framework layer added, generated-asset cost, what is DEMO vs real,
what was verified by numbers only (audio), and the retention loop:
`python3 $S/retention_map.py v2_events.json retention.csv` after 7 days.

## Gotchas (V1 + V2, each cost real time)

| Trap | Fix |
|------|-----|
| SRT times drift | rebase everything to whisper (Step 3) |
| Teaser cut lost "ไม่" → meaning flipped | `snap_cuts.py` on both sides of the word; check the caption at frame 12 |
| Remotion 404 on a clip | file must exist in `public/` **before** bundling (placeholder copy); never symlink |
| Nested `claude -p` → 529 Overloaded | run the demo task in-session, paste verbatim output, tag DEMO |
| `google_imagen` 404 "model not found" | `IMAGE_TOOL=flux_image`, or Kling t2v with image+motion prompt folded together |
| ElevenLabs SFX HTTP 400 | `duration_seconds` ≥ 0.5 |
| Stacked one-shots clip at the sting | gains in `events.mjs` + soft limiter in `build_audio.py` |
| Ring burst renders square | sized circle + radial gradient, not spread shadow on a 0-size box |
| Translation strip covers the next highlight | engine prefers above; shorten `th` |
| `pkill` misses `npm exec` render | kill the PIDs from `pgrep -f "remotion render"` |
| Parallel Bash calls share `cd` | absolute paths |
| `timeout` missing on macOS | `nohup … &` + log polling, or Monitor |
| Page height differs between loads | anchor sections; rects + PNGs in one run |
| Highlight hidden under chips | raise `fy` |
