import { request } from "./api";
import { AlertEvent } from "./types";

// The server reads the stored verdict; a client-supplied verdict is ignored.
export async function triggerAlertCheck(payload: {
  symbol: string;
}): Promise<AlertEvent[]> {
  return request<AlertEvent[]>(`/alerts/check`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
