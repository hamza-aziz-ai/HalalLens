# API and security model

Route tiers, auth and billing boundaries, and rate limits. Back to the [README](../../README.md).

`/docs` (FastAPI OpenAPI) is the route reference. Every route has a tier:

| Tier              | Who                                                                                          | Routes                                                                                                                                                                                                                                                       |
|-------------------|----------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Public**        | anyone (rate limited per IP)                                                                 | `/health`, `/health/billing` (reconciler heartbeat: status and age only), `/halal-score`, `/filings/recent`, `POST /feedback`, `GET /feedback/status/{token}`, `/billing/plans`, `/auth/*`, `/webhooks/razorpay`, `/client-logs`, cached `/filings/{symbol}` |
| **Authenticated** | any signed-in user with a verified email                                                     | `/auth/me`, `/auth/logout`, `/auth/google/link/*`, `GET/PUT /account/alert-emails` (opt-out works after paid access ends), `/market-data/{symbol}`, `/billing/trial`, `/billing/entitlement`, `/billing/razorpay/*`, `/billing/cancel` |
| **Paid**          | active or trialing subscription                                                              | `/narrate`, `/watchlist*`, `/alerts/check`, `/filings/{symbol}/history`, `/filings/{symbol}?refresh=true`                                                                                                                                                    |
| **Admin**         | `is_admin` on a verified account; granted to `ADMIN_EMAILS` only when that mailbox is proven | `GET/PATCH /feedback`, `/feedback/{id}/events`, `/governance/*`, `/ingestion/stats`, `/ops/metrics`                                                                                                                                                          |

`/halal-score` and `/narrate` return `is_compliant` (`true`, `false` or `null`) and `screen_verdict` (`compliant`, `non-compliant`, `insufficient-data`). **`null` is not `false`.**

The filing routes (`/filings/recent`, `/filings/{symbol}`, `/filings/{symbol}/history`) return `verdict` and `is_compliant`; while the filing has any open data-quality issue (listed in `quality_issues`) they are `needs-review` and `null`, also when the result comes from a stored evaluation or a warm cache (D-027). If the open issues cannot be read, the route answers 503 rather than a verdict.

Boundaries worth knowing:

- Accounts are email-first (D-020): sign-up emails a link and the password is chosen there; `POST /auth/password/forgot` sends a set-password link that also verifies the email and signs out every device. Every session belongs to a verified email; an address in `ADMIN_EMAILS` becomes admin only after its mailbox is proven (sign-up link, reset link or Google). Google sign-in matches accounts by Google ID only, never by email, and needs `email_verified=true`; a different Google account is linked only from the account page, after re-entering the password, and only the session that started the link can finish it (D-021). Every Google flow is single-use, expires in 10 minutes and is bound to the browser that started it by a short-lived HttpOnly cookie, which needs the UI and API on one origin (`/api`, the production setup). Links carry the single-use token in the URL fragment; only its SHA-256 digest is stored.
- Governance overrides rewrite the inputs behind *every* user's verdict for a filing, so they are admin-only. Reviewer identity comes from the session, never the request body.
- Watchlists are keyed off the session; the `user_id` path parameter is ignored.
- `/alerts/check` takes only a symbol. The verdict is the stored evaluation of the symbol's newest filing, used only when it is conclusive and has no open quality issues; a caller-supplied `is_compliant` is ignored, and only the caller's own entries are checked or moved. Lookup failures return 503. It only observes: it never sends mail. A flip becomes a pending alert email that the evaluation scheduler sends to the subscriber's own verified address (D-031).
- `GET/PUT /account/alert-emails` reads or sets the caller's own opt-out (`{"enabled": bool}`, no other field accepted). It is authenticated rather than paid so a subscriber whose access ended can still turn the emails off.
- `/market-data` requires a session because a cache miss spends vendor quota.
- Session tokens are SHA-256 digests; passwords are PBKDF2-HMAC-SHA256 at 600k iterations (older hashes are re-hashed on next login).
- Razorpay webhooks are idempotent through the unique `(provider, event_id)` index on `payment_events`.
- Plans are one-time purchases on a ledger of grants (D-024): a timed purchase (Starter, Annual) made while paid time runs queues behind it, Lifetime takes effect when paid and overlays any timed time (a Lifetime refund reveals what remains), nothing renews, and `/billing/cancel` changes nothing (it returns the current state for old clients). Refunds touch only the payment they refund (D-025).
- Upgrading to Lifetime is discounted by the unused part of what was paid for timed plans (D-030). `GET /billing/entitlement` (authenticated, caller-scoped, `Cache-Control: no-store`) adds `lifetime_quote` (`plan_code`, `list_amount`, `credit_amount`, `amount` in paise, `blocked`, `valid_for_seconds`), a preview that is null when Lifetime is held. `POST /billing/razorpay/order` for Lifetime prices it on the server and returns the binding `amount` (charged), `list_amount`, `credit_amount` and `price_valid_until`; a payable below ₹1 answers 409 (contact support). The price holds for a payment attempt created by `price_valid_until` (Razorpay's `created_at`), even if it is captured later. A credited payment whose terms no longer hold becomes `refund_due`: `GET /billing/razorpay/order/{id}` then returns `reason` (`lifetime_held`, `price_expired` or `credit_changed`) and a buyer-facing `message`, and verify answers 409 with the same message.
- Upstream failures (Razorpay, Google) answer 503, never 502, because Cloudflare replaces an origin 502 with its own page. A failed Google sign-in redirects to `/login#error=<code>` instead of returning JSON.

Rate limits (per worker process, see the caveat):

```env
RATE_LIMIT_ENABLED=true
RATE_LIMIT_LOGIN_PER_MINUTE=10       # per IP
RATE_LIMIT_REGISTER_PER_HOUR=5       # per IP, also throttles trial farming
RATE_LIMIT_PUBLIC_PER_MINUTE=60      # per IP, /halal-score
RATE_LIMIT_METERED_PER_MINUTE=30     # per user, /narrate + /market-data + /alerts/check
RATE_LIMIT_WRITE_PER_HOUR=30         # per IP, /feedback + /client-logs
TRUST_PROXY_HEADERS=false            # true only behind a proxy you control
ALLOWED_ORIGIN_REGEX=                # opt-in; matched with fullmatch, not a prefix
```

> The limiter keeps counters in process memory, so `uvicorn --workers N` multiplies every limit by `N` and restarts reset them. Acceptable for the pilot; move `SlidingWindowRateLimiter` (`api/security.py`) to Redis before scaling out.
