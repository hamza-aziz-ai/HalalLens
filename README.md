# HalalLens

> **See your investments through a halal lens.** Read-only Shariah-compliance screening, explainability, and alerting for Indian & GCC equities and mutual-fund schemes.

![CI](https://img.shields.io/github/actions/workflow/status/hamzaziizzz/HalalLens/ci.yml?branch=main)
![License](https://img.shields.io/github/license/hamzaziizzz/HalalLens)

---

## Key Capabilities

| Category                  | Highlights                                                                                         |
| ------------------------- | -------------------------------------------------------------------------------------------------- |
| **AAOIFI Screening**      | Ratio engine enforces 30% debt/cash caps and 5% non-permissible income thresholds per filing.      |
| **Explain-Why Narration** | Deterministic, rule-based narration. An LLM-backed narrator (vLLM/OpenAI style) exists in `narrator/llm.py` but is **temporarily bypassed** on screening paths: its prose cannot be validated against the engine verdict. |
| **Watchlists & Alerts**   | File-backed watchlists plus compliance-flip alert engine (future: Celery + SES delivery).          |
| **Filings Ingestion**     | Production-style BSE/NSE crawlers, PDF capture via MinIO, Camelot tables **and** XBRL/JSON parsing for AAOIFI metrics. |
| **REST API**              | FastAPI service exposes `/halal-score`, `/narrate`, `/watchlist`, and `/alerts/check` endpoints.   |

---

## Architecture Snapshot

```
flowchart TD
    Crawler -->|Announcements| Cache[(Cache & Downloads)]
    Cache --> ETL[Financial Data Processor]
    ETL --> DB[(Postgres + MinIO)]
    DB --> Ratio[Ratio Engine Service]
    Ratio --> Narrator
    Ratio --> Alerts
    Narrator --> API[(FastAPI)]
    Alerts --> API
```

---

## Local Development

```bash
# 1. Clone and enter repo
git clone https://github.com/hamzaziizzz/HalalLens.git
cd HalalLens

# 2. Create env file (see Documentations/ for the project charter / required secrets)
cp .env.local .env

# 3. Install dependencies
pipenv install --dev
```

### Narrator configuration

```bash
# defaults to rule_based
export NARRATOR_MODE=llm
export LLM_ENDPOINT=http://192.168.1.9:8001/v1/chat/completions
export LLM_MODEL=llama-3-8b-instruct
export LLM_API_KEY=local-token    # optional for self-hosted vLLM
export LLM_TEMPERATURE=0.0
export LLM_MAX_TOKENS=400
export LLM_TIMEOUT=30
```

**Currently ignored for screening results:** the service logs a warning and always uses the deterministic narrator, even with `NARRATOR_MODE=llm` configured (`tools/preflight.py` still checks the endpoint in that mode, so leave `NARRATOR_MODE=rule_based` in production). If `NARRATOR_MODE=llm` but endpoint/model are missing, the service automatically falls back to the deterministic narrator. Set `LLM_MAX_TOKENS=0` and/or `LLM_TIMEOUT=0` if you want the model/server to decide token counts and timeouts (useful for reasoning-heavy Ollama models like DeepSeek-R1).

### Database schema

```bash
createdb halallens_dev   # if needed
psql halallens_dev -f database/schema.sql
# Existing databases: apply incremental migrations too
psql halallens_dev -f database/migrations/20241218_add_aaoifi_columns.sql
# Reviewer workflow columns for feedback triage
psql halallens_dev -f database/migrations/20241219_feedback_status.sql
# Governance override table for manual AAOIFI fixes
psql halallens_dev -f database/migrations/20241220_governance_overrides.sql
# Feedback tracking tokens + re-evaluation metadata
psql halallens_dev -f database/migrations/20241221_feedback_tracking.sql
# Session-token hashing + payment idempotency (see "Security model" below)
psql halallens_dev -f database/migrations/20260728_security_hardening.sql
```

> **Heads-up on `20260728_security_hardening.sql`:** it clears `user_sessions`,
> because tokens are now stored as SHA-256 digests rather than in plaintext.
> Everyone signs in again once after deployment. It also adds a unique index on
> `payment_events (provider, event_id)`; if you have duplicate rows from replayed
> webhooks the migration collapses them first.

> **Heads-up:** if you are pointing the app at an established Postgres instance, run the migration file above (or apply the equivalent `ALTER TABLE financial_snapshots ...` statements) before restarting the API. Without the `accounts_receivable`, `liquid_assets`, `non_halal_income`, and `governance_notes` columns, `/filings/recent` will fail as soon as the backend starts selecting the AAOIFI fields.
>
> Likewise, apply `20241219_feedback_status.sql` so the API/UI can store reviewer status, notes, and resolution timestamps for feedback reports. Skipping it results in `column "status" does not exist` errors as soon as the reviewer queue loads.

### FastAPI service

```bash
pipenv run uvicorn api.app:app --reload --port 8001
```

- `GET /health` - liveness probe
- `POST /halal-score` - compute ratios from filing + market data payloads
- `POST /narrate` - generate explain-why text from the same request
- `GET /filings/{symbol}` - fetch the latest stored filing + computed ratios for a symbol
- `GET /filings/recent` - list the newest filings with AAOIFI verdict snapshots
- `GET /market-data/{symbol}` - proxy/caches Indian Stock API market caps & share prices (with Bhavcopy fallback)
- `POST /watchlist` / `GET /watchlist/{user}` - manage compliance-watch entries
- `POST /alerts/check` - run compliance-flip alert evaluation
- `POST /feedback` - capture user-reported issues with filings/verdicts
- `GET /feedback` - reviewer list endpoint (filter by status/limit)
- `PATCH /feedback/{id}` - update status, reviewer, and notes
- `GET /feedback/status/{token}` - requester view: track ticket status + audit trail
- `GET /governance/overrides` - list manual overrides applied to AAOIFI metrics **(admin)**
- `PUT /governance/overrides` - create/update an override for a filing **(admin)**
- `DELETE /governance/overrides/{symbol}/{filing_date}` - remove an override (reverts to extracted values) **(admin)**
- `POST /billing/cancel` - stop auto-renewal; paid access runs to the end of the period
- `tools/metrics_inspector.py` - summarize `logs/metrics/ingestion_metrics.jsonl` (success/failure counts, durations). Helpful for quick CLI dashboards or feeding Promtail/Grafana.

### Security model

| Tier | Who | Routes |
| ---- | --- | ------ |
| **Public** | anyone (rate limited per IP) | `/health`, `/halal-score`, `/filings/recent`, `POST /feedback`, `GET /feedback/status/{token}`, `/billing/plans`, `/auth/*`, `/webhooks/razorpay` |
| **Authenticated** | any signed-in user | `/auth/me`, `/auth/logout`, `/market-data/{symbol}`, `/billing/trial`, `/billing/razorpay/*`, `/billing/cancel` |
| **Paid** | active or trialing subscription | `/narrate`, `/watchlist*`, `/alerts/check`, `/filings/{symbol}/history`, `/filings/{symbol}?refresh=true` |
| **Admin** | `is_admin`, seeded from `ADMIN_EMAILS` | `GET/PATCH /feedback`, `/feedback/{id}/events`, `/governance/*`, `/ingestion/stats`, `/ops/metrics` |

Notes on the boundaries:

- **Governance overrides are admin-only, not a paid feature.** An override rewrites
  the AAOIFI inputs behind *every* user's verdict for that filing, so it is a
  data-integrity operation. The reviewer recorded on an override and on feedback
  triage comes from the session, not from the request body.
- **Watchlists are keyed off the session**, not off the `user_id` in the path or
  body. The path parameter on `GET /watchlist/{user_id}` is retained only for URL
  compatibility and is ignored.
- **`/market-data` requires a session** because a cache miss spends the upstream
  vendor quota.
- **Session tokens are stored as SHA-256 digests.** A database dump cannot be
  replayed against the API.
- **Passwords** use PBKDF2-HMAC-SHA256 at 600k iterations, with a versioned hash
  string. Accounts created under the old 100k scheme are re-hashed transparently
  on their next successful login.
- **Google SSO returns the token in the URL fragment only** (never the query
  string, which would land in access logs and `Referer` headers), and the
  post-login redirect must match `FRONTEND_BASE_URL`'s exact scheme and host, or
  use the `halallens://` mobile scheme.

Rate limits (per worker process - see the caveat below):

```env
RATE_LIMIT_ENABLED=true
RATE_LIMIT_LOGIN_PER_MINUTE=10       # per IP
RATE_LIMIT_REGISTER_PER_HOUR=5       # per IP, also throttles trial farming
RATE_LIMIT_PUBLIC_PER_MINUTE=60      # per IP, /halal-score
RATE_LIMIT_METERED_PER_MINUTE=30     # per user, /narrate + /market-data
RATE_LIMIT_WRITE_PER_HOUR=30         # per IP, /feedback + /client-logs
TRUST_PROXY_HEADERS=false            # set true only behind Caddy/your own proxy
ALLOWED_ORIGIN_REGEX=                # opt-in; matched with fullmatch, not a prefix
```

> **Caveat:** the limiter keeps its counters in process memory, so running
> `uvicorn --workers N` multiplies every limit by `N`, and the counters reset on
> restart. That is acceptable for the pilot; move `SlidingWindowRateLimiter` in
> `api/security.py` onto Redis before scaling out horizontally.
>
> `TRUST_PROXY_HEADERS` gates whether `X-Forwarded-For` is believed for rate-limit
> identity. Leave it off unless a proxy you control strips client-supplied values,
> otherwise a caller can mint a fresh bucket per request.

### Tests

```bash
pipenv run pytest
```

CI (GitHub Actions) installs the Pipenv environment and runs the same test suite on pushes and pull requests.

### Next.js dashboard

```bash
cd ui
npm install          # or pnpm install
npm run dev          # http://192.168.1.9:3000
```

Set `NEXT_PUBLIC_HALAL_API_BASE_URL` in `ui/.env.local` to the FastAPI origin (default `http://192.168.1.9:8001`). The UI calls the API directly from the browser, fetches recent filings via `/filings/recent`, auto-looks up market caps/share prices via `/market-data`, and surfaces `/watchlist` + `/alerts/check` so you can add symbols and see compliance-flip alerts without leaving the dashboard.

Head to `http://192.168.1.9:3000/login` to register/sign in; once authenticated the dashboard lives at `/dashboard` and mirrors the same routing when deployed with Docker (`/login` + `/dashboard` behind port 3001 in the compose stack). When the Google env vars are present you’ll also see a **Continue with Google** button—the FastAPI backend exchanges the OAuth code, issues a HalalLens bearer token, and redirects back to the dashboard with the token stored in `localStorage`.

### Mobile app (Flutter)

```bash
cd halallens-mobile
flutter pub get
flutter run --dart-define=HALALLENS_API_BASE_URL=http://192.168.1.9:8001
```

Notes:
- Use a LAN-accessible API URL when testing on a physical device (avoid `localhost`).
- Optional defines:
  - `HALALLENS_API_TIMEOUT_SECONDS=12`
  - `HALALLENS_MOBILE_OAUTH_REDIRECT=halallens://auth/login`

Google SSO on mobile uses deep links. The API accepts an optional `redirect` query param on `/auth/google/start` and will return the bearer token to `halallens://auth/login?...`. Android and iOS URL schemes are already configured in the app.

### Google SSO (optional)

1. Create a Google Cloud project, configure the OAuth consent screen (External), and register a “Web application” OAuth client. Add the dashboard origin(s) as “Authorized JavaScript origins” and `https://api.example.com/auth/google/callback` (plus `http://192.168.1.9:8001/auth/google/callback` for local dev) as authorized redirect URIs.
2. Populate `.env` with:
   ```env
   GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=super-secret
   GOOGLE_REDIRECT_URI=http://192.168.1.9:8001/auth/google/callback
   FRONTEND_BASE_URL=http://192.168.1.9:3000
   ```
3. Restart the API (or `docker compose up --build`). The `/auth/google/start` endpoint now redirects to Google; after consent the API links/creates a user record (using `google_sub`) and redirects back to `/login#token=...`.

For mobile SSO, call `/auth/google/start?redirect=halallens://auth/login` so the token returns to the app.

### Reviewer workflow (feedback triage)

The dashboard now includes a “Feedback queue” card below the reporter form:

1. Analysts submit issues via the public “Report an issue” form (`POST /feedback`). The API returns a tracking token so requestors can later hit `GET /feedback/status/{token}` to see status/resolution notes.
2. Reviewers open the dashboard, scroll to “Feedback queue,” and press **Refresh** to load open reports from `GET /feedback?status=open`.
3. Each entry shows the symbol, filing date (if provided), verdict, user message, and contact details. Reviewers can type notes and click **Mark resolved**, which fires `PATCH /feedback/{id}` with `{ status: "resolved", review_notes, reviewer }`. Marking resolved optionally triggers an automatic re-evaluation of the cited filing and stores the result in the audit trail exposed to requestors.
4. The queue reloads automatically so only outstanding tickets remain, and you can set tickets to `in_review` when triaging.

All reviewer actions are stored in the `feedback_reports` table (columns added in `20241219_feedback_status.sql` plus `20241221_feedback_tracking.sql`). The same audit log powers the requester-facing status endpoint, so analysts can see when their ticket moved to `in_review`, when it was resolved, and whether a re-check was executed.

## Docker pilot deployment

The repository ships Dockerfiles for both the FastAPI backend and the Next.js dashboard plus a `docker-compose.yml` that stands up PostgreSQL, API, and UI together.

1. Copy `.env` to the project root (or create one) with your existing PostgreSQL connection details plus the Indian Stock Market API credentials, e.g.:
   ```env
   POSTGRES_HOST=host.docker.internal   # or the LAN IP of your DB server
   POSTGRES_DB=halallens
   POSTGRES_USER=halallens
   POSTGRES_PASSWORD=supersecret
   INDIAN_API_BASE_URL=https://api.indianstocks.local/v1   # provided by your vendor
   INDIAN_API_KEY=supersecret-api-key
   GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=super-secret
   GOOGLE_REDIRECT_URI=http://api:8001/auth/google/callback
   FRONTEND_BASE_URL=http://192.168.1.9:3000
   NEXT_PUBLIC_HALAL_API_BASE_URL=http://api:8001
   ```
   If you run Docker on native Linux, `host.docker.internal` is provided via the `extra_hosts` entry in `docker-compose.yml`; you can also set `POSTGRES_HOST` to the IP/hostname of your Postgres instance explicitly.
2. Build and start the API + UI containers (they will connect to your existing Postgres):
   ```bash
   docker compose up --build
   ```
3. Visit:
   - API docs: http://192.168.1.9:8001/docs
   - Dashboard: http://192.168.1.9:3001 (already wired to the containerized API)

The compose stack persists Postgres data in the `postgres_data` volume. Stop with `docker compose down` (add `-v` to drop the volume between runs).

### Operations handbook

| Topic | Checklist |
| ----- | --------- |
| **Logs & retention** | All components respect `HALAL_LOG_ROOT` and follow `logs/<component>/<Year>/<Month>/<component>.log` rotation (daily rollovers, max 31 per folder). Compress/ship these to centralized storage (e.g., S3, Vector) and prune old months via `find logs -type f -mtime +90 -delete`. |
| **Secrets** | Store DB credentials, SMTP keys, Indian API keys, and LLM tokens in `.env` or your orchestrator’s secret manager. Never bake them into Docker images. If rotating passwords, update `.env`, run the relevant migration (if schema changed), then restart containers (`docker compose up -d --no-deps api ingestion`). |
| **Migrations** | Every schema change lands in `database/migrations/`. Apply them in chronological order: `psql -f database/migrations/<timestamp>.sql`. For Docker pilots, run the migration on the external Postgres first (from the host or a psql container) *before* redeploying. |
| **Backfill jobs** | Use `pipenv run python -m jobs.backfill_evaluations --from-date YYYYMMDD --to-date YYYYMMDD` to recompute ratios for historical filings after logic tweaks. For bulk ingestion, schedule `jobs.schedule_ingestion` or run `jobs.ingest_bse` manually with `--save-cache`. Documented examples live in `README_ingestion.md`. |
| **Cache dirs** | `cache/` stores raw announcements (JSON) and extracted financial data. `downloads/` holds temporary PDFs before uploading to MinIO. Clean them periodically (`rm -rf cache/* downloads/*`) once data lands in MinIO/Postgres. |
| **Manual overrides** | When heuristics misread filings (e.g., TCS non-halal income), use the dashboard “Governance overrides” card or the `/governance/overrides` API to upsert corrected metrics. Overrides are stored in `governance_overrides` and surfaced in filings responses. |
| **Log formats** | Each entry uses weekday + 12‑hour timestamp: `Thursday 19-12-2025 07:15:00 PM INFO [component] message`. This matches the operator request for readability. |

### Logging

#### Ops alerting & metrics

To receive email/Slack alerts whenever the ingestion scheduler fails (or when it recovers after consecutive failures), set the following environment variables before launching the scheduler or Docker stack:

```
OPS_SMTP_HOST=smtp.example.com
OPS_SMTP_PORT=587
OPS_SMTP_USERNAME=apikey
OPS_SMTP_PASSWORD=secret
OPS_EMAIL_SENDER=halallens-bot@example.com
OPS_EMAIL_RECIPIENT=ops@example.com
OPS_SLACK_WEBHOOK=https://hooks.slack.com/services/XXX/YYY/ZZZ   # optional
```

Alerts include the component name, severity, and traceback. Either email or Slack is optional—configure whichever channels you use.

The scheduler also writes run metrics to `logs/metrics/ingestion_metrics.jsonl` (override with `INGESTION_METRICS_PATH`). Each line is JSON with `status`, start/end timestamps, and duration seconds; point your observability stack at that file or ship it via Filebeat/Vector to build dashboards of success/failure ratios.

#### Viewing logs in Docker

Mount the `logs/` directory into your host (compose already does this) and inspect per component:

```bash
# API logs for December 2025
tail -f logs/api/2025/December/api.log

# Scheduler logs (and rotations) in the same folder structure
tail -f logs/scheduler/2025/December/scheduler.log
```

Rotations (`*.log.19-12-2025`) can be zipped or shipped off-line via cronjobs. `docker logs` still mirrors stdout for quick debugging, but the filesystem hierarchy is the canonical audit trail.

### Ingestion scheduler

To run BSE ingestion on an interval (default hourly):

```bash
pipenv run python -m jobs.schedule_ingestion
```

This simply loops over `jobs.ingest_bse` and logs success/failure timestamps. For production, map it to a systemd service, Windows Task Scheduler, or any cron-like runner. You can change the interval by editing `SLEEP_MINUTES` in `jobs/schedule_ingestion.py`.

### Alert delivery (email)

Configure SMTP credentials (optional) to deliver compliance flips via email:

```
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=apikey
SMTP_PASSWORD=secret
ALERT_EMAIL_SENDER=alerts@example.com
ALERT_EMAIL_RECIPIENT=team@example.com
```

When set, `/alerts/check` automatically emits emails in addition to returning the alert payload.

---

## Repository Structure

```
HalalLens/
|- api/                 # FastAPI application wiring ratio engine, narrator, alerts
|- alerts/              # Watchlist storage and alert evaluation
|- config/              # Environment variable helpers
|- crawler/             # BSE/NSE announcement fetchers
|- database/            # Postgres manager for announcements & financial snapshots
|- Documentations/      # Charter + project tracker
|- etl/                 # Financial data processor and MinIO client
|- jobs/                # CLI ingestion job tying crawler + ETL + DB
|- narrator/            # Deterministic explain-why narration engine
|- ratio_engine/        # AAOIFI-style ratio calculations and models
|- ui/                  # Next.js 14 dashboard (search + explain-why)
|- tests/               # Pytest coverage for ratio engine, narrator, alerts
|- usage_example.py     # Sample end-to-end ingestion usage
```

---

## Roadmap Highlights

- Harden NSE/BSE ingestion (retry logic, scheduling) and add MF/GCC sources.
- Add Postgres schema/migrations plus automated data-quality checks.
- Stand up vLLM narrator service + RAG pipeline for Explain-Why panel.
- Build the Next.js dashboard (search, movers, watchlists) and connect alerts to SES.
- Instrument Prometheus/Grafana and ship production-ready Helm charts.

Track granular sprint tasks in `Documentations/HalalLens-Project-Tracker.xlsx`.
