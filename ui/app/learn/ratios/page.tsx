"use client";

import Link from "next/link";

const cardClass =
  "rounded-3xl border border-white/10 bg-white/5 p-8 shadow-[0_25px_80px_rgba(3,7,18,0.5)] backdrop-blur";

const RatioCard = ({
  title,
  formula,
  threshold,
  explanation,
}: {
  title: string;
  formula: string;
  threshold: string;
  explanation: string;
}) => (
  <div className="rounded-2xl border border-white/10 bg-white/5 p-5 shadow-[0_18px_50px_rgba(3,7,18,0.35)]">
    <h3 className="text-base font-semibold text-white">{title}</h3>
    <p className="mt-2 text-xs uppercase tracking-[0.2em] text-cyan-300/80">
      Formula
    </p>
    <p className="mt-1 text-sm text-slate-200">{formula}</p>
    <p className="mt-2 text-xs uppercase tracking-[0.2em] text-cyan-300/80">
      Threshold
    </p>
    <p className="mt-1 text-sm text-slate-200">{threshold}</p>
    <p className="mt-3 text-sm text-slate-300">{explanation}</p>
  </div>
);

export default function RatioGuide() {
  return (
    <main className="min-h-screen bg-[#05070d] bg-[image:radial-gradient(1200px_circle_at_10%_-10%,rgba(14,116,144,0.35),transparent_45%),radial-gradient(900px_circle_at_85%_0%,rgba(16,185,129,0.18),transparent_40%)] px-4 py-12 text-slate-100">
      <div className="mx-auto flex max-w-5xl flex-col gap-8">
        <header className={`${cardClass} animate-fade-up`}>
          <div className="flex items-center justify-between text-xs uppercase tracking-[0.2em] text-cyan-300/80">
            <span>Guide</span>
            <Link href="/learn" className="text-cyan-200 hover:text-cyan-100">
              Back to Learn
            </Link>
          </div>
          <h1 className="mt-5 text-3xl font-semibold text-white">
            Ratio explanations
          </h1>
          <p className="mt-3 text-base text-slate-300">
            These ratios match the AAOIFI screening rules used in HalalLens. We
            compute them using the latest available filing and market data.
          </p>
        </header>

        <section className="grid gap-6 md:grid-cols-2">
          <RatioCard
            title="Debt to Market Cap"
            formula="Total debt / Market capitalization"
            threshold="<= 30%"
            explanation="Measures leverage relative to market value. Higher values imply excessive reliance on debt."
          />
          <RatioCard
            title="Cash to Market Cap"
            formula="Cash + cash equivalents / Market capitalization"
            threshold="<= 30%"
            explanation="Limits interest-bearing cash exposure relative to company value."
          />
          <RatioCard
            title="Receivables to Market Cap"
            formula="Accounts receivable / Market capitalization"
            threshold="<= 67%"
            explanation="Ensures the company is not primarily a receivables-driven business."
          />
          <RatioCard
            title="Liquid Assets to Market Cap"
            formula="Liquid assets / Market capitalization"
            threshold="<= 49%"
            explanation="Controls exposure to liquid, potentially interest-bearing assets."
          />
          <RatioCard
            title="Non-permissible Income Ratio"
            formula="Non-permissible income / Total revenue"
            threshold="<= 5%"
            explanation="Keeps impermissible income below a minimal threshold."
          />
        </section>

        <section className={`${cardClass} animate-fade-up animate-delay-150`}>
          <h2 className="text-xl font-semibold text-white">Notes</h2>
          <p className="mt-3 text-sm text-slate-300">
            If a metric is missing, HalalLens shows the ratio as unavailable and
            prompts for manual input. When multiple sources exist, we prioritize
            verified filings, then structured data, and finally manual overrides.
          </p>
        </section>
      </div>
    </main>
  );
}
