import { request } from "./api";
import type {
  FeedbackReport,
  FeedbackPayload,
  FeedbackSubmissionResponse,
  FeedbackTrackingStatus,
  FeedbackEvent,
} from "./types";

export async function fetchFeedbackReports(
  status = "open",
  limit = 20,
): Promise<FeedbackReport[]> {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  params.set("limit", String(limit));
  return request<FeedbackReport[]>(`/feedback?${params.toString()}`);
}

export async function updateFeedbackReport(
  id: number,
  payload: { status: string; review_notes?: string; reviewer?: string; trigger_recompute?: boolean },
): Promise<FeedbackReport> {
  return request<FeedbackReport>(`/feedback/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function submitFeedback(
  payload: FeedbackPayload,
): Promise<FeedbackSubmissionResponse> {
  return request<FeedbackSubmissionResponse>("/feedback", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchFeedbackStatus(
  token: string,
): Promise<FeedbackTrackingStatus> {
  return request<FeedbackTrackingStatus>(`/feedback/status/${token}`);
}

export async function fetchFeedbackEvents(feedbackId: number): Promise<FeedbackEvent[]> {
  return request<FeedbackEvent[]>(`/feedback/${feedbackId}/events`);
}
