# Ingestion Pipeline

This document explains how to run the HalalLens ingestion stack locally: applying the Postgres schema, seeding data via the BSE job, and verifying the new `GET /filings/recent` endpoint.

## 1. PostgreSQL schema

Ensure your Postgres instance is running (e.g., `postgresql-x64-17` on Windows). Then apply the schema:

```bash
psql -h <db-host> -U $POSTGRES_USER -d <db> -f database/schema.sql   # fresh DB; or run scripts/run_migrations.sh
```

Confirm tables exist:

```bash
psql -h <db-host> -U $POSTGRES_USER -d <db> -c "\dt"
```

## 2. Ingestion job

Run the BSE ingestion CLI to fetch announcements and extract financial snapshots:

```bash
pipenv run python jobs/ingest_bse.py --from-date 20250701 --to-date 20250702 --save-cache
```

Options:
- `--save-cache`: stores raw announcements JSON under `cache/` for auditing.
- `--download-dir`, `--cache-dir`: override default directories if needed.
- `--category`: pass BSE category filters (default `-1` for all).

Successful runs will log the number of announcements inserted, snapshots stored, and processor stats.

## 3. Verify via API

With the database populated, restart the FastAPI service (`pipenv run uvicorn api.app:app --reload --port 8001`). The endpoint `GET /filings/recent?limit=20` returns recent filings (joined with any extracted snapshot metrics). Example response:

```json
[
  {
    "symbol": "TCS",
    "company_name": "Tata Consultancy Services",
    "filing_date": "2024-06-30T00:00:00Z",
    "category": "Result",
    "headline": "Financial Results for Q1",
    "confidence": "HIGH",
    "total_debt": 25000000,
    "cash_equiv": 10000000,
    "revenue": 200000000,
    "interest_income": 300000,
    "dividend_income": 150000,
    "audit_status": "audited"
  }
]
```

## 4. UI hookups

The Next.js dashboard calls the API directly to render recent filings—set `NEXT_PUBLIC_HALAL_API_BASE_URL` in `ui/.env.local` to point at the backend. Components in `ui/components/` provide ratio/narration rendering; you can extend them to include a filings list that auto-populates the analyzer form.
