"use client";

import clsx from "clsx";
import { Filing } from "@/lib/types";
import { cardClass, eyebrowClass, VerdictBadge } from "@/components/ui";

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
};

export function HistoryTimeline({ entries, activeKey, onSelect }: Props) {
  if (!entries.length) {
    return null;
  }

  return (
    <article className={clsx(cardClass, "p-5")}>
      <header className="mb-4 flex items-center justify-between gap-3 text-sm">
        <div>
          <p className={eyebrowClass}>History & trends</p>
          <h2 className="mt-1 text-lg font-semibold text-fg">{entries[0]?.symbol}</h2>
        </div>
        <p className="text-xs text-muted">Showing last {entries.length} filings</p>
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
                  "w-full rounded-lg border px-3 py-3 text-left transition motion-reduce:transition-none",
                  isActive
                    ? "border-brand/60 bg-brand/5"
                    : "border-line bg-surface hover:border-brand/40 hover:bg-surface-2",
                )}
              >
                <div className="flex items-center justify-between text-xs text-muted">
                  <span className="font-mono tabular-nums">
                    {new Date(entry.filing_date).toLocaleDateString()}
                  </span>
                  {entry.verdict && <VerdictBadge verdict={entry.verdict} />}
                </div>
                {entry.summary && (
                  <p className="mt-1 line-clamp-2 text-sm text-fg">{entry.summary}</p>
                )}
                <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
                  {RATIO_ROWS.map((ratio) => (
                    <RatioChip
                      key={ratio.key}
                      entry={entry}
                      ratioKey={ratio.key}
                      label={ratio.label}
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
}: {
  entry: Filing;
  ratioKey: string;
  label: string;
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
        "rounded-md border px-2 py-1",
        status === "pass" && "border-success/30 bg-success/10",
        status === "fail" && "border-danger/30 bg-danger/10",
        status === "missing" && "border-line bg-surface-2",
      )}
    >
      <p className="font-mono text-[11px] uppercase tracking-wide text-muted">{label}</p>
      <p
        className={clsx(
          "font-mono text-sm font-semibold tabular-nums",
          status === "pass" && "text-success",
          status === "fail" && "text-danger",
          status === "missing" && "text-fg",
        )}
      >
        {value}
      </p>
      {status === "missing" && (
        <p className="text-[10px] text-muted">Missing inputs</p>
      )}
    </div>
  );
}
