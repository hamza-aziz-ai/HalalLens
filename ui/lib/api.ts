import { AnalysisPayload, AnalysisResponse, HalalScoreResponse, NarrationResponse } from "./types";
import { logClientEvent } from "./logger";

const API_BASE = process.env.NEXT_PUBLIC_HALAL_API_BASE_URL || "http://localhost:8001";

export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("halal-auth-token");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const authToken = getAuthToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (authToken) {
    headers.Authorization = `Bearer ${authToken}`;
  }
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers,
      ...init,
    });
  } catch (error) {
    logClientEvent("error", "api.request_failed", {
      path,
      error: error instanceof Error ? error.message : String(error),
    });
    throw error;
  }
  if (!response.ok) {
    const message = await response.text();
    logClientEvent("error", "api.response_error", {
      path,
      status: response.status,
      message: message.slice(0, 500),
    });
    throw new Error(message || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function callAnalysis(
  payload: AnalysisPayload,
  includeNarration = true,
): Promise<AnalysisResponse> {
  const score = await request<HalalScoreResponse>("/halal-score", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  let narration: NarrationResponse | null = null;
  if (includeNarration) {
    narration = await request<NarrationResponse>("/narrate", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }
  return { score, narration };
}

export { request, API_BASE };
