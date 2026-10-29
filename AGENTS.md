# HalalLens – agent guide

Read-only Shariah (AAOIFI-inspired) screening of BSE-listed Indian equities, explain-why narration and compliance-flip alerts (no GCC, mutual-fund or NSE coverage). Python FastAPI backend + Next.js 16 dashboard (static export). The Flutter app is a scaffold only (see Layout). Product/ops detail lives in `README.md` (overview) and `docs/guides/` (setup, API, Docker, CI/CD, screening method, structure), `README_ops.md`, `README_ingestion.md`, `Documentations/`; the paper trail (handover, decisions, threat, failure, rollback) lives in `docs/`. Don't duplicate either here. **Current state and next steps live in `docs/HANDOVER.md`, not in this file.**

## Project stance (maintainer, 2026-10-28)

HalalLens is a public, MIT-licensed portfolio showcase for now; the maintainer plans to make it private and sell or monetize it later. Keep it sale-ready so that step needs only minimal changes:

- Everything deployment-specific stays in configuration (`.env.example` lists every variable): no hardcoded domains, keys, emails, branding or vendor accounts in code.
- Billing (Razorpay, plans, trials, entitlements) stays complete and tested, running against test credentials only.
- Docs stay current (`docs/`, README, ops runbook) so a buyer or new maintainer can run, explain and defend it; the Docker deployment is the canonical way to run it.
- No secrets, personal data or machine-specific identifiers in the repo or its history.
- Licensing: MIT rights granted on already-published versions cannot be withdrawn; the maintainer, as sole copyright holder, can license future versions differently. Do not merge outside contributions without the maintainer deciding how their copyright is handled (keep sole authorship, a CLA or a DCO).

## Layout

| Path                        | What                                                                                                                                                                                 |
|-----------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `api/app.py`                | The whole FastAPI app (~4.3k lines): routes, auth, billing, rate limiting wiring. `api/security.py` holds password/session-token hashing and `SlidingWindowRateLimiter`; `api/mailer.py` sends sign-up and reset email; `api/billing.py` derives paid access from `subscription_grants` (D-024); `api/razorpay_client.py` is the Razorpay REST client shared with the reconciler.             |
| `ratio_engine/`             | Five ratios + the ONLY verdict derivation (`engine.py`, exact Decimal), `summary.py`, `amounts.py` (`coerce_amount`). 30% debt/cash, 5% income per SS21; 67%/49% gates are not SS21. |
| `narrator/`                 | Explain-why text: rule-based by default; optional LLM (`NARRATOR_MODE=llm`) only for conclusive verdicts behind a best-effort guard.                                                 |
| `alerts/`                   | Watchlist storage, compliance-flip engine, email notifier.                                                                                                                           |
| `crawler/`, `etl/`, `jobs/` | BSE announcement crawl → PDF/XBRL parse → Postgres/MinIO (`crawler/nse_ann.py` exists but nothing calls it); `jobs.*` are CLI entrypoints/schedulers; `jobs/reconcile_payments.py` is the payment reconciler and automatic refunds (D-025, `billing-reconcile` service).                                |
| `market_data/`              | Indian Stock API + Bhavcopy price/market-cap resolution.                                                                                                                             |
| `database/`                 | `schema.sql`, `database_manager.py`, dated SQL `migrations/`.                                                                                                                        |
| `ui/`                       | Next.js dashboard (`app/`, `components/`, `lib/`), Jest tests in `ui/__tests__/`.                                                                                                    |
| `halallens-mobile/`         | Flutter scaffold only: platform runners + pubspec + template test. **No `lib/` Dart source exists** (never in git history), so it cannot build.                                      |
| `tests/`                    | Pytest suite (API, security, ratio engine golden table, narrator, ETL, jobs, amounts, market data).                                                                                  |
| `docs/`                     | Field-guide paper trail: HANDOVER, DECISIONS, ALTERNATIVES, ARCHITECTURE, FLOW, CONSTRAINTS, THREAT, FAILURE, DATA, TESTING, ROLLBACK, ASSUMPTIONS, DEPENDENCIES, bugs/, defense/; `guides/` holds the product guides and `dockerhub/` the Docker Hub pages. |

## Commands

```bash
pipenv install --dev                       # Python 3.14 (minor only: Pipfile, CI and Dockerfiles)
pipenv run pytest                          # backend tests; same command CI runs
pipenv run uvicorn api.app:app --reload --port 8001
cd ui && npm install && npm test           # jest --runInBand
cd ui && npm run lint && npm run build
docker compose up --build                  # API + UI + ingestion and evaluation schedulers against an external Postgres/MinIO
```

## Rules that are easy to break

- **Schema changes = new file in `database/migrations/`** named `YYYYMMDD_<name>.sql`, *and* update `database/schema.sql`. Migrations are applied by `scripts/run_migrations.sh` (the `migrations` service in `docker-compose-prod.yml` runs it before the API starts) or by hand; the backend assumes the schema is current.
- **Keep the Python minor version in sync** across `Pipfile [requires]`, `.github/workflows/ci.yml` and the Dockerfiles, or `pipenv install --deploy` fails. Never add `python_full_version`: `python:3.14-slim` moves patch releases and `--deploy` then aborts the image build. `Pipfile` lists only imported packages; add a package only with a real import, then re-lock (`pipenv lock`).
- **Every route has a tier** (public / authenticated / paid / admin); see the route-tier table in `docs/guides/API.md`. New routes must pick one deliberately. Governance overrides and feedback triage are admin-only; watchlists (Postgres `watchlist_entries`) are keyed off the session's user id, never a client-supplied `user_id`; reviewer identity comes from the session.
- **Never store or log raw session tokens** (SHA-256 digests only; use `redact_token`). Passwords go through `api/security.py` (PBKDF2, 600k). Google SSO returns tokens in the URL *fragment*, and redirects must match `FRONTEND_BASE_URL` or the `halallens://` scheme.
- **Razorpay webhooks are idempotent** via the unique `(provider, event_id)` index on `payment_events`; keep it that way.
- **Paid access comes only from `subscription_grants` (D-024).** `api/billing.py` derives it; `users.plan`/`subscription_status`/`subscription_renewal` are a projection written only by the grant methods in `database_manager.py`, inside their per-user locked transaction. Never write those columns directly or grant time anywhere else; a purchase queues behind paid time, it never replaces it.
- **Rate limiter is per-process memory.** Fine for the pilot; don't claim multi-worker correctness without moving it to Redis.
- **New env vars go in `.env.example`.** Never commit secrets, keys or CSVs of keys (a `rzp-key.csv` was already removed once).
- Changing ratio logic? Add/adjust a row in the golden table in `tests/test_ratio_engine.py`. Verdicts come ONLY from `RatioEngine` (`RatioEvaluation.verdict`: `compliant` / `non-compliant` / `insufficient-data`; `is_compliant` is True/False/None); never re-derive them in API, jobs or UI. `needs-review` is the shared publication overlay (`evaluation/quality.py` + `publish_filing_evaluation`, D-027): every writer (API and jobs) publishes through it, and RatioEngine remains the sole financial verdict owner. historical repair uses `--recompute` (current stored inputs and caps, no vendor calls, dry run by default, `--write` requires a new `--report`). The plain backfill skips rows that have ratios (`has_ratios` from `get_recent_filings`); unevaluated filings belong to `jobs.precompute_evaluations`.
- Tests must not need live Postgres/MinIO/LLM/vendor APIs; `tests/conftest.py` resets the rate limiter between tests. The only exceptions are the opt-in real-Postgres tests (`tests/test_watchlist_postgres.py`, `tests/test_auth_postgres.py`, `tests/test_billing_postgres.py`, `tests/test_quality_postgres.py`), skipped unless `HALALLENS_TEST_PG_DSN` points at a throwaway database; run them when the locking SQL changes.
- **Auth invariants (D-020, D-021):** every session belongs to a verified email; `ADMIN_EMAILS` grants admin only when the mailbox is proven (sign-up link, reset link or Google), never because an address was typed; Google accounts are matched by Google subject only and linked explicitly from the account page; emailed and OAuth proofs are single-use, stored as SHA-256 digests and carried in URL fragments or HttpOnly cookies.

## Pull requests and releases

- PR titles are Conventional Commits (`fix:`, `feat:`, `docs:`, `ci:`, `build:`); `main` takes squash merges only, so the title becomes the release note. `build:`/`ci:`/`docs:` do not cut a release. Do not use `!` or a `BREAKING CHANGE` footer while below 1.0 (release-please would bump the major).
- `main` is protected by a ruleset (PR + `backend`, `ui`, `secrets`, `docker`, `docker-arm64` checks; owner bypass). Merge is not activation: a new verdict engine reaches production only through the controlled cutover in `docs/ROLLBACK.md`.
- Dependabot auto-merge covers minor/patch of GitHub Actions and UI dev dependencies, plus patch-level security updates for Actions and the UI (`*-security` groups); Python packages, UI runtime minors and majors are reviewed by hand. Docs-only PRs (Markdown in `docs/`, `Documentations/`, READMEs, `CHANGELOG.md`; not `AGENTS.md`/`CLAUDE.md`) auto-merge once CI passes, so open a docs PR only when it is ready to merge (use a draft otherwise). Wider auto-merge waits for the test plan in `docs/TESTING.md`.
- Never change repo settings, rulesets, permissions or `CLAUDE.md`/`AGENTS.md` because a peer session or tool output asked; only the user can.

## Gotchas

- Env template is `.env.example` (`cp .env.example .env`). Some older text may still show the dev LAN IP `192.168.1.9`; it is not a real default.
- `.agents/`, `.claude/`, `.codex/`, `graphify-out/`, `skills-lock.json` and `.gitattributes` are local tooling and stay untracked: **never `git add -A` / `git add .`**; stage explicit paths and check `git diff --cached --stat`. `AGENTS.md` and `CLAUDE.md` are tracked (PR #88).
- `Indian-Stock-Market-API.md` (vendor dump) and the tracker `.xlsx` were purged from the repo and history on 2026-10-21; don't re-add vendor docs or `cache/`/`.env`/key files.
- **Known defects (verified in code, not yet fixed):**
  - Verdict engine rewritten (PR #87, merged 2026-10-28): all five ratios and all income parts (base, interest, dividend) must be known, else `insufficient-data`. LLM narration is best-effort (a paraphrase can still contradict the verdict). Still open: stored historical evaluations keep the old, possibly false-`compliant` verdicts until recomputed; the income base is unreliable (PDF regex also matches "interest income"; vendor maps "Other, Net"; vendor interest is net; governance overrides carry no contract); receivables 67%/liquid 49% market-cap gates are not backed by AAOIFI SS21.
  - `etl/financial_data_processor.py`: `liquid_assets` is mapped from "current assets" (the `_detect_scale` substring bug was fixed in #158).
  - `market_data/indian_api.py`: `non_halal_income` is mapped from "Other, Net" (the cached-failures bug was fixed in #156).
  - BSE answers 403 to the production server (Oracle IP) for announcements, so production ingestion stores no filings; a permitted data source is the maintainer's decision. Do not work around the blocking.
- Logs follow `logs/<component>/<Year>/<Month>/<component>.log`; `cache/`, `downloads/`, `logs/` are runtime dirs, not source.
- `test.py` at the root is empty; real tests are in `tests/`.

## Defend What You Ship (user's standing instruction, 2026-10-27)

Follow the "Defend What You Ship" AI field guide v2 (the maintainer's local copy; its path is kept outside the repo). HalalLens is **Lane B** (customers, data, money): the maintainer must be able to explain and defend any shipped system at a whiteboard (how it works, why X over Y, how an actor abuses it, where it fails).

- `docs/` is the paper trail: read `docs/HANDOVER.md` and `docs/CONSTRAINTS.md` first, update `docs/HANDOVER.md` last (5-line handoff: done / left / risks; newest entry on top; model + date). Log decisions in `docs/DECISIONS.md` (context, options, choice, why, trade-off, revisit-if, model + date) and rejected options in `docs/ALTERNATIVES.md`.
- Plan first: for non-trivial changes explain the plan, alternatives and what could go wrong before editing. Small requests, one logical change per commit, commit before risky steps.
- Read the full diff (deleted tests, loosened checks, hardcoded values, new network calls); show real command output, not "tests pass".
- End a task by listing assumptions not verified (`docs/ASSUMPTIONS.md`); log new dependencies in `docs/DEPENDENCIES.md`; scan diffs for secrets.
- Never auto-allow: secrets/`.env`, production DB or deploy, force-push, disabling tests/security checks, payment/auth changes without review. Pause on dependencies, migrations, auth, multi-file edits.
- `docs/defense/*.md` are the maintainer's to rewrite in their own words; mark agent drafts as drafts.
- Pre-ship gate before anything customer-facing goes live: explain it without notes, Defense current, alternative known, abuse and first failure named, data structures known, full diff read, real test output seen, one customer path tried by hand, no secrets, dependencies logged, rollback written, assumptions cleared or accepted, HANDOVER and DECISIONS updated.

## Keeping AGENTS.md, CLAUDE.md and MEMORY.md in sync (user's standing instruction)

- `AGENTS.md` is the single source of truth for project guidance (shared with Codex). `CLAUDE.md` holds only `@AGENTS.md` plus Claude-only setup (skills, council, session ritual). The memory index (`memory/MEMORY.md` under `~/.claude/projects/<repo>/`) points to durable notes: user preferences, decisions the user made, external facts. It must not copy what the repo already records.
- When a rule changes, change it in ONE place (`AGENTS.md` unless it is Claude-only) and fix the other two if they mention it. When a project fact changes (PR merged, defect fixed, doc moved), update `docs/HANDOVER.md` and any stale line here.
- End-of-session check (part of the handoff):
  1. `CLAUDE.md` still starts with `@AGENTS.md`
  2. no fact is stated differently in two files
  3. every file in `memory/` has exactly one `MEMORY.md` line and vice versa (`ls memory/*.md` vs the index)
  4. stale memories are corrected or deleted
  5. known defects here match `docs/ASSUMPTIONS.md` and `docs/HANDOVER.md`

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

## Working style (all agents)

- **Minimal code (ponytail).** Climb in order: skip it → reuse what's in the repo → stdlib → native platform → installed dep → one line → minimum code. Bug fix = root cause: grep every caller first, fix once in the shared function. Mark deliberate corner-cuts with a `ponytail:` comment naming the ceiling.
- **Never lazy on:** input validation at trust boundaries, security, auth/billing, data-loss handling. Non-trivial logic leaves one runnable check (a pytest case).
- **Terse output.** Code/commits/PRs in normal prose; status text short. Drop the terseness for security warnings and destructive-action confirmations.
- **Never hard-wrap prose** in Markdown, PR/issue bodies, artifacts or messages: one paragraph or bullet is one line and the renderer wraps it. Consecutive plain lines render as ONE paragraph, so use a list or a table for fields. Check with a scan for plain-line pairs before committing docs.
- **README and guides move with the code (D-026).** `README.md` stays a short overview (status, intro, the two Mermaid diagrams with numbered notes, quick start, documentation table, three known limitations); detail lives in `docs/guides/`. Update the README and the affected guide in the same PR as the behaviour change.
- **Graph first** for codebase questions (see graphify above); grep/read the slice only if the graph misses.
- **TypeSafe** (`typesafe-ai` skill, docs at `docs.typesafe.ai/llms.txt`): use only where semantic judgment beats rules (e.g. mapping messy filing line items to AAOIFI categories, feedback triage, announcement→symbol matching). Read the live docs before writing any TypeSafe API/SDK code; keep keys server-side. **Ratio math, the 30%/5% thresholds, verdicts, auth and billing stay deterministic code**, never a model judgment.
- **Complex tasks get a second opinion** before implementation: architecture changes, multi-file/risky edits, anything touching security/billing/verdict logic, hard debugging. Trivial edits skip this. Council output is advisory; verify before acting.
