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
      ? "rounded-[28px] border border-white/10 bg-[linear-gradient(145deg,rgba(15,23,42,0.92),rgba(8,12,20,0.95))] shadow-[0_25px_80px_rgba(3,7,18,0.55)]"
      : "rounded-[28px] border border-black/5 bg-white/85 shadow-[0_20px_60px_rgba(15,23,42,0.12)]";
  return (
    <article className={baseCard + " p-6"}>
      <h2 className="text-display text-xl font-semibold text-white">
        Explain-Why
      </h2>
      <p className="mt-2 text-sm text-slate-300">
        {narration.summary} Verdict:{" "}
        <span className="font-semibold text-cyan-300">{narration.verdict}</span>
      </p>
      <ul className="mt-4 space-y-2 text-sm text-slate-200">
        {narration.bullets.map((bullet, index) => (
          <li
            key={index}
            className="rounded-xl border border-white/10 bg-white/5 px-3 py-2"
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
