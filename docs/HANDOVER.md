# HANDOVER

Read first: [ARCHITECTURE.md](ARCHITECTURE.md), [CONSTRAINTS.md](CONSTRAINTS.md). Newest entry on top. Update last, every session.

## Latest session: 2026-10-27 (model: Claude Sonnet 5.5, `claude-sonnet-5-5`; design reviewed with Codex, 3 rounds)

**Done**
- CI rework merged (PR #74): `backend`, `ui`, `secrets` checks, SHA-pinned actions, torch/langchain/playwright/etc. removed from `Pipfile` (103 -> 47 packages), `python_full_version` pin removed (it broke image builds).
- Automation merged (PR #75): Dependabot, narrow auto-merge (Actions + UI dev deps, minor/patch), release-please. Ruleset on `main` (PR + 3 required checks, owner bypass), delete-branch-on-merge, Actions may open PRs.
- Verdict fix open as **draft PR #87**: engine-owned verdict, strict completeness, exact Decimal decisions, shared `coerce_amount`, deterministic narration. CI green.
- Docs: README rewritten to match the code; this `docs/` set added.

**In progress**
- PR #87 awaits review. Codex has not re-checked its last three fixes (its usage limit hit; resets 2026-10-28 00:17).

**Broken or risky**
- **Stored evaluations still hold old, possibly false-`compliant` verdicts.** `jobs/backfill_evaluations.py` skips rows that already have ratios, so it cannot repair them.
- Most filings will probably screen as `insufficient-data` once #87 is active (interest/dividend rarely extracted). Unmeasured.
- `/alerts/check` trusts the caller's verdict and iterates every user's entries.
- The GitHub repo description / README mentioned an optional LLM mode; LLM narration is bypassed.

**Next**
1. Review and merge #87 (merge is not activation).
2. PR-B: recompute + dry-run tooling (frozen stored inputs, before/after CSV, no vendor calls, dry-run by default, governance overrides preserved).
3. Dry run -> you review the distribution -> controlled cutover (see [ROLLBACK.md](ROLLBACK.md)).
4. Separate security PR for `/alerts/check` before live alerts resume.

**Do not touch**
- Do not deploy code from #87 to production outside the cutover window.
- Do not narrow the five required ratios without a scholar-approved methodology decision.
- Secrets, `.env`, key files, force-pushes to `main`, and the payment/auth code need review before any change.

Read first: ARCHITECTURE.md, CONSTRAINTS.md, ROLLBACK.md.
