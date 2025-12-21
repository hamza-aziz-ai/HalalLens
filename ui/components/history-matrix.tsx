"use client";

import clsx from "clsx";
import { Filing } from "@/lib/types";

const RATIO_DEFS = [
  { key: "debt_to_market_cap", label: "Debt / Cap" },
  { key: "cash_to_market_cap", label: "Cash / Cap" },
  { key: "receivables_to_market_cap", label: "Receivables / Cap" },
  { key: "non_permissible_income_ratio", label: "Non-permissible / Rev" },
];

type MatrixProps = {
  entries: Filing[];
  theme?: "dark" | "light";
  selectedKey?: string;
  onSelect?: (entry: Filing) => void;
};

export function HistoryMatrix({
  entries,
  theme = "dark",
  selectedKey,
  onSelect,
}: MatrixProps) {
  if (!entries.length) return null;

  const cardClass = clsx(
    "rounded-2xl border p-4",
    theme === "dark"
      ? "border-slate-800 bg-slate-900/50 text-slate-200"
      : "border-slate-200 bg-white text-slate-800",
  );

  return (
    <article className={cardClass}>
      <header className="mb-4">
        <p
          className={clsx(
            "text-xs uppercase",
            theme === "dark" ? "text-slate-500" : "text-slate-600",
          )}
        >
          Ratio comparisons
        </p>
        <h2
          className={clsx(
            "text-lg font-semibold",
            theme === "dark" ? "text-white" : "text-slate-900",
          )}
        >
          Quarter-over-quarter
        </h2>
      </header>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead
            className={clsx(
              "text-xs uppercase",
              theme === "dark" ? "text-slate-400" : "text-slate-500",
            )}
          >
            <tr>
              <th className="pb-2 pr-3">Filing date</th>
              <th className="pb-2 pr-3">Verdict</th>
              {RATIO_DEFS.map((ratio) => (
                <th key={ratio.key} className="pb-2 pr-3">
                  {ratio.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody
            className={clsx(
              "divide-y",
              theme === "dark" ? "divide-white/10" : "divide-slate-200",
            )}
          >
            {entries.map((entry) => (
              <tr key={`${entry.symbol}-${entry.filing_date}`}>
                <td className="py-2 text-xs">
                  {new Date(entry.filing_date).toLocaleDateString()}
                </td>
                <td className="py-2">
                  <span
                    className={clsx(
                      "rounded-full px-2 py-0.5 text-xs font-semibold",
                      verdictBadge(entry.verdict, theme),
                    )}
                  >
                    {entry.verdict ? formatVerdict(entry.verdict) : "—"}
                  </span>
                </td>
                {RATIO_DEFS.map((ratio) => (
                  <td key={ratio.key} className="py-2 pr-3">
                    <RatioCell
                      entry={entry}
                      ratioKey={ratio.key}
                      theme={theme}
                      isActive={selectedKey === `${entry.symbol}-${entry.filing_date}`}
                      onSelect={onSelect}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}

type RatioCellProps = {
  entry: Filing;
  ratioKey: string;
  theme: "dark" | "light";
  isActive?: boolean;
  onSelect?: (entry: Filing) => void;
};

function RatioCell({ entry, ratioKey, theme, isActive, onSelect }: RatioCellProps) {
  const computation = entry.ratios?.[ratioKey];
  const status =
    !computation || computation.passed === null || computation.value === null
      ? "missing"
      : computation.passed
        ? "pass"
        : "fail";

  const valueLabel =
    status === "missing" ? "—" : `${(computation!.value! * 100).toFixed(2)}%`;

  const baseClass =
    status === "pass"
      ? theme === "dark"
        ? "bg-emerald-500/15 text-emerald-200 border-emerald-500/30"
        : "bg-emerald-100 text-emerald-700 border-emerald-200"
      : status === "fail"
        ? theme === "dark"
          ? "bg-rose-500/15 text-rose-200 border-rose-500/30"
          : "bg-rose-100 text-rose-700 border-rose-200"
        : theme === "dark"
          ? "bg-slate-800/60 text-slate-400 border-slate-700"
          : "bg-slate-100 text-slate-500 border-slate-200";

  return (
    <button
      type="button"
      disabled={status === "missing"}
      title={status === "missing" ? "Missing inputs" : `${valueLabel}`}
      onClick={() => {
        if (status !== "missing" && onSelect) {
          onSelect(entry);
        }
      }}
      className={clsx(
        "w-full rounded-md border px-2 py-1 text-xs font-semibold transition focus:outline-none",
        baseClass,
        status === "missing" && "opacity-60 cursor-not-allowed",
        isActive &&
          (theme === "dark"
            ? "ring-2 ring-cyan-400/60"
            : "ring-2 ring-cyan-500/50"),
      )}
    >
      {valueLabel}
    </button>
  );
}

function verdictBadge(verdict: string | null | undefined, theme: "dark" | "light") {
  if (verdict === "compliant") {
    return theme === "dark"
      ? "bg-emerald-500/15 text-emerald-300"
      : "bg-emerald-100 text-emerald-700";
  }
  if (verdict === "non-compliant") {
    return theme === "dark"
      ? "bg-rose-500/15 text-rose-300"
      : "bg-rose-100 text-rose-700";
  }
  return theme === "dark"
    ? "bg-amber-500/15 text-amber-300"
    : "bg-amber-100 text-amber-700";
}

function formatVerdict(verdict: string) {
  return verdict
    .split("-")
    .map((chunk) => chunk.charAt(0).toUpperCase() + chunk.slice(1))
    .join(" ");
}
