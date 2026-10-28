# HANDOVER

Read first: [ARCHITECTURE.md](ARCHITECTURE.md), [CONSTRAINTS.md](CONSTRAINTS.md). Newest entry on top. Update last, every session.

## Latest session: 2026-10-28 (model: Claude Opus 5.5, `claude-opus-5-5`; switched from Claude Sonnet 5.5 at the start of this session)

**Done**
- PR #87 (verdict engine) and PR #88 (docs, AGENTS.md, CLAUDE.md) merged by the maintainer. Release PR #89 (`0.1.1`) is open.
- Maintainer reviewed the DEFENSE brief and agreed with it (draft banner removed). Their table alignment and wording edits are committed.
- Codex session ID and the local field-guide path removed from the tracked files (they remain in earlier git history).
- Maintainer decisions: Docker deployment is the canonical UI (D-011); no production data yet, so the dry run waits (D-012); leaked secrets were sandbox-only and rotated; Codex re-check of #87 skipped for now.

**In progress**
- Recompute tooling (`jobs.backfill_evaluations --recompute`) in PR #91, stacked on #90; reviewed with Codex. The review found that `get_recent_filings` never returned `ratios`, so the plain backfill overwrote evaluated filings and the recompute selected nothing; fixed with a `has_ratios` projection. Also points `scripts/run_backfill_2025.sh` at `jobs.precompute_evaluations`.

**Broken or risky**
- Stored evaluations computed by the old engine stay possibly false-`compliant` until recomputed (development data only for now).
- `/alerts/check` still trusts the caller's verdict and iterates every user's entries.

**Next**
1. Security PR for `/alerts/check`.
2. Decide whether to keep `nextjs.yml` (Pages is not the canonical UI).

**Do not touch**
- Production deploys outside the controlled cutover (`docs/ROLLBACK.md`). Force-pushes to `main`.

## Session: 2026-10-27 (model: Claude Sonnet 5.5, `claude-sonnet-5-5`; design reviewed with Codex, 3 rounds; LLM mode restored at the maintainer's request, D-010; AGENTS/CLAUDE/MEMORY synced)

**Done**
- CI rework merged (PR #74): `backend`, `ui`, `secrets` checks, SHA-pinned actions, torch/langchain/playwright/etc. removed from `Pipfile` (103 -> 47 packages), `python_full_version` pin removed (it broke image builds).
- Automation merged (PR #75): Dependabot, narrow auto-merge (Actions + UI dev deps, minor/patch), release-please. Ruleset on `main` (PR + 3 required checks, owner bypass), delete-branch-on-merge, Actions may open PRs.
- Verdict fix open as **draft PR #87**: engine-owned verdict, strict completeness, exact Decimal decisions, shared `coerce_amount`, optional LLM mode kept behind a best-effort guard. CI green.
- Docs (PR #88, stacked on #87): README rewritten to match the code; false claims fixed in the ops, ingestion, plan and mobile docs; this `docs/` set added.
- GitHub metadata updated (description, topics: `llm` removed, `bse`/`docker`/`india`/`postgresql` added; dead homepage `halallens.ai` cleared). The portfolio-website and resume sessions were told what is verified and what to avoid claiming; they decide their own edits.

- Process: `AGENTS.md`, `CLAUDE.md` and the memory index are kept in sync (rule and end-of-session check are in AGENTS.md). `AGENTS.md` and `CLAUDE.md` are committed in PR #88; the memory notes live outside the repo. Local tooling dirs stay untracked (never `git add -A`).

**In progress**
- PR #87 awaits review. Codex has not re-checked its last three fixes (its usage limit hit; resets 2026-10-28 00:17).

**Broken or risky**
- **Stored evaluations still hold old, possibly false-`compliant` verdicts.** `jobs/backfill_evaluations.py` skips rows that already have ratios, so it cannot repair them.
- Most filings will probably screen as `insufficient-data` once #87 is active (interest/dividend rarely extracted). Unmeasured.
- `/alerts/check` trusts the caller's verdict and iterates every user's entries.
- LLM narration (when `NARRATOR_MODE=llm`) is best-effort: a paraphrase can still contradict the verdict; the UI says so. Keep `rule_based` if you need guaranteed consistency.

**Next**
1. Review and merge #87 (merge is not activation).
2. PR-B: recompute + dry-run tooling (stored inputs, before/after CSV, no vendor calls, dry-run by default, governance overrides preserved).
3. Dry run -> you review the distribution -> controlled cutover (see [ROLLBACK.md](ROLLBACK.md)).
4. Separate security PR for `/alerts/check` before live alerts resume.

**Do not touch**
- Do not deploy code from #87 to production outside the cutover window.
- Do not narrow the five required ratios without a scholar-approved methodology decision.
- Secrets, `.env`, key files, force-pushes to `main`, and the payment/auth code need review before any change.

Read first: ARCHITECTURE.md, CONSTRAINTS.md, ROLLBACK.md.
