"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";
import Link from "next/link";

import type { Filing, IngestionStats } from "@/lib/types";
import { fetchRecentFilings } from "@/lib/filings";
import { fetchIngestionStats } from "@/lib/ingestion";
import { useTheme } from "@/providers/ThemeProvider";
import { useAuth } from "@/providers/AuthProvider";

export default function DashboardPage() {
  const { theme } = useTheme();
  const { user } = useAuth();

  const [filings, setFilings] = useState<Filing[]>([]);
  const [filingError, setFilingError] = useState<string | null>(null);
  const [adminStats, setAdminStats] = useState<IngestionStats | null>(null);
  const [adminStatsError, setAdminStatsError] = useState<string | null>(null);
  // Shown only while the session is an admin's.
  const stats = user?.is_admin ? adminStats : null;
  const statsError = user?.is_admin ? adminStatsError : null;

  const cardClass =
    theme === "dark"
      ? "rounded-[28px] border border-white/10 bg-[linear-gradient(145deg,rgba(15,23,42,0.92),rgba(8,12,20,0.95))] p-6 shadow-[0_25px_80px_rgba(3,7,18,0.55)]"
      : "rounded-[28px] border border-slate-200/70 bg-white/85 p-6 shadow-[0_20px_60px_rgba(15,23,42,0.12)]";
  const headingClass = theme === "dark" ? "text-white" : "text-slate-900";
  const mutedTextClass = theme === "dark" ? "text-slate-400" : "text-slate-500";

  useEffect(() => {
    fetchRecentFilings()
      .then((data) => {
        setFilings(data);
        setFilingError(null);
      })
      .catch((err) => setFilingError(err.message ?? "Unable to load filings."));

    // Ingestion stats are an operator surface; non-admins get 403 from the API,
    // so don't fetch (or render a scary error) for them.
    if (!user?.is_admin) return;

    fetchIngestionStats()
      .then((data) => {
        setAdminStats(data);
        setAdminStatsError(null);
      })
      .catch((err) => setAdminStatsError(err.message ?? "Unable to load stats."));
  }, [user?.is_admin]);

  return (
    <main className="space-y-10">
      <header className={cardClass}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className={clsx("text-xs uppercase tracking-[0.3em]", mutedTextClass)}>
              Overview
            </p>
            <h1 className={clsx("text-3xl font-semibold text-display", headingClass)}>
              Shariah compliance cockpit
            </h1>
            <p className={clsx("mt-2", mutedTextClass)}>
              Track recent filings, ingestion status, and jump into analysis or
              governance review.
            </p>
          </div>
          <Link
            href="/account"
            className={clsx(
              "rounded-full border px-4 py-2 text-xs font-semibold transition",
              theme === "dark"
                ? "border-cyan-400/40 text-cyan-200 hover:border-cyan-300"
                : "border-cyan-500/40 text-cyan-700 hover:border-cyan-600",
            )}
          >
            {user ? `Plan: ${user.plan}` : "Account"}
          </Link>
        </div>
      </header>

      <section className="grid gap-6 lg:grid-cols-3">
        <div className={cardClass}>
          <p className={clsx("text-xs uppercase", mutedTextClass)}>
            Total announcements
          </p>
          <p className={clsx("mt-2 text-3xl font-semibold", headingClass)}>
            {stats?.total_announcements ?? "—"}
          </p>
          {statsError && <p className="text-xs text-rose-300">{statsError}</p>}
        </div>
        <div className={cardClass}>
          <p className={clsx("text-xs uppercase", mutedTextClass)}>
            Financial snapshots
          </p>
          <p className={clsx("mt-2 text-3xl font-semibold", headingClass)}>
            {stats?.financial_snapshots ?? "—"}
          </p>
          <p className={clsx("mt-2 text-xs", mutedTextClass)}>
            High confidence: {stats?.high_confidence ?? "—"}
          </p>
        </div>
        <div className={cardClass}>
          <p className={clsx("text-xs uppercase", mutedTextClass)}>
            Latest filing
          </p>
          <p className={clsx("mt-2 text-lg font-semibold", headingClass)}>
            {stats?.latest_filing
              ? new Date(stats.latest_filing).toLocaleString()
              : "—"}
          </p>
          <p className={clsx("mt-2 text-xs", mutedTextClass)}>
            Ingestion health checks run hourly.
          </p>
        </div>
      </section>

      <section className={cardClass}>
        <h2 className={clsx("text-lg font-semibold", headingClass)}>
          Quick actions
        </h2>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[
            { href: "/analysis", label: "Run analysis" },
            { href: "/history", label: "View history" },
            { href: "/governance", label: "Governance overrides" },
            { href: "/feedback", label: "Feedback queue" },
            { href: "/account", label: "Manage billing" },
            { href: "/learn", label: "Educational library" },
          ].map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={clsx(
                "rounded-xl border px-4 py-3 text-sm font-semibold transition",
                theme === "dark"
                  ? "border-white/10 bg-white/5 text-slate-200 hover:border-cyan-400/40"
                  : "border-slate-200 bg-white text-slate-700 hover:border-cyan-300",
              )}
            >
              {item.label}
            </Link>
          ))}
        </div>
      </section>

      <section className={cardClass}>
        <div className="flex items-center justify-between">
          <h2 className={clsx("text-lg font-semibold", headingClass)}>
            Recent filings
          </h2>
          <button
            type="button"
            className={clsx(
              "text-xs font-semibold",
              theme === "dark" ? "text-cyan-300" : "text-cyan-700",
            )}
            onClick={async () => {
              try {
                const data = await fetchRecentFilings();
                setFilings(data);
                setFilingError(null);
              } catch (err: any) {
                setFilingError(err.message ?? "Unable to refresh filings.");
              }
            }}
          >
            Refresh
          </button>
        </div>
        {filingError && <p className="mt-2 text-xs text-rose-300">{filingError}</p>}
        <div className="mt-4 max-h-80 space-y-2 overflow-y-auto">
          {filings.map((filing) => (
            <div
              key={`${filing.symbol}-${filing.filing_date}`}
              className={clsx(
                "rounded-lg border px-3 py-2 text-sm",
                theme === "dark"
                  ? "border-slate-800 bg-slate-900 text-slate-200"
                  : "border-slate-200 bg-white text-slate-700",
              )}
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className={clsx("font-semibold", headingClass)}>
                    {filing.symbol}
                  </p>
                  <p className="text-xs text-slate-400">
                    {filing.headline || "—"}
                  </p>
                </div>
                <Link
                  href={`/analysis?symbol=${encodeURIComponent(filing.symbol)}`}
                  className="rounded-md bg-cyan-500 px-3 py-1 text-xs font-semibold text-slate-950 hover:bg-cyan-400"
                >
                  Analyze
                </Link>
              </div>
              <p className={clsx("mt-2 text-xs", mutedTextClass)}>
                {new Date(filing.filing_date).toLocaleDateString()} · {filing.verdict ?? "pending"}
              </p>
            </div>
          ))}
          {filings.length === 0 && (
            <p className={clsx("text-sm", mutedTextClass)}>
              No filings ingested yet.
            </p>
          )}
        </div>
      </section>
    </main>
  );
}
