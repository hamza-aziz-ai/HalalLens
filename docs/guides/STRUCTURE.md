# Repository structure

What each top-level folder holds, and the module map. Back to the [README](../../README.md).

```
api/              FastAPI app (api/app.py), security, mailer, billing grant fold, Razorpay client
alerts/           watchlist storage and flip observation, alert-email sender (scheduler step)
caddy/            maintenance page served by the front Caddy
cloudflare/       maintenance Worker for when the origin is down
config/           environment helpers and logging config
crawler/          BSE announcements fetcher (NSE fetcher exists, unused)
database/         schema.sql, database manager, dated migrations/
Documentations/   charter PDF and planning notes
docs/             handover, decisions, architecture, threat and failure notes
etl/              financial data processor and MinIO client
evaluation/       shared publication overlay: anomaly detector, needs-review masking policy
halallens-mobile/ Flutter platform scaffold (no Dart source)
jobs/             ingestion, evaluation, backup, payment reconciler and scheduler entry points
market_data/      Indian Stock API and Bhavcopy resolution
monitoring/       ops notifier and metrics
narrator/         rule-based narrator and optional best-effort LLM narrator
ratio_engine/     ratio math, verdict, summary, amount coercion
scripts/          run_migrations.sh, deploy.sh, CI smoke tests and helpers
tests/            pytest suite
tools/            preflight, probes, metrics inspector, load test
ui/               Next.js 16 dashboard (static export) and jest tests
utils/            date parsing helpers
```

## Module map

```mermaid
flowchart TD
    Crawler["`BSE crawler`"] -->|"`announcements`"| ETL["`Financial data processor`"]
    ETL --> DB[("`Postgres + object storage`")]
    Market["`Indian Stock API / Bhavcopy`"] --> DB
    DB --> Engine["`Ratio engine: the only verdict`"]
    Engine --> Overlay["`Publication overlay (evaluation/): needs-review while an issue is open`"]
    Overlay -->|"`filing_evaluations`"| DB
    Engine --> Narrator["`Rule-based narrator, optional LLM`"]
    Narrator --> API["`FastAPI`"]
    Overlay --> API
    DB --> Alerts["`Alerts: flip observation and subscriber emails`"]
    Alerts --> API
    Jobs["`Jobs: ingestion, evaluation and alert schedulers`"] --> Overlay
    Jobs --> Alerts
    API --> UI["`Next.js dashboard`"]
```

Deeper maps: [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md), [`docs/FLOW.md`](../FLOW.md), [`Documentations/dependency-map.md`](../../Documentations/dependency-map.md).
