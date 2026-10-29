"use client";

import Link from "next/link";
import clsx from "clsx";

const cardClass =
  "rounded-3xl border border-white/10 bg-white/5 p-6 shadow-[0_25px_80px_rgba(3,7,18,0.5)] backdrop-blur transition hover:border-cyan-400/40 hover:bg-white/10";

const sectionTitle = "text-lg font-semibold text-white";
const muted = "text-sm text-slate-400";

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
    <main className="min-h-screen bg-[#05070d] bg-[image:radial-gradient(1200px_circle_at_10%_-10%,rgba(14,116,144,0.35),transparent_45%),radial-gradient(900px_circle_at_85%_0%,rgba(16,185,129,0.18),transparent_40%)] px-4 py-12 text-slate-100">
      <div className="mx-auto flex max-w-5xl flex-col gap-10">
        <header className="rounded-3xl border border-white/10 bg-gradient-to-br from-slate-900/90 via-slate-900/70 to-slate-950/80 p-8 shadow-[0_25px_80px_rgba(3,7,18,0.55)] animate-fade-up">
          <div className="flex flex-wrap items-center justify-between gap-3 text-xs uppercase tracking-[0.2em] text-cyan-300/80">
            <span>HalalLens</span>
            <Link href="/login" className="text-cyan-200 hover:text-cyan-100">
              Back to login
            </Link>
          </div>
          <h1 className="mt-5 text-3xl font-semibold text-white">
            Learn the foundations of Shariah compliance
          </h1>
          <p className="mt-3 text-base text-slate-300">
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
              <h2 className="text-lg font-semibold text-white">
                {guide.title}
              </h2>
              <p className={clsx("mt-2", muted)}>{guide.description}</p>
              <span className="mt-4 inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-200">
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
  );
}
