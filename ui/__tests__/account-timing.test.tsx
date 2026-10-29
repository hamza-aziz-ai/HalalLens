import { fireEvent, render, screen, within } from "@testing-library/react";

import AccountPage from "@/app/(app)/account/page";
import type { BillingPlan, Entitlement } from "@/lib/types";

const ANNUAL_END = "2027-10-29T07:56:04Z";
const plan = (code: string, name: string, interval_days: number, rank: number) =>
  ({ code, name, price_inr: 1, interval_days, trial_days: 0, features: [], is_active: true, rank }) as BillingPlan;
const mockPlans = [plan("starter", "Starter", 30, 1), plan("annual", "Annual", 365, 2), plan("lifetime", "Lifetime", 0, 3)];
const mockAnnualRunning: Entitlement = {
  plan: "annual",
  subscription_status: "active",
  segments: [{ plan_code: "annual", source: "razorpay", start: "2026-10-29T07:56:04Z", end: ANNUAL_END }],
  next_purchase_starts: ANNUAL_END,
  purchases_blocked: false,
  auto_renewal: false,
};

jest.mock("@/lib/billing", () => ({
  ...jest.requireActual("@/lib/billing"),
  fetchBillingPlans: jest.fn(async () => mockPlans),
  fetchEntitlement: jest.fn(async () => mockAnnualRunning),
  loadRazorpayScript: jest.fn(async () => undefined),
  createRazorpayOrder: jest.fn(async (code: string) => ({ key_id: "k", order_id: `order_${code}`, amount: 1, currency: "INR" })),
  verifyRazorpayPayment: jest.fn(async () => undefined),
}));
jest.mock("@/lib/auth", () => ({ logoutUser: jest.fn() }));
jest.mock("@/components/google-link-card", () => ({ GoogleLinkCard: () => null }));
jest.mock("@/providers/ThemeProvider", () => ({ useTheme: () => ({ theme: "dark" }) }));
jest.mock("@/providers/AuthProvider", () => {
  const user = { id: 42, email: "buyer@example.com", plan: "annual", subscription_status: "active" };
  const refresh = async () => undefined;
  return { useAuth: () => ({ user, refresh }) };
});

beforeAll(() => {
  // The checkout succeeds at once.
  window.Razorpay = class {
    constructor(private options: Record<string, any>) {}
    on() {}
    open() {
      this.options.handler({ razorpay_payment_id: "pay_1", razorpay_order_id: "o", razorpay_signature: "s" });
    }
  } as unknown as typeof window.Razorpay;
});

const card = async (name: string) => (await screen.findByRole("heading", { name, level: 3 })).closest("div.rounded-2xl") as HTMLElement;
const later = new Date(ANNUAL_END).toLocaleDateString();

describe("account page purchase timing while Annual runs", () => {
  it("says timed plans start when Annual ends but Lifetime starts now", async () => {
    render(<AccountPage />);
    expect(await within(await card("Starter")).findByText(`starts ${later}`)).toBeInTheDocument();
    expect(within(await card("Annual")).getByText(`Adds to your plan; starts ${later}`)).toBeInTheDocument();
    expect(within(await card("Lifetime")).queryByText(/starts/)).toBeNull();
  });

  it("welcomes a Lifetime buyer now instead of on the Annual end date", async () => {
    render(<AccountPage />);
    fireEvent.click(within(await card("Lifetime")).getByRole("button"));
    expect(await screen.findByText("Payment received. Welcome to Lifetime!")).toBeInTheDocument();
  });

  it("still tells a Starter buyer it starts when Annual ends", async () => {
    render(<AccountPage />);
    fireEvent.click(within(await card("Starter")).getByRole("button"));
    expect(
      await screen.findByText(`Payment received. Starter starts on ${later}, when your current plan ends.`),
    ).toBeInTheDocument();
  });
});
