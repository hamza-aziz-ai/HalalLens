// Site-wide outage signal: the API client reports, MaintenanceOverlay listens.

export const OUTAGE_EVENT = "halallens:outage";

/**
 * True when a response means "the server is down or restarting", not an API
 * error: Caddy's maintenance answer (503 with Retry-After), the Cloudflare
 * Worker's page (same), or Cloudflare's own 502 / 504 / 520-530 (530: tunnel
 * down). The API's own 503s ("Checkout is unavailable", "Database
 * unavailable") carry no Retry-After and stay ordinary errors.
 */
export function isOutageResponse(status: number, retryAfter: string | null): boolean {
  if (status === 503) return retryAfter !== null;
  return status === 502 || status === 504 || (status >= 520 && status <= 530);
}

export function reportOutage(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(OUTAGE_EVENT));
}
