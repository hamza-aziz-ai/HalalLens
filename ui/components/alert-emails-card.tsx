"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";
import { fetchAlertEmails, saveAlertEmails } from "@/lib/alerts";

/**
 * Opt-out for compliance-flip alert emails (D-031). Works whatever the plan, so
 * a subscriber whose access ended can still turn the emails off.
 */
export function AlertEmailsCard({
  cardClass,
  headingClass,
  mutedTextClass,
}: {
  cardClass: string;
  headingClass: string;
  mutedTextClass: string;
}) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAlertEmails()
      .then(setEnabled)
      .catch((err) => setError(err.message || "Could not load the alert email setting."));
  }, []);

  const toggle = async (next: boolean) => {
    try {
      setBusy(true);
      setError(null);
      setEnabled(await saveAlertEmails(next));
    } catch (err: any) {
      setError(err.message || "Could not save the alert email setting.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={cardClass}>
      <h2 className={clsx("text-lg font-semibold", headingClass)}>Alert emails</h2>
      <label className="mt-3 flex items-center gap-3 text-sm">
        <input
          type="checkbox"
          checked={Boolean(enabled)}
          disabled={enabled === null || busy}
          onChange={(e) => toggle(e.target.checked)}
        />
        Email me when a watched stock&rsquo;s compliance verdict changes
      </label>
      <p className={clsx("mt-2 text-xs", mutedTextClass)}>
        Sent to your account email while you have a paid plan. Not a fatwa and not investment advice.
      </p>
      {error && <p className="mt-2 text-xs text-rose-400">{error}</p>}
    </section>
  );
}
