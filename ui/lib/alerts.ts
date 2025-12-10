import { request } from "./api";
import { AlertEvent } from "./types";

export async function triggerAlertCheck(payload: {
  symbol: string;
  is_compliant: boolean;
}): Promise<AlertEvent[]> {
  return request<AlertEvent[]>(`/alerts/check`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
