import clsx from "clsx";
import type { ReactNode } from "react";

/** Shared building blocks on the design tokens (D-032). */

export function buttonClass(variant: "primary" | "secondary" | "ghost" = "primary", size: "md" | "lg" = "md") {
  return clsx(
    "inline-flex items-center justify-center gap-2 rounded-lg font-semibold transition disabled:opacity-60",
    size === "lg" ? "px-5 py-2.5 text-sm" : "px-3.5 py-2 text-sm",
    variant === "primary" && "bg-brand text-brand-fg hover:bg-brand/90",
    variant === "secondary" && "border border-line bg-surface text-fg hover:bg-surface-2",
    variant === "ghost" && "text-muted hover:bg-surface-2 hover:text-fg",
  );
}

export const cardClass = "rounded-xl border border-line bg-surface shadow-sm";

/** A card with p-6 padding unless className sets its own (p-0, p-5 ...): no tailwind-merge here. */
export function Card({ className, children }: { className?: string; children: ReactNode }) {
  const ownPadding = /(^|\s)p-\d/.test(className ?? "");
  return <div className={clsx(cardClass, !ownPadding && "p-6", className)}>{children}</div>;
}

const VERDICT_STYLE: Record<string, { label: string; tone: string }> = {
  compliant: { label: "Compliant", tone: "border-success/30 bg-success/10 text-success" },
  "non-compliant": { label: "Non-compliant", tone: "border-danger/30 bg-danger/10 text-danger" },
  "needs-review": { label: "Needs review", tone: "border-warning/30 bg-warning/10 text-warning" },
};

/** Verdict pill; anything unknown reads "Insufficient data". */
export function VerdictBadge({ verdict }: { verdict: string }) {
  const style = VERDICT_STYLE[verdict] ?? {
    label: "Insufficient data",
    tone: "border-line bg-surface-2 text-muted",
  };
  return (
    <span className={clsx("inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold", style.tone)}>
      {style.label}
    </span>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={clsx("inline-flex items-center gap-2 font-semibold text-fg", className)}>
      <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden="true">
        <rect width="32" height="32" rx="8" className="fill-brand" />
        <circle cx="14" cy="14" r="7" fill="none" strokeWidth="2.5" className="stroke-brand-fg" />
        <path d="M19 19l6 6" strokeWidth="2.5" strokeLinecap="round" className="stroke-brand-fg" />
        <path d="M11 14.5l2 2 4-4.5" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="stroke-brand-fg" />
      </svg>
      <span>HalalLens</span>
    </span>
  );
}

export const inputClass =
  "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-fg placeholder:text-muted focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30";
export const labelClass = "text-xs font-medium text-muted";
/** Small uppercase mono label above a heading ("01 · Method"). */
export const eyebrowClass = "font-mono text-[11px] font-medium uppercase tracking-wider text-brand";

/** Title block at the top of every signed-in page. */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <p className={eyebrowClass}>{eyebrow}</p>}
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-fg">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

/** Says why a list is empty and what to do next, instead of a bare dash. */
export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line px-4 py-8 text-center">
      <p className="text-sm font-medium text-fg">{title}</p>
      {children && <div className="mx-auto mt-1.5 max-w-md text-sm text-muted">{children}</div>}
    </div>
  );
}
