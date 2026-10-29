# BUG-001: partial data screened as compliant

Append a timestamped log; never rewrite history.

## Symptom
A filing with only some inputs (for example only total debt, or revenue with no interest income) came back `is_compliant = True`. `/halal-score` and the UI showed "Non-compliant" when all inputs were missing. Historical rows stored by the jobs disagreed (`False` vs `None`).

## Repro (before the fix)
`FinancialSnapshotInput(total_debt=1.0)` with a market cap: one computed passing ratio, four `passed=None`, `_aggregate_verdict` ignored the `None`s and returned `True`. A snapshot with no non-permissible, interest or dividend figure computed prohibited income as 0 and passed. A negative base (`-20`) plus interest `10` over revenue `100` gave `-0.1` and passed. A JSON `false` became a verified `0.0`.

## Root cause
Missing ratios were skipped instead of blocking `compliant`; unknown inputs defaulted to zero; five copies of "verdict from boolean" spread the error; type and range checks were absent.

## Fix (PR #87, commit `c359149`)
Engine-owned three-state verdict (`REQUIRED_RATIOS`, strict income), exact Decimal decisions, input validation (`_number`, `coerce_amount`), one summary builder, nullable `is_compliant`, final-pair persistence. See [DECISIONS.md](../DECISIONS.md) D-001 to D-005.

## Verification
- `pytest`: 503 passed; golden table rows for each missing/invalid input and for exact boundaries.
- Four-job parity tests (old derivations fail them for the insufficient case when loaded from `main`).
- Real ETL parser → engine with boolean/underflowing fields -> `insufficient-data`.
- Not verified: production data; GitHub Actions on the final commit beyond the green run.

## Log
- 2026-10-27: found while reading the code for the CI/release plan; fixed in PR #87 (draft); stored rows still stale until PR-B.
- 2026-10-29: PR #87 merged 2026-10-28; PR-B landed as PR #91 (`jobs.backfill_evaluations --recompute`, dry run by default). Stored rows stay stale until someone runs it with `--write`; production holds no filings yet (BSE blocks the server).
