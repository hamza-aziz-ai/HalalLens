import { request, getAuthToken } from "./api";

export type UserProfile = {
  id: number;
  email: string;
  plan: string;
  subscription_status: string;
  subscription_renewal?: string | null;
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
}

export function clearAuthToken() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
}

export async function registerUser(email: string, password: string) {
  const result = await request<AuthResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  saveAuthToken(result.token);
  return result.user;
}

export async function loginUser(email: string, password: string) {
  const result = await request<AuthResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  saveAuthToken(result.token);
  return result.user;
}

export async function logoutUser() {
  try {
    await request("/auth/logout", { method: "POST" });
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
    return profile;
  } catch {
    clearAuthToken();
    return null;
  }
}
