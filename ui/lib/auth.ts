import { request, getAuthToken } from "./api";
import { logClientEvent } from "./logger";

export type UserProfile = {
  id: number;
  email: string;
  plan: string;
  subscription_status: string;
  subscription_renewal?: string | null;
  trial_used?: boolean;
  is_admin?: boolean;
};

export type AuthResponse = {
  token: string;
  expires_at: string;
  user: UserProfile;
};

const TOKEN_KEY = "halal-auth-token";

export function saveAuthToken(token: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, token);
  logClientEvent("info", "auth.token.saved", { length: token.length });
}

export function clearAuthToken() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
  logClientEvent("info", "auth.token.cleared");
}

type AccountEmailResponse = { status: string; detail: string };

/** Email-first sign-up: the server emails a link; the password is chosen there. */
export async function registerUser(email: string) {
  const result = await request<AccountEmailResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
  logClientEvent("info", "auth.register.requested");
  return result.detail;
}

/** Emails a set-password link (or a sign-up link when there is no account). */
export async function requestPasswordReset(email: string) {
  const result = await request<AccountEmailResponse>("/auth/password/forgot", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
  logClientEvent("info", "auth.reset.requested");
  return result.detail;
}

/** Finishes sign-up from the emailed link and signs the new account in. */
export async function confirmSignup(token: string, password: string) {
  const result = await request<AuthResponse>("/auth/signup/confirm", {
    method: "POST",
    body: JSON.stringify({ token, password }),
  });
  saveAuthToken(result.token);
  logClientEvent("info", "auth.signup.confirmed");
  return result.user;
}

/** Sets a new password from the emailed link; every session is signed out. */
export async function resetPassword(token: string, password: string) {
  await request<{ status: string }>("/auth/password/reset", {
    method: "POST",
    body: JSON.stringify({ token, password }),
  });
  logClientEvent("info", "auth.reset.completed");
}

/**
 * Starts linking a Google account (password required again). The API sets a
 * short-lived cookie that binds the flow to this browser; same-origin /api is
 * what lets the browser keep it.
 */
export async function startGoogleLink(password: string) {
  const result = await request<{ url: string }>("/auth/google/link/start", {
    method: "POST",
    body: JSON.stringify({ password }),
  });
  return result.url;
}

/** Finishes a link from the code Google's callback put in the fragment. */
export async function confirmGoogleLink(code: string) {
  return request<import("./types").UserProfile>("/auth/google/link/confirm", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
}

/**
 * Reads a one-time proof from the URL fragment (never the query string) and
 * removes it from the address bar and history straight away.
 */
export function takeFragmentParam(name: string): string | null {
  if (typeof window === "undefined") return null;
  const hash = window.location.hash;
  if (!hash || hash.length < 2) return null;
  const value = new URLSearchParams(hash.substring(1)).get(name);
  if (value) {
    window.history.replaceState(null, "", window.location.pathname);
  }
  return value;
}

export async function loginUser(email: string, password: string) {
  try {
    const result = await request<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    saveAuthToken(result.token);
    logClientEvent("info", "auth.login.success", { email });
    return result.user;
  } catch (error) {
    logClientEvent("warning", "auth.login.failed", {
      email,
      error: error instanceof Error ? error.message : String(error),
    });
    throw error;
  }
}

export async function logoutUser() {
  try {
    await request("/auth/logout", { method: "POST" });
    logClientEvent("info", "auth.logout.success");
  } finally {
    clearAuthToken();
  }
}

export async function fetchCurrentUser(): Promise<UserProfile | null> {
  const token = getAuthToken();
  if (!token) {
    return null;
  }
  try {
    const profile = await request<UserProfile>("/auth/me");
    logClientEvent("debug", "auth.me.success");
    return profile;
  } catch {
    logClientEvent("warning", "auth.me.failed");
    clearAuthToken();
    return null;
  }
}
