"use client";

import Link from "next/link";

const cardClass =
  "rounded-3xl border border-white/10 bg-white/5 p-8 shadow-[0_25px_80px_rgba(3,7,18,0.5)] backdrop-blur";

export default function RibaGuide() {
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
            What is Riba?
          </h1>
          <p className="mt-3 text-base text-slate-300">
            Riba refers to unjust or exploitative gains in a transaction. It is
            broadly understood as any guaranteed increase on a loan or debt,
            regardless of risk or outcome.
          </p>
        </header>

        <section className={`${cardClass} animate-fade-up animate-delay-150`}>
          <h2 className="text-xl font-semibold text-white">
            Why is riba prohibited?
          </h2>
          <p className="mt-3 text-sm text-slate-300">
            Islamic finance emphasizes shared risk, fair exchange, and real
            economic activity. Guaranteed returns on debt can concentrate wealth
            without productive contribution, which conflicts with these
            principles.
          </p>
          <p className="mt-3 text-sm text-slate-300">
            Avoiding riba also protects against predatory lending and financial
            practices that can harm vulnerable communities.
          </p>
        </section>

        <section className={`${cardClass} animate-fade-up animate-delay-150`}>
          <h2 className="text-xl font-semibold text-white">
            Common forms of riba
          </h2>
          <ul className="mt-3 space-y-3 text-sm text-slate-300">
            <li>
              <span className="font-semibold text-white">
                Interest-bearing loans:
              </span>{" "}
              Any loan where the borrower must repay more than the principal.
            </li>
            <li>
              <span className="font-semibold text-white">
                Late payment penalties:
              </span>{" "}
              Charges that increase debt solely due to time.
            </li>
            <li>
              <span className="font-semibold text-white">
                Guaranteed returns:
              </span>{" "}
              Investments that promise fixed yield regardless of performance.
            </li>
          </ul>
        </section>

        <section className={`${cardClass} animate-fade-up animate-delay-150`}>
          <h2 className="text-xl font-semibold text-white">
            How it appears in public companies
          </h2>
          <p className="mt-3 text-sm text-slate-300">
            Companies may earn interest income, hold interest-bearing assets, or
            rely on debt financing. The AAOIFI screens quantify these exposures
            so investors can assess compliance in a consistent way.
          </p>
        </section>
      </div>
    </main>
  );
}
