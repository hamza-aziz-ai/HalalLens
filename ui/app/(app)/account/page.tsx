"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";

import type { BillingPlan, Entitlement } from "@/lib/types";
import {
  createRazorpayOrder,
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
import { useAuth } from "@/providers/AuthProvider";
import { useTheme } from "@/providers/ThemeProvider";
import { isTrialEligible } from "@/lib/subscription";

export default function AccountPage() {
  const { theme } = useTheme();
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

  const cardClass =
    theme === "dark"
      ? "rounded-[28px] border border-white/10 bg-[linear-gradient(145deg,rgba(15,23,42,0.92),rgba(8,12,20,0.95))] p-6 shadow-[0_25px_80px_rgba(3,7,18,0.55)]"
      : "rounded-[28px] border border-slate-200/70 bg-white/85 p-6 shadow-[0_20px_60px_rgba(15,23,42,0.12)]";
  const headingClass = theme === "dark" ? "text-white" : "text-slate-900";
  const mutedTextClass = theme === "dark" ? "text-slate-400" : "text-slate-500";

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
  // While a timed plan runs, a purchase made now starts when the paid time
  // already bought runs out (the API's next_purchase_starts).
  const startsLater = running?.end && entitlement ? entitlement.next_purchase_starts : null;

  const handleUpgrade = async (plan: BillingPlan) => {
    if (!user) return;
    setUpgradeLoading(true);
    setUpgradeMessage(null);
    try {
      await loadRazorpayScript();
      const order = await createRazorpayOrder(plan.code);

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
          theme: { color: "#06b6d4" },
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
        const status = await waitForOrderSettlement(order.order_id);
        if (status === "refund_due") {
          throw new Error("Lifetime access already covers your account, so this payment will be refunded.");
        }
        if (status !== "paid") {
          throw new Error(
            "No completed payment yet. If you did pay, your plan appears here within a few minutes; otherwise no money was taken.",
          );
        }
      }

      await refresh();
      await loadEntitlement();
      setUpgradeMessage(
        startsLater
          ? `Payment received. ${plan.name} starts on ${formatDate(startsLater)}, when your current plan ends.`
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
    <main className="space-y-10">
      <header className={cardClass}>
        <h1 className={clsx("text-3xl font-semibold text-display", headingClass)}>
          Account & subscription
        </h1>
        <p className={clsx("mt-2", mutedTextClass)}>
          Manage your plan, billing status, and account access.
        </p>
      </header>

      <GoogleLinkCard
        cardClass={cardClass}
        headingClass={headingClass}
        mutedTextClass={mutedTextClass}
      />

      <section className={cardClass}>
        <div className="flex flex-col gap-6 md:flex-row md:items-start md:justify-between">
          <div className="space-y-2">
            <h2 className={clsx("text-lg font-semibold", headingClass)}>
              Subscription status
            </h2>
            {user ? (
              <>
                <p className={clsx("text-sm", mutedTextClass)}>
                  Signed in as {" "}
                  <span className={clsx("font-semibold", headingClass)}>
                    {user.email}
                  </span>
                </p>
                <p className={clsx("text-sm", mutedTextClass)}>
                  Plan: {" "}
                  <span className="font-semibold capitalize">
                    {isAdmin ? "admin" : user.plan}
                  </span>{" "}
                  ({isAdmin ? "full access" : user.subscription_status})
                </p>
                {running && !isAdmin && (
                  <p className={clsx("text-xs", mutedTextClass)}>
                    {running.end ? `Access until ${formatDate(running.end)}` : "Lifetime access"}
                  </p>
                )}
                {!isAdmin &&
                  queued.map((segment) => (
                    <p key={segment.start} className={clsx("text-xs", mutedTextClass)}>
                      Then {planName(segment.plan_code)}{" "}
                      {segment.end
                        ? `from ${formatDate(segment.start)} until ${formatDate(segment.end)}`
                        : `for life from ${formatDate(segment.start)}`}
                    </p>
                  ))}
                {running?.end && !isAdmin && (
                  <p className={clsx("text-xs", mutedTextClass)}>
                    No automatic renewal: buy again before your access ends to continue.
                  </p>
                )}
              </>
            ) : (
              <p className={clsx("text-sm", mutedTextClass)}>
                Sign in to manage your subscription.
              </p>
            )}
            <p className={clsx("text-xs", mutedTextClass)}>
              Starter ₹50/month, Annual ₹500/year, and Lifetime ₹2000 unlock unlimited
              lookups, Explain-Why, governance overrides, and premium alerts.
            </p>
            {billingError && (
              <p className="text-xs text-rose-300">{billingError}</p>
            )}
            {upgradeMessage && (
              <p className="text-xs text-emerald-300">{upgradeMessage}</p>
            )}
          </div>
          <div className="w-full max-w-sm space-y-3 rounded-2xl border border-white/10 bg-white/5 p-4 shadow-inner shadow-black/10">
            {user ? (
              <>
                <button
                  type="button"
                  onClick={handleLogout}
                  className="w-full rounded-lg border border-white/20 bg-white/10 px-4 py-2 text-sm font-semibold text-white hover:bg-white/20"
                >
                  Sign out
                </button>
              </>
            ) : (
              <p className={clsx("text-sm", mutedTextClass)}>
                Login required to manage billing.
              </p>
            )}
          </div>
        </div>
      </section>

      <section className={cardClass}>
        <div className="flex items-center justify-between">
          <h2 className={clsx("text-lg font-semibold", headingClass)}>Plans</h2>
          {billingLoading && (
            <span className={clsx("text-xs", mutedTextClass)}>Loading…</span>
          )}
        </div>
        {billingError && <p className="mt-2 text-xs text-rose-300">{billingError}</p>}
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          {billingPlans.map((plan) => {
            // Lifetime active or scheduled covers every plan (the API refuses the order).
            const isLifetimeUser = Boolean(entitlement?.purchases_blocked);
            const extendsLastPlan = lastPaid?.plan_code === plan.code;
            const showTrial = plan.trial_days > 0 && trialEligible;
            const isAnnual = plan.interval_days >= 365 && plan.interval_days > 0;
            const disableUpgrade = upgradeLoading || billingLoading || isLifetimeUser;
            const label = purchaseLabel(plan, currentRank);
            return (
              <div
                key={plan.code}
                className={clsx(
                  "rounded-2xl border p-4",
                  theme === "dark"
                    ? "border-white/10 bg-white/5 text-slate-200"
                    : "border-slate-200 bg-white text-slate-700",
                )}
              >
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-base font-semibold">{plan.name}</h3>
                    <p className={clsx("text-xs", mutedTextClass)}>{formatPlanPrice(plan)}</p>
                  </div>
                  {isAnnual && annualSavings && (
                    <span className="rounded-full bg-emerald-500/15 px-2 py-1 text-[11px] font-semibold text-emerald-200">
                      Save {annualSavings.toFixed(2)}%
                    </span>
                  )}
                </div>
                {plan.trial_days > 0 && (
                  <p className={clsx("mt-2 text-xs", mutedTextClass)}>
                    Includes 1-month trial
                  </p>
                )}
                <ul className="mt-3 space-y-1 text-xs">
                  {plan.features.map((feature) => (
                    <li key={feature}>• {feature}</li>
                  ))}
                </ul>
                <div className="mt-4 flex flex-col gap-2">
                  {user ? (
                    isLifetimeUser ? (
                      <p className={clsx("text-xs", mutedTextClass)}>
                        {plan.code === "lifetime" ? "Your plan: Lifetime." : "Lifetime covers this plan."}
                      </p>
                    ) : (
                      <>
                        {showTrial && (
                          <button
                            type="button"
                            onClick={() => handleTrial(plan)}
                            disabled={trialLoading === plan.code}
                            className="w-full rounded-lg border border-amber-400/40 bg-amber-400/10 px-3 py-2 text-xs font-semibold text-amber-200 hover:bg-amber-400/20 disabled:opacity-60"
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
                          className="w-full rounded-lg bg-gradient-to-r from-cyan-400 to-emerald-400 px-3 py-2 text-xs font-semibold text-slate-950 hover:opacity-90 disabled:opacity-60"
                        >
                          {label}
                        </button>
                        {startsLater && (
                          <p className={clsx("text-[11px]", mutedTextClass)}>
                            {extendsLastPlan ? "Adds to your plan; " : ""}starts {formatDate(startsLater)}
                          </p>
                        )}
                      </>
                    )
                  ) : (
                    <p className={clsx("text-xs", mutedTextClass)}>
                      Sign in to upgrade.
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </main>
  );
}
