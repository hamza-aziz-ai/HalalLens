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

export async function registerUser(email: string, password: string) {
  try {
    const result = await request<AuthResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    saveAuthToken(result.token);
    logClientEvent("info", "auth.register.success", { email });
    return result.user;
  } catch (error) {
    logClientEvent("warning", "auth.register.failed", {
      email,
      error: error instanceof Error ? error.message : String(error),
    });
    throw error;
  }
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
