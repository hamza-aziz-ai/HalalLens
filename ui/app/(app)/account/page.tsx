"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";

import type { BillingPlan } from "@/lib/types";
import {
  createRazorpayOrder,
  fetchBillingPlans,
  loadRazorpayScript,
  verifyRazorpayPayment,
} from "@/lib/billing";
import { logoutUser } from "@/lib/auth";
import { useAuth } from "@/providers/AuthProvider";
import { useTheme } from "@/providers/ThemeProvider";

export default function AccountPage() {
  const { theme } = useTheme();
  const { user, refresh } = useAuth();

  const [billingPlans, setBillingPlans] = useState<BillingPlan[]>([]);
  const [billingLoading, setBillingLoading] = useState(false);
  const [billingError, setBillingError] = useState<string | null>(null);
  const [upgradeLoading, setUpgradeLoading] = useState(false);
  const [upgradeMessage, setUpgradeMessage] = useState<string | null>(null);

  const isAdmin = Boolean(user?.is_admin);
  const hasPaidAccess = Boolean(
    user &&
      (isAdmin ||
        (user.plan !== "free" &&
          ["active", "trialing"].includes(user.subscription_status))),
  );

  const cardClass =
    theme === "dark"
      ? "rounded-[28px] border border-white/10 bg-[linear-gradient(145deg,rgba(15,23,42,0.92),rgba(8,12,20,0.95))] p-6 shadow-[0_25px_80px_rgba(3,7,18,0.55)]"
      : "rounded-[28px] border border-slate-200/70 bg-white/85 p-6 shadow-[0_20px_60px_rgba(15,23,42,0.12)]";
  const headingClass = theme === "dark" ? "text-white" : "text-slate-900";
  const mutedTextClass = theme === "dark" ? "text-slate-400" : "text-slate-500";

  useEffect(() => {
    setBillingLoading(true);
    fetchBillingPlans()
      .then((plans) => {
        setBillingPlans(plans);
        setBillingError(null);
      })
      .catch((err) => setBillingError(err.message ?? "Unable to load plans."))
      .finally(() => setBillingLoading(false));
  }, []);

  const handleUpgrade = async () => {
    if (!user) return;
    setUpgradeLoading(true);
    setUpgradeMessage(null);
    try {
      const plan =
        billingPlans.find((item) => item.code === "starter") ??
        billingPlans.find((item) => item.is_active);
      if (!plan) {
        throw new Error("Billing plan not available.");
      }
      await loadRazorpayScript();
      const order = await createRazorpayOrder(plan.code);

      const paymentResult = await new Promise<{
        razorpay_payment_id: string;
        razorpay_order_id: string;
        razorpay_signature: string;
      }>((resolve, reject) => {
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
        };
        const razorpay = new window.Razorpay(options);
        razorpay.on("payment.failed", (response: any) => {
          reject(response.error || new Error("Payment failed."));
        });
        razorpay.open();
      });

      await verifyRazorpayPayment({
        razorpay_order_id: paymentResult.razorpay_order_id,
        razorpay_payment_id: paymentResult.razorpay_payment_id,
        razorpay_signature: paymentResult.razorpay_signature,
      });

      await refresh();
      setUpgradeMessage("Subscription activated. Welcome to Starter!");
    } catch (err: any) {
      setUpgradeMessage(err.message ?? "Unable to start checkout.");
    } finally {
      setUpgradeLoading(false);
    }
  };

  const handleLogout = async () => {
    await logoutUser();
    await refresh();
  };

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
                {user.subscription_renewal && !isAdmin && (
                  <p className={clsx("text-xs", mutedTextClass)}>
                    Renewal on {new Date(user.subscription_renewal).toLocaleDateString()}
                  </p>
                )}
              </>
            ) : (
              <p className={clsx("text-sm", mutedTextClass)}>
                Sign in to manage your subscription.
              </p>
            )}
            <p className={clsx("text-xs", mutedTextClass)}>
              Starter ₹50/month unlocks unlimited lookups, Explain-Why, governance
              overrides, and premium alerts.
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
                {!hasPaidAccess && (
                  <button
                    type="button"
                    onClick={handleUpgrade}
                    disabled={upgradeLoading || billingLoading}
                    className="w-full rounded-lg bg-gradient-to-r from-cyan-400 to-emerald-400 px-4 py-2 text-sm font-semibold text-slate-950 hover:opacity-90 disabled:opacity-60"
                  >
                    {upgradeLoading ? "Starting checkout…" : "Upgrade to Starter ₹50/mo"}
                  </button>
                )}
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
    </main>
  );
}
