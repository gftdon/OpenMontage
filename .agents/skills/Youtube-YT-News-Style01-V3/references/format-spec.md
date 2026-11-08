# V3 format: readable lanes

Canonical executable source: `assets/YtNewsStyle01V3.reference.tsx`; contract: `v3-contract.md`. All values are design pixels at 1920×1080.

| Element | Geometry |
|---|---|
| Safe bounds | x96–1824, y54–1026 |
| Header | x116–1804, y58, height48; label24 |
| Stock/source stage (source contain preserves UI) | x116,y128,w1190,h520 |
| Presenter card | x1340,y128,w464,h690; cropped uniformly, never stretched |
| Full source | x0,y0,w1920,h1080, cover fit; non-16:9 crops preserve the important source region |
| Source URL | source only: full x116,y112,w1688,h52; label24 |
| Source credit | y658 stage / y186 full source, label24 |
| Headline | y712 stage / y704 full source, 36px |
| Description | stage only, 28px, separate row |
| Stat rail | y850 in both stage/full source, label24, independent from headline/description |
| Caption | bottom66 or source-safe top-left x116/max650/y248, font32, logical phrase; gold active word |
| Lower third | x140,y670, separate from caption |
| CTA | y812; one short question |

Navy #0B0E17, cream #F5F1E8, amber #F2B34C, mint #8FD6B4, clay #D97757. Load Kanit Bold/ExtraBold with render-blocking font readiness; failed load cancels render. No stage-wide dark overlay. Gradient only under text. V3 keeps bounded avatar rect interpolation (0.55s), stage fade/slide 8px, and clamped spring opacity/translate 6px for chips/lower-third/CTA. All remain within media/text lanes; do not delete motion to pass QC.

Footage receives instantaneous punch transforms only when described in BEATS. Punch is allowed ONLY on avatar or source footage, never stock/typography. Long stock returns to avatar or changes actual footage; typography uses genuinely different timed cards. Do not split identical beats and claim a new cut. See SKILL QC commands: any new text or crop must pass actual-video DOM still samples before full render.
