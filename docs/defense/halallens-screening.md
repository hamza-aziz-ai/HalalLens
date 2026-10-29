# DEFENSE: HalalLens Screening

## What HalalLens Does

HalalLens helps people check whether companies listed on the Bombay Stock Exchange (BSE) meet Islamic financial screening criteria.

It calculates five financial ratios and compares them against predefined limits. Based on those calculations, it returns one of three results: `compliant`, `non-compliant`, or `insufficient-data`. Each result also comes with a plain-English explanation.

The idea is to give investors a clearer picture of a company's financial compliance, not to issue a fatwa or replace the judgment of a qualified Islamic scholar.

## How It Works

The process starts with collecting company filings and market-cap data. The crawler fetches the filings, the ETL pipeline processes them, and the market-data resolver provides the information needed for the calculations.

One rule I've tried to follow throughout the project is that **missing information should stay missing**. If I can't reliably identify a figure from a filing, I don't substitute something that looks close enough.

Once the inputs are ready, they go to `ratio_engine`. This is the only component allowed to calculate and decide a compliance verdict.

Whether an evaluation comes from an API request or a scheduled job, it goes through the same process before being saved. That process also checks for unresolved data-quality issues. If there is one, the result is published as `needs-review` instead of exposing the underlying verdict. This doesn't change the calculation; it prevents users from relying on a result when there's a known problem with the data.

For explanations, I use a rule-based system by default. When a result is conclusive, HalalLens can also use an LLM (`gpt-oss:120b-cloud` through Ollama, with temperature set to 0) to make the explanation easier to understand.

I didn't want the LLM making compliance decisions, though. It can produce an explanation that sounds convincing while contradicting the actual result. So I added a guard that checks the generated text and falls back to the rule-based explanation if something looks wrong.

That guard isn't perfect. An unexpected paraphrase could still get through, which is another reason the model never gets to decide the verdict itself.

I also added company watchlists for subscribers. When a stored compliance verdict changes, the evaluation scheduler can email the people watching that company, using their verified email addresses.

For payments, I use Razorpay. Paid plans are one-time purchases rather than recurring subscriptions. Each payment creates an access grant, which makes it easier to handle extensions, upgrades, and refunds without losing track of what someone has paid for.

Lifetime access starts immediately after payment. If someone already has unused paid access, that remaining value is credited toward their Lifetime purchase.

The overall flow is documented in [FLOW.md](../FLOW.md) and [ARCHITECTURE.md](../ARCHITECTURE.md).

## Key Design Decisions

Several parts of HalalLens work the way they do because of problems I encountered while building it or edge cases I wanted to handle properly.

### 1. Three results instead of a simple yes or no (D-001)

I didn't think it made sense to treat missing information as a compliance failure.

A company might meet the criteria, but if I don't have enough financial data to verify that, I shouldn't call it compliant or non-compliant.

That's why I introduced `insufficient-data` as a separate result. It makes the system more honest about what it knows.

### 2. All five ratios are required (D-002)

I chose not to give a company a compliant result unless all five required ratios can be calculated.

This does mean more results end up as `insufficient-data`, but I'd rather have that than give someone false confidence based on incomplete numbers.

Whether a screening can legitimately use fewer ratios is a decision I'd leave to a qualified scholar, not something I'd quietly assume in code.

### 3. Exact calculations without tolerance (D-003)

I use exact decimal calculations and don't add a tolerance around the thresholds.

If a company's ratio is just over the limit, the system should treat it as over the limit. I don't want rounding or an arbitrary margin to change the outcome.

These borderline cases are precisely where accuracy matters most.

### 4. AI can explain a result, but it cannot decide one (D-010, D-022)

I wanted the explanations to be understandable without making the system dependent on an LLM.

The `ratio_engine` always produces the actual verdict. The LLM only explains it.

If the generated explanation seems inconsistent with that result, HalalLens falls back to the predefined rules. I also label AI-generated explanations in the interface so users know where the text came from.

The check is best-effort, so I don't treat it as a guarantee that every misleading explanation will be caught.

### 5. Access is based on individual purchases (D-024)

Instead of storing one subscription renewal date and continuously changing it, I record each purchase as a separate access grant.

The timed grants are arranged so that extending or changing plans doesn't discard time someone has already paid for.

Refunds are also easier to reason about because each refund affects the grant associated with its original purchase.

### 6. Lifetime access starts immediately (D-024 amendment)

I found a problem with the original approach: Lifetime access could end up waiting behind an existing Annual plan.

That meant someone could pay for Lifetime today but not actually receive it until their Annual subscription expired, possibly a year later.

That wasn't the behavior I wanted.

I changed it so Lifetime takes effect as soon as the payment is completed. Any existing timed grants keep their own dates underneath it.

If the Lifetime purchase is refunded, the user's remaining timed access becomes available again.

### 7. Refunds are tied to specific payments (D-025)

Payments and refunds can become complicated when webhooks are delayed, duplicated, or missed.

To handle this, each refund is associated with the payment it belongs to. I also built a reconciler that checks for missed payment events and handles duplicate payments, including automatic refunds.

For now, this is running with Razorpay test keys. I haven't enabled the live-money refund flow yet.

### 8. Every screening result follows the same publication process (D-027)

Originally, the API checked for unresolved data-quality issues before returning a verdict, but the scheduled jobs didn't apply the same check when saving results.

That meant two parts of the system could handle the same filing differently.

I fixed this by moving publication into one shared function. It checks open data-quality issues and saves the evaluation in a single transaction.

I also use a database lock shared with the code that records those issues. This prevents a result from being published as compliant or non-compliant while a known issue is being recorded.

If the issue check fails, the API returns an error rather than potentially showing a misleading verdict.

### 9. Missing data is better than misleading data (D-028)

This was an important correction to the financial extraction process.

Some earlier mappings used numbers that weren't actually the values I needed. For example, current assets were being used as liquid assets. Prohibited income came from the market-data vendor's "Other, Net" line and from a regex that could even mistake "interest income" for prohibited income.

Those shortcuts could produce calculations that looked complete but weren't based on the right figures.

I removed them.

Now, if the extractor can't establish a value reliably, it leaves that input missing.

The trade-off is substantial: automated extraction alone currently cannot produce a `compliant` result because the prohibited-income base must come from an administrator's override.

That's restrictive, but I think it's better than claiming certainty I don't have.

### 10. Migrating PostgreSQL before end of life (D-029)

PostgreSQL 14 reaches end of life on November 12, 2026, so I moved the database to PostgreSQL 17.

The database was small enough that a dump-and-restore migration was practical. I restored the data into a new PostgreSQL 17 volume and left the old volume untouched as a rollback option.

I also added a production safeguard for migrations.

Previously, pointing the application at an empty database volume could cause it to create a fresh schema, potentially making the site appear as though all its data had disappeared.

Now production fails explicitly in that situation instead of quietly starting with an empty database.

### 11. Giving users credit when they upgrade (D-030)

I didn't want someone upgrading to Lifetime to lose the value of an Annual plan they'd already purchased.

So I added a checkout credit based on their unused eligible paid time. Instead of refunding the old purchase, the system deducts that value from the Lifetime price.

The calculation happens on the server, not in the browser. I also store the pricing details on the order and validate them again when payment arrives.

To avoid problems with stale prices, a quote holds for 15 minutes: a payment attempt started within that window keeps the quoted price, even if it completes later. I check the window with the time Razorpay records for the payment attempt.

There's another edge case here: someone could receive upgrade credit and later refund the original plan that earned them that credit.

For now, that situation triggers an alert rather than automatically revoking their Lifetime access. I'd rather investigate it than risk taking away access incorrectly.

Trials and older purchases made before the grant ledger was introduced don't qualify for upgrade credit.

### 12. Sending alerts to the actual subscribers (D-031)

The first version of the alert system wasn't particularly useful. Compliance-change emails went to one operator address, and sending depended on someone calling the alerts endpoint.

I changed that so the evaluation scheduler handles notifications and sends them to the subscribers watching each company.

The system checks that the recipient has a verified email, still has paid access, and hasn't opted out.

I also added retries and a switch to disable sending if necessary.

One limitation is that delivery is *at least once*, not exactly once. If the process crashes after sending an email but before recording it as sent, that email could be delivered again.

I accept that trade-off for now, but it's something worth improving as usage grows.

### 13. Continuous Delivery, not automatic production deployment (D-018)

I automated the build, test, and security scanning process, but I kept production deployment behind a manual approval.

That gives me a chance to review a release before it goes live.

Especially for a system that deals with financial screening and paid access, I prefer having that final checkpoint instead of deploying every successful build automatically.

## How I Structured the Data

I tried to keep the financial data, screening results, user access, and notifications separate so each part has a clear responsibility.

For screening, `filing_evaluations` stores one result per `(symbol, filing_date)`. Each record contains the verdict, a nullable `is_compliant` field, and the calculated ratios stored as JSONB.

These records are written through the shared publication process, so the data-quality checks can't be bypassed by a different writer.

The financial inputs are stored in `financial_snapshots`. If the source doesn't provide a reliable value, it remains missing.

For corrections, I use `governance_overrides`, which only administrators can modify. This lets me apply reviewed values without changing the original financial snapshot. The prohibited-income base is particularly sensitive because it can currently only be supplied through an override.

For billing, `subscription_grants` is the source of truth for access. The `users.plan` field reflects the current access state, and both are updated in the same transaction to avoid inconsistencies.

Lifetime grants take effect immediately rather than waiting behind timed grants.

Each order also stores its pricing terms, including the original price, any upgrade credit, the 15-minute quote window, and the evidence used to calculate the credit.

That makes it possible to check later why someone was charged a particular amount.

Refunds live in `payment_refunds`, with a separate row for each refund.

For watchlists, I use `watchlist_entries`. These rows also help track notifications by recording the latest observed verdict and the last verdict the subscriber was notified about.

Keeping that state with the watchlist entry means a pending notification doesn't continue existing after the watch itself is removed.

The complete data model is documented in [DATA.md](../DATA.md).

## Security Risks I've Considered

I tried to think beyond the normal user flow and look at how someone might deliberately exploit the application.

One obvious target is `/halal-score`.

An attacker might send unexpected values, such as booleans, `NaN`, or extremely small number strings like `"1e-400"`, hoping to exploit input validation or numerical conversion and get an incorrect compliant result.

The payment system has a different set of risks. Someone could try forging or replaying Razorpay webhooks, running overlapping checkouts, or manipulating refund events to obtain extra access or affect another user's subscription.

The upgrade-credit feature introduces more possibilities. For example, someone could try modifying the checkout price in their browser, paying an old discounted order much later, or refunding a purchase after using its remaining value as upgrade credit.

Notifications also need protection. I don't want someone using the watchlist system to send emails to arbitrary addresses or continuing to receive notifications after their paid access ends.

Administrator overrides are another sensitive area. Since an override can affect the financial inputs used for screening, a bad or unauthorized change could alter the verdict shown to every user. This matters even more now that the prohibited-income base depends on admin-supplied values.

I also considered malicious filing content, repeated API requests, and attempts to consume vendor quota through abusive sessions.

The controls I've implemented, along with the risks I haven't fully addressed, are documented in [THREAT.md](../THREAT.md).

## Known Limitations and How I Detect Problems

The biggest problem I still need to solve is getting reliable financial data.

BSE blocks requests from the production server, so I can't consistently fetch new filings through the existing crawler.

Even with filings available, extracting the right figures is difficult. Interest and dividend income aren't consistently identified, and the prohibited-income base isn't automatically extracted at all.

As a result, many filings return `insufficient-data`. With the current design, a filing cannot reach `compliant` through automated extraction alone; it needs an administrator-provided prohibited-income base.

I also expect more results to show `needs-review` now that unresolved data-quality issues block publication consistently across the API and scheduled jobs.

There are some operational gaps too.

Stored evaluations don't automatically refresh whenever their underlying inputs change. The API rate limiter is process-local, which means it won't enforce a shared limit if I run multiple workers. Missed payment webhooks are handled by the reconciler, but that means there can be a delay before the payment state is corrected.

Email alerts use at-least-once delivery, so duplicates are possible, and I haven't added one-click unsubscribe links yet.

To detect problems, I use several monitoring mechanisms:

- `/ops/metrics` for operational metrics and application alerts.
- `missing_inputs` in API responses to show which financial values prevented a conclusive result.
- An uptime workflow that checks `/api/health` and the billing heartbeat.
- Reconciler alerts when payment webhooks were missed.
- Credit-conflict alerts when a purchase that contributed upgrade credit is later refunded.
- Evaluation-scheduler logs and alerts showing how many notification emails succeeded or failed.

If the application or server is unavailable, visitors see a maintenance page rather than an unhandled application error.

I've documented these failure scenarios in [FAILURE.md](../FAILURE.md).

## What I'd Improve With More Time

**My first priority would be the data pipeline.**

I need a dependable and permitted way to obtain BSE filings. Ideally, that would mean getting written permission for the existing approach or moving to a licensed financial-data provider.

After that, I'd focus on improving extraction quality.

I've already removed the mappings that were making unsafe assumptions, such as treating current assets as liquid assets or misidentifying interest income as prohibited income.

That fixed one problem but exposed another: many important values are now missing.

I'd improve extraction for interest and dividend income, add proper handling of XBRL contexts and reporting periods, and review and repair older stored data affected by the previous mappings.

I'd also build the admin-confirmed line-item mapping workflow described in D-023. That would let questionable financial mappings be reviewed before their values are used in a screening result.

Another priority is validating the screening thresholds with a qualified Islamic scholar.

In particular, I'd want the 67% and 49% limits independently reviewed. If I can't justify those thresholds, I'd rather change or remove them than continue using them simply because they're already in the code.

On the infrastructure side, I'd move rate limiting to Redis before scaling beyond a single API worker.

For notifications, I'd add a one-click unsubscribe flow and improve delivery handling as the number of subscribers increases.

For billing, I'd finish validating the reconciliation and refund flows before enabling automatic refunds with live Razorpay keys.

The overall goal would be to improve reliability without weakening the safeguards I've put in place just to produce more conclusive screening results.

## Whiteboard Preparation

Before I consider myself ready for Lane B, I want to make sure I can explain the system clearly without depending on the documentation.

I'll go through the 12 questions in the field guide out loud, without notes. My target is to answer at least 10 of them confidently.

I don't just want to remember which function does what.

I want to be able to explain why I chose this architecture, what alternatives I considered, which trade-offs I made, what could go wrong, and how I'd improve the system if I had more time.

For me, being ready means understanding the decisions well enough to defend them, including the ones that didn't work out the first time.
