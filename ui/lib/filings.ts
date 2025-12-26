import { request } from "./api";
import type { Filing } from "./types";

export type FilingHistoryApiResponse = {
  entries: Filing[];
  next_cursor?: string | null;
};

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

type HistoryOptions = {
  limit?: number;
  cursor?: string | null;
};

export async function fetchFilingHistory(
  symbol: string,
  options?: HistoryOptions,
): Promise<FilingHistoryApiResponse> {
  const params = new URLSearchParams();
  params.set("limit", String(options?.limit ?? 12));
  if (options?.cursor) {
    params.set("cursor", options.cursor);
  }
  return request<FilingHistoryApiResponse>(
    `/filings/${encodeURIComponent(symbol)}/history?${params.toString()}`,
  );
}
