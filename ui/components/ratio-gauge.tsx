import clsx from "clsx";

type RatioGaugeProps = {
  label: string;
  value: number | null;
  threshold: number;
  passed: boolean | null;
  delayMs?: number;
};

const pct = (value: number) => `${(value * 100).toFixed(2)}%`;

/**
 * One ratio as a bar against its cap. The scale runs to the larger of the
 * value and 1.5 × the cap, so the cap marker sits at a readable position and
 * a value over the cap visibly crosses it. Numbers stay in text for screen
 * readers; the bar is decoration.
 */
export default function RatioGauge({ label, value, threshold, passed, delayMs = 0 }: RatioGaugeProps) {
  const scale = Math.max(value ?? 0, threshold * 1.5);
  const fill = value === null ? 0 : (value / scale) * 100;
  const cap = (threshold / scale) * 100;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="text-fg">{label}</span>
        <span className="font-mono tabular-nums">
          <span className={clsx(passed === false ? "font-semibold text-danger" : "text-fg")}>
            {value === null ? "n/a" : pct(value)}
          </span>
          <span className="text-muted"> / {pct(threshold)}</span>
          {passed === false && <span className="sr-only"> (over the cap)</span>}
        </span>
      </div>
      <div className="relative mt-1.5 h-1.5 rounded-full bg-surface-2" aria-hidden="true">
        <div
          className={clsx(
            "animate-grow h-full rounded-full",
            passed === false ? "bg-danger" : passed ? "bg-success" : "bg-muted",
          )}
          style={{ width: `${fill}%`, animationDelay: `${delayMs}ms` }}
        />
        <div className="absolute -top-1 h-3.5 w-0.5 rounded bg-fg/60" style={{ left: `${cap}%` }} />
      </div>
    </div>
  );
}
