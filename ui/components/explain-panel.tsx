"use client";

import { NarrationResponse } from "@/lib/types";

export function ExplainPanel({ narration }: { narration: NarrationResponse }) {
  return (
    <article className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6">
      <h2 className="text-xl font-semibold text-white">Explain-Why</h2>
      <p className="mt-1 text-sm text-slate-400">
        {narration.summary} Verdict:{" "}
        <span className="font-semibold text-cyan-300">{narration.verdict}</span>
      </p>
      <ul className="mt-4 space-y-2 text-sm text-slate-200">
        {narration.bullets.map((bullet, index) => (
          <li
            key={index}
            className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-2"
          >
            {bullet}
          </li>
        ))}
      </ul>
      <div className="mt-4 text-xs text-slate-500">
        <p className="font-semibold text-slate-400">Citations</p>
        <ul className="list-disc space-y-1 pl-6">
          {narration.citations.map((line, idx) => (
            <li key={idx}>{line}</li>
          ))}
        </ul>
      </div>
    </article>
  );
}
