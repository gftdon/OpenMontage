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
    # A fraction ("8/10", "8 เต็ม 10", "8 of 10", "8 out of 10") is said when both numbers occur in ONE script line, or in two ADJACENT
    # script lines no further apart than this many characters (and in the source: within this many characters).
    'fractionSourceWindowChars': 40,
    # Fields printed for the whole video whose NUMBERS (not words) need provenance; dateLabel / brand / page.* stay exempt page chrome.
    'chromeNumberFields': ['breakingLabel', 'officialTag'],
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
    'subjectTokenMinLetters': 4,     # a subject term needs at least one word of this many characters (digits alone never count)
    'evidenceSeenMinChars': 15,      # `seen` (what the judge saw in the frames) must be a string of at least this many characters
    # Small explicit stoplist: function words and generic fillers that prove nothing about what is on screen.
    'subjectStopwords': ['this', 'that', 'with', 'from', 'have', 'will', 'very', 'about', 'there', 'their', 'which', 'would', 'could', 'should',
                         'these', 'those', 'into', 'over', 'also', 'just', 'like', 'then', 'than', 'when', 'what', 'your', 'they', 'them', 'here',
                         'more', 'most', 'some', 'such', 'only', 'really', 'going', 'thing', 'things'],
})

# typo-filler: the episode fails when more than this share of its typo card / item / vs texts has Thai words the script does not support
# (the provenance-thai test). starting value set by the implementer, not an acceptance threshold -- report to lead.
THRESHOLDS['typoFillerMaxShare'] = 0.30

# crop-trims-source (lint_content.py, ERROR): a beat's srcCrop that trims any edge of the 1920x1080 source frame by MORE than this many
# percent of that side fails the lint. No exceptions: the default is "no srcCrop" (show the whole source frame). Decided by the project lead
# 2026-11-12 after the proof run, where an unattended agent kept srcCrop on 42 of 44 clips (trimming up to 15 % of an edge). 2.0 was the
# warning threshold before and is unchanged. Module constants below are NOT overridable with `lint_content.py --set` on purpose (a gate an
# unattended agent can switch off from the command line is not a gate).
CROP_TRIM_MAX_PERCENT = 2.0

# episode-copied (lint_content.py, ERROR): the episode fails when at least this share of its beats (those that have a `src` or a `headline`)
# has a counterpart (same media, same headline, same footage: the same normalised `src` name OR the same cut of the same source video, see
# lint_content.norm_copy_text / _same_footage) among the beats of ONE other episode-format JSON file found under the skill directory or under
# another project of the repo, OR at least this share of THAT file's beats has a counterpart here (padding the episode with new beats does not
# dilute a copy), AND at least COPY_MIN_SAME beats are the same (a handful of shared headlines in two short episodes is not a copy).
# Measured (beat times are not part of the metric; see the W2b result packet for the full table):
#   proof-run episode (projects/V261111_001, agent-made) vs the real episode it copied: 58 of 68 eligible beats = 85.3 %
#     (the proof run's own count was 67 of 79 beats identical in media, src, headline AND kicker = 85 %)
#   same proof-run episode vs the engine sample ytNewsStyle01V4Sample.json (a different video): 0 of 68 = 0.0 %
# an independent episode is expected at ~0 %; 20 % leaves a wide margin on both sides and still catches a half-rewritten copy.
COPY_MAX_SHARE = 0.20
COPY_MIN_SAME = 5

# The copy search reads other JSON files: only regular files up to this size (an episode is a few hundred KB; a bigger .json is skipped and
# counted in metrics.copy.skipped_large), and the whole search must finish within this many seconds (the content gate's own limit is 60 s;
# a search that does not finish fails with copy-search-incomplete: "no copy found" must never mean "did not look").
COPY_MAX_FILE_BYTES = 5 * 1024 * 1024
COPY_WALK_BUDGET_SECONDS = 30.0
