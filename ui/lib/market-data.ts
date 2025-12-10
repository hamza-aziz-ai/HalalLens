import { request } from "./api";
import { MarketQuote } from "./types";

export async function fetchMarketQuote(symbol: string): Promise<MarketQuote> {
  return request<MarketQuote>(`/market-data/${encodeURIComponent(symbol)}`);
}
