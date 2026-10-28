# HANDOVER

Read first: [ARCHITECTURE.md](ARCHITECTURE.md), [CONSTRAINTS.md](CONSTRAINTS.md). Newest entry on top. Update last, every session.

## Latest session: 2026-10-28 (model: Claude Opus 5.5, `claude-opus-5-5`; switched from Claude Sonnet 5.5 at the start of this session)

**Done**
- PR #87 (verdict engine) and PR #88 (docs, AGENTS.md, CLAUDE.md) merged; released as v0.1.1. Recompute tooling (#91) merged; released as v0.2.0 (#99), the first release PR opened with the maintainer's token from the `release` environment.
- Test plan agreed with Codex (docs/TESTING.md, "Road to CI as the only merge gate"): PR1 coverage floors and `pip check` (#93) and PR2 HTTP contracts with the 34-route tier matrix (#94) merged; backend coverage floor 46.4%.
- Automation: docs-only PRs auto-merge (#96, #97 merged itself); the rule now only undoes auto-merge it enabled, by label (#98). All 39 open Dependabot PRs were closed on the maintainer's request. `RELEASE_PLEASE_TOKEN` moved from a repository secret to the `release` environment (only `main`).
- Maintainer reviewed the DEFENSE brief and agreed with it (draft banner removed). Their table alignment and wording edits are committed.
- Codex session ID and the local field-guide path removed from the tracked files (they remain in earlier git history).
- Maintainer decisions: HalalLens is an open-source showcase now and will be privatized and monetized later, so it stays sale-ready (D-013, AGENTS.md "Project stance"); Docker deployment is the canonical UI (D-011); no production data yet, so the dry run waits (D-012); leaked secrets were sandbox-only and rotated; Codex re-check of #87 skipped for now.

**In progress**
- PR #100: grouped Dependabot updates (`actions`, `ui-dev`, `ui-runtime`, `python`), `build(deps)` titles, `@types/node` held at Node 20, manual trigger for release-please. After it merges, Dependabot runs and the grouped PRs are the live check of Dependabot auto-merge.
- Wider auto-merge (D-015) is held until test-plan steps 3 to 8 land; sensitive paths will keep an owner merge.
- Not yet seen live: a release PR merging itself with no human step (v0.2.0 needed one re-enable because of the docs-rule clash fixed in #98). The next `fix:` or `feat:` merge is the check.

**Broken or risky**
- Stored evaluations computed by the old engine stay possibly false-`compliant` until recomputed (development data only for now).
- `/alerts/check` fix (stored verdict, caller-scoped, fail-closed) is in its PR; the watchlist JSON store still has no lock, so the API must run one worker until watchlists move to Postgres.

**Next**
1. Move watchlists to Postgres with a conditional update (then `API_WORKERS` can go above 1).
2. Test plan steps 3 to 8 (billing contracts, Postgres and migrations, parser fixtures, UI and Playwright, Docker, merge policy).
3. Next 15 and eslint upgrade together, after the Playwright smoke exists.
4. Decide whether to keep `nextjs.yml` (Pages is not the canonical UI).

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
