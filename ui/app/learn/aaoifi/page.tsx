"use client";
import SiteHeader from "@/components/site-header";
import SiteFooter from "@/components/site-footer";

import Link from "next/link";

const cardClass =
  "rounded-xl border border-line bg-surface p-8 shadow-sm";

export default function AaoifiGuide() {
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
            AAOIFI screening overview
          </h1>
          <p className="mt-3 text-base text-muted">
            The AAOIFI standards provide a widely used framework for screening
            equities based on financial ratios. The goal is to reduce exposure
            to interest-based income and excessive leverage.
          </p>
        </header>

        <section className={`${cardClass} animate-fade-up animate-delay-150`}>
          <h2 className="text-xl font-semibold text-fg">
            What the screens cover
          </h2>
          <ul className="mt-3 space-y-3 text-sm text-muted">
            <li>
              <span className="font-semibold text-fg">
                Debt exposure:
              </span>{" "}
              Limits how much of the company is funded through interest-bearing
              liabilities.
            </li>
            <li>
              <span className="font-semibold text-fg">
                Cash and liquid assets:
              </span>{" "}
              Caps how much of the balance sheet sits in interest-bearing or
              liquid instruments.
            </li>
            <li>
              <span className="font-semibold text-fg">
                Receivables:
              </span>{" "}
              Ensures that a company is not primarily a receivables-financing
              business.
            </li>
            <li>
              <span className="font-semibold text-fg">
                Non-permissible income:
              </span>{" "}
              Keeps revenue from impermissible activities below a small
              threshold.
            </li>
          </ul>
        </section>

        <section className={`${cardClass} animate-fade-up animate-delay-150`}>
          <h2 className="text-xl font-semibold text-fg">
            Governance and cleansing
          </h2>
          <p className="mt-3 text-sm text-muted">
            AAOIFI recommends that any non-permissible income be purified by
            donating the proportional amount. HalalLens highlights those values
            so users can quantify the cleansing requirement.
          </p>
        </section>
      </div>
    </main>
    <SiteFooter />
    </>
  );
}
