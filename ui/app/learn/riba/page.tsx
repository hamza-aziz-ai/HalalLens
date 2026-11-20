"use client";
import SiteHeader from "@/components/site-header";
import SiteFooter from "@/components/site-footer";

import Link from "next/link";

const cardClass =
  "rounded-xl border border-line bg-surface p-8 shadow-sm";

export default function RibaGuide() {
  return (
    <>
    <SiteHeader />
    <main className="px-4 py-12 text-fg">
      <div className="mx-auto flex max-w-4xl flex-col gap-8">
        <header className={`${cardClass} animate-fade-up`}>
          <div className="flex items-center justify-between text-xs uppercase tracking-[0.2em] text-brand">
            <span>Guide</span>
            <Link href="/learn" className="text-brand hover:underline">
              Back to Learn
            </Link>
          </div>
          <h1 className="mt-5 text-3xl font-semibold text-fg">
            What is Riba?
          </h1>
          <p className="mt-3 text-base text-muted">
            Riba refers to unjust or exploitative gains in a transaction. It is
            broadly understood as any guaranteed increase on a loan or debt,
            regardless of risk or outcome.
          </p>
        </header>

        <section className={`${cardClass} animate-fade-up animate-delay-150`}>
          <h2 className="text-xl font-semibold text-fg">
            Why is riba prohibited?
          </h2>
          <p className="mt-3 text-sm text-muted">
            Islamic finance emphasizes shared risk, fair exchange, and real
            economic activity. Guaranteed returns on debt can concentrate wealth
            without productive contribution, which conflicts with these
            principles.
          </p>
          <p className="mt-3 text-sm text-muted">
            Avoiding riba also protects against predatory lending and financial
            practices that can harm vulnerable communities.
          </p>
        </section>

        <section className={`${cardClass} animate-fade-up animate-delay-150`}>
          <h2 className="text-xl font-semibold text-fg">
            Common forms of riba
          </h2>
          <ul className="mt-3 space-y-3 text-sm text-muted">
            <li>
              <span className="font-semibold text-fg">
                Interest-bearing loans:
              </span>{" "}
              Any loan where the borrower must repay more than the principal.
            </li>
            <li>
              <span className="font-semibold text-fg">
                Late payment penalties:
              </span>{" "}
              Charges that increase debt solely due to time.
            </li>
            <li>
              <span className="font-semibold text-fg">
                Guaranteed returns:
              </span>{" "}
              Investments that promise fixed yield regardless of performance.
            </li>
          </ul>
        </section>

        <section className={`${cardClass} animate-fade-up animate-delay-150`}>
          <h2 className="text-xl font-semibold text-fg">
            How it appears in public companies
          </h2>
          <p className="mt-3 text-sm text-muted">
            Companies may earn interest income, hold interest-bearing assets, or
            rely on debt financing. The AAOIFI screens quantify these exposures
            so investors can assess compliance in a consistent way.
          </p>
        </section>
      </div>
    </main>
    <SiteFooter />
    </>
  );
}
