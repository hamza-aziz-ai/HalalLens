import clsx from "clsx";
import type { GovernanceReview } from "@/lib/types";

const METRIC_LABELS: Record<string, string> = {
  total_debt: "Total debt",
  cash_equiv: "Cash equivalents",
  revenue: "Revenue",
  interest_income: "Interest income",
  dividend_income: "Dividend income",
  accounts_receivable: "Accounts receivable",
  liquid_assets: "Liquid assets",
  non_halal_income: "Non-permissible income",
};

type Theme = "dark" | "light";

type Props = {
  review: GovernanceReview | null;
  loading?: boolean;
  error?: string | null;
  theme: Theme;
  onApplyIndian?: (metrics: Record<string, number | null | undefined>) => void;
};

const numberFormatter = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
});

function formatValue(value?: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  if (Math.abs(value) >= 1_000_000_000) {
    return `${numberFormatter.format(value / 1_000_000_000)}B`;
  }
  if (Math.abs(value) >= 1_000_000) {
    return `${numberFormatter.format(value / 1_000_000)}M`;
  }
  return numberFormatter.format(value);
}

function formatDelta(value?: number | null) {
  if (value === null || value === undefined) return null;
  return `${(value * 100).toFixed(1)}%`;
}

export function GovernanceReviewPanel({
  review,
  loading,
  error,
  theme,
  onApplyIndian,
}: Props) {
  if (loading) {
    return (
      <div className={clsx("mt-4 rounded-2xl border p-4 text-sm", theme === "dark" ? "border-slate-800 bg-slate-900/40 text-slate-200" : "border-slate-200 bg-slate-50 text-slate-700")}>
        Loading governance metrics…
      </div>
    );
  }
  if (error) {
    return (
      <div className={clsx("mt-4 rounded-2xl border p-4 text-sm text-rose-400", theme === "dark" ? "border-rose-500/30 bg-rose-500/5" : "border-rose-200 bg-rose-50")}>
        {error}
      </div>
    );
  }
  if (!review) return null;

  const cardClass =
    theme === "dark"
      ? "rounded-2xl border border-white/10 bg-slate-900/60 text-slate-100"
      : "rounded-2xl border border-slate-200 bg-white text-slate-800";
  const muted =
    theme === "dark" ? "text-slate-400" : "text-slate-500";

  const metricKeys = Object.keys(review.ingested.metrics);

  return (
    <div className={clsx("mt-6 space-y-4", cardClass, "p-4")}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className={clsx("text-xs uppercase", muted)}>Governance comparison</p>
          <h3 className="text-lg font-semibold">Structured vs manual metrics</h3>
        </div>
        {review.indian_api && onApplyIndian && (
          <button
            type="button"
            onClick={() => onApplyIndian(review.indian_api?.metrics || {})}
            className="rounded-lg border border-emerald-400/40 bg-emerald-500/10 px-3 py-1 text-sm font-semibold text-emerald-200 hover:bg-emerald-400/20"
          >
            Apply Indian values
          </button>
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className={clsx("text-xs uppercase", muted)}>
            <tr>
              <th className="px-3 py-2 font-medium">Metric</th>
              <th className="px-3 py-2 font-medium">{review.ingested.label}</th>
              <th className="px-3 py-2 font-medium">{review.override ? review.override.label : "Override"}</th>
              <th className="px-3 py-2 font-medium">{review.indian_api ? review.indian_api.label : "Indian API"}</th>
              <th className="px-3 py-2 font-medium">Delta</th>
            </tr>
          </thead>
          <tbody>
            {metricKeys.map((metric) => {
              const label = METRIC_LABELS[metric] || metric;
              const ingestedVal = review.ingested.metrics[metric];
              const overrideVal = review.override?.metrics[metric];
              const indianVal = review.indian_api?.metrics[metric];
              const diff = review.differences?.[metric] || {};
              const overrideDelta = formatDelta(diff.override_delta);
              const indianDelta = formatDelta(diff.indian_delta);
              return (
                <tr key={metric} className="border-t border-white/5">
                  <td className="px-3 py-2 font-medium">{label}</td>
                  <td className="px-3 py-2">{formatValue(ingestedVal)}</td>
                  <td className="px-3 py-2">{formatValue(overrideVal)}</td>
                  <td className="px-3 py-2">{formatValue(indianVal)}</td>
                  <td className="px-3 py-2 text-xs">
                    {overrideDelta && (
                      <span className="mr-2 inline-flex rounded-full bg-amber-500/10 px-2 py-0.5 text-amber-300">
                        Override {overrideDelta}
                      </span>
                    )}
                    {indianDelta && (
                      <span className="inline-flex rounded-full bg-cyan-500/10 px-2 py-0.5 text-cyan-200">
                        Indian {indianDelta}
                      </span>
                    )}
                    {!overrideDelta && !indianDelta && "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
