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
import { fetchCurrentUser, saveAuthToken } from "@/lib/auth";

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

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      if (typeof window !== "undefined") {
        const { hash, search } = window.location;
        let params: URLSearchParams | null = null;
        if (hash && hash.length > 1) {
          params = new URLSearchParams(hash.substring(1));
        } else if (search && search.length > 1) {
          params = new URLSearchParams(search.substring(1));
        }
        if (params) {
          const oauthToken = params.get("token");
          if (oauthToken) {
            window.history.replaceState(null, "", window.location.pathname);
            saveAuthToken(oauthToken);
          }
        }
      }
      const profile = await fetchCurrentUser();
      setUser(profile);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

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
