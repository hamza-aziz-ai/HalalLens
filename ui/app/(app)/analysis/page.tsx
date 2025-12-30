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
import { useAuth } from "@/providers/AuthProvider";
import { useTheme } from "@/providers/ThemeProvider";
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
  const { theme } = useTheme();
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

  const cardClass =
    theme === "dark"
      ? "rounded-[28px] border border-white/10 bg-[linear-gradient(145deg,rgba(15,23,42,0.92),rgba(8,12,20,0.95))] p-6 shadow-[0_25px_80px_rgba(3,7,18,0.55)]"
      : "rounded-[28px] border border-slate-200/70 bg-white/85 p-6 shadow-[0_20px_60px_rgba(15,23,42,0.12)]";
  const headingClass = theme === "dark" ? "text-white" : "text-slate-900";
  const mutedTextClass = theme === "dark" ? "text-slate-400" : "text-slate-500";
  const frostedInputClass = clsx(
    "flex-1 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-400/50",
    theme === "dark"
      ? "border border-white/10 bg-white/10 text-white placeholder:text-slate-400 shadow-inner shadow-black/30"
      : "border border-slate-200 bg-white text-slate-900 placeholder:text-slate-500 shadow-inner shadow-slate-200/60",
  );
  const textareaClass = clsx(
    "w-full rounded-xl border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-400/60",
    theme === "dark"
      ? "border-slate-700 bg-slate-900 text-white placeholder:text-slate-500"
      : "border-slate-200 bg-white text-slate-900 placeholder:text-slate-500",
  );

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
      const result = await callAnalysis(payload);
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
    setLookupSymbol(upperSymbol);
    runSymbolLookup(upperSymbol);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  return (
    <main className="space-y-10">
      <header className={cardClass}>
        <h1 className={clsx("text-3xl font-semibold text-display", headingClass)}>
          Shariah compliance analysis
        </h1>
        <p className={clsx("mt-2 text-sm", mutedTextClass)}>
          Load the latest filing by symbol or enter metrics manually to compute the
          AAOIFI ratios with Explain-Why narratives.
        </p>
      </header>

      <section className={cardClass}>
        <h2 className={clsx("text-lg font-semibold", headingClass)}>
          Instant symbol lookup
        </h2>
        <p className={clsx("text-sm", mutedTextClass)}>
          Pull the newest filing for a symbol and auto-run the analysis.
        </p>
        <div className="mt-3 flex flex-col gap-3 md:flex-row">
          <input
            className={frostedInputClass}
            placeholder="e.g., 532540 or TCS"
            value={lookupSymbol}
            onChange={(e) => setLookupSymbol(e.target.value.toUpperCase())}
          />
          <button
            type="button"
            onClick={quickAnalyzeSymbol}
            className={clsx(
              "rounded-lg bg-gradient-to-r from-cyan-400 to-emerald-400 px-4 py-2 text-sm font-semibold transition hover:opacity-90 disabled:opacity-50",
              theme === "dark" ? "text-slate-950" : "text-slate-900",
            )}
            disabled={lookupLoading || loading}
          >
            {lookupLoading ? "Analyzing…" : "Analyze symbol"}
          </button>
        </div>
        {lookupError && (
          <p className="mt-2 text-sm text-rose-400">{lookupError}</p>
        )}
        {selectedFiling && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
            <span className={mutedTextClass}>Market data source:</span>
            <ProviderBadge
              provider={marketProvider ?? selectedFiling.market_data_provider}
              theme={theme}
            />
            {marketStatus && <span className={mutedTextClass}>{marketStatus}</span>}
          </div>
        )}
      </section>

      <section className={cardClass}>
        <form
          className="space-y-6"
          onSubmit={(event) => {
            event.preventDefault();
            if (!analysisPayload.market_data.market_cap && !analysisPayload.market_data.trailing_market_cap) {
              setError(MANUAL_MARKET_MESSAGE);
              return;
            }
            runAnalysis(analysisPayload);
          }}
        >
          <div className="grid gap-4 md:grid-cols-2">
            <label className="flex flex-col gap-1 text-sm">
              <span className={mutedTextClass}>Symbol</span>
              <input
                className={textareaClass}
                value={form.snapshot.symbol}
                onChange={(e) => updateField("snapshot", "symbol", e.target.value.toUpperCase())}
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className={mutedTextClass}>Filing date</span>
              <input
                className={textareaClass}
                type="date"
                value={form.snapshot.filing_date}
                onChange={(e) => updateField("snapshot", "filing_date", e.target.value)}
              />
            </label>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
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
              <label key={key} className="flex flex-col gap-1 text-sm">
                <span className={mutedTextClass}>{label}</span>
                <input
                  className={textareaClass}
                  type="number"
                  value={form.snapshot[key as keyof SnapshotForm]}
                  onChange={(e) => updateField("snapshot", key, e.target.value)}
                />
              </label>
            ))}
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            {[
              ["market_cap", "Market cap"],
              ["trailing_market_cap", "Trailing market cap"],
              ["share_price", "Share price"],
            ].map(([key, label]) => (
              <label key={key} className="flex flex-col gap-1 text-sm">
                <span className={mutedTextClass}>{label}</span>
                <input
                  className={textareaClass}
                  type="number"
                  value={form.market_data[key as keyof MarketForm]}
                  onChange={(e) => updateField("market_data", key, e.target.value)}
                />
              </label>
            ))}
          </div>
          {error && <p className="text-sm text-rose-400">{error}</p>}
          <button
            type="submit"
            className="rounded-lg bg-cyan-500 px-6 py-3 text-sm font-medium text-slate-950 transition hover:bg-cyan-400 disabled:opacity-50"
            disabled={loading}
          >
            {loading ? "Analyzing…" : "Analyze filing"}
          </button>
        </form>
      </section>

      {response && (
        <section className="grid gap-6 lg:grid-cols-2">
          <RatioTable evaluation={response.score} theme={theme} />
          {response.narration ? (
            <ExplainPanel narration={response.narration} theme={theme} />
          ) : (
            <article className={clsx(cardClass, "text-sm", mutedTextClass)}>
              Explain-Why narration is unavailable for this filing.
            </article>
          )}
        </section>
      )}
    </main>
  );
}
