"use client";

import clsx from "clsx";
import { Filing } from "@/lib/types";

const RATIO_ROWS = [
  { key: "debt_to_market_cap", label: "Debt / Cap" },
  { key: "cash_to_market_cap", label: "Cash / Cap" },
  { key: "receivables_to_market_cap", label: "Receivables / Cap" },
  { key: "liquid_assets_to_market_cap", label: "Liquid / Cap" },
  { key: "non_permissible_income_ratio", label: "Non-permissible / Rev" },
];

type Props = {
  entries: Filing[];
  activeKey?: string;
  onSelect?: (entry: Filing) => void;
  theme?: "dark" | "light";
};

export function HistoryTimeline({
  entries,
  activeKey,
  onSelect,
  theme = "dark",
}: Props) {
  if (!entries.length) {
    return null;
  }

  return (
    <article
      className={clsx(
        "rounded-2xl border p-4",
        theme === "dark"
          ? "border-slate-800 bg-slate-900/50"
          : "border-slate-200 bg-white",
      )}
    >
      <header className="mb-4 flex items-center justify-between text-sm">
        <div>
          <p
            className={clsx(
              "text-xs uppercase",
              theme === "dark" ? "text-slate-500" : "text-slate-600",
            )}
          >
            History & trends
          </p>
          <h2
            className={clsx(
              "text-lg font-semibold",
              theme === "dark" ? "text-white" : "text-slate-900",
            )}
          >
            {entries[0]?.symbol}
          </h2>
        </div>
        <p className={clsx("text-xs", theme === "dark" ? "text-slate-500" : "text-slate-600")}>
          Showing last {entries.length} filings
        </p>
      </header>
      <ul className="space-y-3">
        {entries.map((entry) => {
          const key = `${entry.symbol}-${entry.filing_date}`;
          const isActive = key === activeKey;
          return (
            <li key={key}>
              <button
                type="button"
                onClick={() => onSelect?.(entry)}
                className={clsx(
                  "w-full rounded-xl border px-3 py-3 text-left transition",
                  isActive
                    ? "border-cyan-500/60 bg-cyan-500/10"
                    : theme === "dark"
                      ? "border-slate-800 bg-slate-900/60 hover:border-cyan-400/60 hover:bg-slate-900"
                      : "border-slate-200 bg-white hover:border-cyan-300 hover:bg-cyan-50",
                )}
              >
                <div
                  className={clsx(
                    "flex items-center justify-between text-xs",
                    theme === "dark" ? "text-slate-400" : "text-slate-600",
                  )}
                >
                  <span>
                    {new Date(entry.filing_date).toLocaleDateString()}
                  </span>
                  {entry.verdict && (
                    <span
                      className={clsx(
                        "rounded-full px-2 py-0.5 text-[11px] font-semibold",
                        verdictBadge(entry.verdict, theme),
                      )}
                    >
                      {formatVerdict(entry.verdict)}
                    </span>
                  )}
                </div>
                {entry.summary && (
                  <p
                    className={clsx(
                      "mt-1 text-sm line-clamp-2",
                      theme === "dark" ? "text-slate-200" : "text-slate-700",
                    )}
                  >
                    {entry.summary}
                  </p>
                )}
                <div
                  className={clsx(
                    "mt-3 grid gap-2 text-xs sm:grid-cols-2",
                    theme === "dark" ? "text-slate-300" : "text-slate-700",
                  )}
                >
                  {RATIO_ROWS.map((ratio) => (
                    <RatioChip
                      key={ratio.key}
                      entry={entry}
                      ratioKey={ratio.key}
                      label={ratio.label}
                      theme={theme}
                    />
                  ))}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </article>
  );
}

function RatioChip({
  entry,
  ratioKey,
  label,
  theme = "dark",
}: {
  entry: Filing;
  ratioKey: string;
  label: string;
  theme?: "dark" | "light";
}) {
  const ratio = entry.ratios?.[ratioKey];
  const value =
    typeof ratio?.value === "number"
      ? `${(ratio.value * 100).toFixed(2)}%`
      : "—";
  const status =
    ratio?.passed === null
      ? "missing"
      : ratio?.passed
        ? "pass"
        : "fail";
  return (
    <div
      className={clsx(
        "rounded-lg border px-2 py-1",
        status === "pass" && "border-emerald-500/40 bg-emerald-500/10",
        status === "fail" && "border-rose-500/40 bg-rose-500/10",
        status === "missing" &&
          (theme === "dark"
            ? "border-slate-700 bg-slate-900/40"
            : "border-slate-200 bg-slate-50"),
      )}
    >
      <p
        className={clsx(
          "text-[11px] uppercase tracking-wide",
          theme === "dark" ? "text-slate-400" : "text-slate-500",
        )}
      >
        {label}
      </p>
      <p
        className={clsx(
          "text-sm font-semibold",
          theme === "dark" ? "text-white" : "text-slate-900",
        )}
      >
        {value}
      </p>
      {status === "missing" && (
        <p className="text-[10px] text-slate-500">Missing inputs</p>
      )}
    </div>
  );
}

function verdictBadge(verdict: string, theme: "dark" | "light") {
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
