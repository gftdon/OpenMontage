---
name: Youtube-Tutor-Style01-V1
description: >-
  Produce a 16:9 YouTube tutorial/longform video (Julian-Goldie commentary
  style) from a finished avatar presenter video (HeyGen etc.) plus its SRT
  script: one continuous avatar that morphs full-frame ↔ bottom-left PiP while
  a media stage shows real product-UI captures, official vendor b-roll, and
  Thai kinetic-typography scenes — with gold karaoke word-highlight subtitles
  and a music bed, muxed to a final deliverable. Use this whenever the user
  supplies an avatar/presenter mp4 (+SRT) and wants it "produced" into a
  YouTube video, asks for a new episode in the Frang tutorial series, says
  things like "ทำเหมือน EP.1", "ทำแบบคลิป Google Flow", "สไตล์
  Youtube-Tutor-Style01", "ประกอบร่างวิดีโอ Avatar เป็นคลิปลง YouTube", or
  references the GoogleFlowYT composition — even if they don't name this skill.
---

# Youtube-Tutor-Style01-V1 — avatar ➜ YouTube tutorial longform

Reference implementation: `remotion-composer/src/GoogleFlowYT.tsx` (comp id
`GoogleFlowYT`, 1920×1080 @ 25fps). First delivered episode:
`projects/google-flow-yt-ep1/renders/final.mp4` (230s, $0 marginal asset cost).
**Do not rebuild the format — clone it and swap the data.**

Anatomy of the format:

- One continuous avatar `OffthreadVideo` that **morphs** between full-frame and
  a bottom-left PiP card (never a hard cut) via `pipProgress` + card/crop lerp.
- A **media stage** behind the PiP: browser-framed product screenshots with
  slow zoom + click-highlight rings, full-bleed official footage excerpts, and
  cream-card Thai kinetic-typography scenes on an espresso stage.
- **Karaoke caption lane** (locked gold-glow style from karaoke_subtitle_v2),
  kicker pill top-left, brand chip top-right, info chips bottom-right, progress
  ribbon top, hook title at open, next-episode teaser + cream endcard at close.
- Music bed ~14 dB under the VO. Remotion renders are **silent** — audio is
  muxed afterward.

## Inputs required (ask only for what's missing)

1. **Avatar video** — mp4, single continuous take, ideally 1920×1080. Any fps
   works (composition stays 25fps; OffthreadVideo resamples).
2. **SRT** matching the spoken script **exactly**. Its text is the script
   source of truth; its cue times are untrusted (HeyGen SRT drifts up to −4.1s
   non-linearly — the #1 trap of this format).
3. **Topic + branding** — series/presenter name, EP number, episode subject,
   optional per-episode accent color.

Infra assumed present: `remotion-composer/` app, karaoke venv at
`~/.cache/karaoke-subtitle/venv`, ffmpeg, yt-dlp, Playwright MCP (user's
logged-in browser), pixabay registry tools, Kanit fonts in
`remotion-composer/public/fonts/` (Kanit-ExtraBold.ttf, Kanit-Bold.ttf).

## Pipeline at a glance

| # | Step | Output |
|---|------|--------|
| 0 | Workspace + governance | `projects/<slug>/`, decision log entries |
| 1 | Probe + intake | avatar in `public/<mediaDir>/`, specs known |
| 2 | Script + karaoke timing | `script.txt`, captions TS module |
| 3 | **Whisper rebase** | `line_starts.json` — the timing spine |
| 4 | Beat design | BEATS table (~25–30 beats / 4 min) |
| 5 | Asset gathering ($0) | b-roll, UI captures, stills, music bed |
| 6 | Composition | `<CompId>.tsx` cloned from GoogleFlowYT + Root.tsx reg |
| 7 | QA stills | visual check at every beat |
| 8 | Render | silent visual mp4 |
| 9 | Mux + verify | `final.mp4` with VO + bed |
| 10 | Deliver | render in `projects/<slug>/renders/`, checkpoints done |

## Step 0 — Workspace + governance

This is an OpenMontage production: run it as a **hybrid pipeline** project
(`projects/<slug>/`) with stage checkpoints (idea → script → scene_plan →
assets → edit → compose; publish is normally out of scope) and decision-log
entries. **Read `references/governance.md` before writing any artifact or
checkpoint** — it lists the exact schema enums; guessing them fails validation
repeatedly. Present both composition runtimes (Remotion vs alternatives) in
the composition-mode decision, per house rule.

## Step 1 — Probe + intake

```bash
ffprobe -v error -select_streams v -show_entries stream=width,height,r_frame_rate,duration -of csv=p=0 AVATAR.mp4
mkdir -p remotion-composer/public/<mediaDir> projects/<slug>/assets/{audio,video,music}
cp AVATAR.mp4 remotion-composer/public/<mediaDir>/avatar_source.mp4
```

`<mediaDir>` is the episode's media folder (e.g. `google-flow-yt`). Note the
VO end: last spoken moment + breathing room = `VO_END_SEC`; total = VO_END + ~4s
endcard.

## Step 2 — Script + karaoke timing

```bash
# 1. Script lines from SRT (text only; strips quotes/arrows that break alignment)
python3 .Codex/skills/Youtube-Tutor-Style01-V1/scripts/srt_to_script.py \
  --srt SOURCE.srt --out projects/<slug>/artifacts/script.txt

# 2. 16kHz mono VO for whisper
ffmpeg -v error -i AVATAR.mp4 -vn -ac 1 -ar 16000 -y projects/<slug>/assets/audio/vo.wav

# 3. Word timing (karaoke venv — mlx-whisper large-v3; NOT the project .venv,
#    and NOT the transcriber pipeline tool — faster-whisper isn't installed)
~/.cache/karaoke-subtitle/venv/bin/python .Codex/skills/karaoke_subtitle_v2/scripts/extract_timing.py \
  --wav projects/<slug>/assets/audio/vo.wav \
  --script projects/<slug>/artifacts/script.txt \
  --out projects/<slug>/artifacts/caption_pages.json

# 4. Sentence-safe repage + Remotion TS module
python3 .Codex/skills/karaoke_subtitle_v2/scripts/repage.py \
  --pages projects/<slug>/artifacts/caption_pages.json \
  --script projects/<slug>/artifacts/script.txt \
  --out-pages projects/<slug>/artifacts/caption_pages_final.json \
  --out-ts remotion-composer/src/<name>Captions.ts
```

Accept only: repage prints `violations: 0`, and extract_timing's aligned char
count ≈ script char count. Whisper takes ~2 min for a 4-min VO.

## Step 3 — Whisper rebase (the critical step)

Vendor SRT times drift non-linearly vs the real audio. Captions are
whisper-timed, so **every visual keyed to SRT times fires out of sync**. All
beat boundaries come from whisper line starts instead:

```bash
python3 .Codex/skills/Youtube-Tutor-Style01-V1/scripts/line_starts.py \
  --pages projects/<slug>/artifacts/caption_pages_final.json \
  --script projects/<slug>/artifacts/script.txt \
  --out projects/<slug>/artifacts/line_starts.json
```

It prints a per-line `start – end` table and hard-fails unless its pages
exactly reconstruct each script line. Rules:

- Beat `t` = the `start` of the script line that opens the beat.
- Sub-animations tied to specific words (checklist item pops, chip swaps,
  typing windows, chat bubbles) use word-level `s`/`e` from the captions TS
  module — grep the word, take its `s`.
- Never type a time read from the SRT into the composition. Ever.

## Step 4 — Beat design

Read `references/beat-design.md` and design the BEATS table. Compressed rules:

- Open **full-frame** 4–6s with the HookTitle; close full-frame with the EP
  teaser; endcard after `VO_END_SEC`.
- Alternate: instruction/demo lines → `pip`; personal asides, transitions,
  emphasis → `full`. Return to full-frame every ~30–60s so the presenter
  reconnects with the viewer.
- One beat per line-group; beats run 4–15s; ~25–30 beats per 4 minutes.
- Media per pip beat: real UI → `img` (BrowserCard + zoom + optional ring);
  vendor footage → `video` (with verified `srcFrom`); concept/list/summary →
  `typo` scene.

## Step 5 — Asset gathering ($0 policy)

All assets free, in `remotion-composer/public/<mediaDir>/` (copy originals to
`projects/<slug>/assets/` too):

- **Official vendor videos** via yt-dlp (see `video-download` skill). On
  403/PO-token errors: `brew upgrade yt-dlp` first — that fixed it before.
- **Real product UI** via Playwright MCP in the user's logged-in browser:
  navigate the real product, type the demo text *from the actual script* into
  real inputs, screenshot ~1920-wide. **Never press Generate/Submit or any
  button that spends credits or publishes.** Disclose any residue created in
  the user's account (e.g. an empty project).
- **pixabay_video / pixabay_music** registry tools for generic b-roll and the
  music bed.
- **Frame-sweep every excerpt** (`ffmpeg -ss T -i src -frames:v 1 f.png`, view
  the frames) to confirm it shows what the kicker claims before committing
  `srcFrom` — chapter timestamps lie.
- Stills for polaroid cards: extract frames from the downloaded footage.

## Step 6 — Composition

Clone the reference, don't rebuild:

```bash
cp remotion-composer/src/GoogleFlowYT.tsx remotion-composer/src/<CompId>.tsx
```

**Swap per episode**: component/comp id + metadata fn names; `VO_END_SEC` /
`TOTAL_DURATION_SEC`; captions import; `<mediaDir>` paths; `BEATS` table;
typo-scene content and their word-timed sub-arrays (CHECK_ITEMS, SHOTS,
EXPORTS, FLOW_STEPS, EDIT_BUBBLES + their display window); HookTitle text;
BrandChip label; browser-card domain pill; endcard text/chips; TeaserChip;
optionally the accent tokens.

**Locked (don't touch)**: the morph math (`pipProgress`, card/crop lerp,
`MODE_BLEND_SEC 0.45`), CaptionLane gold karaoke style, ProgressBar ribbon,
component structure. The presenter is never scale-pulsed.

**PIP_CROP must be re-measured for each avatar framing** (this produced a user
revision on EP.1 — the crop was off-center):

1. Render a full-frame still, view it, estimate the presenter's face midline
   x in source pixels (`x_s`).
2. Crop height `H` ≈ head-to-mid-torso (EP.1: 495 from a half-body framing);
   `W = H × 16/9` (card is 16:9); `PIP_CROP = { x: round(x_s − W/2), y: ~10,
   w: W, h: H }`, x clamped to `[0, 1920−W]`.
3. Verify: render a pip-mode still, draw the card's center line, confirm the
   face midline sits on it (card center x = PIP.x + PIP.w/2 = 256):
   ```bash
   ffmpeg -y -i qa_pip.png -vf "drawbox=x=254:y=791:w=3:h=225:color=red@0.9:t=fill" qa_pip_line.png
   ```
   Nudge `PIP_CROP.x` until centered. (EP.1 final: x=535 for x_s≈975.)

Register in `remotion-composer/src/Root.tsx`:

```tsx
<Composition id="<CompId>" component={<CompId>} durationInFrames={Math.ceil(TOTAL * 25)}
  fps={25} width={1920} height={1080} defaultProps={{}} calculateMetadata={calculate<CompId>Metadata} />
```

## Step 7 — QA stills

Render a still ~1.5s into every beat and **view them all** (Read tool):

```bash
cd remotion-composer
for t in 2 6 21 30 48 66 90 118 150 171 185 202 210 220 228; do   # beat starts +1.5s
  npx remotion still <CompId> out/qa/still_${t}s.png --frame=$((t * 25))
done
```

CLI gotcha: **no entry-point argument** — `npx remotion still <CompId> out.png`;
passing `src/index.ts` makes the CLI parse it as the composition id.

Checklist per still: correct kicker + media for the beat; excerpt shows the
claimed content; captions match what's being said (proves the rebase);
PiP centered; nothing collides with the caption band (keep the bottom center
~170px clear; InfoChip bottom is at 176px); typo scenes fully inside frame;
dark-UI zoom ≤ ~1.24 with no crop into artifacts.

## Step 8 — Render (silent — expected)

```bash
cd remotion-composer && npx remotion render <CompId> out/<name>_visual.mp4 --concurrency=8 --crf=18
```

## Step 9 — Mux audio + verify

```bash
.Codex/skills/Youtube-Tutor-Style01-V1/scripts/mux_av.sh \
  remotion-composer/out/<name>_visual.mp4 \
  remotion-composer/public/<mediaDir>/avatar_source.mp4 \
  projects/<slug>/assets/music/bed.mp3 \
  projects/<slug>/renders/final.mp4 \
  <TOTAL_SEC> <VO_END_SEC>
```

Accept: duration = TOTAL ± 0.1s; output mean volume within ~1 dB of the source
VO's own mean; max ≤ −1 dB. (EP.1: mean −18.8 dB, max −2.5 dB.)

## Step 10 — Deliver

`final.mp4` in `projects/<slug>/renders/`; all six checkpoints written and
schema-valid; decision log updated; report to the user with the beat map and
any account residue disclosed. Spot-check the muxed file by extracting 2–3
frames + listening points before calling it done.

## Gotchas (each one cost real time on EP.1)

| Trap | Fix |
|------|-----|
| SRT cue times drift up to −4.1s, non-linearly | Rebase everything to whisper (Step 3) |
| Remotion render has no audio | Mux (Step 9) — always |
| `npx remotion render src/index.ts <CompId>` | Drop the entry point: `npx remotion render <CompId> out.mp4` |
| yt-dlp 403 / PO-token errors | `brew upgrade yt-dlp` |
| Transcriber pipeline tool errors (`faster-whisper is not installed`) | Use karaoke venv mlx-whisper (Step 2) |
| B-roll excerpt shows the wrong moment | Frame-sweep before setting `srcFrom` |
| PiP subject off-center | Measure PIP_CROP per avatar; centerline check (Step 6) |
| Dark screenshots look mushy zoomed | Keep zoom ≤ ~1.24, `origin` on the region that matters |
| 🃏 and 👇 emoji have broken in headless Chrome before | Stick to the proven set (✅🐩💰🎬⚡✏️🎞️🚀💡🖼️🔍🎯🏞️✨🧩💬🔒) or test a still first |
| zsh eats `===` echo separators, `cd` state persists between calls | Plain words in echos; absolute paths |
| Artifact/checkpoint schema rejections | `references/governance.md` has the exact enums |
