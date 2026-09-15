# Format spec — Web-News Style01 (FableNewsYT)

All numbers are 1920×1080 design px unless marked "css" (capture coordinates).

## Geometry (locked)

| Element | Rect | Notes |
|---|---|---|
| Left stage | x 80, y 100, w 1210, h 840, r 22 | browser chrome 46 px tall inside → viewport 1210×794 |
| Avatar card | x 1362, y 96, w 478, h 850, r 26 | 0.5624 ≈ 9:16; 2 px cream border + amber glow |
| Top bar | y 0–92 | brand pill left, amber kicker after it (pip mode only) |
| Caption lane | bottom 26, centred, max-width 1500, font 36 | gold karaoke style, hidden after `VO_END_SEC` |
| Stat chips | stage bottom-left, 26 px above stage bottom, wrap | dark glass, amber/mint/clay tones |
| Lower-third | x 80, bottom 150 | BREAKING pill + 62 px title + clay-edged sub |
| CTA chip | x 80, bottom 170 | shown from `CTA_T` to `VO_END_SEC` |

### Morph (locked)

`pipProgress(t)` eases 0→1 over `MODE_BLEND_SEC = 0.55` at every mode change.
Card rect lerps full→card; `scale = lerp(1, AV.h/1080)`; the crop window is
`cardW/scale × cardH/scale` centred on `lerp(960→AV_CX, 540→AV_CY)`. Because
the scale is uniform the presenter never stretches mid-morph. Per avatar only
`AV_CX` changes (face midline x in source px; measure from a frame); `AV_CY`
stays 540 because the card crop spans the full source height — move it only for
a tight head-and-shoulders source, and verify the head is inside the card.

The left stage fades/slides in with `p` (`stageOpacity`, `stageSlide -40→0`),
so in full-frame mode nothing but the avatar, brand bar and captions show.

## Design tokens

Navy `#0B0E17` / `#141A2B` stage, cream `#F5F1E8` text, amber `#F2B34C`
(primary accent, kicker, highlights), clay `#D97757` (secondary — brand dot,
"negative"/baseline numbers), mint `#8FD6B4` (positive numbers), Kanit
ExtraBold/Bold everywhere, karaoke gold `#F59E0B` / `#FDE68A` (locked).
Backdrop = gradient + 28 px dot grid + two slow-drifting amber/clay glows.

## Beat schema

```ts
interface Beat {
  t: number;                       // whisper line start (or word time for mid-line cuts)
  mode: "full" | "pip";
  media?: "web" | "broll" | "clip" | "typo" | "none";
  kicker?: string;                 // amber pill in the top bar (pip only)
  // web
  file?: string;                   // "sec_hero" | "quote_02" | "chart_0" (first tab; tabs are 0-indexed)  → public/<mediaDir>/web/<file>.png
  cssH?: number;                   // css height when the file isn't in WEB_CLIPS (tab captures)
  cam?: { t: number; fy: number; z: number; fx?: number }[];   // t relative to beat start
  hl?: { t: number; key?: string; rect?: WebRect; pad?: number }[];  // t absolute (word time)
  // broll / clip / typo
  src?: string; from?: number;     // BROLL_DUR key + seek seconds
  idx?: string; headline?: string; sub?: string; subT?: number;
  clipFit?: "cover" | "contain";   // clip beats: cover = full-bleed footage, contain = light renders on cream
  typo?: "summary3" | "vs" | "final4";
  // overlays
  stats?: { t: number; big?: string; label: string; tone?: "amber" | "mint" | "clay" }[];
  lower?: { title: string; sub: string; t?: number; dur?: number };
}
```

`file` = capture file name without `.png`: `sec_<section>` → `WEB_CLIPS[<section>]`,
`<carousel>_NN` → `WEB_CLIPS[<carousel>]`, `<tabs>_N` → `WEB_CLIPS["<tabs>_N"]`
(all produced by `capture_page.mjs`); `cssH` overrides when a file isn't there.
All episode copy that is not per-beat (brand, date, URL pill, official tag,
CTA, endcard, typo-scene titles, vs-card copy) sits in the `EPISODE` block.

The stage renders the current beat on top of the previous one with a 0.35 s
fade-in (crossfade, never a dip to black). Each beat lasts until the next `t`.

## Media types — when to use which

| Type | Use for | Rules |
|---|---|---|
| `web` | anything the page literally says: headline, paragraph, quote card, table, chart | camera lands on the sentence *before* its word time; ≤ 3 highlights per beat; zoom 1.0–1.6 |
| `broll` | company/topic intros, concepts with no page support, breathing room | 3–8 s; headline ≤ 5 Thai words; `idx` badge for numbered lists / CASE n; `sub` appears at its word time |
| `clip` | videos hosted on the page itself (official) | museum-card look, `EPISODE.officialTag`, `clipFit: "contain"` (default) for light renders / `"cover"` for square or dark footage; loops |
| `typo` | "สรุปง่าย ๆ", A-vs-B explanations, closing summary | word-timed chips; keep to ≤ 4 items |
| `full` | cold open, rhetorical questions, section pivots, close | cold open 10–14 s, pivots 2–7 s, close ~20 s; nothing else on screen but captions / lower-third / CTA |

## Camera model (web beats)

Capture css width 1100 maps to the 1210 px viewport: `S0 = 1.1`, so display
scale `s = S0 × z`. `fx, fy` (css px inside the capture) is placed at 50 % /
46 % of the viewport, clamped to the page bounds. Captures shorter than the
viewport are **vertically centred**. Practical presets:

- Hero: `z 1.0 → 1.1`, `fy ≈ 400` (title + moon), then `z 1.28 → 1.36` on the title.
- Paragraph with highlights: `z 1.26–1.46`, `fy` = highlight `y + 60`.
- Quote card (carousel capture 340 css tall): `fx 535, fy 168, z 1.46 → 1.54`.
- Table: `z 1.05 → 1.22`, `fy ≈ 300`; highlight header cell + row + rival cell.
- Chart tab capture (≈ 720 css tall): `z 1.08 → 1.14`, `fy ≈ 340`.
- Long section with two targets (price paragraph → cost chart): 3–4 keys,
  e.g. `[{0, 330, 1.2}, {3.5, 380, 1.2}, {7.5, 880, 1.05}, {16, 880, 1.1}]`.
- Always drift slightly (`z +0.06` over the beat) so the frame never freezes.

Highlights are amber `rgba(242,179,76,0.55)` with `mix-blend-mode: multiply`,
wiped in left→right with a spring at the word time; `key` looks up
`WEB_RECTS`, `rect` allows a computed rect (table row/col helpers `rowRect`,
`colRect`).

## Stat / info chips

- `big` + `label` for numbers (48 px amber number, 24 px label); label-only for
  lists (27 px). Tones: mint = improvement, clay = baseline/competitor, amber =
  neutral/brand.
- Fire on the exact word (`25%@198.27` → `t: 198.3`). Max 3 visible; they wrap
  at the stage width. They persist until the beat ends.
- When the page shows the same number, pair the chip with a highlight.

## Pacing (EP.1 numbers to copy)

- ≈ 7 beats per minute. EP.1 = 55 beats / 455.6 s VO: 8 full-frame (cold open
  13.3 s, pivots 2–6 s, close 21.3 s), 24 web, 18 b-roll, 2 clip, 3 typo.
  Scale the counts to the VO length; keep the rate and the full-frame cadence.
- Cold open: lower-third at 1.3 s for 5.2 s. CTA at the word `claude.ai`.
- Endcard: `VO_END_SEC = last word end + 0.3`, total = VO_END + 4.4 s.

## Typo scenes

- `summary3`: label + 3 big chips (icon + word) at their word times.
- `vs`: eyebrow line (at fable word − 0.6 s), two 520 px cards (amber vs clay)
  entering at each name's word time, bottom conclusion chip at its word time.
- `final4`: title + 4 wrapped chips at word times over dark city footage.
Emoji proven in headless Chrome: ✍️📊💻💡📄📝🧾🗣️🔎🤖🌅⚠️🧪⏱️🗒️▶️🌍🔓🛡️🧬🎭🚫🧠🚀💸✨.

## Common mistakes

| Mistake | Fix |
|---|---|
| Keying beats to SRT | whisper `line_starts.json` + word dump only |
| Highlight under the chips | raise `fy` so the sentence is mid-viewport |
| Short capture top-aligned with blank below | composition centres; if it still looks empty, zoom to 1.5+ or capture taller |
| Presenter off-centre in the card | measure `AV_CX` from a frame; the crop follows |
| Same b-roll twice in a row | rotate clips; use `from` offsets for a second use later |
| Quote card cut at COMPANY row | capture the carousel 340 css tall, not the container height |
| Dark UI zoomed > 1.3 looks mushy | this page is light; for dark pages keep z ≤ 1.24 |
| Scale-pulsing the presenter | never — life comes from glows, camera drift, chips |
