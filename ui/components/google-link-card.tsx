"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";
import { GOOGLE_ERRORS, confirmGoogleLink, startGoogleLink, takeFragmentParam } from "@/lib/auth";
import { useAuth } from "@/providers/AuthProvider";

/**
 * "Link Google account": the password is asked again, Google proves the
 * identity, and this page (with the same session) confirms the link. Google
 * never signs anyone in or changes the account email here.
 */
export function GoogleLinkCard({
  cardClass,
  headingClass,
  mutedTextClass,
}: {
  cardClass: string;
  headingClass: string;
  mutedTextClass: string;
}) {
  const { user, refresh } = useAuth();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const linkError = takeFragmentParam("link_error");
    if (linkError) {
      setError(GOOGLE_ERRORS[linkError] ?? "Linking failed. Start again.");
      return;
    }
    const code = takeFragmentParam("link");
    if (!code) return;
    confirmGoogleLink(code)
      .then(() => {
        setMessage("Google account linked. You can now use Continue with Google.");
        return refresh();
      })
      .catch((err) => setError(err.message || "Linking failed. Start again."));
  }, [refresh]);

  if (!user) return null;

  const start = async () => {
    try {
      setBusy(true);
      setError(null);
      window.location.assign(await startGoogleLink(password));
    } catch (err: any) {
      setError(err.message || "Could not start linking.");
      setBusy(false);
    }
  };

  return (
    <section className={cardClass}>
      <h2 className={clsx("text-lg font-semibold", headingClass)}>Google sign-in</h2>
      {user.google_linked ? (
        <p className={clsx("mt-2 text-sm", mutedTextClass)}>
          A Google account is linked; &ldquo;Continue with Google&rdquo; signs you in.
        </p>
      ) : (
        <div className="mt-3 max-w-sm space-y-3">
          <p className={clsx("text-sm", mutedTextClass)}>
            Link a Google account to this account. Confirm your password first.
          </p>
          <input
            className="w-full rounded-lg border border-white/10 bg-white/10 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-400/60"
            type="password"
            autoComplete="current-password"
            placeholder="Current password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button
            type="button"
            disabled={busy || !password}
            onClick={start}
            className={clsx(
              "rounded-lg border border-white/20 bg-white/10 px-4 py-2 text-sm font-semibold hover:bg-white/20",
              (busy || !password) && "opacity-60",
            )}
          >
            {busy ? "Opening Google…" : "Link Google account"}
          </button>
        </div>
      )}
      {message && <p className="mt-2 text-xs text-emerald-400">{message}</p>}
      {error && <p className="mt-2 text-xs text-rose-400">{error}</p>}
    </section>
  );
}
