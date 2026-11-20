"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
} from "react";

export type Theme = "dark" | "light";

const THEME_STORAGE_KEY = "halal-lens-theme";

type ThemeContextValue = {
  theme: Theme;
  setTheme: (value: Theme) => void;
  toggleTheme: () => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

// The stored choice wins, else the system preference. The inline script in
// app/layout.tsx applies the same rule before the first paint (no flash).
const themeListeners = new Set<() => void>();
const subscribeTheme = (listener: () => void) => {
  themeListeners.add(listener);
  return () => {
    themeListeners.delete(listener);
  };
};
const readTheme = (): Theme => {
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
};
const setTheme = (value: Theme) => {
  window.localStorage.setItem(THEME_STORAGE_KEY, value);
  themeListeners.forEach((listener) => listener());
};

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useSyncExternalStore(subscribeTheme, readTheme, () => "dark" as Theme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const value = useMemo(
    () => ({
      theme,
      setTheme,
      toggleTheme: () => setTheme(readTheme() === "dark" ? "light" : "dark"),
    }),
    [theme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useTheme must be used within ThemeProvider");
  }
  return ctx;
}
