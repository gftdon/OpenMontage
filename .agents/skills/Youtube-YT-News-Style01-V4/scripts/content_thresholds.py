"""Thresholds for lint_content.py (plain Python dict, no JSON config).

Every number the lead may still change lives here; `lint_content.py --set key=value`
overrides any key for one run (value parsed as JSON), and `--legacy` applies
LEGACY_OVERRIDES (replay of V3 data that predates card kinds).
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

    # presenter-share
    'maxPresenterShare': 0.25,       # presenter-only seconds / voice-over seconds
    'maxPresenterRun': 12.0,         # one continuous presenter-only run, seconds
    'presenterRunReportMin': 7.0,    # runs at least this long are listed in metrics
    'coldOpenSeconds': 10.0,         # leading presenter-only time excluded from share/runs

    # cta-length (non-space characters)
    'maxCtaChars': 40,

    # typo-kind
    'requireTypoKind': True,
    'typoKinds': ['summary3', 'vs', 'final4', 'default'],

    # source-reuse
    'sourceReuseWindowSeconds': 60.0,
    'sourceReuseOverlapSeconds': 0.05,

    # provenance
    'lineNeighbors': 1,              # script lines either side of the beat's overlapping lines
    'fractionSourceWindowChars': 40,
    'latinMinLetters': 3,
    'thaiShareMin': 0.6,
    'thaiTokenMinLength': 2,
    # Generic chrome words that need no spoken/source support. Do NOT grow this
    # list to make a replay look better; report what fires instead.
    'latinAllowlist': ['AI', 'NEWS', 'TECH', 'SOURCE', 'DEMO', 'UPDATE', 'BREAKING', 'VS'],
}

LEGACY_OVERRIDES = {
    'requireTypoKind': False,
}
