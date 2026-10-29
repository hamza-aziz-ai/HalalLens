# HANDOVER

Read first: [ARCHITECTURE.md](ARCHITECTURE.md), [CONSTRAINTS.md](CONSTRAINTS.md). Newest entry on top. Update last, every session.

## Latest session: 2026-10-29, afternoon (model: Claude Opus 5.5, `claude-opus-5-5`): email, auth hardening, watchlists in Postgres, Next 16, payments

**Done** (production runs **v0.9.0** on the Oracle VM)
- Payments (Razorpay **test** keys only): order, checkout, signature verification and webhook proven end to end in production (a test Annual purchase granted the plan until 2027-10-29; one webhook event recorded). #178 handles checkout dismissal and shows Razorpay's failure reason. The maintainer's Razorpay account is KYC-verified; a ₹100 live test through razorpay.me was refunded (that path never touches the app).
- `/products/` page (plans read live from `/billing/plans`, "information and education only, not investment advice") and a site footer linking every policy page (#178). Support mailbox `support@halallens.in` via Cloudflare Email Routing to the maintainer's Gmail, shown on the policy pages from `SUPPORT_EMAIL` (no hardcoded address). SPF is merged (`_spf.mx.cloudflare.net` + Oracle); Cloudflare's checker still reports "misconfigured" because it expects its exact string, while routing works.
- Pull-only deploys: `scripts/deploy.sh vX.Y.Z` in the repo; with `IMAGE_REPOSITORY` in `.env` it pulls the CI-published images for the tag instead of building on the server. The publish workflow bakes the repository variable `SUPPORT_EMAIL` into the UI image.
- Email: OCI Email Delivery (Mumbai, free tier about 3,000 a month), sender `no-reply@halallens.in`; SPF, DMARC (`p=none`) and the DKIM CNAME are in Cloudflare and the DKIM key is ACTIVE. SMTP settings are in the server `.env` (credential never displayed).
- Auth hardening (#172, D-020, design agreed with Codex): email-first sign-up, set-password/reset links, sessions only for verified emails, admin from `ADMIN_EMAILS` only after the mailbox is proven, Google matched by subject only with `email_verified=true`; reset and login share a row lock. #173 (D-021): browser-bound single-use Google flows (`oauth_flows`, `hl_oauth` cookie) and explicit "Link Google account" on the account page. Verified in production: a new account signed up, verified and linked Google; the maintainer's admin was restored by a fresh Google sign-in.
- Watchlists in Postgres (#163, D-019) with seed-first conditional updates (Codex caught the flip-first race; the real-Postgres test fails 20/20 with flip-first).
- Next.js 16.4.2 / React 19 / ESLint 9 flat config (#164); the dashboard image applies Alpine security updates (#170, a brotli CRITICAL failed the v0.7.0 publish); Next 16.4.3 and other Dependabot updates merged (#167 to #169).
- Repo: `docker` and `docker-arm64` are required checks; Docker Hub pages get their descriptions from `docs/dockerhub/*.md` via a workflow (#176); categories set by the maintainer.
- Council: free BSE/NSE data sources reviewed with Codex: no comprehensive authorised zero-cost route for filings; BSE and NSE feeds refuse honest automated clients; written permission or a licensed feed are the options.

**In progress / next**
- BSE announcements data source: maintainer decides later (permission request or licensed feed). Until then production stores no filings.
- Switch production to pull mode: set `IMAGE_REPOSITORY` in `.env.production`, deploy the next release with `scripts/deploy.sh`; test a refund in Razorpay Test Mode (should end the plan through the webhook).
- Candidates: pull-only deploy from the published images, rewrite the 7 `set-state-in-effect` components, a monthly backup-restore test, a separate R2 bucket for backups.

**Broken or risky**
- Password accounts depend on email delivery; if SMTP fails, sign-up and reset links do not arrive (the API still answers 202).
- Rate limiting is per process: keep `API_WORKERS=1`.
- Opt-in real-Postgres tests (`tests/test_watchlist_postgres.py`, `tests/test_auth_postgres.py`) do not run in CI; run them when `alerts/storage.py` or the auth SQL changes.

## Session: 2026-10-29, later (model: Claude Opus 5.5, `claude-opus-5-5`): data, backups, monitoring, defects

**Done**
- v0.5.3 (#150): Bhavcopy reads BSE's UDiFF file and NSE's market caps from the daily price-report zip, matched by exact ticker before any fuzzy name match. In production, 28 Oct matched 2,497 companies.
- v0.6.0 (#152): nightly `pg_dump` to `backups/postgres/` in R2, 14-day retention, deleted only after a successful upload; the first one is in R2. Deployed to the VM (the maintainer approved the deploy).
- Uptime check (#154): `/api/health` every 30 minutes, opens an `uptime` issue on failure; `UPTIME_URL` repository variable set; the first run passed.
- Defects fixed: free-tier manual analysis no longer fails on the paid `/narrate` (#155); Indian Stock API failures no longer cached for the life of the process, successes cached for 6 hours (#156); `_detect_scale` matches whole unit words (#158); company announcements follow every page with a bounded loop (#159). Releases v0.6.1 to v0.6.3.

**In progress / next**
- Deploy v0.6.3 to the VM: production deploys need the maintainer's approval (`bash ~/vm_deploy.sh v0.6.3` on the VM).
- BSE announcements still answer 403 to the server: data-source decision pending with the maintainer.
- Approved by the maintainer and in progress: `docker` and `docker-arm64` are now required checks on `main` (ruleset updated 2026-10-29); next the Next.js 15/16 upgrade and watchlists in Postgres (schema migration). Pull-only compose and runbook not started.

**Broken or risky**
- Filings parsed before #158 keep values scaled by the old substring rule; re-parse or `--recompute` is a maintainer-run step (no production filings yet).
- Backups share the PDF bucket and its token; a separate bucket and token would isolate them.

## Session: 2026-10-29 (model: Claude Opus 5.5, `claude-opus-5-5`): first production deployment

**Done**
- `https://halallens.in` is live: v0.5.2 runs on the Oracle A1 VM `halallens-prod` (Mumbai, 2 OCPU / 12 GB arm64, Ubuntu 24.04) behind the Cloudflare Tunnel. The VM was created by a CLI launch retry after "Out of host capacity" errors. Verified from the internet: `/`, `/login/`, `/api/health` and `/api/openapi.json` return 200. The VM's own address has no open app ports (80, 443, 5432 and 8001 closed); the host firewall allows only SSH. Preflight reached Postgres and the R2 bucket; the migrations applied; all services are healthy.
- VM hardening: key-only SSH, no root login, fail2ban on sshd, unattended upgrades, Docker from Docker's apt repository. The app lives in `/opt/halallens` (a checkout of the release tag plus `.env`, mode 600).
- Releases: v0.5.1 (Indian Stock API monthly cap and the key no longer in URLs, #145) and v0.5.2 (static UI image: Caddy serving the export, no Node.js or Next.js at runtime, non-root, about 25 MB, #147). The v0.5.1 image publish failed its Trivy gate on Next.js 14 CRITICAL advisories in the old UI image; v0.5.2 published both images, amd64 and arm64, to Docker Hub (`hamzaazizai/halallens-api`, `-ui`) and GHCR, which already allows anonymous pulls.

**In progress / next**
- **BSE blocks the server (blocker for data):** from the Oracle IP, BSE's announcements API answers 403 and the Bhavcopy page no longer has the form the client expects ("Missing hidden fields"), so ingestion stores nothing. The direct Bhavcopy CSV download still answers 200. Needs a maintainer decision on a permitted data source (BSE's official data products, the Indian Stock API within its quota, or another licensed feed); do not work around BSE's blocking.
- Optional settings still empty in the server `.env`: Google sign-in, Razorpay (test keys), SMTP alerts. Then register the Google callback and the Razorpay webhook on the `/api/` URLs.
- Pull-only compose and a runbook, so the VM pulls the published images instead of building; add `docker` and `docker-arm64` to the required checks.

**Broken or risky**
- No filings or evaluations in production until the BSE question is settled; the dashboard shows empty lists.
- The UI still builds with Next.js 14.2.35 (only the build stage now); the UI-stack upgrade to 15 or 16 remains open.

## Session: 2026-10-28 (model: Claude Opus 5.5, `claude-opus-5-5`; switched from Claude Sonnet 5.5 at the start of this session; Docker and `/alerts/check` designs reviewed with Codex)

**Done**
- Releases, all published by release-please with no human step after merge since v0.2.1: v0.1.1 (verdict engine #87), v0.2.0 (recompute tooling #91), v0.2.1 (`/alerts/check` takes the stored verdict, caller-scoped, fails closed, #115), v0.2.2 (GitHub Pages removed, no LAN-address API fallback, #123), v0.3.0 (Docker CI #126, one origin behind Caddy with the API under `/api/` #128, portable config defaults #127), v0.4.0 (arm64 CI #130, filing PDFs in Cloudflare R2 #131, D-016), v0.5.0 (Cloudflare Tunnel mode #134, D-017).
- Tests: coverage floors and `pip check` (#93), HTTP contracts with the 34-route tier matrix (#94); the `docker` and `docker-arm64` jobs build the images and run `scripts/docker_smoke.sh` and `scripts/proxy_smoke.sh` (both Caddy modes, per-client rate-limit buckets). Backend floor 47.2%.
- Production compose: one API worker by default (#115), `api_cache` volume for watchlists (#118), no MinIO container (its free image is gone; R2 instead, #131), tunnel mode (#134); `.env.*` ignored by git (#133).
- Automation: docs-only PRs auto-merge (#96, #98); Dependabot runs monthly with grouped minor/patch, majors and security updates, and patch-level security updates for Actions and the UI auto-merge (#100, #119, #138); UI-stack majors are ignored until the planned upgrade. `RELEASE_PLEASE_TOKEN` lives in the `release` environment (only `main`). Old Dependabot PRs closed; only the `main` branch remains, on GitHub and locally.
- Infrastructure set up by the maintainer: `halallens.in` (BigRock registrar) moved its DNS to Cloudflare and is active, with stale records to a dead AWS address deleted; Cloudflare Tunnel `halallens` created; R2 bucket `bse-pdfs` with a bucket-scoped token; an Oracle Resource Manager stack `halallens-prod` (A1.Flex, 2 OCPU / 12 GB, Ubuntu 24.04 aarch64, new `halallens-vcn`) whose instance creation keeps failing with "Out of host capacity".

**In progress**
- First deployment on `halallens.in`: waiting for Oracle Ampere capacity (retry the stack's Apply). Then fill the server `.env` (from the local, git-ignored `.env.production`), install Docker, build from the `v0.5.0` tag and start the stack in tunnel mode.
- Docker plan agreed with Codex: steps 1 and 2 done; next are hardening (non-root, one Python image, digest-pinned bases, `LICENSE` in images; Node moved to 24 LTS), a pull-only compose file with a runbook, then CI-gated publishing to Docker Hub (amd64 + arm64).
- Wider auto-merge (D-015) stays held until test-plan steps 3 to 8 land.

**Broken or risky**
- Stored evaluations from the old engine may still say `compliant` until recomputed (no production data yet).
- Watchlists are a JSON file rewritten without a lock: the API must run one worker until they move to Postgres.
- (Fixed on 2026-10-29: `_detect_scale` #158, the Indian Stock API failure cache #156, free-tier `callAnalysis` #155, company announcement paging #159.)
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
