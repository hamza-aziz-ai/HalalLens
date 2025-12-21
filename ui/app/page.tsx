"use client";

import { useEffect, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import clsx from "clsx";

import {
  AnalysisPayload,
  AnalysisResponse,
  FeedbackReport,
  FeedbackTrackingStatus,
  GovernanceOverride,
} from "@/lib/types";
import { callAnalysis } from "@/lib/api";
import { ExplainPanel } from "@/components/explain-panel";
import { RatioTable } from "@/components/ratio-table";
import { HistoryTimeline } from "@/components/history-timeline";
import { HistoryMatrix } from "@/components/history-matrix";
import { RatioTrendChart } from "@/components/ratio-trend-chart";
import {
  fetchFilingDetail,
  fetchFilingHistory,
  fetchRecentFilings,
} from "@/lib/filings";
import type { Filing } from "@/lib/types";
import { fetchMarketQuote } from "@/lib/market-data";
import { fetchWatchlist, upsertWatchlist } from "@/lib/watchlist";
import type { WatchlistEntry } from "@/lib/types";
import { triggerAlertCheck } from "@/lib/alerts";
import { fetchIngestionStats } from "@/lib/ingestion";
import type { IngestionStats } from "@/lib/types";
import {
  submitFeedback,
  fetchFeedbackReports,
  updateFeedbackReport,
  fetchFeedbackStatus,
} from "@/lib/feedback";
import {
  fetchGovernanceOverrides,
  upsertGovernanceOverride,
  deleteGovernanceOverride,
} from "@/lib/governance";

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

const STATUS_BADGE_MAP: Record<string, string> = {
  open: "border-cyan-500/40 bg-cyan-500/10 text-cyan-200",
  in_review: "border-amber-400/40 bg-amber-400/10 text-amber-200",
  resolved: "border-emerald-400/40 bg-emerald-400/10 text-emerald-200",
};

const formatStatusLabel = (status: string) =>
  status
    .replace(/_/g, " ")
    .replace(/\b\w/g, (ch) => ch.toUpperCase());

const formatTimestamp = (value?: string | null) =>
  value ? new Date(value).toLocaleString() : "—";

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
type Theme = "dark" | "light";
const DEMO_USER_ID = "demo-user";
const THEME_STORAGE_KEY = "halal-lens-theme";
const HISTORY_DEFAULT_LIMIT = 12;
const MANUAL_MARKET_MESSAGE =
  "Market data unavailable; please enter values manually.";
const PROVIDER_LABELS: Record<string, string> = {
  tiingo: "Tiingo",
  yahoo: "Yahoo Finance",
  bhavcopy: "BSE Bhavcopy",
  cache: "Cached snapshot",
};
const CARD_CLASS = (theme: Theme) =>
  theme === "dark"
    ? "rounded-3xl border border-white/15 bg-gradient-to-br from-slate-900/90 via-slate-900/70 to-slate-950/80 shadow-2xl shadow-black/40 backdrop-blur"
    : "rounded-3xl border border-slate-200/70 bg-white/90 shadow-2xl shadow-black/10 backdrop-blur";

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
  const [feedbackMessage, setFeedbackMessage] = useState("");
  const [feedbackContact, setFeedbackContact] = useState("");
  const [feedbackStatus, setFeedbackStatus] = useState<string | null>(null);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const [feedbackQueue, setFeedbackQueue] = useState<FeedbackReport[]>([]);
  const [feedbackQueueError, setFeedbackQueueError] = useState<string | null>(null);
  const [feedbackQueueLoading, setFeedbackQueueLoading] = useState(false);
  const [feedbackNotes, setFeedbackNotes] = useState<Record<number, string>>({});
  const [feedbackRecompute, setFeedbackRecompute] = useState<Record<number, boolean>>({});
  const [feedbackTicketId, setFeedbackTicketId] = useState<number | null>(null);
  const [feedbackTrackingToken, setFeedbackTrackingToken] = useState<string | null>(null);
  const [feedbackLookupToken, setFeedbackLookupToken] = useState("");
  const [feedbackLookupResult, setFeedbackLookupResult] = useState<FeedbackTrackingStatus | null>(null);
  const [feedbackLookupError, setFeedbackLookupError] = useState<string | null>(null);
  const selectedHistoryKey =
    selectedFiling && selectedFiling.filing_date
      ? `${selectedFiling.symbol}-${selectedFiling.filing_date}`
      : undefined;
  const [governanceOverrides, setGovernanceOverrides] = useState<GovernanceOverride[]>([]);
  const [overrideForm, setOverrideForm] = useState({
    accounts_receivable: "",
    liquid_assets: "",
    non_halal_income: "",
    governance_notes: "",
    reason: "",
    reviewer: "",
  });
  const [overrideStatus, setOverrideStatus] = useState<string | null>(null);
  const [overrideError, setOverrideError] = useState<string | null>(null);
  const [overrideLoading, setOverrideLoading] = useState(false);
  const [lookupSymbol, setLookupSymbol] = useState("");
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [lookupLoading, setLookupLoading] = useState(false);
  const [filingHistory, setFilingHistory] = useState<Filing[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [theme, setTheme] = useState<Theme>("dark");
  const [historyLimit, setHistoryLimit] = useState(HISTORY_DEFAULT_LIMIT);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark") {
      setTheme(stored);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

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
    refreshFeedback();
  }, []);

  useEffect(() => {
    if (selectedFiling) {
      refreshOverrides(selectedFiling.symbol);
      setOverrideForm((prev) => ({
        ...prev,
        accounts_receivable: stringifyNumber(selectedFiling.accounts_receivable),
        liquid_assets: stringifyNumber(selectedFiling.liquid_assets),
        non_halal_income: stringifyNumber(selectedFiling.non_halal_income),
        governance_notes: selectedFiling.governance_notes || "",
        reason: selectedFiling.governance_override_reason || "",
        reviewer: selectedFiling.governance_override_reviewer || "",
      }));
    } else {
      setGovernanceOverrides([]);
    }
  }, [selectedFiling]);

  const updateField = (group: FieldGroup, key: string, value: string) => {
    setForm((prev) => ({
      ...prev,
      [group]: {
        ...prev[group],
        [key]: value,
      },
    }));
  };

  const loadHistory = async (symbol?: string, limit?: number) => {
    const trimmed = (symbol || "").trim().toUpperCase();
    if (!trimmed) {
      setFilingHistory([]);
      setHistoryError(null);
      return;
    }
    const effectiveLimit = limit ?? historyLimit;
    try {
      const data = await fetchFilingHistory(trimmed, effectiveLimit);
      setFilingHistory(data);
      setHistoryError(null);
    } catch (err: any) {
      setFilingHistory([]);
      setHistoryError(err.message ?? "Unable to load history.");
    }
  };

  const refreshFeedback = async () => {
    setFeedbackQueueLoading(true);
    try {
      const queue = await fetchFeedbackReports("", 50);
      const active = queue.filter((report) => report.status !== "resolved");
      setFeedbackQueue(active);
      setFeedbackQueueError(null);
      setFeedbackNotes({});
      setFeedbackRecompute((prev) => {
        const next = { ...prev };
        active.forEach((report) => {
          if (next[report.id] === undefined) {
            next[report.id] = true;
          }
        });
        return next;
      });
    } catch (err: any) {
      setFeedbackQueue([]);
      setFeedbackQueueError(err.message ?? "Unable to load feedback queue.");
    } finally {
      setFeedbackQueueLoading(false);
    }
  };

  const handleHistorySelect = (entry: Filing) => {
    handleSelectFiling(
      entry,
      setForm,
      setSelectedFiling,
      setMarketStatus,
      setWatchlistSymbol,
      loadHistory,
    );
  };

  const handleLoadMoreHistory = async () => {
    if (!selectedFiling) return;
    const nextLimit = historyLimit + 8;
    setHistoryLimit(nextLimit);
    await loadHistory(selectedFiling.symbol, nextLimit);
  };

  const refreshOverrides = async (symbol?: string) => {
    if (!symbol) {
      setGovernanceOverrides([]);
      return;
    }
    try {
      const rows = await fetchGovernanceOverrides(symbol, 25);
      setGovernanceOverrides(rows);
      setOverrideError(null);
    } catch (err: any) {
      setGovernanceOverrides([]);
      setOverrideError(err.message ?? "Unable to load overrides.");
    }
  };

  const handleFeedbackStatusChange = async (
    report: FeedbackReport,
    status: "open" | "in_review" | "resolved",
    options?: { triggerRecompute?: boolean },
  ) => {
    const notes = feedbackNotes[report.id]?.trim();
    try {
      await updateFeedbackReport(report.id, {
        status,
        review_notes: notes || undefined,
        reviewer: "dashboard",
        trigger_recompute: options?.triggerRecompute,
      });
      if (status === "resolved") {
        setFeedbackNotes((prev) => {
          const next = { ...prev };
          delete next[report.id];
          return next;
        });
      }
      await refreshFeedback();
    } catch (err: any) {
      setFeedbackQueueError(err.message ?? "Unable to update feedback.");
    }
  };

  const handleCopyTrackingToken = async () => {
    if (!feedbackTrackingToken) return;
    try {
      await navigator.clipboard.writeText(feedbackTrackingToken);
      setFeedbackStatus("Tracking token copied to clipboard.");
    } catch (err: any) {
      setFeedbackError(err.message ?? "Unable to copy tracking token.");
    }
  };

  const handleFeedbackStatusLookup = async () => {
    const token = feedbackLookupToken.trim() || feedbackTrackingToken?.trim();
    if (!token) {
      setFeedbackLookupError("Enter a tracking token to check status.");
      setFeedbackLookupResult(null);
      return;
    }
    try {
      setFeedbackLookupError(null);
      const result = await fetchFeedbackStatus(token);
      setFeedbackLookupResult(result);
    } catch (err: any) {
      setFeedbackLookupResult(null);
      setFeedbackLookupError(err.message ?? "Unable to look up ticket.");
    }
  };

  const runAnalysis = async (override?: AnalysisPayload) => {
    const payload = override ?? normalizePayload(form);
    if (
      !payload.market_data.market_cap &&
      !payload.market_data.trailing_market_cap
    ) {
      setError("Enter market cap or trailing market cap before analyzing.");
      return;
    }
    if (!payload.snapshot.symbol || !payload.snapshot.filing_date) {
      setError("Symbol and filing date are required.");
      return;
    }
    setLoading(true);
    setError(null);
    setResponse(null);
    try {
      const data = await callAnalysis(payload);
      setResponse(data);
      const alerts = await triggerAlertCheck({
        symbol: payload.snapshot.symbol,
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
    await runAnalysis();
  };

  const quickAnalyzeSymbol = async () => {
    const trimmed = lookupSymbol.trim().toUpperCase();
    if (!trimmed) {
      setLookupError("Enter a BSE symbol (e.g., 532540 or TCS).");
      return;
    }
    setLookupError(null);
    setLookupLoading(true);
    try {
      const filing = await fetchFilingDetail(trimmed, { refresh: true });
      setSelectedFiling(filing);
      setFormFromFiling(filing, setForm);
      setWatchlistSymbol(filing.symbol);
      setHistoryLimit(HISTORY_DEFAULT_LIMIT);
      await loadHistory(filing.symbol, HISTORY_DEFAULT_LIMIT);
      applyMarketStatusForFiling(filing, setMarketStatus);
      let payload = payloadFromFiling(filing);
      if (
        !payload.market_data.market_cap &&
        !payload.market_data.trailing_market_cap
      ) {
        try {
          const quote = await fetchMarketQuote(filing.symbol);
          payload = payloadFromFiling(filing, {
            market_cap: quote.market_cap ?? undefined,
            share_price: quote.share_price ?? undefined,
          });
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
          const providerLabel = formatProviderLabel(quote.provider);
          setMarketStatus(
            providerLabel
              ? `Auto-filled via ${providerLabel}`
              : "Auto-filled via live quote",
          );
        } catch {
          setMarketStatus(MANUAL_MARKET_MESSAGE);
        }
      }
      await runAnalysis(payload);
    } catch (err: any) {
      setLookupError(err.message ?? "Unable to fetch filing data.");
    } finally {
      setLookupLoading(false);
    }
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

  const handleFeedbackSubmit = async () => {
    const symbol = (selectedFiling?.symbol || form.snapshot.symbol || "").trim();
    if (!symbol) {
      setFeedbackError("Select a filing or enter a symbol before submitting feedback.");
      return;
    }
    const message = feedbackMessage.trim();
    if (!message) {
      setFeedbackError("Please describe what looks incorrect.");
      return;
    }
    let filingDate: string | undefined;
    if (selectedFiling?.filing_date) {
      filingDate = selectedFiling.filing_date;
    } else if (form.snapshot.filing_date) {
      const parsed = new Date(form.snapshot.filing_date);
      if (!Number.isNaN(parsed.getTime())) {
        filingDate = parsed.toISOString();
      }
    }
    try {
      setFeedbackError(null);
      const result = await submitFeedback({
        symbol,
        filing_date: filingDate,
        verdict: selectedFiling?.verdict ?? null,
        message,
        contact: feedbackContact.trim() || undefined,
      });
      setFeedbackStatus(`Ticket #${result.ticket_id} received. Save the tracking token below.`);
      setFeedbackTicketId(result.ticket_id);
      setFeedbackTrackingToken(result.tracking_token);
      setFeedbackLookupToken(result.tracking_token);
      setFeedbackLookupResult(null);
      setFeedbackMessage("");
      setFeedbackContact("");
    } catch (err: any) {
      setFeedbackStatus(null);
      setFeedbackError(err.message ?? "Unable to send feedback.");
    }
  };

  const parseOverrideNumber = (value: string) => {
    if (!value.trim()) return undefined;
    const parsed = Number(value);
    return Number.isNaN(parsed) ? undefined : parsed;
  };

  const handleOverrideSubmit = async () => {
    const symbol = (selectedFiling?.symbol || form.snapshot.symbol || "").trim();
    let filingDate =
      selectedFiling?.filing_date ||
      (form.snapshot.filing_date
        ? new Date(form.snapshot.filing_date).toISOString()
        : "");

    if (!symbol || !filingDate) {
      setOverrideError("Select a filing or fill symbol + filing date before overriding.");
      return;
    }
    if (
      !overrideForm.accounts_receivable &&
      !overrideForm.liquid_assets &&
      !overrideForm.non_halal_income &&
      !overrideForm.governance_notes
    ) {
      setOverrideError("Provide at least one metric or note to override.");
      return;
    }
    setOverrideError(null);
    setOverrideStatus(null);
    setOverrideLoading(true);
    try {
      const payload = {
        symbol,
        filing_date: filingDate,
        accounts_receivable: parseOverrideNumber(overrideForm.accounts_receivable),
        liquid_assets: parseOverrideNumber(overrideForm.liquid_assets),
        non_halal_income: parseOverrideNumber(overrideForm.non_halal_income),
        governance_notes: overrideForm.governance_notes.trim() || undefined,
        reason: overrideForm.reason.trim() || undefined,
        reviewer: overrideForm.reviewer.trim() || undefined,
      };
      await upsertGovernanceOverride(payload);
      setOverrideStatus("Override saved.");
      await refreshOverrides(symbol);
    } catch (err: any) {
      setOverrideError(err.message ?? "Unable to save override.");
    } finally {
      setOverrideLoading(false);
    }
  };

  const handleOverrideDelete = async (entry: GovernanceOverride) => {
    try {
      await deleteGovernanceOverride(entry.symbol, entry.filing_date);
      setOverrideStatus("Override removed.");
      await refreshOverrides(entry.symbol);
    } catch (err: any) {
      setOverrideError(err.message ?? "Unable to delete override.");
    }
  };

  const rootClass = clsx(
    "relative min-h-screen transition-colors",
    theme === "dark"
      ? "bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 text-white"
      : "bg-gradient-to-b from-slate-100 via-white to-slate-50 text-slate-900",
  );
  const overlayClass =
    theme === "dark"
      ? "bg-gradient-to-r from-cyan-500/20 via-transparent to-emerald-500/20"
      : "bg-gradient-to-r from-cyan-400/20 via-transparent to-emerald-400/20";
  const headingClass = theme === "dark" ? "text-white" : "text-slate-900";
  const secondaryTextClass = theme === "dark" ? "text-slate-300" : "text-slate-600";
  const mutedTextClass = theme === "dark" ? "text-slate-400" : "text-slate-500";
  const bodyTextClass = theme === "dark" ? "text-slate-200" : "text-slate-700";
  const sectionTitleClass = clsx("text-lg font-semibold", headingClass);
  const refreshButtonClass =
    theme === "dark"
      ? "text-sm text-cyan-300 hover:text-cyan-200"
      : "text-sm text-cyan-700 hover:text-cyan-600";
  const errorTextClass = theme === "dark" ? "text-rose-300" : "text-rose-500";
  const successTextClass = theme === "dark" ? "text-emerald-300" : "text-emerald-600";
  const pillClass = clsx(
    "inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs",
    theme === "dark"
      ? "border border-cyan-400/40 bg-cyan-400/10 text-cyan-200"
      : "border border-cyan-600/20 bg-cyan-100 text-cyan-700",
  );
  const frostedInputClass = clsx(
    "flex-1 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-400/50",
    theme === "dark"
      ? "border border-white/10 bg-white/10 text-white placeholder:text-slate-400"
      : "border border-slate-200 bg-white text-slate-900 placeholder:text-slate-500",
  );
  const textareaClass = clsx(
    "rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-400/60",
    theme === "dark"
      ? "border-slate-700 bg-slate-900 text-white placeholder:text-slate-500"
      : "border-slate-200 bg-white text-slate-900 placeholder:text-slate-500",
  );

  return (
    <div className={clsx(rootClass, theme === "light" && "theme-light")}>
      <div
        className={clsx(
          "pointer-events-none absolute inset-x-0 top-0 h-60 blur-[120px]",
          overlayClass,
        )}
      />
      <main className="relative z-10 mx-auto max-w-6xl space-y-10 px-4 py-10">
        <header className={clsx(CARD_CLASS(theme), "p-6")}>
          <div className="flex items-start justify-between">
            <div className={pillClass}>
            <span className="h-2 w-2 animate-pulse rounded-full bg-cyan-300" />
            Real-time AAOIFI cockpit
          </div>
            <button
              type="button"
              onClick={() =>
                setTheme((prev) => (prev === "dark" ? "light" : "dark"))
              }
              className={clsx(
                "rounded-full border px-3 py-1 text-xs font-semibold shadow-sm transition hover:opacity-90",
                theme === "dark"
                  ? "border-white/20 bg-white/10 text-white"
                  : "border-slate-300 bg-white/70 text-slate-900",
              )}
            >
              Theme: {theme === "dark" ? "Dark" : "Light"}
            </button>
          </div>
          <h1 className={clsx("mt-4 text-3xl font-semibold", headingClass)}>
            Shariah compliance insights
          </h1>
          <p className={clsx("mt-2", secondaryTextClass)}>
            Choose an ingested filing, auto-load its metrics, and compute AAOIFI
            ratios with Explain-Why narratives.
          </p>
        </header>

        <section className={clsx(CARD_CLASS(theme), "p-6")}>
          <h2 className={clsx("text-lg font-semibold", headingClass)}>
            Instant symbol lookup
          </h2>
          <p className={clsx("text-sm", mutedTextClass)}>
            Enter any BSE ticker to load the latest ingested filing and auto-run the AAOIFI
            ratios plus Explain-Why narrative.
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
              className={clsx(
                "rounded-lg bg-gradient-to-r from-cyan-400 to-emerald-400 px-4 py-2 text-sm font-semibold transition hover:opacity-90 disabled:opacity-50",
                theme === "dark" ? "text-slate-950" : "text-slate-900",
              )}
              onClick={quickAnalyzeSymbol}
              disabled={lookupLoading || loading}
            >
              {lookupLoading || loading ? "Analyzing…" : "Analyze symbol"}
            </button>
          </div>
          {lookupError && (
            <p className="mt-2 text-sm text-rose-400">{lookupError}</p>
          )}
          <p className={clsx("mt-2 text-xs", mutedTextClass)}>
            We grab the newest filing from the backend. You can still tweak numbers below if
            anything needs correction.
          </p>
        </section>

        <section className={clsx(CARD_CLASS(theme), "p-6")}>
        <div className="flex items-center justify-between">
          <h2 className={sectionTitleClass}>Governance overrides</h2>
          <button
            type="button"
            className={refreshButtonClass}
            onClick={() => refreshOverrides(selectedFiling?.symbol)}
            disabled={!selectedFiling}
          >
            Refresh
          </button>
        </div>
        <p className={clsx("text-sm", mutedTextClass)}>
          Apply manual corrections when AAOIFI metrics were extracted incorrectly. Overrides
          feed the ratio engine immediately and are logged with reviewer metadata.
        </p>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <TextInput
            label="Accounts receivable override"
            type="number"
            value={overrideForm.accounts_receivable}
            onChange={(value) =>
              setOverrideForm((prev) => ({ ...prev, accounts_receivable: value }))
            }
            theme={theme}
          />
          <TextInput
            label="Liquid assets override"
            type="number"
            value={overrideForm.liquid_assets}
            onChange={(value) =>
              setOverrideForm((prev) => ({ ...prev, liquid_assets: value }))
            }
            theme={theme}
          />
          <TextInput
            label="Non-permissible income override"
            type="number"
            value={overrideForm.non_halal_income}
            onChange={(value) =>
              setOverrideForm((prev) => ({ ...prev, non_halal_income: value }))
            }
            theme={theme}
          />
          <TextInput
            label="Reviewer name"
            value={overrideForm.reviewer}
            onChange={(value) =>
              setOverrideForm((prev) => ({ ...prev, reviewer: value }))
            }
            theme={theme}
          />
        </div>
        <div className="mt-3 grid gap-3">
          <label className="space-y-1 text-sm">
            <span className={mutedTextClass}>Override notes</span>
            <textarea
              className={clsx("min-h-[70px]", textareaClass)}
              value={overrideForm.governance_notes}
              onChange={(e) =>
                setOverrideForm((prev) => ({ ...prev, governance_notes: e.target.value }))
              }
            />
          </label>
          <label className="space-y-1 text-sm">
            <span className={mutedTextClass}>Reason</span>
            <input
              className={textareaClass}
              value={overrideForm.reason}
              onChange={(e) =>
                setOverrideForm((prev) => ({ ...prev, reason: e.target.value }))
              }
            />
          </label>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={handleOverrideSubmit}
            className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-slate-900 hover:bg-emerald-400 disabled:opacity-60"
            disabled={overrideLoading}
          >
            {overrideLoading ? "Saving…" : "Apply override"}
          </button>
          {selectedFiling ? (
            <span className={clsx("text-xs", mutedTextClass)}>
              Target: <strong>{selectedFiling.symbol}</strong>{" "}
              {new Date(selectedFiling.filing_date).toLocaleString()}
            </span>
          ) : (
            <span className={clsx("text-xs", mutedTextClass)}>
              Select a filing to target overrides automatically.
            </span>
          )}
        </div>
        {overrideError && (
          <p className={clsx("mt-2 text-sm", errorTextClass)}>{overrideError}</p>
        )}
        {overrideStatus && (
          <p className={clsx("mt-2 text-sm", successTextClass)}>{overrideStatus}</p>
        )}
        <div className="mt-4 space-y-2">
          {governanceOverrides.length === 0 ? (
            <p className={clsx("text-sm", mutedTextClass)}>
              {selectedFiling
                ? "No overrides for this symbol."
                : "Select a filing to view overrides."}
            </p>
          ) : (
            governanceOverrides.map((entry) => (
              <div
                key={`${entry.symbol}-${entry.filing_date}`}
                className={clsx(
                  "rounded-lg border p-3 text-sm",
                  theme === "dark"
                    ? "border-slate-800 bg-slate-900/70 text-slate-200"
                    : "border-slate-200 bg-white text-slate-700",
                )}
              >
                <div className={clsx("flex items-center justify-between text-xs", mutedTextClass)}>
                  <span>
                    {entry.symbol} — {new Date(entry.filing_date).toLocaleString()}
                  </span>
                  <button
                    type="button"
                    className="text-rose-400 hover:text-rose-300"
                    onClick={() => handleOverrideDelete(entry)}
                  >
                    Remove
                  </button>
                </div>
                <p className={clsx("mt-1 text-xs", mutedTextClass)}>
                  Reviewer: {entry.reviewer || "—"} · Source: {entry.source || "manual"}
                </p>
                <p className={clsx("mt-1", bodyTextClass)}>
                  AR={entry.accounts_receivable ?? "—"} · Liquid={entry.liquid_assets ?? "—"}
                  {" · "}Non-halal={entry.non_halal_income ?? "—"}
                </p>
                {entry.governance_notes && (
                  <p className="text-xs text-amber-500">{entry.governance_notes}</p>
                )}
                {entry.reason && (
                  <p className={clsx("text-xs", mutedTextClass)}>Reason: {entry.reason}</p>
                )}
              </div>
            ))
          )}
        </div>
      </section>

        <section className={clsx(CARD_CLASS(theme), "p-6")}>
        <form className="space-y-6" onSubmit={submit}>
          <Fieldset legend="Snapshot details" theme={theme}>
            <div className="grid gap-4 md:grid-cols-2">
              <TextInput
                label="Symbol"
                required
                value={form.snapshot.symbol}
                onChange={(value) =>
                  updateField("snapshot", "symbol", value.toUpperCase())
                }
                theme={theme}
              />
              <TextInput
                label="Filing date"
                type="date"
                required
                value={form.snapshot.filing_date}
                onChange={(value) =>
                  updateField("snapshot", "filing_date", value)
                }
                theme={theme}
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
                  theme={theme}
                />
              ))}
            </div>
          </Fieldset>

          <Fieldset legend="Market data" theme={theme}>
            {marketStatus && (
              <p
                className={clsx(
                  "text-xs",
                  theme === "dark" ? "text-cyan-200" : "text-cyan-700",
                )}
              >
                {marketStatus}
              </p>
            )}
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
                theme={theme}
              />
              <TextInput
                label="Trailing market cap"
                type="number"
                value={form.market_data.trailing_market_cap}
                onChange={(value) =>
                  updateField("market_data", "trailing_market_cap", value)
                }
                theme={theme}
              />
              <TextInput
                label="Share price"
                type="number"
                value={form.market_data.share_price}
                onChange={(value) =>
                  updateField("market_data", "share_price", value)
                }
                theme={theme}
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
          <RatioTable evaluation={response.score} theme={theme} />
          <ExplainPanel narration={response.narration} theme={theme} />
          {response.narration.source && (
            <p className="text-sm text-slate-400">
              Explain-Why source: {response.narration.source}
            </p>
          )}
        </section>
      )}

      {selectedFiling &&
        (historyError ? (
          <section
            className={clsx(CARD_CLASS(theme), "p-4 text-sm", errorTextClass)}
          >
            {historyError}
          </section>
        ) : filingHistory.length > 0 ? (
          <section className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className={sectionTitleClass}>Historical analytics</h2>
                <p className={clsx("text-sm", mutedTextClass)}>
                  Compare AAOIFI ratios over time and drill into past filings.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className={mutedTextClass}>
                  Showing last {filingHistory.length} filings
                </span>
                <button
                  type="button"
                  className={clsx(
                    "rounded-full border px-3 py-1 text-xs font-semibold transition",
                    theme === "dark"
                      ? "border-cyan-400/40 text-cyan-200 hover:border-cyan-300 hover:text-cyan-100"
                      : "border-cyan-500/40 text-cyan-700 hover:border-cyan-600 hover:text-cyan-600",
                  )}
                  onClick={handleLoadMoreHistory}
                  disabled={!selectedFiling}
                >
                  Load more
                </button>
              </div>
            </div>
            <div className="grid gap-6 lg:grid-cols-2">
              <HistoryTimeline
                theme={theme}
                entries={filingHistory}
                activeKey={selectedHistoryKey}
                onSelect={handleHistorySelect}
              />
              <RatioTrendChart
                entries={filingHistory}
                theme={theme}
                onSelect={handleHistorySelect}
              />
            </div>
            <HistoryMatrix
              entries={filingHistory}
              theme={theme}
              selectedKey={selectedHistoryKey}
              onSelect={handleHistorySelect}
            />
          </section>
        ) : (
          <section className={clsx(CARD_CLASS(theme), "p-4 text-sm", mutedTextClass)}>
            No historical filings found for {selectedFiling.symbol}.
          </section>
        ))}

        <section className={clsx(CARD_CLASS(theme), "p-6")}>
        <div className="flex items-center justify-between">
          <h2 className={sectionTitleClass}>Recent filings</h2>
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
            className={refreshButtonClass}
          >
            Refresh
          </button>
        </div>
        {filingError ? (
          <p className={clsx("mt-2 text-sm", errorTextClass)}>
            {filingError} — ensure `/filings/recent` is reachable.
          </p>
        ) : (
          <div className="mt-4 max-h-80 space-y-2 overflow-y-auto">
            {filings.map((filing) => (
              <div
                key={`${filing.symbol}-${filing.filing_date}`}
                className={clsx(
                  "rounded-lg border px-3 py-2 text-left text-sm",
                  theme === "dark"
                    ? "border-slate-800 bg-slate-900 text-slate-200"
                    : "border-slate-200 bg-white text-slate-700",
                )}
              >
                <button
                  onClick={() => {
                    setHistoryLimit(HISTORY_DEFAULT_LIMIT);
                    handleSelectFiling(
                      filing,
                      setForm,
                      setSelectedFiling,
                      setMarketStatus,
                      setWatchlistSymbol,
                      (symbol?: string) =>
                        loadHistory(symbol, HISTORY_DEFAULT_LIMIT),
                    );
                  }}
                  className="w-full text-left hover:text-cyan-300"
                >
                  <div className="flex items-center justify-between">
                    <span className={clsx("font-semibold", headingClass)}>
                      {filing.symbol}
                    </span>
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
                        setHistoryLimit(HISTORY_DEFAULT_LIMIT);
                        await handleAnalyzeFiling(
                          filing,
                          setForm,
                          setSelectedFiling,
                          setMarketStatus,
                          runAnalysis,
                          setWatchlistSymbol,
                          (symbol?: string) =>
                            loadHistory(symbol, HISTORY_DEFAULT_LIMIT),
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
          <FilingDetails
            filing={selectedFiling}
            marketStatus={marketStatus}
            theme={theme}
          />
        )}
      </section>

        <section className={clsx(CARD_CLASS(theme), "p-6")}>
        <h2 className={sectionTitleClass}>Report an issue</h2>
        <p className={clsx("text-sm", mutedTextClass)}>
          Flag incorrect ratios, market data, or verdicts. Please include a brief
          description — we review every submission.
        </p>
        <div className="mt-4 space-y-2">
          <textarea
            className={clsx("min-h-[90px] w-full", textareaClass)}
            placeholder="Describe what looks wrong…"
            value={feedbackMessage}
            onChange={(e) => {
              setFeedbackMessage(e.target.value);
              setFeedbackStatus(null);
              setFeedbackError(null);
            }}
          />
          <input
            className={textareaClass}
            placeholder="Email or Telegram (optional, for follow-up)"
            value={feedbackContact}
            onChange={(e) => {
              setFeedbackContact(e.target.value);
              setFeedbackStatus(null);
              setFeedbackError(null);
            }}
          />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={handleFeedbackSubmit}
            className="rounded-lg bg-amber-400 px-4 py-2 text-sm font-semibold text-slate-900 hover:bg-amber-300"
          >
            Send feedback
          </button>
          {selectedFiling ? (
            <span className={clsx("text-xs", mutedTextClass)}>
              Reporting for <strong>{selectedFiling.symbol}</strong> filing dated{" "}
              {new Date(selectedFiling.filing_date).toLocaleDateString()}
            </span>
          ) : form.snapshot.symbol ? (
            <span className={clsx("text-xs", mutedTextClass)}>
              Reporting for <strong>{form.snapshot.symbol}</strong> (manual entry)
            </span>
          ) : (
            <span className={clsx("text-xs", mutedTextClass)}>
              Select a filing first to include its context.
            </span>
          )}
        </div>
        {feedbackError && (
          <p className={clsx("mt-2 text-sm", errorTextClass)}>{feedbackError}</p>
        )}
        {feedbackStatus && (
          <p className={clsx("mt-2 text-sm", successTextClass)}>{feedbackStatus}</p>
        )}
        {feedbackTrackingToken && (
          <div
            className={clsx(
              "mt-4 rounded-lg border px-3 py-2 text-xs",
              theme === "dark"
                ? "border-slate-800 bg-slate-900/70 text-slate-200"
                : "border-slate-200 bg-white text-slate-700",
            )}
          >
            <p>
              Ticket{" "}
              <strong>
                #{feedbackTicketId ?? "—"}
              </strong>{" "}
              tracking token:
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2 font-mono text-sm">
              <span className="break-all">{feedbackTrackingToken}</span>
              <button
                type="button"
                onClick={handleCopyTrackingToken}
                className="rounded-md bg-slate-800 px-2 py-1 text-xs text-slate-100 hover:bg-slate-700"
              >
                Copy
              </button>
            </div>
            <p className={clsx("mt-1 text-[11px]", mutedTextClass)}>
              Keep this token handy — you can paste it below or share it with your team
              to follow the review history.
            </p>
          </div>
        )}
        <div className="mt-6 border-t border-slate-800/40 pt-4">
          <h3 className={clsx("text-sm font-semibold", headingClass)}>
            Check ticket status
          </h3>
          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            <input
              className={clsx("flex-1", textareaClass)}
              placeholder="Tracking token"
              value={feedbackLookupToken}
              onChange={(e) => {
                setFeedbackLookupToken(e.target.value);
                setFeedbackLookupResult(null);
                setFeedbackLookupError(null);
              }}
            />
            <button
              type="button"
              onClick={handleFeedbackStatusLookup}
              className="rounded-lg bg-slate-700 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-600"
            >
              Check status
            </button>
          </div>
          {feedbackLookupError && (
            <p className={clsx("mt-2 text-sm", errorTextClass)}>
              {feedbackLookupError}
            </p>
          )}
          {feedbackLookupResult && (
            <div
              className={clsx(
                "mt-3 rounded-lg border px-3 py-2 text-xs",
                theme === "dark"
                  ? "border-slate-800 bg-slate-900/60 text-slate-200"
                  : "border-slate-200 bg-white text-slate-700",
              )}
            >
              <p>
                <strong>Status:</strong>{" "}
                {formatStatusLabel(feedbackLookupResult.status)}
              </p>
              <p className="mt-1">
                <strong>Last update:</strong>{" "}
                {formatTimestamp(feedbackLookupResult.status_updated_at)}
              </p>
              {feedbackLookupResult.review_notes && (
                <p className="mt-1">
                  <strong>Reviewer notes:</strong>{" "}
                  {feedbackLookupResult.review_notes}
                </p>
              )}
              {feedbackLookupResult.reevaluation_notes && (
                <p className="mt-1">
                  <strong>Re-evaluation:</strong>{" "}
                  {feedbackLookupResult.reevaluation_notes} (
                  {formatTimestamp(feedbackLookupResult.reevaluated_at)})
                </p>
              )}
              <p className="mt-1 text-[11px] text-slate-400">
                Created {formatTimestamp(feedbackLookupResult.created_at)} • Ticket #
                {feedbackLookupResult.ticket_id}
              </p>
            </div>
          )}
        </div>
      </section>

        <section className={clsx(CARD_CLASS(theme), "p-6")}>
        <div className="flex items-center justify-between">
          <h2 className={sectionTitleClass}>Feedback queue</h2>
          <button
            type="button"
            className={refreshButtonClass}
            onClick={refreshFeedback}
          >
            Refresh
          </button>
        </div>
        <p className={clsx("text-sm", mutedTextClass)}>
          Internal reviewers can triage user reports, add notes, and mark them resolved.
        </p>
        {feedbackQueueLoading ? (
          <p className="mt-3 text-sm text-slate-500">Loading feedback…</p>
        ) : feedbackQueueError ? (
          <p className="mt-3 text-sm text-rose-300">{feedbackQueueError}</p>
        ) : feedbackQueue.length === 0 ? (
          <p className="mt-3 text-sm text-slate-500">No open feedback.</p>
        ) : (
          <ul className="mt-4 space-y-3">
            {feedbackQueue.map((report) => (
              <li
                key={report.id}
                className={clsx(
                  "rounded-lg border p-3 text-sm",
                  theme === "dark"
                    ? "border-slate-800 bg-slate-900/70 text-slate-200"
                    : "border-slate-200 bg-white text-slate-700",
                )}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-col">
                    <span className={clsx("font-semibold", headingClass)}>
                      {report.symbol || "Unspecified"}
                    </span>
                    <span className="text-xs text-slate-500">
                      {report.filing_date
                        ? new Date(report.filing_date).toLocaleString()
                        : "No filing date"}
                    </span>
                  </div>
                  <span
                    className={clsx(
                      "rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase",
                      STATUS_BADGE_MAP[report.status] ||
                        "border-slate-500/40 bg-slate-600/10 text-slate-200",
                    )}
                  >
                    {formatStatusLabel(report.status)}
                  </span>
                </div>
                {report.public_token && (
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
                    Tracking token:{" "}
                    <button
                      type="button"
                      className="underline"
                      onClick={() => {
                        setFeedbackLookupToken(report.public_token || "");
                        setFeedbackLookupResult(null);
                        setFeedbackLookupError(null);
                      }}
                    >
                      {report.public_token}
                    </button>
                  </div>
                )}
                <p className={clsx("mt-1 text-xs uppercase", mutedTextClass)}>
                  {report.verdict ? `Verdict: ${report.verdict}` : "No verdict context"}
                </p>
                <p className={clsx("mt-2", bodyTextClass)}>{report.message}</p>
                {report.contact && (
                  <p className={clsx("mt-1 text-xs", mutedTextClass)}>
                    Contact: {report.contact}
                  </p>
                )}
                <textarea
                  className={clsx("mt-3 w-full rounded-md", textareaClass, "text-xs")}
                  placeholder="Reviewer notes…"
                  value={feedbackNotes[report.id] ?? ""}
                  onChange={(e) =>
                    setFeedbackNotes((prev) => ({
                      ...prev,
                      [report.id]: e.target.value,
                    }))
                  }
                />
                <div className="mt-2 flex flex-wrap items-center gap-3">
                  {report.status === "open" && (
                    <button
                      type="button"
                      className="rounded-md bg-amber-400 px-3 py-1 text-xs font-semibold text-slate-900 hover:bg-amber-300"
                      onClick={() =>
                        handleFeedbackStatusChange(report, "in_review", {
                          triggerRecompute: false,
                        })
                      }
                    >
                      Move to in-review
                    </button>
                  )}
                  {report.status === "in_review" && (
                    <button
                      type="button"
                      className="rounded-md bg-slate-600 px-3 py-1 text-xs font-semibold text-white hover:bg-slate-500"
                      onClick={() =>
                        handleFeedbackStatusChange(report, "open", {
                          triggerRecompute: false,
                        })
                      }
                    >
                      Re-open
                    </button>
                  )}
                  <button
                    type="button"
                    className="rounded-md bg-emerald-500 px-3 py-1 text-xs font-semibold text-slate-950 hover:bg-emerald-400"
                    onClick={() =>
                      handleFeedbackStatusChange(report, "resolved", {
                        triggerRecompute: feedbackRecompute[report.id] ?? true,
                      })
                    }
                  >
                    Resolve
                  </button>
                  <label className="flex items-center gap-1 text-[11px] text-slate-400">
                    <input
                      type="checkbox"
                      className="h-3 w-3 accent-emerald-400"
                      checked={feedbackRecompute[report.id] ?? true}
                      onChange={(e) =>
                        setFeedbackRecompute((prev) => ({
                          ...prev,
                          [report.id]: e.target.checked,
                        }))
                      }
                    />
                    Re-run ratios on resolve
                  </label>
                </div>
                <div className={clsx("mt-2 text-[11px]", mutedTextClass)}>
                  Submitted {new Date(report.created_at).toLocaleString()} • Last update{" "}
                  {formatTimestamp(report.status_updated_at)}
                </div>
                {report.reevaluation_notes && (
                  <p className="mt-1 text-xs text-emerald-300">
                    Re-evaluation: {report.reevaluation_notes} (
                    {formatTimestamp(report.reevaluated_at)})
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

        <section className={clsx(CARD_CLASS(theme), "p-6")}>
        <div className="flex items-center justify-between">
          <h2 className={sectionTitleClass}>Ingestion stats</h2>
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
            className={refreshButtonClass}
          >
            Refresh
          </button>
        </div>
        {statsError ? (
          <p className={clsx("mt-2 text-sm", errorTextClass)}>{statsError}</p>
        ) : ingestionStats ? (
          <ul className="mt-3 grid gap-2 text-sm text-slate-200 sm:grid-cols-2">
            <li
              className={clsx(
                "rounded-lg border px-3 py-2",
                theme === "dark"
                  ? "border-slate-800 bg-slate-900/70"
                  : "border-slate-200 bg-white",
              )}
            >
              <p className={clsx("text-xs", mutedTextClass)}>Total announcements</p>
              <p className={clsx("text-xl font-semibold", headingClass)}>
                {ingestionStats.total_announcements}
              </p>
            </li>
            <li
              className={clsx(
                "rounded-lg border px-3 py-2",
                theme === "dark"
                  ? "border-slate-800 bg-slate-900/70"
                  : "border-slate-200 bg-white",
              )}
            >
              <p className={clsx("text-xs", mutedTextClass)}>Financial snapshots</p>
              <p className={clsx("text-xl font-semibold", headingClass)}>
                {ingestionStats.financial_snapshots}
              </p>
            </li>
            <li
              className={clsx(
                "rounded-lg border px-3 py-2",
                theme === "dark"
                  ? "border-slate-800 bg-slate-900/70"
                  : "border-slate-200 bg-white",
              )}
            >
              <p className={clsx("text-xs", mutedTextClass)}>High-confidence filings</p>
              <p className={clsx("text-xl font-semibold", headingClass)}>
                {ingestionStats.high_confidence}
              </p>
            </li>
            <li
              className={clsx(
                "rounded-lg border px-3 py-2",
                theme === "dark"
                  ? "border-slate-800 bg-slate-900/70"
                  : "border-slate-200 bg-white",
              )}
            >
              <p className={clsx("text-xs", mutedTextClass)}>Latest filing</p>
              <p className={clsx("text-sm font-semibold", headingClass)}>
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

        <section className={clsx(CARD_CLASS(theme), "p-6")}>
        <h2 className={sectionTitleClass}>Watchlist</h2>
        <p className={clsx("text-sm", mutedTextClass)}>
          Track compliance flips for symbols. Alerts trigger when verdict changes.
        </p>
        <div className="mt-4 flex gap-2">
          <input
            className={clsx(
              "flex-1 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-400/60",
              theme === "dark"
                ? "border border-white/10 bg-white/10 text-white placeholder:text-slate-400"
                : "border border-slate-200 bg-white text-slate-900 placeholder:text-slate-500",
            )}
            placeholder="Symbol (e.g., TCS)"
            value={watchlistSymbol}
            onChange={(e) => setWatchlistSymbol(e.target.value.toUpperCase())}
          />
          <button
            className="rounded-lg bg-gradient-to-r from-emerald-400 to-cyan-400 px-4 py-2 text-sm font-semibold text-slate-900 hover:opacity-90"
            onClick={handleAddWatchlist}
            type="button"
          >
            Add
          </button>
        </div>
        {watchlistError && (
          <p className={clsx("mt-2 text-sm", errorTextClass)}>{watchlistError}</p>
        )}
        <ul className="mt-4 space-y-2 text-sm text-slate-200">
          {watchlist.map((entry) => (
            <li
              key={`${entry.user_id}-${entry.symbol}-${entry.trigger}`}
              className={clsx(
                "rounded-lg border px-3 py-2",
                theme === "dark"
                  ? "border-white/5 bg-white/5 text-slate-200"
                  : "border-slate-200 bg-white text-slate-700",
              )}
            >
              <span className={clsx("font-semibold", headingClass)}>{entry.symbol}</span>{" "}
              <span className={clsx("text-xs uppercase", mutedTextClass)}>
                {entry.trigger.replace("_", " ")}
              </span>
            </li>
          ))}
          {watchlist.length === 0 && (
            <li className={clsx("text-slate-500", mutedTextClass)}>
              No watchlist entries yet.
            </li>
          )}
        </ul>
        </section>
      </main>
    </div>
  );
}

function Fieldset({
  legend,
  children,
  theme,
}: {
  legend: string;
  children: React.ReactNode;
  theme: Theme;
}) {
  return (
    <fieldset
      className={clsx(
        "space-y-4 rounded-xl border p-4",
        theme === "dark" ? "border-slate-800" : "border-slate-200 bg-white",
      )}
    >
      <legend
        className={clsx(
          "px-2 text-sm font-semibold",
          theme === "dark" ? "text-slate-300" : "text-slate-600",
        )}
      >
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
  theme,
}: {
  label: string;
  type?: string;
  required?: boolean;
  value: string;
  onChange: (value: string) => void;
  theme: Theme;
}) {
  return (
    <label className="space-y-1 text-sm">
      <span className={theme === "dark" ? "text-slate-400" : "text-slate-600"}>
        {label}
      </span>
      <input
        className={clsx(
          "w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-400/60",
          theme === "dark"
            ? "border-slate-700 bg-slate-900 text-white placeholder:text-slate-500"
            : "border-slate-200 bg-white text-slate-900 placeholder:text-slate-500",
        )}
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
  setForm: Dispatch<SetStateAction<FormState>>,
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
      non_permissible_income: stringifyNumber(
        filing.non_halal_income ?? filing.non_halal_income,
      ),
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

type MarketOverride = {
  market_cap?: number;
  trailing_market_cap?: number;
  share_price?: number;
};

function payloadFromFiling(
  filing: Filing,
  overrides?: MarketOverride,
): AnalysisPayload {
  const asNumber = (value?: number | null) =>
    typeof value === "number" ? value : undefined;
  return {
    snapshot: {
      symbol: filing.symbol,
      filing_date: filing.filing_date,
      total_debt: asNumber(filing.total_debt),
      cash_equiv: asNumber(filing.cash_equiv),
      revenue: asNumber(filing.revenue),
      interest_income: asNumber(filing.interest_income),
      dividend_income: asNumber(filing.dividend_income),
      non_permissible_income: asNumber(filing.non_halal_income),
    },
    market_data: {
      market_cap: asNumber(
        overrides?.market_cap ?? filing.market_cap_used ?? undefined,
      ),
      trailing_market_cap: asNumber(
        overrides?.trailing_market_cap ?? filing.trailing_cap_used ?? undefined,
      ),
      share_price: asNumber(overrides?.share_price),
    },
  };
}

function FilingDetails({
  filing,
  marketStatus,
  theme,
}: {
  filing: Filing;
  marketStatus: string | null;
  theme: Theme;
}) {
  const containerClass = clsx(
    "mt-4 rounded-xl border p-4 text-sm",
    theme === "dark"
      ? "border-slate-800 bg-slate-900/60 text-slate-200"
      : "border-slate-200 bg-white text-slate-700",
  );
  const labelClass = theme === "dark" ? "text-slate-400" : "text-slate-600";
  const valueClass = theme === "dark" ? "text-white" : "text-slate-900";
  const entries = [
    ["Company", filing.company_name || "—"],
    ["Category", filing.category || "—"],
    ["Confidence", filing.confidence || "—"],
    ["Total debt", displayNumber(filing.total_debt)],
    ["Cash equivalents", displayNumber(filing.cash_equiv)],
    ["Revenue", displayNumber(filing.revenue)],
    ["Interest income", displayNumber(filing.interest_income)],
    ["Dividend income", displayNumber(filing.dividend_income)],
    ["Accounts receivable", displayNumber(filing.accounts_receivable)],
    ["Liquid assets", displayNumber(filing.liquid_assets)],
    ["Audit status", filing.audit_status || "—"],
  ];
  return (
    <div className={containerClass}>
      <h3 className={clsx("text-base font-semibold", valueClass)}>
        Selected filing: {filing.symbol}
      </h3>
      <p className={clsx("text-xs", labelClass)}>
        Filing date: {new Date(filing.filing_date).toLocaleDateString()}
      </p>
      <ul className="mt-3 space-y-1">
        {entries.map(([label, value]) => (
          <li key={label} className="flex items-center justify-between">
            <span className={labelClass}>{label}</span>
            <span className={valueClass}>{value}</span>
          </li>
        ))}
      </ul>
      {marketStatus && (
        <p
          className={clsx(
            "mt-2 text-xs",
            theme === "dark" ? "text-cyan-400" : "text-cyan-600",
          )}
        >
          {marketStatus}
        </p>
      )}
      {filing.verdict && (
        <div
          className={clsx(
            "mt-3 rounded-lg border p-3",
            theme === "dark"
              ? "border-slate-800 bg-slate-900/80"
              : "border-slate-200 bg-slate-50",
          )}
        >
          <p className={clsx("text-xs uppercase", labelClass)}>Automated verdict</p>
          <p
            className={`text-sm font-semibold ${verdictBadgeClass(
              filing.verdict,
            )}`}
          >
            {formatVerdict(filing.verdict)}
          </p>
          {filing.summary && (
            <p className={clsx("mt-1 text-xs", labelClass)}>{filing.summary}</p>
          )}
          {filing.governance_notes && (
            <p className="mt-1 text-xs text-amber-500">
              {filing.governance_notes}
            </p>
          )}
        </div>
      )}
      <p className={clsx("mt-3 text-xs", labelClass)}>
        Market data auto-fills when available; you can still override values
        before analyzing.
      </p>
      {filing.governance_override_applied && (
        <p className="mt-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-700">
          Manual governance override applied
          {filing.governance_override_reviewer && ` by ${filing.governance_override_reviewer}`}
          {filing.governance_override_updated_at &&
            ` on ${new Date(filing.governance_override_updated_at).toLocaleString()}`}
          {filing.governance_override_reason && `. Reason: ${filing.governance_override_reason}`}
        </p>
      )}
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

function formatProviderLabel(provider?: string | null) {
  if (!provider) return "";
  return PROVIDER_LABELS[provider] || provider.toUpperCase();
}

function applyMarketStatusForFiling(
  filing: Filing,
  setMarketStatus: (value: string | null) => void,
) {
  if (hasStoredMarketData(filing)) {
    const label = formatProviderLabel(filing.market_data_provider);
    setMarketStatus(
      label
        ? `Auto-filled via ${label}`
        : "Using stored market data from ingestion pipeline.",
    );
  } else {
    setMarketStatus("Fetching latest market data…");
  }
}

async function handleAnalyzeFiling(
  filing: Filing,
  setForm: Dispatch<SetStateAction<FormState>>,
  setSelectedFiling: (filing: Filing) => void,
  setMarketStatus: (status: string | null) => void,
  runAnalysis: () => Promise<void>,
  setWatchlistSymbol: (value: string) => void,
  loadHistory: (symbol?: string) => Promise<void>,
) {
  setSelectedFiling(filing);
  setFormFromFiling(filing, setForm);
  setWatchlistSymbol(filing.symbol);
  await loadHistory(filing.symbol);
  applyMarketStatusForFiling(filing, setMarketStatus);
  if (!hasStoredMarketData(filing)) {
    await fetchAndApplyMarketData(filing.symbol, setForm, setMarketStatus);
  }
  await runAnalysis();
}

function handleSelectFiling(
  filing: Filing,
  setForm: Dispatch<SetStateAction<FormState>>,
  setSelectedFiling: (filing: Filing) => void,
  setMarketStatus: (status: string | null) => void,
  setWatchlistSymbol: (value: string) => void,
  loadHistory: (symbol?: string) => Promise<void>,
) {
  setSelectedFiling(filing);
  setFormFromFiling(filing, setForm);
  setWatchlistSymbol(filing.symbol);
  loadHistory(filing.symbol);
  applyMarketStatusForFiling(filing, setMarketStatus);
  if (!hasStoredMarketData(filing)) {
    fetchAndApplyMarketData(filing.symbol, setForm, setMarketStatus);
  }
}

async function fetchAndApplyMarketData(
  symbol: string,
  setForm: Dispatch<SetStateAction<FormState>>,
  setStatus: (value: string | null) => void,
) {
  setStatus("Fetching latest market data…");
  try {
    const quote = await fetchMarketQuote(symbol);
    setForm((prev: FormState) => ({
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
    const providerLabel = formatProviderLabel(quote.provider);
    setStatus(
      providerLabel
        ? `Auto-filled via ${providerLabel}`
        : "Auto-filled via live quote",
    );
  } catch (err) {
    setStatus(MANUAL_MARKET_MESSAGE);
  }
}
