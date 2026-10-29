# DECISIONS

One entry per decision, newest last. Model for every entry below: Claude Sonnet 5.5 (`claude-sonnet-5-5`), 2026-10-27, with Codex (ChatGPT) as the second opinion where noted. Rejected options live in [ALTERNATIVES.md](ALTERNATIVES.md).

## D-001: The engine owns a three-state verdict
- **Date:** 2026-10-27   Model: Claude Sonnet 5.5 + Codex review
- **Context:** The engine returned a boolean and skipped missing ratios, so one computed passing ratio gave `is_compliant=True`. Five copies of "derive the verdict from the boolean" existed (API, two ingest jobs, backfill, precompute).
- **Options:**
  1. keep the boolean, patch each copy
  2. add a fourth "borderline" state
  3. engine returns `compliant` / `non-compliant` / `insufficient-data`, consumers read it.
- **Chosen:** 3.
- **Why:** The DB already stores those strings; fixing it once removes the copies. Unknown is not a failure, so `is_compliant` is nullable.
- **Trade-off:** Nullable `is_compliant` breaks Boolean-only clients; UI and API had to change together.
- **Revisit if:** a scholar wants a "needs scholarly review" band beyond data quality.

## D-002: All five ratios and all three income parts are required
- **Context:** Which inputs may be missing before a filing can be called compliant?
- **Options:**
  1. three canonical ratios required
  2. all five required
  3. any one computed ratio.
- **Chosen:** 2, with prohibited income needing base + interest + dividend known (explicit zero counts).
- **Why:** Never a false pass; narrowing the set is a methodology decision, not a bug fix. SS21 backs 30/30/5 but not the 67%/49% gates.
- **Trade-off:** Many filings become `insufficient-data` until extraction improves. Unmeasured.
- **Revisit if:** the dry run shows the product unusable *and* a scholar approves a narrower set (one constant, `REQUIRED_RATIOS`).

## D-003: Exact decisions with Decimal in an explicit context
- **Context:** Floats put `(0.1+0.2)/6` above an exact 5%; Decimal's default 28 digits rounded away a `1e-30` income.
- **Chosen:** `numerator <= threshold * denominator` in a module-level 1500-digit context (no division, no ambient context); inputs bounded to finite values within float range; thresholds validated.
- **Why:** Boundary cases are the ones users care about. 1500 digits holds any sum in the supported domain exactly.
- **Trade-off:** Adapters still reduce values to float; integer exactness is engine-local only.
- **Revisit if:** inputs ever arrive as arbitrary-precision decimals.

## D-004: LLM narration bypassed on screening paths  (SUPERSEDED by D-010)
- **Date:** 2026-10-27   Model: Claude Sonnet 5.5 + Codex review
- **Context:** A model can echo the right status while its prose says the opposite; no keyword filter closes that (Codex produced counterexamples).
- **Chosen (then):** `NarrationEngine` always returned the rule-based narration; LLM code kept.
- **Why superseded:** the bypass removed an advertised feature without the maintainer deciding it. See D-010.

## D-005: One shared `coerce_amount` for untrusted numbers
- **Chosen:** `ratio_engine/amounts.py`; bool, NaN/inf and under-flowing strings become unknown, exact zeros stay zero. API, jobs, ETL, vendor mapper and cache runner delegate to it.
- **Why:** Repo rule: fix once in the shared function. A boolean became a verified zero income in four places.
- **Trade-off:** Behavior changes for malformed inputs (now unknown). Numeric JSON literals already decoded to 0.0 are outside the guarantee.

## D-006: `main` is protected by a ruleset; auto-merge is narrow  (still in force; D-015 will widen it once its conditions are met)
- **Chosen:** PR + `backend`/`ui`/`secrets` required, squash only, owner bypass. Auto-merge only for Dependabot minor/patch of GitHub Actions and UI dev deps.
- **Why:** Python packages touch ETL scaling and verdict logic; tests do not yet prove dependency bumps safe there.
- **Revisit if:** the verdict golden table and ETL fixtures cover those libraries.

## D-007: release-please with Conventional Commit PR titles
- **Chosen:** Release PR from squash-merge titles; `build:`/`ci:`/`docs:` do not release; no `!` / `BREAKING CHANGE` footers while below 1.0 (they would bump the major).
- **Trade-off:** Release PRs opened by the default token do not run CI (resolved by D-014).

## D-008: Pin the Python minor version only
- **Context:** `python_full_version = "3.14.6"` made `pipenv install --deploy` abort when `python:3.14-slim` moved to 3.14.10, breaking image builds.
- **Chosen:** `python_version = "3.14"`; hashes in `Pipfile.lock` still pin every dependency.

## D-009: Remove unused heavy dependencies
- **Chosen:** Dropped torch (CUDA index), langchain*, ollama, playwright, firecrawl-py, ghostscript, bs4 (nothing imports them); pytest/pandas-stubs moved to dev.
- **Why:** CI time, image size, attack surface. Camelot 2.0.0 needs only `pypdfium2`.

## D-010: Restore the optional LLM mode with a best-effort guard
- **Date:** 2026-10-27   Model: Claude Sonnet 5.5
- **Context:** The maintainer reviewed D-004 and chose to keep the LLM mode, accepting weaker consistency. Codex had said this is acceptable only under an explicit, weaker contract.
- **Options:**
  1. keep it bypassed
  2. restore with a guard, UI caveat and honest docs
  3. LLM only for non-decisive commentary.
- **Chosen:** 2 (maintainer's decision).
- **Why:** The mode is advertised and opt-in (`NARRATOR_MODE=llm`, default `rule_based`); the engine verdict and the badge stay authoritative.
- **How:** The model is asked only about `compliant` / `non-compliant`; it must repeat the verdict in `screen_verdict`; summary/verdict/bullets pass a keyword check; the label shown is the engine's; any doubt or error falls back to rule-based; `insufficient-data` never reaches the model; the UI shows an AI-generated caveat.
- **Trade-off:** Not a guarantee. A paraphrase the word lists miss can still contradict the verdict (a test documents that ceiling).
- **Revisit if:** a user is shown contradicting text, or a structured per-claim validation against the ratio facts is built (then the caveat can go).

## D-011: The Docker deployment is the canonical UI
- **Date:** 2026-10-28   Model: Claude Opus 5.5 (maintainer's decision)
- **Context:** Two ways serve the dashboard: the `ui` container behind Caddy, and GitHub Pages from `nextjs.yml`. The Pages build sets no API URL.
- **Options:**
  1. GitHub Pages
  2. Docker deployment
- **Chosen:** 2.
- **Why:** It is built with the real API URL and deploys together with the API, which the cutover in ROLLBACK.md needs.
- **Trade-off:** The Pages site stayed live but was not a working product.
- **Update 2026-10-28 (maintainer):** `nextjs.yml` removed and GitHub Pages turned off: the public build called a private LAN address and every API call failed. The UI's fallback API URL is now `http://localhost:8001` instead of that LAN address.
- **Revisit if:** a static demo with a public API becomes useful.

## D-012: No production data yet; recompute tooling first, dry run later
- **Date:** 2026-10-28   Model: Claude Opus 5.5 (maintainer's input)
- **Context:** The project is in its initial stage and has no production data, so a production dry run is not possible.
- **Chosen:** Build the recompute/dry-run tooling (PR-B) now; run the dry run when real data exists.
- **Why:** The tooling is still needed for any database that holds evaluations computed by the old engine, including development ones.

## D-013: Open-source showcase now, private and monetized later
- **Date:** 2026-10-28   Model: Claude Opus 5.5 (maintainer's decision)
- **Context:** The maintainer uses HalalLens as a public portfolio project but intends to privatize and monetize it later, with only minimal changes at that point.
- **Chosen:** Keep the public MIT repo, and keep it sale-ready (configuration in env, billing complete in test mode, docs current, no secrets or personal identifiers, Docker as the canonical deployment). Rules are in AGENTS.md, "Project stance".
- **Trade-off:** MIT cannot be revoked for versions already published; only future versions can be licensed differently. Outside contributions would complicate relicensing unless their copyright is settled first.
- **Revisit if:** the maintainer starts accepting outside contributions, or decides to privatize (then: make the repo private, choose a licence for new versions, rotate any credentials, review the git history for anything a buyer should not receive).

## D-014: Fully automatic releases with a repo-scoped token
- **Date:** 2026-10-28   Model: Claude Opus 5.5 (maintainer asked for fully automatic releases)
- **Context:** The release PR was opened with `GITHUB_TOKEN`, so CI never ran on it and the ruleset made every release need an owner-bypass merge (v0.1.1 was merged that way).
- **Options:**
  1. Keep a human merge for every release
  2. A fine-grained personal token (`RELEASE_PLEASE_TOKEN`) for release-please and for enabling auto-merge
  3. A GitHub App token
- **Chosen:** 2.
- **Why:** Simplest for a solo maintainer. A token-created PR triggers CI, and an auto-merge enabled with the same token makes its push trigger the release run (a `GITHUB_TOKEN` merge would not).
- **Trade-off:** The token is tied to the maintainer's account and expires (at most one year), so it must be renewed; merges show as the maintainer. Every `feat:`/`fix:` on `main` now releases without a human step. A release is only a tag and notes; deployment stays manual (ROLLBACK.md).
- **Revisit if:** the project gets a second maintainer or is sold (then a GitHub App, option 3), or releases need a human gate.

## D-015: Pull requests merge automatically once CI passes (HELD; scope revised)
- **Date:** 2026-10-28   Model: Claude Opus 5.5 (maintainer's decision: "fully automatic merge ... past, present, future")
- **Context:** Auto-merge covered only Dependabot minor/patch updates of GitHub Actions and UI dev dependencies (D-006); everything else waited for a human.
- **Options:**
  1. Keep the narrow scope
  2. Auto-merge every same-repo PR, gated only by the required checks
- **Chosen:** 2, for open PRs (including the Dependabot backlog) and all future ones. Fork PRs are excluded.
- **Why:** The maintainer wants the repository to run without manual merges.
- **Trade-off:** No human reads a diff before it reaches `main`. Major upgrades (Next, zod, eslint) and Python packages on the ETL/verdict paths merge if CI passes, and CI cannot catch everything. A merge is not a deployment: production changes still go through the cutover in ROLLBACK.md. Merges by Dependabot runs use `GITHUB_TOKEN` (Dependabot runs cannot read Actions secrets), so their push to `main` does not start other workflows unless `RELEASE_PLEASE_TOKEN` is also stored as a Dependabot secret.
- **Revisit if:** an auto-merged change breaks the app, or a second contributor joins.
- **Revised 2026-10-28 (maintainer, after a council with Codex):** activation is held until the test plan in docs/TESTING.md lands, because with CI as the only gate the tests must catch what a reviewer would. The scope is narrowed: sensitive paths (`.github/**`, `CODEOWNERS`, migrations, `schema.sql`, `api/app.py`, `api/security.py`, auth/billing modules, `ratio_engine/**`, tests and gate config) keep a deliberate owner merge, enforced by CODEOWNERS plus a code-owner-review ruleset and a `pull_request_target` policy job. The first `auto-merge.yml` ran on `pull_request` from the PR's own head and enabled auto-merge on the very PR that added it, so it was removed. Until then: Dependabot minor/patch for Actions and UI dev deps (D-006) and docs-only PRs (`docs-automerge.yml`) auto-merge.

## D-016: Filing PDFs in Cloudflare R2; MinIO leaves the production stack
- **Date:** 2026-10-28   Model: Claude Opus 5.5 (maintainer's choice)
- **Context:** `docker-compose-prod.yml` pinned `minio/minio:RELEASE.2023-03-20T20-16-18Z`, which can no longer be pulled from Docker Hub or Quay: MinIO stopped publishing free images and the community edition is source-only. The production stack could not start on a fresh host. The target host is a free Oracle Ampere VM, where RAM is limited.
- **Options:**
  1. Cloudflare R2 (S3-compatible, external)
  2. Another self-hosted S3 server (SeaweedFS, Garage)
  3. Build MinIO from source or use a third-party repackage
- **Chosen:** 1.
- **Why:** Free for 10 GB with free egress, uses none of the VM's RAM or disk, and the existing MinIO Python SDK talks to any S3 endpoint, so the code change is configuration (HTTPS, region, bucket) and one shared client factory.
- **Trade-off:** PDFs live with a third party (they are public BSE documents). A bucket-scoped R2 token cannot list or create buckets, so the maintainer creates the bucket and preflight checks only that bucket. Local development keeps a MinIO it already runs.
- **Revisit if:** storage exceeds the free tier, or the product must keep all data on one host.

## D-017: Cloudflare Tunnel as an alternative way in (production on `halallens.in`)
- **Date:** 2026-10-28   Model: Claude Opus 5.5 (maintainer's choice of host and domain)
- **Context:** The first host is a free Oracle Cloud Ampere VM; `halallens.in` (BigRock) moved its DNS to Cloudflare. Medical-ChatBot already runs behind a Cloudflare Tunnel with no open web ports.
- **Options:**
  1. Caddy with Let's Encrypt on ports 80/443 (the existing setup)
  2. Cloudflare Tunnel in front of Caddy
- **Chosen:** both, selected by `CADDY_MODE` (`tls` default, `tunnel`); production uses the tunnel.
- **Why:** The tunnel needs no open web ports or certificates on the VM, and the same compose file still runs on any host with TLS mode, which a buyer may prefer.
- **Trade-off:** In tunnel mode the API trusts `Cf-Connecting-Ip` for client identity, so Caddy must be reachable only through the tunnel (`CADDY_BIND=127.0.0.1`, firewall closed to 80/443); if it were exposed, a client could pick its own rate-limit bucket. Traffic and TLS terminate at Cloudflare.
- **Revisit if:** the host moves off Cloudflare DNS, or the product needs end-to-end TLS it controls.

## D-018: Publish images to GHCR and Docker Hub, gated on CI
- **Date:** 2026-10-28   Model: Claude Opus 5.5 (maintainer's choice: publish soon, to both registries; design agreed with Codex)
- **Context:** CI built and smoke-tested the images on every PR but published nothing; deployment built images on the server. The maintainer wanted public images, visible on Docker Hub and in the repository's Packages panel.
- **Options:**
  1. Keep building on each server
  2. GHCR only
  3. Docker Hub only
  4. Both
- **Chosen:** 4, after the Node 24 and non-root Python image hardening, before the remaining hardening (digest-pinned bases, static non-root UI).
- **Why:** GHCR needs no extra credentials and shows next to the code; Docker Hub is where people look for images. Publishing from CI means every server runs the exact image CI tested.
- **Trade-off:** Public version tags are permanent, so a later hardening fix ships as a new version, never by rewriting an old tag. The UI image still runs as root until the static UI step. Per-architecture tags (`vX.Y.Z-amd64`, `-arm64`) are visible next to the joined tag.
- **Revisit if:** the project goes private (make the packages and Docker Hub repositories private or move to a private registry), or a buyer wants another registry.

## D-019: Watchlists in PostgreSQL with conditional updates

- **Date:** 2026-10-29   Model: Claude Opus 5.5 (maintainer approved the migration; design agreed with Codex in council)
- **Context:** Watchlists were a JSON file rewritten whole without a lock, so two workers or overlapping requests could duplicate an alert or undo another user's change; the API had to run one worker.
- **Options:**
  1. Keep the file and add a file lock
  2. Postgres with read-compare-update in the application
  3. Postgres with conditional `UPDATE`s that decide baseline vs flip in the database
- **Chosen:** 3. Table `watchlist_entries` (FK to `users`, cascade), insert-if-absent, then for a conclusive verdict first `UPDATE ... WHERE last_is_compliant IS NULL` (baseline), and only if that matched nothing `UPDATE ... WHERE last_is_compliant <> verdict` (flip), committed before an alert is returned. The JSON storage was removed.
- **Why:** PostgreSQL re-checks an UPDATE's WHERE on the newest row version after waiting for the row lock, so concurrent identical verdicts produce one flip. Seeding first matters: flip-first can lose a concurrent opposite verdict (Codex found this in review; the opt-in test fails 20/20 with flip-first and passes with seed-first).
- **Trade-off:** Re-adding a symbol now keeps its baseline (it used to reset it). A delayed, stale verdict can still move a baseline backwards (needs verdict versioning). Email stays best-effort after the commit. One API worker remains the default because the rate limiter is per-process.
- **Revisit if:** alerts move to a scheduled job, or verdicts get versions.

## D-020: Email-first accounts, proven-mailbox admin, no Google linking by email

- **Date:** 2026-10-29   Model: Claude Opus 5.5 (maintainer approved; design agreed with Codex in council)
- **Context:** Sign-up never proved the email, yet an `ADMIN_EMAILS` address became admin at sign-up, login, `/auth/me` and two access checks; Google sign-in attached to any account with the same email and accepted a missing `email_verified`. Anyone could pre-register an address (even an admin's) and keep a known password after the owner later signed in with Google.
- **Options:**
  1. Verify after sign-up, keep the password chosen at sign-up
  2. Email-first: the password is chosen on the emailed link
  3. Keep auto-linking Google for verified accounts
  4. Link Google only explicitly from a signed-in account
- **Chosen:** 2 and 4. `email_verified_at` on users, `auth_tokens` (SHA-256 digest, purpose, single use, 1 h sign-up / 30 min reset). Sessions require a verified email; admin is granted from `ADMIN_EMAILS` only when the mailbox is proven. Reset replaces the password, verifies the email, revokes all sessions and other proofs in one transaction; login holds the same row lock from password check to session insert. The migration revokes every unproven admin and session.
- **Why:** With option 1, a victim clicking a verification mail would verify an attacker's password (Codex). Implicit linking by email lets a squatter's account absorb the owner's Google identity. Mocks cannot prove the lock, so a real-Postgres test does (it fails without `FOR UPDATE`).
- **Trade-off:** Password sign-up now needs working email. Existing users must re-prove their mailbox once. Google users with an email already used by a password account are refused until explicit linking (PR 3) exists. Generic responses mean a mistyped address gets no feedback.
- **Revisit if:** a second sign-in provider is added, or email delivery becomes unreliable.

## D-021: Browser-bound Google OAuth flows and explicit account linking

- **Date:** 2026-10-29   Model: Claude Opus 5.5 (maintainer approved; design agreed with Codex in council)
- **Context:** The OAuth `state` was HMAC-signed and reusable for 10 minutes, not tied to the browser, so an attacker could complete their own Google sign-in in a victim's browser (login CSRF). D-020 stopped linking Google by email, so a user whose Google email differs needed an explicit, safe way to link.
- **Options:**
  1. Keep the signed state, add a nonce cache
  2. Store each flow in Postgres, bind it to the browser with a short-lived cookie
  3. Link Google from the callback using the state alone
  4. Callback only proves the Google identity; the signed-in session confirms the link
- **Chosen:** 2 and 4. `oauth_flows` stores digests of the state and of a random `hl_oauth` cookie (HttpOnly, SameSite=Lax, Secure on https, path `/api/auth/google`, 10 minutes); the callback needs both, once. Linking: `POST /auth/google/link/start` (session + password again) records the user and session; the callback stores the Google identity and a one-time code in the account page's fragment; `POST /auth/google/link/confirm` links only for that same user and still-valid session. `OAUTH_STATE_SECRET` is no longer used. The Google request no longer asks for offline access.
- **Why:** A flow started in one browser cannot be finished in another, and a victim who completes an attacker's link flow cannot attach their Google identity to the attacker's account (no cookie, and the confirm needs the attacker's session in the victim's browser).
- **Trade-off:** Needs the UI and API on one origin (production `/api`); a split-origin dev setup can sign in with Google but not link. A Google account links to one HalalLens account; no merges. Flows live in the database (cleaned after a day).
- **Revisit if:** the mobile app ships (its OAuth would use PKCE with an app-bound redirect), or the API moves to its own origin.

## D-022: LLM narration through a signed-in Ollama daemon (gpt-oss:120b-cloud)

- **Date:** 2026-10-29   Model: Claude Opus 5.5 (maintainer's choices: model `gpt-oss:120b-cloud` via Ollama, daemon on the VM, public data may go to the cloud model, rule-based fallback; setup advice from the Medical-ChatBot project)
- **Context:** The narrator could already call an OpenAI-compatible endpoint behind a verdict guard, but nothing was deployed. The maintainer wants LLM explanations (and later line-item mapping suggestions) with `gpt-oss:120b-cloud`.
- **Options:**
  1. Call ollama.com directly with an API key
  2. Run an Ollama daemon on the VM, signed in to the maintainer's account
  3. Self-host a small model on the VM
- **Chosen:** 2. An optional `ollama` compose service (profile `llm`, internal only, 256 MB, sign-in persisted in a volume); the narrator calls Ollama's native `/api/chat` with `think: high` and temperature 0 (financial text; high measured 1–2 s, changed 2026-10-29 at the maintainer's request), `num_predict` ≥ 4096, reads only `message.content`, rejects empty or oversized replies, and never relies on schema output (the existing parser and verdict guard validate). A process-wide guard allows 6 calls a minute and opens a 60-second circuit after 3 failures in a row.
- **Why:** Option 1 returns HTTP 402 without paid credits (Medical-ChatBot's finding); option 3 is too weak and slow on 2 OCPUs. The daemon route is free and keeps the API unchanged apart from the native call.
- **Trade-off:** The free allowance's limits are unpublished; a signed-in device on the VM can spend it; sign-in is a manual browser step after a volume loss. Narration latency is seconds, so `NARRATION_TIMEOUT_SECONDS` must be measured and raised from 8.
- **Revisit if:** usage outgrows the free allowance (paid credits or another provider), or more API workers need a shared rate limit.

## D-023: LLM line-item mapping as per-filing suggestions (agreed design, not built yet)

- **Date:** 2026-10-29   Model: Claude Opus 5.5 (maintainer: "LLM suggests, an admin confirms"; design agreed with Codex in council)
- **Context:** The ETL maps filing data straight into fixed snapshot columns through substring aliases (XBRL/JSON) and keyword matches (PDF rows); raw facts are not stored, the XBRL parser ignores contexts and units, and the PDF parser keeps the rightmost number. Known wrong mappings (liquid assets from "current assets") come from these heuristics. The maintainer wants the model to help map messy line items.
- **Options:**
  1. Approve reusable alias rules (label to metric) suggested by the model
  2. Approve a specific captured fact for a metric in one filing revision, then rebuild inputs deterministically
  3. Let the model fill values directly
- **Chosen:** 2, in three PRs after D-022 merges: (a) capture every XBRL fact with full context (qualified tag, period, entity, dimensions, unit, precision, raw text, document hash, extractor version), including facts current rules already match, and show the evidence to admins; (b) admin-triggered suggestions through the guarded Ollama client in the API process: labels with section context, category definitions with exclusions, null abstention, no amounts, no confidence, strict rejection of anything malformed; (c) per-filing confirmation, then selections to a candidate snapshot, a RatioEngine preview of before and after inputs and verdict, and a reviewed apply that rejects stale previews, writes consistently and keeps rollback evidence. An explicit selection supersedes heuristics; an existing governance override stays final (proposal). Deferred: PDF, reusable aliases, composition rules, an upload pipeline.
- **Why:** A label means different things across periods, statement bases and sections, so a reusable rule applied deterministically can still be wrong everywhere (Codex). Capturing final values would freeze today's parser losses. Existing recompute only re-reads stored inputs, so applying selections needs its own path. Option 3 would put model output into verdict inputs.
- **Trade-off:** More review work per filing; no production filings to use until a data source is chosen; the model's usefulness is unproven until representative filings are tested; filing text goes to the cloud model (public or synthetic documents only).
- **Revisit if:** confirmed selections show stable patterns worth promoting to scoped aliases, or PDF filings dominate the data source.

## D-024: Paid access from a ledger of grants; purchases queue, nothing paid is discarded

- **Date:** 2026-10-29   Model: Claude Opus 5.5 (maintainer's rules: a lower tier is a "Switch", Lifetime disables the timed plans, switching keeps the current period until it ends; design agreed with Codex in council, 3 rounds)
- **Context:** Plans are one-time Razorpay Orders (no auto-debit). Every purchase overwrote `renewal = now + interval`: an Annual holder buying Starter lost about 11 months, an early renewal lost the remaining days, a Lifetime holder buying Starter dropped to 30 days, any refund dropped the whole account to free, and the order claim committed before the grant (a crash left a paid order without access).
- **Options:**
  1. `next_plan` / `next_period_end` columns on `users` (one queued period)
  2. Stored period boundaries per purchase, rewritten on refunds
  3. A ledger of grants (one per paid order, trial or pre-ledger period) with access derived by a fold
  4. Razorpay Subscriptions (auto-debit) now
- **Chosen:** 3. `subscription_grants` holds plan, duration (NULL = Lifetime), allocation time and refund state; `api/billing.py` lays grants end to end in allocation order (`start = max(allocated_at, previous end)`; a refunded grant ends at `max(start, min(natural end, revoked_at))`). Settlement, refunds, trials and projection refreshes each run in one transaction under a per-user row lock with the database clock; `users.plan`/`subscription_status`/`subscription_renewal` (now TIMESTAMPTZ) are a projection written only there. Orders keep immutable terms (plan, interval, payment id). Verify fetches the payment and grants only a captured payment matching the order's amount and currency; the webhook checks the same. Lifetime (active or scheduled) blocks purchases at order creation and, under the lock, turns a late capture into a `refund_due` order. Partial refunds accumulate; a grant is revoked when refunds reach the order amount. Labels come from `subscription_plans.rank`: Upgrade, Switch, Extend. A legacy grant preserves each existing period's exact end.
- **Why:** A single renewal date cannot express "Annual until X, then Starter until Y" (1 is a one-slot queue that blocks concurrent checkouts). Deriving boundaries (3) needs no rewrite on refunds and no promotion job; Codex's counterexamples (refund after a queued purchase; refund of a queued purchase) fixed the fold to keep revoked grants with a clamped end. Auto-debit (4) adds mandates, failed-debit handling and cancellation, unrelated to keeping prepaid time.
- **Trade-off:** Every access check after a period ends takes the user lock once to rebuild the projection; refunds of orders with no grant (refund-due, or pre-ledger orders that could not be linked) need manual review; payments stay manual (no renewal reminders yet).
- **Revisit if:** auto-renewal is wanted (Razorpay Subscriptions: each charge becomes one grant), more API workers make the lock a bottleneck, or plans start to differ in features (labels and stacking then need per-feature rules).
- **Amendment (2026-10-30, Claude Opus 5.5, agreed with Codex in council, run to agreement): Lifetime takes effect when paid.** Production showed the queueing rule applied to Lifetime: a buyer with Annual until 2027-10-29 saw "Plan: Annual, then Lifetime for life from 10/29/2027" after paying for Lifetime. Now an unrevoked Lifetime grant is an overlay that starts at its settlement time (`allocated_at`) and is the current plan immediately; `api/billing.py` builds the timed chain from the other grants exactly as before (Annual, Starter, trial and legacy keep their D-024 dates on wall-clock time underneath: no pause, no extension) and adds each Lifetime as its own segment (`end` = NULL, or `max(allocated_at, revoked_at)` once refunded), with an explicit `lifetime` flag taken from the grant (a refunded Lifetime has a finite end, so "end is None" cannot identify it). The current segment prefers a covering Lifetime; `/billing/entitlement` then lists only the Lifetime. Refunding the Lifetime reveals whatever timed access remains (with its original end), or leaves the account free when none does. `lifetime_held`, `refund_due`, settlement and the refund SQL are unchanged; no schema change. Alternatives: keep queueing (the buyer pays for something that starts in a year), or pause/extend the timed grant under Lifetime (more code, and a refund would hand back time the buyer already used under Lifetime). Trade-off: timed time under a Lifetime runs out unseen; it only matters if the Lifetime is refunded. Existing projections are repaired once after deploy (README_ops, "Lifetime takes effect when paid").

## D-025: Refunds are scoped to the payment they refund; reconciliation and automatic refunds follow

- **Date:** 2026-10-29   Model: Claude Opus 5.5 (maintainer: "go reconciliation"; design agreed with Codex in council, 3 rounds)
- **Context:** Payments complete at Razorpay even when our server is down; a missed result relied on the browser call or webhook retries, which Razorpay stops after 24 hours and then disables the webhook. Two refund cases were manual (`refund_due`, amount mismatch). Reading the refund path showed three defects: a refund matched the order, not the payment, so refunding a second payment on a paid order would revoke the plan the first payment bought; refund totals mixed per-refund amounts with Razorpay's cumulative snapshot and could double-count; any refund before settlement marked the whole order refunded.
- **Options:** keep matching by order and patch the cases; scope every refund to its payment and record each refund once.
- **Chosen:** `payment_refunds` stores one row per processed refund id with its payment; totals are summed from it. A refund changes access only when its payment is the order's funding payment (`razorpay_orders.payment_id`) and processed refunds reach the order amount; a refund of another attempt is recorded and changes nothing; a payment refunded before settlement can never fund the order (another attempt still can); a pre-ledger grant with no recorded funding payment goes to manual review. Agreed next steps (separate PRs): a reconciler that sweeps Razorpay payments and refunds from a persisted checkpoint (from the first order, no age cutoff) and follows every nonterminal payment and refund by id; automatic refunds of proven duplicates and `refund_due` payments through intents persisted before the POST with `X-Refund-Idempotency`, TEST keys only; amount mismatches stay manual; a heartbeat checked by the uptime workflow.
- **Why:** Razorpay allows several payment attempts per order, so the payment, not the order, is what a refund refunds. Summing distinct refunds is exact; a snapshot plus deltas is not (Codex's counterexample).
- **Built (PR B, plan agreed with Codex with no round limit):** `jobs/reconcile_payments.py` in the `billing-reconcile` service; refunds then payments swept per stream from a checkpoint (bootstrap: first order, at most 7 days per run, 30-minute overlap, 10-minute lag), one older day re-swept per run, `billing_tracked` items followed up by id; settlement outcomes classified from the state the lock saw; pre-ledger purchases bound atomically with their recorded refunds; advisory lock on a dedicated connection; Razorpay access shared through `api/razorpay_client.py`. PR C (agreed with Codex, run to agreement): `refund_actions` (one immutable request per payment, persisted before the POST, monotonic states), automatic full refunds of proven duplicates and `refund_due` payments with `rzp_test_` keys only, recovery by our key in the refund's notes before any re-send, 409 in progress retried / parameter mismatch blocked, other refusals blocked for a human, completion from recorded refunds (`sync_refund_action`) that separates the request's outcome from the payment's refund obligation, `/health/billing` heartbeat checked by the uptime workflow with `BILLING_EXPECTED`.
- **Trade-off:** refunds of migrated (pre-ledger) purchases need a human; one more table.
- **Revisit if:** live payments start (automatic refunds need their own reviewed switch), or refund volume makes manual review heavy.

## D-026: A short README with two diagrams; detail moves to docs/guides/

- **Date:** 2026-10-29   Model: Claude Opus 5.5 (maintainer: match the sister project Medical-ChatBot's README layout)
- **Context:** The README had grown to about 230 lines mixing the pitch, setup, the route-tier table, Docker, CI and a long limitations list, with badges and one plain module diagram. A buyer or reviewer could not see in one screen what happens to a request or how code reaches the live site, and every new feature added another section.
- **Options:**
  1. Keep one long README and add the two diagrams to it
  2. A short README (status, intro, System Design and Solution Architecture diagrams with numbered notes, quick start, documentation table, three known limitations) with the rest moved verbatim into `docs/guides/`
  3. A generated documentation site (MkDocs or similar)
- **Chosen:** 2. Guides: `SCREENING.md` (what exists, the method, the full limitations list), `SETUP.md`, `API.md`, `DOCKER.md`, `CI-CD.md`, `STRUCTURE.md`; each opens with its purpose and a link back to the README. No badges or screenshots; hand-written Mermaid with markdown-string labels, `classDef` colours and a key under each diagram. The README and the affected guide change in the same PR as the behaviour they describe.
- **Why:** Same shape as Medical-ChatBot, so both projects read the same way; the two diagrams answer the whiteboard questions (how a verdict is made, how a release reaches production) without notes; a moved section keeps its exact text, so nothing is lost.
- **Trade-off:** Readers follow one more link for setup and API detail; inbound links and the route-tier test message now point at `docs/guides/API.md`; the README notes and the guides can drift if the same-PR rule is skipped. Lines that were already stale when moved still need their own fix.
- **Revisit if:** the guides outgrow plain Markdown (search, versioned docs), or the project goes private and needs a separate public landing page.

## D-027: One publication path: open quality issues mask the engine's verdict for every writer

- **Date:** 2026-10-29   Model: Claude Opus 5.5 (design agreed with Codex in council)
- **Context:** The `needs-review` overlay lived only in `api/app.py::_ensure_filing_evaluation`. The four jobs (`precompute_evaluations`, `ingest_bse`, `ingest_indianapi`, `backfill_evaluations`) and the Indian-history path stored the engine's pair without it, so a filing with an open quality issue could carry a conclusive stored verdict. Stored ratios and the recent and history caches were returned without checking issues, an issue-read failure became "no issues", the jobs' market-failure clearing resolved every issue type (governance and anomaly included) whenever a process-local counter remembered a failure, and a blocker recorded while an evaluation was being written could be lost to the race.
- **Options:**
  1. Keep the overlay in the API and mask on every read only
  2. Copy the overlay into each job
  3. One pure policy (`evaluation/quality.py`) and one database publication method that reconciles the detector's row, reads every open issue and upserts the evaluation in one transaction under a per-filing advisory lock that every issue writer also takes; stored and cached results are masked with the same policy on the way out
  4. A schema change (a `blocked` column or a trigger)
- **Chosen:** 3. `BSEDatabaseManager.publish_filing_evaluation` (`pg_advisory_xact_lock` on the canonical symbol and filing instant, in its own two-key namespace) is the only writer of `filing_evaluations`; `upsert_filing_evaluation` is gone. Any unresolved issue, of any type, publishes `needs-review` with `is_compliant = null`; recording an issue downgrades an existing result in the same transaction (keeping `evaluated_at`); resolving an issue never restores a verdict, a later evaluation or `jobs.backfill_evaluations --recompute --write` does. A market lookup resolves only the issue types it disproves (`quality.PRIMARY_LOOKUP_DISPROVES`, `quality.FALLBACK_LOOKUP_DISPROVES`); a stored cap disproves nothing. Issue-read and publication failures are 503. Recompute simulates publication in its dry run and rejects a stale preview on `--write`. RatioEngine remains the sole financial verdict owner: the policy only masks.
- **Why:** "A filing with an open issue is never published as compliant or non-compliant" now holds for every writer and every read, with a test per writer; the lock closes the record-versus-publish race (`tests/test_quality_postgres.py` fails with the lock removed). An advisory lock needs no migration; option 1 leaves conclusive rows for alerts and later readers, option 2 drifts, option 4 adds schema for what a lock already gives.
- **Trade-off:** Jobs now store `needs-review` for filings with open market or governance issues where they used to store a conclusive pair, so more filings show `needs-review` until an operator resolves the issue and the filing is re-evaluated; every filing response does one issue read per row, also on a cache hit; a recompute row can be skipped as stale and needs another run; the input re-read before a recompute write is not under the lock (a millisecond window, marked in code).
- **Revisit if:** `/filings/recent` load makes the per-row issue reads matter (batch them), an issue type should be advisory rather than blocking (an explicit allowlist decision), or `needs-review` from market issues hides too many results.

## D-028: Input mappings abstain instead of guessing (removal first)

- **Date:** 2026-10-29   Model: Claude Opus 5.5 (design agreed with Codex in council, run to agreement)
- **Context:** The mappers filled engine inputs with figures that are not those inputs. `liquid_assets` came from "current assets", "net current assets" or "cash and bank balances" in the ETL, and the vendor derived it as cash + receivables + short-term investments with missing parts as 0. The prohibited-income base (`non_halal_income`) came from a PDF regex that also matched "interest income" and from the vendor's "Other, Net". `interest_income` accepted the vendor's net non-operating interest and any tag containing "finance income" or "interest income" (net figures included). XBRL took the first matching fact whatever its context; the PDF parser took a row's rightmost number; vendor keys repeated across statements kept the last value. The engine adds base + positive interest + positive dividend, so a base that already holds interest double counts it.
- **Options:**
  1. Removal first: drop every mapping that cannot be shown to mean the input; a field we cannot establish is missing
  2. Replace the stand-ins with a composition formula (for example liquid assets = cash + current investments + receivables)
  3. Keep the mappings and flag the affected verdicts for review
- **Chosen:** 1. `liquid_assets` only from an explicit "liquid assets" aggregate (structured `liquidassets`, PDF "liquid assets", vendor `liquidassets`; "net", "illiquid" and "non-liquid" assets abstain). Interest income gross only: labels containing "net", "expens", "includ", "accrued" or "receivable" abstain, `financeincome` and the vendor's `interestincexpnetnonoptotal` are gone. Dividend income never from labels containing "paid", "payable", "propos", "declar", "includ" or "receivable". For interest, dividend and liquid assets, a second different value (another XBRL context, JSON node, PDF table or vendor statement) or a PDF row with more than one distinct number removes the field; the same value repeated is kept, an explicit 0 survives, a missing value is never 0, and a row matching an excluded label never falls through to another field. Vendor keys repeated with different values map to None. PDF metric cache version v4 to v5.
- **Label decision (prohibited-income base):** no label is kept. "Non-permissible", "impermissible", "haram" and "prohibited" income are the names AAOIFI SS21 and Shariah disclosures use for the whole prohibited figure, which normally includes interest income; none of them shows that the figure excludes interest and dividends, so adding interest and dividends on top of it would double count. A "total non-permissible income" label is inclusive by name. The base therefore has no extractor or vendor alias and is missing unless a governance override supplies it (`_extract_non_halal_from_text` is deleted); `governance_notes` text is still captured.
- **Why:** An input we cannot establish is missing, never guessed (D-002): a guessed figure can produce a false pass or a false fail, while a missing one gives `insufficient-data` and a failing ratio stays conclusive. A composition formula (2) is a methodology choice that belongs to D-023's reviewed per-filing mapping, not a bug fix; flagging (3) still publishes numbers we know are wrong. The methodology itself (which figures make up liquid assets and the prohibited-income base) is not verified by a Shariah scholar.
- **Trade-off:** Many more filings screen `insufficient-data` (no automated filing can reach `compliant` without an override for the base); a text-only interest disclosure is no longer mapped; XBRL with several periods loses interest, dividend and liquid assets. Context, period and unit selection is still not validated, so a single wrong-period figure can still pass, and the extractor as a whole is not validated. Stored snapshots, `metrics/v4/` cache objects and governance overrides written before this change keep the old values until the reviewed repair in README_ops ("Stored data repair").
- **Revisit if:** D-023's fact capture lands (contexts and periods make the conflict rule selective instead of abstaining), a scholar approves a liquid-assets composition or a residual base definition, or real filings show an explicit "excluding interest and dividend" label worth accepting.

## D-029: Postgres 14 -> 17 by dump and restore into a new volume

- **Date:** 2026-10-29   Model: Claude Opus 5.5 (plan reviewed by the 5-advisor council; Codex was at its usage limit)
- **Context:** Production ran `postgres:14` (14.24); 14 reaches end of life on 2026-11-12. The backups are written by the API image's `pg_dump` 17, which a 14 server's own tools cannot read, so the restore path already needed a workaround. The database is 21 MB, one role (`halallens`, the image's bootstrap superuser, owns everything), initdb-default settings, no init scripts.
- **Options:**
  1. `pg_dump` 14 data and `pg_restore` it into 17 on a new volume, keeping the old volume untouched
  2. `pg_upgrade` (copy or `--link`) between two data directories
  3. Bump the image in place on the same volume
  4. Logical replication from 14 to 17, then switch over
- **Chosen:** 1. `docker-compose-prod.yml` runs `postgres:17.11-trixie` on the new volume `postgres17_data`; `postgres_data` stays on disk, unreferenced, as the rollback. `scripts/run_migrations.sh` gains an opt-in `REQUIRE_EXISTING_DB=1` (set in production) that refuses to create the schema on an empty database, so a deploy that lands on an empty volume fails instead of starting an empty site. Runbook with checkpoints in README_ops ("Postgres major upgrade").
- **Why:** At 21 MB the dump and single-transaction restore take seconds, so downtime is minutes; the old volume is an instant, tested rollback (`scripts/deploy.sh <old tag>`); the dump also goes off-site first. `pg_upgrade` needs both major versions' binaries in one container (the official images ship one); 3 cannot work (17 refuses a 14 data directory); 4 is a lot of moving parts for 21 MB.
- **Trade-off:** Minutes of downtime (maintenance page, uptime alerts); a rollback after the cutover loses writes made on 17 unless they are dumped and restored into 14 by hand; the old volume and the off-site dump use disk until the 14-day retention ends.
- **Revisit if:** the database grows to where a dump and restore no longer fit a short window (then `pg_upgrade --link` or logical replication), or the next major upgrade is due (consider a reusable script and a CI upgrade drill then).

## D-030: Upgrade credit at checkout for Lifetime

- **Date:** 2026-10-30   Model: Claude Opus 5.5 (maintainer's decisions: a discount at checkout, no refund; proration = paid amount × unused time; a credited payment refunded later is an alert only; pre-ledger grants excluded; payable below ₹1 blocks checkout. Plan agreed with Codex in council, run to agreement)
- **Context:** Since the D-024 amendment Lifetime takes effect when paid and timed grants keep running underneath, so a buyer with months of Annual left paid the full ₹2000 for Lifetime and the unused Annual time was worth nothing to them.
- **Options:**
  1. Refund the unused part of the timed grants when Lifetime is bought
  2. Discount Lifetime at checkout by the unused paid time (credit), priced on the server and fixed in the order
  3. A flat discount for anyone holding a paid plan
  4. Leave the price alone
- **Chosen:** 2. `api/billing.py` computes the credit as a pure function of the grants, the funding facts of their orders and `now` (integer paise, aware UTC, microsecond durations; prices are arguments). Eligible sources are unrevoked timed grants from `razorpay` orders that are `paid` by a known payment in INR with no refund pending (an open `billing_tracked` item naming the order or payment, or an unsettled `refund_actions` row); trial and legacy grants give nothing. Net paid = the order's charged amount minus processed refunds of that payment (`payment_refunds`); a running grant credits `floor(net_paid × remaining / duration)`, a queued one its full net paid, an expired one nothing; floored per source, summed, capped at the list price. `/billing/entitlement` previews it as `lifetime_quote` (`Cache-Control: no-store`). Checkout prices Lifetime on one locked read with the database clock, releases the lock, creates the Razorpay order for the charged amount outside any transaction, fails closed unless Razorpay echoes that amount in INR, and stores the terms on `razorpay_orders` (`list_amount`, `credit_amount`, `priced_at`, `price_valid_until` = priced + 15 minutes, `credit_version` = 1, `credit_detail` with per-source evidence; `amount = list_amount - credit_amount` by CHECK). Payable below 100 paise answers 409 (contact support) and opens no order. Settlement (verify, webhook and reconciler share `settle_razorpay_order` under the user lock) re-checks only credited orders: every source that took credit must be unchanged (grant unrevoked, same funding payment, same net paid, no refund pending), and the payment attempt's Razorpay `created_at` (the payment entity's, never the webhook envelope's) must be at or before `price_valid_until` (inclusive, whole seconds). Any failure makes the order `refund_due` with `refund_due_reason` (`price_expired`, `credit_changed`; `lifetime_held` for the existing rule) and the charged amount is refunded by the existing machinery. A credited order whose attempt time is unknown is never priced by processing time: verify fetches the payment, the webhook fetches it when its entity lacks one, and otherwise the order stays claimable ("retry") and the reconciler tracks the payment as pending and settles it from the fetched payment. A refund later recorded for a payment that funded a settled credited order's credit opens a `credit_conflict` item in `billing_tracked` (never re-checked or resolved automatically) and alerts the operator; access changes only by the existing rules. Orders without `credit_version` (ordinary and pre-migration ones) settle exactly as before.
- **Why:** A discount keeps the money where it is (no refund flows, nothing extra to reconcile), and pricing on the server with the terms stored on the order makes the price auditable and the settlement check deterministic. The quoted price is honoured for a payment attempt created within 15 minutes of pricing, including later authorisation or capture; this intentionally honours some late successful payments (a UPI or bank flow started in time) instead of refunding them. The attempt's creation time comes from Razorpay, so a buyer cannot stretch the window from the browser. Legacy grants are excluded until their funding payment is verified (D-025 binding), because their paid amount is not proven.
- **Trade-off:** Accepted exposure: a credited payment refunded after the upgrade settles leaves the buyer with both the credit and the refund until a human acts on the `credit_conflict` alert (maintainer decision: alert only, no suspension). Pending-refund detection is best effort from what this app recorded (a dashboard refund is seen once the reconciler or a webhook records it). The credit shrinks every second, so the checkout price usually differs from the preview by a few paise and the UI then asks for confirmation. The quote takes the per-user lock briefly on every Lifetime checkout.
- **Revisit if:** credit conflicts happen in practice (then claw back or suspend), credit is wanted for other upgrades (the calculator already takes any list price), pre-ledger grants get bound to their payments, or live keys start (the automatic refund of a credited `refund_due` order still needs its own reviewed switch).

## D-031: Compliance-flip emails go to the subscriber, from the scheduler, with the mailbox on the watch row

- **Date:** 2026-10-30   Model: Claude Opus 5.5 (plan agreed with Codex in council, run to agreement)
- **Context:** A compliance flip was emailed to one operator address (`ALERT_EMAIL_RECIPIENT`), and only when a subscriber happened to call `/alerts/check`; the subscriber who watched the symbol never heard of it, and the route did SMTP in a request. The product sells "watchlists with compliance-change alerts".
- **Options:**
  1. Mailbox on the watch row: `notified_is_compliant` next to `last_is_compliant` (pending while they differ), retry columns and the observed evaluation on the same row; a scheduler step observes and sends
  2. An outbox table, one row per alert to send
  3. Keep sending from `/alerts/check`, to the subscriber instead of the operator
- **Chosen:** 1. `alerts/storage.py::observe` is the one fail-closed lookup (moved out of `api/app.py`, no web framework imports), used by `/alerts/check` (observation only) and the scheduler: one transaction under the filing's D-027 lock reads the newest stored evaluation and its open issues; a first verdict is a silent seed, unknown verdicts move nothing, an older observation never overwrites a newer one. `alerts/delivery.py` runs after each precompute (independently of its success) under one session-level advisory lock: kill switch `ALERT_EMAILS_ENABLED` (default off: silent rebaseline), then for due pending rows (fair order, 5 per user, 50 per run) it re-checks the source, mails only verified, opted-in users with paid access now (`api.billing.project`, Lifetime overlay included; admins as in the API), and acknowledges by compare-and-set on `notified` (recording what was sent even if the verdict moved, so a correction stays pending). SMTP failures back off and stop after 5 attempts; an unknown source defers without counting. `users.alert_emails` is the opt-out (`GET/PUT /account/alert-emails`, authenticated so it works after access ends). `ALERT_EMAIL_RECIPIENT` and `alerts/notifier.py` are removed.
- **Why:** The watch row already exists per (user, symbol), so a pending alert cannot outlive or duplicate it and a verdict that flips back leaves nothing to send; two columns say what an outbox would. The scheduler sends regardless of who calls the route, outside any request, with retries and fairness. The D-027 lock means an observation never reads a half-published evaluation.
- **Trade-off:** At-least-once, not exactly-once: a crash after SMTP accepted a message resends it (same Message-ID). No history of sent alerts beyond the mail log. Pilot opt-out without one-click unsubscribe or `List-Unsubscribe` (needs a sign-in). Alerts lag the evaluation interval (15 min by default).
- **Revisit if:** volume or a provider's bulk-sender rules require one-click unsubscribe (RFC 8058); alerts need history, digests or other channels (then an outbox); several scheduler replicas run (the lock already serialises them, but throughput would need per-user batching).
