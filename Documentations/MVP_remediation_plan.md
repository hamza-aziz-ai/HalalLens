# MVP Remediation Plan (Updated)

> **Status (2026-10-29): kept as history; the section statuses below are not maintained.** Since it was written: Bhavcopy quotes persist in `bhavcopy_quotes`, market-data failures are recorded in `data_quality_issues` and alert ops after `MARKET_FAILURE_ALERT_THRESHOLD` failures, XBRL/JSON parsing exists in `etl/financial_data_processor.py`, `/ops/metrics` and an uptime workflow exist. Not built: a fallback-reason display, email/Slack notifications when feedback tickets update, a metrics dashboard. Current state and next steps live in `docs/HANDOVER.md`.

This plan tracks the remaining work after the current feature rollout.

## 1. Market-data resilience
Status: **in progress**
- Persist bhavcopy lookups in a `bhavcopy_quotes` table so data survives restarts.
- Record per-symbol failures in `data_quality_issues` and alert ops after N retries.
- The web UI already shows provider badges. Expand to show fallback reason.

## 2. Historical analytics view
Status: **done**
- Cursor-based history API exists with `next_cursor`.
- The web dashboard provides "Load more" and timeline/trend UI.

## 3. Governance accuracy
Status: **partial**
- Governance overrides + reviewer metadata + history are live in the web dashboard.
- Remaining: structured XBRL/JSON parsing for filings and nightly validation checks.

## 4. Feedback visibility
Status: **partial**
- Status endpoint now returns audit trail; the web dashboard shows it.
- Remaining: notifications (email/Slack) when tickets update.

## 5. Monitoring & docs
Status: **in progress**
- Ops runbook exists and was updated.
- Remaining: lightweight metrics dashboard and automated alert wiring checks.

## 6. Execution order / focus
1. Market-data resilience persistence + alerting.
2. Governance structured parsing + validation.
3. Feedback notifications.
4. Monitoring dashboards.
