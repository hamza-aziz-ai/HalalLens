import { ReactNode } from "react";
import SiteHeader from "@/components/site-header";
import SiteFooter from "@/components/site-footer";
import { cardClass } from "@/components/ui";

export const policyCardClass = `${cardClass} p-6`;
export const policyTitleClass = "text-lg font-semibold text-fg";
export const policyBodyClass = "text-sm leading-relaxed text-muted";
export const policyListClass = "list-disc space-y-2 pl-5 text-sm text-muted";

type PolicyLayoutProps = {
  title: string;
  subtitle: string;
  updatedAt: string;
  children: ReactNode;
};

/** Public page frame: site header, page title block, content cards and footer. */
export default function PolicyLayout({ title, subtitle, updatedAt, children }: PolicyLayoutProps) {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-12">
        <header>
          <h1 className="text-3xl font-semibold tracking-tight text-fg">{title}</h1>
          <p className="mt-3 text-base text-muted">{subtitle}</p>
          <p className="mt-3 text-xs text-muted">Last updated: {updatedAt}</p>
        </header>
        <div className="flex flex-col gap-6">{children}</div>
      </main>
      <SiteFooter />
    </>
  );
}
