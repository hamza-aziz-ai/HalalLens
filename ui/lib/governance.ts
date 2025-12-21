import { request } from "./api";
import type { GovernanceOverride } from "./types";

export async function fetchGovernanceOverrides(
  symbol?: string,
  limit = 50,
): Promise<GovernanceOverride[]> {
  const params = new URLSearchParams();
  if (symbol) params.set("symbol", symbol);
  params.set("limit", String(limit));
  return request<GovernanceOverride[]>(`/governance/overrides?${params.toString()}`);
}

export async function upsertGovernanceOverride(
  payload: Partial<GovernanceOverride> & { symbol: string; filing_date: string },
): Promise<GovernanceOverride> {
  return request<GovernanceOverride>("/governance/overrides", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function deleteGovernanceOverride(symbol: string, filingDate: string): Promise<void> {
  const encodedDate = encodeURIComponent(filingDate);
  await request(`/governance/overrides/${symbol}/${encodedDate}`, {
    method: "DELETE",
  });
}
