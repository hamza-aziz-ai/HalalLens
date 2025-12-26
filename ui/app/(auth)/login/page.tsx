"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import clsx from "clsx";
import { loginUser, registerUser, saveAuthToken } from "@/lib/auth";
import { useAuth } from "@/providers/AuthProvider";
import { API_BASE } from "@/lib/api";

type Mode = "signin" | "signup";

const cardBase =
  "w-full max-w-md rounded-3xl border border-white/10 bg-white/5 p-8 shadow-2xl shadow-black/30 backdrop-blur";

export default function LoginPage() {
  const router = useRouter();
  const { user, loading, setUser, refresh } = useAuth();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!loading && user) {
      router.replace("/dashboard");
    }
  }, [loading, user, router]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const { hash, search } = window.location;
    let params: URLSearchParams | null = null;
    if (hash && hash.length > 1) {
      params = new URLSearchParams(hash.substring(1));
    } else if (search && search.length > 1) {
      params = new URLSearchParams(search.substring(1));
    }
    if (!params) return;
    const oauthToken = params.get("token");
    if (!oauthToken) return;
    window.history.replaceState(null, "", window.location.pathname);
    saveAuthToken(oauthToken);
    refresh();
    router.replace("/dashboard");
  }, [refresh, router]);

  const handleSubmit = async () => {
    if (!email.trim() || !password) {
      setError("Email and password are required.");
      return;
    }
    try {
      setSubmitting(true);
      setError(null);
      const profile =
        mode === "signup"
          ? await registerUser(email.trim(), password)
          : await loginUser(email.trim(), password);
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
    <div className="min-h-screen bg-slate-950 px-4 py-10 text-slate-100">
      <div className="mx-auto flex min-h-[80vh] max-w-5xl flex-col items-center justify-center gap-8 text-center">
        <header className="space-y-2">
          <p className="text-xs tracking-widest text-cyan-300/80 uppercase">
            HalalLens
          </p>
          <h1 className="text-3xl font-semibold">Welcome back</h1>
          <p className="text-sm text-slate-400">
            Sign in to access the Shariah compliance cockpit. ₹50/month plan unlocks
            unlimited instant lookups, Explain-Why narratives, and governance overrides.
          </p>
        </header>

        <div className={cardBase}>
          <div className="mb-4 flex gap-2 text-xs font-semibold uppercase text-slate-400">
            <button
              type="button"
              onClick={() => setMode("signin")}
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
              onClick={() => setMode("signup")}
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
            {error && <p className="text-xs text-rose-300">{error}</p>}
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
                ? "Create account"
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
    </div>
  );
}
