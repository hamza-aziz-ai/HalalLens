"use client";

import clsx from "clsx";

import type { Filing } from "@/lib/types";

const RATIO_SERIES = [
  {
    key: "debt_to_market_cap",
    label: "Debt / Cap",
    color: "#38bdf8",
    threshold: 0.3,
  },
  {
    key: "cash_to_market_cap",
    label: "Cash / Cap",
    color: "#34d399",
    threshold: 0.3,
  },
  {
    key: "receivables_to_market_cap",
    label: "Receivables / Cap",
    color: "#f472b6",
    threshold: 0.67,
  },
  {
    key: "liquid_assets_to_market_cap",
    label: "Liquid / Cap",
    color: "#a78bfa",
    threshold: 0.49,
  },
  {
    key: "non_permissible_income_ratio",
    label: "Non-permissible / Rev",
    color: "#fbbf24",
    threshold: 0.05,
  },
] as const;

type ChartDatum = {
  filingKey: string;
  dateLabel: string;
  entry: Filing;
  [key: string]: number | string | Filing;
};

function buildChartData(entries: Filing[]): ChartDatum[] {
  const sorted = [...entries].sort(
    (a, b) =>
      new Date(a.filing_date).getTime() - new Date(b.filing_date).getTime(),
  );

  return sorted.map((entry) => {
    const datum: ChartDatum = {
      filingKey: `${entry.symbol}-${entry.filing_date}`,
      dateLabel: new Date(entry.filing_date).toLocaleDateString(),
      entry,
    };

    RATIO_SERIES.forEach((series) => {
      const val = entry.ratios?.[series.key]?.value;
      datum[series.key] =
        typeof val === "number" ? Number((val * 100).toFixed(2)) : null;
    });

    return datum;
  });
}

export function RatioTrendChart({
  entries,
  theme = "dark",
  onSelect,
}: {
  entries: Filing[];
  theme?: "dark" | "light";
  onSelect?: (entry: Filing) => void;
}) {
  if (!entries.length) return null;

  const data = buildChartData(entries);
  const chartWidth = 640;
  const chartHeight = 280;
  const padding = { top: 24, right: 16, bottom: 48, left: 52 };
  const plotWidth = chartWidth - padding.left - padding.right;
  const plotHeight = chartHeight - padding.top - padding.bottom;

  const ratioValues = data.flatMap((datum) =>
    RATIO_SERIES.map((series) => datum[series.key] as number | null).filter(
      (value): value is number => typeof value === "number",
    ),
  );

  const ratioMax = Math.max(
    100,
    ...ratioValues,
    ...RATIO_SERIES.map((series) => series.threshold * 100),
  );

  const valueToY = (value: number) => {
    if (!ratioMax) return padding.top + plotHeight;
    const clamped = Math.min(Math.max(value, 0), ratioMax);
    const percent = clamped / ratioMax;
    return padding.top + (1 - percent) * plotHeight;
  };

  const indexToX = (index: number) => {
    if (data.length === 1) {
      return padding.left + plotWidth / 2;
    }
    const step = plotWidth / (data.length - 1);
    return padding.left + step * index;
  };

  const buildPathForSeries = (seriesKey: string) => {
    let started = false;
    const segments: string[] = [];

    data.forEach((datum, index) => {
      const value = datum[seriesKey] as number | null;
      if (typeof value === "number") {
        const coordinate = `${indexToX(index)},${valueToY(value)}`;
        segments.push(`${started ? "L" : "M"}${coordinate}`);
        started = true;
      } else {
        started = false;
      }
    });

    return segments.join(" ");
  };

  const cardClass = clsx(
    "rounded-[28px] border p-5 shadow-[0_25px_80px_rgba(3,7,18,0.5)]",
    theme === "dark"
      ? "border-white/10 bg-[linear-gradient(145deg,rgba(15,23,42,0.92),rgba(8,12,20,0.95))] text-slate-200"
      : "border-slate-200/70 bg-white/85 text-slate-800",
  );

  const gridFractions = [0, 0.25, 0.5, 0.75, 1];
  const overlayWidth =
    data.length > 1 ? (plotWidth / (data.length - 1)) * 0.8 : plotWidth;
  const overlayHalf = overlayWidth / 2;

  return (
    <article className={cardClass}>
      <header className="mb-4">
        <p
          className={clsx(
            "text-xs uppercase tracking-[0.2em]",
            theme === "dark" ? "text-slate-500" : "text-slate-600",
          )}
        >
          Ratio trends
        </p>
        <h2
          className={clsx(
            "text-display text-lg font-semibold",
            theme === "dark" ? "text-white" : "text-slate-900",
          )}
        >
          Threshold view
        </h2>
      </header>

      <div className="overflow-x-auto">
        <svg
          width="100%"
          viewBox={`0 0 ${chartWidth} ${chartHeight}`}
          role="img"
          aria-label="AAOIFI ratio trends chart"
          className="w-full"
        >
          {gridFractions.map((fraction) => {
            const value = ratioMax * fraction;
            const y = valueToY(value);
            return (
              <g key={`grid-${fraction}`}>
                <line
                  x1={padding.left}
                  x2={chartWidth - padding.right}
                  y1={y}
                  y2={y}
                  stroke={theme === "dark" ? "#1f2937" : "#cbd5f5"}
                  strokeDasharray="4 4"
                />
                <text
                  x={padding.left - 10}
                  y={y + 4}
                  fontSize={11}
                  textAnchor="end"
                  fill={theme === "dark" ? "#94a3b8" : "#475569"}
                >
                  {value.toFixed(0)}%
                </text>
              </g>
            );
          })}

          {RATIO_SERIES.map((series) => (
            <g key={`${series.key}-threshold`}>
              <line
                x1={padding.left}
                x2={chartWidth - padding.right}
                y1={valueToY(series.threshold * 100)}
                y2={valueToY(series.threshold * 100)}
                stroke={series.color}
                strokeDasharray="6 4"
              />
              <text
                x={chartWidth - padding.right + 4}
                y={valueToY(series.threshold * 100) - 4}
                fontSize={10}
                fill={theme === "dark" ? series.color : "#475569"}
              >
                {`${series.label} cap ${(series.threshold * 100).toFixed(0)}%`}
              </text>
            </g>
          ))}

          {RATIO_SERIES.map((series) => (
            <path
              key={series.key}
              d={buildPathForSeries(series.key)}
              fill="none"
              stroke={series.color}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ))}

          {data.map((datum, index) => (
            <g key={datum.filingKey}>
              <text
                x={indexToX(index)}
                y={chartHeight - padding.bottom / 3}
                fontSize={11}
                textAnchor="middle"
                fill={theme === "dark" ? "#94a3b8" : "#475569"}
                transform={`rotate(-20 ${indexToX(index)},${chartHeight - padding.bottom / 3})`}
              >
                {datum.dateLabel}
              </text>
              <rect
                x={indexToX(index) - overlayHalf}
                width={overlayWidth}
                y={padding.top}
                height={plotHeight}
                fill="transparent"
                className="cursor-pointer"
                aria-label={`Select filing ${datum.dateLabel}`}
                onClick={() => onSelect?.(datum.entry)}
              />
              {RATIO_SERIES.map((series) => {
                const value = datum[series.key] as number | null;
                if (typeof value !== "number") return null;
                return (
                  <circle
                    key={`${datum.filingKey}-${series.key}`}
                    cx={indexToX(index)}
                    cy={valueToY(value)}
                    r={4}
                    fill={theme === "dark" ? "#0f172a" : "#ffffff"}
                    stroke={series.color}
                    strokeWidth={2}
                  />
                );
              })}
            </g>
          ))}
        </svg>
      </div>

      <div className="mt-4 flex flex-wrap gap-4 text-xs">
        {RATIO_SERIES.map((series) => (
          <div key={series.key} className="flex items-center gap-2">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ backgroundColor: series.color }}
            />
            <span>
              {series.label} cap {(series.threshold * 100).toFixed(0)}%
            </span>
          </div>
        ))}
      </div>
    </article>
  );
}
