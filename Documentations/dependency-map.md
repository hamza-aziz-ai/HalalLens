# Halal-Lens Dependency Map

This stack consists of three first-party services plus three external dependencies.

| Component | Purpose | Depends on | Health Probe |
|-----------|---------|------------|--------------|
| `preflight` helper | Runs once before the rest of the stack to confirm external infra is reachable. | PostgreSQL, MinIO, LLM/Ollama endpoint (if narrator mode is `llm`). | `tools/preflight.py` exits non-zero when any dependency is unreachable. Compose keeps the rest of the stack stopped. |
| `api` service | FastAPI app that powers the public HTTP interface and narrations. | PostgreSQL, MinIO (for PDFs), LLM/Ollama (when `NARRATOR_MODE=llm`). | Docker health-check hits `http://api:8001/health` via `tools/http_probe.py`. |
| `ui` service | Static Next.js dashboard served by `serve`. | API health endpoint. | Docker health-check performs a GET on `http://ui:3000`. |
| `ingestion` scheduler | Hourly ingestion of BSE filings and automated evaluations. | PostgreSQL, MinIO, API (for internal calls). | Health probe `python -m jobs.ingestion_health` verifies the heartbeat file is updated within twice the scheduler interval. |
| PostgreSQL (external) | Stores filings, ratios, watchlists. | n/a | Checked by `tools/preflight.py`. |
| MinIO (external) | Holds cached PDFs. | n/a | Checked by `tools/preflight.py`. |
| LLM / Ollama (external) | Generates Explain-Why narratives when configured. | n/a | Checked by `tools/preflight.py` (socket reachability). |

## Operational Guidance

1. Configure the `.env` file with the correct connection info for PostgreSQL, MinIO and the LLM endpoint.
2. Run `docker compose up --build` (omit `-d`) so Docker can stop the stack if any health check fails. The `preflight` service must finish successfully before API/UI/ingestion start.
3. If a service health check fails, Docker marks it as unhealthy and restarts it. Use `docker compose logs <service>` to view the error – logs now use a consistent `%(asctime)s %(levelname)s [service] message` format.
4. The ingestion scheduler writes its heartbeat to `/tmp/ingestion_heartbeat.txt` (override via `INGESTION_HEARTBEAT`). The health probe fails when the heartbeat is older than twice the configured interval (`INGESTION_INTERVAL_MINUTES`), forcing Compose to restart the container.

These probes, combined with the richer logging, provide clear visibility into INFO/WARNING/ERROR/CRITICAL events across services. Use the new `tools/preflight.py` script directly if you need to validate infrastructure before touching Docker (e.g., `pipenv run python tools/preflight.py`).***
