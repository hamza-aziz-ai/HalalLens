"use client";
import SiteHeader from "@/components/site-header";
import SiteFooter from "@/components/site-footer";

import Link from "next/link";
import clsx from "clsx";

const cardClass =
  "rounded-xl border border-line bg-surface p-6 shadow-sm transition hover:border-brand/50 hover:bg-surface-2";

const sectionTitle = "text-lg font-semibold text-fg";
const muted = "text-sm text-muted";

const guides = [
  {
    title: "Understanding Riba",
    description:
      "What riba is, why it is prohibited, and how it shows up in modern finance.",
    href: "/learn/riba",
  },
  {
    title: "AAOIFI Screening Primer",
    description:
      "Why the AAOIFI screens exist, how they are applied, and what they mean for investors.",
    href: "/learn/aaoifi",
  },
  {
    title: "Ratio Walkthrough",
    description:
      "Plain-language explanations of each ratio, thresholds, and how we compute them.",
    href: "/learn/ratios",
  },
];

export default function LearnLanding() {
  return (
    <>
    <SiteHeader />
    <main className="px-4 py-12 text-fg">
      <div className="mx-auto flex max-w-5xl flex-col gap-10">
        <header className="rounded-xl border border-line bg-surface p-8 shadow-sm animate-fade-up">
          <h1 className="mt-2 text-3xl font-semibold text-fg">
            Learn the foundations of Shariah compliance
          </h1>
          <p className="mt-3 text-base text-muted">
            These guides explain the concepts behind the screens we calculate.
            They are educational resources, not investment advice.
          </p>
        </header>

        <section className="grid gap-6 md:grid-cols-3">
          {guides.map((guide) => (
            <Link
              key={guide.href}
              href={guide.href}
              className={`${cardClass} animate-fade-up animate-delay-150`}
            >
              <h2 className="text-lg font-semibold text-fg">
                {guide.title}
              </h2>
              <p className={clsx("mt-2", muted)}>{guide.description}</p>
              <span className="mt-4 inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-brand">
                Read guide
              </span>
            </Link>
          ))}
        </section>

        <section className={clsx(cardClass, "space-y-3")}>
          <h2 className={sectionTitle}>How to use these guides</h2>
          <p className={muted}>
            Each guide explains a concept that directly maps to the HalalLens
            dashboard. If something in a filing looks unfamiliar, jump to the
            relevant section and compare the definitions with the numbers you
            see.
          </p>
          <p className={muted}>
            For deeper study, consult primary sources or scholars. The AAOIFI
            standards are regularly updated and interpretations can vary by
            region.
          </p>
        </section>
      </div>
    </main>
    <SiteFooter />
    </>
  );
}
