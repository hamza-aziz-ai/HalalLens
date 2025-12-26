import type { Filing } from "./types";

const historyKey = (entry: Filing) =>
  `${entry.symbol}-${new Date(entry.filing_date).toISOString()}`;

export function mergeHistoryEntries(
  existing: Filing[],
  incoming: Filing[],
): Filing[] {
  if (!incoming.length) {
    return existing;
  }
  const map = new Map(existing.map((entry) => [historyKey(entry), entry] as const));
  const combined = [...existing];
  for (const entry of incoming) {
    const key = historyKey(entry);
    if (!map.has(key)) {
      combined.push(entry);
      map.set(key, entry);
    }
  }
  combined.sort(
    (a, b) =>
      new Date(b.filing_date).getTime() - new Date(a.filing_date).getTime(),
  );
  return combined;
}
