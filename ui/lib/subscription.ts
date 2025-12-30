import type { UserProfile } from "./auth";

export function hasPaidAccess(user?: UserProfile | null): boolean {
  if (!user) return false;
  if (user.is_admin) return true;
  const plan = (user.plan || "free").toLowerCase();
  const status = (user.subscription_status || "inactive").toLowerCase();
  if (plan === "free") return false;
  if (plan === "lifetime") {
    return status !== "inactive";
  }
  if (!["active", "trialing"].includes(status)) return false;
  if (user.subscription_renewal) {
    const renewal = new Date(user.subscription_renewal);
    if (!Number.isNaN(renewal.getTime()) && renewal < new Date()) {
      return false;
    }
  }
  return true;
}

export function isTrialEligible(user?: UserProfile | null): boolean {
  if (!user) return false;
  if (user.is_admin) return false;
  const plan = (user.plan || "free").toLowerCase();
  const status = (user.subscription_status || "inactive").toLowerCase();
  if (plan !== "free") return false;
  if (status !== "inactive") return false;
  return !user.trial_used;
}
