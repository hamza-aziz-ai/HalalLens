import { request } from "./api";
import type { BillingPlan, Entitlement, RazorpayOrderResponse } from "./types";

export type RazorpayPaymentResult = {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
};

export async function fetchBillingPlans(): Promise<BillingPlan[]> {
  return request<BillingPlan[]>("/billing/plans");
}

export async function fetchEntitlement(): Promise<Entitlement> {
  return request<Entitlement>("/billing/entitlement");
}

/** Button label for buying `plan` after the last paid plan of rank `currentRank` (0: none). */
export function purchaseLabel(plan: BillingPlan, currentRank: number): string {
  if (currentRank === 0 || plan.rank > currentRank) return "Upgrade";
  return plan.rank < currentRank ? "Switch" : "Extend";
}

/** Paise as rupees: "₹1502", or "₹1501.63" when there are paise. */
export function formatRupees(paise: number): string {
  return paise % 100 === 0 ? `₹${paise / 100}` : `₹${(paise / 100).toFixed(2)}`;
}

/** "₹2000 − ₹498 credit = ₹1502" for a price with upgrade credit (D-030). */
export function creditBreakdown(price: { list_amount: number; credit_amount: number; amount: number }): string {
  return `${formatRupees(price.list_amount)} − ${formatRupees(price.credit_amount)} credit = ${formatRupees(price.amount)}`;
}

/** refund_due only: reason (lifetime_held | price_expired | credit_changed) and the buyer-facing message. */
export type OrderSettlement = { status: string; reason?: string | null; message?: string | null };

/**
 * After the checkout closes without its success callback, ask the server what
 * happened: a payment finished on the bank's page is settled by the webhook.
 * Polls every 2 s for up to `timeoutMs`; returns the last status (and refund reason) seen.
 */
export async function waitForOrderSettlement(orderId: string, timeoutMs = 30_000): Promise<OrderSettlement> {
  const deadline = Date.now() + timeoutMs;
  let seen: OrderSettlement = { status: "created" };
  while (Date.now() < deadline) {
    try {
      seen = await request<OrderSettlement>(`/billing/razorpay/order/${encodeURIComponent(orderId)}`);
    } catch {
      // A transient failure: keep waiting until the deadline.
    }
    if (seen.status !== "created" && seen.status !== "attempted") return seen;
    await new Promise((resolve) => setTimeout(resolve, 2_000));
  }
  return seen;
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
