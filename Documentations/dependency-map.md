# Halal-Lens Dependency Map

This map covers the development stack in `docker-compose.yml` (five services) and its three external dependencies. `docker-compose-prod.yml` also bundles Postgres and adds `migrations`, `caddy`, `backup`, `billing-reconcile`, and the optional `cloudflared` and `ollama` services (see `docs/guides/DOCKER.md` and `README_ops.md`).

| Component | Purpose | Depends on | Health Probe |
|-----------|---------|------------|--------------|
| `preflight` helper | Runs once before the rest of the stack to confirm external infra is reachable. | PostgreSQL, MinIO, and an LLM/Ollama endpoint **only if** narrator mode is `llm`. | `tools/preflight.py` exits non-zero when any dependency is unreachable. Compose keeps the rest of the stack stopped. |
| `api` service | FastAPI app that powers the public HTTP interface and narrations. | PostgreSQL, MinIO (for PDFs). Narration is rule-based by default; an LLM is called only when `NARRATOR_MODE=llm`. | Docker health-check hits `http://api:8001/health` via `tools/http_probe.py`. |
| `ui` service | Next.js static export served by Caddy on port 3000 (exposed as 3001 in compose). | Starts after the API is healthy. | Docker health-check runs `wget --spider http://127.0.0.1:3000/`. |
| `ingestion` scheduler | Hourly ingestion of BSE filings and Bhavcopy market data. | PostgreSQL, MinIO; starts after the API is healthy (no HTTP calls to it). | Health probe `python -m jobs.ingestion_health` verifies the heartbeat file is updated within twice the scheduler interval. |
| `evaluation` scheduler | Evaluates filings that have no evaluation yet (`jobs.precompute_evaluations`), every `EVALUATION_INTERVAL_MINUTES` (default 15). | PostgreSQL; starts after the API is healthy. | Health probe `python -m jobs.evaluation_health` checks its heartbeat file. |
| `mobile` app | Flutter platform scaffold only (no Dart source, cannot build). | n/a | n/a |
| PostgreSQL (external) | Stores filings, ratios, watchlists, accounts and billing. | n/a | Checked by `tools/preflight.py`. |
| MinIO (external) | Holds cached PDFs (Cloudflare R2 in production). | n/a | Checked by `tools/preflight.py`. |
| LLM / Ollama (external) | Optional: generates best-effort Explain-Why text for conclusive verdicts when `NARRATOR_MODE=llm`. | n/a | Checked by `tools/preflight.py` only in `llm` mode. |

## Operational Guidance

1. Configure the `.env` file with the correct connection info for PostgreSQL, MinIO and the LLM endpoint.
2. Run `docker compose up --build` (omit `-d`) so Docker can stop the stack if any health check fails. The `preflight` service must finish successfully before the API starts; the UI and both schedulers wait for a healthy API.
3. If a service health check fails, Docker marks it as unhealthy and restarts it. Use `docker compose logs <service>` to view the error – logs now use a consistent `%(asctime)s %(levelname)s [%(name)s] %(message)s` format (override with `LOG_FORMAT`).
4. The ingestion scheduler writes its heartbeat to `/tmp/ingestion_heartbeat.txt` (override via `INGESTION_HEARTBEAT`). The health probe fails when the heartbeat is older than twice the configured interval (`INGESTION_INTERVAL_MINUTES`), forcing Compose to restart the container.

These probes, combined with the richer logging, provide clear visibility into INFO/WARNING/ERROR/CRITICAL events across services. Use the new `tools/preflight.py` script directly if you need to validate infrastructure before touching Docker (e.g., `pipenv run python tools/preflight.py`).
