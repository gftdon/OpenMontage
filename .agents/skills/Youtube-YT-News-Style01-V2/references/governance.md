# OpenMontage governance for this pipeline

Rule Zero: production goes through a pipeline project. This format runs as a
**hybrid** pipeline. Worked precedent: `projects/google-flow-yt-ep1/`.

## Run shape

- Workspace: `projects/<slug>/` with `artifacts/`, `assets/`, `renders/`.
- Stages (hybrid): `idea → script → scene_plan → assets → edit → compose`
  (+ `publish`, normally out of scope — the user has publishing elsewhere).
- Each stage ends with a checkpoint via `.venv` python (NOT system python3):

```python
from pathlib import Path
from lib.checkpoint import write_checkpoint
write_checkpoint(
    pipeline_dir=Path("projects"), project_id="<slug>",
    stage="assets", status="completed",
    artifacts={"asset_manifest": {...}},   # canonical artifact for the stage
    pipeline_type="hybrid",
    human_approval_required=True, human_approved=True,  # only if actually true
)
```

- Canonical artifact per stage: idea→`brief`, script→`script`,
  scene_plan→`scene_plan`, assets→`asset_manifest`, edit→`edit_decisions`,
  compose→`render_report`. Compose additionally requires a `final_review`
  before presenting to the user; `source_media_review` is required before the
  first planning stage when the user supplied media (they did — the avatar).
- Decisions: append to `projects/<slug>/decision_log.json`, keyed by
  (category, subject), append-only.
- House rule: the composition-mode decision must **present both composition
  runtimes** (EP.1 decision d03 chose Remotion atelier after presenting both).

## Schema gotchas (every one of these caused a validation failure on EP.1)

**decision_log `category` enum** — nothing else validates:
`pipeline_selection, provider_selection, renderer_family_selection,
render_runtime_selection, composition_mode, playbook_selection,
fallback_decision, budget_tradeoff, downgrade_approval, music_source,
motion_commitment, concept_selection, voice_selection, capability_extension,
playbook_override, visual_accuracy_check`
(no approval/caption categories — use `budget_tradeoff` / `playbook_selection`
for those.)

**decision `options_considered`**: array of objects
`{option_id, label, score (0–1), reason, rejected_because?}`;
`selected` is the chosen `option_id` string, not a label.

**asset `type` enum**: `image, video, audio, narration, music, sfx, diagram,
animation, code_snippet, subtitle, font, lut` (no `data`).

**scene `type` enum**: `talking_head, broll, animation, character_scene,
diagram, text_card, transition, generated, screen_recording`.

**edit_decisions**: `additionalProperties: false` — no ad-hoc `notes` field.
Atelier composition mode REQUIRES
`bespoke: {entry, composition_id, art_direction}`.

**render_report**: no `encoding_notes` — use `verification_notes[]`.
`render_grammar` enum includes `presenter` (the right value for this format).

**final_review**: `status` ∈ `pass | revise | fail` (not "passed");
`checks` is an OBJECT that must contain all of
`{technical_probe, visual_spotcheck, audio_spotcheck, promise_preservation,
subtitle_check}`.

When in doubt, read the JSON Schema in `schemas/artifacts/<name>.schema.json`
rather than guessing a field.
