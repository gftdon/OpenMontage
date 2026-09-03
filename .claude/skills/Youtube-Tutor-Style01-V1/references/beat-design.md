# Beat design guide — Youtube-Tutor-Style01

How to turn a script + whisper line starts into the BEATS table that drives
the whole composition. Reference data: the `BEATS` array in
`remotion-composer/src/GoogleFlowYT.tsx` (29 beats over 226s of VO).

## The BeatDef contract

```ts
interface BeatDef {
  t: number;                 // whisper line start (line_starts.json) — never SRT
  mode: "full" | "pip";      // where the avatar lives during this beat
  kicker: string;            // top-left topic pill (pip beats only; "" on full)
  media: "video" | "img" | "typo" | "none";
  src?: string;              // staticFile path under public/, e.g. "<mediaDir>/x.mp4"
  srcFrom?: number;          // seconds into the source video (frame-swept!)
  typo?: string;             // which typography scene component
  z1?: number; z2?: number;  // still zoom start→end over the beat (≤ ~1.24)
  origin?: string;           // CSS transform-origin, aims the zoom
  chip?: string;             // bottom-right info pill
  chip2?: string; chipSwapT?: number; // chip swaps text mid-beat (word-timed)
  ring?: { left: string; top: string }; // pulsing click-highlight on stills
}
```

A beat runs from its `t` to the next beat's `t` (last beat → `VO_END_SEC`).
The avatar morph blends over `MODE_BLEND_SEC` (0.45s) whenever `mode` changes.

## Cadence rules

- **Open**: beat 0 is `full` with empty kicker; HookTitle overlay carries the
  title, killed by ~t=4.8s. First pip beat lands on the line where content
  actually starts (EP.1: 4.64s).
- **Rhythm**: `pip` for anything the viewer should *see* (UI, demos, lists);
  `full` for human moments — greetings, jokes, "ลองคิดดูนะคะ", section pivots.
  Return to `full` every ~30–60s; longer away and the video feels like a
  screencast, not a presenter.
- **Length**: beats of 4–15s. Under ~3s feels twitchy; over ~18s goes static —
  split it or add a chip swap / ring to keep motion.
- **Close**: final content beat `full`, TeaserChip enters (~7s before VO end),
  Endcard hard-covers everything from `VO_END_SEC` to the total (~4s tail).
- Group consecutive script lines that belong to one on-screen idea into a
  single beat; don't force one beat per line.

## Choosing media per beat

**`img` (BrowserCard)** — real product UI screenshots. The card fakes browser
chrome (traffic lights + domain pill — update the domain text per product!).
Slow zoom `z1→z2` across the beat; keep ≤ ~1.24 on dark UI (crushes/mushes
beyond that). Point `origin` at the region being discussed. Add `ring` when
the VO says "กดตรงนี้" — position is in % of the *cropped image area*.

**`video` (FootageLayer)** — full-bleed official footage. Set `srcFrom` only
after frame-sweeping the file at 1s steps around the candidate moment and
*viewing the frames*; EP.1 shipped a wrong-excerpt bug from trusting a
chapter timestamp. A bottom gradient keeps the caption lane readable.

**`typo`** — cream-card kinetic typography on the espresso TypoStage. Use for
frameworks, lists, prompts, diagrams, summaries — the moments a tutorial
viewer screenshots.

**`none` + `full`** — presenter carries it. No kicker, no chip.

## Typography scene inventory (EP.1 set — clone & retheme)

| `typo` | Component | Use for | Word-timed internals |
|--------|-----------|---------|----------------------|
| `prompt_card` | PromptCard | typing out an example prompt + result polaroid | typing window start/end; polaroid pop |
| `checklist4` | Checklist4 | N-point framework reveal | one `t` per item = start of the word introducing it |
| `start_end` | StartEndDiagram | A→B concept (two polaroids + gradient arc) | card pops, arc draw window, punchline chip |
| `shot_list` | ShotList | numbered shot/step rows | one `t` per row |
| `export` | ExportOverlay | platform/option chips over footage | one `t` per chip (~1.3s apart) |
| `workflow` | WorkflowPipeline | summary pipeline of the whole method | step interval (~1.15s) from the recap pacing |

Every internal `t` above comes from **word-level** `s` values in the captions
TS module: grep the spoken word, use its `s`. That's what makes items pop
exactly as they're said. New scene types: copy the TypoStage + cream-card +
`springIn` pattern from an existing one.

## Chips, bubbles, overlays

- `chip` = supporting fact, bottom-right (InfoChip). One idea per chip. Use
  `chip2`/`chipSwapT` when the VO moves to a second point mid-beat.
- EDIT_BUBBLES pattern (chat bubbles stacking bottom-right) for "say commands
  to the AI" moments — one bubble per spoken command, word-timed, with a
  display window matching the beat.
- Kicker text: 2–5 Thai words, THE topic of the beat, uppercase Latin OK
  (e.g. "เขียน PROMPT"). Don't restate the caption.

## Art direction (Frang house style)

- Palette tokens at the top of the composition: espresso stage `#171009` /
  `#241708`, cream cards `#FAF3EA`, ink `#2A2018`, amber accent `#E8A13C` /
  `#F6C87B`, plus a per-episode accent pair (EP.1: Google blue `#4C8DF6` +
  mint `#7FD1AE`) feeding the signature `RIBBON` gradient. Retheming an
  episode = swap the accent pair; the warm base stays.
- Font: Kanit ExtraBold/Bold (`KanitX` FontFace loader, files in
  `public/fonts/`). Headline sizes ~54–58, body 30–42, chips 19–28.
- **Locked**: CaptionLane gold karaoke styling (GOLD `#F59E0B`, GOLD_LIGHT
  `#FDE68A`, font 38, bottom 42, maxWidth 980) — established user preference.
- **Never scale-pulse the presenter** (established user rule). Motion comes
  from springs on cards/chips, zooms on stills, the beat sweep, arc draws.
- Emoji: the EP.1 set renders fine in Remotion's headless Chrome; 🃏 and 👇
  are known-broken from a past project. Verify any new emoji with a still.
- Media must keep the bottom-center ~170px clear for the caption lane;
  InfoChip owns bottom-right (bottom: 176), PiP owns bottom-left
  (56,791 400×225).
