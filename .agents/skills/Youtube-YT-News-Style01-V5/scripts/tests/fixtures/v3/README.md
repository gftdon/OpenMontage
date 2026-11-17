# V3 fixtures for the V4 layout gate (CF-A66, G8)

Real probe output from the shipped V3 episode, used to prove that every new V4 rule **fails on the V3 defect and
passes on the corrected counterpart**. The JSON files are byte-identical copies (never edited) of

`projects/v261111-001-gemini-4-carbon/qc/layout/runs/8e60e0cc-4248-429d-a3c6-1a19ed5f0663/<frame>.json`

They are V2-shaped (`schemaVersion: 2`, no `layers`, `avatar`, `backings`, `tier`, `lane`, `rubric`).
All augmentation happens in code, in `builders.mjs`, so the originals stay verifiable
(`shasum -a 256` below). Tests call the single `rule*` functions on the augmented objects; `evaluateLayout`
on the raw files is a single `schema` issue (fail closed).

| Fixture | Source frame | sha256 |
|---|---|---|
| `v3-dark-6940.json` | 6940 | 21ad629c5f3deb2a2e15782a31036888aa3a6b1de6cf6f5ec6b36e648e2b8c60 |
| `v3-dark-6941.json` | 6941 | e8dda831749d75496c2122b9080fffc4d496fb279799434b5351ae424743946a |
| `v3-dark-6942.json` | 6942 | a18ccc5fb41f4892e89f301184c6d75bd91197084b7767dc276c0bf9d2bb9de6 |
| `v3-headline-semi-1875.json` | 1875 | 25a451929dcc01a7421e815c3d8b535430a41c1400cc0c09efded5114419666f |
| `v3-morph-url-1860.json` | 1860 | 9fbbd00b8986b82b974dacd1baee07c39caa653f571c2a3269a52104c1a667de |
| `v3-cta-16035.json` | 16035 | a6e53374c16a3984bf12261928fa6fefe072bb18775c2beaefa1a27f5f883f08 |

## What each fixture proves

| Fixture | Use | Augmentation (`builders.mjs`) | Rule / result on V3 | Passing counterpart |
|---|---|---|---|---|
| 6940 / 6941 / 6942 | augmented | `augmentDark`: `phase:'vo'`, `layers=[{kind:'avatar', box:avatarBacking.avatar.box, opacity:avatarBacking.avatar.opacity}]`. No stage layer: in mode full the stage is genuinely unmounted in V3 (the dark flash). | `content-presence`: coverage 0 / 0.00208 / 0.00903 (need 0.25) | `withHeldStage`: adds `{kind:'stage', box:0,0,1920,1080, opacity:1}` (the outgoing layer held) -> coverage >= 1 |
| 1875 | as-is | none (V2 `backing` already has alpha/opacity/sameVisibilityAncestry/box) | `backing` (headline): effAlpha 0.95 x 0.622585 = 0.5915; every other field passes | `backing.opacity = 1` on the headline -> pass |
| 1860 | augmented | `augmentPresenter`: `phase:'vo'`, `avatar={opacity:0.920627, box:B, mediaBox}` with B = `avatarBacking.avatar.box` (213.14,128,1590.84x739.70) and `mediaBox` = 16:9 at card height, centred (x = 351.0, width 1315.2) | `presenter-text-backing` (source-url): effAlpha 1 x 0.285714 = 0.2857. Caption (0.92) and credit (0.90) pass at the boundary | URL `opacity = 0` and its backing `opacity = 0` (V4 delayed chrome) -> pass |
| 16035 | augmented | `augmentPresenter` (avatar opacity 1, B = 116,128,1688x744; frame 16035 is t = 641.4 s, before the 642 s punch, so scale = 1) | `presenter-text-backing` (cta, `backing:null`, effAlpha 0) | a solid backing (alpha 1, opacity 1) padded 16x8 px around the cta ink -> pass |
| 1860 (synthetic) | augmented + synthetic | as above, plus `avatar.faceBox = mapFaceBox({x:.37,y:.12,w:.19,h:.36}, mediaBox, 16/9)` (= 837.6,216.8,249.9x266.3), plus `backings` derived from the frame's occluders (everything but the avatar) | unshifted frame passes both face rules | caption `inkRects`/`rects` shifted +500 px in x -> `face-text`; an extra backing box (800,200,300x300) -> `face-backing` |

The face box is the spec's reference rect (read off 1860.png), used **only** to build this fixture; it is not
hard-coded anywhere in the rules.

## Not in this folder (later steps)

* `v3probe-*` (frames 1481, 2044, 16035, 16250, 6941, 1860 re-rendered with the patched V3 probe: `font-rubric`,
  `text-alpha`, `lane-missing` on real data) need the V4 `measureQcFrame` and re-rendered stills.
* `font-rubric`, `text-alpha`, `tier-*`, `unknown-field`, `lane-*`, `reserved-intersect`, `line-count`,
  `nowrap-overflow`, `lane-table` have **no natural V3 DOM defect**; they are synthetic fail + pass cases built with
  `v3Field` / `v3Snap` in `scripts/tests/eval_rules.test.mjs`.

## builders.mjs

Test-only helpers: `v3Field`, `v3Snap`, `backingFor`, `permissiveCtx` (one big lane, per-snapshot field rules, so
generic tests only trigger the rule under test), `PLAN` / `CTX` (a lane table inside the safe area plus the real
`qc_field_rules.json`), `loadRaw`, `augmentDark`, `withHeldStage`, `augmentPresenter`, `mapFaceBox`, `inkBox`.
