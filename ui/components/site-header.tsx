"use client";

import Link from "next/link";
import { useAuth } from "@/providers/AuthProvider";
import { useTheme } from "@/providers/ThemeProvider";
import { Logo, buttonClass } from "@/components/ui";

const LINKS = [
  ["Method", "/#method"],
  ["Sample", "/#sample"],
  ["Pricing", "/products/"],
  ["Learn", "/learn/"],
] as const;

/** Public top bar: brand, page links, theme switch and the sign-in or dashboard button. */
export default function SiteHeader() {
  const { user, loading } = useAuth();
  const { theme, toggleTheme } = useTheme();
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-bg/85 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-4">
        <Link href="/" aria-label="HalalLens home">
          <Logo />
        </Link>
        <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
          {LINKS.map(([label, href]) => (
            <Link key={href} href={href} className={buttonClass("ghost")}>
              {label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={toggleTheme}
            className={buttonClass("ghost")}
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          >
            {theme === "dark" ? "Light" : "Dark"}
          </button>
          {!loading && user ? (
            <Link href="/dashboard/" className={buttonClass("primary")}>
              Open dashboard
            </Link>
          ) : (
            <Link href="/login/" className={buttonClass("primary")}>
              Sign in
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
