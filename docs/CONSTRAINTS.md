# CONSTRAINTS

Hard rules for people and AI sessions. If a task needs to break one, **stop and ask**.

## Never
- Derive a verdict anywhere except `RatioEngine._aggregate_verdict`. No `if is_compliant` truthiness on a nullable value.
- Write `filing_evaluations` any way except `BSEDatabaseManager.publish_filing_evaluation` (the D-027 overlay under the filing's lock), or record or resolve a quality issue without that lock.
- Fill an engine input the mappers cannot establish with a stand-in (D-028): a missing figure stays missing.
- Grant paid time or write `users.plan` / `subscription_status` / `subscription_renewal` outside the grant methods (D-024), or price a Lifetime upgrade anywhere but on the server (D-030).
- Treat `insufficient-data` / `null` as `non-compliant`, or an unknown amount as zero.
- Let LLM text replace the engine's label, or present it without the AI-generated caveat. LLM prose is best-effort; only the rule-based narrator is guaranteed consistent with the verdict.
- Commit or print secrets, keys, `.env`, or CSVs of keys. Never paste the Razorpay secret anywhere.
- Store or log raw session tokens (SHA-256 digests only; use `redact_token`).
- Force-push or rewrite history on `main` (owner bypass is for hotfixes only).
- Re-add the vendor API dump, the tracker spreadsheet, `cache/`, `downloads/`, `logs/` or key files.
- Disable or skip tests or security checks to make something pass.
- Claim multi-worker rate-limit correctness (the limiter is per process).

## Always
- Change ratio logic together with a row in the golden table (`tests/test_ratio_engine.py`).
- Schema change = a dated file in `database/migrations/` **and** an update to `database/schema.sql`.
- New env var = an entry in `.env.example`.
- Every route has a tier (public / authenticated / paid / admin) chosen deliberately.
- Keep the Python **minor** version in sync across `Pipfile`, `ci.yml` and the Dockerfiles; never add `python_full_version`.
- Show real command output, read the diff, one logical change per commit.

## Only
- Admins change governance overrides and triage feedback.
- A controlled cutover window (Caddy 503, schedulers paused, alerts off including `ALERT_EMAILS_ENABLED=false`, `NARRATOR_MODE=rule_based`, UI before/with API) deploys a new verdict engine to a database that holds evaluations.

## Protected areas (pause and review first)
Auth and sessions (`api/security.py`), billing and webhooks, `database/migrations/`, `ratio_engine/`, `.github/workflows/`, anything that touches production credentials.

## Dependencies
No new dependency without a reason logged in [DEPENDENCIES.md](DEPENDENCIES.md).
