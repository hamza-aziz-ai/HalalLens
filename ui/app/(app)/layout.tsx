"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import clsx from "clsx";

import { useAuth } from "@/providers/AuthProvider";
import { useTheme } from "@/providers/ThemeProvider";
import { logoutUser } from "@/lib/auth";
import { Logo, buttonClass } from "@/components/ui";
import GithubBadge from "@/components/github-badge";

// 24×24 stroke icons (path data only), drawn in currentColor.
const ICONS: Record<string, string> = {
  overview: "M4 13h6V4H4zM14 20h6v-9h-6zM4 20h6v-3H4zM14 7h6V4h-6z",
  analysis: "M4 19V5M4 19h16M8 15l3-4 3 2 5-6",
  history: "M12 8v4l3 2M3.05 11a9 9 0 1 1 .5 4M3 5v6h6",
  governance: "M12 3l8 4v5c0 4.5-3.4 8.4-8 9-4.6-.6-8-4.5-8-9V7z",
  feedback: "M4 5h16v11H8l-4 4z",
  account: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 20a8 8 0 0 1 16 0",
  learn: "M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2zM8 7h7",
};

const NAV_ITEMS = [
  { href: "/dashboard", label: "Overview", icon: "overview" },
  { href: "/analysis", label: "Analysis", icon: "analysis" },
  { href: "/history", label: "History", icon: "history" },
  { href: "/governance", label: "Governance", icon: "governance" },
  { href: "/feedback", label: "Feedback", icon: "feedback" },
  { href: "/account", label: "Account", icon: "account" },
];

function Icon({ name }: { name: string }) {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={ICONS[name]} />
    </svg>
  );
}

function NavLinks({ pathname, onNavigate }: { pathname: string; onNavigate?: () => void }) {
  return (
    <nav aria-label="App" className="space-y-1">
      {NAV_ITEMS.map((item) => {
        const active = pathname.replace(/\/$/, "") === item.href;
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={clsx(
              "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
              active ? "bg-brand/10 text-brand" : "text-muted hover:bg-surface-2 hover:text-fg",
            )}
          >
            <Icon name={item.icon} />
            {item.label}
          </Link>
        );
      })}
      <Link
        href="/learn"
        onClick={onNavigate}
        className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-muted transition hover:bg-surface-2 hover:text-fg"
      >
        <Icon name="learn" />
        Learn
      </Link>
    </nav>
  );
}

function AppShell({ children }: { children: React.ReactNode }) {
  const { user, loading, setUser } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const router = useRouter();
  const pathname = usePathname() || "";
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (!loading && !user) {
      router.replace("/login");
    }
  }, [loading, user, router]);

  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setMenuOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  if (loading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted">
        Loading…
      </div>
    );
  }

  const signOut = async () => {
    try {
      await logoutUser();
    } finally {
      // The token is already cleared locally even if the API call failed.
      setUser(null);
      router.replace("/login");
    }
  };

  return (
    <div className="min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-lg focus:bg-surface focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-30 border-b border-line bg-bg/85 backdrop-blur">
        <div className="flex h-14 items-center gap-3 px-4 lg:px-6">
          <button
            type="button"
            className={clsx(buttonClass("ghost"), "lg:hidden")}
            aria-label="Open menu"
            aria-expanded={menuOpen}
            aria-controls="app-menu"
            onClick={() => setMenuOpen(true)}
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
              <path d="M4 7h16M4 12h16M4 17h16" />
            </svg>
          </button>
          <Link href="/dashboard" aria-label="HalalLens overview">
            <Logo />
          </Link>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden rounded-full border border-line px-2.5 py-0.5 font-mono text-[11px] uppercase text-muted sm:inline">
              {user.plan}
            </span>
            <span className="hidden max-w-[16rem] truncate text-sm text-muted md:inline">{user.email}</span>
            <GithubBadge />
            <button
              type="button"
              onClick={toggleTheme}
              className={buttonClass("ghost")}
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            >
              {theme === "dark" ? "Light" : "Dark"}
            </button>
            <button type="button" onClick={signOut} className={buttonClass("secondary")}>
              Sign out
            </button>
          </div>
        </div>
      </header>

      {menuOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <button
            type="button"
            className="absolute inset-0 bg-black/40"
            aria-label="Close menu"
            onClick={() => setMenuOpen(false)}
          />
          <div id="app-menu" className="absolute inset-y-0 left-0 w-72 border-r border-line bg-surface p-4 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <Logo />
              <button type="button" className={buttonClass("ghost")} onClick={() => setMenuOpen(false)}>
                Close
              </button>
            </div>
            <NavLinks pathname={pathname} onNavigate={() => setMenuOpen(false)} />
          </div>
        </div>
      )}

      <div className="mx-auto grid max-w-7xl gap-8 px-4 py-8 lg:grid-cols-[13rem_minmax(0,1fr)] lg:px-6">
        <aside className="hidden lg:block">
          <div className="sticky top-20">
            <NavLinks pathname={pathname} />
          </div>
        </aside>
        <main id="main" className="min-w-0 space-y-8">
          {children}
        </main>
      </div>
    </div>
  );
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
