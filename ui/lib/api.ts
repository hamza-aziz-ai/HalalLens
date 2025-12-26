import { AnalysisPayload, AnalysisResponse, HalalScoreResponse, NarrationResponse } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_HALAL_API_BASE_URL || "http://localhost:8000";

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
  const response = await fetch(`${API_BASE}${path}`, {
    headers,
    ...init,
  });
  if (!response.ok) {
    const message = await response.text();
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
