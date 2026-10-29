"use client";

import { useState } from "react";
import clsx from "clsx";

const inputClass =
  "w-full rounded-lg border border-white/10 bg-white/10 px-3 py-2 text-sm text-white placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-cyan-400/60";

/** Password + confirmation form shared by the sign-up and reset pages. */
export function SetPasswordForm({
  title,
  intro,
  submitLabel,
  onSubmit,
}: {
  title: string;
  intro: string;
  submitLabel: string;
  onSubmit: (password: string) => Promise<void>;
}) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    if (password !== confirm) {
      setError("The two passwords do not match.");
      return;
    }
    try {
      setSubmitting(true);
      setError(null);
      await onSubmit(password);
    } catch (err: any) {
      setError(err.message || "Something went wrong. Request a new link.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-3 text-left">
      <h1 className="text-xl font-semibold text-white">{title}</h1>
      <p className="text-sm text-slate-300">{intro}</p>
      <label className="text-xs font-semibold uppercase text-slate-400">New password</label>
      <input
        className={inputClass}
        type="password"
        autoComplete="new-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <label className="text-xs font-semibold uppercase text-slate-400">Repeat password</label>
      <input
        className={inputClass}
        type="password"
        autoComplete="new-password"
        value={confirm}
        onChange={(e) => setConfirm(e.target.value)}
      />
      {error && <p className="text-xs text-rose-300">{error}</p>}
      <button
        type="button"
        disabled={submitting || !password}
        onClick={submit}
        className={clsx(
          "w-full rounded-lg bg-gradient-to-r from-cyan-400 to-emerald-400 px-4 py-2 text-sm font-semibold text-slate-900 hover:opacity-90",
          (submitting || !password) && "opacity-60",
        )}
      >
        {submitting ? "Please wait…" : submitLabel}
      </button>
    </div>
  );
}

export const authCardClass =
  "mx-auto mt-16 w-full max-w-md rounded-3xl border border-white/10 bg-white/5 p-8 shadow-[0_25px_80px_rgba(3,7,18,0.6)] backdrop-blur";

export const authPageClass = "min-h-screen bg-[#05070d] px-4 py-12 text-slate-100";
