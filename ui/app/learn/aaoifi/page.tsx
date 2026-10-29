"use client";

import Link from "next/link";

const cardClass =
  "rounded-3xl border border-white/10 bg-white/5 p-8 shadow-[0_25px_80px_rgba(3,7,18,0.5)] backdrop-blur";

export default function AaoifiGuide() {
  return (
    <main className="min-h-screen bg-[#05070d] bg-[image:radial-gradient(1200px_circle_at_10%_-10%,rgba(14,116,144,0.35),transparent_45%),radial-gradient(900px_circle_at_85%_0%,rgba(16,185,129,0.18),transparent_40%)] px-4 py-12 text-slate-100">
      <div className="mx-auto flex max-w-4xl flex-col gap-8">
        <header className={`${cardClass} animate-fade-up`}>
          <div className="flex items-center justify-between text-xs uppercase tracking-[0.2em] text-cyan-300/80">
            <span>Guide</span>
            <Link href="/learn" className="text-cyan-200 hover:text-cyan-100">
              Back to Learn
            </Link>
          </div>
          <h1 className="mt-5 text-3xl font-semibold text-white">
            AAOIFI screening overview
          </h1>
          <p className="mt-3 text-base text-slate-300">
            The AAOIFI standards provide a widely used framework for screening
            equities based on financial ratios. The goal is to reduce exposure
            to interest-based income and excessive leverage.
          </p>
        </header>

        <section className={`${cardClass} animate-fade-up animate-delay-150`}>
          <h2 className="text-xl font-semibold text-white">
            What the screens cover
          </h2>
          <ul className="mt-3 space-y-3 text-sm text-slate-300">
            <li>
              <span className="font-semibold text-white">
                Debt exposure:
              </span>{" "}
              Limits how much of the company is funded through interest-bearing
              liabilities.
            </li>
            <li>
              <span className="font-semibold text-white">
                Cash and liquid assets:
              </span>{" "}
              Caps how much of the balance sheet sits in interest-bearing or
              liquid instruments.
            </li>
            <li>
              <span className="font-semibold text-white">
                Receivables:
              </span>{" "}
              Ensures that a company is not primarily a receivables-financing
              business.
            </li>
            <li>
              <span className="font-semibold text-white">
                Non-permissible income:
              </span>{" "}
              Keeps revenue from impermissible activities below a small
              threshold.
            </li>
          </ul>
        </section>

        <section className={`${cardClass} animate-fade-up animate-delay-150`}>
          <h2 className="text-xl font-semibold text-white">
            Governance and cleansing
          </h2>
          <p className="mt-3 text-sm text-slate-300">
            AAOIFI recommends that any non-permissible income be purified by
            donating the proportional amount. HalalLens highlights those values
            so users can quantify the cleansing requirement.
          </p>
        </section>
      </div>
    </main>
  );
}
