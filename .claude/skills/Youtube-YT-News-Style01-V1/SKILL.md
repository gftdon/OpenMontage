---
name: Youtube-YT-News-Style01-V1
description: Use when turning an AI-avatar presenter take (mp4 + SRT) and a YOUTUBE VIDEO LINK into a 16:9 YouTube news report — the presenter morphs between full-frame and a vertical 9:16 card on the RIGHT while the LEFT stage shows clips cut from the YouTube source video, matched to whatever the presenter is talking about (plus stock b-roll and Thai typography scenes). Triggers - "ตัดต่อวิดีโอรายงานข่าวจากคลิปยูทูป", "ทำวิดีโอข่าวจากลิงก์ YouTube", "อ่านข่าวจากคลิป YouTube + avatar", "YT news V1", "Youtube-YT-News-Style01", "สร้างวิดีโอสรุปคลิปยูทูป", "แสดง footage จากคลิปต้นฉบับตรงกับที่ Avatar พูด", or any avatar mp4 + SRT + youtube.com/watch brief — even if the user doesn't name this skill. NOT for web-article sources (use Youtube-Web-News-Style01-V1/V2), 9:16 reels, or the bottom-left PiP tutorial format (use Youtube-Tutor-Style01-V1).
---

# Youtube-YT-News-Style01-V1 — avatar + YouTube source ➜ 16:9 news report

Reference implementation: `remotion-composer/src/TripoYTNewsV1.tsx` (comp id
`TripoYTNewsV1`, 1920×1080 @ 25 fps, 374.5 s = 370.1 s VO + endcard). First
delivered episode: `projects/tripo-game-news-yt/renders/TripoYTNews_V1.mp4`
(RemakeBench "I let 4 AI Build this Game From Scratch", delivered as
`V260915_001_40_Long_Final.mp4`). The stage/morph engine is cloned from
`FableNewsYT.tsx` — a snapshot of that file lives in
`assets/FableNewsYT.reference.tsx` in case the live file moves.
**Clone the reference and swap the data — do not rebuild the format.**

This is the **YouTube-source sibling** of `Youtube-Web-News-Style01-V1`:
identical stage, avatar morph, captions, typo scenes and audio pipeline — but
the report subject is a YouTube video, so instead of Playwright page captures
the left stage plays **clips cut from the source video**. Everything about the
visual format is in `references/format-spec.md`; everything about the source
recon is in `references/yt-source.md` (read it before cutting).

Anatomy (compressed): dark navy stage + dot grid. **Left stage** (1210×840)
shows one of: a source-video clip in a light **museum card** with a
`SOURCE · <CHANNEL>` tag (`clip` beat), a source clip or stock footage
**full-bleed** with a kinetic Thai headline (`broll` beat), or a **typography
scene** (`summary3` / `vs` / `final4`). **Avatar** = one continuous
`OffthreadVideo` morphing (uniform scale) between full-frame and a 9:16 anchor
card on the right (478×850 at x=1362). Overlays: brand top bar + amber kicker
per beat, stat chips that pop on word times, BREAKING lower-third on the cold
open, CTA chip, gold karaoke caption lane (locked), progress bar, endcard.
Music bed ducked under the VO. Remotion renders are **silent** — mux after.

## Inputs (ask only for what's missing)

1. **Avatar video** — one continuous take, 1920×1080 preferred; any fps.
2. **SRT** whose text is the exact spoken script. Text is trusted; **cue times
   are not** (they drift seconds — everything is rebased to whisper).
3. **YouTube URL** of the video being reported on (must be downloadable with
   yt-dlp). The workflow's script step usually embeds it in the task prompt.
4. Branding: brand label + date for the top bar, endcard text, accent tones if
   different from the locked set.

Names used below (pick once, at intake): `<slug>` = kebab-case project id
(`projects/<slug>/`); `<mediaDir>` = folder under `remotion-composer/public/`
(= `EPISODE.assetDir`); `<CompId>` = PascalCase component/composition id (e.g.
`TripoYTNewsV1`); `<name>` = camelCase module prefix for `src/<name>Captions.ts`.

Infra assumed: `remotion-composer/` app, karaoke venv at
`~/.cache/karaoke-subtitle/venv`, ffmpeg, `yt-dlp` (+ this repo's
`video-download` skill), pixabay registry tools (`PIXABAY_API_KEY` in `.env`),
Kanit fonts in `remotion-composer/public/fonts/`.

## Pipeline at a glance

| # | Step | Output |
|---|------|--------|
| 0 | Workspace + governance | `projects/<slug>/`, checkpoints, decision log |
| 1 | Probe + intake | avatar copied into `public/<mediaDir>/`, `AV_CX` measured |
| 2 | Script + karaoke timing | `script.txt`, `<name>Captions.ts` |
| 3 | **Whisper rebase** | `line_starts.json` + word dump — the timing spine |
| 4 | **YT recon** | download, chapters, contact sheets, line→range map |
| 5 | **Clip cutting** | `yt_*.mp4` (1080p25, muted) + `BROLL_DUR` lines |
| 6 | Stock b-roll + music | `public/<mediaDir>/broll/*.mp4`, `bed.mp3` |
| 7 | Composition | `<CompId>.tsx` cloned from FableNewsYT + Root.tsx registration |
| 8 | QA stills | one still per beat, viewed, fixed |
| 9 | Render + mux | silent visual → `renders/<name>.mp4` with VO + bed |
| 10 | Deliver | frames from the muxed file checked, report with beat map |

## Step 0 — Workspace + governance

OpenMontage production ⇒ `projects/<slug>/{artifacts,assets/{ytsource/clips,broll,audio},renders}`,
hybrid-pipeline checkpoints and decision-log entries. **Read
`references/governance.md` before writing any artifact.**

If a previous run of the same episode exists (e.g. a V2 build), **reuse its
whisper artifacts** (`caption_pages_final.json`, `line_starts.json`,
`<name>Captions.ts`), its `avatar_source.mp4` copy, stock b-roll and
`bed.mp3` — Steps 1–3 and 6 are already done. Verify the avatar file is the
same take (compare ffprobe duration) before trusting the timing.

## Step 1 — Probe + intake

```bash
ffprobe -v error -select_streams v -show_entries stream=width,height,r_frame_rate,duration -of csv=p=0 AVATAR.mp4
mkdir -p remotion-composer/public/<mediaDir>/{broll,web}
cp AVATAR.mp4 remotion-composer/public/<mediaDir>/avatar_source.mp4   # COPY — the bundler ignores symlinks
```

Extract 3 frames, view them, note the presenter's face-midline x in source px
→ `AV_CX`. `AV_CY` stays 540 for head-to-desk framing (see
`references/format-spec.md` for when to move it). After Step 3, assert avatar
duration ≥ last word `end` in `line_starts.json` + 0.3 — otherwise the SRT and
the video are not the same take.

## Step 2 — Script + karaoke timing

```bash
python3 .claude/skills/Youtube-YT-News-Style01-V1/scripts/srt_to_script.py --srt SOURCE.srt --out projects/<slug>/artifacts/script.txt
ffmpeg -v error -i AVATAR.mp4 -vn -ac 1 -ar 16000 -y projects/<slug>/assets/audio/vo16k.wav
~/.cache/karaoke-subtitle/venv/bin/python .claude/skills/karaoke_subtitle_v2/scripts/extract_timing.py \
  --wav projects/<slug>/assets/audio/vo16k.wav --script projects/<slug>/artifacts/script.txt --out projects/<slug>/artifacts/caption_pages.json
python3 .claude/skills/karaoke_subtitle_v2/scripts/repage.py --pages projects/<slug>/artifacts/caption_pages.json \
  --script projects/<slug>/artifacts/script.txt --out-pages projects/<slug>/artifacts/caption_pages_final.json \
  --out-ts remotion-composer/src/<name>Captions.ts
```

Accept only `violations: 0`. Whisper large-v3 takes ~3 min for a 7-min VO —
start it in the background and do Step 4 recon while it runs.

## Step 3 — Whisper rebase (the timing spine)

```bash
python3 .claude/skills/Youtube-YT-News-Style01-V1/scripts/line_starts.py \
  --pages projects/<slug>/artifacts/caption_pages_final.json --script projects/<slug>/artifacts/script.txt --out projects/<slug>/artifacts/line_starts.json
python3 .claude/skills/Youtube-YT-News-Style01-V1/scripts/words_by_line.py \
  projects/<slug>/artifacts/caption_pages_final.json projects/<slug>/artifacts/script.txt
```

- `VO_END_SEC` = last line's `end` + 0.3; `TOTAL_DURATION_SEC` = `VO_END_SEC` + 4.4.
- Beat `t` = whisper `start` of the script line that opens the beat.
- Stat chips, CTA, mid-line transitions = the `s` of the exact word.
- **Never type a time read from the SRT into the composition.**

## Step 4 — YT recon (replaces page recon)

```bash
bash .claude/skills/Youtube-YT-News-Style01-V1/scripts/yt_survey.sh "<YOUTUBE_URL>" projects/<slug>/assets/ytsource
```

Gives `source.mp4` (1080p cut master), `chapters.txt` (YouTube chapters = the
section map) and two contact sheets. Then **read `references/yt-source.md`**
and follow its look-before-you-cut protocol: sheets → chapter-midpoint frames
→ per-clip arc tiles. Map every script line to a source range (or to stock
b-roll / a typo scene when the source has nothing for it — generic wisdom
segments are stock b-roll, never forced source footage). Design the BEATS
table with the same rules as the web format: full-frame open 10–14 s with the
BREAKING lower-third, full-frame 2–7 s at every rhetorical turn, full-frame
close with the CTA chip, endcard after `VO_END_SEC`, 3–16 s beats, ~7 per
minute, never the same clip twice in a row.

## Step 5 — Clip cutting

```bash
bash .claude/skills/Youtube-YT-News-Style01-V1/scripts/cut_clips.sh \
  projects/<slug>/assets/ytsource/source.mp4 projects/<slug>/assets/ytsource/clips \
  yt_fight:6:17 yt_pipeline:38:62 yt_ui:150:172 ...
cp projects/<slug>/assets/ytsource/clips/*.mp4 remotion-composer/public/<mediaDir>/broll/
```

Name clips `yt_<topic>` (no collisions with stock keys), pad in-points 2–3 s,
make every clip longer than its beat, never include the source's
sponsor/promo-code segments. Paste the printed durations into `BROLL_DUR`.

## Step 6 — Stock b-roll + music

```bash
.venv/bin/python .claude/skills/Youtube-YT-News-Style01-V1/scripts/fetch_broll.py projects/<slug>/artifacts/broll-queries.json projects/<slug>/assets/broll --music "technology corporate inspiring background" projects/<slug>/assets/audio/bed.mp3
bash .claude/skills/Youtube-YT-News-Style01-V1/scripts/transcode_broll.sh projects/<slug>/assets/broll remotion-composer/public/<mediaDir>/broll
```

`broll-queries.json` = `{"key": ["search query", "pixabay category"]}` — start
from `assets/broll-queries.example.json`. Build a contact sheet of first
frames and **view it** — and view first frames of any stock you inherit from a
previous run too (a `gladiator.mp4` that actually contains yellow banking text
shipped once). Pixabay music/footage is YouTube-safe under the Pixabay Content
License — state this in the delivery report.

## Step 7 — Composition

```bash
cp remotion-composer/src/FableNewsYT.tsx remotion-composer/src/<CompId>.tsx
```

Swap, in this order:

1. Component / comp id / metadata fn names (`FableNewsYT` → `<CompId>`).
2. The data imports: `./<name>Captions`, and `./<name>Web` (any existing module
   exporting `WEB_CLIPS`/`WEB_RECTS`/`WebRect` — unused without `web` beats,
   but the engine references the symbols; reusing a previous run's module is
   the easy path).
3. `VO_END_SEC` (last word end + 0.3) and `TOTAL_DURATION_SEC` (+4.4 s endcard).
4. `AV_CX` (Step 1 measurement).
5. **`EPISODE` block** — every on-screen string: `assetDir`, `brand`,
   `dateLabel`, `officialTag` = `SOURCE · <CHANNEL>`, `cta`, `endcard.*`
   (credit the source channel in `endcard.sub`), `summary3Label`,
   `final4.*`, `vs.*`.
6. `BROLL_DUR` (stock + `cut_clips.sh` output).
7. `BEATS`, then the word-timed arrays: `SUMMARY3`, `FINAL4`, `VS`, `CTA_T`.

Beat media choices: `clip` (museum card) for source UI/diagram/dashboard
footage — `clipFit: "contain"` when edge UI matters, `"cover"` for cinematic
shots; `broll` (full-bleed + headline) for action source clips and stock;
`typo` for the three typography scenes. Grep the clone for the previous
episode's strings before rendering. Register in `Root.tsx` (props type must be
a `type` alias, not an interface). **Locked**: morph math, stage geometry,
caption lane, chip/kicker/stage components.

## Step 8 — QA stills (view every one)

```bash
node .claude/skills/Youtube-YT-News-Style01-V1/scripts/stills.mjs <CompId> 75,312,572,... remotion-composer/out/qa remotion-composer
```

Frame = `round((beat.t + 2) × 25)` — one frame ≈ 2 s into every beat, plus 3
frames inside a morph. Tile 2×2 and check: the source clip shows what the
sentence is about **at that moment** (not 3 s later — if the visual arrives
late, re-cut the clip earlier, don't move the beat); headlines/sub match;
stat chips don't cover key content; captions show the words being spoken; Thai
glyphs intact.

## Step 9 — Render + mux

```bash
cd remotion-composer && npx remotion render src/index.tsx <CompId> out/<name>_visual.mp4 --concurrency=5 --crf=18
bash .claude/skills/Youtube-YT-News-Style01-V1/scripts/mux_av.sh remotion-composer/out/<name>_visual.mp4 AVATAR.mp4 projects/<slug>/assets/audio/bed.mp3 projects/<slug>/renders/<name>.mp4 <TOTAL> <VO_END>
```

Accept: duration = TOTAL ± 0.1 s; mean loudness within 1 dB of the source VO;
max ≤ −1 dB.

## Step 10 — Deliver

Extract ~14 frames from the **muxed** file + 3 mid-morph frames, view them,
then report: deliverable path, beat map summary, clip ranges used
(source-timestamped), asset sources/licences (YouTube source = commentary/
news-use clip excerpts with on-screen `SOURCE ·` attribution + endcard
credit; Pixabay for stock + music), and anything left out. Copy the file to
the workflow's requested artifact name if one exists (e.g.
`<Video Code>_40_Long_Final.mp4`). Write the compose checkpoint +
final_review.

## Gotchas (each cost real time on the trial episode)

| Trap | Fix |
|------|-----|
| SRT times drift vs audio | Rebase everything to whisper (Step 3) |
| `ClipStage` ignores `from` (loops from 0) | Only `broll` beats honour `from`; re-cut the clip instead |
| Beat opens on a title card / file dialog / chart | Survey the exact arc (`fps=1/2,tile`) before cutting; pad in-points 2–3 s |
| Survey frame ≠ renderer frame (~1 s drift) | Verify with a QA still 2 s into the beat; re-cut, don't nudge the beat |
| Inherited stock b-roll is mislabeled | Contact-sheet **every** stock clip, including from previous runs |
| Source's sponsor end card leaks in | Never cut from the promo segment; check the last chapter |
| Remotion `public/` symlinks → 404 in render | Copy files, never symlink |
| Interface props type fails `Record<string, unknown>` | `export type <CompId>Props = {…}` |
| Foreign numbers on screen the VO never says | Only with a Thai headline/sub that explains them |
| 🃏/👇-class emoji break headless Chrome | Use common emoji only (🎮💻🎨🎵📚📐📱🛍️✅ proven) |
| Render is silent | `mux_av.sh` is mandatory; check loudness accept criteria |
| Long whisper run blocks the pipeline | Background it (Step 2) and do YT recon meanwhile |
