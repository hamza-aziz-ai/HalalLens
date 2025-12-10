import { AnalysisPayload, AnalysisResponse, HalalScoreResponse, NarrationResponse } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_HALAL_API_BASE_URL || "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function callAnalysis(payload: AnalysisPayload): Promise<AnalysisResponse> {
  const score = await request<HalalScoreResponse>("/halal-score", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  const narration = await request<NarrationResponse>("/narrate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return { score, narration };
}

export { request, API_BASE };
