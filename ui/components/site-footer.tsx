import Link from "next/link";

const LINKS = [
  ["Products & pricing", "/products/"],
  ["Learn", "/learn/"],
  ["Terms", "/terms/"],
  ["Privacy", "/privacy/"],
  ["Cancellation & refunds", "/refund-policy/"],
  ["Delivery", "/shipping-policy/"],
  ["Contact", "/contact/"],
] as const;

/** Public links every page should expose: products, policies and contact. */
export default function SiteFooter() {
  return (
    <footer className="mx-auto mt-10 max-w-6xl border-t border-white/10 pt-6 text-xs text-slate-400">
      <nav aria-label="Site" className="flex flex-wrap gap-x-5 gap-y-2">
        {LINKS.map(([label, href]) => (
          <Link key={href} href={href} className="hover:text-cyan-100">
            {label}
          </Link>
        ))}
      </nav>
      <p className="mt-3">
        HalalLens screens companies against Shariah criteria for information and education only. It
        is not investment advice or a recommendation to buy or sell any security.
      </p>
    </footer>
  );
}
