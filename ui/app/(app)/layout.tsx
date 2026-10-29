"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import clsx from "clsx";

import { useAuth } from "@/providers/AuthProvider";
import { ThemeProvider, useTheme } from "@/providers/ThemeProvider";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Overview" },
  { href: "/analysis", label: "Analysis" },
  { href: "/history", label: "History" },
  { href: "/governance", label: "Governance" },
  { href: "/feedback", label: "Feedback" },
  { href: "/account", label: "Account" },
];

function AppShell({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!loading && !user) {
      router.replace("/login");
    }
  }, [loading, user, router]);

  if (loading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 text-sm text-slate-400">
        Redirecting…
      </div>
    );
  }

  const shellClass =
    theme === "dark"
      ? "bg-[#05070d] bg-[image:radial-gradient(1200px_circle_at_12%_-10%,rgba(14,116,144,0.35),transparent_45%),radial-gradient(900px_circle_at_85%_0%,rgba(16,185,129,0.18),transparent_40%),radial-gradient(700px_circle_at_70%_85%,rgba(251,191,36,0.12),transparent_45%)] text-slate-100"
      : "bg-[#f5f7fb] bg-[image:radial-gradient(900px_circle_at_20%_-10%,rgba(14,116,144,0.16),transparent_45%),radial-gradient(800px_circle_at_85%_0%,rgba(16,185,129,0.12),transparent_40%)] text-slate-900";

  return (
    <div className={clsx("min-h-screen", shellClass)}>
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-10 lg:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="hidden lg:block">
          <div
            className={clsx(
              "sticky top-10 rounded-[28px] border p-5 shadow-[0_25px_80px_rgba(3,7,18,0.5)]",
              theme === "dark"
                ? "border-white/10 bg-[linear-gradient(145deg,rgba(15,23,42,0.9),rgba(8,12,20,0.95))]"
                : "border-slate-200/70 bg-white/85",
            )}
          >
            <div className="space-y-2">
              <p className="text-xs uppercase tracking-[0.3em] text-cyan-300/80">
                HalalLens
              </p>
              <p className="text-sm text-slate-400">
                Shariah compliance cockpit
              </p>
            </div>
            <nav className="mt-6 space-y-2 text-sm">
              {NAV_ITEMS.map((item) => {
                const active = pathname === item.href;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={clsx(
                      "flex items-center justify-between rounded-xl border px-3 py-2 transition",
                      active
                        ? theme === "dark"
                          ? "border-cyan-400/40 bg-cyan-400/10 text-cyan-100"
                          : "border-cyan-200 bg-cyan-50 text-cyan-700"
                        : theme === "dark"
                          ? "border-white/10 bg-white/5 text-slate-200 hover:border-cyan-400/40 hover:text-white"
                          : "border-slate-200 bg-white text-slate-700 hover:border-cyan-300 hover:text-slate-900",
                    )}
                  >
                    <span>{item.label}</span>
                    <span className="text-xs text-slate-400">→</span>
                  </Link>
                );
              })}
            </nav>
            <div className="mt-6 flex items-center justify-between gap-2 text-xs text-slate-400">
              <Link href="/learn" className="text-cyan-200 hover:text-cyan-100">
                Learn
              </Link>
              <button
                type="button"
                onClick={toggleTheme}
                className={clsx(
                  "rounded-full border px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.2em] transition",
                  theme === "dark"
                    ? "border-white/20 bg-white/10 text-white"
                    : "border-slate-300 bg-white/70 text-slate-900",
                )}
              >
                {theme === "dark" ? "Dark" : "Light"}
              </button>
            </div>
          </div>
        </aside>
        <div className="space-y-10">{children}</div>
      </div>
    </div>
  );
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <AppShell>{children}</AppShell>
    </ThemeProvider>
  );
}
