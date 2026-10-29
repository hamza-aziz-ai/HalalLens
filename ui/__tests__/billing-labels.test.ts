import { purchaseLabel } from "@/lib/billing";
import type { BillingPlan } from "@/lib/types";

const plan = (code: string, rank: number) => ({ code, rank }) as BillingPlan;
const starter = plan("starter", 1);
const annual = plan("annual", 2);
const lifetime = plan("lifetime", 3);

describe("purchaseLabel", () => {
  it("offers an upgrade when nothing is running", () => {
    expect([starter, annual, lifetime].map((p) => purchaseLabel(p, 0))).toEqual(["Upgrade", "Upgrade", "Upgrade"]);
  });

  it("calls a lower tier a switch and the same tier an extension", () => {
    expect([starter, annual, lifetime].map((p) => purchaseLabel(p, annual.rank))).toEqual([
      "Switch",
      "Extend",
      "Upgrade",
    ]);
  });
});
