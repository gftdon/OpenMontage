"""Thresholds for lint_content.py (plain Python dict, no JSON config).

Every number the lead may still change lives here; `lint_content.py --set key=value`
overrides any key for one run (value parsed as JSON), and `--legacy` applies
LEGACY_OVERRIDES (currently none: --legacy only relaxes the V4-only gates).
"""

THRESHOLDS = {
    # card-timing: a card whose number is spoken more than this many seconds away
    # (before for timed cards, after for any card) is reported. "Gone before spoken"
    # is strict: no tolerance.
    'timingToleranceSeconds': 2.0,
    # An anchor whose nearest spoken occurrence is further than this from the card's
    # window is not "this card's number" (e.g. a lone "3" said 6 minutes away): it is
    # counted in metrics.timing.anchorsOnlySpokenFar and left to provenance. Set very
    # large (1e9) to restore the literal "nearest occurrence, however far" rule.
    'timingMaxDistanceSeconds': 30.0,
    # Specific anchors only: a number is a timing anchor if it has >= this many digits or
    # contains , . %; shorter numbers anchor only through an adjacent unit word that is also
    # adjacent at the spoken occurrence; a non-numeric stat `big` anchors if it is at least
    # this many characters and occurs in the script.
    'anchorMinDigits': 3,
    'anchorMinBigChars': 4,

    # presenter-share -- LOCKED by lead 2026-11-12: total presenter-only share <= 25 % of the voice-over
    # (cold open up to 10 s and the final beat excluded) and each continuous presenter-only run <= 12 s
    # (punch never resets a run). Independent of how much source footage is left.
    'maxPresenterShare': 0.25,       # presenter-only seconds / voice-over seconds
    'maxPresenterRun': 12.0,         # one continuous presenter-only run, seconds
    'presenterRunReportMin': 7.0,    # runs at least this long are listed in metrics.presenter.runsOver7
    'coldOpenSeconds': 10.0,         # (locked) leading presenter-only time excluded from share/runs

    # cta-length (non-space characters)
    'maxCtaChars': 40,

    # source-reuse
    'sourceReuseWindowSeconds': 60.0,
    'sourceReuseOverlapSeconds': 0.05,

    # provenance
    'lineNeighbors': 1,              # script lines either side of the beat's overlapping lines
    'fractionSourceWindowChars': 40,
    'latinMinLetters': 3,
    # provenance-latin is always a warn (English chips/kickers are editorial translations of the Thai
    # narration); metrics.latin splits the count into editorial labels (these fields) and data-bearing fields.
    'latinEditorialFields': ['kicker', 'headline', 'sub'],
    'thaiShareMin': 0.6,
    'thaiTokenMinLength': 2,
    # Generic chrome words that need no spoken/source support. Do NOT grow this
    # list to make a replay look better; report what fires instead.
    'latinAllowlist': ['AI', 'NEWS', 'TECH', 'SOURCE', 'DEMO', 'UPDATE', 'BREAKING', 'VS'],
}

# --legacy (V3 replay data) changes no numbers; it relaxes the V4-only gates in lint_content.py
# (schema validator may be absent, per-beat visual evidence is not required).
LEGACY_OVERRIDES = {}

# Shown-vs-said checks (lint_content.py, source clip beats): the evidence window is the shown range
# in the ORIGINAL video widened by this many seconds each side.
THRESHOLDS.update({
    'evidenceWindowPadSeconds': 3.0,
    'labelLatinMinLetters': 4,       # Latin words in a source beat's headline checked against the window
    'subjectTokenMinLetters': 3,
})
