import { request } from "./api";
import type { Filing } from "./types";

export async function fetchRecentFilings(limit = 20): Promise<Filing[]> {
  return request<Filing[]>(`/filings/recent?limit=${limit}`);
}

export async function fetchFilingDetail(
  symbol: string,
  options?: { refresh?: boolean },
): Promise<Filing> {
  const params = new URLSearchParams();
  if (options?.refresh) {
    params.set("refresh", "true");
  }
  const query = params.toString();
  const path = query
    ? `/filings/${encodeURIComponent(symbol)}?${query}`
    : `/filings/${encodeURIComponent(symbol)}`;
  return request<Filing>(path);
}

export async function fetchFilingHistory(
  symbol: string,
  limit = 12,
): Promise<Filing[]> {
  return request<Filing[]>(
    `/filings/${encodeURIComponent(symbol)}/history?limit=${limit}`,
  );
}
