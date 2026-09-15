# Format spec — Web-News Style01 V2 (engine `FableNewsYTV2.tsx`)

All numbers are 1920×1080 design px unless marked "css" (capture coordinates).
The engine renders; the **episode module** (`<name>EpisodeV2.ts`) holds every
episode-specific value. Never put episode copy in the engine.

## Geometry (locked)

| Element | Rect | Notes |
|---|---|---|
| Left stage | x 80, y 100, w 1210, h 840, r 22 | browser chrome 46 px inside → viewport 1210×794 |
| Avatar card | x 1362, y 96, w 478, h 850, r 26 | 0.5624 ≈ 9:16; 2 px cream border + amber glow |
| Top bar | y 0–92 | brand pill left, amber kicker (pip only), **chapter pill right** (`n/N · title`; `PREVIEW` during the teaser) |
| Caption lane | bottom 26, centred, max-width 1500, font 36 | gold karaoke (locked); hidden during the sting and after VO end |
| Stat chips | stage bottom-left, 26 px above stage bottom | dark glass, amber/mint/clay |
| Gloss chip | stage top-right (under the chrome on web beats) | 📖 term · Thai meaning, 5 s |
| Lower-third | x 80, bottom 150 | tag pill (default BREAKING, `lower.tag`) + 62 px title + clay-edged sub |
| Next chips | x 80, bottom 150 (300 when the CTA chip is on) | "ต่อไป ▶" pill (`next.pill`) + label + cascading chips + clay tease |
| CTA chip | x 80, bottom 170 | `CTA_T` → VO end |
| VERIFIED | chrome right pill + stamp bottom-right of the viewport for 3 s on every entry into the browser | `EPISODE.captureLabel` |
| Progress bar | top, 5 px | chapter ticks at `CHAPTERS_TL` |
| Thumbnail comp | brand top-left, two 132 px headline lines (2nd amber), accent pill, presenter card 590×1000 at x 1290 | `EPISODE.thumbs[]`, prop `variant` |

### Morph (locked)

`pipProgress(t)` eases 0→1 over `MODE_BLEND_SEC = 0.55` at every mode change;
uniform scale, crop window `cardW/scale × cardH/scale` centred on
`lerp(960→AV_CX, 540→AV_CY)`. Per avatar only `AV_CX` changes (face midline x
in source px). The stage fades/slides with `p`.

### Timeline (V2)

`TIMELINE.teaser[]` = 2–3 source ranges of the presenter's own take cut to the
front; `stingDur` follows; `mainSrcStart` skips the greeting; `mainSrcEnd` =
last word end + 0.3; `endcardDur` 8 s (room for YouTube end-screen elements).
`segments()` lays them out; `mapMain(src)` shifts every main-body time; teaser
beats are `abs: true` and use `SEG.teaser[i].dst` / `mapTeaser(i, src)`.
The avatar is one `<Sequence>` per segment (`startFrom = src`); captions are
rebuilt from the same segments (words outside a segment are dropped); the audio
build reads the same JSON. One source of truth → no drift anywhere.

## Design tokens

Navy `#0B0E17` / `#141A2B`, cream `#F5F1E8`, amber `#F2B34C` (primary), clay
`#D97757` (rival / baseline / tease), mint `#8FD6B4` (improvement / verified),
Kanit ExtraBold/Bold, karaoke gold `#F59E0B` / `#FDE68A` (locked), mono for the
terminal. Backdrop = gradient + 28 px dot grid + two drifting glows.

## Beat schema (V2)

```ts
interface Beat {
  t: number;                 // src seconds (whisper) — or timeline seconds when abs: true
  abs?: boolean;
  mode: "full" | "pip";
  media?: "web" | "broll" | "clip" | "typo" | "explain" | "chart" | "terminal" | "none";
  kicker?: string;
  // web
  file?: string; cssH?: number; cam?: CamKey[];
  hl?: { t; key?; rect?; pad?; th?: string }[];     // th = Thai translation strip (latest one stays)
  // footage
  src?: string; from?: number; headline?: string; sub?: string; subT?: number; idx?: string;
  clipFit?: "cover" | "contain"; hook?: boolean;   // hook = teaser typography (112 / 58 px)
  // typo
  typo?: "summary3" | "vs" | "final4" | "agenda" | "sting";
  // new stages
  explain?: { title; sub?; layout: "flow" | "list" | "compare"; left?; right?; items: { t; icon; text; tone? }[]; footnote? };
  chart?: { title; sub?; unit?; max?; bars: { label; value; tone?; note? }[] };
  terminal?: { title; tag; lines: { t; kind: "cmd"|"out"|"ok"|"warn"|"claude"|"add"|"del"|"dim"; text }[] };
  // overlays
  stats?: { t; big?; label; tone? }[];
  lower?: { title; sub; t?; dur?; tag? };
  next?: { label?; items: string[]; tease?; t?; pill? };
  gloss?: { t; term; th }[];
}
```

Word-timed arrays beside BEATS: `AGENDA`, `SUMMARY3`, `FINAL4`, `VS {fableT,
mythosT, subT, leftLines[], rightLines[]}`, `CTA_T`, `CHAPTERS {src, title}`,
`MUSIC_DIPS[]` (src seconds of marquee numbers). `EPISODE` holds brand, date,
page pill, `captureLabel`, `officialTag`, `previewTag`, `cta`, `sting`,
`endcard` (+`next` subscribe line), labels for agenda/summary3/final4, `vs`
copy, `thumbs[]` (3 variants: two headline lines + accent; the accent must be
verifiable on the page).

## Media types — when to use which

| Type | Use for | Rules |
|---|---|---|
| `web` | anything the page literally says | camera lands before the word; ≤ 3 highlights; zoom 1.0–1.6; **every English highlight gets `th`**; files `sec_<section>` / `<carousel>_NN` (name the quote carousel `quote`) / `<tabs>_N`; never 3 captures of the same `<prefix>_NN` family in a row (lint) |
| `broll` | intros, breathing room, generated signature shots | 3–8 s; headline ≤ 5 Thai words; `hook` only in the teaser |
| `clip` | videos hosted on the page | museum card + `officialTag`; `clipFit` |
| `typo` | agenda (structure promise), summary chips, vs card, closing chips | word-timed; ≤ 5 items |
| `explain` | a story that needs a picture: overnight flow, "3 said pass / 1 found it", where the data lives, why it's slow | `flow` ≤ 4 steps, `compare` = 2 cards + ≤ 2 items, `list` ≤ 4; one per 60–90 s max |
| `chart` | the page's table → bars | ≤ 4 bars; us = amber, rival = clay; `note` for a footnote value; sub = "ยิ่งสูงยิ่งดี · ที่มา" |
| `terminal` | a demo of the product doing a task | replay of a **real** run (paste verbatim output); tag `DEMO · <tool>`; 6–9 s, ≤ 13 lines |
| `full` | cold-open (after the teaser), pivots with `next`, punchline cuts, close with CTA | pivots 2–7 s with `next`; punchline 2–4 s with `lower` |

## Camera model (web beats) — unchanged from V1

`S0 = 1.1`, `s = S0 × z`, focus at 50 % / 46 % of the viewport, clamped; short
captures centred. Presets: hero `z 1.0→1.1, fy 400`; paragraph `z 1.26–1.46, fy
= highlight y + 60`; quote card (340 css) `fx 535, fy 168, z 1.46→1.54`; table `z
1.2→1.24, fy 300`; chart tab `z 1.08→1.14, fy 340`. Always drift `z +0.06`.
Highlights: amber multiply, spring wipe; translation strip prefers **above**
the rect (covers the line already read), else below, else clamped; only the
latest strip in a beat stays visible.

## Pacing (EP.1 V2 numbers to copy)

64 beats / 469.6 s VO: 25 web, 16 b-roll, 10 full, 5 explain, 4 typo, 2 clip,
1 chart, 1 terminal; 33 visual events / minute (lint). Teaser 12.4 s (3 cuts) +
sting 2.6 s; first main full-frame 5.4 s + agenda 6.9 s; pivots 2–7 s; close:
"มุมไทย" card 12 s → full-frame CTA 9 s (subscribe cue stacked above) → endcard 8 s.

## Common mistakes

| Mistake | Fix |
|---|---|
| Keying beats to SRT | whisper `line_starts.json` + word dump only |
| Teaser cut drops a word ("ไม่") | `snap_cuts.py` then read the caption at the first frame; the negation must be there |
| Translation strip over the next highlight | engine prefers above; if both lines are highlighted, shorten `th` |
| VERIFIED stamp under the gloss chip | stamp is bottom-right, gloss top-right — keep it that way |
| Subscribe cue under the CTA chip | `next` on the closing full beat stacks itself above the CTA automatically |
| Spread box-shadow on a 0-size element for the ring burst | renders square — use a sized circle with a radial gradient |
| Missing generated clip at bundle time | copy a stock clip to `gen_<name>.mp4` first; the bundle 404s otherwise |
| Same b-roll twice in a row | rotate clips; `from` offsets |
| Scale-pulsing the presenter | never |
