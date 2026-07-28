import { request } from "./api";
import { WatchlistEntry } from "./types";

/**
 * The API derives the owner from the bearer token; `userId` is retained only
 * for URL compatibility and is ignored server-side. The returned entries are
 * always the authenticated user's own.
 */
export async function fetchWatchlist(userId: string): Promise<WatchlistEntry[]> {
  return request<WatchlistEntry[]>(`/watchlist/${encodeURIComponent(userId)}`);
}

export async function upsertWatchlist(entry: WatchlistEntry): Promise<void> {
  await request(`/watchlist`, {
    method: "POST",
    body: JSON.stringify(entry),
  });
}
