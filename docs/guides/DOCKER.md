# Docker pilot

The Compose stacks, the published images and where operations live. Back to the [README](../../README.md).

`docker-compose.yml` runs `preflight`, `api` (port 8001), `ui` (port 3001), and the `ingestion` and `evaluation` schedulers against an **external** Postgres and MinIO. `docker-compose-prod.yml` adds Caddy for TLS and a bundled Postgres, stores filing PDFs in an external S3-compatible bucket (Cloudflare R2 by default; MinIO no longer publishes free images), and serves everything on one domain (`HALAL_APP_DOMAIN`): the dashboard at `/` and the API under `/api/` (Swagger at `/api/docs`). In production, register `https://<domain>/api/auth/google/callback` with Google and `https://<domain>/api/webhooks/razorpay` with Razorpay. Caddy either serves the domain itself with Let's Encrypt (`CADDY_MODE=tls`) or sits behind a Cloudflare Tunnel with no open web ports (`CADDY_MODE=tunnel`, used for `halallens.in`); see `README_ops.md`.

```bash
cp .env.example .env     # set POSTGRES_*, MINIO_*, INDIAN_API_*, NEXT_PUBLIC_HALAL_API_BASE_URL, ...
docker compose up --build
```

Published images: every release publishes `halallens-api` and `halallens-ui` for linux/amd64 and linux/arm64 to GHCR (`ghcr.io/hamza-aziz-ai/halallens-api`, `...-ui`) and, when configured, Docker Hub, tagged `vX.Y.Z` (and `latest` for the newest release). See `.github/workflows/publish-images.yml`.

Operations (logs, metrics, backups, secret rotation, troubleshooting): [`README_ops.md`](../../README_ops.md). Ingestion CLI: [`README_ingestion.md`](../../README_ingestion.md).

> **Before deploying a new verdict engine** to a database that already holds evaluations, read [`docs/ROLLBACK.md`](../ROLLBACK.md) and [`docs/HANDOVER.md`](../HANDOVER.md): stored evaluations keep their old verdicts until they are recomputed.
