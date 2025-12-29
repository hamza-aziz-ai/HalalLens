"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";

import type {
  FeedbackEvent,
  FeedbackReport,
  FeedbackTrackingStatus,
} from "@/lib/types";
import {
  fetchFeedbackReports,
  updateFeedbackReport,
  submitFeedback,
  fetchFeedbackStatus,
  fetchFeedbackEvents,
} from "@/lib/feedback";
import { useAuth } from "@/providers/AuthProvider";
import { useTheme } from "@/providers/ThemeProvider";

const STATUS_BADGE_MAP: Record<string, string> = {
  open: "border-cyan-500/40 bg-cyan-500/10 text-cyan-200",
  in_review: "border-amber-400/40 bg-amber-400/10 text-amber-200",
  resolved: "border-emerald-400/40 bg-emerald-400/10 text-emerald-200",
};

const formatStatusLabel = (status: string) =>
  status
    .replace(/_/g, " ")
    .replace(/\b\w/g, (ch) => ch.toUpperCase());

const formatTimestamp = (value?: string | null) =>
  value ? new Date(value).toLocaleString() : "—";

export default function FeedbackPage() {
  const { theme } = useTheme();
  const { user } = useAuth();
  const isAdmin = Boolean(user?.is_admin);

  const [symbol, setSymbol] = useState("");
  const [filingDate, setFilingDate] = useState("");
  const [message, setMessage] = useState("");
  const [contact, setContact] = useState("");
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ticketId, setTicketId] = useState<number | null>(null);
  const [trackingToken, setTrackingToken] = useState<string | null>(null);

  const [lookupToken, setLookupToken] = useState("");
  const [lookupResult, setLookupResult] = useState<FeedbackTrackingStatus | null>(null);
  const [lookupError, setLookupError] = useState<string | null>(null);

  const [queue, setQueue] = useState<FeedbackReport[]>([]);
  const [queueError, setQueueError] = useState<string | null>(null);
  const [queueLoading, setQueueLoading] = useState(false);
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [recomputeMap, setRecomputeMap] = useState<Record<number, boolean>>({});
  const [eventsMap, setEventsMap] = useState<Record<number, FeedbackEvent[]>>({});
  const [eventsLoading, setEventsLoading] = useState<Record<number, boolean>>({});
  const [eventsExpanded, setEventsExpanded] = useState<Record<number, boolean>>({});
  const [eventsError, setEventsError] = useState<Record<number, string | null>>({});

  const cardClass =
    theme === "dark"
      ? "rounded-[28px] border border-white/10 bg-[linear-gradient(145deg,rgba(15,23,42,0.92),rgba(8,12,20,0.95))] p-6 shadow-[0_25px_80px_rgba(3,7,18,0.55)]"
      : "rounded-[28px] border border-slate-200/70 bg-white/85 p-6 shadow-[0_20px_60px_rgba(15,23,42,0.12)]";
  const headingClass = theme === "dark" ? "text-white" : "text-slate-900";
  const mutedTextClass = theme === "dark" ? "text-slate-400" : "text-slate-500";
  const inputClass = clsx(
    "w-full rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-400/60",
    theme === "dark"
      ? "border border-white/10 bg-white/10 text-white placeholder:text-slate-400"
      : "border border-slate-200 bg-white text-slate-900 placeholder:text-slate-500",
  );
  const textareaClass = clsx(
    "rounded-xl border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-cyan-400/60",
    theme === "dark"
      ? "border-slate-700 bg-slate-900 text-white placeholder:text-slate-500"
      : "border-slate-200 bg-white text-slate-900 placeholder:text-slate-500",
  );

  const refreshQueue = async () => {
    if (!isAdmin) return;
    setQueueLoading(true);
    try {
      const rows = await fetchFeedbackReports("", 50);
      setQueue(rows);
      setQueueError(null);
      setNotes({});
      setRecomputeMap({});
      setEventsMap({});
      setEventsError({});
      setEventsExpanded({});
      setEventsLoading({});
    } catch (err: any) {
      setQueue([]);
      setQueueError(err.message ?? "Unable to load feedback queue.");
    } finally {
      setQueueLoading(false);
    }
  };

  useEffect(() => {
    refreshQueue();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin]);

  const handleSubmit = async () => {
    if (!message.trim()) {
      setError("Please describe the issue.");
      return;
    }
    setError(null);
    setStatusMessage(null);
    try {
      const response = await submitFeedback({
        symbol: symbol.trim() || undefined,
        filing_date: filingDate ? new Date(filingDate).toISOString() : undefined,
        verdict: null,
        message: message.trim(),
        contact: contact.trim() || undefined,
      });
      setTicketId(response.ticket_id);
      setTrackingToken(response.tracking_token);
      setLookupToken(response.tracking_token);
      setLookupResult(null);
      setMessage("");
      setContact("");
      setStatusMessage(`Ticket #${response.ticket_id} received.`);
    } catch (err: any) {
      setError(err.message ?? "Unable to send feedback.");
    }
  };

  const handleStatusLookup = async () => {
    if (!lookupToken.trim()) {
      setLookupError("Enter a tracking token to check status.");
      return;
    }
    setLookupError(null);
    try {
      const result = await fetchFeedbackStatus(lookupToken.trim());
      setLookupResult(result);
    } catch (err: any) {
      setLookupResult(null);
      setLookupError(err.message ?? "Unable to look up ticket.");
    }
  };

  const handleCopyToken = async () => {
    if (!trackingToken) return;
    try {
      await navigator.clipboard.writeText(trackingToken);
      setStatusMessage("Tracking token copied to clipboard.");
    } catch (err: any) {
      setError(err.message ?? "Unable to copy token.");
    }
  };

  const handleStatusChange = async (
    report: FeedbackReport,
    status: string,
    extra?: { reviewer?: string },
  ) => {
    try {
      await updateFeedbackReport(report.id, {
        status,
        review_notes: notes[report.id] || undefined,
        reviewer: extra?.reviewer,
        trigger_recompute: recomputeMap[report.id] || false,
      });
      await refreshQueue();
    } catch (err: any) {
      setQueueError(err.message ?? "Unable to update feedback.");
    }
  };

  const toggleHistory = async (report: FeedbackReport) => {
    setEventsExpanded((prev) => ({ ...prev, [report.id]: !prev[report.id] }));
    if (eventsMap[report.id]) return;
    setEventsLoading((prev) => ({ ...prev, [report.id]: true }));
    try {
      const events = await fetchFeedbackEvents(report.id);
      setEventsMap((prev) => ({ ...prev, [report.id]: events }));
      setEventsError((prev) => ({ ...prev, [report.id]: null }));
    } catch (err: any) {
      setEventsError((prev) => ({
        ...prev,
        [report.id]: err.message ?? "Unable to load events.",
      }));
    } finally {
      setEventsLoading((prev) => ({ ...prev, [report.id]: false }));
    }
  };

  return (
    <main className="space-y-10">
      <header className={cardClass}>
        <h1 className={clsx("text-3xl font-semibold text-display", headingClass)}>
          Feedback & triage
        </h1>
        <p className={clsx("mt-2", mutedTextClass)}>
          Report mismatched ratios or data quality issues. Track ticket status and
          keep an audit trail of review actions.
        </p>
      </header>

      <section className={cardClass}>
        <h2 className={clsx("text-lg font-semibold", headingClass)}>
          Report an issue
        </h2>
        <p className={clsx("text-sm", mutedTextClass)}>
          Include a symbol and filing date when possible to speed up reviews.
        </p>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <input
            className={inputClass}
            placeholder="Symbol (optional)"
            value={symbol}
            onChange={(event) => setSymbol(event.target.value.toUpperCase())}
          />
          <input
            className={inputClass}
            type="date"
            value={filingDate}
            onChange={(event) => setFilingDate(event.target.value)}
          />
        </div>
        <div className="mt-3 space-y-2">
          <textarea
            className={clsx("min-h-[90px] w-full", textareaClass)}
            placeholder="Describe what looks wrong…"
            value={message}
            onChange={(event) => {
              setMessage(event.target.value);
              setError(null);
              setStatusMessage(null);
            }}
          />
          <input
            className={textareaClass}
            placeholder="Email or Telegram (optional)"
            value={contact}
            onChange={(event) => setContact(event.target.value)}
          />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={handleSubmit}
            className="rounded-lg bg-amber-400 px-4 py-2 text-sm font-semibold text-slate-900 hover:bg-amber-300"
          >
            Send feedback
          </button>
          {statusMessage && (
            <span className="text-xs text-emerald-300">{statusMessage}</span>
          )}
          {error && <span className="text-xs text-rose-300">{error}</span>}
        </div>
        {trackingToken && (
          <div
            className={clsx(
              "mt-4 rounded-lg border px-3 py-2 text-xs",
              theme === "dark"
                ? "border-slate-800 bg-slate-900/70 text-slate-200"
                : "border-slate-200 bg-white text-slate-700",
            )}
          >
            <p>Tracking token:</p>
            <div className="mt-2 flex flex-wrap items-center gap-2 font-mono text-sm">
              <span className="break-all">{trackingToken}</span>
              <button
                type="button"
                onClick={handleCopyToken}
                className="rounded-md bg-slate-800 px-2 py-1 text-xs text-slate-100 hover:bg-slate-700"
              >
                Copy
              </button>
            </div>
          </div>
        )}
      </section>

      <section className={cardClass}>
        <h2 className={clsx("text-lg font-semibold", headingClass)}>
          Check ticket status
        </h2>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row">
          <input
            className={clsx("flex-1", textareaClass)}
            placeholder="Tracking token"
            value={lookupToken}
            onChange={(event) => {
              setLookupToken(event.target.value);
              setLookupResult(null);
              setLookupError(null);
            }}
          />
          <button
            type="button"
            onClick={handleStatusLookup}
            className="rounded-lg bg-slate-700 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-600"
          >
            Check status
          </button>
        </div>
        {lookupError && <p className="mt-2 text-xs text-rose-300">{lookupError}</p>}
        {lookupResult && (
          <div className="mt-3 rounded-lg border border-white/10 bg-white/5 p-3 text-sm">
            <p>
              Ticket <strong>#{lookupResult.ticket_id}</strong> · {lookupResult.status}
            </p>
            <p className={clsx("text-xs", mutedTextClass)}>
              Submitted {new Date(lookupResult.created_at).toLocaleString()}
            </p>
            {lookupResult.review_notes && (
              <p className="mt-2 text-xs text-amber-200">{lookupResult.review_notes}</p>
            )}
          </div>
        )}
      </section>

      {isAdmin && (
        <section className={cardClass}>
          <div className="flex items-center justify-between">
            <h2 className={clsx("text-lg font-semibold", headingClass)}>
              Feedback queue
            </h2>
            <button
              type="button"
              onClick={refreshQueue}
              className={clsx(
                "text-xs font-semibold",
                theme === "dark" ? "text-cyan-300" : "text-cyan-700",
              )}
            >
              Refresh
            </button>
          </div>
          {queueLoading && (
            <p className={clsx("mt-3 text-sm", mutedTextClass)}>Loading queue…</p>
          )}
          {queueError && <p className="mt-2 text-xs text-rose-300">{queueError}</p>}
          {!queueLoading && queue.length === 0 && (
            <p className={clsx("mt-3 text-sm", mutedTextClass)}>
              No open reports right now.
            </p>
          )}
          <div className="mt-4 space-y-3">
            {queue.map((report) => (
              <div
                key={report.id}
                className={clsx(
                  "rounded-xl border p-3 text-sm",
                  theme === "dark"
                    ? "border-slate-800 bg-slate-900/70 text-slate-200"
                    : "border-slate-200 bg-white text-slate-700",
                )}
              >
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                  <span className={mutedTextClass}>
                    #{report.id} · {report.symbol || "—"} · {formatTimestamp(report.filing_date)}
                  </span>
                  <span
                    className={clsx(
                      "rounded-full border px-2 py-0.5 text-[11px] font-semibold",
                      STATUS_BADGE_MAP[report.status] || STATUS_BADGE_MAP.open,
                    )}
                  >
                    {formatStatusLabel(report.status)}
                  </span>
                </div>
                <p className="mt-2 text-sm">{report.message}</p>
                <div className="mt-2 grid gap-2 md:grid-cols-[1fr_auto]">
                  <textarea
                    className={clsx("min-h-[60px]", textareaClass)}
                    placeholder="Reviewer notes"
                    value={notes[report.id] ?? ""}
                    onChange={(event) =>
                      setNotes((prev) => ({
                        ...prev,
                        [report.id]: event.target.value,
                      }))
                    }
                  />
                  <div className="space-y-2 text-xs">
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={Boolean(recomputeMap[report.id])}
                        onChange={(event) =>
                          setRecomputeMap((prev) => ({
                            ...prev,
                            [report.id]: event.target.checked,
                          }))
                        }
                      />
                      Trigger re-evaluation
                    </label>
                    <div className="flex flex-col gap-2">
                      <button
                        type="button"
                        onClick={() =>
                          handleStatusChange(report, "in_review", {
                            reviewer: user?.email,
                          })
                        }
                        className="rounded-lg border border-amber-400/40 bg-amber-400/10 px-3 py-1 text-xs font-semibold text-amber-200"
                      >
                        Mark in review
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          handleStatusChange(report, "resolved", {
                            reviewer: user?.email,
                          })
                        }
                        className="rounded-lg border border-emerald-400/40 bg-emerald-400/10 px-3 py-1 text-xs font-semibold text-emerald-200"
                      >
                        Resolve
                      </button>
                    </div>
                  </div>
                </div>
                <div className="mt-3 flex items-center justify-between text-xs">
                  <button
                    type="button"
                    onClick={() => toggleHistory(report)}
                    className="text-cyan-300 hover:text-cyan-200"
                  >
                    {eventsExpanded[report.id] ? "Hide" : "Show"} audit trail
                  </button>
                  <span className={mutedTextClass}>
                    Status updated {formatTimestamp(report.status_updated_at)}
                  </span>
                </div>
                {eventsExpanded[report.id] && (
                  <div className="mt-3 rounded-lg border border-white/10 bg-white/5 p-3 text-xs">
                    {eventsLoading[report.id] && (
                      <p className={mutedTextClass}>Loading events…</p>
                    )}
                    {eventsError[report.id] && (
                      <p className="text-rose-300">{eventsError[report.id]}</p>
                    )}
                    {eventsMap[report.id]?.length ? (
                      <ul className="space-y-2">
                        {eventsMap[report.id]?.map((event) => (
                          <li key={event.id}>
                            <span className="font-semibold">
                              {formatStatusLabel(event.event_type)}
                            </span>
                            <span className={clsx("ml-2", mutedTextClass)}>
                              {formatTimestamp(event.created_at)}
                            </span>
                            {event.details && (
                              <p className={mutedTextClass}>{event.details}</p>
                            )}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      !eventsLoading[report.id] && (
                        <p className={mutedTextClass}>No events yet.</p>
                      )
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
