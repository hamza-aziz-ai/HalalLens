# TESTING

What must pass before a change counts as done. Paste real output into the PR; "tests pass" is not evidence.

## Commands

```bash
pipenv run pytest                                # backend; CI runs the same command
cd ui && npm ci && npm run lint && npm test && npm run build
docker build -f api.Dockerfile -t halal-lens-api:check .     # when Pipfile, Dockerfiles or .dockerignore change
docker run --rm -v "$PWD:/repo:ro" ghcr.io/gitleaks/gitleaks:latest git /repo --no-banner --redact   # secrets over history
```

Recompute dry run (needs a database): `pipenv run python -m jobs.backfill_evaluations --recompute --report before_after.csv`; nothing is written without `--write`.

**Pass looks like:** `pytest` ends with `N passed` and no failures (503 at the time of PR #87); jest `Test Suites: 7 passed`; lint `No ESLint warnings or errors`; `next build` finishes; gitleaks `no leaks found`.

## CI (required on every PR)
`backend` (pytest), `ui` (lint, jest, build), `secrets` (gitleaks, full history). `main` cannot be merged without all three.

## What the tests prove (and do not)
- `tests/test_ratio_engine.py`: golden verdict table (boundaries at exactly 30%/5%, each missing input, each invalid input), exact-decimal edge cases.
- `tests/test_job_verdicts.py`: all four jobs persist the engine's verdict pair; real adapters reject booleans. **Stubs** patch market lookup (and the BSE mapper in the persistence test).
- `tests/test_amounts.py`: every converter x unusable/known values; real ETL parser -> engine; API payload rejection; thresholds; market-cap handling.
- `tests/test_api_endpoints.py`: handlers without HTTP; final-pair parity for persistent and transient records.
- They do **not** prove production data behaviour, the deployed UI, or the GitHub Actions environment.

## Manual path a customer would take (before activating a new engine)
1. Register / sign in on the dashboard.
2. Open a filing for a symbol with complete data: expect a green **Compliant** badge and a deterministic explanation.
3. Open a filing with missing interest/dividend: expect amber **Insufficient data**, never **Non-compliant**.
4. Run the analysis form with a blank field: expect "Insufficient data" and the missing input named.
5. Hit `/halal-score` with `{"interest_income": true}`: expect a 422.

## Before shipping Lane-B changes
Run the pre-ship gate in the field guide: read the full diff, see real test output, try one customer path by hand, confirm no secrets, log new dependencies, write rollback steps, clear or accept unverified assumptions ([ASSUMPTIONS.md](ASSUMPTIONS.md)).
