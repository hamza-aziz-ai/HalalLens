type ClientLogLevel = "debug" | "info" | "warning" | "error";

const API_BASE =
  process.env.NEXT_PUBLIC_HALAL_API_BASE_URL || "http://localhost:8001";

export function logClientEvent(
  level: ClientLogLevel,
  message: string,
  context?: Record<string, unknown>,
) {
  if (typeof window === "undefined") return;
  const payload = {
    level,
    message,
    context,
    url: window.location.href,
    user_agent: window.navigator.userAgent,
  };
  try {
    const blob = new Blob([JSON.stringify(payload)], {
      type: "application/json",
    });
    if (navigator.sendBeacon) {
      navigator.sendBeacon(`${API_BASE}/client-logs`, blob);
      return;
    }
  } catch {
    // fall back to fetch
  }
  fetch(`${API_BASE}/client-logs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    keepalive: true,
  }).catch(() => {
    // best-effort logging only
  });
}
