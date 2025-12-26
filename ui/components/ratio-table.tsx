"use client";

import clsx from "clsx";

import { ProviderBadge } from "@/components/provider-badge";
import type { HalalScoreResponse } from "@/lib/types";

export function RatioTable({
  evaluation,
  theme = "dark",
}: {
  evaluation: HalalScoreResponse;
  theme?: "dark" | "light";
}) {
  const rows = Object.entries(evaluation.ratios);
  const baseCard =
    theme === "dark"
      ? "rounded-3xl border border-white/10 bg-gradient-to-br from-slate-900/80 via-slate-900/60 to-slate-950/80 shadow-2xl shadow-black/40"
      : "rounded-3xl border border-black/5 bg-white/80 shadow-2xl shadow-black/10";
  return (
    <article className={baseCard + " p-6"}>
      <header className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-white">
            {evaluation.symbol}
          </h2>
          <p className="text-sm text-slate-400">
            Filing date: {new Date(evaluation.filing_date).toLocaleDateString()}
          </p>
        </div>
        <span
          className={clsx(
            "rounded-full px-3 py-1 text-sm font-semibold",
            evaluation.is_compliant
              ? "bg-emerald-400/20 text-emerald-300"
              : "bg-rose-400/20 text-rose-300",
            theme === "light" && evaluation.is_compliant && "text-emerald-600",
            theme === "light" && !evaluation.is_compliant && "text-rose-600",
          )}
        >
          {evaluation.is_compliant ? "Compliant" : "Non-compliant"}
        </span>
      </header>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-slate-400">
            <tr>
              <th className="pb-2">Ratio</th>
              <th className="pb-2">Value</th>
              <th className="pb-2">Threshold</th>
              <th className="pb-2">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/10 text-slate-100">
            {rows.map(([key, computation]) => {
              const rowProvider =
                computation.provider ?? evaluation.market_data_provider;
              return (
                <tr key={key}>
                <td className="py-2">{humanize(key)}</td>
                <td className="py-2">
                  {typeof computation.value === "number"
                    ? `${(computation.value * 100).toFixed(2)} %`
                    : "—"}
                </td>
                <td className="py-2">{(computation.threshold * 100).toFixed(0)} %</td>
                <td className="py-2">
                  <div className="flex flex-col gap-1">
                    {computation.passed === null ? (
                      <span className="text-slate-500">Missing data</span>
                    ) : (
                      <span
                        className={clsx(
                          "rounded-md px-2 py-1 text-xs font-semibold",
                          computation.passed
                            ? "bg-emerald-400/15 text-emerald-200"
                            : "bg-rose-400/15 text-rose-200",
                          theme === "light" &&
                            (computation.passed ? "text-emerald-700" : "text-rose-700"),
                        )}
                      >
                        {computation.passed ? "PASS" : "FAIL"}
                      </span>
                    )}
                    <ProviderBadge provider={rowProvider} theme={theme} />
                  </div>
                </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function humanize(key: string) {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}
