# Subscription Enablement Plan

## Current gaps blocking subscriptions

1. **No user accounts or authentication**
   - UI uses a hardcoded `demo-user` identifier; backend endpoints assume anonymous access.
   - Without login/session we cannot distinguish paying vs free users or log per-user usage.

2. **Missing subscription/billing records**
   - No `users` table, no subscription state, no payment metadata.
   - Need integration with an INR-friendly gateway (e.g., Razorpay Subscription API) plus webhook handling.

3. **No feature gating/quotas**
   - All API endpoints and UI features are open. We must define entitlements (free vs ₹50/mo) and enforce:
     - Instant symbol lookup rate limits
     - Explain-Why, governance overrides, history view, watchlist alerts

4. **Usage tracking + reporting**
   - Need per-user usage logs/counters to enforce free-tier quotas and monitor abuse.
   - Admin dashboard/report for active subscribers, renewals, failed payments.

5. **Subscription UX**
   - UI lacks sign-up, login, pricing CTA, or billing screens.
   - Need modals/forms to initiate checkout, display plan status, show remaining free lookups.

6. **Notifications & emails**
   - Should send transactional emails (welcome, payment confirmed, renewal reminder, failure) using existing SMTP plumbing.

## Implementation roadmap

1. **Authentication base**
   - Decide auth provider (self-hosted JWT vs Supabase/Auth0).
   - Create `users` table + FastAPI session middleware; update UI to support sign-in/sign-up.

2. **Billing integration**
   - Create Razorpay plan (₹50/mo) and implement checkout flow + webhook to update `subscription_status`.

3. **Entitlement enforcement**
   - Add plan checks to premium endpoints and UI components; implement daily quota counters for free tier.

4. **Usage logging & admin tools**
   - Persist usage events, expose admin dashboard listing subscribers and failed payments.

5. **Subscription UX**
   - Pricing banner, upgrade CTA, account/settings page showing plan, renewal date, usage stats.

6. **Transactional comms**
   - Hook into existing email notifier for welcome/renewal/failure alerts.

Each phase should ship with tests, doc updates, and migration scripts as needed.
