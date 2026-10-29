# TESTING

What must pass before a change counts as done. Paste real output into the PR; "tests pass" is not evidence.

## Commands

```bash
pipenv run pytest --cov                          # backend + coverage floor; CI runs the same (plus `pipenv run pip check`)
cd ui && npm ci && npm run lint && npm test -- --coverage && npm run build
docker build -f api.Dockerfile -t halal-lens-api:check .     # when Pipfile, Dockerfiles or .dockerignore change
docker run --rm -v "$PWD:/repo:ro" ghcr.io/gitleaks/gitleaks:latest git /repo --no-banner --redact   # secrets over history
```

Recompute dry run (needs a database): `pipenv run python -m jobs.backfill_evaluations --recompute --report before_after.csv`; nothing is written without `--write`.

**Pass looks like:** `pytest` ends with `N passed` and no failures (503 at the time of PR #87); jest `Test Suites: 7 passed`; lint `No ESLint warnings or errors`; `next build` finishes; gitleaks `no leaks found`.

## CI (required on every PR)
`backend` (pip check, pytest with coverage), `ui` (lint, jest with coverage, build), `secrets` (gitleaks, full history), `docker` (builds the Python image, which runs the API, preflight, migrations and both schedulers as UID 10001, and the UI image from a clean checkout and runs `scripts/docker_smoke.sh`: API `/health`, `/openapi.json`, a public `/halal-score` and a 503 for a DB route without a database; UI `/`, `/login/` and one script asset; scheduler job imports from the same image, and a check that it does not run as root) and `scripts/proxy_smoke.sh` (the production Caddy routing on one origin: `/api/health`, bare `/api` redirect, Swagger loading `/api/openapi.json`, a JSON 404 for unknown API paths, `/api/halal-score`, the dashboard and policy redirects, the UI bundle calling `/api`, and a forged `X-Forwarded-For` not escaping the rate limit). All of `backend`, `ui`, `secrets`, `docker` and `docker-arm64` are required on `main` (ruleset, 2026-10-29).

## Coverage floors (a ratchet)
- Backend: `.coveragerc` measures line and branch coverage over every application package, so modules no test imports count as 0%. `fail_under` is 46.4 (43.58% at the first measurement; 46.47% with 667 tests after the HTTP contracts).
- UI: `ui/jest.config.cjs` counts every file in `app/`, `components/`, `lib/` and `providers/`. Thresholds: statements 13, branches 13, functions 18, lines 14 (measured 13.35 / 13.84 / 18.82 / 14.04 on 2026-10-28; the earlier 82% counted only files a test imported).
- Raise a floor in the PR that adds the tests. Lowering one, or excluding files, needs the maintainer's review.
- Coverage shows what ran, not what was checked: a test weakened to `assert True` keeps its coverage. It is a guard against regression, not the definition of done.

## Road to CI as the only merge gate (agreed with Codex, 2026-10-28)
Auto-merge stays held until these land, in order. "Complete enough" means every critical contract is tested across its real boundary, and representative regressions are shown to fail CI.
1. Measurement: coverage floors above, `pip check`, unused `zod` removed.
2. HTTP and security contracts (done except the `/alerts/check` fix, which gets its own PR): `TestClient(app)` with lifespan; route-tier matrix (anonymous / free / paid / admin, expired sessions, ownership, 401/403/422/429, CORS, nullable verdict JSON); a test that fails when a route has no tier; `/alerts/check` defects fixed.
3. Billing contracts: real HMAC with dummy secrets; tampered or unsigned bodies; wrong owner, amount or currency; duplicate and concurrent settlement; webhook vs browser ordering; trial reuse.
4. Real SQL and migrations: disposable Postgres 14 service in CI; bootstrap, seeded prior-schema upgrade, rerun, schema comparison; integration tests selected explicitly (ordinary tests stay offline).
5. Input to verdict: PDF/XBRL/JSON/CSV fixtures through the real parsers into the engine (ingestion runs on the request path); `_detect_scale` fixed with a regression test; one success and one failure cycle per scheduler.
6. UI: Jest contracts for `lib/api.ts` and auth/billing helpers, every verdict state; a small Playwright smoke on the served static export.
7. Packaging: build the three Docker images; container smoke (startup, `/openapi.json`, a real screening request).
8. Merge policy: CODEOWNERS plus a code-owner-review ruleset over sensitive paths (workflows, migrations, `api/app.py`, `api/security.py`, `ratio_engine/`, tests, gate config); a fail-closed required aggregate; branch up to date with `main`; dependency review; the release token only in the `release` environment. Then a deliberate-regression exercise and live enforcement tests, then activation.

What CI cannot catch even then: behaviour no test asserts, vendor/Razorpay/Google API changes, production-data effects, performance, supply-chain malice.

## What the tests prove (and do not)
- `tests/test_ratio_engine.py`: golden verdict table (boundaries at exactly 30%/5%, each missing input, each invalid input), exact-decimal edge cases.
- `tests/test_job_verdicts.py`: all four jobs persist the engine's verdict pair; real adapters reject booleans. **Stubs** patch market lookup (and the BSE mapper in the persistence test).
- `tests/test_amounts.py`: every converter x unusable/known values; real ETL parser -> engine; API payload rejection; thresholds; market-cap handling.
- `tests/test_api_endpoints.py`: handlers without HTTP; final-pair parity for persistent and transient records.
- `tests/test_http_contracts.py`: every request through the ASGI stack with `TestClient`. A route table must match `app.routes` exactly, so a new route without a tier fails. Tier matrix: anonymous, free, paid and admin against all 34 routes, matched on the guard's status and message. Malformed, unknown and expired sessions; raw tokens never reach the database; three-state verdict JSON (`null` stays `null`); 422s for booleans, extra fields and bad dates; security headers; CORS allow and deny; 429 with `Retry-After`; watchlist scoped to the session. Outbound non-loopback sockets are blocked. Disabling the paid guard makes 6 of these tests fail (checked by hand on 2026-10-28).
- `tests/test_watchlist_postgres.py` (**opt-in, not in CI**): the watchlist storage against a real, disposable PostgreSQL with independent connections: concurrent identical flips alert once, opposite verdicts from a NULL baseline never lose the flip, re-adding keeps the baseline, owner isolation, cascade on user delete, rollback on a failed statement. It is the one narrow exception to "tests need no live Postgres", because locking cannot be proven with mocks; it is skipped unless `HALALLENS_TEST_PG_DSN` points at a throwaway database (the file's docstring has the `docker run` line). Run it whenever `alerts/storage.py` changes and paste the output in the PR.
- They do **not** prove production data behaviour, the deployed UI, or the GitHub Actions environment.

## Manual path a customer would take (before activating a new engine)
1. Register / sign in on the dashboard.
2. Open a filing for a symbol with complete data: expect a green **Compliant** badge and a deterministic explanation.
3. Open a filing with missing interest/dividend: expect amber **Insufficient data**, never **Non-compliant**.
4. Run the analysis form with a blank field: expect "Insufficient data" and the missing input named.
5. Hit `/halal-score` with `{"interest_income": true}`: expect a 422.

## Before shipping Lane-B changes
Run the pre-ship gate in the field guide: read the full diff, see real test output, try one customer path by hand, confirm no secrets, log new dependencies, write rollback steps, clear or accept unverified assumptions ([ASSUMPTIONS.md](ASSUMPTIONS.md)).
