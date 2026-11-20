"use client";

import clsx from "clsx";

import { ProviderBadge } from "@/components/provider-badge";
import RatioGauge from "@/components/ratio-gauge";
import { VerdictBadge, cardClass, eyebrowClass } from "@/components/ui";
import type { HalalScoreResponse } from "@/lib/types";

/** The screening result: verdict up top, then each ratio as a gauge against its cap. */
export function RatioTable({
  evaluation,
}: {
  evaluation: HalalScoreResponse;
}) {
  const rows = Object.entries(evaluation.ratios);
  const missingEntries = Object.entries(evaluation.missing_inputs || {});
  // Display only: the verdict comes from RatioEngine via is_compliant (null = insufficient data).
  const verdict =
    evaluation.is_compliant === true
      ? "compliant"
      : evaluation.is_compliant === false
        ? "non-compliant"
        : "insufficient-data";
  return (
    <article className={clsx(cardClass, "p-6")}>
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line pb-4">
        <div>
          <p className={eyebrowClass}>Screening result</p>
          <h2 className="mt-1 font-mono text-xl font-semibold tracking-tight text-fg">{evaluation.symbol}</h2>
          <p className="text-xs text-muted">
            Filing date:{" "}
            <span className="font-mono tabular-nums">{new Date(evaluation.filing_date).toLocaleDateString()}</span>
          </p>
        </div>
        <VerdictBadge verdict={verdict} />
      </header>
      {rows.length > 0 ? (
        <ul className="mt-4 space-y-4">
          {rows.map(([key, computation], index) => {
            const rowProvider = computation.provider ?? evaluation.market_data_provider;
            return (
              <li key={key}>
                <RatioGauge
                  label={humanize(key)}
                  value={typeof computation.value === "number" ? computation.value : null}
                  threshold={computation.threshold}
                  passed={computation.passed}
                  delayMs={index * 90}
                />
                <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
                  {computation.passed === null ? (
                    <span className="text-muted">Missing data</span>
                  ) : (
                    <span
                      className={clsx(
                        "rounded-md px-1.5 py-0.5 font-mono text-[11px] font-semibold",
                        computation.passed ? "bg-success/10 text-success" : "bg-danger/10 text-danger",
                      )}
                    >
                      {computation.passed ? "PASS" : "FAIL"}
                    </span>
                  )}
                  <ProviderBadge provider={rowProvider} />
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="mt-4 text-sm text-muted">No ratios were returned for this filing.</p>
      )}
      {missingEntries.length > 0 && (
        <div className="mt-5 rounded-lg border border-warning/30 bg-warning/10 p-3 text-xs text-fg">
          <p className="font-semibold text-warning">Missing inputs</p>
          <ul className="mt-2 list-disc space-y-1 pl-4">
            {missingEntries.map(([key, value]) => (
              <li key={key}>
                {humanize(key)}: {value}
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}

function humanize(key: string) {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}
