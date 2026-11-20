import type { GovernanceReview } from "@/lib/types";
import { buttonClass, eyebrowClass } from "@/components/ui";

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

type Props = {
  review: GovernanceReview | null;
  loading?: boolean;
  error?: string | null;
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
  onApplyIndian,
}: Props) {
  if (loading) {
    return (
      <div className="rounded-lg border border-line bg-surface-2 p-4 text-sm text-muted">
        Loading governance metrics…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-lg border border-danger/30 bg-danger/10 p-4 text-sm text-danger">
        {error}
      </div>
    );
  }
  if (!review) return null;

  const metricKeys = Object.keys(review.ingested.metrics);

  return (
    <div className="space-y-4 rounded-lg border border-line bg-surface-2/50 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className={eyebrowClass}>Governance comparison</p>
          <h3 className="mt-1 font-semibold text-fg">Structured vs manual metrics</h3>
        </div>
        {review.indian_api && onApplyIndian && (
          <button
            type="button"
            onClick={() => onApplyIndian(review.indian_api?.metrics || {})}
            className={buttonClass("secondary")}
          >
            Apply Indian values
          </button>
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-left text-sm">
          <thead>
            <tr className="border-b border-line text-xs text-muted">
              <th className="px-3 py-2 font-medium">Metric</th>
              <th className="px-3 py-2 text-right font-medium">{review.ingested.label}</th>
              <th className="px-3 py-2 text-right font-medium">{review.override ? review.override.label : "Override"}</th>
              <th className="px-3 py-2 text-right font-medium">{review.indian_api ? review.indian_api.label : "Indian API"}</th>
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
                <tr key={metric} className="border-b border-line last:border-0">
                  <td className="px-3 py-2 font-medium text-fg">{label}</td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-fg">{formatValue(ingestedVal)}</td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-fg">{formatValue(overrideVal)}</td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-fg">{formatValue(indianVal)}</td>
                  <td className="px-3 py-2 text-xs">
                    {overrideDelta && (
                      <span className="mr-2 inline-flex rounded-full bg-warning/10 px-2 py-0.5 font-mono tabular-nums text-warning">
                        Override {overrideDelta}
                      </span>
                    )}
                    {indianDelta && (
                      <span className="inline-flex rounded-full bg-brand/10 px-2 py-0.5 font-mono tabular-nums text-brand">
                        Indian {indianDelta}
                      </span>
                    )}
                    {!overrideDelta && !indianDelta && <span className="text-muted">—</span>}
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
