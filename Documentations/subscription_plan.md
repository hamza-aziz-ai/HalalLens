# Subscription Enablement Plan

## Current state

1. **User accounts + auth**
   - Email/password login and Google SSO are live.
   - Session tokens are issued by the API and persisted in web/mobile.

2. **Billing integration**
   - Razorpay order creation + verification endpoints exist.
   - The web dashboard exposes upgrade + 1-month trial flows for Starter/Annual and a Lifetime purchase. (The mobile app has no source in this repo.)
   - Razorpay webhook handler updates subscription state.

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
