"use client";

import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";

import type { Filing } from "@/lib/types";
import { fetchFilingHistory } from "@/lib/filings";
import { mergeHistoryEntries } from "@/lib/history";
import { HistoryTimeline } from "@/components/history-timeline";
import { HistoryMatrix } from "@/components/history-matrix";
import { RatioTrendChart } from "@/components/ratio-trend-chart";
import { ProviderBadge } from "@/components/provider-badge";
import { useAuth } from "@/providers/AuthProvider";
import { useTheme } from "@/providers/ThemeProvider";
import { getAutoProviderLabel } from "@/lib/providers";

const DEFAULT_LIMIT = 12;

export default function HistoryPage() {
  const { theme } = useTheme();
  const { user } = useAuth();
  const isAdmin = Boolean(user?.is_admin);
  const hasPaidAccess = Boolean(
    user &&
      (isAdmin ||
        (user.plan !== "free" &&
          ["active", "trialing"].includes(user.subscription_status))),
  );

  const [symbol, setSymbol] = useState("");
  const [entries, setEntries] = useState<Filing[]>([]);
  const [selected, setSelected] = useState<Filing | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [appending, setAppending] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);

  const cardClass =
    theme === "dark"
      ? "rounded-[28px] border border-white/10 bg-[linear-gradient(145deg,rgba(15,23,42,0.92),rgba(8,12,20,0.95))] p-6 shadow-[0_25px_80px_rgba(3,7,18,0.55)]"
      : "rounded-[28px] border border-slate-200/70 bg-white/85 p-6 shadow-[0_20px_60px_rgba(15,23,42,0.12)]";
  const headingClass = theme === "dark" ? "text-white" : "text-slate-900";
  const mutedTextClass = theme === "dark" ? "text-slate-400" : "text-slate-500";
  const inputClass = clsx(
    "w-full rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-400/60",
    theme === "dark"
      ? "border border-white/10 bg-white/10 text-white placeholder:text-slate-400"
      : "border border-slate-200 bg-white text-slate-900 placeholder:text-slate-500",
  );

  const selectedKey = selected
    ? `${selected.symbol}-${selected.filing_date}`
    : undefined;

  const providerLabel = useMemo(() => {
    if (!selected?.market_data_provider) return null;
    return getAutoProviderLabel(selected.market_data_provider);
  }, [selected]);

  const loadHistory = async (target: string, cursor?: string | null) => {
    const trimmed = target.trim().toUpperCase();
    if (!trimmed) return;
    if (!hasPaidAccess) {
      setHistoryError("Upgrade to Starter to unlock historical analytics.");
      setEntries([]);
      setSelected(null);
      setNextCursor(null);
      return;
    }
    const isAppend = Boolean(cursor);
    setHistoryError(null);
    if (isAppend) {
      setAppending(true);
    } else {
      setLoading(true);
    }
    try {
      const data = await fetchFilingHistory(trimmed, {
        limit: DEFAULT_LIMIT,
        cursor: cursor ?? undefined,
      });
      setNextCursor(data.next_cursor ?? null);
      setEntries((prev) =>
        isAppend ? mergeHistoryEntries(prev, data.entries) : data.entries,
      );
      setSelected((prev) => prev ?? data.entries[0] ?? null);
      if (!data.entries.length) {
        setSelected(null);
      }
    } catch (err: any) {
      setEntries([]);
      setSelected(null);
      setNextCursor(null);
      setHistoryError(err.message ?? "Unable to load history.");
    } finally {
      setLoading(false);
      setAppending(false);
    }
  };

  useEffect(() => {
    if (symbol.trim()) {
      loadHistory(symbol);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main className="space-y-10">
      <header className={cardClass}>
        <h1 className={clsx("text-3xl font-semibold text-display", headingClass)}>
          Historical analytics
        </h1>
        <p className={clsx("mt-2", mutedTextClass)}>
          Scan quarter-by-quarter AAOIFI ratios, verdict shifts, and market data
          context for any symbol.
        </p>
        <div className="mt-4 grid gap-3 md:grid-cols-[1fr_auto]">
          <input
            className={inputClass}
            placeholder="Enter BSE symbol (e.g., TCS or 532540)"
            value={symbol}
            onChange={(event) => setSymbol(event.target.value.toUpperCase())}
          />
          <button
            type="button"
            onClick={() => loadHistory(symbol)}
            className="rounded-lg bg-gradient-to-r from-cyan-400 to-emerald-400 px-4 py-2 text-sm font-semibold text-slate-950 hover:opacity-90"
          >
            Load history
          </button>
        </div>
        {!hasPaidAccess && (
          <p className={clsx("mt-3 text-xs", mutedTextClass)}>
            History is a paid feature. Upgrade to Starter to unlock the timeline.
          </p>
        )}
        {historyError && (
          <p className="mt-2 text-sm text-rose-400">{historyError}</p>
        )}
      </header>

      {loading && (
        <section className={cardClass}>
          <p className={clsx("text-sm", mutedTextClass)}>Loading history…</p>
        </section>
      )}

      {!loading && entries.length > 0 && (
        <section className="space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className={clsx("text-lg font-semibold", headingClass)}>
                {selected?.company_name || selected?.symbol}
              </h2>
              <p className={clsx("text-sm", mutedTextClass)}>
                {selected
                  ? `Selected filing: ${new Date(selected.filing_date).toLocaleDateString()}`
                  : "Select a filing to see details."}
              </p>
            </div>
            {selected && (
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className={mutedTextClass}>Market data source:</span>
                <ProviderBadge provider={selected.market_data_provider} theme={theme} />
                {providerLabel && (
                  <span className={mutedTextClass}>{providerLabel}</span>
                )}
              </div>
            )}
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <HistoryTimeline
              theme={theme}
              entries={entries}
              activeKey={selectedKey}
              onSelect={setSelected}
            />
            <RatioTrendChart
              theme={theme}
              entries={entries}
              onSelect={setSelected}
            />
          </div>

          <HistoryMatrix
            entries={entries}
            theme={theme}
            selectedKey={selectedKey}
            onSelect={setSelected}
          />

          <div className="flex justify-end">
            <button
              type="button"
              onClick={() => loadHistory(symbol, nextCursor)}
              disabled={!nextCursor || appending}
              className={clsx(
                "rounded-full border px-4 py-2 text-xs font-semibold transition",
                theme === "dark"
                  ? "border-cyan-400/40 text-cyan-200 hover:border-cyan-300 hover:text-cyan-100"
                  : "border-cyan-500/40 text-cyan-700 hover:border-cyan-600 hover:text-cyan-600",
              )}
            >
              {appending
                ? "Loading…"
                : nextCursor
                  ? "Load more history"
                  : "End of history"}
            </button>
          </div>
        </section>
      )}

      {!loading && !entries.length && !historyError && (
        <section className={cardClass}>
          <p className={clsx("text-sm", mutedTextClass)}>
            Enter a symbol to view historical ratios and compliance shifts.
          </p>
        </section>
      )}
    </main>
  );
}
