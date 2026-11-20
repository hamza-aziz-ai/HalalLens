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
    <footer className="mx-auto mt-16 w-full max-w-6xl border-t border-line px-4 py-8 text-sm text-muted">
      <nav aria-label="Site" className="flex flex-wrap gap-x-6 gap-y-2">
        {LINKS.map(([label, href]) => (
          <Link key={href} href={href} className="hover:text-fg">
            {label}
          </Link>
        ))}
      </nav>
      <p className="mt-4 max-w-3xl text-xs leading-relaxed">
        HalalLens screens companies against Shariah criteria for information and education only. It
        is not investment advice, a recommendation to buy or sell any security, or a fatwa.
      </p>
    </footer>
  );
}
