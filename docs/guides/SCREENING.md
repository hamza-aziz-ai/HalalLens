# Screening method

What HalalLens screens today, how the engine decides a verdict, and the known limitations in full. Back to the [README](../../README.md).

## What it does

| Area                   | What exists today                                                                                                                                                                                                                                                                                   |
|------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Screening**          | `ratio_engine/` computes five ratios per filing and returns one verdict: `compliant`, `non-compliant` or `insufficient-data`.                                                                                                                                                                       |
| **Explain-Why**        | Rule-based by default. An optional LLM narrator (`NARRATOR_MODE=llm`; production uses `gpt-oss:120b-cloud` through a signed-in Ollama daemon, D-022) is used only for conclusive verdicts and only if its text passes a best-effort consistency check; the badge and ratio table always show the engine's verdict. Unknown results are always narrated by the rule-based narrator. |
| **Alerts**             | Watchlists in Postgres (D-019) and a compliance-flip engine; email delivery through SMTP. `/alerts/check` (paid) reads the stored verdict of the newest filing and checks only the caller's watchlist; concurrent checks send at most one alert (see [Known limitations](#known-limitations)).              |
| **Filings ingestion**  | BSE announcements crawler (blocked from the production server, so production holds no filings yet), PDF capture in an S3-compatible bucket (MinIO locally, R2 in production), Camelot tables plus XBRL/JSON parsing, Indian Stock API and Bhavcopy market data.                                                                                                                                                                  |
| **API + UI**           | FastAPI service (`/docs` lists every route) and a Next.js 16 static-export dashboard.                                                                                                                                                                                                               |
| **Accounts + billing** | Email-first sign-up and Google SSO, hashed opaque session tokens, one-time Razorpay purchases on a ledger of grants (D-024) with idempotent webhooks, trials and a payment reconciler (D-025).                                                                                                                                                                                      |

Not built: GCC or mutual-fund coverage, NSE crawling (`crawler/nse_ann.py` exists but nothing calls it), RAG/vLLM serving, SES/Celery alert delivery, and the Flutter app's Dart source (`halallens-mobile/` is a platform scaffold with no `lib/`, so it cannot build).

## How the screen decides

For each filing the engine computes five ratios and compares each against a configured cap:

| Ratio                             | Cap | Basis                                                           |
|-----------------------------------|-----|-----------------------------------------------------------------|
| Total debt / market cap           | 30% | AAOIFI SS21 (uses *total* debt, not only interest-bearing)      |
| Cash and equivalents / market cap | 30% | AAOIFI SS21 (uses all cash, not only interest-bearing deposits) |
| Non-permissible income / revenue  | 5%  | AAOIFI SS21                                                     |
| Accounts receivable / market cap  | 67% | **not backed by SS21**, kept as configured                      |
| Liquid assets / market cap        | 49% | **not backed by SS21**, kept as configured                      |

Verdict rule (`ratio_engine/engine.py`, one place; nothing else re-derives it):

- **`non-compliant`**: any ratio computed from valid inputs fails. A failure is conclusive even if other inputs are missing.
- **`compliant`**: all five ratios were computed from valid inputs and all passed. Prohibited income needs its base figure, interest income and dividend income to all be known (an explicit `0` counts); an unknown part is never assumed zero.
- **`insufficient-data`**: anything else. This is *not* a failure. `is_compliant` is `null` in the API and the UI shows "Insufficient data".

`needs-review` is an API-level overlay for filings with open data-quality issues; it is also stored and returned with `is_compliant = null`.

Arithmetic is exact (Decimal, no tolerance): 0.30000000000000004 over a 0.30 cap fails. Inputs must be finite numbers within float range; booleans, NaN/inf, negatives and underflowing strings are treated as unknown.

## Known limitations

- **Methodology.** The receivables (67%) and liquid-assets (49%) market-cap gates are not backed by AAOIFI SS21 but are required for `compliant`. Debt and cash use total balances, not only interest-bearing ones.
- **Income inputs are weak evidence.** The PDF extractor's prohibited-income regex also matches "interest income"; the vendor maps "Other, Net" to the base; vendor interest is net; governance overrides carry no declared contract. Interest and dividend figures are rarely extracted, so many filings screen as `insufficient-data`.
- **Stored evaluations can be stale.** Evaluations computed by an older engine keep their verdicts until recomputed: run `python -m jobs.backfill_evaluations --recompute --report dry_run.csv` (dry run), then `--recompute --report write_run.csv --write` (a new report name each run; an existing file is refused). It uses the current stored inputs and stored market caps, never calls the vendor, and `--write` requires the report.
- **Watchlists live in Postgres** (`watchlist_entries`, D-019). Re-adding a symbol keeps its baseline; a flip is detected with conditional updates, so concurrent `/alerts/check` calls send at most one alert per flip. Run one worker anyway (`API_WORKERS=1`, the compose default) while the rate limiter is per-process. Alerts fire only when a user calls `/alerts/check` (no scheduled job does), and email is best-effort.
- `etl/financial_data_processor.py` maps `liquid_assets` from "current assets" (the `_detect_scale` substring bug was fixed in #158).
- `market_data/indian_api.py` maps "Other, Net" to `non_halal_income` (the payload cache keeps successes only for 6 hours since #156).
- The rate limiter is per process (see above).
