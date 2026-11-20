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
import { Card, EmptyState, PageHeader, buttonClass, eyebrowClass, inputClass } from "@/components/ui";

const STATUS_BADGE_MAP: Record<string, string> = {
  open: "border-brand/30 bg-brand/10 text-brand",
  in_review: "border-warning/30 bg-warning/10 text-warning",
  resolved: "border-success/30 bg-success/10 text-success",
};

const formatStatusLabel = (status: string) =>
  status
    .replace(/_/g, " ")
    .replace(/\b\w/g, (ch) => ch.toUpperCase());

const formatTimestamp = (value?: string | null) =>
  value ? new Date(value).toLocaleString() : "—";

export default function FeedbackPage() {
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
    <>
      <PageHeader
        eyebrow="Support"
        title="Feedback & triage"
        description="Report mismatched ratios or data quality issues. Track ticket status and keep an audit trail of review actions."
      />

      <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
        <Card>
          <h2 className="font-semibold text-fg">Report an issue</h2>
          <p className="mt-1 text-sm text-muted">
            Include a symbol and filing date when possible to speed up reviews.
          </p>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <input
              className={inputClass}
              aria-label="Symbol"
              placeholder="Symbol (optional)"
              value={symbol}
              onChange={(event) => setSymbol(event.target.value.toUpperCase())}
            />
            <input
              className={inputClass}
              aria-label="Filing date"
              type="date"
              value={filingDate}
              onChange={(event) => setFilingDate(event.target.value)}
            />
          </div>
          <div className="mt-3 space-y-3">
            <textarea
              className={clsx("min-h-[90px]", inputClass)}
              aria-label="Describe the issue"
              placeholder="Describe what looks wrong…"
              value={message}
              onChange={(event) => {
                setMessage(event.target.value);
                setError(null);
                setStatusMessage(null);
              }}
            />
            <input
              className={inputClass}
              aria-label="Contact"
              placeholder="Email or Telegram (optional)"
              value={contact}
              onChange={(event) => setContact(event.target.value)}
            />
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button type="button" onClick={handleSubmit} className={buttonClass("primary")}>
              Send feedback
            </button>
            {statusMessage && (
              <span className="text-xs text-success">{statusMessage}</span>
            )}
            {error && <span className="text-xs text-danger">{error}</span>}
          </div>
          {trackingToken && (
            <div className="mt-4 rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs text-fg">
              <p className={eyebrowClass}>Tracking token:</p>
              <div className="mt-2 flex flex-wrap items-center gap-2 font-mono text-sm">
                <span className="break-all">{trackingToken}</span>
                <button type="button" onClick={handleCopyToken} className={buttonClass("secondary")}>
                  Copy
                </button>
              </div>
            </div>
          )}
        </Card>

        <Card className="self-start">
          <h2 className="font-semibold text-fg">Check ticket status</h2>
          <div className="mt-3 flex flex-col gap-2 sm:flex-row">
            <input
              className={clsx("flex-1", inputClass)}
              aria-label="Tracking token"
              placeholder="Tracking token"
              value={lookupToken}
              onChange={(event) => {
                setLookupToken(event.target.value);
                setLookupResult(null);
                setLookupError(null);
              }}
            />
            <button type="button" onClick={handleStatusLookup} className={buttonClass("secondary")}>
              Check status
            </button>
          </div>
          {lookupError && <p className="mt-2 text-xs text-danger">{lookupError}</p>}
          {lookupResult && (
            <div className="mt-3 rounded-lg border border-line bg-surface-2 p-3 text-sm text-fg">
              <p>
                Ticket <strong className="font-mono">#{lookupResult.ticket_id}</strong> · {lookupResult.status}
              </p>
              <p className="font-mono text-xs tabular-nums text-muted">
                Submitted {new Date(lookupResult.created_at).toLocaleString()}
              </p>
              {lookupResult.review_notes && (
                <p className="mt-2 text-xs text-warning">{lookupResult.review_notes}</p>
              )}
            </div>
          )}
        </Card>
      </div>

      {isAdmin && (
        <Card className="p-0">
          <div className="flex items-center justify-between border-b border-line px-5 py-4">
            <h2 className="font-semibold text-fg">Feedback queue</h2>
            <button type="button" onClick={refreshQueue} className={buttonClass("ghost")}>
              Refresh
            </button>
          </div>
          {queueLoading && (
            <p className="px-5 py-4 text-sm text-muted">Loading queue…</p>
          )}
          {queueError && <p className="px-5 pt-4 text-xs text-danger">{queueError}</p>}
          {!queueLoading && queue.length === 0 && (
            <div className="p-5">
              <EmptyState title="No open reports right now." />
            </div>
          )}
          <ul>
            {queue.map((report) => (
              <li key={report.id} className="border-b border-line px-5 py-4 text-sm text-fg last:border-0">
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                  <span className="font-mono tabular-nums text-muted">
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
                <div className="mt-3 grid gap-3 md:grid-cols-[1fr_auto]">
                  <textarea
                    className={clsx("min-h-[60px]", inputClass)}
                    aria-label={`Reviewer notes for #${report.id}`}
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
                    <label className="flex items-center gap-2 text-muted">
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-brand"
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
                        className={buttonClass("secondary")}
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
                        className={buttonClass("primary")}
                      >
                        Resolve
                      </button>
                    </div>
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
                  <button
                    type="button"
                    onClick={() => toggleHistory(report)}
                    aria-expanded={Boolean(eventsExpanded[report.id])}
                    className="font-semibold text-brand hover:underline"
                  >
                    {eventsExpanded[report.id] ? "Hide" : "Show"} audit trail
                  </button>
                  <span className="text-muted">
                    Status updated <span className="font-mono tabular-nums">{formatTimestamp(report.status_updated_at)}</span>
                  </span>
                </div>
                {eventsExpanded[report.id] && (
                  <div className="mt-3 rounded-lg border border-line bg-surface-2 p-3 text-xs">
                    {eventsLoading[report.id] && (
                      <p className="text-muted">Loading events…</p>
                    )}
                    {eventsError[report.id] && (
                      <p className="text-danger">{eventsError[report.id]}</p>
                    )}
                    {eventsMap[report.id]?.length ? (
                      <ul className="space-y-2">
                        {eventsMap[report.id]?.map((event) => (
                          <li key={event.id}>
                            <span className="font-semibold text-fg">
                              {formatStatusLabel(event.event_type)}
                            </span>
                            <span className="ml-2 font-mono tabular-nums text-muted">
                              {formatTimestamp(event.created_at)}
                            </span>
                            {event.details && (
                              <p className="text-muted">{event.details}</p>
                            )}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      !eventsLoading[report.id] && (
                        <p className="text-muted">No events yet.</p>
                      )
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
