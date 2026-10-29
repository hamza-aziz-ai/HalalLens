# ROLLBACK

How to undo a change. The risky ones first.

## Last known good
- `main` before the verdict fix: commit `63432a2` (a Dependabot update on top of PR #75).
- Releases are tagged `vX.Y.Z` by release-please and published as images (D-018); the release running in production is recorded in `docs/HANDOVER.md`. Roll back a deploy with `scripts/deploy.sh <previous tag>` (README_ops.md); migrations are forward-only, so check the table below first.
- Note the commit/tag before every risky deploy.

## Rolling back the verdict-engine change (PR #87)
**Code:** revert the squash commit on `main` (`git revert <sha>`, via a PR), rebuild images, redeploy. There is no schema change in #87, so no down-migration.

**Data (the real risk):** the new engine does not rewrite stored evaluations by itself, but new evaluations (ingestion, `/filings/{symbol}`) use the new logic. After a `--recompute --write` run (PR #91), rows are overwritten in place (`filing_evaluations` is keyed by `(symbol, filing_date)`).
1. Before any recompute: export `filing_evaluations` with `pg_dump --table` (the CSV is evidence, not a backup) and run the dry run `python -m jobs.backfill_evaluations --recompute --report dry_run.csv`. The CSV holds the old and new verdicts, missing inputs, row status and the inputs and caps used.
2. To go back after a recompute: restore the table from that export.
3. Re-check afterwards: `GET /filings/{symbol}` for a few symbols, the dashboard badges, `/ops/metrics`.

## Controlled cutover (activation) and its rollback
1. Caddy returns 503 on screening routes (keep the Razorpay webhook reachable); pause `ingestion` and `evaluation` schedulers; keep `/alerts/check` off and `ALERT_EMAILS_ENABLED=false` (alerts are rebaselined silently once the scheduler runs again, README_ops "Repair procedure"); set `NARRATOR_MODE=rule_based`.
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
| Billing ledger and reconciliation (D-024, D-025) | Fix forward. Migrations `20261029_subscription_grants`, `_v2_payment_refunds`, `_v3_billing_reconcile`, `_v4_refund_actions` are additive, but older code would ignore grants and refund records and overwrite access. To stop the reconciler alone: `docker compose -f docker-compose-prod.yml stop billing-reconcile` (no data is lost; it resumes from its checkpoint). |
| Lifetime takes effect when paid (D-024 amendment) | Deploy the previous tag, then re-run the Lifetime re-projection command in README_ops (Billing) so stored projections follow the old rule. No schema or grant changes to undo. |
| Upgrade credit at checkout (D-030) | Deploy the previous tag; the migration `20261030_lifetime_upgrade_credit` is additive and stays. Old code settles an open credited order without its checks, so watch open credited orders by hand (README_ops, Billing, "Upgrade credit rollback") |
| One publication path (D-027)                   | Deploy the previous tag; no schema change. Rows already stored as `needs-review` stay so until re-evaluated; older jobs would again store conclusive pairs next to open issues, so prefer fixing forward. |
| Input mappings removal-first (D-028)           | Deploy the previous tag; no schema change. Old code reads the `metrics/v4/` cache objects again and restores the rejected stand-ins (current assets, "Other, Net", net interest) on new extractions; snapshots written since keep their missing fields. Prefer fixing forward. |
| Compliance-flip emails to subscribers (D-031)  | Prefer the switch: set `ALERT_EMAILS_ENABLED=false` and recreate `evaluation` (README_ops, "Alert emails"); pending flips are then rebaselined silently. A code rollback needs the previous tag; the migration `20261030_alert_emails` is additive and stays, and old code mails flips found by `/alerts/check` only to `ALERT_EMAIL_RECIPIENT`, if that is set. |
| Cloudflare maintenance Worker                  | Remove the `halallens.in/*` route in the Cloudflare dashboard; the site works without it |
| Auth hardening (D-020)                         | Do not revert the code alone: the migration revoked unproven admins and every session. Fix forward; if an admin is locked out, prove the mailbox with a reset link or Google sign-in. A full revert also needs `ALTER TABLE users DROP COLUMN email_verified_at; DROP TABLE auth_tokens;` and re-setting `is_admin` by hand. |
| Postgres 14 -> 17 upgrade (D-029)              | Before the cutover: the way back at each checkpoint in README_ops ("Postgres major upgrade"). After it: `scripts/deploy.sh <previous tag>` boots 14 on the untouched `postgres_data` volume with the data as of the freeze; writes made on 17 are lost unless dumped and restored into 14 by hand (README_ops). Keep the old volume and the off-site dump for 14 days. The cutover ran on 2026-10-29 (v0.17.4); a one-time cron job on the server removes the old volume on 2026-11-13, after which there is no way back to 14 short of restoring a 14 dump by hand. |

## Prefer a switch over a deploy
There is no feature flag for the verdict. The safest brake is to keep the new engine un-deployed outside the cutover window. Switches that exist: `ALERT_EMAILS_ENABLED` (alert emails, D-031), `NARRATOR_MODE` (LLM narration), and stopping the `billing-reconcile` service (reconciliation and automatic refunds).
