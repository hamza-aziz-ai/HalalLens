import { request } from "./api";
import { Filing } from "./types";

export async function fetchRecentFilings(limit = 20): Promise<Filing[]> {
  return request<Filing[]>(`/filings/recent?limit=${limit}`);
}

export async function fetchFilingDetail(symbol: string): Promise<Filing> {
  return request<Filing>(`/filings/${encodeURIComponent(symbol)}`);
}
