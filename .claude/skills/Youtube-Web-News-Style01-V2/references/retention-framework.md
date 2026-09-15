# Retention framework — STOP / STAY / ONLY-HERE / EASY / MEASURE

Reusable for any "presenter reads a web page" news episode. Each rule = a
mechanic in the engine + a field in the episode module + the tool that makes it.
Nothing here needs a new avatar take.

## STOP — first 3 seconds (thumbnail ↔ frame 0 ↔ teaser)

| Rule | Mechanic | Field / tool |
|---|---|---|
| Never open on the greeting | Pre-lap teaser: 2–3 of the presenter's own sentences cut to the front, then an ident sting, then the take from the first content word | `TIMELINE.teaser[]`, `mainSrcStart`; `snap_cuts.py` for the cut points |
| Pick the sentence with **number + known brand + contrast word** (แต่ / ครั้งแรก / ไม่มีใคร) | score whisper lines; the payoff must land inside 3 s of on-screen text | `words_by_line.py` |
| Frame 0 = the thumbnail | teaser beat 0 is `broll` + `hook` typography over a generated signature shot; thumbnail comp uses the same headline | `EPISODE.thumbs[]`, `thumbs.mjs` (A/B/C for YouTube Test & compare) |
| Something moves in the first 500 ms | camera push on the shot + headline spring + chip at the number | `hook: true`, `stats` |
| Sound opens with a hit | impact + whoosh at 0, riser 2.5 s before the sting, impact + sting at the sting | `events.mjs` writes these automatically |
| Hook text must be verifiable on the page | receipts are the brand; no "1 คืน" if the page never says it | review `EPISODE.thumbs`, teaser `headline/sub` |

## STAY — a reason to keep watching every 30 s, something new on screen every 5 s

| Rule | Mechanic | Field / tool |
|---|---|---|
| Structure promise | `agenda` typo scene right after the first full-frame line ("ใน 8 นาทีนี้ 1…5") | `AGENDA[]` word-timed |
| Progress you can see | chapter pill `n/N · title` + ticks on the progress bar; YouTube chapters in the description | `CHAPTERS[]`, `chapters.py` |
| Open loops at pivots | `next` chips on full-frame pivots: what's coming + a clay `tease` for something further ahead ("แล้วราคาล่ะ? อีกไม่ถึง 2 นาที") | `next {label, items, tease}` |
| Punchline on the face | 2–4 s full-frame cut on the payoff sentence with a lower-third (tag = the company) | `mode: "full"` + `lower {tag}` |
| No quote-card run ≥ 3 | replace the 2nd/3rd quote with `explain` (flow / compare) or b-roll | lint `quoteRuns` |
| No visual gap > 5 s | add a chip / highlight / camera key / gloss at a word time | lint `gapsOver5s` (allowed only on pivots ≤ 6 s) |
| Music breathes | bed 0.22 base, 0.30 teaser, 0.38 sting, 0.34 endcard; dips to 0.07 at marquee numbers; VO-envelope duck | `MUSIC_DIPS[]`, `build_audio.py` |
| SFX on every UI event | pop (chips), tick (chart bars, next chips, gloss), swoosh (highlights), whoosh (media change), morph, chapter stinger, typing under the terminal | `events.mjs` → `build_audio.py`; library from `gen_sfx.sh` |
| Subscribe cue at the end | `next` on the closing full beat with `pill: "แล้วเจอกันคลิปหน้า"`; stacks above the CTA | — |

## ONLY-HERE — receipts, our own test, our own pictures, our angle

| Rule | Mechanic | Field / tool |
|---|---|---|
| Receipts as a brand | VERIFIED pill in the chrome + stamp on every entry into the browser; every spoken number has a highlight or chip | `EPISODE.captureLabel` |
| We tried it | `terminal` beat replaying a real run (verbatim outputs) under the "best at coding" line; tag DEMO | `TERMINAL_DEMO` |
| Signature pictures, not stock | 3 generated shots per episode in the house palette (teaser hook, one concept, the ident/typo background) | `gen_shots.py` (image tool → Kling i2v, or Kling t2v) |
| The page's table as our chart | `chart` beat right after the table receipts beat | `chart {bars}` from `web_data.json` table rows |
| Local angle | "มุมไทย" `explain` card before the CTA: where to use it, free plan, price in THB with the FX date, Thai language | verify price + FX on the day; `footnote` carries the source |
| Series identity | same sting, chapter pill, kicker vocabulary, endcard `next` line | `EPISODE.sting`, `EPISODE.endcard.next` |

## EASY — make dense foreign news readable for Thai viewers

| Rule | Mechanic | Field |
|---|---|---|
| Translate what you highlight | every English highlight carries a Thai one-liner strip (≤ 12 words) | `hl[].th` |
| Gloss the jargon | first mention of an English term gets 📖 term · meaning (prototype, benchmark, GPU kernel, jailbreak, Creative Commons…) | `gloss[]` |
| Show the story, not the quote | `explain` flow for processes (overnight work), compare for contrasts (3 said pass / 1 found it; where data lives), list for facts (มุมไทย) | `explain{}` |
| Numbers need a baseline | chips pair the win (mint) with the baseline (clay): 10× vs 10–15 %, −85 % vs "ระบบเดิมเข้มเกินไป" | `stats[].tone` |
| One idea per screen | explain ≤ 4 items, chart ≤ 4 bars, agenda ≤ 5 chips | — |

## MEASURE — close the loop

1. Before publish: `events.mjs` lint (counts, gaps, quote runs, beats > 16 s,
   events/min), stills of every new scene type, loudness within 1 dB of the
   source VO, frames from the **muxed** file.
2. Publish with `chapters.txt` in the description and the 3 thumbnails in
   YouTube Test & compare.
3. After 7 days: export audience retention (CSV) → `retention_map.py EVENTS.json
   retention.csv` → the steepest `loss/10 s` beats become the next episode's
   fixes (more dips? shorter pivots? move the tease?). Record the numbers in the
   project README so the rules get real thresholds.

## Timeline model (why nothing drifts)

Source time (`src`, seconds in the avatar take) vs timeline time. `segments()`
lays out teaser pieces → sting → main; `mapMain(src)` shifts every main time;
the avatar layer is one `<Sequence>` per segment; captions are rebuilt from the
same segments; `events.mjs` exports the same layout for `build_audio.py`, which
re-cuts the VO from the take (8 ms fades) and builds bed + SFX on it. Change a
cut point in one place and picture, captions and sound all move together.

## Audio design (from `v2_events.json`)

SFX gains (dB): impact −11 (open) / −8 (sting), sting −9, riser −11, chapter
−12, morph −13, whoosh −14…−18, pop −15, tick −16, swoosh −19, typing −24.
Soft limiter above 0.85. Accept: final mean within 1 dB of the source VO, max ≤
−0.4 dB (EP.1 V2: −18.5 vs −19.2 dB, max −1.3 dB).
