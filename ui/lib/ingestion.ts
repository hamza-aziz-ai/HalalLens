import { request } from "./api";
import { IngestionStats } from "./types";

export async function fetchIngestionStats(): Promise<IngestionStats> {
  return request<IngestionStats>(`/ingestion/stats`);
}
