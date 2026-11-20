"use client";

import { useEffect, useState } from "react";
import { GOOGLE_ERRORS, confirmGoogleLink, startGoogleLink, takeFragmentParam } from "@/lib/auth";
import { useAuth } from "@/providers/AuthProvider";
import { Card, buttonClass, inputClass } from "@/components/ui";

/**
 * "Link Google account": the password is asked again, Google proves the
 * identity, and this page (with the same session) confirms the link. Google
 * never signs anyone in or changes the account email here.
 */
export function GoogleLinkCard() {
  const { user, refresh } = useAuth();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const linkError = takeFragmentParam("link_error");
    if (linkError) {
      // One-time, browser-only read of the fragment after hydration (static export): it cannot be initial state.
      // eslint-disable-next-line react-hooks/set-state-in-effect
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
    <Card>
      <h2 className="font-semibold text-fg">Google sign-in</h2>
      {user.google_linked ? (
        <p className="mt-2 text-sm text-muted">
          A Google account is linked; &ldquo;Continue with Google&rdquo; signs you in.
        </p>
      ) : (
        <div className="mt-3 max-w-sm space-y-3">
          <p className="text-sm text-muted">
            Link a Google account to this account. Confirm your password first.
          </p>
          <input
            className={inputClass}
            aria-label="Current password"
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
            className={buttonClass("secondary")}
          >
            {busy ? "Opening Google…" : "Link Google account"}
          </button>
        </div>
      )}
      {message && <p className="mt-2 text-xs text-success">{message}</p>}
      {error && <p className="mt-2 text-xs text-danger">{error}</p>}
    </Card>
  );
}
