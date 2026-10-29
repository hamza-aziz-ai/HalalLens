"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import PolicyLayout, {
  policyBodyClass,
  policyCardClass,
  policyListClass,
  policyTitleClass,
} from "@/components/policy-layout";
import { fetchBillingPlans } from "@/lib/billing";
import type { BillingPlan } from "@/lib/types";

// Plan features shown to customers; admin-only capabilities are not listed.
const FEATURE_LABELS: Record<string, string> = {
  instant_lookup: "Instant symbol lookup with fresh ratios",
  explain_why: "Explain-Why narration of every verdict",
  history: "Filing history and ratio trends",
  alerts: "Watchlists with compliance-change alerts",
};

function period(plan: BillingPlan) {
  if (plan.interval_days <= 0) return "one-time payment, no renewal";
  if (plan.interval_days === 365) return "per year";
  if (plan.interval_days === 30) return "per month (30 days)";
  return `per ${plan.interval_days} days`;
}

/** Products and pricing. Prices come from the live plan catalogue (API). */
export default function ProductsPage() {
  const [plans, setPlans] = useState<BillingPlan[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchBillingPlans()
      .then((all) => setPlans(all.filter((plan) => plan.is_active !== false)))
      .catch(() => setError("Prices could not be loaded right now. Please refresh."));
  }, []);

  return (
    <PolicyLayout
      title="Products & pricing"
      subtitle="HalalLens is an online software subscription for Shariah-compliance screening of BSE-listed Indian companies."
      updatedAt="October 29, 2026"
    >
      <section className={policyCardClass}>
        <h2 className={policyTitleClass}>What you get</h2>
        <p className={`${policyBodyClass} mt-3`}>
          A web dashboard that computes AAOIFI-inspired financial ratios (debt, cash and
          interest-bearing deposits, receivables, liquid assets and non-compliant income) from
          public company data, shows a verdict of compliant, non-compliant or insufficient data, and explains it.
          Everyone can screen a company manually for free; paid plans add:
        </p>
        <ul className={`mt-3 ${policyListClass}`}>
          {Object.values(FEATURE_LABELS).map((label) => (
            <li key={label}>{label}</li>
          ))}
        </ul>
      </section>

      <section className={policyCardClass}>
        <h2 className={policyTitleClass}>Plans</h2>
        {error && <p className={`${policyBodyClass} mt-3`}>{error}</p>}
        {!plans && !error && <p className={`${policyBodyClass} mt-3`}>Loading prices…</p>}
        {plans && (
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            {plans.map((plan) => (
              <div key={plan.code} className="rounded-2xl border border-white/10 bg-white/5 p-5">
                <p className="text-sm font-semibold text-white">{plan.name}</p>
                <p className="mt-2 text-2xl font-semibold text-white">
                  ₹{plan.price_inr.toLocaleString("en-IN")}
                </p>
                <p className="text-xs text-slate-400">{period(plan)}</p>
                {plan.trial_days > 0 && (
                  <p className="mt-2 text-xs text-emerald-300">{plan.trial_days}-day free trial</p>
                )}
              </div>
            ))}
          </div>
        )}
        <p className={`${policyBodyClass} mt-4`}>
          Prices are in Indian rupees. Payments are processed securely
          by Razorpay. Access starts as soon as the payment is confirmed; nothing is shipped.{" "}
          <Link href="/login/" className="text-cyan-200 hover:text-cyan-100">
            Create an account
          </Link>{" "}
          and choose a plan on the Account page.
        </p>
      </section>

      <section className={policyCardClass}>
        <h2 className={policyTitleClass}>Important</h2>
        <ul className={`mt-3 ${policyListClass}`}>
          <li>
            HalalLens is for information and education. It is not investment advice, a research
            report, or a recommendation to buy, sell or hold any security, and it is not a fatwa.
          </li>
          <li>
            Results depend on the data available; when inputs are missing the verdict is
            &ldquo;insufficient data&rdquo;, never a guess.
          </li>
          <li>
            See the{" "}
            <Link href="/refund-policy/" className="text-cyan-200 hover:text-cyan-100">
              cancellation and refund policy
            </Link>
            ,{" "}
            <Link href="/terms/" className="text-cyan-200 hover:text-cyan-100">
              terms
            </Link>{" "}
            and{" "}
            <Link href="/privacy/" className="text-cyan-200 hover:text-cyan-100">
              privacy policy
            </Link>
            .
          </li>
        </ul>
      </section>
    </PolicyLayout>
  );
}
