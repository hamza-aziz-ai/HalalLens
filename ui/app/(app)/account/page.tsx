"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";

import type { BillingPlan, Entitlement } from "@/lib/types";
import {
  createRazorpayOrder,
  creditBreakdown,
  FEATURE_LABELS,
  fetchBillingPlans,
  fetchEntitlement,
  loadRazorpayScript,
  purchaseLabel,
  startTrial,
  verifyRazorpayPayment,
  waitForOrderSettlement,
} from "@/lib/billing";
import { logoutUser } from "@/lib/auth";
import { GoogleLinkCard } from "@/components/google-link-card";
import { AlertEmailsCard } from "@/components/alert-emails-card";
import { useAuth } from "@/providers/AuthProvider";
import { Card, PageHeader, buttonClass, eyebrowClass } from "@/components/ui";
import { isTrialEligible } from "@/lib/subscription";

export default function AccountPage() {
  const { user, refresh } = useAuth();

  const [billingPlans, setBillingPlans] = useState<BillingPlan[]>([]);
  const [billingLoading, setBillingLoading] = useState(true);
  const [billingError, setBillingError] = useState<string | null>(null);
  const [upgradeLoading, setUpgradeLoading] = useState(false);
  const [upgradeMessage, setUpgradeMessage] = useState<string | null>(null);
  const [trialLoading, setTrialLoading] = useState<string | null>(null);
  const [entitlement, setEntitlement] = useState<Entitlement | null>(null);

  const isAdmin = Boolean(user?.is_admin);
  const trialEligible = isTrialEligible(user);

  useEffect(() => {
    fetchBillingPlans()
      .then((plans) => {
        setBillingPlans(plans);
        setBillingError(null);
      })
      .catch((err) => setBillingError(err.message ?? "Unable to load plans."))
      .finally(() => setBillingLoading(false));
  }, []);

  const loadEntitlement = () =>
    fetchEntitlement()
      .then(setEntitlement)
      .catch(() => setEntitlement(null));

  useEffect(() => {
    if (!user) return;
    fetchEntitlement()
      .then(setEntitlement)
      .catch(() => setEntitlement(null));
  }, [user]);

  const formatDate = (iso: string) => new Date(iso).toLocaleDateString();
  const planName = (code: string) => billingPlans.find((p) => p.code === code)?.name ?? code;
  const running = entitlement?.segments[0] ?? null;
  const queued = entitlement?.segments.slice(1) ?? [];
  // A purchase follows the LAST paid plan (running or queued), so labels compare
  // against that one: with Annual then Starter queued, Starter is "Extend".
  const lastPaid = entitlement?.segments[entitlement.segments.length - 1] ?? null;
  const currentRank = lastPaid ? billingPlans.find((p) => p.code === lastPaid.plan_code)?.rank ?? 0 : 0;
  // While a timed plan runs, a timed purchase made now starts when the paid
  // time already bought runs out (the API's next_purchase_starts). Lifetime
  // never queues: it takes effect when paid (D-024 amendment).
  const startsLater = running?.end && entitlement ? entitlement.next_purchase_starts : null;
  const startsLaterFor = (plan: BillingPlan) => (plan.interval_days > 0 ? startsLater : null);
  // Lifetime's price after credit for unused paid time (D-030), when this user can buy it.
  const quoteFor = (plan: BillingPlan) =>
    entitlement?.lifetime_quote?.plan_code === plan.code ? entitlement.lifetime_quote : null;

  const handleUpgrade = async (plan: BillingPlan) => {
    if (!user) return;
    setUpgradeLoading(true);
    setUpgradeMessage(null);
    const planStartsLater = startsLaterFor(plan);
    try {
      await loadRazorpayScript();
      const order = await createRazorpayOrder(plan.code);
      // A price with upgrade credit is fixed by the order (D-030); the credit
      // shrinks as the current plan runs, so confirm when it moved since the preview.
      const preview = quoteFor(plan);
      if (preview && order.amount !== preview.amount) {
        const binding = {
          list_amount: order.list_amount ?? order.amount,
          credit_amount: order.credit_amount ?? 0,
          amount: order.amount,
        };
        if (!window.confirm(`Your ${plan.name} price is now ${creditBreakdown(binding)}. Continue to payment?`)) {
          setUpgradeMessage("Checkout cancelled. No money was taken.");
          return;
        }
      }

      // null: the checkout closed without its success callback.
      const paymentResult = await new Promise<{
        razorpay_payment_id: string;
        razorpay_order_id: string;
        razorpay_signature: string;
      } | null>((resolve, reject) => {
        if (!window.Razorpay) {
          reject(new Error("Razorpay script failed to load."));
          return;
        }
        const options = {
          key: order.key_id,
          amount: order.amount,
          currency: order.currency,
          order_id: order.order_id,
          name: "HalalLens",
          description: plan.name,
          handler: resolve,
          prefill: {
            email: user.email,
          },
          theme: { color: "#0f766e" }, // brand teal (--brand, light theme)
          modal: {
            // Closing the checkout ends the wait. It is not proof of a cancel:
            // a payment finished on the bank's page never calls `handler`.
            ondismiss: () => resolve(null),
          },
        };
        const razorpay = new window.Razorpay(options);
        razorpay.on("payment.failed", (response: any) => {
          // Razorpay puts the reason in error.description, not error.message.
          reject(new Error(response?.error?.description || "Payment failed. No money was taken."));
        });
        razorpay.open();
      });

      if (paymentResult) {
        await verifyRazorpayPayment({
          razorpay_order_id: paymentResult.razorpay_order_id,
          razorpay_payment_id: paymentResult.razorpay_payment_id,
          razorpay_signature: paymentResult.razorpay_signature,
        });
      } else {
        setUpgradeMessage("Checking your payment…");
        const settlement = await waitForOrderSettlement(order.order_id);
        if (settlement.status === "refund_due") {
          throw new Error(settlement.message ?? "This payment will be refunded.");
        }
        if (settlement.status !== "paid") {
          throw new Error(
            "No completed payment yet. If you did pay, your plan appears here within a few minutes; otherwise no money was taken.",
          );
        }
      }

      await refresh();
      await loadEntitlement();
      setUpgradeMessage(
        planStartsLater
          ? `Payment received. ${plan.name} starts on ${formatDate(planStartsLater)}, when your current plan ends.`
          : `Payment received. Welcome to ${plan.name}!`,
      );
    } catch (err: any) {
      setUpgradeMessage(err.message ?? "Unable to start checkout.");
    } finally {
      setUpgradeLoading(false);
    }
  };

  const handleTrial = async (plan: BillingPlan) => {
    if (!user) return;
    setTrialLoading(plan.code);
    setUpgradeMessage(null);
    try {
      await startTrial(plan.code);
      await refresh();
      await loadEntitlement();
      setUpgradeMessage(`Trial started for ${plan.name}.`);
    } catch (err: any) {
      setUpgradeMessage(err.message ?? "Unable to start trial.");
    } finally {
      setTrialLoading(null);
    }
  };

  const handleLogout = async () => {
    await logoutUser();
    await refresh();
  };

  const formatPlanPrice = (plan: BillingPlan) => {
    if (plan.interval_days <= 0) {
      return `₹${plan.price_inr} lifetime`;
    }
    if (plan.interval_days >= 365) {
      return `₹${plan.price_inr}/year`;
    }
    return `₹${plan.price_inr}/month`;
  };

  const annualSavings = (() => {
    const monthly = billingPlans.find((plan) => plan.interval_days === 30);
    const annual = billingPlans.find((plan) => plan.interval_days >= 365 && plan.interval_days > 0);
    if (!monthly || !annual) return null;
    const yearly = monthly.price_inr * 12;
    if (!yearly) return null;
    const savings = ((yearly - annual.price_inr) / yearly) * 100;
    return savings > 0 ? savings : null;
  })();

  return (
    <>
      <PageHeader
        eyebrow="Account"
        title="Account & subscription"
        description="Manage your plan, billing status, and account access."
      />

      <Card>
        <div className="flex flex-col gap-6 md:flex-row md:items-start md:justify-between">
          <div className="space-y-2">
            <h2 className="font-semibold text-fg">
              Subscription status
            </h2>
            {user ? (
              <>
                <p className="text-sm text-muted">
                  Signed in as {" "}
                  <span className="font-semibold text-fg">
                    {user.email}
                  </span>
                </p>
                <p className="text-sm text-muted">
                  Plan: {" "}
                  <span className="font-semibold capitalize text-fg">
                    {isAdmin ? "admin" : user.plan}
                  </span>{" "}
                  ({isAdmin ? "full access" : user.subscription_status})
                </p>
                {running && !isAdmin && (
                  <p className="text-xs text-muted">
                    {running.end ? `Access until ${formatDate(running.end)}` : "Lifetime access"}
                  </p>
                )}
                {!isAdmin &&
                  queued.map((segment) => (
                    <p key={segment.start} className="text-xs text-muted">
                      Then {planName(segment.plan_code)}{" "}
                      {segment.end
                        ? `from ${formatDate(segment.start)} until ${formatDate(segment.end)}`
                        : `for life from ${formatDate(segment.start)}`}
                    </p>
                  ))}
                {running?.end && !isAdmin && (
                  <p className="text-xs text-muted">
                    No automatic renewal: buy again before your access ends to continue.
                  </p>
                )}
              </>
            ) : (
              <p className="text-sm text-muted">
                Sign in to manage your subscription.
              </p>
            )}
            <p className="text-xs text-muted">
              Starter ₹50/month, Annual ₹500/year, and Lifetime ₹2000 unlock unlimited
              lookups, Explain-Why, governance overrides, and premium alerts.
            </p>
            {billingError && (
              <p className="text-xs text-danger">{billingError}</p>
            )}
            {upgradeMessage && (
              <p className="text-xs text-success">{upgradeMessage}</p>
            )}
          </div>
          <div className="w-full max-w-sm space-y-3 rounded-lg border border-line bg-surface-2 p-4">
            {user ? (
              <>
                <button
                  type="button"
                  onClick={handleLogout}
                  className={clsx(buttonClass("secondary"), "w-full")}
                >
                  Sign out
                </button>
              </>
            ) : (
              <p className="text-sm text-muted">
                Login required to manage billing.
              </p>
            )}
          </div>
        </div>
      </Card>

      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-fg">Plans</h2>
          {billingLoading && (
            <span className="text-xs text-muted">Loading…</span>
          )}
        </div>
        {billingError && <p className="text-xs text-danger">{billingError}</p>}
        <div className="grid gap-4 md:grid-cols-3">
          {billingPlans.map((plan) => {
            // An unrefunded Lifetime covers every plan (the API refuses the order).
            const isLifetimeUser = Boolean(entitlement?.purchases_blocked);
            const extendsLastPlan = lastPaid?.plan_code === plan.code;
            const planStartsLater = startsLaterFor(plan);
            const showTrial = plan.trial_days > 0 && trialEligible;
            const isAnnual = plan.interval_days >= 365 && plan.interval_days > 0;
            const quote = quoteFor(plan);
            const disableUpgrade = upgradeLoading || billingLoading || isLifetimeUser || Boolean(quote?.blocked);
            const label = purchaseLabel(plan, currentRank);
            // Presentation only: outline the plan that is running now.
            const isCurrent = !isAdmin && running?.plan_code === plan.code;
            return (
              <div
                key={plan.code}
                className={clsx(
                  "flex flex-col rounded-xl border bg-surface p-5 shadow-sm transition motion-reduce:transition-none",
                  isCurrent ? "border-brand ring-1 ring-brand/30" : "border-line hover:border-brand/40",
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className={eyebrowClass}>{isCurrent ? "Current plan" : "Plan"}</p>
                    <h3 className="mt-1 text-base font-semibold text-fg">{plan.name}</h3>
                    <p className="mt-1 font-mono text-sm tabular-nums text-fg">{formatPlanPrice(plan)}</p>
                  </div>
                  {isAnnual && annualSavings && (
                    <span className="rounded-full border border-success/30 bg-success/10 px-2 py-0.5 font-mono text-[11px] font-semibold tabular-nums text-success">
                      Save {annualSavings.toFixed(2)}%
                    </span>
                  )}
                </div>
                {plan.trial_days > 0 && (
                  <p className="mt-2 text-xs text-muted">
                    Includes 1-month trial
                  </p>
                )}
                <ul className="mt-4 flex-1 space-y-1.5 border-t border-line pt-4 text-xs text-muted">
                  {plan.features
                    .filter((feature) => FEATURE_LABELS[feature])
                    .map((feature) => (
                      <li key={feature}>• {FEATURE_LABELS[feature]}</li>
                    ))}
                </ul>
                <div className="mt-4 flex flex-col gap-2">
                  {user ? (
                    isLifetimeUser ? (
                      <p className="text-xs text-muted">
                        {plan.code === "lifetime" ? "Your plan: Lifetime." : "Lifetime covers this plan."}
                      </p>
                    ) : (
                      <>
                        {showTrial && (
                          <button
                            type="button"
                            onClick={() => handleTrial(plan)}
                            disabled={trialLoading === plan.code}
                            className={clsx(buttonClass("secondary"), "w-full")}
                          >
                            {trialLoading === plan.code
                              ? "Starting trial…"
                              : "Start 1‑month trial"}
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => handleUpgrade(plan)}
                          disabled={disableUpgrade}
                          className={clsx(buttonClass("primary"), "w-full")}
                        >
                          {label}
                        </button>
                        {quote && quote.credit_amount > 0 && (
                          <p className="text-[11px] text-muted">
                            {creditBreakdown(quote)} for your unused paid time.
                          </p>
                        )}
                        {quote?.blocked && (
                          <p className="text-[11px] text-warning">
                            Your credit covers almost all of the price, so checkout is closed: contact support to upgrade.
                          </p>
                        )}
                        {planStartsLater && (
                          <p className="text-[11px] text-muted">
                            {extendsLastPlan ? "Adds to your plan; " : ""}starts {formatDate(planStartsLater)}
                          </p>
                        )}
                      </>
                    )
                  ) : (
                    <p className="text-xs text-muted">
                      Sign in to upgrade.
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <div className="grid gap-6 md:grid-cols-2">
        <GoogleLinkCard />
        <AlertEmailsCard />
      </div>
    </>
  );
}
