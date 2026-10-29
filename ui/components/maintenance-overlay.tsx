"use client";

import { useEffect, useState } from "react";

import { API_BASE } from "@/lib/api";
import { OUTAGE_EVENT } from "@/lib/outage";

// While the tab is visible, check every 30 s, so a restart shows up even when
// the user is idle; once down, check every 5 s and reload as soon as both the
// API and the dashboard answer (fresh data, fresh page chunks).
const HEARTBEAT_MS = 30_000;
const RECHECK_MS = 5_000;

async function siteIsUp(): Promise<boolean> {
  try {
    const [api, page] = await Promise.all([
      fetch(`${API_BASE}/health`, { cache: "no-store" }),
      fetch("/", { method: "HEAD", cache: "no-store" }),
    ]);
    return api.ok && page.ok;
  } catch {
    return false;
  }
}

/** The maintenance screen inside the dashboard: appears and disappears on its own. */
export default function MaintenanceOverlay() {
  const [down, setDown] = useState(false);

  useEffect(() => {
    let active = true;
    // One failed request is not an outage: confirm with a health check first.
    const confirm = async () => {
      if (!(await siteIsUp()) && active) setDown(true);
    };
    const beat = window.setInterval(() => {
      if (document.visibilityState === "visible") confirm();
    }, HEARTBEAT_MS);
    window.addEventListener(OUTAGE_EVENT, confirm);
    return () => {
      active = false;
      window.clearInterval(beat);
      window.removeEventListener(OUTAGE_EVENT, confirm);
    };
  }, []);

  useEffect(() => {
    if (!down) return;
    const timer = window.setInterval(async () => {
      if (await siteIsUp()) window.location.reload();
    }, RECHECK_MS);
    return () => window.clearInterval(timer);
  }, [down]);

  if (!down) return null;
  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="maintenance-title"
      className="fixed inset-0 z-[100] grid place-items-center bg-[radial-gradient(1100px_circle_at_10%_-10%,rgba(14,116,144,0.38),transparent_45%),radial-gradient(900px_circle_at_90%_0%,rgba(16,185,129,0.2),transparent_40%),#05070d] px-4 text-slate-200"
    >
      <div className="w-full max-w-md rounded-[28px] border border-white/10 bg-white/5 p-8 text-center shadow-[0_25px_80px_rgba(3,7,18,0.5)]">
        <svg className="mx-auto mb-5 h-11 w-11 animate-spin motion-reduce:animate-none" viewBox="0 0 44 44" fill="none" aria-hidden="true">
          <circle cx="22" cy="22" r="17" stroke="#22d3ee" strokeWidth="3" opacity=".35" />
          <path d="M22 5a17 17 0 0 1 17 17" stroke="#34d399" strokeWidth="3" strokeLinecap="round" />
        </svg>
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300">HalalLens</p>
        <h2 id="maintenance-title" className="mt-3 text-2xl font-semibold text-white">
          We&apos;ll be right back
        </h2>
        <p className="mt-3 text-sm leading-relaxed text-slate-300">
          HalalLens is briefly unavailable while we update or restart it. Your account, plan, watchlists and
          screening history are safe. This screen goes away by itself as soon as it is back.
        </p>
        <p className="mt-5 text-xs text-slate-400">
          <span className="mr-2 inline-block h-2 w-2 animate-pulse rounded-full bg-cyan-400 motion-reduce:animate-none" />
          Checking every few seconds
        </p>
      </div>
    </div>
  );
}
