# HalalLens Ops Runbook

This guide captures day‑to‑day operations for running HalalLens in a pilot or early production environment.

## 1. Secrets & environment

| Variable                                | Purpose                                                                                                                                                                                                                                                      |
|-----------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `POSTGRES_*`                            | Database host, db name, user, password. Use external Postgres; Docker compose connects via `host.docker.internal`.                                                                                                                                           |
| `MINIO_*`                               | MinIO credentials if you override defaults from `jobs/ingest_bse.py`.                                                                                                                                                                                        |
| `INDIAN_API_BASE_URL`, `INDIAN_API_KEY` | Indian Stock Market API endpoint + token for live market data/metrics.                                                                                                                                                                                       |
| `OPS_*`                                 | Ops alerting (SMTP + Slack). See README for full list.                                                                                                                                                                                                       |
| `HALAL_LOG_ROOT`                        | Where component logs live (default `./logs`).                                                                                                                                                                                                                |
| `LOG_LEVEL`                             | `DEBUG` / `INFO`. Set globally or per service.                                                                                                                                                                                                               |
| `NARRATOR_*`, `LLM_*`                   | Narrator configuration. Default `NARRATOR_MODE=rule_based`. In `llm` mode the model is asked only about conclusive verdicts and its text is best-effort (UI marks it AI-generated); `tools/preflight.py` requires the endpoint to be reachable in that mode. |

Store secrets in a `.env` file, Docker secrets, or whichever secret manager your platform provides. Rotate them periodically; when rotating DB passwords, restart API + ingestion containers to pick up the new values.

### Deployment quick-start

1. Provision a host with Docker Compose v2. No GPU or LLM server is needed for the default rule-based narration; an LLM server is only needed if you set `NARRATOR_MODE=llm` (a compatible GPU if you self-host it).
2. Prepare external Postgres + MinIO/S3 endpoints (or reuse existing ones). Populate `.env` from `.env.example` with all `POSTGRES_*`, `MINIO_*`, `INDIAN_API_*`, `OPS_*`, and (only for the LLM narrator) `NARRATOR_MODE` / `LLM_*`.
3. Launch the stack:

   ```bash
   docker compose up --build -d
   ```

4. Verify:

   ```bash
   curl http://<api-host>:8001/health
   curl http://<api-host>:8001/ops/metrics   # admin session required
   ```

5. Start the ingestion scheduler (systemd or `docker compose run --rm ingestion`). Watch `/ops/metrics` and the ingestion heartbeat for failures.

### Uptime check

`.github/workflows/uptime.yml` requests `<UPTIME_URL>/api/health` every 30 minutes (three tries, 20 s apart). A failure opens one issue labelled `uptime`, or comments on the open one, which notifies the repository's watchers; the next success closes it. Set the repository variable `UPTIME_URL` (e.g. `https://halallens.in`) to turn it on; without it the job is skipped. GitHub disables scheduled workflows after 60 days without repository activity, so re-enable it under Actions if that happens. It checks only that the site answers, not that ingestion or backups ran: read those in the service logs.

### PostgreSQL backups and restore

The `backup` service in `docker-compose-prod.yml` runs `jobs.backup_postgres` once a day (`BACKUP_INTERVAL_HOURS`, default 24). Each run writes a `pg_dump --format=custom` of the app database to `backups/postgres/<db>-<UTC timestamp>.dump` in `MINIO_BUCKET` (R2 in production), then deletes backups under that prefix older than `BACKUP_RETENTION_DAYS` (default 14). Old copies are deleted only after a successful upload; a failed run logs `Backup failed`, notifies through the ops notifier and retries after an hour. The dumps hold user accounts (emails, password hashes, session digests): keep the bucket private and the token scoped to it.

- Back up now: `docker compose -f docker-compose-prod.yml exec -T backup python -m jobs.backup_postgres` (one run inside the running service; `run backup ...` would append to its `--loop` entrypoint).
- **Use the API image's `pg_restore`, not the Postgres container's.** The dumps are written by the API image's `pg_dump` (17); Postgres 14's own `pg_restore` refuses them with `unsupported version (1.16) in file header`. One error during a restore is expected and harmless: `unrecognized configuration parameter "transaction_timeout"` (a 17-only setting).
- Restore: download a `.dump` from the bucket (Cloudflare dashboard, or any S3 client) into `/opt/halallens/halallens.dump`, then stop the writers and restore into the running Postgres:
  1. `docker compose -f docker-compose-prod.yml stop api ingestion evaluation backup`
  2. `docker compose -f docker-compose-prod.yml run --rm --no-deps -T -v "$PWD/halallens.dump:/tmp/restore.dump:ro" --entrypoint sh backup -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore --clean --if-exists --no-owner -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" /tmp/restore.dump'`
  3. `docker compose -f docker-compose-prod.yml up -d`
- Restore drill: restore the newest dump into a throwaway `postgres:14` container started with `--network none`, run the API image's `pg_restore` inside its network namespace (`docker run --network container:<throwaway> --entrypoint pg_restore <api image> ... -h 127.0.0.1`), and compare `count(*)` per table with live. Last drill 2026-10-29: 20 of 20 tables matched, including 34,959 `market_data_snapshots` rows. Repeat monthly and after any Postgres or API base-image upgrade.

### Billing (Razorpay, one-time purchases)

Plans are one-time Razorpay Orders; nothing renews automatically. Each paid order, trial and pre-ledger period is a row in `subscription_grants`, and access is derived from them (D-024): a purchase made while paid time runs starts when it ends, a refund removes only its own purchase's time.

- **Before deploying the first release with D-024**, apply `database/migrations/20261029_subscription_grants.sql` (it is idempotent, and creates a legacy grant that keeps each current subscriber's exact end date). Rehearsed on a restored production copy on 2026-10-29.
- **Refund due:** if a payment lands while Lifetime already covers the user (two checkouts were open), the order gets status `refund_due`, nothing is granted, and the API logs `REFUND DUE`. Refund it in the Razorpay dashboard: `SELECT order_id, user_id, amount, payment_id FROM razorpay_orders WHERE status = 'refund_due';`
- **Refunds that match no grant** (refund-due orders, or old orders the migration could not link) are logged `matches no grant: review by hand`; adjust access by hand only after checking the user's grants.
- Partial refunds keep access until refunds reach the full order amount.

### Docker Hub pages

The Docker Hub descriptions of `halallens-api` and `halallens-ui` come from `docs/dockerhub/*.md` (full description) and `.github/workflows/dockerhub-description.yml` (short description). The workflow runs when those change on `main`, or by hand (Actions, Docker Hub descriptions, Run workflow). It uses `DOCKERHUB_NAMESPACE` and `DOCKERHUB_TOKEN` from the `publish` environment; updating a description needs a token with Read, Write, Delete access. Categories (up to three per repository) can only be set in Docker Hub's repository settings, not through the API.

### LLM narration (Ollama, optional)

The Explain-Why text is rule-based by default. To let a model rewrite it for conclusive verdicts (D-022):

1. Add `llm` to `COMPOSE_PROFILES` and set `NARRATOR_MODE=llm`, `LLM_PROVIDER=ollama`, `LLM_ENDPOINT=http://ollama:11434/api/chat`, `LLM_MODEL=gpt-oss:120b-cloud` in `.env`, then deploy.
2. Link the daemon to the Ollama account once: `docker compose -f docker-compose-prod.yml exec ollama ollama signin`, open the printed link in a browser signed in to ollama.com and connect the device. The key lives in the `ollama_data` volume, so restarts and updates stay signed in; deleting the volume or removing the device on ollama.com signs it out ("You need to be signed in" in the API log).
3. Check: `docker compose -f docker-compose-prod.yml exec ollama ollama run gpt-oss:120b-cloud "Say ok"`.

Calling ollama.com directly with an API key needs paid credits (HTTP 402); the signed-in daemon uses the account's free allowance, whose limits are not published. The API therefore makes at most 6 model calls a minute and skips the model for 60 s after 3 failures in a row; any failure, timeout or text that contradicts the verdict falls back to the rule-based explanation. Only public filing figures, the symbol and the verdict are sent, never user data; prompts and replies are not logged. Trade-off: the VM holds a signed-in device on the maintainer's Ollama account, so anyone who controls the VM can spend that allowance.

### Indian Stock API quota

The vendor plan is small (the free plan allows 500 requests per month). Every vendor call goes through `market_data/indian_api.py::_request_json`, which enforces `INDIAN_API_MONTHLY_LIMIT` (production default 450) with a counter in `cache/indian_api_quota.json` in the persistent `api_cache` volume, so the cap survives restarts. At the cap the app logs `Indian API monthly limit reached` and falls back to stored data and the free Bhavcopy files. In production the ingestion and evaluation schedulers run with the vendor turned off, so the quota is spent only on users' on-demand lookups. The API key is sent only in the `X-API-Key` header, never in a URL.

### Production deploys (`scripts/deploy.sh`)

On the server, from the checkout that holds `.env` (production: `/opt/halallens`):

```bash
git fetch --tags && git checkout vX.Y.Z   # first time only, to get the script
scripts/deploy.sh vX.Y.Z
```

The script checks out the release tag (compose file, Caddyfile, migrations), then:

- **Pull mode** (recommended): with `IMAGE_REPOSITORY` in `.env` (e.g. `ghcr.io/<owner>` or `docker.io/<namespace>`), it pulls `halallens-api` and `halallens-ui` for that tag: the images CI tested, smoke-tested, Trivy-scanned and published with SBOM and provenance. Nothing is built on the server. Wait for the release's Publish images run to finish first; if the tag is not published yet, the pull fails before anything is restarted.
- **Build mode** (default): without `IMAGE_REPOSITORY`, it builds the images on the server from the tag.

Either way it starts the stack, waits for the API health check, prints the service states and smoke-tests `/api/health`, `/api/openapi.json`, `/` and `/products/` through Caddy; a non-200 makes it exit non-zero. **Rollback:** run it again with the previous tag (migrations are forward-only: see `docs/ROLLBACK.md`). The dashboard's support address is part of the UI image: the publish workflow bakes in the repository variable `SUPPORT_EMAIL`, and build mode uses `SUPPORT_EMAIL` from `.env` (default `support@<HALAL_APP_DOMAIN>`).

**During a deploy** the api and ui containers restart for a few seconds. The front Caddy then answers with `caddy/maintenance.html` (503, `Retry-After: 20`, reloads itself), and `/api/*` with a JSON 503. Cloudflare's own "Bad gateway" page appears only when Caddy, cloudflared or the VM itself is down. Every 502 is avoided on purpose: Cloudflare replaces an origin 502 with its own page, so upstream failures in the API (Razorpay, Google) answer 503. Unknown paths get the dashboard's 404 page (`ui/app/not-found.tsx`, exported as `404.html`).

### Cloudflare maintenance Worker (origin down)

The front Caddy's maintenance page cannot help when Caddy, cloudflared or the VM itself is down; Cloudflare then shows its own error page. `cloudflare/maintenance-worker.js` covers that case on the free Workers plan: it passes every request to the origin and answers a 503 maintenance page only when Cloudflare reports the origin unreachable (502, 504, 520 to 527, 530 = tunnel down) or the fetch fails.

Deploy once from the Cloudflare dashboard (no token needed):

1. **Workers & Pages → Create → Worker**, name it `halallens-maintenance`, deploy the starter, then **Edit code**, replace everything with `cloudflare/maintenance-worker.js` and **Deploy**. Under **Settings**, turn **Observability** logs off (they would record visitor requests).
2. **Settings → Domains & Routes → Add → Route:** zone `halallens.in`, route `halallens.in/*`, failure mode **Fail open** (if the Worker errors or the free plan's 100,000 requests a day run out, traffic goes straight to the origin).
3. **Websites → halallens.in → Workers Routes → Add route:** `halallens.in/api/*` with Worker **None**, so API calls and Razorpay webhooks never pass through the Worker.
4. Check: `curl -sI https://halallens.in/` still returns 200, and `/api/health` 200. The real test is the next time the tunnel is down (the page should show instead of Cloudflare's).

The page is an exact copy of `caddy/maintenance.html` (a dashboard Worker cannot import files), so visitors see the same page whether a container restarts or the whole origin is down; `tests/test_maintenance_page.py` fails when the copies differ. After changing the page, paste the Worker again.

### Published images

`publish-images.yml` runs when release-please publishes a release, or by hand (Actions → Publish images → Run workflow, with an existing tag) to retry. It waits for CI to pass on the released commit, builds `halallens-api` and `halallens-ui` natively for amd64 and arm64, runs the container and Caddy smoke tests, scans with Trivy (fails on fixable CRITICAL findings; HIGH and unfixed CRITICAL are listed in the run summary; reviewed exceptions go in `.trivyignore` with a reason and expiry), then pushes `vX.Y.Z-amd64` and `vX.Y.Z-arm64`, joins them into `vX.Y.Z`, and moves `latest` only for the newest release. A version tag that already exists is never overwritten.

- GHCR (`ghcr.io/<owner>/halallens-*`) needs no setup. New packages start private: make each one public once under the repository's Packages → Package settings (the HalalLens packages already allow anonymous pulls).
- Docker Hub needs the repository variable `DOCKERHUB_NAMESPACE` (account name) and the secret `DOCKERHUB_TOKEN` (an access token with Read & Write) in the `publish` environment, which only `main` and `v*` tags may use. Without them only GHCR is published.

### Images and volume ownership

One Python image (`api.Dockerfile`) runs every Python role: the API by default, and preflight, migrations and both schedulers through the commands in the compose files. It runs as the unprivileged user `10001:10001` and can write only to `cache/`, `downloads/`, `logs/`, `logs_runtime/` and `/tmp`. New named volumes mounted there take that ownership automatically. A volume created by an older image that ran as root keeps root ownership; fix it once with `docker run --rm --user 0 -v <volume>:/v halal-lens-api chown -R 10001:10001 /v`. The development compose file bind-mounts the working tree and runs these services as root on purpose.

### Exposing the site: Caddy TLS or Cloudflare Tunnel

`docker-compose-prod.yml` serves the dashboard at `/` and the API under `/api/` on `HALAL_APP_DOMAIN`. Pick one way in:

- **TLS (default, `CADDY_MODE=tls`):** point the domain's DNS at the host, open ports 80 and 443, set `ACME_EMAIL`. Caddy gets the certificates.
- **Cloudflare Tunnel (`CADDY_MODE=tunnel`):** no open web ports and no certificates on the host; the domain's DNS must be on Cloudflare.
  1. Cloudflare Zero Trust → Networks → Tunnels → create a `cloudflared` tunnel; copy its token.
  2. Add a public hostname: the domain (e.g. `halallens.in`), service `http://caddy:80`.
  3. In `.env`: `CADDY_MODE=tunnel`, `CADDY_SITE_ADDRESS=:80`, `CADDY_BIND=127.0.0.1`, `COMPOSE_PROFILES=tunnel`, `CLOUDFLARE_TUNNEL_TOKEN=<token>`.
  4. `docker compose -f docker-compose-prod.yml up -d`; the tunnel shows as Healthy in the dashboard.
  5. Keep the host's firewall (e.g. the OCI security list) closed to 80/443: the API trusts Cloudflare's `Cf-Connecting-Ip` in this mode, so Caddy must be reachable only through the tunnel.

## 2. Schema migrations

1. Pull latest `main`.
2. Apply any new files in `database/migrations/` in chronological order. `scripts/run_migrations.sh` does this and records applied files in `schema_migrations` (set `DATABASE_URL`, or `POSTGRES_*`). A single file can also be applied with `psql -h <host> -U <user> -d <db> -f database/migrations/<timestamp>_<name>.sql`.
3. Restart the API if columns changed.

Never skip migrations; the backend expects the schema to match.

## 3. Ingestion/backfill operations

### Scheduled ingestion

- Run `pipenv run python -m jobs.schedule_ingestion` as a service (systemd, supervisor, container).  
- Environment variables: `INGESTION_INTERVAL_MINUTES`, `OPS_*` for alerts.
- Logs: `logs/scheduler/<Year>/<Month>/scheduler.log`.
- Metrics: `logs/metrics/ingestion_metrics.jsonl`.
- Recommended cadence: hourly. During volatile earnings seasons drop to 15 minutes temporarily, then revert to hourly once filings clear. Watch `/ops/metrics` for consecutive failures.

### Manual backfill

To ingest a date range:

```bash
pipenv run python -m jobs.ingest_bse --from-date 20251009 --to-date 20251009 --save-cache
```

`--save-cache` stores raw JSON in `cache/` for audits; clean it when finished.

**Evaluations.** For filings with no evaluation yet use `jobs.precompute_evaluations` (the scheduled path; it selects them directly). `jobs.backfill_evaluations` without flags also skips filings that already have ratios, but it reads a window of the newest filings with evaluated rows first (`--limit`, default 500), so it can miss them. To repair evaluations computed by older ratio logic, use the recompute mode: `python -m jobs.backfill_evaluations --recompute --report dry_run.csv` (dry run), then `--recompute --report write_run.csv --write` (a new report name each run; an existing file is refused). It re-evaluates rows that already have ratios from the **current** stored inputs (snapshot, current governance overrides for receivables, liquid assets and non-halal income) and the stored market caps passed unchanged to the engine. It never calls the vendor or Bhavcopy, keeps `needs-review` for open quality issues (it does not detect or resolve anomalies), and skips rows with no stored market cap. It is not a replay of an earlier dry run: the `--write` run re-reads the database. The CSV is evidence, not a backup: take a `pg_dump` of `filing_evaluations` first; each write commits on its own, so a failure mid-run leaves earlier rows written. Restart every API worker afterwards (narration caches are per process).

## 4. Logs & monitoring

- Files reside under `logs/<component>/<Year>/<MonthName>/component.log`. Rotations include the date suffix.
- Example: `tail -f logs/api/2025/December/api.log`
- Ship logs to S3/Vector via your preferred agent; prune older months with `find logs -type f -mtime +90 -delete`.
- Ops notifications: configure `OPS_SMTP_*`, `OPS_EMAIL_*`, and/or `OPS_SLACK_WEBHOOK`. Failures produce “ERROR” emails/Slack messages with tracebacks; recoveries emit “INFO” alerts. Set `OPS_EVENT_HISTORY` (default 40) to control how many recent alert records are retained/returned by the API.
- Metrics (JSONL) can be ingested by Promtail/Vector for dashboards (success/failure counts, duration). The API also aggregates these into `GET /ops/metrics`, which surfaces the most recent ingestion runs, market-data alert history, and LLM narration failures—ideal for Grafana tables/cards without scraping raw files.
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
        - targets: [<host>]
          labels:
            __path__: /home/halal/logs/metrics/ingestion_metrics.jsonl
            job: halallens-ingestion
    ```

## 5. Manual data quality review

- Use the dashboard “Feedback queue” to triage reports. Reviewers add notes and mark entries resolved (see README).
- If you need to suppress a filing temporarily, set `verdict=null` in `filing_evaluations` and re-run the ingestion/backfill for that symbol once corrections exist.
- Record manual overrides/notes in `feedback_reports.review_notes` to keep an audit trail.
- For AAOIFI-specific fixes (receivables/liquid/non-halal income), leverage the “Governance overrides” card in the dashboard or call `/governance/overrides` via API. Overrides live in the `governance_overrides` table and are applied before ratios execute.

## 6. Realtime symbol lookups (Indian API fallback)

- Populate `INDIAN_API_BASE_URL` and `INDIAN_API_KEY` in `.env`. Without these the API can only rely on cached BSE filings.
- When a user hits `GET /filings/{symbol}?refresh=true` and no local filing exists, FastAPI will:
  1. Grab company metadata + financial statements from the Indian Stock Market API.
  2. Persist the synthetic filing to `announcements`, `financial_snapshots`, `market_data_snapshots`, and `indianapi_snapshots`.
  3. Immediately compute AAOIFI ratios so subsequent `/filings/{symbol}` calls read from Postgres like any other entry.
- You can verify the persistence by running:

  ```bash
  curl -H "Authorization: Bearer <paid-session-token>" "http://<api-host>:8001/filings/TCS?refresh=true"
  psql -X -U $POSTGRES_USER -d $POSTGRES_DB -c \
      "SELECT symbol, filing_date, confidence FROM announcements ORDER BY filing_date DESC LIMIT 3;"
  ```

- Failures are logged under `logs/api/YYYY/Month/api.log` with the prefix `Indian API snapshot`. Re-run the refresh request once the upstream API recovers or you adjust the API key/rate limits.

## 7. Disaster recovery

- **Postgres**: snapshot nightly (pg_dump or managed backup).  
- **Filing PDFs** (S3-compatible bucket, Cloudflare R2 in production): copy the bucket elsewhere with rclone; PDFs can also be re-downloaded from BSE by re-running ingestion.  
- **Cache/downloads**: not critical—rebuildable by re-running ingestion.  
- **.env** / secrets: store in a secure vault and version them with change history.
- **Log retention**: rotate monthly via the existing folder structure. Prune anything >90 days unless compliance demands longer (`find logs -type f -mtime +90 -delete`). Archive `logs/metrics/*.jsonl` after importing into your dashboarding stack.

## 8. Backfills & secret rotation runbook

### Running historical backfills

1. Decide the date range (BSE is noisy; keep batches ≤ 2 weeks). Example:

   ```bash
   pipenv run python -m jobs.ingest_bse --from-date 20241101 --to-date 20241107 --save-cache
   pipenv run python -m jobs.precompute_evaluations --lookback-days 30   # evaluate filings that still need one
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

## 9. Troubleshooting checklist

- `GET /health` returns `{"status": "ok"}` – verifies FastAPI + DB connectivity.  
- Scheduler heartbeat: check `/tmp/ingestion_heartbeat.txt` timestamp (or your custom path).  
- Persistent Indian API failures: inspect `logs/market_data/` and consider adjusting API rate limits, refreshing the key, or falling back to Bhavcopy-only mode temporarily.  
- `preflight` fails with an LLM endpoint error: the LLM endpoint is unreachable while `NARRATOR_MODE=llm`. Fix the endpoint or set `NARRATOR_MODE=rule_based`. Narration errors fall back to the rule-based narrator and show up in `/ops/metrics`.
- Feedback queue empty but users reported issues: check `logs/api/.../api.log` for errors around `/feedback` endpoints.

## 10. Mobile app notes

- `halallens-mobile/` is a Flutter **platform scaffold only**: it has no `lib/` Dart source and cannot build. There is no mobile client to operate.
- The API still accepts the `halallens://auth/login` redirect on `/auth/google/start` for a future app.
