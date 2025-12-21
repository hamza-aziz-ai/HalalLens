"use client";

import { NarrationResponse } from "@/lib/types";

export function ExplainPanel({
  narration,
  theme = "dark",
}: {
  narration: NarrationResponse;
  theme?: "dark" | "light";
}) {
  const baseCard =
    theme === "dark"
      ? "rounded-3xl border border-white/10 bg-gradient-to-br from-slate-900/80 via-slate-900/60 to-slate-950/80 shadow-2xl shadow-black/40"
      : "rounded-3xl border border-black/5 bg-white/80 shadow-2xl shadow-black/10";
  return (
    <article className={baseCard + " p-6"}>
      <h2 className="text-xl font-semibold text-white">Explain-Why</h2>
      <p className="mt-1 text-sm text-slate-300">
        {narration.summary} Verdict:{" "}
        <span className="font-semibold text-cyan-300">{narration.verdict}</span>
      </p>
      <ul className="mt-4 space-y-2 text-sm text-slate-200">
        {narration.bullets.map((bullet, index) => (
          <li
            key={index}
            className="rounded-xl border border-white/5 bg-white/5 px-3 py-2"
          >
            {bullet}
          </li>
        ))}
      </ul>
      <div className="mt-4 text-xs text-slate-400">
        <p className="font-semibold text-slate-300">Citations</p>
        <ul className="list-disc space-y-1 pl-6">
          {narration.citations.map((line, idx) => (
            <li key={idx}>{line}</li>
          ))}
        </ul>
      </div>
    </article>
  );
}
