"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";

import type { Filing, GovernanceOverride, GovernanceReview } from "@/lib/types";
import { fetchFilingDetail } from "@/lib/filings";
import {
  fetchGovernanceOverrides,
  upsertGovernanceOverride,
  deleteGovernanceOverride,
  fetchGovernanceReview,
} from "@/lib/governance";
import { GovernanceReviewPanel } from "@/components/governance-review";
import { useAuth } from "@/providers/AuthProvider";
import { useTheme } from "@/providers/ThemeProvider";

const defaultOverrideForm = {
  accounts_receivable: "",
  liquid_assets: "",
  non_halal_income: "",
  governance_notes: "",
  reason: "",
  reviewer: "",
};

function stringifyNumber(value?: number | null) {
  if (value === null || value === undefined) return "";
  return String(value);
}

function parseOverrideNumber(value: string) {
  if (!value) return undefined;
  const parsed = Number(value);
  return Number.isNaN(parsed) ? undefined : parsed;
}

export default function GovernancePage() {
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
  const [selectedFiling, setSelectedFiling] = useState<Filing | null>(null);
  const [loadingFiling, setLoadingFiling] = useState(false);
  const [filingError, setFilingError] = useState<string | null>(null);

  const [governanceOverrides, setGovernanceOverrides] = useState<GovernanceOverride[]>([]);
  const [overrideForm, setOverrideForm] = useState({ ...defaultOverrideForm });
  const [overrideStatus, setOverrideStatus] = useState<string | null>(null);
  const [overrideError, setOverrideError] = useState<string | null>(null);
  const [overrideLoading, setOverrideLoading] = useState(false);

  const [governanceReview, setGovernanceReview] = useState<GovernanceReview | null>(null);
  const [governanceReviewError, setGovernanceReviewError] = useState<string | null>(null);
  const [governanceReviewLoading, setGovernanceReviewLoading] = useState(false);

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
  const textareaClass = clsx(
    "w-full rounded-xl border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-400/60",
    theme === "dark"
      ? "border-slate-700 bg-slate-900 text-white placeholder:text-slate-500"
      : "border-slate-200 bg-white text-slate-900 placeholder:text-slate-500",
  );

  const refreshOverrides = async (targetSymbol?: string) => {
    if (!targetSymbol) {
      setGovernanceOverrides([]);
      return;
    }
    try {
      const rows = await fetchGovernanceOverrides(targetSymbol, 25);
      setGovernanceOverrides(rows);
    } catch (err: any) {
      setGovernanceOverrides([]);
      setOverrideError(err.message ?? "Unable to load overrides.");
    }
  };

  const loadGovernanceReview = async (targetSymbol?: string, filingDate?: string) => {
    if (!targetSymbol || !filingDate) {
      setGovernanceReview(null);
      setGovernanceReviewError(null);
      return;
    }
    setGovernanceReviewLoading(true);
    try {
      const data = await fetchGovernanceReview(targetSymbol, filingDate);
      setGovernanceReview(data);
      setGovernanceReviewError(null);
    } catch (err: any) {
      setGovernanceReview(null);
      setGovernanceReviewError(err.message ?? "Unable to load governance review.");
    } finally {
      setGovernanceReviewLoading(false);
    }
  };

  useEffect(() => {
    if (selectedFiling) {
      refreshOverrides(selectedFiling.symbol);
      loadGovernanceReview(selectedFiling.symbol, selectedFiling.filing_date);
    } else {
      setGovernanceOverrides([]);
      setGovernanceReview(null);
    }
  }, [selectedFiling]);

  const loadLatestFiling = async () => {
    const trimmed = symbol.trim();
    if (!trimmed) return;
    setLoadingFiling(true);
    setFilingError(null);
    try {
      const filing = await fetchFilingDetail(trimmed, { refresh: true });
      setSelectedFiling(filing);
    } catch (err: any) {
      setSelectedFiling(null);
      setFilingError(err.message ?? "Unable to load filing.");
    } finally {
      setLoadingFiling(false);
    }
  };

  const handleOverrideSubmit = async () => {
    if (!hasPaidAccess) {
      setOverrideError("Upgrade to unlock governance overrides.");
      return;
    }
    const targetSymbol = selectedFiling?.symbol || symbol.trim().toUpperCase();
    const filingDate = selectedFiling?.filing_date;
    if (!targetSymbol || !filingDate) {
      setOverrideError("Load a filing before applying overrides.");
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
      await upsertGovernanceOverride({
        symbol: targetSymbol,
        filing_date: filingDate,
        accounts_receivable: parseOverrideNumber(overrideForm.accounts_receivable),
        liquid_assets: parseOverrideNumber(overrideForm.liquid_assets),
        non_halal_income: parseOverrideNumber(overrideForm.non_halal_income),
        governance_notes: overrideForm.governance_notes.trim() || undefined,
        reason: overrideForm.reason.trim() || undefined,
        reviewer: overrideForm.reviewer.trim() || undefined,
      });
      setOverrideStatus("Override saved.");
      await refreshOverrides(targetSymbol);
    } catch (err: any) {
      setOverrideError(err.message ?? "Unable to save override.");
    } finally {
      setOverrideLoading(false);
    }
  };

  const handleOverrideDelete = async (entry: GovernanceOverride) => {
    try {
      if (!hasPaidAccess) {
        throw new Error("Upgrade to unlock governance overrides.");
      }
      await deleteGovernanceOverride(entry.symbol, entry.filing_date);
      setOverrideStatus("Override removed.");
      await refreshOverrides(entry.symbol);
    } catch (err: any) {
      setOverrideError(err.message ?? "Unable to delete override.");
    }
  };

  const handleApplyIndianMetrics = (
    metrics: Record<string, number | null | undefined>,
  ) => {
    if (!hasPaidAccess) {
      setOverrideError("Upgrade to unlock governance overrides.");
      return;
    }
    const toInput = (value?: number | null) =>
      stringifyNumber(typeof value === "number" ? value : undefined);
    setOverrideForm((prev) => ({
      ...prev,
      accounts_receivable: toInput(metrics.accounts_receivable),
      liquid_assets: toInput(metrics.liquid_assets),
      non_halal_income: toInput(metrics.non_halal_income),
    }));
    setOverrideStatus("Indian API metrics copied to override form.");
  };

  return (
    <main className="space-y-10">
      <header className={cardClass}>
        <h1 className={clsx("text-3xl font-semibold text-display", headingClass)}>
          Governance overrides
        </h1>
        <p className={clsx("mt-2", mutedTextClass)}>
          Apply structured corrections when extracted AAOIFI metrics disagree with
          filings or Indian API values.
        </p>
        <div className="mt-4 grid gap-3 md:grid-cols-[1fr_auto]">
          <input
            className={inputClass}
            placeholder="Enter a symbol to review (e.g., TCS)"
            value={symbol}
            onChange={(event) => setSymbol(event.target.value.toUpperCase())}
          />
          <button
            type="button"
            onClick={loadLatestFiling}
            className="rounded-lg bg-gradient-to-r from-cyan-400 to-emerald-400 px-4 py-2 text-sm font-semibold text-slate-950 hover:opacity-90"
          >
            {loadingFiling ? "Loading…" : "Load latest filing"}
          </button>
        </div>
        {filingError && <p className="mt-2 text-sm text-rose-400">{filingError}</p>}
        {selectedFiling && (
          <p className={clsx("mt-2 text-xs", mutedTextClass)}>
            Reviewing {selectedFiling.symbol} · Filing date{" "}
            {new Date(selectedFiling.filing_date).toLocaleDateString()}
          </p>
        )}
        {!hasPaidAccess && (
          <p className={clsx("mt-2 text-xs", mutedTextClass)}>
            Governance overrides require the Starter plan.
          </p>
        )}
      </header>

      <section className={cardClass}>
        <GovernanceReviewPanel
          review={governanceReview}
          loading={governanceReviewLoading}
          error={governanceReviewError}
          theme={theme}
          onApplyIndian={handleApplyIndianMetrics}
        />

        <div className="mt-6 grid gap-4 md:grid-cols-2">
          <TextInput
            label="Accounts receivable override"
            value={overrideForm.accounts_receivable}
            onChange={(value) =>
              setOverrideForm((prev) => ({ ...prev, accounts_receivable: value }))
            }
            theme={theme}
          />
          <TextInput
            label="Liquid assets override"
            value={overrideForm.liquid_assets}
            onChange={(value) =>
              setOverrideForm((prev) => ({ ...prev, liquid_assets: value }))
            }
            theme={theme}
          />
          <TextInput
            label="Non-permissible income override"
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

        <div className="mt-4 grid gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className={mutedTextClass}>Override notes</span>
            <textarea
              className={clsx("min-h-[70px]", textareaClass)}
              value={overrideForm.governance_notes}
              onChange={(event) =>
                setOverrideForm((prev) => ({
                  ...prev,
                  governance_notes: event.target.value,
                }))
              }
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className={mutedTextClass}>Reason</span>
            <input
              className={textareaClass}
              value={overrideForm.reason}
              onChange={(event) =>
                setOverrideForm((prev) => ({ ...prev, reason: event.target.value }))
              }
            />
          </label>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={handleOverrideSubmit}
            className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-slate-900 hover:bg-emerald-400 disabled:opacity-60"
            disabled={overrideLoading || !hasPaidAccess}
          >
            {overrideLoading ? "Saving…" : "Apply override"}
          </button>
          {overrideStatus && (
            <span className="text-xs text-emerald-300">{overrideStatus}</span>
          )}
          {overrideError && (
            <span className="text-xs text-rose-300">{overrideError}</span>
          )}
        </div>
      </section>

      <section className={cardClass}>
        <div className="flex items-center justify-between">
          <h2 className={clsx("text-lg font-semibold", headingClass)}>Override history</h2>
          <button
            type="button"
            className={clsx(
              "text-xs font-semibold",
              theme === "dark" ? "text-cyan-300" : "text-cyan-700",
            )}
            onClick={() => refreshOverrides(selectedFiling?.symbol)}
            disabled={!selectedFiling}
          >
            Refresh
          </button>
        </div>
        {governanceOverrides.length === 0 ? (
          <p className={clsx("mt-3 text-sm", mutedTextClass)}>
            {selectedFiling
              ? "No overrides for this symbol yet."
              : "Load a symbol to view overrides."}
          </p>
        ) : (
          <div className="mt-4 space-y-3">
            {governanceOverrides.map((entry) => (
              <div
                key={`${entry.symbol}-${entry.filing_date}`}
                className={clsx(
                  "rounded-lg border px-3 py-3 text-sm",
                  theme === "dark"
                    ? "border-slate-800 bg-slate-900/70 text-slate-200"
                    : "border-slate-200 bg-white text-slate-700",
                )}
              >
                <div className="flex items-center justify-between text-xs">
                  <span className={mutedTextClass}>
                    {entry.symbol} · {new Date(entry.filing_date).toLocaleString()}
                  </span>
                  <button
                    type="button"
                    className="text-rose-400 hover:text-rose-300"
                    onClick={() => handleOverrideDelete(entry)}
                    disabled={!hasPaidAccess}
                  >
                    Remove
                  </button>
                </div>
                <p className="mt-1 text-xs text-slate-400">
                  Reviewer: {entry.reviewer || "—"} · Source: {entry.source || "manual"}
                </p>
                <p className="mt-2 text-sm">
                  AR={entry.accounts_receivable ?? "—"} · Liquid={entry.liquid_assets ?? "—"}
                  {" · "}Non-halal={entry.non_halal_income ?? "—"}
                </p>
                {entry.governance_notes && (
                  <p className="text-xs text-amber-300">{entry.governance_notes}</p>
                )}
                {entry.reason && (
                  <p className={clsx("text-xs", mutedTextClass)}>Reason: {entry.reason}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}

function TextInput({
  label,
  value,
  onChange,
  theme,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  theme: "dark" | "light";
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className={theme === "dark" ? "text-slate-400" : "text-slate-500"}>
        {label}
      </span>
      <input
        className={clsx(
          "w-full rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-400/60",
          theme === "dark"
            ? "border border-white/10 bg-white/10 text-white"
            : "border border-slate-200 bg-white text-slate-900",
        )}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}
