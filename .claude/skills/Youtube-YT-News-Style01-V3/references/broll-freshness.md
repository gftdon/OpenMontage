# Production B-roll freshness (inherited V2 gate)

Every broll/clip/typo src appears in at most one beat. Source clips use yt_ prefix and must be cut from this episode source. Stock is fresh only when downloaded for this episode by fetch_broll, present in its manifest with matching raw hash and not present in another episode by content. At most two deliberately approved old stock files are allowed. Renaming does not make content fresh.

Use a NEW slug and mediaDir per episode; never copy another episode's B-roll library for production. Select queries from this episode's spoken lines; source UI first. Semantic/vision relevance validation is a separate B-roll selection workflow, not proven by uniqueness.

Production command (run only with explicit authority to update its ledger):

```bash
python3 .claude/skills/Youtube-YT-News-Style01-V3/scripts/check_broll.py remotion-composer/src/<CompId>.tsx --media-dir <mediaDir> --manifest projects/<slug>/assets/broll/_manifest.json --public-root remotion-composer/public --projects-root projects --ledger projects/_broll_ledger.json
```

The checker auto-seeds its selected ledger. For regression tests, supply an isolated test ledger and project/public roots; never point a test at main's ledger. Reused stock from the historical regression is explicitly old: a passing engine gate does not mean production freshness passed. Do not relax the cap or forge a fetch manifest to claim freshness. Record production ledger only after authorized delivery.
