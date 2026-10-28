# HANDOVER

Read first: [ARCHITECTURE.md](ARCHITECTURE.md), [CONSTRAINTS.md](CONSTRAINTS.md). Newest entry on top. Update last, every session.

## Latest session: 2026-10-28 (model: Claude Opus 5.5, `claude-opus-5-5`; switched from Claude Sonnet 5.5 at the start of this session; Docker and `/alerts/check` designs reviewed with Codex)

**Done**
- Releases, all published by release-please with no human step after merge since v0.2.1: v0.1.1 (verdict engine #87), v0.2.0 (recompute tooling #91), v0.2.1 (`/alerts/check` takes the stored verdict, caller-scoped, fails closed, #115), v0.2.2 (GitHub Pages removed, no LAN-address API fallback, #123), v0.3.0 (Docker CI #126, one origin behind Caddy with the API under `/api/` #128, portable config defaults #127), v0.4.0 (arm64 CI #130, filing PDFs in Cloudflare R2 #131, D-016), v0.5.0 (Cloudflare Tunnel mode #134, D-017).
- Tests: coverage floors and `pip check` (#93), HTTP contracts with the 34-route tier matrix (#94); the `docker` and `docker-arm64` jobs build the images and run `scripts/docker_smoke.sh` and `scripts/proxy_smoke.sh` (both Caddy modes, per-client rate-limit buckets). Backend floor 47.2%.
- Production compose: one API worker by default (#115), `api_cache` volume for watchlists (#118), no MinIO container (its free image is gone; R2 instead, #131), tunnel mode (#134); `.env.*` ignored by git (#133).
- Automation: docs-only PRs auto-merge (#96, #98); Dependabot runs monthly with grouped minor/patch, majors and security updates, and patch-level security updates for Actions and the UI auto-merge (#100, #119, #138); UI-stack majors are ignored until the planned upgrade. `RELEASE_PLEASE_TOKEN` lives in the `release` environment (only `main`). Old Dependabot PRs closed; only the `main` branch remains, on GitHub and locally.
- Infrastructure set up by the maintainer: `halallens.in` (BigRock registrar) moved its DNS to Cloudflare and is active, with stale records to a dead AWS address deleted; Cloudflare Tunnel `halallens` created; R2 bucket `bse-pdfs` with a bucket-scoped token; an Oracle Resource Manager stack `halallens-prod` (A1.Flex, 2 OCPU / 12 GB, Ubuntu 24.04 aarch64, new `halallens-vcn`) whose instance creation keeps failing with "Out of host capacity".

**In progress**
- First deployment on `halallens.in`: waiting for Oracle Ampere capacity (retry the stack's Apply). Then fill the server `.env` (from the local, git-ignored `.env.production`), install Docker, build from the `v0.5.0` tag and start the stack in tunnel mode.
- Docker plan agreed with Codex: steps 1 and 2 done; next are hardening (non-root, one Python image, digest-pinned bases, `LICENSE` in images, Node 20 to the current LTS), a pull-only compose file with a runbook, then CI-gated publishing to Docker Hub (amd64 + arm64).
- Wider auto-merge (D-015) stays held until test-plan steps 3 to 8 land.

**Broken or risky**
- Stored evaluations from the old engine may still say `compliant` until recomputed (no production data yet).
- Watchlists are a JSON file rewritten without a lock: the API must run one worker until they move to Postgres.
- `_detect_scale` substring scaling, the process-lifetime `lru_cache` of Indian Stock API failures, the free-tier `callAnalysis` always calling the paid `/narrate`, and announcements fetched from page 1 only (AGENTS.md "Known defects").
- Node 20 is end-of-life in the UI image and CI.
- SSH to the Oracle VM is open to the internet by the maintainer's choice (key-only login; fail2ban and unattended upgrades planned on the VM).
- Not yet seen live: a real R2 upload, the tunnel serving the site, Google sign-in and the Razorpay webhook on the `/api/` URLs. `docker` and `docker-arm64` are not required checks in the ruleset yet.

**Next**
1. Deploy once the Oracle VM exists; register `https://halallens.in/api/auth/google/callback` with Google and `https://halallens.in/api/webhooks/razorpay` with Razorpay.
2. Docker plan steps 3 to 5 (hardening, pull-only compose and runbook, publishing).
3. Move watchlists to Postgres (then more than one API worker).
4. Test plan steps 3 to 8 (billing, Postgres and migrations, parser fixtures, UI and Playwright, merge policy), then the Next/React/TypeScript upgrade.

**Do not touch**
- Medical-ChatBot's Oracle VM and `medical-chatbot-vcn`. Production deploys outside the controlled cutover (`docs/ROLLBACK.md`). Force-pushes to `main`.

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
