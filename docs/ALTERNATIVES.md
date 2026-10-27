# ALTERNATIVES

What we turned down, why, and what would change our mind. Decisions that chose between these are in [DECISIONS.md](DECISIONS.md).

| Choice | Rejected option | Why rejected | Revisit if |
| ------ | --------------- | ------------ | ---------- |
| Verdict states | A fourth numeric "borderline" state | Closeness to a cap does not change `<=` semantics; `needs-review` already covers data quality | A scholar defines a review band |
| Required ratios | Only debt, cash and income required | Methodology change smuggled into a bug fix; SS21 does not back the two extra gates either way | Scholar-approved methodology |
| Float tolerance | Epsilon (e.g. 1e-9) around thresholds | An undocumented tolerance can flip a real failure to a pass; exact Decimal has no tolerance | Never for decisions |
| LLM prose | Keyword/polarity guard, then structured status field | Both passed contradictory prose in Codex's counterexamples | Per-claim validation against ratio facts |
| Legacy rows | A quarantine flag / schema field to hide unrecomputed results | Needs a migration; a controlled cutover (recompute in the maintenance window) gives the same safety | Cutover cannot be done atomically |
| Registry | Docker Hub as primary | Needs a stored token and has pull limits; GHCR uses the built-in token | The user wants Docker Hub discoverability (mirror on release tags) |
| Releases | semantic-release; manual tags | semantic-release needs more secrets; manual tags get forgotten | Release volume grows |
| Dependency bots | Renovate | One more app to trust; Dependabot is already present | Grouping needs outgrow Dependabot |
| Auto-merge | Merge every Dependabot PR | Python/prod deps touch verdict and ETL paths with thin tests | Golden + ETL coverage proves them |
| Deploy | Watchtower pull-based auto-deploy | No approval gate or migration ordering on a billing app | Never without a gate |
| Pages vs VM | Delete `nextjs.yml` | The Pages site is live; deleting it is the maintainer's call | Maintainer decides the canonical UI |
| Backfill | Reuse `jobs.backfill_evaluations` for history | It skips rows with ratios, caps at 500 and re-enriches from the vendor | Never; PR-B adds a recompute mode |
