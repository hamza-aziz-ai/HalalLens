"use client";

import clsx from "clsx";

import { cardClass, eyebrowClass } from "@/components/ui";
import { NarrationResponse } from "@/lib/types";

export function ExplainPanel({
  narration,
}: {
  narration: NarrationResponse;
}) {
  return (
    <article className={clsx(cardClass, "p-6")}>
      <p className={eyebrowClass}>Narration</p>
      <h2 className="mt-1 text-xl font-semibold tracking-tight text-fg">Explain-Why</h2>
      <p className="mt-2 text-sm text-fg">
        {narration.summary} Verdict: <span className="font-semibold text-brand">{narration.verdict}</span>
      </p>
      {narration.source === "llm" && (
        <p
          className="mt-3 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning"
          data-testid="ai-caveat"
        >
          AI-generated explanation. It may be imperfect: the Compliant / Non-compliant badge and the ratio table are the authoritative screening result.
        </p>
      )}
      <ul className="mt-4 space-y-2 text-sm text-fg">
        {narration.bullets.map((bullet, index) => (
          <li key={index} className="rounded-lg border border-line bg-surface-2 px-3 py-2">
            {bullet}
          </li>
        ))}
      </ul>
      <div className="mt-5 border-t border-line pt-4 text-xs text-muted">
        <p className="font-mono text-[11px] font-medium uppercase tracking-wider text-muted">Citations</p>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {narration.citations.map((line, idx) => (
            <li key={idx}>{line}</li>
          ))}
        </ul>
      </div>
    </article>
  );
}
