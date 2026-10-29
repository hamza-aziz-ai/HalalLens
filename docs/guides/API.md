# API and security model

Route tiers, auth and billing boundaries, and rate limits. Back to the [README](../../README.md).

`/docs` (FastAPI OpenAPI) is the route reference. Every route has a tier:

| Tier              | Who                                                                                          | Routes                                                                                                                                                                                                                                                       |
|-------------------|----------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Public**        | anyone (rate limited per IP)                                                                 | `/health`, `/health/billing` (reconciler heartbeat: status and age only), `/halal-score`, `/filings/recent`, `POST /feedback`, `GET /feedback/status/{token}`, `/billing/plans`, `/auth/*`, `/webhooks/razorpay`, `/client-logs`, cached `/filings/{symbol}` |
| **Authenticated** | any signed-in user with a verified email                                                     | `/auth/me`, `/auth/logout`, `/auth/google/link/*`, `/market-data/{symbol}`, `/billing/trial`, `/billing/entitlement`, `/billing/razorpay/*`, `/billing/cancel`                                                                                               |
| **Paid**          | active or trialing subscription                                                              | `/narrate`, `/watchlist*`, `/alerts/check`, `/filings/{symbol}/history`, `/filings/{symbol}?refresh=true`                                                                                                                                                    |
| **Admin**         | `is_admin` on a verified account; granted to `ADMIN_EMAILS` only when that mailbox is proven | `GET/PATCH /feedback`, `/feedback/{id}/events`, `/governance/*`, `/ingestion/stats`, `/ops/metrics`                                                                                                                                                          |

`/halal-score` and `/narrate` return `is_compliant` (`true`, `false` or `null`) and `screen_verdict` (`compliant`, `non-compliant`, `insufficient-data`). **`null` is not `false`.**

Boundaries worth knowing:

- Accounts are email-first (D-020): sign-up emails a link and the password is chosen there; `POST /auth/password/forgot` sends a set-password link that also verifies the email and signs out every device. Every session belongs to a verified email; an address in `ADMIN_EMAILS` becomes admin only after its mailbox is proven (sign-up link, reset link or Google). Google sign-in matches accounts by Google ID only, never by email, and needs `email_verified=true`; a different Google account is linked only from the account page, after re-entering the password, and only the session that started the link can finish it (D-021). Every Google flow is single-use, expires in 10 minutes and is bound to the browser that started it by a short-lived HttpOnly cookie, which needs the UI and API on one origin (`/api`, the production setup). Links carry the single-use token in the URL fragment; only its SHA-256 digest is stored.
- Governance overrides rewrite the inputs behind *every* user's verdict for a filing, so they are admin-only. Reviewer identity comes from the session, never the request body.
- Watchlists are keyed off the session; the `user_id` path parameter is ignored.
- `/alerts/check` takes only a symbol. The verdict is the stored evaluation of the symbol's newest filing, used only when it is conclusive and has no open quality issues; a caller-supplied `is_compliant` is ignored, and only the caller's own entries are checked or moved. Lookup failures return 503.
- `/market-data` requires a session because a cache miss spends vendor quota.
- Session tokens are SHA-256 digests; passwords are PBKDF2-HMAC-SHA256 at 600k iterations (older hashes are re-hashed on next login).
- Razorpay webhooks are idempotent through the unique `(provider, event_id)` index on `payment_events`.
- Plans are one-time purchases on a ledger of grants (D-024): a purchase made while paid time runs queues behind it, nothing renews, and `/billing/cancel` changes nothing (it returns the current state for old clients). Refunds touch only the payment they refund (D-025).
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
