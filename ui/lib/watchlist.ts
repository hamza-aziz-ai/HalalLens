import { request } from "./api";
import { WatchlistEntry } from "./types";

export async function fetchWatchlist(userId: string): Promise<WatchlistEntry[]> {
  return request<WatchlistEntry[]>(`/watchlist/${encodeURIComponent(userId)}`);
}

export async function upsertWatchlist(entry: WatchlistEntry): Promise<void> {
  await request(`/watchlist`, {
    method: "POST",
    body: JSON.stringify(entry),
  });
}
