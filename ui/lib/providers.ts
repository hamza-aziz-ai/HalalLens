export const PROVIDER_LABELS: Record<string, string> = {
  tiingo: "Tiingo",
  yahoo: "Yahoo Finance",
  bhavcopy: "BSE Bhavcopy",
  cache: "Cached snapshot",
  manual: "Manual input",
  indianapi: "Indian Stock API",
};

export type ProviderVariant = "auto" | "fallback" | "cache" | "manual";

export function getProviderLabel(provider?: string | null): string {
  if (!provider || provider === "manual") {
    return PROVIDER_LABELS.manual;
  }
  return PROVIDER_LABELS[provider] || provider.toUpperCase();
}

export function getAutoProviderLabel(provider?: string | null): string | null {
  if (!provider || provider === "manual") {
    return null;
  }
  return getProviderLabel(provider);
}

export function providerVariant(provider?: string | null): ProviderVariant {
  if (!provider || provider === "manual") {
    return "manual";
  }
  if (provider === "bhavcopy") {
    return "fallback";
  }
  if (provider === "cache") {
    return "cache";
  }
  return "auto";
}

export function isManualProvider(provider?: string | null): boolean {
  return !provider || provider === "manual";
}
