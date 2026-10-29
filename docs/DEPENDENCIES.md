# DEPENDENCIES & SECRETS LOG

Every dependency, why it is here, and who maintains it. New entries need a reason before they are added. Maintainer names are from general knowledge and **unverified**; check the package page before relying on them. Versions are pinned by hash in `Pipfile.lock` / `ui/package-lock.json`.

## Python runtime (`Pipfile [packages]`, 12)
| Package            | Why                                                | Imported by                                                                      | Note                                                                     |
|--------------------|----------------------------------------------------|----------------------------------------------------------------------------------|--------------------------------------------------------------------------|
| fastapi, uvicorn   | HTTP API and server                                | `api/`                                                                           |                                                                          |
| psycopg2-binary    | Postgres driver                                    | `database/`                                                                      |                                                                          |
| requests           | HTTP client for vendor/BSE/Razorpay-adjacent calls | `api/`, `crawler/`, `etl/`, `market_data/`, `monitoring/`, `narrator/`, `tools/` |                                                                          |
| python-dotenv      | load `.env`                                        | `config/`                                                                        |                                                                          |
| lxml               | XBRL/XML parsing                                   | `etl/`                                                                           |                                                                          |
| minio              | PDF object storage                                 | `etl/`                                                                           |                                                                          |
| pandas             | tabular handling                                   | `database/database_manager.py`, `market_data/bhavcopy.py`                        | pulls numpy; also required by camelot                                    |
| camelot-py (2.0.0) | PDF table extraction                               | `etl/financial_data_processor.py`                                                | needs only `pypdfium2`; `ghostscript` is an optional extra we do not use |
| pdfminer-six       | PDF text extraction                                | `etl/`                                                                           | declared explicitly; also brings `cryptography`                          |
| cloudscraper       | session handling for the NSE fetcher               | `crawler/nse_ann.py` only                                                        | that crawler is not called anywhere: candidate for removal               |
| fake-useragent     | rotating User-Agent                                | `crawler/nse_ann.py` only                                                        | same unused NSE fetcher: candidate for removal with cloudscraper         |

Dev: `pytest`, `pandas-stubs`, `pytest-cov` (added 2026-10-28 for the CI coverage floor; brings `coverage`), `httpx2` 2.16.0 (added 2026-10-28 for `fastapi.testclient`; starlette 1.10 deprecates `httpx` there and imports `httpx2` first; published from `github.com/pydantic/httpx2` by the httpx author).

UI: `zod` removed on 2026-10-28 (no file imported it).

## Removed on 2026-10-27 (nothing imported them)
torch (CUDA index), langchain, langchain-ollama, ollama, playwright, firecrawl-py, ghostscript, bs4. Effect: 103 -> 47 locked runtime packages, no multi-GB CUDA wheel in the images.

## Added on 2026-10-27
None. `ratio_engine/amounts.py` uses only the standard library (`decimal`, `math`).

## UI stack (`ui/package.json`, upgraded 2026-10-29)
| Package | Why | Note |
|---|---|---|
| next 16.4.2, react / react-dom 19.3.1 | dashboard framework, static export (`output: "export"`) | Upgraded together from Next 14 / React 18: Next 14.2.35 had fixable CRITICAL advisories (CVE-2026-75604, GHSA-2464-fhr4-w9xw, GHSA-2xp9-vwfh-vxw4); the runtime image never shipped Next (v0.5.2), the build stage did. Majors stay ignored by Dependabot and move together. |
| eslint 9.39.5, eslint-config-next 16.4.2 | lint (`eslint .`, flat config `ui/eslint.config.mjs`) | Next 16 removed `next lint`. ESLint 10 is not used yet (the Next plugin set targets 9). `react-hooks/set-state-in-effect` (new) is a warning for 7 existing components until they are rewritten. |
| @types/jest 29.5.14 | types for the Jest 29 tests | New: without it the test files failed `tsc` (70 errors), and Next 16's build type-checks them. |

## External services
- Cloudflare R2: filing PDF storage and Postgres backups in production (D-016), reached through the `minio` SDK's S3 API. Free tier 10 GB, free egress.
- Cloudflare Tunnel and Workers (free plan): the tunnel connects the VM; the `halallens-maintenance` Worker (`cloudflare/maintenance-worker.js`, deployed from the dashboard) serves the maintenance page when the origin is unreachable, 100,000 requests a day, fail open.
- Razorpay (Test Mode): orders, webhooks, and since D-025 the reconciler's GET calls and automatic refund POSTs (TEST keys only).
- Ollama (`ollama/ollama` image) signed in to the maintainer's ollama.com account for `gpt-oss:120b-cloud` (D-022).
- OCI Email Delivery: SMTP for sign-up, reset and ops alerts.

- GitHub Container Registry and Docker Hub: published images (D-018). Docker Hub credentials are the `DOCKERHUB_TOKEN` secret in the `publish` environment.
- Trivy (`aquasec/trivy:0.75.0` image, run in `publish-images.yml`): vulnerability scan before publishing; run as a container rather than a marketplace action to keep third-party code out of a job that holds registry credentials.

## CI actions (pinned by commit SHA)
`actions/checkout`, `actions/setup-python`, `actions/setup-node`, `gitleaks/gitleaks-action`, `dependabot/fetch-metadata`, `googleapis/release-please-action`. Dependabot keeps the SHAs fresh.

## Secrets
- Names only live in `.env.example`; values live in `.env` (untracked) and the host's secret store.
- Rotated by the maintainer after the 2026-10-21 history purge. Still to confirm by the maintainer: Razorpay test key and webhook secret, PEM key pair on all hosts, Postgres and MinIO credentials.
- Never paste a secret value into docs, PRs, commits or chat. gitleaks scans every PR.
- GitHub Actions secrets: `RELEASE_PLEASE_TOKEN` is an **environment** secret in `release` (deployment branches: `main` only), so workflows run for pull requests cannot read it; it is the maintainer's fine-grained token (this repo only, Contents + Pull requests read/write), used only by `release-please.yml`, set 2026-10-28, renew before it expires. Repository secret: `CLAUDE_CODE_OAUTH_TOKEN` (left by Claude Code's GitHub App setup on 2026-05-19; **no workflow uses it**; kept by the maintainer's choice; delete it and revoke the token before selling or handing over the repo).
