import Link from "next/link";
import SiteFooter from "@/components/site-footer";
import { policyBodyClass, policyCardClass } from "@/components/policy-layout";

// Exported as 404.html; the UI image's Caddy serves it for every unknown path.
export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col bg-[radial-gradient(1200px_circle_at_10%_-10%,rgba(14,116,144,0.35),transparent_45%),radial-gradient(900px_circle_at_85%_0%,rgba(16,185,129,0.18),transparent_40%),#05070d] px-4 py-12 text-slate-100">
      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-8">
        <section className={`${policyCardClass} text-center`}>
          <p className="text-xs uppercase tracking-[0.2em] text-cyan-300/80">HalalLens · 404</p>
          <h1 className="mt-4 text-3xl font-semibold text-white">Page not found</h1>
          <p className={`${policyBodyClass} mt-3`}>
            The page you asked for does not exist or has moved.
          </p>
          <nav className="mt-6 flex flex-wrap justify-center gap-3 text-sm font-semibold">
            <Link
              href="/"
              className="rounded-full bg-cyan-400/90 px-5 py-2 text-slate-950 hover:bg-cyan-300"
            >
              Go home
            </Link>
            <Link
              href="/products/"
              className="rounded-full border border-white/15 px-5 py-2 text-cyan-200 hover:text-cyan-100"
            >
              Products
            </Link>
            <Link
              href="/contact/"
              className="rounded-full border border-white/15 px-5 py-2 text-cyan-200 hover:text-cyan-100"
            >
              Contact
            </Link>
          </nav>
        </section>
      </div>
      <SiteFooter />
    </main>
  );
}
