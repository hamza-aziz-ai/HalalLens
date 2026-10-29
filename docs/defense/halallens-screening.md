# DEFENSE: HalalLens screening

## What HalalLens Does

HalalLens helps users check whether a BSE-listed company meets Islamic financial screening criteria by calculating five financial ratios against predefined thresholds and returning one of three results: `compliant`, `non-compliant`, or `insufficient-data`, along with an explanation in plain English. It's designed to help people make informed investment decisions, not to replace a scholar's judgment or issue a fatwa.

## How It Works

The process starts with collecting company filings and market-cap data through the crawler, ETL pipeline, and market-data resolver. Once the data is ready, it goes to `ratio_engine`, which is the only component responsible for deciding the verdict.

The API then saves and returns the result. If there's an unresolved data-quality issue, it also adds a `needs-review` flag so users know the result may need another look.

For explanations, I kept things simple and reliable. By default, HalalLens uses rule-based explanations. For conclusive results, it can optionally use an LLM (`gpt-oss:120b-cloud` via Ollama, with temperature set to 0) to generate more natural explanations. Since LLMs can sometimes contradict themselves, there's a guard in place that falls back to the rule-based explanation when the AI-generated text looks questionable. The guard is best-effort: a paraphrase it doesn't recognise can still slip through, which is why the verdict itself always comes from `ratio_engine`.

For payments, I use Razorpay. Paid plans are one-time purchases, and each purchase creates an access grant rather than a recurring subscription.

More details are available in [FLOW.md](../FLOW.md) and [ARCHITECTURE.md](../ARCHITECTURE.md).

## Key Design Decisions

A few decisions shaped how I built the system:

- **Three possible results instead of just true or false (D-001):** I didn't want missing data to automatically mean a company had failed the screening. Sometimes the correct answer is simply that there isn't enough information to decide.

- **All five ratios must be available (D-002):** I'd rather return `insufficient-data` than incorrectly tell someone a company is compliant. Deciding whether fewer ratios are acceptable is something I'd leave to a qualified scholar.

- **Exact decimal calculations with no tolerance (D-003):** Small differences matter, especially when a company is right at the threshold. I wanted the calculations to be precise and predictable.

- **AI explains the result but never decides it (D-010, D-022):** Even when an LLM produces an explanation, the actual verdict always comes from `ratio_engine`. If the explanation seems inconsistent, the system falls back to its predefined rules. AI-generated explanations are also clearly labeled in the UI.

- **Purchase-based access instead of a single renewal date (D-024):** Each payment creates its own access grant. These grants are applied one after another, which means upgrading or extending a plan doesn't waste time someone has already paid for. If a payment is refunded, only the access associated with that purchase is removed.

- **Payment-specific refunds and reconciliation (D-025):** Refunds are tied to their original payments. I also built a reconciler to handle missed webhooks and automatically refund duplicate payments. For now, everything runs with Razorpay test keys.

- **Continuous Delivery rather than Continuous Deployment (D-018):** Builds, tests, and security scans happen automatically, but I deliberately kept production deployment as a manual approval step. I want to review what goes live rather than having every successful build automatically reach production.

## Data Structures

I kept the data model focused on separating financial inputs, screening results, and billing.

Each company filing gets one record in `filing_evaluations`, uniquely identified by `(symbol, filing_date)`. The record stores the verdict, a nullable `is_compliant` field, and the calculated ratios in JSONB format.

The original financial inputs live in `financial_snapshots`. If something needs correcting, an administrator can apply an override through `governance_overrides` without changing the underlying source data.

For billing, `subscription_grants` is the source of truth for user access. The `users.plan` field is just a convenient representation of that access, updated in the same database transaction to keep everything consistent. Refunds are stored separately in `payment_refunds`, with one record per refund.

The full schema is documented in [DATA.md](../DATA.md).

## Security Risks I Considered

I also looked at how someone might deliberately misuse the system.

For example, an attacker could try sending unusual inputs like booleans, `NaN`, or number strings that underflow (such as `"1e-400"`) to `/halal-score` in an attempt to trick the API into returning a compliant result.

Payments introduce their own risks. Someone could forge or replay a Razorpay webhook, start two checkouts at nearly the same time, or manipulate refunds to get extra access or interfere with another user's plan.

Admin overrides are particularly sensitive because changing financial inputs could affect the verdict shown to every user. Crafted filing content and abusive API sessions are also concerns, especially when they could consume paid vendor resources.

I've documented the controls I've implemented, along with the risks that still need work, in [THREAT.md](../THREAT.md).

## Known Limitations and How I Monitor Them

The biggest limitation right now is data availability.

BSE blocks requests from the production server, which means the crawler can't reliably fetch and store new filings. Even when filings are available, extracting the required financial information isn't always straightforward. Interest income and dividend income, in particular, are often missing, so many evaluations may end up as `insufficient-data`.

There are a few operational limitations as well. Previously stored results don't automatically update when inputs change. The rate limiter works per process, so it won't provide a shared limit across multiple API workers. And if a payment webhook is missed, the system has to wait for the reconciler to detect and resolve it.

To catch problems, I use `/ops/metrics`, operational alerts, the `missing_inputs` field in API responses, and an uptime workflow that checks `/api/health` and the billing heartbeat. The reconciler also raises alerts when it discovers a missed webhook.

If the application or server becomes unavailable, visitors see a maintenance page rather than a raw error.

These scenarios are covered in [FAILURE.md](../FAILURE.md).

## What I'd Improve With More Time

My first priority would be fixing the data pipeline. I'd work on getting a reliable, permitted source of BSE filings, either through written permission or a licensed provider.

Next, I'd improve financial data extraction. Right now, interest and dividend income aren't consistently captured, and the regex-based approach can incorrectly interpret "interest income" as prohibited income. I'd also fix the mapping for `liquid_assets`, which currently relies on current assets rather than the correct balance-sheet line item.

Another important improvement would be building the admin-confirmed line-item mapping workflow described in D-023, so questionable mappings can be reviewed before they affect screening results.

On the screening side, I'd want a qualified scholar to validate the 67% and 49% thresholds. If those rules aren't justified, I'd remove or revise them rather than keep them just because they're already implemented.

For scalability, I'd move rate limiting to Redis before running multiple API workers.

Finally, I'd decide when it's appropriate to enable automatic refunds using Razorpay live keys, after validating the payment and reconciliation flows thoroughly.

## Whiteboard Preparation

Before considering myself ready for Lane B, I want to be able to explain the system without relying on documentation.

The plan is to go through all 12 questions in the field guide out loud, without notes. If I can confidently answer at least 10, I'll consider myself ready.

The goal isn't just to remember how the code works. It's to be able to explain **why I made these decisions, what trade-offs I accepted, where the system can fail, and what I'd improve next.**
