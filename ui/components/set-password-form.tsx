"use client";

import { useState } from "react";
import clsx from "clsx";

const inputClass =
  "w-full rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-fg placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-brand/60";

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
      <h1 className="text-xl font-semibold text-fg">{title}</h1>
      <p className="text-sm text-muted">{intro}</p>
      <label className="text-xs font-semibold uppercase text-muted">New password</label>
      <input
        className={inputClass}
        type="password"
        autoComplete="new-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <label className="text-xs font-semibold uppercase text-muted">Repeat password</label>
      <input
        className={inputClass}
        type="password"
        autoComplete="new-password"
        value={confirm}
        onChange={(e) => setConfirm(e.target.value)}
      />
      {error && <p className="text-xs text-danger">{error}</p>}
      <button
        type="button"
        disabled={submitting || !password}
        onClick={submit}
        className={clsx(
          "w-full rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-brand-fg hover:bg-brand/90",
          (submitting || !password) && "opacity-60",
        )}
      >
        {submitting ? "Please wait…" : submitLabel}
      </button>
    </div>
  );
}

export const authCardClass =
  "mx-auto mt-16 w-full max-w-md rounded-xl border border-line bg-surface p-8 shadow-sm";

export const authPageClass = "min-h-screen bg-bg px-4 py-12 text-fg";
