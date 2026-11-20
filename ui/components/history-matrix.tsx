"use client";

import clsx from "clsx";
import { Filing } from "@/lib/types";
import { cardClass, eyebrowClass, VerdictBadge } from "@/components/ui";

const RATIO_DEFS = [
  { key: "debt_to_market_cap", label: "Debt / Cap" },
  { key: "cash_to_market_cap", label: "Cash / Cap" },
  { key: "receivables_to_market_cap", label: "Receivables / Cap" },
  { key: "liquid_assets_to_market_cap", label: "Liquid / Cap" },
  { key: "non_permissible_income_ratio", label: "Non-permissible / Rev" },
];

type MatrixProps = {
  entries: Filing[];
  selectedKey?: string;
  onSelect?: (entry: Filing) => void;
};

export function HistoryMatrix({ entries, selectedKey, onSelect }: MatrixProps) {
  if (!entries.length) return null;

  return (
    <article className={clsx(cardClass, "p-5")}>
      <header className="mb-4">
        <p className={eyebrowClass}>Ratio comparisons</p>
        <h2 className="mt-1 text-lg font-semibold text-fg">Quarter-over-quarter</h2>
      </header>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line text-xs text-muted">
            <tr>
              <th className="pb-2 pr-3 font-medium">Filing date</th>
              <th className="pb-2 pr-3 font-medium">Verdict</th>
              {RATIO_DEFS.map((ratio) => (
                <th key={ratio.key} className="pb-2 pr-3 font-medium">
                  {ratio.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr
                key={`${entry.symbol}-${entry.filing_date}`}
                className="border-b border-line last:border-0"
              >
                <td className="py-2 pr-3 font-mono text-xs tabular-nums text-muted">
                  {new Date(entry.filing_date).toLocaleDateString()}
                </td>
                <td className="py-2 pr-3">
                  {entry.verdict ? (
                    <VerdictBadge verdict={entry.verdict} />
                  ) : (
                    <span className="text-xs text-muted">n/a</span>
                  )}
                </td>
                {RATIO_DEFS.map((ratio) => (
                  <td key={ratio.key} className="py-2 pr-3">
                    <RatioCell
                      entry={entry}
                      ratioKey={ratio.key}
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
  isActive?: boolean;
  onSelect?: (entry: Filing) => void;
};

function RatioCell({ entry, ratioKey, isActive, onSelect }: RatioCellProps) {
  const computation = entry.ratios?.[ratioKey];
  const status =
    !computation || computation.passed === null || computation.value === null
      ? "missing"
      : computation.passed
        ? "pass"
        : "fail";

  const valueLabel =
    status === "missing" ? "—" : `${(computation!.value! * 100).toFixed(2)}%`;

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
        "w-full rounded-md border px-2 py-1 font-mono text-xs font-semibold tabular-nums transition motion-reduce:transition-none",
        status === "pass" && "border-success/30 bg-success/10 text-success",
        status === "fail" && "border-danger/30 bg-danger/10 text-danger",
        status === "missing" && "cursor-not-allowed border-line bg-surface-2 text-muted opacity-60",
        isActive && "ring-2 ring-brand/50",
      )}
    >
      {valueLabel}
    </button>
  );
}
