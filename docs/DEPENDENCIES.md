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

## External services
- Cloudflare R2: filing PDF storage in production (D-016), reached through the `minio` SDK's S3 API. Free tier 10 GB, free egress.

## CI actions (pinned by commit SHA)
`actions/checkout`, `actions/setup-python`, `actions/setup-node`, `gitleaks/gitleaks-action`, `dependabot/fetch-metadata`, `googleapis/release-please-action`. Dependabot keeps the SHAs fresh.

## Secrets
- Names only live in `.env.example`; values live in `.env` (untracked) and the host's secret store.
- Rotated by the maintainer after the 2026-10-21 history purge. Still to confirm by the maintainer: Razorpay test key and webhook secret, PEM key pair on all hosts, Postgres and MinIO credentials.
- Never paste a secret value into docs, PRs, commits or chat. gitleaks scans every PR.
- GitHub Actions secrets: `RELEASE_PLEASE_TOKEN` is an **environment** secret in `release` (deployment branches: `main` only), so workflows run for pull requests cannot read it; it is the maintainer's fine-grained token (this repo only, Contents + Pull requests read/write), used only by `release-please.yml`, set 2026-10-28, renew before it expires. Repository secret: `CLAUDE_CODE_OAUTH_TOKEN` (left by Claude Code's GitHub App setup on 2026-05-19; **no workflow uses it**; kept by the maintainer's choice; delete it and revoke the token before selling or handing over the repo).
