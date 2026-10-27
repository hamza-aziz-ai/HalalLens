# DEFENSE: HalalLens screening

> **DRAFT written by Claude from the code, not by the maintainer.** The field guide's rule is that this page is yours: rewrite it in your own words, then use it for the whiteboard drill. Anything you cannot say without notes is the gap to close before shipping.

**What it does (2 sentences):** For a BSE-listed company's filing, HalalLens computes five financial ratios against configured caps and says `compliant`, `non-compliant` or `insufficient-data`, with a plain-English explanation. It is a screen to help a user decide, not a fatwa.

**How it works (flow):** filings and market caps enter through the crawler, ETL and market-data resolver; the numbers go into `ratio_engine`, which is the only place a verdict is decided; the API stores and returns the verdict and the narrator explains it deterministically. See [FLOW.md](../FLOW.md).

**Key decisions and why X over Y:**
- Three states, not a boolean: unknown is not a failure (D-001, ALTERNATIVES).
- All five ratios required: never a false pass; narrowing is a scholar's decision (D-002).
- Exact decimals, no tolerance: borderline cases are exactly where users look (D-003).
- Optional LLM text is best-effort: a model can echo the right label with contradicting text, so the label comes from the engine, doubtful text falls back to rules, and the UI marks LLM text as AI-generated (D-010).

**Data structures and why:** one `filing_evaluations` row per `(symbol, filing_date)` with `is_compliant` nullable, a `verdict` text and ratios as JSONB; inputs in `financial_snapshots`, overridable by admin-only `governance_overrides`. See [DATA.md](../DATA.md).

**How a malicious actor could abuse it:** send booleans, NaN or tiny strings to `/halal-score` to fake a pass; replay a payment webhook; abuse admin overrides to change every user's verdict; feed a crafted filing; use a paid session to burn vendor quota. Controls and honest gaps are in [THREAT.md](../THREAT.md).

**Where it fails and how we notice:** vendor/BSE outages, missing extraction (most filings may be `insufficient-data`), stale stored rows, per-process rate limiter. `/ops/metrics`, heartbeat, ops alerts, `missing_inputs` in responses. See [FAILURE.md](../FAILURE.md).

**What I would change with more time:** recompute tooling and a dry-run report (PR-B); extract interest/dividend and separate prohibited income from interest income; make `/alerts/check` server-side and per user; verify or drop the 67%/49% gates with a scholar; decide the canonical UI (Pages vs Docker).

**Whiteboard drill:** answer the 12 questions in the field guide out loud with no notes; 10 confident answers means Lane B ready.
