# V4 format: scenes, lanes and data semantics

Canonical executable source: `assets/YtNewsStyle01V4.reference.tsx` (identical to `remotion-composer/src/YtNewsStyle01V4.tsx`). An episode is DATA ONLY: `episode.json` + captions JSON, no per-episode TSX. Schema: `assets/episode.schema.json` + semantic rules S01-S20 in `scripts/episode_schema.mjs`. All values are design pixels at 1920×1080, 25 fps.

Data contract and who checks each field (schema S01–S20, lint codes, layout/render/finalize gates): `references/v5-contract.md`; authoring procedure: `SKILL.md`.

What changed from V3: no cover-full-bleed source scene (a wide source is a centred 16:9 window), scene changes cross-fade under an opaque layer, and the episode is data-only.

## Scene kinds

| Kind | Picture | Selected by | Notes |
|---|---|---|---|
| P | presenter full-bleed 1920×1080 | `mode:"full"` | only keys `t, mode, kicker, punch, stats, lower` (S04); lower third and CTA live here |
| S | browser-style window + picture + presenter card | `mode:"pip"`, `media:"broll"\|"clip"`, `layout:"stage"` | headline + description (description yields to stat chips) |
| T | text card inside the same window + presenter card | `mode:"pip"`, `media:"typo"`, `layout:"stage"` (S08), `typo:"card"\|"summary3"\|"final4"\|"vs"` | no footage; `src/from/srcCrop/origin/punch` forbidden (S05) |
| W | centred 16:9 source window, presenter hidden | `mode:"pip"`, `media:"clip"`, `layout:"wide"` (S08); no `sub`, no `stats` | |
| E | end card, dark opaque, hard cut in | time only: `[voEndSec, totalDurationSec)` | `endcard.{eyebrow,titleA,titleB,cta}` |

`media:"clip"` is a source clip (`origin:"source"`, `src` starts `yt_`); `broll` is `stock` or `ai` (`ai_` prefix) (S06).

## Geometry (`LANES`; x, y, w, h, corner radius r)

Machine-readable copy of every lane (and the per-scene lane maps): `assets/yt-news-v4-lanes.json`; `scripts/tests/lanes_json.test.mjs` fails if it ever differs from the engine's `LANES`.

| Group | Lanes |
|---|---|
| Header (P S T W) | `header.brand` 96,54,480,44 r12; `header.kicker` 1344,54,480,44 r12 |
| Presenter | `avatar` (card, S T W; hidden in W) 1362,100,478,850 r26; `avatar.full` (P) 0,0,1920,1080 |
| Split window (S T) | `stage` 80,100,1210,840 r22; `split.chrome` bar 80,100,1210,52; `split.chrome.url` 164,104,700,44 r10; `split.chrome.label` 872,104,400,44 |
| Split picture + text (S) | `split.picture` 1138×640 at 116,172 r16; `split.lower` backing 80,812,1210,128; `split.headline` 112,814,1146,62 |
| Text card (T) | `typo.backing` 80,152,1210,716; `typo.content` 116,172,1138,676 |
| Description / stat rail (P S T) | `sub` 112,876,1146,60 |
| Wide window (W) | `wide.window` 320,100,1280,844 r22; `wide.chrome` 320,100,1280,52; `wide.chrome.url` 404,104,640,44 r10; `wide.chrome.label` 1182,104,400,44; `wide.picture` 320,152,1280,720; `wide.bar` 320,872,1280,72; `wide.headline` 340,874,1240,62 |
| Caption (P S T W) | `caption` 96,954,1728,72 |
| Presenter-only overlays (P) | `full.lowerThird` 96,520,960,196; `full.cta` 96,722,1728,150 (same x and width as `caption`) |
| End card (E) | `end.eyebrow` 360,300,1200,44; `end.title` 160,360,1600,94; `end.sub` 260,470,1400,60; `end.cta` 260,560,1400,144 |

Text lanes `typo.content`, `split.headline`, `sub`, `wide.headline` are 4 px wider on each side than the laid-out text box (glyph side bearings such as a leading "โ"), and the headline/sub lanes start 6 / 2 px above the line box (tall Thai stacks such as "น้ำ").

## Text sizes (CSS px)

The engine clamps every field to `MIN_PX`: **read 38, label 30**. The gate floors are lower: CSS font size read 36 / label 28 (`readFontPx`, `labelFontPx`), and rubric size read 28 / label 22 (`readRubricPx`, `labelRubricPx`; rubric size = reference-glyph ink height ÷ 0.7, `rubricInkDivisor`). If text does not fit its lane, change the layout (shorter text, another variant, another beat split). Never shrink below the minimum and never demote a tier. Fields are one line unless `qc_field_rules.json` says otherwise (`typo-*` 2 lines; the closing question `cta` is one line).

As implemented: header brand/kicker label 30; S/W headline 40 (800); description 38; stat big 38 / label 30; chrome URL and credit label 30; lower third label 30, title 52, sub 38; CTA 40; caption 38 (≤ 40 graphemes per page, S19); end card eyebrow 30, title 72, sub 40, cta 40.
- `card`: title 76, rows 60 with a numbered badge (40), row padding 26, gap 22. 1-3 rows: one column, one line each. 4 rows: two columns, a row may wrap to 2 lines.
- `summary3`: eyebrow (= headline) label 34; chips 56 (icon 52), one row when every item ≤ 8 graphemes and the row fits 1130 px, else a 900 px column.
- `final4`: title 64, sub 42, chips 46 (icon 44) in a 2×2 grid of 545 px cells, gap 20.
- `vs`: eyebrow label 34; side cards 520 px wide: badge label 30, title 60, lines 44; separator "vs" 48; conclusion 44.

## Transitions

Constants: `MODE_BLEND_SEC` 0.55; `IN_F` 14 (presenter morph / incoming window fade); `XF_F` 9 (S/T→S/T and W→W cross-fade); `OUT_F` 9 (outgoing layer fades under the incoming one, then unmounts). A beat starts at frame `ceil(t×25)`.

Invariant: the outgoing layer stays fully opaque until the incoming layer is fully opaque, then fades under it, so there is never a dark frame (`coverageOk`). An outgoing T card keeps its finished text (no restart) until the incoming picture covers it (T→T and T→S: `XF_F`; T→W: until the card has faded out, `IN_F`+`OUT_F` = 23 frames, because the wide window never covers the card's left strip; T→P: the presenter covers it, and any field the presenter box reaches is hidden for that frame). Outgoing S/W labels unmount at once.

Label delay (frames after the new beat starts before its labels enter): T→T and T→S **9**; S→S, S→T, W→W, P→P **0**; every other pair **14** (P→S/T/W, S/T→W, W→S/T, S/T/W→P). Attribution (source URL, credit, AI label) starts 2 frames earlier than other labels. Chrome continuity: S→S and W→W with the same layout and the same origin (`source` or `ai`; stock has none) keep one browser chrome, and its entrance does not run again.

Settle table (`settleFrames(prev, next)`: frames the outgoing layer of beat i stays visible after beat i+1 starts):

| prev \ next | P | S | T | W |
|---|---|---|---|---|
| P | 0 | 0 | 0 | 0 |
| S | 14 | 18 | 18 | 23 |
| T | 14 | 18 | 18 | 23 |
| W | 14 | 23 | 23 | 18 |

(18 = `XF_F`+`OUT_F`, 23 = `IN_F`+`OUT_F`, 14 = `IN_F`; after the last beat 0.)

## Field semantics

- **`from`** (number ≥ 0, ≤ 600): start offset in seconds into the public cut file `public/<assetDir>/broll/<src>.mp4`, not into the original video. `brollDur[src]` is that file's duration (S07: every `src` is a key). The beat plays from frame `round(from×25)`. Loop length `L = floor((brollDur[src] − from)×25) − 2` frames. S09: `L ≥ 25` (error). Stock/ai clips loop: past `L` they restart at `from` (warning if `shown > L`). Source clips never loop: past `L` the last frame is held. With `shown` = frames the beat is on screen and `settle(i→i+1)` from the table above, `shown + settle ≤ L` must hold: source = error, stock = warning (the outgoing layer keeps playing into the next beat). S10: a `src` may appear in several beats only if all are source clips and their frame ranges `[round(from×25), +shown)` do not overlap (reusing a stock/ai `src` is an error).
- **`srcCrop`** `{x,y,w,h}` (broll/clip only): integer pixels of the 1920×1080 source frame; schema ranges x 0-1280, y 0-720, w 640-1920, h 360-1080. S11: `x+w ≤ 1920`, `y+h ≤ 1080`, aspect `w/h` within 25% of 16:9 (error), warning above 10%. The crop region is scaled uniformly by `max(box.w/w, box.h/h)` (cover) and centred in the picture box (1138×640 for S, 1280×720 for W), anything outside the box is clipped. Without `srcCrop` the whole frame is cover-fitted. No rule limits upscaling; keep the scale below 1.0 as the worked example does. `srcCrop` must never cut content of the source picture (panels, text, labels, credits baked into the clip); the default is NO `srcCrop` (the picture boxes are 16:9, so the whole 1920×1080 frame is shown); use it only for a deliberate zoom whose edges fall on empty background.
- **Stat chips** (`stats`, 1-3 per beat, S/P/T only): `at` is **absolute episode seconds**, `dur` 1-12 s, visible on `[at, at+dur)` independent of beat boundaries. S13: `at` inside its own beat; may carry over at most one boundary (end ≤ end of the next beat); gone before `ctaT`; never visible during a wide beat; at most 3 visible at once; all visible chips belong to one beat. The description line yields while a chip is visible and re-enters when the last chip ends. S18 (warning): estimated row width ≤ 1138 px.
- **Card items**: `cards[j].at` and `items[j].at` are **absolute episode seconds** inside the beat, no `dur`, no carry-over. Cards: `cards[0].at` equals the beat `t`, times increase, each `< beat end`; the latest card with `at ≤ t` is shown (S14). Items (`summary3` 3, `final4` 4): `at` in `[t, end)`, non-decreasing (S14). Entrances never start before the scene's label delay.
- **`avatarFaceBox`** `{x,y,w,h}`: fractions (0-1) of the presenter media frame (the 1920×1080 avatar video). It is also what centres the presenter-card crop horizontally. Measure per episode: sample ≥ 8 frames spread over the avatar video, take the union of hairline→chin and ear→ear, add about 6% margin, round outward to 0.01. Never hardcode it per skill. The schema only checks the range; the DOM gate uses it: `face-text` (any text ink over the face region inside the presenter box) and `face-backing` (any backing with opacity ≥ 0.05 over it, not painted below the presenter).
- **`punch`** (`{at, z 1-1.6, fx, fy}`, max 4): only on `mode:"full"` beats, never on pip beats, `at` inside the beat, strictly increasing, and never at or after `ctaT` (S12).
- **`ctaT`, `voEndSec`, `totalDurationSec`**: S01 first beat at 0, `t` increasing, last `t < voEndSec`; S02 each beat ≥ 1.0 s; S03 `ctaT < voEndSec` and `totalDurationSec − voEndSec` in [3, 5]; S20 last beat is `mode:"full"` and `ctaT ≥ beats[last].t`; S15 lower third `dur` 2-8 s inside its P beat; S19 captions: hash equals `captionsInputSha256`, last page ends ≤ `voEndSec + 0.25`.

## Wash / backing rule

> ห้าม dark wash คลุมภาพ footage (ภาพต้นทาง / stock) ทั้งภาพ · อนุญาตพื้นทึบหรือ wash เฉพาะพื้นของ beat การ์ดข้อความ (media:"typo") ซึ่งไม่มี footage อยู่ข้างใต้ · ข้อความที่วางบน footage ใช้พื้นรองเฉพาะจุดใต้ข้อความเท่านั้น

V4 text cards use a solid designed card background (no footage underneath). Every text field sits on a solid backing with alpha ≥ 0.9 (`minBackingEffAlpha`).

## Palette and fonts

Navy `#0B0E17` (panels `#141A2B`, `#0E1322`), cream `#F5F1E8` (dim `#CFC9BE`), amber `#F2B34C`, mint `#8FD6B4`, clay `#D97757`; chrome bar `#232B45`; caption active word `#FDE68A` with a `#F59E0B` glow. Font family `KanitX` = Kanit ExtraBold (800) + Bold (700) from `fonts/Kanit-*.ttf`, loaded render-blocking; a failed load cancels the render. Default weight 700, headings 800.

## Gates

`scripts/qc_layout.mjs` is the DOM layout gate on sampled frames: resumable, each invocation stops by its time budget (default 420 s) and exits 75 until complete. `scripts/qc_final_pixels.mjs` scans the rendered file for dark dips (abrupt drops to the navy background) before `voEndSec`. `scripts/render_episode.mjs` refuses a FINAL render without a passing gate report that matches the sources, and a gates lock; drafts must be named `*.draft.*`. Flags and exit codes are in each script's header. The gate, the render (`scripts/render_episode.mjs`) and the stills tool (`scripts/stills.mjs`) bundle from `remotion-composer/src/ytNewsStyle01V4.entry.tsx` (the V4 entry, copy in `assets/ytNewsStyle01V4.entry.reference.tsx`), never from `Root.tsx` / `index.tsx`; source hashes and the bundle key cover the entry's import closure only. Studio for V4: `cd remotion-composer && npx remotion studio src/ytNewsStyle01V4.entry.tsx`.

The empty-backing sweep (a backing painted above the presenter during a transition window) counts an empty region only if its short side is ≥ 12 px (`avatarEmptyMinShortSide`), and it fails when the counted regions have total area ≥ 1500 px² and long side ≥ 24 px for longer than 0.3 s inside a transition window. An empty strip thinner than 12 px over the presenter is therefore NOT caught by the gate.

Not guaranteed by the gates:

1. An empty strip of backing thinner than 12 px over the presenter.
2. Whether a `srcCrop` cuts content of the source picture; no gate knows what is content.
3. During a cross-fade the outgoing picture is not checked for attribution: a source URL/credit can sit over a still-opaque stock picture for up to 9 frames, and an outgoing AI picture has no AI label for 9-14 frames.
4. Text that stays at a low but non-zero opacity when settled (the text-alpha rule reads colour alpha only).
5. S10 ignores the outgoing tail: a source clip reused in a non-adjacent beat can show up to 23 of the same frames twice.

