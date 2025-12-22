# HalalLens Ops Runbook

This guide captures day‑to‑day operations for running HalalLens in a pilot or early production environment.

## 1. Secrets & environment

| Variable | Purpose |
| -------- | ------- |
| `POSTGRES_*` | Database host, db name, user, password. Use external Postgres; Docker compose connects via `host.docker.internal`. |
| `MINIO_*` | MinIO credentials if you override defaults from `jobs/ingest_bse.py`. |
| `INDIAN_API_BASE_URL`, `INDIAN_API_KEY` | Indian Stock Market API endpoint + token for live market data/metrics. |
| `OPS_*` | Ops alerting (SMTP + Slack). See README for full list. |
| `HALAL_LOG_ROOT` | Where component logs live (default `./logs`). |
| `LOG_LEVEL` | `DEBUG` / `INFO`. Set globally or per service. |
| `NARRATOR_*`, `LLM_*` | LLM narrator configuration (optional). |

Store secrets in a `.env` file, Docker secrets, or whichever secret manager your platform provides. Rotate them periodically; when rotating DB passwords, restart API + ingestion containers to pick up the new values.

## 2. Schema migrations

1. Pull latest `main`.
2. Apply any new files in `database/migrations/` using `psql` against your Postgres instance:  
   `psql -h <host> -U <user> -d Halal-Lens -f database/migrations/<timestamp>_<name>.sql`
3. Restart the API if columns changed.

Never skip migrations; the backend expects the schema to match.

## 3. Ingestion/backfill operations

### Scheduled ingestion

- Run `pipenv run python -m jobs.schedule_ingestion` as a service (systemd, supervisor, container).  
- Environment variables: `INGESTION_INTERVAL_MINUTES`, `OPS_*` for alerts.
- Logs: `logs/scheduler/<Year>/<Month>/scheduler.log`.
- Metrics: `logs/metrics/ingestion_metrics.jsonl`.

### Manual backfill

To ingest specific ranges (e.g., newly added AAOIFI fields):

```bash
pipenv run python -m jobs.ingest_bse --from-date 20251009 --to-date 20251009 --save-cache
pipenv run python -m jobs.backfill_evaluations --from-date 20251009 --to-date 20251009
```

`--save-cache` stores raw JSON in `cache/` for audits; clean it when finished.

## 4. Logs & monitoring

- Files reside under `logs/<component>/<Year>/<MonthName>/component.log`. Rotations include the date suffix.
- Example: `tail -f logs/api/2025/December/api.log`
- Ship logs to S3/Vector via your preferred agent; prune older months with `find logs -type f -mtime +90 -delete`.
- Ops notifications: configure `OPS_SMTP_*`, `OPS_EMAIL_*`, and/or `OPS_SLACK_WEBHOOK`. Failures produce “ERROR” emails/Slack messages with tracebacks; recoveries emit “INFO” alerts.
- Metrics (JSONL) can be ingested by Promtail/Vector for dashboards (success/failure counts, duration).
  - `monitoring/notifier.py` drives the alerts. To test, run `python -m monitoring.notifier` after exporting the `OPS_*` variables or call `OpsNotifier("api").notify("INFO", "testing")` from a REPL.
  - The ingestion scheduler writes JSON lines to `logs/metrics/ingestion_metrics.jsonl`. Quickly summarize them with:

    ```bash
    python tools/metrics_inspector.py logs/metrics/ingestion_metrics.jsonl
    # or tail the last N runs
    python tools/metrics_inspector.py --tail 10
    ```

    Forward the JSONL file to Grafana/Prometheus by pointing Promtail/Vector at it. A minimal Promtail scrape config:

    ```yaml
    - job_name: halallens_ingestion
      static_configs:
        - targets: [localhost]
          labels:
            __path__: /home/halal/logs/metrics/ingestion_metrics.jsonl
            job: halallens-ingestion
    ```

## 5. Manual data quality review

- Use the dashboard “Feedback queue” to triage reports. Reviewers add notes and mark entries resolved (see README).
- If you need to suppress a filing temporarily, set `verdict=null` in `filing_evaluations` and re-run the ingestion/backfill for that symbol once corrections exist.
- Record manual overrides/notes in `feedback_reports.review_notes` to keep an audit trail.
- For AAOIFI-specific fixes (receivables/liquid/non-halal income), leverage the “Governance overrides” card in the dashboard or call `/governance/overrides` via API. Overrides live in the `governance_overrides` table and are applied before ratios execute.

## 6. Disaster recovery

- **Postgres**: snapshot nightly (pg_dump or managed backup).  
- **MinIO PDFs**: replicate the bucket externally (MinIO gateway or rclone).  
- **Cache/downloads**: not critical—rebuildable by re-running ingestion.  
- **.env** / secrets: store in a secure vault and version them with change history.

## 6. Backfills & secret rotation runbook

### Running historical backfills

1. Decide the date range (BSE is noisy; keep batches ≤ 2 weeks). Example:

   ```bash
   pipenv run python -m jobs.ingest_bse --from-date 20241101 --to-date 20241107 --save-cache
   pipenv run python -m jobs.backfill_evaluations --from-date 20241101 --to-date 20241107
   ```

2. Watch `logs/ingestion/` for errors; resolve missing market data by re-running just the affected symbols.
3. After a successful batch, commit or archive the cache files if you need provenance; otherwise, prune `cache/`.

### Rotating secrets / credentials

1. Store all sensitive values in your vault of choice (1Password, Vault, AWS SM, etc.). Never edit `.env` directly on production hosts.
2. When a credential changes (Indian API key, SMTP password, DB user):
   - Update the vault and regenerate the `.env` from template (`cp .env.example .env && edit`).
   - Restart API/UI/scheduler containers so they pick up the new env values (`docker compose restart api ui ingestion`).
   - Confirm `GET /health` and the ingestion heartbeat update.
3. Record the change in your ops log and destroy/rotate the old secret if applicable.

Keep this runbook alongside `README.md`; update both whenever operational requirements change.

## 7. Troubleshooting checklist

- `GET /health` returns `{"status": "ok"}` – verifies FastAPI + DB connectivity.  
- Scheduler heartbeat: check `/tmp/ingestion_heartbeat.txt` timestamp (or your custom path).  
- Persistent Indian API failures: inspect `logs/market_data/` and consider adjusting API rate limits, refreshing the key, or falling back to Bhavcopy-only mode temporarily.  
- LLM narration errors: confirm Ollama/vLLM endpoint reachable from containers (`curl http://host.docker.internal:11434/health`).  
- Feedback queue empty but users reported issues: check `logs/api/.../api.log` for errors around `/feedback` endpoints.
