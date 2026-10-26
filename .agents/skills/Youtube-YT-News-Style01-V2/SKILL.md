---
name: Youtube-YT-News-Style01-V2
description: Use when turning an AI-avatar presenter take (mp4 + SRT) and a YOUTUBE VIDEO LINK into a 16:9 YouTube news report — the presenter morphs between full-frame and a vertical 9:16 card on the RIGHT while the LEFT stage shows clips cut from the YouTube source video, matched to whatever the presenter is talking about (plus stock b-roll and Thai typography scenes). Triggers - "ตัดต่อวิดีโอรายงานข่าวจากคลิปยูทูป", "ทำวิดีโอข่าวจากลิงก์ YouTube", "อ่านข่าวจากคลิป YouTube + avatar", "YT news V1", "YT news V2", "Youtube-YT-News-Style01", "สร้างวิดีโอสรุปคลิปยูทูป", "แสดง footage จากคลิปต้นฉบับตรงกับที่ Avatar พูด", or any avatar mp4 + SRT + youtube.com/watch brief — even if the user doesn't name this skill. Supersedes `Youtube-YT-News-Style01-V1` — same video format, but enforces NO repeated footage inside a video and FRESH stock b-roll for every video (at most 2 previously used files). NOT for web-article sources (use Youtube-Web-News-Style01-V1/V2), 9:16 reels, or the bottom-left PiP tutorial format (use Youtube-Tutor-Style01-V1).
---

# Youtube-YT-News-Style01-V2 — avatar + YouTube source ➜ 16:9 news report

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

## What changed in V2

Same video format as `Youtube-YT-News-Style01-V1` (its historical predecessor).
Only B-roll handling changed — V1 episodes all shipped the same 8 stock files
(a previous episode's `broll/` was copied forward, `fetch_broll.py` skipped
existing files) and repeated a file 3–4× inside one video (V1 only forbade the
same clip twice in a row). V2 adds:

- a ledger of which stock files each episode used (`projects/_broll_ledger.json`);
- `fetch_broll.py` that skips every clip the ledger knows (and reserves the ids
  it downloads, so a parallel video job cannot take the same clip) → fresh stock
  per video;
- `check_broll.py` gate (Step 8b) that fails the render on any repeat or
  non-fresh footage;
- the rules below.

## B-roll freshness rules (mandatory)

- Every footage file — stock `<key>.mp4` **and** source clip `yt_*.mp4` —
  appears in **at most ONE beat** of the video, typo-scene backgrounds
  included. Need more visuals? Fetch another stock clip, or cut a different
  time range of the source as a new `yt_` file (a different range = a different
  clip; the same range under two names is still a repeat).
- Every `broll` / `clip` / `typo` beat sets `src` explicitly (a missing `src`
  silently falls back to a default file).
- Stock b-roll is downloaded **fresh for every video**. **Fresh** = a stock file
  that `fetch_broll.py` downloaded for THIS episode (it is a key in this
  episode's `_manifest.json`, raw file unchanged) AND whose content matches no
  other episode's file. Anything else is **old**. At most **2** old files per
  video, and only as a deliberate choice: copy that specific file, log it in
  `decision_log.json` (category `fallback_decision`); it still counts once.
  Detection is by **content** — renaming or re-copying a file does not make it
  fresh. A `yt_` clip whose content matches another episode's file is a hard
  failure (`yt_` clips are cut from THIS episode's source only).
- Every new video gets a NEW `<slug>` and a NEW `<mediaDir>`; reusing them is
  only for re-running the same episode.
- Never copy another episode's `remotion-composer/public/<other>/broll/` or
  `projects/<other>/assets/broll/`. Never use the example query file's
  keys/queries verbatim: write queries from THIS episode's script lines
  (concrete nouns/actions), descriptive key names (`price_tag_half`, not
  `office`), one key per beat that needs stock + ~30% spares (the first hit is
  wrong ~1 in 5).
- `check_broll.py` must pass before render (Step 8b); run
  `broll_ledger.py record` after delivery (Step 10). Order: fetch_broll →
  transcode_broll.sh → composition (explicit `src` everywhere, no repeats,
  `assetDir` = `<mediaDir>`) → QA stills → `check_broll.py` → render → record.

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
| 6 | **Fresh** stock b-roll + music | `_manifest.json`, `public/<mediaDir>/broll/*.mp4`, `bed.mp3` |
| 7 | Composition | `<CompId>.tsx` cloned from FableNewsYT + Root.tsx registration |
| 8 | QA stills | one still per beat, viewed, fixed |
| 8b | **B-roll gate** | `check_broll.py` exits 0 |
| 9 | Render + mux | silent visual → `renders/<name>.mp4` with VO + bed |
| 10 | Deliver | frames from the muxed file checked, ledger recorded, report with beat map + B-roll line |

## Step 0 — Workspace + governance

OpenMontage production ⇒ `projects/<slug>/{artifacts,assets/{ytsource/clips,broll,audio},renders}`,
hybrid-pipeline checkpoints and decision-log entries. **Read
`references/governance.md` before writing any artifact.**

If a previous run of the **same episode** exists, **reuse its whisper
artifacts** (`caption_pages_final.json`, `line_starts.json`,
`<name>Captions.ts`), its `avatar_source.mp4` copy, `bed.mp3` and that same
episode's own b-roll — Steps 1–3 are already done. Verify the avatar file is
the same take (compare ffprobe duration) before trusting the timing. **Never**
reuse stock b-roll from a different episode (see B-roll freshness rules).

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
python3 .claude/skills/Youtube-YT-News-Style01-V2/scripts/srt_to_script.py --srt SOURCE.srt --out projects/<slug>/artifacts/script.txt
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
python3 .claude/skills/Youtube-YT-News-Style01-V2/scripts/line_starts.py \
  --pages projects/<slug>/artifacts/caption_pages_final.json --script projects/<slug>/artifacts/script.txt --out projects/<slug>/artifacts/line_starts.json
python3 .claude/skills/Youtube-YT-News-Style01-V2/scripts/words_by_line.py \
  projects/<slug>/artifacts/caption_pages_final.json projects/<slug>/artifacts/script.txt
```

- `VO_END_SEC` = last line's `end` + 0.3; `TOTAL_DURATION_SEC` = `VO_END_SEC` + 4.4.
- Beat `t` = whisper `start` of the script line that opens the beat.
- Stat chips, CTA, mid-line transitions = the `s` of the exact word.
- **Never type a time read from the SRT into the composition.**

## Step 4 — YT recon (replaces page recon)

```bash
bash .claude/skills/Youtube-YT-News-Style01-V2/scripts/yt_survey.sh "<YOUTUBE_URL>" projects/<slug>/assets/ytsource
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
minute, never the same clip twice anywhere in the video (one file = one beat).

## Step 5 — Clip cutting

```bash
bash .claude/skills/Youtube-YT-News-Style01-V2/scripts/cut_clips.sh \
  projects/<slug>/assets/ytsource/source.mp4 projects/<slug>/assets/ytsource/clips \
  yt_fight:6:17 yt_pipeline:38:62 yt_ui:150:172 ...
cp projects/<slug>/assets/ytsource/clips/*.mp4 remotion-composer/public/<mediaDir>/broll/
```

Name clips `yt_<topic>` (no collisions with stock keys), pad in-points 2–3 s,
make every clip longer than its beat, never include the source's
sponsor/promo-code segments. Clips are distinct files with distinct source
ranges — never cut the same range twice under two names, never use one clip
for two beats. Paste the printed durations into `BROLL_DUR`.

## Step 6 — Fresh stock b-roll + music

```bash
# write projects/<slug>/artifacts/broll-queries.json from THIS episode's script (see below)
.venv/bin/python .claude/skills/Youtube-YT-News-Style01-V2/scripts/fetch_broll.py projects/<slug>/artifacts/broll-queries.json projects/<slug>/assets/broll --ledger projects/_broll_ledger.json --music "technology corporate inspiring background" projects/<slug>/assets/audio/bed.mp3
bash .claude/skills/Youtube-YT-News-Style01-V2/scripts/transcode_broll.sh projects/<slug>/assets/broll remotion-composer/public/<mediaDir>/broll
```

1. `broll-queries.json` = `{"key": ["search query", "pixabay category"]}`.
   `assets/broll-queries.example.json` shows the FORMAT only — its `example_*`
   keys and queries must not be reused. Write queries from this episode's script
   lines (concrete nouns/actions), descriptive keys, one key per stock beat +
   ~30% spares. Keys starting with `_` are ignored.
2. `fetch_broll.py QUERIES.json OUT_DIR` — `OUT_DIR` must be the project's raw
   folder `projects/<slug>/assets/broll` (the slug is read from it). It searches
   Pixabay page by page and skips clips the ledger already knows (by id, and by
   md5 after download), so similar queries still return a different clip. It
   seeds the ledger automatically (`broll_ledger.py seed` stays available as an
   optional manual command), reserves the ids it downloads, and writes
   `OUT_DIR/_manifest.json` (key → pixabay id, url, md5). Exit 1 if any key
   failed:
   - `no fresh clip — use a more specific query` → rewrite that query.
   - `existing file was not fetched by fetch_broll (copied?) — delete it and re-run`
     → the raw file in `OUT_DIR` was not downloaded by the tool; delete it.
   - `--dry-run` previews picks without downloading.
3. `transcode_broll.sh` re-encodes when the raw file is newer than the existing
   output. Replacing a wrong pick = delete/replace the raw file, re-fetch with a
   new query, re-run transcode. If you rename or drop a key, also delete the
   stale `public/<mediaDir>/broll/<key>.mp4`.
4. Build a contact sheet of first frames of every fetched clip and **view it**
   (a `gladiator.mp4` that actually contained yellow banking text shipped once).
   Replace wrong picks with new, more specific queries — never with another
   episode's file.
5. Optional, at most 2: a deliberate old file — copy that specific transcoded
   file from `remotion-composer/public/<other>/broll/` straight into
   `remotion-composer/public/<mediaDir>/broll/` (never into
   `projects/<slug>/assets/broll/` — fetch_broll fails on files it did not
   fetch), log it in `decision_log.json` (`fallback_decision`). The gate counts
   it as old.

Pixabay music/footage is YouTube-safe under the Pixabay Content License — state
this in the delivery report.

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
5. **`EPISODE` block** — every on-screen string: `assetDir` (**must equal
   `<mediaDir>`** — the clone ships `"fable-news"`; the gate fails otherwise), `brand`,
   `dateLabel`, `officialTag` = `SOURCE · <CHANNEL>`, `cta`, `endcard.*`
   (credit the source channel in `endcard.sub`), `summary3Label`,
   `final4.*`, `vs.*`.
6. `BROLL_DUR` (stock + `cut_clips.sh` output).
7. `BEATS`, then the word-timed arrays: `SUMMARY3`, `FINAL4`, `VS`, `CTA_T`.

Beat media choices: `clip` (museum card) for source UI/diagram/dashboard
footage — `clipFit: "contain"` when edge UI matters, `"cover"` for cinematic
shots; `broll` (full-bleed + headline) for action source clips and stock;
`typo` for the three typography scenes. Set `src` explicitly on every `broll`/`clip`/`typo` beat. Keep `BEATS` as one
inline `const BEATS: Beat[] = [ ... ];` of object literals with literal
`media`/`src` (no spreads, `.map`, helper calls or later mutation — the gate
cannot parse them safely). Grep the clone for the previous
episode's strings before rendering. Register in `Root.tsx` (props type must be
a `type` alias, not an interface). **Locked**: morph math, stage geometry,
caption lane, chip/kicker/stage components.

## Step 8 — QA stills (view every one)

```bash
node .claude/skills/Youtube-YT-News-Style01-V2/scripts/stills.mjs <CompId> 75,312,572,... remotion-composer/out/qa remotion-composer
```

Frame = `round((beat.t + 2) × 25)` — one frame ≈ 2 s into every beat, plus 3
frames inside a morph. Tile 2×2 and check: the source clip shows what the
sentence is about **at that moment** (not 3 s later — if the visual arrives
late, re-cut the clip earlier, don't move the beat); headlines/sub match;
stat chips don't cover key content; captions show the words being spoken; Thai
glyphs intact.

## Step 8b — B-roll gate (right before the render)

```bash
.venv/bin/python .claude/skills/Youtube-YT-News-Style01-V2/scripts/check_broll.py remotion-composer/src/<CompId>.tsx --media-dir <mediaDir> --manifest projects/<slug>/assets/broll/_manifest.json
```

Optional flags: `--public-root remotion-composer/public`, `--projects-root
projects`, `--ledger projects/_broll_ledger.json`, `--max-old 0..2` (default 2,
capped at 2). It seeds the ledger itself. Exit 0 = PASS, 1 = violations,
2 = usage/parse error. It **FAILS** when:

- a `broll`/`clip`/`typo` beat has no explicit `src`;
- any `src` is used by more than one beat (typo-scene backgrounds count);
- a referenced file is missing, or two keys are the same file renamed;
- more than `--max-old` stock files are old (not fresh, see freshness rules);
- a `yt_` clip's content matches another episode's file;
- `EPISODE.assetDir` ≠ `--media-dir`;
- `<mediaDir>` was already delivered under a different composition;
- `BEATS` cannot be parsed safely (see Step 7).

On FAIL: fix `BEATS` / fetch more clips (Step 6) / cut new `yt_` ranges
(Step 5), re-run QA stills for every changed beat, re-check until PASS. Must
exit 0 before Step 9.

## Step 9 — Render + mux

```bash
cd remotion-composer && npx remotion render src/index.tsx <CompId> out/<name>_visual.mp4 --concurrency=5 --crf=18
bash .claude/skills/Youtube-YT-News-Style01-V2/scripts/mux_av.sh remotion-composer/out/<name>_visual.mp4 AVATAR.mp4 projects/<slug>/assets/audio/bed.mp3 projects/<slug>/renders/<name>.mp4 <TOTAL> <VO_END>
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

Mark this video's stock files as used:

```bash
.venv/bin/python .claude/skills/Youtube-YT-News-Style01-V2/scripts/broll_ledger.py record <mediaDir> --composition remotion-composer/src/<CompId>.tsx --manifest projects/<slug>/assets/broll/_manifest.json
```

`record` also stores the episode marker and refuses to re-bind a `<mediaDir>` to
another composition. The delivery report includes a **B-roll line**: `N fresh / M old (≤2)` with
file names, and confirmation that `check_broll.py` passed.

## Gotchas (each cost real time on the V1 episodes)

| Trap | Fix |
|------|-----|
| SRT times drift vs audio | Rebase everything to whisper (Step 3) |
| `ClipStage` ignores `from` (loops from 0) | Only `broll` beats honour `from`; re-cut the clip instead |
| Beat opens on a title card / file dialog / chart | Survey the exact arc (`fps=1/2,tile`) before cutting; pad in-points 2–3 s |
| Survey frame ≠ renderer frame (~1 s drift) | Verify with a QA still 2 s into the beat; re-cut, don't nudge the beat |
| Fetched stock b-roll is mislabeled | Contact-sheet **every** fetched clip; replace wrong picks with a more specific query (no inheriting across episodes) |
| Same 8 stock files in every episode | Fresh `fetch_broll.py` per video (ledger-aware, seeds itself); never copy another episode's `broll/` |
| Pixabay first hit is always the same video | `fetch_broll.py` (V2) skips ids/md5 the ledger knows — write more specific queries on `no fresh clip` |
| Same clip 3–4× in one video | `check_broll.py` gate (Step 8b): one file = one beat; fetch another clip or cut a new `yt_` range |
| Copied an old raw/public file into this episode | Gate fails by content (renaming does not help) — delete it, fetch with a new query |
| Forgot to change `EPISODE.assetDir` (clone ships `fable-news`) | Gate fails — set `assetDir` = `<mediaDir>` (Step 7) |
| Beat without `src` silently shows the default file | Set `src` explicitly on every `broll`/`clip`/`typo` beat; `check_broll.py` fails otherwise |
| Source's sponsor end card leaks in | Never cut from the promo segment; check the last chapter |
| Remotion `public/` symlinks → 404 in render | Copy files, never symlink |
| Interface props type fails `Record<string, unknown>` | `export type <CompId>Props = {…}` |
| Foreign numbers on screen the VO never says | Only with a Thai headline/sub that explains them |
| 🃏/👇-class emoji break headless Chrome | Use common emoji only (🎮💻🎨🎵📚📐📱🛍️✅ proven) |
| Render is silent | `mux_av.sh` is mandatory; check loudness accept criteria |
| Long whisper run blocks the pipeline | Background it (Step 2) and do YT recon meanwhile |
