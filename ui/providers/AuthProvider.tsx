"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  ReactNode,
} from "react";
import type { UserProfile } from "@/lib/types";
import { fetchCurrentUser, saveAuthToken, takeFragmentParam } from "@/lib/auth";

type AuthContextValue = {
  user: UserProfile | null;
  loading: boolean;
  refresh: () => Promise<void>;
  setUser: (user: UserProfile | null) => void;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);

  // Fetches the session's user; `loading` already starts true for the first load.
  const load = useCallback(async () => {
    try {
      // A session token arrives only on the Google sign-in landing page, and
      // only in the fragment; other pages never take one from the URL.
      if (
        typeof window !== "undefined" &&
        window.location.pathname.replace(/\/$/, "") === "/login"
      ) {
        const oauthToken = takeFragmentParam("token");
        if (oauthToken) {
          saveAuthToken(oauthToken);
        }
      }
      const profile = await fetchCurrentUser();
      setUser(profile);
    } finally {
      setLoading(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    await load();
  }, [load]);

  useEffect(() => {
    load();
  }, [load]);

  const value = useMemo(
    () => ({
      user,
      loading,
      refresh,
      setUser,
    }),
    [user, loading, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
