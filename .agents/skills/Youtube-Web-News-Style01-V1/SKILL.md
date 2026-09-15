---
name: Youtube-Web-News-Style01-V1
description: >-
  Use when the user supplies an AI-avatar presenter video (HeyGen etc.) plus its
  SRT and a URL of an article / launch page, and wants it edited into a 16:9
  YouTube news report where the presenter morphs between full-frame and a
  vertical 9:16 card on the RIGHT while the LEFT shows the real web page
  scrolled/zoomed to whatever the presenter is talking about (with highlighted
  sentences), plus b-roll — the layout of the "Example.png" reference and the
  FableNewsYT composition. Triggers: "ตัดต่อวีดีโอรายงานข่าว", "ทำวิดีโอข่าว AI
  จากหน้าเว็บ", "แสดงเนื้อหาบนหน้าเว็บตรงกับที่ Avatar พูด", "Avatar
  แนวตั้งอยู่ฝั่งขวา", "morph ย่อไปฝั่งขวา", "สไตล์ Youtube-Web-News-Style01",
  "ทำเหมือนคลิป Fable 5.1 / Codex news", or any avatar mp4 + SRT + article URL
  brief — even if the user doesn't name this skill. NOT for the bottom-left PiP
  tutorial format (use Youtube-Tutor-Style01-V1) or vertical reels.
---

# Youtube-Web-News-Style01-V1 — avatar + live web page ➜ 16:9 news report

Reference implementation: `remotion-composer/src/FableNewsYT.tsx` (comp id
`FableNewsYT`, 1920×1080 @ 25 fps, 460 s = 455.6 s VO + endcard). First delivered episode:
`projects/fable-mythos-news-yt/renders/Claude_Fable_Mythos_51_News_16x9.mp4`
(Anthropic Fable/Mythos 5.1 launch, $0 marginal asset cost, ~2.5 h wall clock).
**Clone the reference and swap the data — do not rebuild the format.** A
snapshot lives in `assets/FableNewsYT.reference.tsx` in case the live file moves.

Anatomy (full spec in `references/format-spec.md`):

- Dark navy stage with dot grid. **Left stage** (1210×840) shows one of: a
  browser-framed **capture of the real page** with a camera (pan/zoom) and
  amber **phrase highlights** synced to the words being spoken; full-bleed
  **b-roll** with a kinetic Thai headline; an **official page video** in a
  museum card; or a **typography scene** (summary chips / vs card).
- **Avatar** = one continuous `OffthreadVideo` that morphs (uniform scale, no
  distortion) between full-frame and a **9:16 anchor card on the right**
  (478×850 at x=1362).
- Overlays: AI NEWS top bar + amber kicker per beat, number/info chips that pop
  on word times, BREAKING lower-third on the cold open, `Codex.ai`-style CTA
  chip, gold karaoke caption lane (locked style), progress bar, endcard.
- Music bed ducked under the VO. Remotion renders are **silent** — mux after.

## Inputs (ask only for what's missing)

1. **Avatar video** — one continuous take, 1920×1080 preferred; any fps.
2. **SRT** whose text is the exact spoken script. Text is trusted; **cue times
   are not** (they drifted −1.6…−2.5 s on EP.1, −4.1 s on the tutor series).
3. **URL** of the page the presenter is reporting on (must be publicly loadable
   in headless Chromium). Optionally a reference screenshot of the wanted look.
4. Branding: brand label + date for the top bar, endcard text, accent colours.

Names used below (pick them once, at intake): `<slug>` = kebab-case project id
(`projects/<slug>/`, e.g. `launch-news-ep2`); `<mediaDir>` = folder under
`remotion-composer/public/` (e.g. `launch-news`) = `EPISODE.assetDir`;
`<CompId>` = PascalCase component / composition id (e.g. `LaunchNewsYT`);
`<name>` = camelCase module prefix for `src/<name>Captions.ts` and
`src/<name>Web.ts` (e.g. `launchNews`) — the same string goes into the
capture config's `tsOut` and the composition's two imports.

Infra assumed: `remotion-composer/` app, karaoke venv at
`~/.cache/karaoke-subtitle/venv`, ffmpeg, `playwright` npm package resolvable
from `~/node_modules` or global (`cd ~ && npm i playwright@1.62 && npx
playwright install chromium`), pixabay registry tools (`PIXABAY_API_KEY` in
`.env`), Kanit fonts in `remotion-composer/public/fonts/`.

## Pipeline at a glance

| # | Step | Output |
|---|------|--------|
| 0 | Workspace + governance | `projects/<slug>/`, checkpoints, decision log |
| 1 | Probe + intake | avatar copied into `public/<mediaDir>/`, `AV_CX` measured |
| 2 | Script + karaoke timing | `script.txt`, `<name>Captions.ts` |
| 3 | **Whisper rebase** | `line_starts.json` + word dump — the timing spine |
| 4 | Page recon + beat design | section→line map, BEATS table (≈7 beats per minute; 55 for the 7.6-min EP.1) |
| 5 | Web capture | `sec_*.png`, `quote_NN.png`, `chart_N.png`, `<name>Web.ts` (clips + rects) |
| 6 | B-roll + music | `public/<mediaDir>/broll/*.mp4` (1080p25), `bed.mp3` |
| 7 | Composition | `<CompId>.tsx` cloned from FableNewsYT + Root.tsx registration |
| 8 | QA stills | one still per beat, viewed, fixed |
| 9 | Render + mux | silent visual → `renders/<name>.mp4` with VO + bed |
| 10 | Deliver | frames from the muxed file checked, report with beat map |

## Step 0 — Workspace + governance

OpenMontage production ⇒ `projects/<slug>/{artifacts,assets/{web,broll,audio},renders}`,
hybrid-pipeline checkpoints and decision-log entries. **Read
`references/governance.md` before writing any artifact** — it lists the exact
schema enums. Present both composition runtimes in the composition-mode decision.

## Step 1 — Probe + intake

```bash
ffprobe -v error -select_streams v -show_entries stream=width,height,r_frame_rate,duration -of csv=p=0 AVATAR.mp4
mkdir -p remotion-composer/public/<mediaDir>/{broll,web}
cp AVATAR.mp4 remotion-composer/public/<mediaDir>/avatar_source.mp4   # COPY — the bundler ignores symlinks
```

Extract 3 frames (`ffmpeg -ss T -i AVATAR.mp4 -frames:v 1`), view them, note the
presenter's face-midline x in source px → `AV_CX` (EP.1: 940). `AV_CY` stays 540
for head-to-desk framing (the 9:16 crop is full source height); only if the
presenter is a tight head-and-shoulders shot set `AV_CY` to the chest midline
and check the card still contains the whole head. After Step 3, assert the
avatar's ffprobe duration ≥ last word `end` in `line_starts.json` + 0.3 —
otherwise the SRT and the video are not the same take.

## Step 2 — Script + karaoke timing

```bash
python3 .Codex/skills/Youtube-Web-News-Style01-V1/scripts/srt_to_script.py --srt SOURCE.srt --out projects/<slug>/artifacts/script.txt
ffmpeg -v error -i AVATAR.mp4 -vn -ac 1 -ar 16000 -y projects/<slug>/assets/audio/vo16k.wav
~/.cache/karaoke-subtitle/venv/bin/python .Codex/skills/karaoke_subtitle_v2/scripts/extract_timing.py \
  --wav projects/<slug>/assets/audio/vo16k.wav --script projects/<slug>/artifacts/script.txt --out projects/<slug>/artifacts/caption_pages.json
python3 .Codex/skills/karaoke_subtitle_v2/scripts/repage.py --pages projects/<slug>/artifacts/caption_pages.json \
  --script projects/<slug>/artifacts/script.txt --out-pages projects/<slug>/artifacts/caption_pages_final.json \
  --out-ts remotion-composer/src/<name>Captions.ts
```

Accept only `violations: 0` and aligned chars ≈ script chars (EP.1: 4852 vs 4813).
Whisper large-v3 takes ~3 min for a 7.6-min VO — start it in the background
first and do page recon while it runs.

## Step 3 — Whisper rebase (the timing spine)

```bash
python3 .Codex/skills/Youtube-Web-News-Style01-V1/scripts/line_starts.py \
  --pages projects/<slug>/artifacts/caption_pages_final.json --script projects/<slug>/artifacts/script.txt --out projects/<slug>/artifacts/line_starts.json
python3 .Codex/skills/Youtube-Web-News-Style01-V1/scripts/words_by_line.py \
  projects/<slug>/artifacts/caption_pages_final.json projects/<slug>/artifacts/script.txt        # add line numbers to filter
```

- `VO_END_SEC` = last line's `end` in `line_starts.json` + 0.3; `TOTAL_DURATION_SEC` = `VO_END_SEC` + 4.4.
- Beat `t` = whisper `start` of the script line that opens the beat.
- Stat chips, highlight reveals, chip lists, CTA = the `s` of the exact word
  (`25%`, `Millennium`, `สรุป`, `Codex.ai`…) from the word dump.
- Mid-line transitions ("เรื่องที่สอง…") = the `s` of that word.
- **Never type a time read from the SRT into the composition.**

## Step 4 — Page recon + beat design

```bash
node .Codex/skills/Youtube-Web-News-Style01-V1/scripts/explore_page.mjs "<URL>"   # h1/h2 positions, tabs, buttons, <video> sources
npx playwright screenshot --full-page --viewport-size=1100,900 --wait-for-timeout=6000 "<URL>" full.png   # then tile + view it
```

Map every script line to a page section (or to b-roll / typography when the
page has nothing for it), then write the BEATS table following
`references/format-spec.md`. Compressed rules:

- Open full-frame 10–14 s with the BREAKING lower-third; return to full-frame
  for 2–7 s at every rhetorical turn ("ทีนี้มาดู…", "แล้ว…ต่างกันยังไง?",
  "สรุปสุดท้าย"); close full-frame (~20 s) with the CTA chip; endcard after
  `VO_END_SEC`.
- Company/customer stories: b-roll intro (3 s, headline = company) → the page's
  quote card with 1–2 highlights + stat chips.
- Numbers the presenter says out loud get a `stats` chip at the word time and,
  when the page states them, a highlight on that sentence.
- Alternate media types; never two b-roll beats of the same clip back to back;
  beats run 3–16 s; ~7 beats per minute.

## Step 5 — Web capture (exact sentences, exact coordinates)

Write `projects/<slug>/artifacts/capture-config.json` from
`assets/capture-config.example.json` (sections anchored to heading text, the
phrases to highlight per section, tables, tabbed charts, quote carousel), then:

```bash
node .Codex/skills/Youtube-Web-News-Style01-V1/scripts/capture_page.mjs projects/<slug>/artifacts/capture-config.json
cp projects/<slug>/assets/web/*.png remotion-composer/public/<mediaDir>/web/
```

Fix every `MISS` / `ANCHOR MISS` in the log (wrong wording, hyphen variant,
wrong `nth`) and re-run — rects and PNGs must come from the **same run**.
Naming convention the composition relies on: `sec_<section>.png` ↔
`WEB_CLIPS[<section>]`, `<carousel>_NN.png` ↔ `WEB_CLIPS[<carousel>]`,
`<tabs>_N.png` ↔ `WEB_CLIPS["<tabs>_N"]` — beats reference the file name
without `.png`; `cssH` is only needed for a capture that isn't in `WEB_CLIPS`
(read its `h` from the `tab`/`section` log line or `web_data.json`).
Details and traps: `references/web-capture.md`. Make each section capture
**taller than the viewport (≥ 800 css px)** when the beat must scroll to a
sentence; short captures are centred instead of scrolled.

## Step 6 — B-roll + music ($0)

```bash
.venv/bin/python .Codex/skills/Youtube-Web-News-Style01-V1/scripts/fetch_broll.py projects/<slug>/artifacts/broll-queries.json projects/<slug>/assets/broll --music "technology corporate inspiring background" projects/<slug>/assets/audio/bed.mp3
bash .Codex/skills/Youtube-Web-News-Style01-V1/scripts/transcode_broll.sh projects/<slug>/assets/broll remotion-composer/public/<mediaDir>/broll
```

`broll-queries.json` = `{"key": ["search query", "pixabay category"]}` — start
from `assets/broll-queries.example.json` (it lists the category vocabulary).
Build a contact sheet of first frames and **view it** — replace wrong picks with
a new query (EP.1 swapped 3 of 14). Page-hosted `<video>` assets (from
`videos.json`) are the best b-roll: transcode them too and present them as
`clip` beats with the OFFICIAL tag. Paste the printed durations into `BROLL_DUR`.

## Step 7 — Composition

```bash
cp remotion-composer/src/FableNewsYT.tsx remotion-composer/src/<CompId>.tsx
```

Swap, in this order:

1. Component / comp id / metadata fn names (`FableNewsYT` → `<CompId>`).
2. The two data imports: `./<name>Captions` and `./<name>Web`.
3. `VO_END_SEC` (last word end + 0.3) and `TOTAL_DURATION_SEC` (+4.4 s endcard).
4. `AV_CX` (Step 1 measurement).
5. **`EPISODE` block** — every on-screen string lives there: `assetDir`
   (= `<mediaDir>`), `brand`, `dateLabel`, `page.domain/path` (browser chrome
   URL pill), `officialTag`, `cta`, `endcard.*`, `summary3Label`, `final4.*`,
   `vs.*` (both card titles/badges/lines, eyebrow, conclusion).
6. `BROLL_DUR` (paste from `transcode_broll.sh`).
7. `BEATS`, then the word-timed arrays the typo scenes read: `SUMMARY3`,
   `FINAL4`, `VS` (three word times), `CTA_T`.

Grep the clone for the previous episode's strings (`fable`, `Mythos`,
`anthropic`, `Codex.ai`) before rendering — anything left outside `EPISODE`
and `BEATS` is a bug in the reference, fix it there too. Register in
`Root.tsx` (props type must be a `type` alias, not an interface).
**Locked**: morph math, stage geometry, caption lane, chip/kicker/stage
components (their copy comes from `EPISODE`/`BEATS`, never edit literals).

## Step 8 — QA stills (view every one)

```bash
node .Codex/skills/Youtube-Web-News-Style01-V1/scripts/stills.mjs <CompId> 75,388,1320,... remotion-composer/out/qa remotion-composer
```

Frame = `round((beat.t + 2) × 25)` — one frame ≈ 2 s into every beat, plus 3
frames inside a morph (`t`, `t + 0.2`, `t + 0.4` s of a mode change). Tile them
2×2 and check: highlight sits on the sentence being spoken; stat chips don't
cover the highlighted text (move the camera `fy`, not the chip); quote card
fully visible incl. COMPANY row; captions show the words being spoken; Thai
glyphs intact; nothing under the caption band.

## Step 9 — Render + mux

```bash
cd remotion-composer && npx remotion render src/index.tsx <CompId> out/<name>_visual.mp4 --concurrency=5 --crf=18   # ≈ 8 min for a 7.6-min video on M4 Pro
bash .Codex/skills/Youtube-Web-News-Style01-V1/scripts/mux_av.sh remotion-composer/out/<name>_visual.mp4 AVATAR.mp4 projects/<slug>/assets/audio/bed.mp3 projects/<slug>/renders/<name>.mp4 <TOTAL> <VO_END>
```

Accept: duration = TOTAL ± 0.1 s; mean loudness within 1 dB of the source VO
(EP.1: −19.1 vs −19.2 dB); max ≤ −1 dB.

## Step 10 — Deliver

Extract ~14 frames from the **muxed** file + 3 mid-morph frames, view them,
then report: deliverable path, beat map summary, asset sources/licences, and
anything left out. Write the compose checkpoint + final_review.

## Gotchas (each cost real time on EP.1)

| Trap | Fix |
|------|-----|
| SRT times drift vs audio | Rebase everything to whisper (Step 3) |
| Remotion `public/` symlinks → 404 in render | Copy files, never symlink |
| Interface props type fails `Record<string, unknown>` | `export type <CompId>Props = {…}` |
| Page charts blank in capture | Scroll the whole page once before capturing (script does) |
| `Terminal-Bench 4.0` phrase not found | Site uses U+2011 non-breaking hyphens — script normalises; check `nth` |
| Carousel arrow buttons "not visible" | Use the text `Next` pagination button (config `nextSelector` + `nextText`) |
| Page height differs between loads (±40 px) | Anchor sections to headings; rects + PNGs in one run |
| Short capture leaves half the frame blank | Composition centres captures shorter than the viewport; else capture taller |
| Highlight hidden under stat chips | Camera `fy` so the sentence lands mid-viewport (chips live at the bottom) |
| 21 parallel ffmpeg transcodes timed out | `transcode_broll.sh` runs sequentially |
| `timeout` command missing on macOS | Use `nohup … &` + log polling |
| Parallel Bash calls share `cd` state | Run everything from the repo root, or use absolute paths when calls run in parallel |
| `load_dotenv()` AssertionError from stdin | `load_dotenv('.env')` |
| Stock pick is wrong (blender for "shopping") | Contact sheet + re-query before transcoding |
