"use client";

import clsx from "clsx";

import { getProviderLabel, providerVariant, type ProviderVariant } from "@/lib/providers";

const PROVIDER_BADGES: Record<ProviderVariant, string> = {
  auto: "border-brand/30 bg-brand/10 text-brand",
  fallback: "border-line bg-surface-2 text-fg",
  cache: "border-line bg-surface-2 text-muted",
  manual: "border-warning/30 bg-warning/10 text-warning",
};

export function ProviderBadge({
  provider,
  className,
}: {
  provider?: string | null;
  className?: string;
}) {
  const tone = providerVariant(provider);
  const label = getProviderLabel(provider);
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-md border px-2 py-0.5 font-mono text-[11px] font-medium",
        PROVIDER_BADGES[tone],
        className,
      )}
    >
      {label}
    </span>
  );
}
