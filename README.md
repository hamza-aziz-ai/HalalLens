# HalalLens

> **See your investments through a halal lens.** Read-only Shariah-compliance screening, explainability, and alerting for Indian & GCC equities and mutual-fund schemes.

![CI](https://img.shields.io/github/actions/workflow/status/hamzaziizzz/HalalLens/ci.yml?branch=main)
![License](https://img.shields.io/github/license/hamzaziizzz/HalalLens)

---

## Key Capabilities

| Category                  | Highlights                                                                                         |
| ------------------------- | -------------------------------------------------------------------------------------------------- |
| **AAOIFI Screening**      | Ratio engine enforces 30% debt/cash caps and 5% non-permissible income thresholds per filing.      |
| **Explain-Why Narration** | Rule-based fallback plus optional LLM-backed narrator (vLLM/OpenAI style) with JSON outputs.      |
| **Watchlists & Alerts**   | File-backed watchlists plus compliance-flip alert engine (future: Celery + SES delivery).          |
| **Filings Ingestion**     | Production-style BSE/NSE crawlers, PDF capture via MinIO, and Camelot-based ETL for key metrics.   |
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

# 2. Create env file (see Documentations/Charter for required secrets)
cp .env.local .env

# 3. Install dependencies
pipenv install --dev
```

### Narrator configuration

```bash
# defaults to rule_based
export NARRATOR_MODE=llm
export LLM_ENDPOINT=http://localhost:8001/v1/chat/completions
export LLM_MODEL=llama-3-8b-instruct
export LLM_API_KEY=local-token    # optional for self-hosted vLLM
export LLM_TEMPERATURE=0.0
export LLM_MAX_TOKENS=400
export LLM_TIMEOUT=30
```

If `NARRATOR_MODE=llm` but endpoint/model are missing, the service automatically falls back to the deterministic narrator. Set `LLM_MAX_TOKENS=0` and/or `LLM_TIMEOUT=0` if you want the model/server to decide token counts and timeouts (useful for reasoning-heavy Ollama models like DeepSeek-R1).

### Database schema

```bash
createdb halallens_dev   # if needed
psql halallens_dev -f database/schema.sql
```

### FastAPI service

```bash
pipenv run uvicorn api.app:app --reload --port 8000
```

- `GET /health` - liveness probe
- `POST /halal-score` - compute ratios from filing + market data payloads
- `POST /narrate` - generate explain-why text from the same request
- `GET /filings/{symbol}` - fetch the latest stored filing + computed ratios for a symbol
- `GET /filings/recent` - list the newest filings with AAOIFI verdict snapshots
- `GET /market-data/{symbol}` - proxy/caches Yahoo Finance market caps & share prices
- `POST /watchlist` / `GET /watchlist/{user}` - manage compliance-watch entries
- `POST /alerts/check` - run compliance-flip alert evaluation

### Tests

```bash
pipenv run pytest
```

CI (GitHub Actions) installs the Pipenv environment and runs the same test suite on pushes and pull requests.

### Next.js dashboard

```bash
cd ui
npm install          # or pnpm install
cp .env.local .env.local
npm run dev          # http://localhost:3000
```

Set `HALAL_API_BASE_URL` to the FastAPI origin (default `http://localhost:8000`). The UI proxies analysis via `/api/analysis`, fetches recent filings via `/api/filings/recent`, auto-looks up market caps/share prices via `/api/market-data` (now using the BSE `SCRIP_CD` captured in ingestion for better coverage), and surfaces `/watchlist` + `/alerts/check` so you can add symbols and see compliance-flip alerts without leaving the dashboard.

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
