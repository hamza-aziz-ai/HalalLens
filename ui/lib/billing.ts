import { request } from "./api";
import type { BillingPlan, RazorpayOrderResponse } from "./types";

export type RazorpayPaymentResult = {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
};

export async function fetchBillingPlans(): Promise<BillingPlan[]> {
  return request<BillingPlan[]>("/billing/plans");
}

export async function createRazorpayOrder(
  planCode: string,
): Promise<RazorpayOrderResponse> {
  return request<RazorpayOrderResponse>("/billing/razorpay/order", {
    method: "POST",
    body: JSON.stringify({ plan_code: planCode }),
  });
}

export async function verifyRazorpayPayment(
  payment: RazorpayPaymentResult,
): Promise<{ plan: string; subscription_status: string; subscription_renewal?: string | null }> {
  return request("/billing/razorpay/verify", {
    method: "POST",
    body: JSON.stringify({
      order_id: payment.razorpay_order_id,
      payment_id: payment.razorpay_payment_id,
      signature: payment.razorpay_signature,
    }),
  });
}

export async function startTrial(
  planCode: string,
): Promise<{ plan: string; subscription_status: string; subscription_renewal?: string | null }> {
  return request("/billing/trial", {
    method: "POST",
    body: JSON.stringify({ plan_code: planCode }),
  });
}

export async function loadRazorpayScript(): Promise<void> {
  if (typeof window === "undefined") return;
  if (window.Razorpay) return;
  await new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Unable to load Razorpay checkout"));
    document.body.appendChild(script);
  });
}
