"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import type { Filing, IngestionStats } from "@/lib/types";
import { fetchRecentFilings } from "@/lib/filings";
import { fetchIngestionStats } from "@/lib/ingestion";
import { useAuth } from "@/providers/AuthProvider";
import { Card, EmptyState, PageHeader, VerdictBadge, buttonClass, eyebrowClass } from "@/components/ui";

const QUICK_ACTIONS = [
  { href: "/analysis", label: "Screen a company", body: "Look up a symbol or enter figures by hand." },
  { href: "/history", label: "Filing history", body: "Ratios and verdicts over time for one company." },
  { href: "/account", label: "Plan and alerts", body: "Subscription, watchlist alerts and sign-in methods." },
  { href: "/learn", label: "Learn", body: "Riba, the AAOIFI screens and each ratio explained." },
];

export default function DashboardPage() {
  const { user } = useAuth();

  const [filings, setFilings] = useState<Filing[] | null>(null);
  const [filingError, setFilingError] = useState<string | null>(null);
  const [adminStats, setAdminStats] = useState<IngestionStats | null>(null);
  const [adminStatsError, setAdminStatsError] = useState<string | null>(null);

  const loadFilings = useCallback(async () => {
    try {
      setFilings(await fetchRecentFilings());
      setFilingError(null);
    } catch (err: any) {
      setFilingError(err.message ?? "Unable to load filings.");
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- first load after mount (static export)
    loadFilings();

    // Ingestion stats are an operator surface; non-admins get 403 from the API,
    // so don't fetch (or render a scary error) for them.
    if (!user?.is_admin) return;

    fetchIngestionStats()
      .then((data) => {
        setAdminStats(data);
        setAdminStatsError(null);
      })
      .catch((err) => setAdminStatsError(err.message ?? "Unable to load stats."));
  }, [user?.is_admin, loadFilings]);

  return (
    <>
      <PageHeader
        eyebrow="Overview"
        title="Overview"
        description="Recent screenings, quick ways in, and (for operators) the state of filing collection."
        actions={
          <Link href="/analysis" className={buttonClass("primary")}>
            Screen a company
          </Link>
        }
      />

      {user?.is_admin && (
        <section aria-label="Ingestion" className="grid gap-4 sm:grid-cols-3">
          {[
            ["Announcements", adminStats?.total_announcements],
            ["Financial snapshots", adminStats?.financial_snapshots],
            ["High confidence", adminStats?.high_confidence],
          ].map(([label, value]) => (
            <Card key={label as string} className="p-5">
              <p className={eyebrowClass}>{label}</p>
              <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-fg">
                {value ?? (adminStatsError ? "n/a" : "…")}
              </p>
            </Card>
          ))}
          {adminStatsError && <p className="text-sm text-danger sm:col-span-3">{adminStatsError}</p>}
        </section>
      )}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {QUICK_ACTIONS.map((action) => (
          <Link
            key={action.href}
            href={action.href}
            className="group rounded-xl border border-line bg-surface p-4 transition hover:border-brand/40 hover:shadow-md"
          >
            <p className="text-sm font-semibold text-fg group-hover:text-brand">{action.label}</p>
            <p className="mt-1 text-xs text-muted">{action.body}</p>
          </Link>
        ))}
      </section>

      <Card className="p-0">
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <h2 className="font-semibold text-fg">Recent filings</h2>
          <button type="button" className={buttonClass("ghost")} onClick={loadFilings}>
            Refresh
          </button>
        </div>
        {filingError && <p className="px-5 pt-4 text-sm text-danger">{filingError}</p>}
        {filings === null && !filingError && <p className="px-5 py-6 text-sm text-muted">Loading…</p>}
        {filings && filings.length === 0 && (
          <div className="p-5">
            <EmptyState title="No screened filings yet">
              Automatic collection of BSE filings is not running in production yet. You can still
              screen any company from{" "}
              <Link href="/analysis" className="text-brand hover:underline">
                Analysis
              </Link>{" "}
              by entering its figures.
            </EmptyState>
          </div>
        )}
        {filings && filings.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[36rem] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs text-muted">
                  <th scope="col" className="px-5 py-2 font-medium">Company</th>
                  <th scope="col" className="px-5 py-2 font-medium">Filing date</th>
                  <th scope="col" className="px-5 py-2 font-medium">Verdict</th>
                  <th scope="col" className="px-5 py-2"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {filings.map((filing) => (
                  <tr key={`${filing.symbol}-${filing.filing_date}`} className="border-b border-line last:border-0 hover:bg-surface-2/60">
                    <td className="px-5 py-3">
                      <p className="font-medium text-fg">{filing.company_name || filing.symbol}</p>
                      <p className="font-mono text-xs text-muted">{filing.symbol}</p>
                    </td>
                    <td className="px-5 py-3 font-mono text-xs tabular-nums text-muted">
                      {new Date(filing.filing_date).toLocaleDateString()}
                    </td>
                    <td className="px-5 py-3">
                      <VerdictBadge verdict={filing.verdict ?? ""} />
                    </td>
                    <td className="px-5 py-3 text-right">
                      <Link
                        href={`/analysis?symbol=${encodeURIComponent(filing.symbol)}`}
                        className={buttonClass("secondary")}
                      >
                        Analyze
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
