# FAILURE

For each dependency: what if it is slow, down, wrong or empty? First limit expected, and how we would notice.

| Dependency                         | Failure                                           | What happens                                                                                                              | How we notice                                                       |
|------------------------------------|---------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------|
| Postgres                           | Down or slow                                      | API starts with "Database unavailable"; DB-backed routes return 503; `/halal-score` still works (no DB read)              | API logs, `preflight`, `/health/billing` 503 (with Razorpay configured); `GET /health` is liveness only and stays 200 |
| MinIO                              | Down                                              | New PDFs cannot be stored; reads of already-parsed data continue                                                          | `preflight`, ingestion logs and ops alert                           |
| Indian Stock API                   | Down / rate-limited / wrong                       | Falls back to Bhavcopy; failures recorded in `data_quality_issues`; successful payloads cached 6 h, failures not cached (#156); at `INDIAN_API_MONTHLY_LIMIT` calls stop until the next month | `/ops/metrics`, ops alert, api logs                                 |
| BSE site                           | Down / blocks                                     | Ingestion run fails; heartbeat stops advancing. Happening now: BSE answers 403 to the production server, so production stores no filings (ASSUMPTIONS #25) | Scheduler heartbeat, `/ops/metrics`, ops email/Slack                |
| Razorpay                           | Down / webhook delayed or disabled                | Orders fail (503, never 502); payments made while we were down are settled by the reconciler within 15 min of recovery; Razorpay disables a webhook after 24 h of failures | Reconciler "webhook was missed" alert, `billing_tracked`, Razorpay dashboard |
| Payment reconciler                 | Stopped or failing                                | Missed webhooks and dashboard refunds wait; automatic refunds wait                                                        | `/api/health/billing` stale, uptime workflow issue, `billing_reconcile_state.last_error` |
| API or dashboard container         | Restarting (deploy) or down                       | Caddy serves the maintenance page (503) and a JSON 503 under `/api/*`; open dashboards show the maintenance overlay      | Uptime workflow, deploy smoke test                                  |
| Caddy, tunnel or VM                | Down                                              | The Cloudflare Worker serves the same maintenance page; `/api/*` returns Cloudflare's 530                                 | Uptime workflow                                                     |
| SMTP                               | Down                                              | Alert email fails after the verdict is computed; sign-up and reset links do not arrive while the API still answers 202    | Notifier log lines; `Account email failed` in the API log           |
| Narrator LLM (`NARRATOR_MODE=llm`) | Down / slow / malformed / contradicts the verdict | Falls back to the rule-based narration (error, doubtful text, or unknown verdict); the label shown is always the engine's | Warning logs, `failure_callback`, `/ops/metrics` narration failures |
| Filing PDF                         | Scanned/odd layout                                | Metrics missing -> `insufficient-data`, not a pass                                                                        | Quality issues, feedback queue                                      |
| The verdict engine                 | Bad input                                         | Unknown, never a pass; non-finite quotients are `invalid`                                                                 | Golden tests; `missing_inputs` in responses                         |

## Limits we expect to hit first
1. **`insufficient-data` volume.** Interest and dividend figures are rarely extracted, so many filings will be unknown. Measure with the `--recompute` dry-run report once real data exists.
2. **Per-process rate limiter** once `uvicorn --workers N` > 1 or after restarts.
3. **Single Postgres / single host** for the pilot.

## After deploying a new engine
Stored evaluations still hold old verdicts until recomputed; see [ROLLBACK.md](ROLLBACK.md).
