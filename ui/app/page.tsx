"use client";

import { useEffect, useState } from "react";

import { AnalysisPayload, AnalysisResponse } from "@/lib/types";
import { callAnalysis } from "@/lib/api";
import { ExplainPanel } from "@/components/explain-panel";
import { RatioTable } from "@/components/ratio-table";
import { fetchRecentFilings } from "@/lib/filings";
import type { Filing } from "@/lib/types";
import { fetchMarketQuote } from "@/lib/market-data";
import {
  fetchWatchlist,
  upsertWatchlist,
  WatchlistEntry,
} from "@/lib/watchlist";
import { triggerAlertCheck } from "@/lib/alerts";
import { fetchIngestionStats, IngestionStats } from "@/lib/ingestion";

type SnapshotForm = {
  symbol: string;
  filing_date: string;
  total_debt: string;
  cash_equiv: string;
  revenue: string;
  interest_income: string;
  dividend_income: string;
  non_permissible_income: string;
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
  },
  market_data: {
    market_cap: "",
    trailing_market_cap: "",
    share_price: "",
  },
};

type FieldGroup = keyof FormState;
const DEMO_USER_ID = "demo-user";

export default function HomePage() {
  const [form, setForm] = useState<FormState>(defaultPayload);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<AnalysisResponse | null>(null);
  const [filings, setFilings] = useState<Filing[]>([]);
  const [filingError, setFilingError] = useState<string | null>(null);
  const [selectedFiling, setSelectedFiling] = useState<Filing | null>(null);
  const [marketStatus, setMarketStatus] = useState<string | null>(null);
  const [watchlist, setWatchlist] = useState<WatchlistEntry[]>([]);
  const [watchlistSymbol, setWatchlistSymbol] = useState("");
  const [watchlistError, setWatchlistError] = useState<string | null>(null);
  const [alertMessage, setAlertMessage] = useState<string | null>(null);
  const [ingestionStats, setIngestionStats] = useState<IngestionStats | null>(null);
  const [statsError, setStatsError] = useState<string | null>(null);

  useEffect(() => {
    fetchRecentFilings()
      .then(setFilings)
      .catch((err) => setFilingError(err.message));
    fetchWatchlist(DEMO_USER_ID)
      .then(setWatchlist)
      .catch((err) => setWatchlistError(err.message));
    fetchIngestionStats()
      .then(setIngestionStats)
      .catch((err) => setStatsError(err.message));
  }, []);

  const updateField = (group: FieldGroup, key: string, value: string) => {
    setForm((prev) => ({
      ...prev,
      [group]: {
        ...prev[group],
        [key]: value,
      },
    }));
  };

  const analyzeForm = async () => {
    if (
      !form.market_data.market_cap?.trim() &&
      !form.market_data.trailing_market_cap?.trim()
    ) {
      setError("Enter market cap or trailing market cap before analyzing.");
      return;
    }
    setLoading(true);
    setError(null);
    setResponse(null);
    try {
      const cleaned = normalizePayload(form);
      const data = await callAnalysis(cleaned);
      setResponse(data);
      const alerts = await triggerAlertCheck({
        symbol: cleaned.snapshot.symbol,
        is_compliant: data.score.is_compliant,
      });
      if (alerts.length) {
        setAlertMessage(alerts.map((a) => a.message).join(" | "));
      } else {
        setAlertMessage("No compliance flip detected.");
      }
    } catch (err: any) {
      setError(err.message ?? "Unable to fetch analysis");
    } finally {
      setLoading(false);
    }
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    await analyzeForm();
  };

  const handleAddWatchlist = async () => {
    const symbol = watchlistSymbol.trim().toUpperCase();
    if (!symbol) {
      setWatchlistError("Enter a symbol to watch.");
      return;
    }
    try {
      setWatchlistError(null);
      await upsertWatchlist({
        user_id: DEMO_USER_ID,
        symbol,
        trigger: "compliance_flip",
      });
      setWatchlistSymbol("");
      const data = await fetchWatchlist(DEMO_USER_ID);
      setWatchlist(data);
    } catch (err: any) {
      setWatchlistError(err.message);
    }
  };

  return (
    <main className="space-y-8">
      <header>
        <p className="text-sm uppercase tracking-wide text-cyan-300">
          HalalLens
        </p>
        <h1 className="text-3xl font-semibold text-white">
          Shariah compliance insights
        </h1>
        <p className="mt-2 text-slate-300">
          Choose an ingested filing, auto-load its metrics, and compute AAOIFI
          ratios with Explain-Why narratives.
        </p>
      </header>

      <section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-6 shadow-xl shadow-black/40">
        <form className="space-y-6" onSubmit={submit}>
          <Fieldset legend="Snapshot details">
            <div className="grid gap-4 md:grid-cols-2">
              <TextInput
                label="Symbol"
                required
                value={form.snapshot.symbol}
                onChange={(value) =>
                  updateField("snapshot", "symbol", value.toUpperCase())
                }
              />
              <TextInput
                label="Filing date"
                type="date"
                required
                value={form.snapshot.filing_date}
                onChange={(value) =>
                  updateField("snapshot", "filing_date", value)
                }
              />
              {[
                ["total_debt", "Total debt"],
                ["cash_equiv", "Cash equivalents"],
                ["revenue", "Revenue"],
                ["non_permissible_income", "Non-permissible income"],
                ["interest_income", "Interest income"],
                ["dividend_income", "Dividend income"],
              ].map(([key, label]) => (
                <TextInput
                  key={key}
                  label={label}
                  type="number"
                  value={form.snapshot[key as keyof SnapshotForm]}
                  onChange={(value) => updateField("snapshot", key, value)}
                />
              ))}
            </div>
          </Fieldset>

          <Fieldset legend="Market data">
            <div className="grid gap-4 md:grid-cols-3">
              <TextInput
                label="Market cap"
                type="number"
                required={
                  !form.market_data.trailing_market_cap &&
                  !form.market_data.market_cap
                }
                value={form.market_data.market_cap}
                onChange={(value) =>
                  updateField("market_data", "market_cap", value)
                }
              />
              <TextInput
                label="Trailing market cap"
                type="number"
                value={form.market_data.trailing_market_cap}
                onChange={(value) =>
                  updateField("market_data", "trailing_market_cap", value)
                }
              />
              <TextInput
                label="Share price"
                type="number"
                value={form.market_data.share_price}
                onChange={(value) =>
                  updateField("market_data", "share_price", value)
                }
              />
            </div>
          </Fieldset>

          <div className="flex gap-3">
            <button
              type="submit"
              className="rounded-lg bg-cyan-500 px-6 py-3 text-sm font-medium text-slate-950 transition hover:bg-cyan-400 disabled:opacity-50"
              disabled={loading}
            >
              {loading ? "Analyzing..." : "Analyze filing"}
            </button>
            <button
              type="button"
              className="rounded-lg border border-slate-700 px-6 py-3 text-sm font-medium text-slate-200 hover:bg-slate-800"
              onClick={() => {
                setForm(defaultPayload);
                setResponse(null);
              }}
            >
              Reset
            </button>
          </div>
        </form>
        {error && (
          <p className="mt-4 text-sm text-rose-300">
            {error}
            {error.includes("Unable") &&
              " — ensure the FastAPI service is running and HALAL_API_BASE_URL is set."}
          </p>
        )}
        {alertMessage && (
          <p className="mt-2 text-sm text-cyan-200">{alertMessage}</p>
        )}
      </section>

      {response && (
        <section className="grid gap-6 lg:grid-cols-2">
          <RatioTable evaluation={response.score} />
          <ExplainPanel narration={response.narration} />
          {response.narration.source && (
            <p className="text-sm text-slate-400">
              Explain-Why source: {response.narration.source}
            </p>
          )}
        </section>
      )}

      <section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Recent filings</h2>
          <button
            type="button"
            onClick={async () => {
              try {
                const data = await fetchRecentFilings();
                setFilings(data);
                setFilingError(null);
              } catch (err: any) {
                setFilingError(err.message);
              }
            }}
            className="text-sm text-cyan-300 hover:text-cyan-200"
          >
            Refresh
          </button>
        </div>
        {filingError ? (
          <p className="mt-2 text-sm text-rose-300">
            {filingError} — ensure `/filings/recent` is reachable.
          </p>
        ) : (
          <div className="mt-4 max-h-80 space-y-2 overflow-y-auto">
            {filings.map((filing) => (
              <div
                key={`${filing.symbol}-${filing.filing_date}`}
                className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-left text-sm text-slate-200"
              >
                <button
                  onClick={() =>
                    handleSelectFiling(
                      filing,
                      setForm,
                      setSelectedFiling,
                      setMarketStatus,
                      setWatchlistSymbol,
                    )
                  }
                  className="w-full text-left hover:text-cyan-300"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-white">{filing.symbol}</span>
                    <div className="flex items-center gap-2 text-xs text-slate-500">
                      {filing.verdict && (
                        <span
                          className={`rounded-full px-2 py-0.5 font-semibold ${verdictBadgeClass(
                            filing.verdict,
                          )}`}
                        >
                          {formatVerdict(filing.verdict)}
                        </span>
                      )}
                      <span>
                        {new Date(filing.filing_date).toLocaleDateString()}
                      </span>
                    </div>
                  </div>
                  <p className="mt-1 text-xs text-slate-400">
                    {filing.headline || "--"}
                  </p>
                </button>
                {hasFinancialData(filing) ? (
                  <div className="mt-2 flex gap-2">
                    <button
                      onClick={async () => {
                        await handleAnalyzeFiling(
                          filing,
                          setForm,
                          setSelectedFiling,
                          setMarketStatus,
                          analyzeForm,
                          setWatchlistSymbol,
                        );
                      }}
                      className="rounded-md bg-cyan-500 px-3 py-1 text-xs font-semibold text-slate-950 hover:bg-cyan-400"
                    >
                      Analyze
                    </button>
                  </div>
                ) : (
                  <p className="mt-2 text-xs text-amber-300">
                    Missing financial inputs; click entry to edit manually.
                  </p>
                )}
              </div>
            ))}
            {filings.length === 0 && (
              <p className="text-sm text-slate-500">No filings ingested yet.</p>
            )}
          </div>
        )}
        {selectedFiling && (
          <FilingDetails filing={selectedFiling} marketStatus={marketStatus} />
        )}
      </section>

      <section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Ingestion stats</h2>
          <button
            type="button"
            onClick={async () => {
              try {
                const stats = await fetchIngestionStats();
                setIngestionStats(stats);
                setStatsError(null);
              } catch (err: any) {
                setStatsError(err.message);
              }
            }}
            className="text-sm text-cyan-300 hover:text-cyan-200"
          >
            Refresh
          </button>
        </div>
        {statsError ? (
          <p className="mt-2 text-sm text-rose-300">{statsError}</p>
        ) : ingestionStats ? (
          <ul className="mt-3 grid gap-2 text-sm text-slate-200 sm:grid-cols-2">
            <li className="rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
              <p className="text-xs text-slate-400">Total announcements</p>
              <p className="text-xl font-semibold text-white">
                {ingestionStats.total_announcements}
              </p>
            </li>
            <li className="rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
              <p className="text-xs text-slate-400">Financial snapshots</p>
              <p className="text-xl font-semibold text-white">
                {ingestionStats.financial_snapshots}
              </p>
            </li>
            <li className="rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
              <p className="text-xs text-slate-400">High-confidence filings</p>
              <p className="text-xl font-semibold text-white">
                {ingestionStats.high_confidence}
              </p>
            </li>
            <li className="rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
              <p className="text-xs text-slate-400">Latest filing</p>
              <p className="text-sm font-semibold text-white">
                {ingestionStats.latest_filing
                  ? new Date(ingestionStats.latest_filing).toLocaleString()
                  : "—"}
              </p>
            </li>
          </ul>
        ) : (
          <p className="mt-2 text-sm text-slate-500">Loading stats…</p>
        )}
      </section>

      <section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
        <h2 className="text-lg font-semibold text-white">Watchlist</h2>
        <p className="text-sm text-slate-400">
          Track compliance flips for symbols. Alerts trigger when verdict changes.
        </p>
        <div className="mt-4 flex gap-2">
          <input
            className="flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
            placeholder="Symbol (e.g., TCS)"
            value={watchlistSymbol}
            onChange={(e) => setWatchlistSymbol(e.target.value.toUpperCase())}
          />
          <button
            className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-emerald-400"
            onClick={handleAddWatchlist}
            type="button"
          >
            Add
          </button>
        </div>
        {watchlistError && (
          <p className="mt-2 text-sm text-rose-300">{watchlistError}</p>
        )}
        <ul className="mt-4 space-y-2 text-sm text-slate-200">
          {watchlist.map((entry) => (
            <li
              key={`${entry.user_id}-${entry.symbol}-${entry.trigger}`}
              className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-2"
            >
              <span className="font-semibold text-white">{entry.symbol}</span>{" "}
              <span className="text-xs uppercase text-slate-500">
                {entry.trigger.replace("_", " ")}
              </span>
            </li>
          ))}
          {watchlist.length === 0 && (
            <li className="text-slate-500">No watchlist entries yet.</li>
          )}
        </ul>
      </section>
    </main>
  );
}

function Fieldset({
  legend,
  children,
}: {
  legend: string;
  children: React.ReactNode;
}) {
  return (
    <fieldset className="space-y-4 rounded-xl border border-slate-800 p-4">
      <legend className="px-2 text-sm font-semibold text-slate-300">
        {legend}
      </legend>
      {children}
    </fieldset>
  );
}

function TextInput({
  label,
  type = "text",
  required = false,
  value,
  onChange,
}: {
  label: string;
  type?: string;
  required?: boolean;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="space-y-1 text-sm">
      <span className="text-slate-400">{label}</span>
      <input
        className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:border-cyan-400 focus:outline-none"
        type={type}
        required={required}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
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
      non_permissible_income: parseNumber(
        formState.snapshot.non_permissible_income,
      ),
      interest_income: parseNumber(formState.snapshot.interest_income),
      dividend_income: parseNumber(formState.snapshot.dividend_income),
    },
    market_data: {
      market_cap: parseNumber(formState.market_data.market_cap),
      trailing_market_cap: parseNumber(
        formState.market_data.trailing_market_cap,
      ),
      share_price: parseNumber(formState.market_data.share_price),
    },
  };
}

function setFormFromFiling(
  filing: Filing,
  setForm: (state: FormState) => void,
) {
  setForm({
    snapshot: {
      symbol: filing.symbol,
      filing_date: filing.filing_date.split("T")[0],
      total_debt: stringifyNumber(filing.total_debt),
      cash_equiv: stringifyNumber(filing.cash_equiv),
      revenue: stringifyNumber(filing.revenue),
      interest_income: stringifyNumber(filing.interest_income),
      dividend_income: stringifyNumber(filing.dividend_income),
      non_permissible_income: "",
    },
    market_data: {
      market_cap: stringifyNumber(filing.market_cap_used),
      trailing_market_cap: stringifyNumber(filing.trailing_cap_used),
      share_price: "",
    },
  });
}

function stringifyNumber(value?: number) {
  return typeof value === "number" ? String(value) : "";
}

function FilingDetails({
  filing,
  marketStatus,
}: {
  filing: Filing;
  marketStatus: string | null;
}) {
  const entries = [
    ["Company", filing.company_name || "—"],
    ["Category", filing.category || "—"],
    ["Confidence", filing.confidence || "—"],
    ["Total debt", displayNumber(filing.total_debt)],
    ["Cash equivalents", displayNumber(filing.cash_equiv)],
    ["Revenue", displayNumber(filing.revenue)],
    ["Interest income", displayNumber(filing.interest_income)],
    ["Dividend income", displayNumber(filing.dividend_income)],
    ["Audit status", filing.audit_status || "—"],
  ];
  return (
    <div className="mt-4 rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-sm text-slate-200">
      <h3 className="text-base font-semibold text-white">
        Selected filing: {filing.symbol}
      </h3>
      <p className="text-xs text-slate-400">
        Filing date: {new Date(filing.filing_date).toLocaleDateString()}
      </p>
      <ul className="mt-3 space-y-1">
        {entries.map(([label, value]) => (
          <li key={label} className="flex items-center justify-between">
            <span className="text-slate-400">{label}</span>
            <span className="text-white">{value}</span>
          </li>
        ))}
      </ul>
      {marketStatus && (
        <p className="mt-2 text-xs text-cyan-200">{marketStatus}</p>
      )}
      {filing.verdict && (
        <div className="mt-3 rounded-lg border border-slate-800 bg-slate-900/80 p-3">
          <p className="text-xs uppercase text-slate-500">Automated verdict</p>
          <p
            className={`text-sm font-semibold ${verdictBadgeClass(
              filing.verdict,
            )}`}
          >
            {formatVerdict(filing.verdict)}
          </p>
          {filing.summary && (
            <p className="mt-1 text-xs text-slate-400">{filing.summary}</p>
          )}
        </div>
      )}
      <p className="mt-3 text-xs text-slate-400">
        Market data auto-fills when available; you can still override values
        before analyzing.
      </p>
    </div>
  );
}

function displayNumber(value?: number) {
  if (typeof value !== "number") return "—";
  return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function hasFinancialData(filing: Filing) {
  return (
    filing.total_debt !== undefined ||
    filing.cash_equiv !== undefined ||
    filing.revenue !== undefined ||
    filing.interest_income !== undefined ||
    filing.dividend_income !== undefined
  );
}

function hasStoredMarketData(filing: Filing) {
  return (
    typeof filing.market_cap_used === "number" ||
    typeof filing.trailing_cap_used === "number"
  );
}

function verdictBadgeClass(verdict?: string | null) {
  if (verdict === "compliant") {
    return "border border-emerald-500/40 bg-emerald-500/10 text-emerald-300";
  }
  if (verdict === "non-compliant") {
    return "border border-rose-500/40 bg-rose-500/10 text-rose-300";
  }
  return "border border-amber-500/40 bg-amber-500/10 text-amber-300";
}

function formatVerdict(verdict?: string | null) {
  if (!verdict) return "Pending";
  return verdict
    .split("-")
    .map((chunk) => chunk.charAt(0).toUpperCase() + chunk.slice(1))
    .join(" ");
}

async function handleAnalyzeFiling(
  filing: Filing,
  setForm: (state: FormState) => void,
  setSelectedFiling: (filing: Filing) => void,
  setMarketStatus: (status: string | null) => void,
  analyzeForm: () => Promise<void>,
  setWatchlistSymbol: (value: string) => void,
) {
  setSelectedFiling(filing);
  setFormFromFiling(filing, setForm);
  setWatchlistSymbol(filing.symbol);
  if (hasStoredMarketData(filing)) {
    setMarketStatus("Using stored market data from ingestion pipeline.");
  } else {
    await fetchAndApplyMarketData(filing.symbol, setForm, setMarketStatus);
  }
  await analyzeForm();
}

function handleSelectFiling(
  filing: Filing,
  setForm: (state: FormState) => void,
  setSelectedFiling: (filing: Filing) => void,
  setMarketStatus: (status: string | null) => void,
  setWatchlistSymbol: (value: string) => void,
) {
  setSelectedFiling(filing);
  setFormFromFiling(filing, setForm);
  setWatchlistSymbol(filing.symbol);
  if (hasStoredMarketData(filing)) {
    setMarketStatus("Using stored market data from ingestion pipeline.");
  } else {
    fetchAndApplyMarketData(filing.symbol, setForm, setMarketStatus);
  }
}

async function fetchAndApplyMarketData(
  symbol: string,
  setForm: (state: FormState) => void,
  setStatus: (value: string | null) => void,
) {
  setStatus("Fetching latest market data…");
  try {
    const quote = await fetchMarketQuote(symbol);
    setForm((prev) => ({
      ...prev,
      market_data: {
        ...prev.market_data,
        market_cap: quote.market_cap
          ? String(Math.round(quote.market_cap))
          : prev.market_data.market_cap,
        share_price: quote.share_price
          ? String(quote.share_price)
          : prev.market_data.share_price,
      },
    }));
    setStatus(null);
  } catch (err) {
    setStatus("Market data unavailable; please enter values manually.");
  }
}
