import clsx from "clsx";
import sample from "@/lib/sample-screening.json";
import { SampleGauges, SampleLabel } from "@/components/sample-screening";
import { VerdictBadge, cardClass } from "@/components/ui";

/** Hero visual: the first sample company as a screening "console" (real engine output, fictional data). */
export default function HeroConsole() {
  const company = sample.companies[0];
  return (
    <div className={clsx(cardClass, "animate-fade-up animate-delay-150 overflow-hidden shadow-xl shadow-brand/5")}>
      <div className="flex items-center justify-between border-b border-line bg-surface-2 px-4 py-2.5">
        <span className="flex items-center gap-2 font-mono text-xs text-muted">
          <span className="animate-blink h-2 w-2 rounded-full bg-success" aria-hidden="true" />
          ratio_engine · exact decimal
        </span>
        <span className="font-mono text-xs text-muted">{company.symbol}</span>
      </div>
      <div className="p-5">
        <SampleLabel />
        <div className="mt-3 flex items-start justify-between gap-3">
          <div>
            <p className="font-semibold text-fg">{company.name}</p>
            <p className="text-xs text-muted">Five ratios against their caps</p>
          </div>
          <VerdictBadge verdict={company.verdict} />
        </div>
        <div className="mt-5">
          <SampleGauges company={company} />
        </div>
        <p className="mt-5 border-t border-line pt-4 font-mono text-xs text-muted">
          <span className="text-brand">→</span> {company.summary}
        </p>
      </div>
    </div>
  );
}
