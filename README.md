# HalalLens

> **See your investments through a halal lens.**  A privacy‑first, read‑only Shariah‑compliance screener and analytics dashboard for Indian & GCC equities and mutual‑fund schemes.

![CI](https://img.shields.io/github/actions/workflow/status/hamzaziizzz/HalalLens/ci.yml?branch=main)
![License](https://img.shields.io/github/license/hamzaziizzz/HalalLens)

---

## ✨ Key Features

| Category                  | Highlights                                                                                                     |
| ------------------------- | -------------------------------------------------------------------------------------------------------------- |
| **Shariah Screening**     | AAOIFI‑compliant ratio engine (<30 % debt, <5 % non‑permissible revenue, cash filters) with quarterly history. |
| **Explain Why Panel**     | LLM‑powered plain‑English explainer citing exact figures + PDF/XBRL page links.                                |
| **Daily Movers Board**    | Top gainers/losers for 1 d / 7 d / 30 d, halal badge & filters, export CSV (Pro).                              |
| **Performance Snapshots** | CAGR, volatility (σ), Sharpe‑lite metric, benchmark overlay.                                                   |
| **Watch‑list & Alerts**   | Compliance‑flip, price‑threshold, and news keyword triggers via email/WhatsApp/push.                           |
| **Public API**            | `/api/halal‑score?symbol=TCS` returns JSON verdict with ratios & citations.                                    |

---

## 🏗️  System Overview

```
flowchart TD
    A[Filings Crawler] -->|Nightly ETL| B[Raw Docs (S3)]
    B --> C[Financial Extractor]
    C --> D[Postgres + Timescale]
    D --> E[Shariah Screen Svc]
    E --> F[LLM Narrator API]
    E --> G[Alert Engine]
    F --> H[Next.js Front‑end]
    G --> H
```

---

## 🚀  Quick Start (Local Dev)

```bash
# 1. Clone and enter repo
$ git clone https://github.com/your‑org/HalalLens.git && cd HalalLens

# 2. Bootstrap environment
$ cp .env.example .env        # edit DB creds & API keys

# 3. Launch everything (CPU‑only)
$ docker compose up ‑d        # API: http://localhost:8000 | UI: http://localhost:3000

# 4. Seed sample data (TCS, HDFCFund)
$ make seed
```

> **GPU Inference:** If you have an NVIDIA card or DGX, add `‑‑profile gpu` to `docker compose` to enable the vLLM service.

### Production on Kubernetes (EKS)

```bash
$ helm dependency build ./deploy/charts/halallens
$ helm install halallens ./deploy/charts/halallens ‑f deploy/values‑prod.yaml
```

## 🧮  Ratio API (FastAPI)

```bash
$ pipenv install --dev  # ensure FastAPI/Uvicorn dependencies are present
$ uvicorn api.app:app --reload --port 8000
```

`GET /health` returns a simple status probe. Compute a verdict by posting to `/halal-score`, or get a plain-language explainer from `/narrate`:

```bash
curl -X POST http://localhost:8000/halal-score \
  -H 'Content-Type: application/json' \
  -d '{
        "snapshot": {
          "symbol": "TCS",
          "filing_date": "2024-06-30T00:00:00Z",
          "total_debt": 120000000,
          "cash_equiv": 45000000,
          "revenue": 500000000,
          "non_permissible_income": 1000000
        },
        "market_data": {
          "market_cap": 600000000
        }
      }'
```

The response echoes the ratios, thresholds, and pass/fail verdict so downstream services (LLM narrator, alerts) can consume the same API contract.

```bash
curl -X POST http://localhost:8000/narrate \
  -H 'Content-Type: application/json' \
  -d @payload.json
```

`/narrate` returns `summary`, `verdict`, bullet points, and lightweight citations composed from the same ratio evaluation so the UI can power the “Explain Why” panel without calling an external LLM.

### Watchlists & Alerts

```bash
# add an entry tracking compliance flips for INFY
$ curl -X POST http://localhost:8000/watchlist \
    -H 'Content-Type: application/json' \
    -d '{"user_id":"demo-user","symbol":"INFY"}'

# list entries
$ curl http://localhost:8000/watchlist/demo-user

# feed latest verdicts to trigger alerts
$ curl -X POST http://localhost:8000/alerts/check \
    -H 'Content-Type: application/json' \
    -d '{"symbol":"INFY","is_compliant":false}'
```

Alerts return lightweight JSON events (user, symbol, message) so you can plug in SES/WhatsApp delivery later; persisted watchlists live at `cache/watchlists.json` for easy cron-based processing.

## 🕒  BSE Ingestion Job

Use the orchestration script in `jobs/ingest_bse.py` to pull corporate filings, persist announcements, and extract financial snapshots:

```bash
$ pipenv run python jobs/ingest_bse.py --from-date 20250701 --to-date 20250702 --save-cache
```

Flags let you adjust categories, cache/download locations, and whether to save the raw payload. To schedule nightly runs, drop it into cron or a workflow runner, e.g.:

```
0 1 * * * cd /opt/Halal-Lens && pipenv run python jobs/ingest_bse.py --save-cache >> logs/ingestion.log 2>&1
```

This keeps `announcements` and `financial_snapshots` fresh for the `/halal-score` API.

---

## 📂  Repo Structure

```
HalalLens/
├── api/                 # FastAPI application (screening & narrator)
├── crawler/             # Playwright/Selenium based filings scrapers
├── etl/                 # PDF/XBRL parsers, data cleaners
├── ui/                  # Next.js 14 front‑end
├── charts/              # Helm charts
├── infra/terraform/     # AWS infrastructure as code
├── tests/               # PyTest & Playwright tests (≥90 % coverage)
└── README.md
```

---

## 🛠️  Tech Stack

* **Backend:** Python 3.12 · FastAPI · Pydantic v2 · pgvector
* **Inference:** vLLM · Llama‑3‑8B‑Instruct (fallback GPT‑4o)
* **Storage:** Postgres 15 (Timescale), S3/MinIO
* **Front‑end:** Next.js 14 · Tailwind CSS · shadcn/ui
* **Infra:** Docker · Helm · GitHub Actions · AWS EKS (prod) · K3d (dev)
* **Observability:** Prometheus · Grafana · Loki · Sentry

---

## 🪄  Roadmap

* [ ] NSE/BSE full‑coverage crawler
* [ ] Mutual‑fund scheme parser (AMFI)
* [ ] GCC iXBRL ingestion (Tadawul)
* [ ] Portfolio import via Zerodha Kite & Fyers
* [ ] OAuth2 social login (Apple/Google)
* [ ] Mobile PWA wrapper (Capacitor)

See [`PROJECTS`](https://github.com/hamzaziizzz/HalalLens/projects) for sprint board.

---

## 🤝  Contributing

1. Open an issue describing bug/feature.
2. Fork → feature branch (`feat/…`).
3. Run `make test && make lint`.
4. Submit PR – auto CI checks will gate merge.

We follow the [Conventional Commits](https://www.conventionalcommits.org/) spec and the [Contributor Covenant](CODE_OF_CONDUCT.md).

---

## 📜  License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for details.

---

## 🙌  Acknowledgements

* AAOIFI Shariah Standards
* NSE/BSE XBRL teams
* Llama 3 authors & the vLLM community
* Islamic finance researchers whose papers shaped our methodology
