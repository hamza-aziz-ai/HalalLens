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

type Mode = "signin" | "signup" | "forgot";


const cardBase =
  "w-full rounded-3xl border border-white/10 bg-white/5 p-8 shadow-[0_25px_80px_rgba(3,7,18,0.6)] backdrop-blur";

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
    window.location.href = `${API_BASE}/auth/google/start`;
  };

  return (
    <div className="min-h-screen bg-[#05070d] bg-[image:radial-gradient(1200px_circle_at_10%_-10%,rgba(14,116,144,0.35),transparent_45%),radial-gradient(900px_circle_at_85%_0%,rgba(16,185,129,0.18),transparent_40%)] px-4 py-12 text-slate-100">
      <div className="mx-auto grid max-w-6xl gap-8 lg:grid-cols-[minmax(0,1fr)_420px]">
        <section className="flex flex-col justify-between rounded-3xl border border-white/10 bg-gradient-to-br from-slate-900/90 via-slate-900/60 to-slate-950/90 p-10 shadow-[0_30px_90px_rgba(3,7,18,0.6)] animate-fade-up">
          <div className="space-y-6">
            <p className="text-xs tracking-[0.3em] text-cyan-300/80 uppercase">
              HalalLens
            </p>
            <h1 className="text-display text-4xl font-semibold">
              Shariah compliance, clarified.
            </h1>
            <p className="text-base text-slate-300">
              Stay aligned with AAOIFI guidance, trace every ratio, and capture
              governance notes in one cockpit built for serious research.
            </p>
            <div className="grid gap-4 text-sm text-slate-300 sm:grid-cols-2">
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-cyan-200">
                  Insight
                </p>
                <p className="mt-2 font-semibold text-white">
                  Instant AAOIFI ratios with provenance.
                </p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-emerald-200">
                  Explain
                </p>
                <p className="mt-2 font-semibold text-white">
                  Explain-Why narratives for every verdict.
                </p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-amber-200">
                  Governance
                </p>
                <p className="mt-2 font-semibold text-white">
                  Override, annotate, and audit critical metrics.
                </p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-indigo-200">
                  Learning
                </p>
                <p className="mt-2 font-semibold text-white">
                  Built-in guides on riba and AAOIFI screens.
                </p>
              </div>
            </div>
          </div>
          <Link
            href="/learn"
            className="mt-8 inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-200 hover:text-cyan-100"
          >
            Explore the learning hub
          </Link>
        </section>

        <div className={`${cardBase} animate-fade-up animate-delay-150`}>
          <div className="mb-4 flex gap-2 text-xs font-semibold uppercase text-slate-400">
            <button
              type="button"
              onClick={() => switchMode("signin")}
              className={clsx(
                "flex-1 rounded-full border px-3 py-1 transition",
                mode === "signin"
                  ? "border-cyan-400/50 bg-cyan-400/15 text-cyan-100"
                  : "border-white/10 bg-transparent",
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
                  ? "border-emerald-400/50 bg-emerald-400/15 text-emerald-100"
                  : "border-white/10 bg-transparent",
              )}
            >
              Sign up
            </button>
          </div>

          <div className="space-y-3 text-left">
            <label className="text-xs font-semibold uppercase text-slate-400">
              Email
            </label>
            <input
              className="w-full rounded-lg border border-white/10 bg-white/10 px-3 py-2 text-sm text-white placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            {mode === "signin" ? (
              <>
                <label className="text-xs font-semibold uppercase text-slate-400">
                  Password
                </label>
                <input
                  className="w-full rounded-lg border border-white/10 bg-white/10 px-3 py-2 text-sm text-white placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
                  type="password"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button
                  type="button"
                  onClick={() => switchMode("forgot")}
                  className="text-xs text-cyan-200 hover:text-cyan-100"
                >
                  Forgot password?
                </button>
              </>
            ) : (
              <p className="text-xs text-slate-400">
                {mode === "signup"
                  ? "We email you a link to confirm the address; you choose your password there."
                  : "We email you a link to set a new password. It also confirms your email."}
              </p>
            )}
            {error && <p className="text-xs text-rose-300">{error}</p>}
            {notice && <p className="text-xs text-emerald-300">{notice}</p>}
            <button
              type="button"
              disabled={submitting}
              onClick={handleSubmit}
              className={clsx(
                "w-full rounded-lg bg-gradient-to-r from-cyan-400 to-emerald-400 px-4 py-2 text-sm font-semibold text-slate-900 hover:opacity-90",
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
              <span className="h-px flex-1 bg-white/20" />
              <span className="px-3 text-xs uppercase text-slate-500">OR</span>
              <span className="h-px flex-1 bg-white/20" />
            </div>
            <button
              type="button"
              onClick={handleGoogle}
              className="w-full rounded-lg border border-white/20 bg-white/10 px-4 py-2 text-sm font-semibold text-white hover:bg-white/20"
            >
              Continue with Google
            </button>
          </div>
        </div>
      </div>
      <SiteFooter />
    </div>
  );
}
