# ROLLBACK

How to undo a change. The risky ones first.

## Last known good
- `main` before the verdict fix: commit `63432a2` (a Dependabot update on top of PR #75). Tags: none yet (release-please creates `v0.x` on the first release PR).
- Note the commit/tag before every risky deploy.

## Rolling back the verdict-engine change (PR #87)
**Code:** revert the squash commit on `main` (`git revert <sha>`, via a PR), rebuild images, redeploy. There is no schema change in #87, so no down-migration.

**Data (the real risk):** the new engine does not rewrite stored evaluations by itself, but new evaluations (ingestion, `/filings/{symbol}`) use the new logic. After PR-B's recompute runs, rows are overwritten in place (`filing_evaluations` is keyed by `(symbol, filing_date)`).
1. Before any recompute: export `filing_evaluations` with `pg_dump --table` (the CSV is evidence, not a backup) and run the dry run `python -m jobs.backfill_evaluations --recompute --report dry_run.csv`. The CSV holds the old and new verdicts, missing inputs, row status and the inputs and caps used.
2. To go back after a recompute: restore the table from that export.
3. Re-check afterwards: `GET /filings/{symbol}` for a few symbols, the dashboard badges, `/ops/metrics`.

## Controlled cutover (activation) and its rollback
1. Caddy returns 503 on screening routes (keep the Razorpay webhook reachable); pause `ingestion` and `evaluation` schedulers; keep `/alerts/check` off; set `NARRATOR_MODE=rule_based`.
2. Deploy API and UI together (UI before or with the API; the old UI renders `null` as "Non-compliant").
3. Run the reviewed recompute with a new report name (`--recompute --report write_run.csv --write`; an existing file is refused). It re-reads the current stored inputs rather than replaying the dry run, so compare the two CSVs; verify that `verdict` and `is_compliant` agree on every row. Each write commits on its own: after a failure, restore from the `pg_dump` or rerun.
4. Clear the in-process narration cache (restart the API); lift maintenance only after verification.
**Rollback:** keep maintenance on, redeploy the previous images, restore the exported table, then lift maintenance.

## Other changes
| Change                                         | How to undo                                                                        |
|------------------------------------------------|------------------------------------------------------------------------------------|
| CI / Dependabot / release-please (PR #74, #75) | Revert the PR; a ruleset can be edited or disabled in repo settings                |
| Dependency cleanup (PR #74)                    | Revert; `Pipfile.lock` restores the old pins (re-adding torch is a multi-GB image) |
| Release created by release-please              | Delete the GitHub Release and tag; revert the release PR commit                    |
| Docs-only PRs                                  | Revert                                                                             |
| Auth hardening (D-020)                         | Do not revert the code alone: the migration revoked unproven admins and every session. Fix forward; if an admin is locked out, prove the mailbox with a reset link or Google sign-in. A full revert also needs `ALTER TABLE users DROP COLUMN email_verified_at; DROP TABLE auth_tokens;` and re-setting `is_admin` by hand. |

## Prefer a switch over a deploy
There is no feature flag for the verdict. The safest brake is to keep the new engine un-deployed outside the cutover window.
