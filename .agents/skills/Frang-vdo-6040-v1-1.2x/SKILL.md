---
name: Frang-vdo-6040-v1-1.2x
description: Produce a polished vertical (9:16) avatar-presenter tutorial video in a 60/40 split layout — content top 60%, presenter bottom 40% — from a supplied AI avatar video plus screen-recorded step footage, finished with a 1.2x speed pass. Use when the user supplies an avatar/talking-head video and step-by-step screen footage and wants an engaging social tutorial (Thai or other narration language) with footage cut in on the spoken steps, b-roll, motion cards, kinetic captions, and a music bed. Triggers include "60/40", avatar presenter at the bottom of the video, tutorial with cut-in footage, 1.2x final speed.
---

# Frang-vdo-6040-v1-1.2x — 60/40 avatar tutorial recipe

Repeatable production recipe. Reference implementation (all artifacts, QC evidence, reusable code): `projects/claude-cowork-avatar-tutorial/` + `remotion-composer/src/avatarTutorial/`. Consult them as the working example; this file is the process, not a copy of the outputs.

Route through the `avatar-spokesperson` pipeline (AGENT_GUIDE Rule Zero): read `pipeline_defs/avatar-spokesperson.yaml`, log decisions in `decision_log.json` (including `render_runtime_selection` with all options considered), checkpoint per stage.

## Inputs contract

- Avatar video with embedded narration (any aspect; letterbox bars are detected and cropped in Phase 1).
- Step-by-step screen footage (silent or discardable audio is normal).
- Output: 1080x1920 @ 30fps, content top 60% (y 0–1152) / presenter bottom 40% (y 1152–1920), final speed 1.2x. Narration language = avatar's language; keep captions/cards in that language.
- If the user specifies a different split or speed, those numbers are parameters — the process is unchanged.

## Phase 1 — parallel analysis swarm (3 agents)

Fan out, disjoint write scopes; all artifacts land in `projects/<name>/artifacts/`.

1. **Bar research** (skip when a standing bar file exists and the user accepts it — see `projects/claude-cowork-avatar-tutorial/artifacts/bar_research.md`): concrete praised explainer examples + a measurable craft checklist (shot length 5–10s, cut to screen on the verb, hook proof by 3–4s, music 20–24 LU under voice, master -14 LUFS / TP -1, hard cuts over wipes).
2. **Avatar analysis**: word-level transcript of the narration (ElevenLabs Scribe, `language_code` set explicitly; fallback faster-whisper large-v3). Gotchas that matter: ASR emits sub-word fragments in Thai — resegment with pythainlp and align to fragment timestamps; ASR smears phrase-final syllables over silences — clamp every word against `silencedetect` (-35dB, ≥0.25s) intervals. Also: letterbox crop (`negate,cropdetect` when bars are white; verify bounds at ≥4 timestamps), loudness (loudnorm first pass), head/tail trim points, beat map (`avatar_beats.json`: every topic/step with tight start/end). Done when: `avatar_transcript.json` + `avatar_beats.json` + `avatar_crop.json` + extracted narration WAV exist and word timings provably match measured silences.
3. **Footage analysis**: step segmentation via region frame-diff at 10fps + visual confirmation (±0.2s), trimmed per-step clips (crf 16, no audio), app-window crop rect inside any desktop wallpaper (chroma-mask, not luminance), dead-air segments flagged for removal, audio keep/discard verdict (volumedetect; screen recordings are usually digital silence → discard). Done when: `tutorial_segments.json` + step clips + reference PNGs exist.

## Phase 2 — contract (orchestrator writes, never delegated)

- `edit_decisions.json`: the full segment list — every narration beat maps to exactly one of: tutorial footage (matching spoken step), b-roll, or motion card. Segments are contiguous (absorb beat gaps into neighbors); hard cuts only; dead air inside footage removed via sub-cut lists with `src_in`/`src_out`/`speed`/zoom focuses; each segment carries an optional chip label.
- `remotion-composer/src/avatarTutorial/theme.ts` (exists — adapt values): 60/40 layout constants, dark warm palette (coral accent #E8836B, active-caption yellow #FFC53D), Prompt (heading) + Sarabun (body) Thai fonts.
- Layout default (from the reference run): card x48 y72 w984 h1016 r32; media window x80 y196 w920 h620; caption band x80 y852 w920 h168; progress bar y36 h6; avatar crop cover-scaled, eyes land ~180px below zone top.

## Phase 3 — parallel builder swarm (4 agents, disjoint files)

1. **Captions**: phrase-group the transcript (2–5 words, break on >0.35s pauses, ~2.2s max) → JSON + Remotion component: Prompt 600 @48px, active word #FFC53D, last spoken word HOLDS highlight through intra-phrase pauses, pop-in 6 frames, nothing during silence gaps.
2. **B-roll**: one clip per non-footage beat. Source chain: Pexels API → Pixabay API → Mixkit (no key needed). Verify every `.env` key is non-empty before trusting a 401. Rules: landscape, no burned-in text, no camera-facing faces, warm-gradeable; process to exact window size, 30fps, crf 18, no audio, unified warm grade; VIEW a middle frame of every rendered clip before accepting. Record provenance in `broll_manifest.json`.
3. **Audio**: narration anchor two-pass loudnorm -16 LUFS; instrumental bed (95–110 BPM, no vocals) sidechain-ducked 20–24 LU under voice (`sidechaincompress` threshold 0.03 ratio 4 attack 20 release 400), natural swells in beat gaps and outro; fade ends AFTER the last word's tail; master two-pass -14 LUFS / TP -1.0, exact duration. All measurements into `audio_mix_report.json`.
4. **Motion cards**: one component per non-footage beat (hook title, concept explainer, step mock-UI, CTA end card). Spring physics (damping ~14), first element on screen ≤2 frames after the cut, full build ≤24 frames (deliberate narrative sequencing exempt), Thai copy byte-exact from `edit_decisions.json`. Reuse patterns from `remotion-composer/src/avatarTutorial/cards/`.

## Phase 4 — integrate + render (1 agent)

- Master Remotion comp: gradient+grain background, progress bar, content card (chip header, media window, caption band), avatar zone with divider, `<Audio>` = final mix, outro fade ~8 frames.
- Screen footage: crop to the app window first, then scale to the media window; zoom punch-ins on the fields being discussed (measure rects from reference PNGs); synthetic typing overlay (grapheme-cluster-safe for Thai combining marks) when the source "typing" is instant paste. Mask parked cursors/glyphs inside the transform layer so masks follow zooms.
- Register the composition in `Root.tsx` following the existing pattern; `npx remotion render ... --codec=h264 --crf=18`.
- Gotcha: same-name `.ts`/`.tsx` siblings shadow each other on case-insensitive filesystems — name data modules `*Data.ts`.
- Done when: stills at every segment boundary + every interaction are viewed clean, then the full render probes correctly.

## Phase 5 — QC swarm (5 reviewers) → fix pass → re-render + remux

Reviewers (read-only, findings to `artifacts/qc/`): layout/polish, captions, audio, edit-rhythm/cut-accuracy, avatar presentation (framing, 25→30fps dup cadence, lip-sync onset). Verdicts: critical/suggestion/nitpick. Fix ALL criticals and suggestions; re-render; then:

- **AAC priming remux (always)**: Remotion's mux leaves +42.67ms (2048 samples) uncompensated. Remux: `ffmpeg -i render.mp4 -i final_mix.wav -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 192k -movflags +faststart final.mp4`, then PROVE sync by cross-correlating the decode against the mix WAV (expect lag 0 ±100 samples).
- Final verifier gives SHIP / NO-SHIP against the fix list.

## Phase 6 — 1.2x finishing pass (signature step)

Re-time the mastered composite uniformly — never re-render for speed: uniform speed-up preserves lip-sync, captions, cuts, and music swells by construction.

```bash
ffmpeg -i final.mp4 -vf "setpts=PTS/1.2,fps=30" -af "atempo=1.2" \
  -c:v libx264 -crf 17 -preset slow -pix_fmt yuv420p \
  -c:a aac -b:a 192k -ar 48000 -movflags +faststart final_1.2x.mp4
```

Verify: duration = master/1.2; xcorr lag ≈ 0 vs an `atempo=1.2` reference of the mix; ebur128 (expect ≈ -14 LUFS ±0.5, TP ≤ -1); view frames at hook, tutorial core, the fastest caption phrase (min phrase duration shrinks 20% — confirm readable), end card.

## Standing rules

- Every run writes: brief, decision_log, edit_decisions, transcripts/beats, broll_manifest, audio_mix_report, qc/*, render_report — all under `projects/<kebab-name>/`.
- Announce tool/provider choices before paid calls; log fallbacks (e.g. Pexels→Mixkit) in the decision log.
- Footage covers only the steps it actually shows; motion cards + b-roll cover the rest. Match visuals to narration beats, never the reverse.
