# HalalLens

> **See your investments through a halal lens.** Read-only Shariah-compliance screening, explainability, and alerting for Indian & GCC equities and mutual-fund schemes.

![CI](https://img.shields.io/github/actions/workflow/status/hamzaziizzz/HalalLens/ci.yml?branch=main)
![License](https://img.shields.io/github/license/hamzaziizzz/HalalLens)

---

## Key Capabilities

| Category                  | Highlights                                                                                         |
| ------------------------- | -------------------------------------------------------------------------------------------------- |
| **AAOIFI Screening**      | Ratio engine enforces 30% debt/cash caps and 5% non-permissible income thresholds per filing.      |
| **Explain-Why Narration** | Deterministic narrator converts ratios into plain English with sourcing hints for the UI.         |
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
cp .env.example .env

# 3. Install dependencies
pipenv install --dev
```

### FastAPI service

```bash
pipenv run uvicorn api.app:app --reload --port 8000
```

- `GET /health` - liveness probe
- `POST /halal-score` - compute ratios from filing + market data payloads
- `POST /narrate` - generate explain-why text from the same request
- `POST /watchlist` / `GET /watchlist/{user}` - manage compliance-watch entries
- `POST /alerts/check` - run compliance-flip alert evaluation

### Tests

```bash
pipenv run pytest
```

CI (GitHub Actions) installs the Pipenv environment and runs the same test suite on pushes and pull requests.

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
