"use client";

import clsx from "clsx";

import { getProviderLabel, providerVariant, type ProviderVariant } from "@/lib/providers";

const PROVIDER_BADGES: Record<ProviderVariant, { dark: string; light: string }> = {
  auto: {
    dark: "border-cyan-400/40 bg-cyan-500/10 text-cyan-100",
    light: "border-cyan-200 bg-cyan-50 text-cyan-700",
  },
  fallback: {
    dark: "border-indigo-400/40 bg-indigo-500/15 text-indigo-100",
    light: "border-indigo-200 bg-indigo-50 text-indigo-700",
  },
  cache: {
    dark: "border-slate-500/40 bg-slate-700/40 text-slate-200",
    light: "border-slate-300 bg-slate-100 text-slate-700",
  },
  manual: {
    dark: "border-amber-400/40 bg-amber-500/15 text-amber-100",
    light: "border-amber-200 bg-amber-50 text-amber-700",
  },
};

export function ProviderBadge({
  provider,
  theme = "dark",
  className,
}: {
  provider?: string | null;
  theme?: "dark" | "light";
  className?: string;
}) {
  const tone = providerVariant(provider);
  const label = getProviderLabel(provider);
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium",
        PROVIDER_BADGES[tone][theme],
        className,
      )}
    >
      {label}
    </span>
  );
}
