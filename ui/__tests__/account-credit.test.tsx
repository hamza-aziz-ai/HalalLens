import { fireEvent, render, screen, within } from "@testing-library/react";

import AccountPage from "@/app/(app)/account/page";
import { creditBreakdown, formatRupees } from "@/lib/billing";
import type { BillingPlan, Entitlement } from "@/lib/types";

const ANNUAL_END = "2027-10-29T07:56:04Z";
const plan = (code: string, name: string, interval_days: number, rank: number) =>
  ({ code, name, price_inr: 1, interval_days, trial_days: 0, features: [], is_active: true, rank }) as BillingPlan;
const mockPlans = [plan("starter", "Starter", 30, 1), plan("annual", "Annual", 365, 2), plan("lifetime", "Lifetime", 0, 3)];
const quote = { plan_code: "lifetime", list_amount: 200000, credit_amount: 49800, amount: 150200, blocked: false, valid_for_seconds: 900 };
const mockEntitlement: Entitlement = {
  plan: "annual",
  subscription_status: "active",
  segments: [{ plan_code: "annual", source: "razorpay", start: "2026-10-29T07:56:04Z", end: ANNUAL_END }],
  next_purchase_starts: ANNUAL_END,
  purchases_blocked: false,
  auto_renewal: false,
  lifetime_quote: quote,
};
const mockOrder = { key_id: "k", order_id: "order_l", amount: 150200, list_amount: 200000, credit_amount: 49800, currency: "INR" };
let mockCheckout: "pay" | "dismiss" = "pay";

jest.mock("@/lib/billing", () => ({
  ...jest.requireActual("@/lib/billing"),
  fetchBillingPlans: jest.fn(async () => mockPlans),
  fetchEntitlement: jest.fn(async () => mockEntitlement),
  loadRazorpayScript: jest.fn(async () => undefined),
  createRazorpayOrder: jest.fn(async () => mockOrder),
  verifyRazorpayPayment: jest.fn(async () => undefined),
  waitForOrderSettlement: jest.fn(async () => ({
    status: "refund_due",
    reason: "price_expired",
    message: "This payment started after your Lifetime price expired.",
  })),
}));
jest.mock("@/lib/auth", () => ({ logoutUser: jest.fn() }));
jest.mock("@/components/google-link-card", () => ({ GoogleLinkCard: () => null }));
jest.mock("@/components/alert-emails-card", () => ({ AlertEmailsCard: () => null }));
jest.mock("@/providers/ThemeProvider", () => ({ useTheme: () => ({ theme: "dark" }) }));
jest.mock("@/providers/AuthProvider", () => {
  const user = { id: 42, email: "buyer@example.com", plan: "annual", subscription_status: "active" };
  const refresh = async () => undefined;
  return { useAuth: () => ({ user, refresh }) };
});

const opened = jest.fn();
beforeAll(() => {
  window.Razorpay = class {
    constructor(private options: Record<string, any>) {}
    on() {}
    open() {
      opened(this.options.amount);
      if (mockCheckout === "pay") {
        this.options.handler({ razorpay_payment_id: "pay_1", razorpay_order_id: "o", razorpay_signature: "s" });
      } else {
        this.options.modal.ondismiss();
      }
    }
  } as unknown as typeof window.Razorpay;
});

beforeEach(() => {
  opened.mockClear();
  mockCheckout = "pay";
  mockOrder.amount = 150200;
  mockOrder.credit_amount = 49800;
  quote.blocked = false;
  window.confirm = jest.fn(() => true);
});

const card = async (name: string) => (await screen.findByRole("heading", { name, level: 3 })).closest("div.rounded-2xl") as HTMLElement;

describe("money formatting", () => {
  it("shows whole rupees plainly and paise with two decimals", () => {
    expect(formatRupees(200000)).toBe("₹2000");
    expect(formatRupees(150163)).toBe("₹1501.63");
    expect(creditBreakdown({ list_amount: 200000, credit_amount: 49800, amount: 150200 })).toBe("₹2000 − ₹498 credit = ₹1502");
  });
});

describe("Lifetime upgrade credit on the account page", () => {
  it("shows the list price, the credit and the payable on the Lifetime card only", async () => {
    render(<AccountPage />);
    expect(await within(await card("Lifetime")).findByText("₹2000 − ₹498 credit = ₹1502 for your unused paid time.")).toBeInTheDocument();
    expect(within(await card("Annual")).queryByText(/credit/)).toBeNull();
  });

  it("pays the previewed price without asking again", async () => {
    render(<AccountPage />);
    fireEvent.click(within(await card("Lifetime")).getByRole("button"));
    expect(await screen.findByText("Payment received. Welcome to Lifetime!")).toBeInTheDocument();
    expect(window.confirm).not.toHaveBeenCalled();
    expect(opened).toHaveBeenCalledWith(150200);
  });

  it("asks before charging a price that moved since the preview, and stops when declined", async () => {
    mockOrder.amount = 150237;
    mockOrder.credit_amount = 49763;
    window.confirm = jest.fn(() => false);
    render(<AccountPage />);
    fireEvent.click(within(await card("Lifetime")).getByRole("button"));
    expect(await screen.findByText("Checkout cancelled. No money was taken.")).toBeInTheDocument();
    expect(window.confirm).toHaveBeenCalledWith(
      "Your Lifetime price is now ₹2000 − ₹497.63 credit = ₹1502.37. Continue to payment?",
    );
    expect(opened).not.toHaveBeenCalled();
  });

  it("closes checkout when the payable is below one rupee", async () => {
    quote.blocked = true;
    render(<AccountPage />);
    const lifetime = await card("Lifetime");
    expect(await within(lifetime).findByText(/contact support to upgrade/)).toBeInTheDocument();
    expect(within(lifetime).getByRole("button")).toBeDisabled();
  });

  it("tells the buyer the server's reason when a payment is kept for a refund", async () => {
    mockCheckout = "dismiss";
    render(<AccountPage />);
    fireEvent.click(within(await card("Lifetime")).getByRole("button"));
    expect(await screen.findByText("This payment started after your Lifetime price expired.")).toBeInTheDocument();
  });
});
