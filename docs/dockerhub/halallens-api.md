# HalalLens API

Backend of **HalalLens**: Shariah (AAOIFI-inspired) screening of BSE-listed Indian equities. A FastAPI service computes the five screening ratios with exact decimals and returns a verdict (`compliant`, `non-compliant` or `insufficient-data`), explains it, and sends compliance-flip alerts. The same image also runs the database migrations, the startup checks, the BSE ingestion and evaluation schedulers, the nightly PostgreSQL backup, and the Razorpay payment reconciler.

Source, docs and issues: [github.com/hamza-aziz-ai/HalalLens](https://github.com/hamza-aziz-ai/HalalLens)

## Tags

- `vX.Y.Z`: a release, for `linux/amd64` and `linux/arm64`. A published version tag is never overwritten.
- `latest`: the newest release.
- `vX.Y.Z-amd64`, `vX.Y.Z-arm64`: the single-architecture images behind each release.

The same images are on GitHub Container Registry as `ghcr.io/hamza-aziz-ai/halallens-api`.

## What is inside

- Python 3.14 on Debian slim; runs as UID 10001, never root.
- Every release is built and published by CI only after the tests pass. Before it is pushed, each image passes a smoke test and a Trivy scan that fails on fixable critical vulnerabilities. Releases carry an SBOM and build provenance.

## Running it

The image expects PostgreSQL and an S3-compatible bucket (MinIO, Cloudflare R2, ...). The supported way to run the whole stack (API, dashboard, Caddy, schedulers, backups, payment reconciler) is the Docker Compose file in the repository; see `README_ops.md` there for every setting. Configuration is environment variables only (`.env.example` lists them all), so nothing deployment-specific is baked into the image.

The role is chosen by the entrypoint: the API by default (`uvicorn api.app:app`), or `python3 -m jobs.schedule_ingestion`, `jobs.schedule_evaluations`, `jobs.backup_postgres --loop`, `jobs.reconcile_payments --loop`, `tools.preflight`, and the migration script for the other services.

## Licence

MIT. Screening results are informational, not a fatwa or investment advice.
