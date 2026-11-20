"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import clsx from "clsx";
import {
  GOOGLE_ERRORS,
  loginUser,
  registerUser,
  requestPasswordReset,
  saveAuthToken,
  takeFragmentParam,
} from "@/lib/auth";
import { useAuth } from "@/providers/AuthProvider";
import { API_BASE } from "@/lib/api";
import SiteFooter from "@/components/site-footer";
import SiteHeader from "@/components/site-header";

type Mode = "signin" | "signup" | "forgot";


const cardBase = "w-full rounded-xl border border-line bg-surface p-8 shadow-sm";

export default function LoginPage() {
  const router = useRouter();
  const { user, loading, setUser, refresh } = useAuth();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!loading && user) {
      router.replace("/dashboard");
    }
  }, [loading, user, router]);

  useEffect(() => {
    const googleError = takeFragmentParam("error");
    if (googleError) {
      // One-time, browser-only read of the fragment after hydration (static export): it cannot be initial state.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setError(GOOGLE_ERRORS[googleError] ?? "Google sign-in failed. Please try again.");
      return;
    }
    const oauthToken = takeFragmentParam("token");
    if (!oauthToken) return;
    saveAuthToken(oauthToken);
    refresh();
    router.replace("/dashboard");
  }, [refresh, router]);

  const switchMode = (next: Mode) => {
    setMode(next);
    setError(null);
    setNotice(null);
  };

  const handleSubmit = async () => {
    if (!email.trim() || (mode === "signin" && !password)) {
      setError(mode === "signin" ? "Email and password are required." : "Email is required.");
      return;
    }
    try {
      setSubmitting(true);
      setError(null);
      setNotice(null);
      if (mode === "signup") {
        setNotice(await registerUser(email.trim()));
        return;
      }
      if (mode === "forgot") {
        setNotice(await requestPasswordReset(email.trim()));
        return;
      }
      const profile = await loginUser(email.trim(), password);
      setUser(profile);
      router.replace("/dashboard");
    } catch (err: any) {
      setError(err.message || "Unable to authenticate.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleGoogle = () => {
    // An API route (prod API_BASE is the same-origin "/api" proxy), not a Next page: a full navigation that redirects to Google.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = `${API_BASE}/auth/google/start`;
  };

  return (
    <>
    <SiteHeader />
    <div className="px-4 py-12 text-fg">
      <div className="mx-auto grid max-w-6xl gap-8 lg:grid-cols-[minmax(0,1fr)_420px]">
        <section className="flex flex-col justify-center animate-fade-up">
          <h1 className="text-3xl font-semibold tracking-tight text-fg sm:text-4xl">
            Shariah screening you can check.
          </h1>
          <p className="mt-4 max-w-lg text-base leading-relaxed text-muted">
            Screen BSE-listed companies against AAOIFI-inspired ratios, see the numbers behind
            every verdict, and get an alert when a company on your watchlist changes status.
          </p>
          <ul className="mt-6 space-y-2 text-sm text-muted">
            <li>Manual screening is free with an account.</li>
            <li>Paid plans add symbol lookup, Explain-Why, filing history and alerts.</li>
          </ul>
          <Link href="/#sample" className="mt-6 text-sm font-semibold text-brand hover:underline">
            See a sample screening
          </Link>
        </section>

        <div className={`${cardBase} animate-fade-up animate-delay-150`}>
          <div className="mb-4 flex gap-2 text-xs font-semibold uppercase text-muted">
            <button
              type="button"
              onClick={() => switchMode("signin")}
              className={clsx(
                "flex-1 rounded-full border px-3 py-1 transition",
                mode === "signin"
                  ? "border-brand/50 bg-brand/10 text-brand"
                  : "border-line bg-transparent",
              )}
            >
              Sign in
            </button>
            <button
              type="button"
              onClick={() => switchMode("signup")}
              className={clsx(
                "flex-1 rounded-full border px-3 py-1 transition",
                mode === "signup"
                  ? "border-brand/50 bg-brand/10 text-brand"
                  : "border-line bg-transparent",
              )}
            >
              Sign up
            </button>
          </div>

          <div className="space-y-3 text-left">
            <label className="text-xs font-semibold uppercase text-muted">
              Email
            </label>
            <input
              className="w-full rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-fg placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-brand/60"
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            {mode === "signin" ? (
              <>
                <label className="text-xs font-semibold uppercase text-muted">
                  Password
                </label>
                <input
                  className="w-full rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-fg placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-brand/60"
                  type="password"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button
                  type="button"
                  onClick={() => switchMode("forgot")}
                  className="text-xs text-brand hover:underline"
                >
                  Forgot password?
                </button>
              </>
            ) : (
              <p className="text-xs text-muted">
                {mode === "signup"
                  ? "We email you a link to confirm the address; you choose your password there."
                  : "We email you a link to set a new password. It also confirms your email."}
              </p>
            )}
            {error && <p className="text-xs text-danger">{error}</p>}
            {notice && <p className="text-xs text-success">{notice}</p>}
            <button
              type="button"
              disabled={submitting}
              onClick={handleSubmit}
              className={clsx(
                "w-full rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-brand-fg hover:bg-brand/90",
                submitting && "opacity-60",
              )}
            >
              {submitting
                ? "Please wait…"
                : mode === "signup"
                ? "Email me a sign-up link"
                : mode === "forgot"
                ? "Email me a link"
                : "Sign in"}
            </button>
            <div className="relative my-4 flex items-center">
              <span className="h-px flex-1 bg-surface-2" />
              <span className="px-3 text-xs uppercase text-muted">OR</span>
              <span className="h-px flex-1 bg-surface-2" />
            </div>
            <button
              type="button"
              onClick={handleGoogle}
              className="w-full rounded-lg border border-line bg-surface-2 px-4 py-2 text-sm font-semibold text-fg hover:bg-surface-2"
            >
              Continue with Google
            </button>
          </div>
        </div>
      </div>
    </div>
    <SiteFooter />
    </>
  );
}
