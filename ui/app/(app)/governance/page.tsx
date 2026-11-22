"use client";

import { useState } from "react";

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
import { Card, EmptyState, PageHeader, buttonClass, inputClass, labelClass } from "@/components/ui";
import { hasGovernanceAccess } from "@/lib/subscription";

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
  const { user } = useAuth();
  const canOverride = hasGovernanceAccess(user);

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

  const loadLatestFiling = async () => {
    const trimmed = symbol.trim();
    if (!trimmed) return;
    setLoadingFiling(true);
    setFilingError(null);
    try {
      const filing = await fetchFilingDetail(trimmed, { refresh: true });
      setSelectedFiling(filing);
      // Not awaited: both load alongside, each handling its own errors.
      refreshOverrides(filing.symbol);
      loadGovernanceReview(filing.symbol, filing.filing_date);
    } catch (err: any) {
      setSelectedFiling(null);
      setGovernanceOverrides([]);
      setGovernanceReview(null);
      setFilingError(err.message ?? "Unable to load filing.");
    } finally {
      setLoadingFiling(false);
    }
  };

  const handleOverrideSubmit = async () => {
    if (!canOverride) {
      setOverrideError("Governance overrides are limited to admin accounts.");
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
      if (!canOverride) {
        throw new Error("Governance overrides are limited to admin accounts.");
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
    if (!canOverride) {
      setOverrideError("Governance overrides are limited to admin accounts.");
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
    <>
      <PageHeader
        eyebrow="Admin"
        title="Governance overrides"
        description="Apply structured corrections when extracted AAOIFI metrics disagree with filings or Indian API values."
      />

      <Card>
        <div className="grid gap-3 md:grid-cols-[1fr_auto]">
          <input
            className={inputClass}
            aria-label="Symbol"
            placeholder="Enter a symbol to review (e.g., TCS)"
            value={symbol}
            onChange={(event) => setSymbol(event.target.value.toUpperCase())}
          />
          <button type="button" onClick={loadLatestFiling} className={buttonClass("primary")}>
            {loadingFiling ? "Loading…" : "Load latest filing"}
          </button>
        </div>
        {filingError && <p className="mt-2 text-sm text-danger">{filingError}</p>}
        {selectedFiling && (
          <p className="mt-2 text-xs text-muted">
            Reviewing <span className="font-mono text-fg">{selectedFiling.symbol}</span> · Filing date{" "}
            <span className="font-mono tabular-nums">{new Date(selectedFiling.filing_date).toLocaleDateString()}</span>
          </p>
        )}
        {!canOverride && (
          <p className="mt-2 text-xs text-muted">
            Governance overrides are limited to admin accounts.
          </p>
        )}
      </Card>

      <Card className="space-y-5">
        <GovernanceReviewPanel
          review={governanceReview}
          loading={governanceReviewLoading}
          error={governanceReviewError}
          onApplyIndian={handleApplyIndianMetrics}
        />

        <div className="grid gap-4 md:grid-cols-2">
          <TextInput
            label="Accounts receivable override"
            value={overrideForm.accounts_receivable}
            onChange={(value) =>
              setOverrideForm((prev) => ({ ...prev, accounts_receivable: value }))
            }
          />
          <TextInput
            label="Liquid assets override"
            value={overrideForm.liquid_assets}
            onChange={(value) =>
              setOverrideForm((prev) => ({ ...prev, liquid_assets: value }))
            }
          />
          <TextInput
            label="Non-permissible income override"
            value={overrideForm.non_halal_income}
            onChange={(value) =>
              setOverrideForm((prev) => ({ ...prev, non_halal_income: value }))
            }
          />
          <TextInput
            label="Reviewer name"
            value={overrideForm.reviewer}
            onChange={(value) =>
              setOverrideForm((prev) => ({ ...prev, reviewer: value }))
            }
          />
        </div>

        <div className="grid gap-4">
          <label className="flex flex-col gap-1.5">
            <span className={labelClass}>Override notes</span>
            <textarea
              className={`min-h-[70px] ${inputClass}`}
              value={overrideForm.governance_notes}
              onChange={(event) =>
                setOverrideForm((prev) => ({
                  ...prev,
                  governance_notes: event.target.value,
                }))
              }
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className={labelClass}>Reason</span>
            <input
              className={inputClass}
              value={overrideForm.reason}
              onChange={(event) =>
                setOverrideForm((prev) => ({ ...prev, reason: event.target.value }))
              }
            />
          </label>
        </div>

        <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
          <button
            type="button"
            onClick={handleOverrideSubmit}
            className={buttonClass("primary")}
            disabled={overrideLoading || !canOverride}
          >
            {overrideLoading ? "Saving…" : "Apply override"}
          </button>
          {overrideStatus && (
            <span className="text-xs text-success">{overrideStatus}</span>
          )}
          {overrideError && (
            <span className="text-xs text-danger">{overrideError}</span>
          )}
        </div>
      </Card>

      <Card className="p-0">
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <h2 className="font-semibold text-fg">Override history</h2>
          <button
            type="button"
            className={buttonClass("ghost")}
            onClick={() => refreshOverrides(selectedFiling?.symbol)}
            disabled={!selectedFiling}
          >
            Refresh
          </button>
        </div>
        {governanceOverrides.length === 0 ? (
          <div className="p-5">
            <EmptyState
              title={
                selectedFiling
                  ? "No overrides for this symbol yet."
                  : "Load a symbol to view overrides."
              }
            />
          </div>
        ) : (
          <ul>
            {governanceOverrides.map((entry) => (
              <li
                key={`${entry.symbol}-${entry.filing_date}`}
                className="border-b border-line px-5 py-3 text-sm last:border-0"
              >
                <div className="flex items-center justify-between gap-3 text-xs">
                  <span className="text-muted">
                    <span className="font-mono text-fg">{entry.symbol}</span> ·{" "}
                    <span className="font-mono tabular-nums">{new Date(entry.filing_date).toLocaleString()}</span>
                  </span>
                  <button
                    type="button"
                    className="font-semibold text-danger hover:underline disabled:opacity-60"
                    onClick={() => handleOverrideDelete(entry)}
                    disabled={!canOverride}
                  >
                    Remove
                  </button>
                </div>
                <p className="mt-1 text-xs text-muted">
                  Reviewer: {entry.reviewer || "—"} · Source: {entry.source || "manual"}
                </p>
                <p className="mt-2 font-mono text-sm tabular-nums text-fg">
                  AR={entry.accounts_receivable ?? "—"} · Liquid={entry.liquid_assets ?? "—"}
                  {" · "}Non-halal={entry.non_halal_income ?? "—"}
                </p>
                {entry.governance_notes && (
                  <p className="mt-1 text-xs text-warning">{entry.governance_notes}</p>
                )}
                {entry.reason && (
                  <p className="text-xs text-muted">Reason: {entry.reason}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}

function TextInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className={labelClass}>{label}</span>
      <input
        className={inputClass}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}
