"use client";

import { useMemo, useState } from "react";

import type { Filing } from "@/lib/types";
import { fetchFilingHistory } from "@/lib/filings";
import { mergeHistoryEntries } from "@/lib/history";
import { HistoryTimeline } from "@/components/history-timeline";
import { HistoryMatrix } from "@/components/history-matrix";
import { RatioTrendChart } from "@/components/ratio-trend-chart";
import { ProviderBadge } from "@/components/provider-badge";
import { useAuth } from "@/providers/AuthProvider";
import { Card, EmptyState, PageHeader, buttonClass, inputClass } from "@/components/ui";
import { getAutoProviderLabel } from "@/lib/providers";
import { hasPaidAccess as hasPaidAccessForUser } from "@/lib/subscription";

const DEFAULT_LIMIT = 12;

export default function HistoryPage() {
  const { user } = useAuth();
  const hasPaidAccess = hasPaidAccessForUser(user);

  const [symbol, setSymbol] = useState("");
  const [entries, setEntries] = useState<Filing[]>([]);
  const [selected, setSelected] = useState<Filing | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [appending, setAppending] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);

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
      setHistoryError("Upgrade to a paid plan to unlock historical analytics.");
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

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="History"
        title="Historical analytics"
        description="Scan quarter-by-quarter AAOIFI ratios, verdict shifts, and market data context for any symbol."
      />

      <Card>
        <div className="grid gap-3 md:grid-cols-[1fr_auto]">
          <input
            className={inputClass}
            aria-label="BSE symbol"
            placeholder="Enter BSE symbol (e.g., TCS or 532540)"
            value={symbol}
            onChange={(event) => setSymbol(event.target.value.toUpperCase())}
          />
          <button
            type="button"
            onClick={() => loadHistory(symbol)}
            className={buttonClass("primary")}
          >
            Load history
          </button>
        </div>
        {!hasPaidAccess && (
          <p className="mt-3 text-xs text-muted">
            History is a paid feature. Upgrade to a paid plan to unlock the timeline.
          </p>
        )}
        {historyError && (
          <p className="mt-2 text-sm text-danger">{historyError}</p>
        )}
      </Card>

      {loading && (
        <Card>
          <p className="text-sm text-muted motion-safe:animate-pulse">Loading history…</p>
        </Card>
      )}

      {!loading && entries.length > 0 && (
        <section className="space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="space-y-0.5">
              <h2 className="text-lg font-semibold text-fg">
                {selected?.company_name || selected?.symbol}
              </h2>
              <p className="text-sm text-muted">
                {selected
                  ? `Selected filing: ${new Date(selected.filing_date).toLocaleDateString()}`
                  : "Select a filing to see details."}
              </p>
              {selected?.data_updated_at && (
                <p className="text-xs text-muted">
                  Last updated: <span className="font-mono tabular-nums">{new Date(selected.data_updated_at).toLocaleDateString()}</span>
                </p>
              )}
              {selected?.confidence && (
                <p className="text-xs text-muted">
                  Confidence: {selected.confidence}
                </p>
              )}
              {selected?.governance_override_applied && (
                <p className="text-xs text-muted">
                  Override applied
                  {selected.governance_override_source
                    ? ` (${selected.governance_override_source})`
                    : ""}
                </p>
              )}
              {selected?.quality_issues?.length ? (
                <p className="text-xs text-warning">
                  Data quality flags: {selected.quality_issues.join(", ")}
                </p>
              ) : null}
            </div>
            {selected && (
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="text-muted">Market data source:</span>
                <ProviderBadge provider={selected.market_data_provider} />
                {providerLabel && (
                  <span className="text-muted">{providerLabel}</span>
                )}
              </div>
            )}
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <HistoryTimeline
              entries={entries}
              activeKey={selectedKey}
              onSelect={setSelected}
            />
            <RatioTrendChart entries={entries} onSelect={setSelected} />
          </div>

          <HistoryMatrix
            entries={entries}
            selectedKey={selectedKey}
            onSelect={setSelected}
          />

          <div className="flex justify-end">
            <button
              type="button"
              onClick={() => loadHistory(symbol, nextCursor)}
              disabled={!nextCursor || appending}
              className={buttonClass("secondary")}
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
        <EmptyState title="No symbol loaded">
          Enter a symbol to view historical ratios and compliance shifts.
        </EmptyState>
      )}
    </div>
  );
}
