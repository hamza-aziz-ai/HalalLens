# Subscription Enablement Plan

> **Status (2026-10-29): partly done; the billing model is superseded by D-024 and D-025** (`docs/DECISIONS.md`): plans are one-time Razorpay purchases on a ledger of grants (`subscription_grants`), timed purchases queue behind paid time, Lifetime takes effect when paid over any timed time (D-024 amendment) and is discounted by the unused paid time (D-030), nothing renews automatically, a reconciler settles missed webhooks and refunds, and automatic refunds run under TEST keys only. Payments run against Razorpay test keys. The remaining gaps below are not built; renewal-related items do not apply while there is no auto-renewal.

## Current state

1. **User accounts + auth**
   - Email-first sign-up (D-020) and Google SSO (D-021) are live.
   - Session tokens are issued by the API and kept by the web dashboard (the mobile app has no source in this repo).

2. **Billing integration**
   - Razorpay order creation + verification endpoints exist.
   - The web dashboard exposes upgrade + 30-day trial flows for Starter/Annual and a Lifetime purchase. (The mobile app has no source in this repo.)
   - The Razorpay webhook and the reconciler record grants and refunds; `users.plan` and `subscription_status` are a projection of the grants (D-024).

3. **Feature gating**
   - Premium features (instant lookup, history, narration, watchlists and alerts) are enforced in the API and surfaced in UI copy. Governance overrides are admin-only, not a paid feature.

## Remaining gaps / enhancements

1. **Usage tracking + quotas**
   - Add per-user usage counters and free-tier quotas.
   - Provide a usage/limits UI on the web dashboard.

2. **Admin reporting**
   - Admin view of active subscribers, renewals, failed payments.
   - Exportable billing/usage summaries.

3. **Transactional messaging**
   - Emails for welcome, payment confirmation, renewal, and failures.
   - Optional in-app notifications for status changes.

4. **Plan evolution**
   - Define usage/entitlement differences beyond Starter/Annual/Lifetime if needed.
   - Regional pricing support if needed.
