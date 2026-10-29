# HANDOVER

Read first: [ARCHITECTURE.md](ARCHITECTURE.md), [CONSTRAINTS.md](CONSTRAINTS.md). Newest entry on top. Update last, every session.

## Latest session: 2026-10-29, late night (model: Claude Opus 5.5, `claude-opus-5-5`): Postgres 17, one publication path, input mappings, docs, lint

- **Done:** production runs **v0.17.4 on Postgres 17.11** (cutover 17:35-17:38 UTC by the README_ops runbook, D-029: final dump checksummed and copied to `backups/upgrade/`, restore into the new volume `postgres17_data` with identical per-table counts and sequences, migrations all skipped, one backup on 17 uploaded; `REQUIRE_EXISTING_DB=1` is now in the server `.env`). #222 (D-027): every writer publishes through `publish_filing_evaluation` under an advisory lock, reads fail closed, market recovery clears only what a live lookup disproves. #220 (D-028): unsafe input mappings removed (no current assets, no "Other, Net", no net interest; the prohibited-income base only from a governance override). #219 cleared the UI lint warnings. #218 recorded the refund test. Docs: README restructure, ARCHITECTURE and FLOW diagrams, the full Markdown audit and the maintainer's defense page (#211-#217, 2c0653c). Production inventory after deploy: 1 evaluation (not conclusive), 0 conclusive rows with an open issue, so the D-027 repair has nothing to do; the one stored snapshot is vendor-sourced and potentially affected by D-028 but backs no conclusive verdict.
- **Left:** item 6 (flip alerts to subscribers instead of the operator) waits for its council; after 2026-11-12 (14 days) and with the maintainer's OK remove the old volume `halallens_postgres_data`, `upgrade/` on the server, `backups/upgrade/halallens-pg14.dump` and the `postgres:14` image; BSE data source; DMARC `p=quarantine` around 2026-11-05; automatic refunds against Razorpay still untested (ASSUMPTIONS #21, #22).
- **Risks:** since D-028 no filing can reach `compliant` from automated extraction alone (an admin override must supply the prohibited-income base); more filings show `needs-review` (D-027); rollback to Postgres 14 loses every write made on 17 since 17:38 UTC unless re-dumped (README_ops); the D-029 plan was reviewed by the 5-advisor council because Codex was at its usage limit.

## Session: 2026-10-29, night (model: Claude Opus 5.5, `claude-opus-5-5`): billing ledger, reconciliation, automatic refunds, maintenance pages that come and go on their own

**Done** (production runs **v0.17.1** on the Oracle VM, deployed from the published images)
- Billing ledger (#196, D-024): purchases queue behind paid time (Switch / Extend / Upgrade by plan rank, "starts on" dates, "No automatic renewal"); Lifetime covers every plan; settlement is one transaction under a per-user lock; verify grants only a captured payment matching the order. #199: a payment finished on the bank's page is found by polling the order after the checkout closes; labels follow the last queued plan. Proven in production (Test Mode): a Starter bought on top of Annual queued to 29/10/2027, granted by the `payment.captured` webhook.
- Refunds and reconciliation (D-025, three PRs, each designed with Codex and run to agreement): #203 refunds apply only to the payment they refund (a duplicate's refund used to revoke the valid plan) and are summed per refund id; #205 the `billing-reconcile` service sweeps Razorpay payments and refunds every 15 min from a checkpoint (first run linked the pre-ledger Annual to its payment); #207 automatic full refunds of duplicate and `refund_due` payments (TEST keys only, request stored before sending, `X-Refund-Idempotency`), and `GET /api/health/billing` checked by the uptime workflow with `BILLING_EXPECTED=true` (set by the maintainer; a manual run passed).
- Maintenance: Cloudflare Worker `halallens-maintenance` live in front of the site (routes `halallens.in/*` fail open, `halallens.in/api/*` none), serving the same page as Caddy (#194, #201); the page and a dashboard overlay appear and disappear on their own (#201). Outage tests on production: dashboard container down and tunnel down (530 behind the Worker), and the overlay appeared and reloaded by itself; #209 fixed see-through backgrounds (a Tailwind class compiled to an invalid `background-color`, also on 9 pages).
- Google sign-in failures redirect with a message instead of raw JSON, and uvicorn's access log (which recorded OAuth codes) is off (#195). LLM narration uses high reasoning effort at temperature 0 (#190). The first DMARC report was clean (Oracle mail DKIM-aligned once the key went active).
- Councils with Codex now always run to agreement (`max_rounds: 0`, maintainer's default, in CLAUDE.md).

**In progress / next**
- Done 2026-10-29: refund test of the queued Starter (`pay_TtiiAAmu32yhEb`): `refund.processed` revoked only that purchase, the Annual stayed (ASSUMPTIONS #19 verified). Still untested: automatic refunds against Razorpay (#21, #22), which need a real duplicate or Lifetime-conflict payment.
- README restructure like Medical-ChatBot's (short front page with System Design and Solution Architecture diagrams, details in `docs/guides/`): in a separate PR.
- DMARC to `p=quarantine` after about a week of clean reports (around 2026-11-05).
- BSE data source (maintainer); known input-mapping defects to the council.

**Broken or risky**
- Automatic refunds are TEST-only by code; live payments need a reviewed change to enable them.
- Reconciliation is best effort over Razorpay's list APIs; completeness beyond the 30-minute overlap and the one-day audit is unverified.
- Uptime detection of a stopped reconciler is nominal (60-90 min); GitHub can delay scheduled runs.

## Session: 2026-10-29, evening (model: Claude Opus 5.5, `claude-opus-5-5`): LLM live, pull-only deploys, refund fix, maintenance and 404 pages, restore drill

**Done** (production runs **v0.12.0** on the Oracle VM, deployed from the published GHCR images)
- LLM narration live (#181, D-022): `ollama` service signed in to the maintainer's ollama.com account, `gpt-oss:120b-cloud`, temperature 0 and high reasoning effort at the maintainer's request (#190, measured 1.1 to 1.9 s per explanation). Rule-based text stays the fallback; the verdict still comes only from `RatioEngine`.
- Pull-only deploys (#180) are the production path: `scripts/deploy.sh vX.Y.Z` with `IMAGE_REPOSITORY=ghcr.io/hamza-aziz-ai`. #186 strips carriage returns from `.env` values (a CRLF `.env` broke the first pull). #185: CI on `main` is never cancelled (a cancelled release-commit run blocked the v0.10.0 image publish, so v0.10.0 was never deployed).
- Billing: #188 fixed refunds never revoking the plan (the revocation reused the purchase's payment id and hit the `(provider, event_id)` unique index). The Razorpay webhook did not exist at all; the maintainer created it. Razorpay later rejected our key (`.env.production` held the sample key from a pasted prompt); a regenerated test key was pushed and verified from the container.
- Maintenance and 404 pages (#191): the front Caddy answers restarts with `caddy/maintenance.html` (503) and a JSON 503 under `/api/*`; upstream failures in the API answer 503, never 502, because Cloudflare replaces an origin 502 with its own page; the UI never shows a raw response body; unknown paths get a HalalLens 404. The same approach was shared with Medical-ChatBot, which added a free-plan Cloudflare Worker for the case where Caddy, the tunnel or the VM is down.
- Backup restore drill: newest R2 dump restored into a throwaway Postgres 14, all 20 tables matched live. It found that the documented restore (Postgres 14's `pg_restore`) cannot read the dumps (written by `pg_dump` 17); README_ops now restores with the API image's `pg_restore`, and the "back up now" command was fixed.

**In progress / next**
- End-to-end refund test in Razorpay Test Mode: buy Starter, check the `payment.captured` webhook, refund, check `refund.processed` (keyed `rfnd_...`) and the plan back to free.
- Cloudflare Worker maintenance page for Caddy, tunnel or VM outages (maintainer approved; needs a Cloudflare token or the dashboard).
- Known input-mapping defects (`liquid_assets` from "current assets", `non_halal_income` from "Other, Net", the income regex) go to the council before any change; BSE data source is still the maintainer's decision.

**Broken or risky**
- Dump and server versions differ (`pg_dump` 17, server 14). Restores work with the API image's `pg_restore`; upgrading Postgres to 17 would remove the skew.
- LLM narration depends on the maintainer's ollama.com device sign-in (`8e69076a6c04`); removing it there or deleting the `ollama_data` volume silently falls back to rule-based text.

## Session: 2026-10-29, afternoon (model: Claude Opus 5.5, `claude-opus-5-5`): email, auth hardening, watchlists in Postgres, Next 16, payments

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
