import Link from "next/link";
import { ReactNode } from "react";

export const policyCardClass =
  "rounded-3xl border border-white/10 bg-white/5 p-6 shadow-[0_25px_80px_rgba(3,7,18,0.5)] backdrop-blur";
export const policyTitleClass = "text-lg font-semibold text-white";
export const policyBodyClass = "text-sm leading-relaxed text-slate-300";
export const policyListClass = "list-disc space-y-2 pl-5 text-sm text-slate-300";

type PolicyLayoutProps = {
  title: string;
  subtitle: string;
  updatedAt: string;
  children: ReactNode;
};

export default function PolicyLayout({
  title,
  subtitle,
  updatedAt,
  children,
}: PolicyLayoutProps) {
  return (
    <main className="min-h-screen bg-[radial-gradient(1200px_circle_at_10%_-10%,rgba(14,116,144,0.35),transparent_45%),radial-gradient(900px_circle_at_85%_0%,rgba(16,185,129,0.18),transparent_40%),#05070d] px-4 py-12 text-slate-100">
      <div className="mx-auto flex max-w-4xl flex-col gap-8">
        <header className="rounded-3xl border border-white/10 bg-gradient-to-br from-slate-900/90 via-slate-900/70 to-slate-950/80 p-8 shadow-[0_25px_80px_rgba(3,7,18,0.55)] animate-fade-up">
          <div className="flex flex-wrap items-center justify-between gap-3 text-xs uppercase tracking-[0.2em] text-cyan-300/80">
            <span>HalalLens</span>
            <div className="flex items-center gap-3 text-[11px] font-semibold">
              <Link href="/login" className="text-cyan-200 hover:text-cyan-100">
                Login
              </Link>
              <Link href="/learn" className="text-cyan-200 hover:text-cyan-100">
                Learn
              </Link>
            </div>
          </div>
          <h1 className="mt-5 text-3xl font-semibold text-white">{title}</h1>
          <p className="mt-3 text-base text-slate-300">{subtitle}</p>
          <p className="mt-4 text-xs uppercase tracking-[0.2em] text-slate-400">
            Last updated: {updatedAt}
          </p>
        </header>
        <div className="flex flex-col gap-6">{children}</div>
      </div>
    </main>
  );
}
