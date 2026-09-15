# YouTube-source recon & clip cutting (the step that replaces web-capture)

In this format the report subject is a **YouTube video**, so the left stage is
fed by clips cut from that video. This replaces the Playwright page-capture
step of `Youtube-Web-News-Style01-V1`. Everything else (avatar morph, stage
geometry, captions, typo scenes, mux) is identical — see `format-spec.md`.

## 1. Download + chapters

```bash
bash .claude/skills/Youtube-YT-News-Style01-V1/scripts/yt_survey.sh "<YOUTUBE_URL>" projects/<slug>/assets/ytsource
```

YouTube **chapters are the section map** — they land within a second of the
real topic boundaries and come with titles, so most of the "which range covers
what" work is already done. If the video has no chapters, fall back to the
contact sheets alone.

## 2. Look before you cut

1. View `survey/sheetA.jpg` + `sheetB.jpg` (tiles every ~85 s, two offsets) for
   the whole-arc impression: where are the diagrams, the UI screens, the
   gameplay/beauty shots, the stats cards.
2. For every chapter you might use, view **one single frame at its midpoint**
   (`ffmpeg -ss T -i source.mp4 -frames:v 1`) to confirm what is actually on
   screen.
3. Before finalising a cut, survey the exact arc:
   `ffmpeg -ss A -to B -i source.mp4 -vf "fps=1/2,scale=480:270,tile=5x2" -frames:v 1 arc.jpg`
   — a single frame at the chapter midpoint can lie: title cards, file
   dialogs and score charts often sit 2–3 s inside an otherwise perfect range.

Cut ranges are only final after all three views. Each of these skipped checks
cost a re-render on the trial episode (fight clip opened on a Tripo webpage,
chair clip opened on a macOS file dialog, "clay colosseum" clip was a bar
chart for everything past its first 4 s).

## 3. Cut

```bash
bash .claude/skills/Youtube-YT-News-Style01-V1/scripts/cut_clips.sh \
  projects/<slug>/assets/ytsource/source.mp4 projects/<slug>/assets/ytsource/clips \
  yt_fight:6:17 yt_pipeline:38:62 ...
cp projects/<slug>/assets/ytsource/clips/*.mp4 remotion-composer/public/<mediaDir>/broll/
```

- Name clips `yt_<topic>` so they can't collide with stock b-roll keys.
- The script prints `BROLL_DUR` lines — paste them into the composition.
- Pad in-points 2–3 s early; make every clip longer than its beat.
- **Never** include the source's sponsor/promo-code end card.

## 4. Map script lines → source ranges

Build the line→range map from `line_starts.json` (whisper) and the chapter
list, exactly like the section→line map in the web-news format:

| Script content (what she says) | Source visual |
|---|---|
| Cold open / hook claims | the source's own gameplay or beauty shots (full-bleed `broll` beat) |
| "AI ตัวที่ N คือ…" tool intros | the source's UI recording of that tool (`clip` museum card) |
| Process/verification talk | judging screens, dashboards, code overlays (`clip`) |
| Generic wisdom (skills, opportunities) | **stock b-roll**, not the source — the source has nothing for it |
| Summary | the source's stats/results cards if mentioned or showable with a Thai headline that explains them |

Presentation rules:

- UI/diagram/dashboard clips → `clip` beats (museum card, `clipFit: "contain"`
  when edge UI matters, `"cover"` otherwise). The `officialTag` becomes
  `SOURCE · <CHANNEL>` — attribution lives there and in the endcard `sub`.
- Action/cinematic clips → `broll` beats (full-bleed + kinetic Thai headline).
- Numbers that appear in the source but are **never spoken** in the VO may be
  shown only with a headline/sub that explains them in Thai (e.g. "ต้นฉบับ
  ปรับเกม 95 รอบ"); unexplained foreign numbers confuse.
- Same adjacency rules as the web format: never the same clip twice in a row,
  alternate media types, 3–16 s per beat, ~7 beats per minute.

## 5. What carries over unchanged

Stock b-roll (Step 6), typo scenes (`summary3` / `vs` / `final4`), the CTA
chip, the endcard, karaoke captions, the music bed, and the render/mux QA
loop are identical to the web-news format — follow the main SKILL.md.
