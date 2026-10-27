# FAILURE

For each dependency: what if it is slow, down, wrong or empty? First limit expected, and how we would notice.

| Dependency | Failure | What happens | How we notice |
| ---------- | ------- | ------------ | ------------- |
| Postgres | Down or slow | API starts with "Database unavailable"; DB-backed routes return 503; `/halal-score` still works (no DB read) | `GET /health`, API logs, compose healthcheck, `preflight` |
| MinIO | Down | New PDFs cannot be stored; reads of already-parsed data continue | `preflight`, ingestion logs and ops alert |
| Indian Stock API | Down / rate-limited / wrong | Falls back to Bhavcopy; failures recorded in `data_quality_issues`; payload cache never expires, caches `None` failures | `/ops/metrics`, ops alert, api logs |
| BSE site | Down / blocks | Ingestion run fails; heartbeat stops advancing | Scheduler heartbeat, `/ops/metrics`, ops email/Slack |
| Razorpay | Down / webhook delayed | Orders fail; webhook replays are idempotent | Razorpay dashboard, api logs |
| SMTP | Down | Alert email fails after the verdict is computed | Notifier log lines |
| Narrator LLM (`NARRATOR_MODE=llm`) | Down / slow / malformed / contradicts the verdict | Falls back to the rule-based narration (error, doubtful text, or unknown verdict); the label shown is always the engine's | Warning logs, `failure_callback`, `/ops/metrics` narration failures |
| Filing PDF | Scanned/odd layout | Metrics missing -> `insufficient-data`, not a pass | Quality issues, feedback queue |
| The verdict engine | Bad input | Unknown, never a pass; non-finite quotients are `invalid` | Golden tests; `missing_inputs` in responses |

## Limits we expect to hit first
1. **`insufficient-data` volume.** Interest and dividend figures are rarely extracted, so many filings will be unknown. Measure with the PR-B dry run.
2. **Per-process rate limiter** once `uvicorn --workers N` > 1 or after restarts.
3. **Single Postgres / single host** for the pilot.

## After deploying a new engine
Stored evaluations still hold old verdicts until recomputed; see [ROLLBACK.md](ROLLBACK.md).
