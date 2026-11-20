import Link from "next/link";
import SiteFooter from "@/components/site-footer";
import SiteHeader from "@/components/site-header";
import { policyBodyClass, policyCardClass } from "@/components/policy-layout";
import { buttonClass } from "@/components/ui";

// Exported as 404.html; the UI image's Caddy serves it for every unknown path.
export default function NotFound() {
  return (
    <>
    <SiteHeader />
    <main className="flex flex-col px-4 py-16 text-fg">
      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-8">
        <section className={`${policyCardClass} text-center`}>
          <p className="text-sm font-semibold text-brand">404</p>
          <h1 className="mt-4 text-3xl font-semibold text-fg">Page not found</h1>
          <p className={`${policyBodyClass} mt-3`}>
            The page you asked for does not exist or has moved.
          </p>
          <nav className="mt-6 flex flex-wrap justify-center gap-3 text-sm font-semibold">
            <Link
              href="/"
              className={buttonClass("primary")}
            >
              Go home
            </Link>
            <Link
              href="/products/"
              className={buttonClass("secondary")}
            >
              Products
            </Link>
            <Link
              href="/contact/"
              className={buttonClass("secondary")}
            >
              Contact
            </Link>
          </nav>
        </section>
      </div>
    </main>
    <SiteFooter />
    </>
  );
}
