# DEFENSE: HalalLens screening

> **Draft by an agent** (Claude Opus 5.5, 2026-10-29), written at the maintainer's request to bring this page up to date. The field guide asks for this page in the maintainer's own words: read it, rewrite what you would say differently, then remove this note.

**What it does (2 sentences):** For a BSE-listed company's filing, HalalLens computes five financial ratios against configured caps and says `compliant`, `non-compliant` or `insufficient-data`, with a plain-English explanation. It is a screen to help a user decide, not a fatwa.

**How it works (flow):** filings and market caps enter through the crawler, ETL and market-data resolver; the numbers go into `ratio_engine`, which is the only place a verdict is decided; the API stores and returns the verdict, adds `needs-review` when a data-quality issue is open, and the narrator explains it. The explanation is rule-based by default; for conclusive verdicts it can come from an LLM (`gpt-oss:120b-cloud` through Ollama, temperature 0) behind a best-effort guard, falling back to the rules. Paid plans are one-time Razorpay purchases recorded as grants. See [FLOW.md](../FLOW.md) and [ARCHITECTURE.md](../ARCHITECTURE.md).

**Key decisions and why X over Y:**
- Three states, not a boolean: unknown is not a failure (D-001, ALTERNATIVES).
- All five ratios required: never a false pass; narrowing is a scholar's decision (D-002).
- Exact decimals, no tolerance: borderline cases are exactly where users look (D-003).
- Optional LLM text is best-effort: a model can echo the right label with contradicting text, so the label comes from the engine, doubtful text falls back to rules, and the UI marks LLM text as AI-generated (D-010, D-022).
- Access is a ledger, not a renewal date: each purchase is a grant laid end to end, so switching or extending never discards paid time and a refund removes only its own purchase (D-024).
- Refunds are scoped to the payment they refund, and a reconciler settles what the webhook missed and refunds duplicates automatically, with test keys only for now (D-025).
- Continuous Delivery, not Continuous Deployment: every release is built, tested and scanned automatically, but production changes only when I approve a deploy (D-018).

**Data structures and why:** one `filing_evaluations` row per `(symbol, filing_date)` with `is_compliant` nullable, a `verdict` text and ratios as JSONB; inputs in `financial_snapshots`, overridable by admin-only `governance_overrides`. Billing: `subscription_grants` is the source of truth for access and `users.plan` is a projection written in the same transaction; refunds are one row per refund in `payment_refunds`. See [DATA.md](../DATA.md).

**How a malicious actor could abuse it:** send booleans, NaN or tiny strings to `/halal-score` to fake a pass; forge or replay a payment webhook; race two checkouts or refund a second payment to gain time or revoke someone's plan; abuse admin overrides to change every user's verdict; feed a crafted filing; use a session to burn vendor quota. Controls and honest gaps are in [THREAT.md](../THREAT.md).

**Where it fails and how we notice:** BSE blocks the production server, so no new filings are stored; most filings may be `insufficient-data` because interest and dividend are rarely extracted; stored rows stay stale until recomputed; the rate limiter is per process; a missed payment webhook waits for the reconciler. We notice through `/ops/metrics`, ops alerts, `missing_inputs` in responses, the uptime workflow (`/api/health` and the billing heartbeat), and the reconciler's "webhook was missed" alerts. When the app or the server is down, visitors see a maintenance page instead of an error. See [FAILURE.md](../FAILURE.md).

**What I would change with more time:** get a permitted data source for filings (written permission or a licensed feed); extract interest and dividend income and stop the regex treating "interest income" as prohibited income; map `liquid_assets` from the right line instead of "current assets"; build the admin-confirmed line-item mapping (D-023); verify or drop the 67%/49% gates with a scholar; move the rate limiter to Redis before running more than one API worker; decide when to enable automatic refunds with live keys.

**Whiteboard drill:** answer the 12 questions in the field guide out loud with no notes; 10 confident answers means Lane B ready.
