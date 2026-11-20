"use client";

import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import { useSearchParams } from "next/navigation";

import type { AnalysisPayload, AnalysisResponse, Filing } from "@/lib/types";
import { callAnalysis } from "@/lib/api";
import { fetchFilingDetail } from "@/lib/filings";
import { fetchMarketQuote } from "@/lib/market-data";
import { ProviderBadge } from "@/components/provider-badge";
import { RatioTable } from "@/components/ratio-table";
import { ExplainPanel } from "@/components/explain-panel";
import { EmptyState, PageHeader, buttonClass, cardClass, eyebrowClass, inputClass, labelClass } from "@/components/ui";
import { useAuth } from "@/providers/AuthProvider";
import { getAutoProviderLabel } from "@/lib/providers";
import { hasPaidAccess as hasPaidAccessForUser } from "@/lib/subscription";

type SnapshotForm = {
  symbol: string;
  filing_date: string;
  total_debt: string;
  cash_equiv: string;
  revenue: string;
  interest_income: string;
  dividend_income: string;
  non_permissible_income: string;
  accounts_receivable: string;
  liquid_assets: string;
};

type MarketForm = {
  market_cap: string;
  trailing_market_cap: string;
  share_price: string;
};

type FormState = {
  snapshot: SnapshotForm;
  market_data: MarketForm;
};

const defaultPayload: FormState = {
  snapshot: {
    symbol: "",
    filing_date: "",
    total_debt: "",
    cash_equiv: "",
    revenue: "",
    interest_income: "",
    dividend_income: "",
    non_permissible_income: "",
    accounts_receivable: "",
    liquid_assets: "",
  },
  market_data: {
    market_cap: "",
    trailing_market_cap: "",
    share_price: "",
  },
};

const MANUAL_MARKET_MESSAGE =
  "Market data unavailable; please enter values manually.";

function stringifyNumber(value?: number | null) {
  if (value === null || value === undefined) return "";
  return String(value);
}

function normalizePayload(formState: FormState): AnalysisPayload {
  const parseNumber = (value: string) => {
    if (!value) return undefined;
    const parsed = Number(value);
    return Number.isNaN(parsed) ? undefined : parsed;
  };

  return {
    snapshot: {
      symbol: formState.snapshot.symbol,
      filing_date: formState.snapshot.filing_date,
      total_debt: parseNumber(formState.snapshot.total_debt),
      cash_equiv: parseNumber(formState.snapshot.cash_equiv),
      revenue: parseNumber(formState.snapshot.revenue),
      interest_income: parseNumber(formState.snapshot.interest_income),
      dividend_income: parseNumber(formState.snapshot.dividend_income),
      non_permissible_income: parseNumber(formState.snapshot.non_permissible_income),
      accounts_receivable: parseNumber(formState.snapshot.accounts_receivable),
      liquid_assets: parseNumber(formState.snapshot.liquid_assets),
    },
    market_data: {
      market_cap: parseNumber(formState.market_data.market_cap),
      trailing_market_cap: parseNumber(formState.market_data.trailing_market_cap),
      share_price: parseNumber(formState.market_data.share_price),
    },
  };
}

function filingToForm(filing: Filing): FormState {
  const filingDate = filing.filing_date
    ? new Date(filing.filing_date).toISOString().split("T")[0]
    : "";
  return {
    snapshot: {
      symbol: filing.symbol,
      filing_date: filingDate,
      total_debt: stringifyNumber(filing.total_debt ?? undefined),
      cash_equiv: stringifyNumber(filing.cash_equiv ?? undefined),
      revenue: stringifyNumber(filing.revenue ?? undefined),
      interest_income: stringifyNumber(filing.interest_income ?? undefined),
      dividend_income: stringifyNumber(filing.dividend_income ?? undefined),
      non_permissible_income: stringifyNumber(filing.non_halal_income ?? undefined),
      accounts_receivable: stringifyNumber(filing.accounts_receivable ?? undefined),
      liquid_assets: stringifyNumber(filing.liquid_assets ?? undefined),
    },
    market_data: {
      market_cap: stringifyNumber(filing.market_cap_used ?? undefined),
      trailing_market_cap: stringifyNumber(filing.trailing_cap_used ?? undefined),
      share_price: stringifyNumber(filing.share_price ?? undefined),
    },
  };
}

export default function AnalysisPage() {
  const { user } = useAuth();
  const searchParams = useSearchParams();
  const hasPaidAccess = hasPaidAccessForUser(user);

  const [form, setForm] = useState<FormState>(defaultPayload);
  const [response, setResponse] = useState<AnalysisResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [lookupSymbol, setLookupSymbol] = useState("");
  const [lookupLoading, setLookupLoading] = useState(false);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [marketStatus, setMarketStatus] = useState<string | null>(null);
  const [marketProvider, setMarketProvider] = useState<string | null>(null);
  const [selectedFiling, setSelectedFiling] = useState<Filing | null>(null);

  const analysisPayload = useMemo(() => normalizePayload(form), [form]);

  const updateField = (
    group: keyof FormState,
    field: string,
    value: string,
  ) => {
    setForm((prev) => ({
      ...prev,
      [group]: {
        ...prev[group],
        [field]: value,
      },
    }));
  };

  const runAnalysis = async (payload: AnalysisPayload) => {
    setLoading(true);
    setError(null);
    try {
      const result = await callAnalysis(payload, hasPaidAccess);
      setResponse(result);
    } catch (err: any) {
      setError(err.message ?? "Unable to compute ratios.");
    } finally {
      setLoading(false);
    }
  };

  const runSymbolLookup = async (value: string) => {
    const trimmed = value.trim();
    if (!trimmed) return;
    if (!hasPaidAccess) {
      setLookupError("Upgrade to a paid plan to unlock instant symbol lookup.");
      return;
    }
    setLookupLoading(true);
    setLookupError(null);
    setMarketStatus(null);
    try {
      const filing = await fetchFilingDetail(trimmed, {
        refresh: true,
      });
      setSelectedFiling(filing);
      const nextForm = filingToForm(filing);
      setForm(nextForm);
      setMarketProvider(filing.market_data_provider ?? null);

      const needsMarketData =
        !filing.market_cap_used && !filing.trailing_cap_used;
      if (needsMarketData) {
        try {
          const quote = await fetchMarketQuote(filing.symbol);
          setForm((prev) => ({
            ...prev,
            market_data: {
              ...prev.market_data,
              market_cap: stringifyNumber(quote.market_cap ?? undefined),
              share_price: stringifyNumber(quote.share_price ?? undefined),
            },
          }));
          setMarketProvider(quote.provider ?? null);
          setMarketStatus(
            quote.market_cap
              ? `Market data loaded from ${getAutoProviderLabel(
                  quote.provider,
                )}.`
              : MANUAL_MARKET_MESSAGE,
          );
        } catch (quoteErr: any) {
          setMarketStatus(MANUAL_MARKET_MESSAGE);
        }
      } else {
        setMarketStatus(
          filing.market_data_provider
            ? `Using stored market data from ${getAutoProviderLabel(
                filing.market_data_provider,
              )}.`
            : null,
        );
      }

      const payload = normalizePayload(nextForm);
      if (!payload.market_data.market_cap && !payload.market_data.trailing_market_cap) {
        setMarketStatus(MANUAL_MARKET_MESSAGE);
        return;
      }
      await runAnalysis(payload);
    } catch (err: any) {
      setLookupError(err.message ?? "Unable to load filing.");
    } finally {
      setLookupLoading(false);
    }
  };

  const quickAnalyzeSymbol = async () => {
    await runSymbolLookup(lookupSymbol);
  };

  useEffect(() => {
    const paramSymbol = searchParams.get("symbol");
    if (!paramSymbol) return;
    const upperSymbol = paramSymbol.toUpperCase();
    if (upperSymbol === lookupSymbol) return;
    // Mirrors ?symbol= into the input on each navigation and runs the lookup (a fetch, so it belongs in an effect).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLookupSymbol(upperSymbol);
    runSymbolLookup(upperSymbol);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Screening"
        title="Shariah compliance analysis"
        description="Load the latest filing by symbol or enter metrics manually to compute the AAOIFI ratios with Explain-Why narratives."
      />

      <div className="grid items-start gap-6 lg:grid-cols-2">
        <div className="space-y-6">
          <section className={clsx(cardClass, "p-6")}>
            <p className={eyebrowClass}>01 · Lookup</p>
            <h2 className="mt-1 text-lg font-semibold text-fg">Instant symbol lookup</h2>
            <p className="mt-1 text-sm text-muted">
              Pull the newest filing for a symbol and auto-run the analysis.
            </p>
            <div className="mt-4 flex flex-col gap-3 sm:flex-row">
              <input
                className={clsx(inputClass, "font-mono sm:flex-1")}
                aria-label="Symbol to look up"
                placeholder="e.g., 532540 or TCS"
                value={lookupSymbol}
                onChange={(e) => setLookupSymbol(e.target.value.toUpperCase())}
              />
              <button
                type="button"
                onClick={quickAnalyzeSymbol}
                className={buttonClass("primary")}
                disabled={lookupLoading || loading}
              >
                {lookupLoading ? "Analyzing…" : "Analyze symbol"}
              </button>
            </div>
            {lookupError && (
              <p className="mt-2 text-sm text-danger" role="alert">{lookupError}</p>
            )}
            {selectedFiling && (
              <div className="mt-4 space-y-2 rounded-lg border border-line bg-surface-2 p-3 text-xs text-muted">
                <div className="flex flex-wrap items-center gap-2">
                  <span>Market data source:</span>
                  <ProviderBadge provider={marketProvider ?? selectedFiling.market_data_provider} />
                  {marketStatus && <span>{marketStatus}</span>}
                </div>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                  <span>
                    Filing date:{" "}
                    <span className="font-mono tabular-nums text-fg">
                      {new Date(selectedFiling.filing_date).toLocaleDateString()}
                    </span>
                  </span>
                  {selectedFiling.data_updated_at && (
                    <span>
                      Last updated:{" "}
                      <span className="font-mono tabular-nums text-fg">
                        {new Date(selectedFiling.data_updated_at).toLocaleDateString()}
                      </span>
                    </span>
                  )}
                  {selectedFiling.confidence && (
                    <span>Confidence: {selectedFiling.confidence}</span>
                  )}
                  {selectedFiling.governance_override_applied && (
                    <span>
                      Override applied
                      {selectedFiling.governance_override_source
                        ? ` (${selectedFiling.governance_override_source})`
                        : ""}
                    </span>
                  )}
                </div>
                {selectedFiling.quality_issues?.length ? (
                  <p className="text-warning">
                    Data quality flags: {selectedFiling.quality_issues.join(", ")}
                  </p>
                ) : null}
              </div>
            )}
          </section>

          <section className={clsx(cardClass, "p-6")}>
            <p className={eyebrowClass}>02 · Inputs</p>
            <h2 className="mt-1 text-lg font-semibold text-fg">Filing metrics</h2>
            <form
              className="mt-4 space-y-6"
              onSubmit={(event) => {
                event.preventDefault();
                if (!analysisPayload.market_data.market_cap && !analysisPayload.market_data.trailing_market_cap) {
                  setError(MANUAL_MARKET_MESSAGE);
                  return;
                }
                runAnalysis(analysisPayload);
              }}
            >
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="flex flex-col gap-1">
                  <span className={labelClass}>Symbol</span>
                  <input
                    className={clsx(inputClass, "font-mono")}
                    value={form.snapshot.symbol}
                    onChange={(e) => updateField("snapshot", "symbol", e.target.value.toUpperCase())}
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className={labelClass}>Filing date</span>
                  <input
                    className={clsx(inputClass, "font-mono tabular-nums")}
                    type="date"
                    value={form.snapshot.filing_date}
                    onChange={(e) => updateField("snapshot", "filing_date", e.target.value)}
                  />
                </label>
              </div>
              <fieldset className="border-t border-line pt-4">
                <legend className="pr-2 font-mono text-[11px] font-medium uppercase tracking-wider text-muted">
                  Balance sheet and income
                </legend>
                <div className="grid gap-4 sm:grid-cols-2">
                  {[
                    ["total_debt", "Total debt"],
                    ["cash_equiv", "Cash equivalents"],
                    ["revenue", "Revenue"],
                    ["non_permissible_income", "Non-permissible income"],
                    ["interest_income", "Interest income"],
                    ["dividend_income", "Dividend income"],
                    ["accounts_receivable", "Accounts receivable"],
                    ["liquid_assets", "Liquid assets"],
                  ].map(([key, label]) => (
                    <label key={key} className="flex flex-col gap-1">
                      <span className={labelClass}>{label}</span>
                      <input
                        className={clsx(inputClass, "font-mono tabular-nums")}
                        type="number"
                        value={form.snapshot[key as keyof SnapshotForm]}
                        onChange={(e) => updateField("snapshot", key, e.target.value)}
                      />
                    </label>
                  ))}
                </div>
              </fieldset>
              <fieldset className="border-t border-line pt-4">
                <legend className="pr-2 font-mono text-[11px] font-medium uppercase tracking-wider text-muted">
                  Market data
                </legend>
                <div className="grid gap-4 sm:grid-cols-3">
                  {[
                    ["market_cap", "Market cap"],
                    ["trailing_market_cap", "Trailing market cap"],
                    ["share_price", "Share price"],
                  ].map(([key, label]) => (
                    <label key={key} className="flex flex-col gap-1">
                      <span className={labelClass}>{label}</span>
                      <input
                        className={clsx(inputClass, "font-mono tabular-nums")}
                        type="number"
                        value={form.market_data[key as keyof MarketForm]}
                        onChange={(e) => updateField("market_data", key, e.target.value)}
                      />
                    </label>
                  ))}
                </div>
              </fieldset>
              {error && <p className="text-sm text-danger" role="alert">{error}</p>}
              <button type="submit" className={buttonClass("primary", "lg")} disabled={loading}>
                {loading ? "Analyzing…" : "Analyze filing"}
              </button>
            </form>
          </section>
        </div>

        <section className="space-y-6 lg:sticky lg:top-6" aria-live="polite">
          {response ? (
            <>
              <RatioTable evaluation={response.score} />
              {response.narration ? (
                <ExplainPanel narration={response.narration} />
              ) : (
                <article className={clsx(cardClass, "p-6 text-sm text-muted")}>
                  {hasPaidAccess
                    ? "Explain-Why narration is unavailable for this filing."
                    : "Explain-Why narration is included in the paid plans."}
                </article>
              )}
            </>
          ) : (
            <div className={clsx(cardClass, "p-6")}>
              <p className={eyebrowClass}>03 · Result</p>
              <div className="mt-3">
                <EmptyState title="No screening yet">
                  Look up a symbol or enter the filing metrics, then run the analysis to see the verdict, each ratio against its cap and the Explain-Why text.
                </EmptyState>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
