import { request } from "./api";
import type { FeedbackPayload } from "./types";

export async function submitFeedback(payload: FeedbackPayload): Promise<void> {
  await request("/feedback", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
