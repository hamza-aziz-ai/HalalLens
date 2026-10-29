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

/** Whether compliance-flip alerts are emailed to the signed-in user's own address. */
export async function fetchAlertEmails(): Promise<boolean> {
  return (await request<{ enabled: boolean }>(`/account/alert-emails`)).enabled;
}

export async function saveAlertEmails(enabled: boolean): Promise<boolean> {
  const result = await request<{ enabled: boolean }>(`/account/alert-emails`, {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });
  return result.enabled;
}
