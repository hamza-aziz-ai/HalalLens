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

