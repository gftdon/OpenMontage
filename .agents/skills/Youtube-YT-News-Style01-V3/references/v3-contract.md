# V3 authoring contract

The tracked template and caption helper are self-contained; clone both to neutral new episode names. `REPLACE_MEDIA_DIR` is intentional: replace it with the new public folder. Never depend on untracked per-episode modules.

```ts
interface Beat {
  t: number; // absolute seconds; sorted, contiguous until VO_END_SEC
  mode: 'full' | 'pip'; // full = avatar
  media?: 'broll' | 'clip' | 'typo';
  src?: string;
  origin?: 'source' | 'stock'; // mandatory for media
  layout?: 'stage' | 'full'; // mandatory for media
  chrome?: boolean; // explicit; true only for source
  captionLane?: 'top' | 'bottom'; // inspect source contactsheet, no OCR
  cards?: {t: number; lines: string[]}[]; // typography content cards
  punch?: {t: number; z: number; fx?: number; fy?: number}[];
}
```

Punch is allowed only on avatar/source footage, never stock/typography. Typography `cards` must change content, not repeat a card to evade hold.

`punch` is a discrete camera step at absolute t, not interpolation. A 15% scale ratio delta or effective visible viewport displacement 0.15 (left=fx*(1-1/z), top=fy*(1-1/z), size=1/z) resets the hold timer. Author meaningful crops: keep subject/source UI clear. A slow animated camera is not a cut. The avatar/source footage must actually render the same hard step described by the metadata.

The linter compares adjacent primary visual identities (actual media/src/layout or primary typography card content) before timing. Overlay lower/chip/CTA/kicker/headline/card changes never reset holds, regardless of dwell, so splitting an identical beat does not shorten its hold. Keep BEATS a literal array; spreads, computed maps and mutation fail the inherited tokenizer. Use new source ranges or deliberate hard crops rather than duplicate identical files.

Text fields are explicit `data-qc-field`, `data-qc-role` logical units. Caption words share one field, preventing false collisions within a phrase. The QC-only probe waits for Kanit fonts, then measures real Range rects (including Thai marks), cumulative opacity and clipped ancestors after layout. Missing data fails, not skips. Crossfade exemption is limited to previous/current versions of the same logical field; the reference keeps bounded motion but does not crossfade overlapping text fields and needs no exemption.

Acceptance uses actual video in stills, never a blank-media substitute. Sampling covers every beat boundary/settled/mid/last, captions, hard punch, lower-third and CTA. Delivery stills at 9/89/172s are extra examples, not a replacement for the plan.
