# MVP Remediation Plan

## 1. Market-data resilience
- Persist bhavcopy lookups in a `bhavcopy_quotes` table so data survives restarts.
- Extend `BhavcopyMarketResolver` to read/write that table via `database_manager`.
- Record per-symbol failures in `data_quality_issues` (issue type `market_data_fetch_failed`) so the UI can surface fallback status.
- Alert the ops channel via `OpsNotifier` when a symbol fails N times in a row.
- UI: add an auto/manual badge next to each ratio indicating provider (Indian Stock API, Bhavcopy, Cached, Manual).

## 2. Historical analytics view
- Add cursor-based pagination to `/filings/{symbol}/history` so analysts can request older quarters (e.g. `before=<ISO>` + `next_cursor`).
- Update UI timeline/heatmap to use the cursor and provide a "Load more" button.
- Add pytest + Jest coverage for the new parameters and UI behavior.

## 3. Governance accuracy
- Integrate structured parsing (XBRL/JSON) for high-volume filings; fall back to current regex heuristics only when structured data is absent and mark them low-confidence.
- Extend governance overrides table with confidence + reviewer metadata and show override history in the UI.
- Nightly validation comparing our metrics to reference providers for key tickers; log discrepancies as `data_quality_issue` entries.

## 4. Feedback visibility
- Send notifications (email/Slack) to the reporter when reviewers update their ticket.
- Improve `/feedback/status/{token}` payload: include status, last action date, and whether re-evaluation changed the verdict.
- UI modal for users to paste their tracking token and view the timeline.

## 5. Monitoring & docs
- Wire `OpsNotifier` to Slack/email so ingestion failures raise real alerts.
- Provide a lightweight metrics dashboard or script summarizing `logs/metrics/ingestion_metrics.jsonl`.
- Expand `README_ops.md` with a backfill playbook, log locations/rotation, and secret rotation/restart steps.

## 6. Execution order / focus
1. Market data resilience (most visible gap).
2. History pagination + UI enhancements.
3. Governance structured parsing + reviewer workflow.
4. Feedback notifications/UI.
5. Monitoring/alerting + documentation polish.

Track each item in Notion/Trello with owner + ETA, keep branches small (tests included), and deploy to staging VM before merging.
