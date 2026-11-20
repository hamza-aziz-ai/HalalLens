import Link from "next/link";
import SiteHeader from "@/components/site-header";
import SiteFooter from "@/components/site-footer";
import SampleScreening from "@/components/sample-screening";
import HeroConsole from "@/components/hero-console";
import { Card, buttonClass } from "@/components/ui";

const RATIOS = [
  { name: "Debt to market cap", cap: "30%", basis: "AAOIFI Shari'ah Standard 21" },
  { name: "Cash and interest-bearing deposits to market cap", cap: "30%", basis: "AAOIFI Shari'ah Standard 21" },
  { name: "Non-permissible income to revenue", cap: "5%", basis: "AAOIFI Shari'ah Standard 21" },
  { name: "Receivables to market cap", cap: "67%", basis: "Additional gate, not part of SS21" },
  { name: "Liquid assets to market cap", cap: "49%", basis: "Additional gate, not part of SS21" },
];

const STEPS = [
  {
    title: "Collect",
    body: "Company filings and market capitalisation are gathered and mapped to the five inputs. A value that cannot be read reliably is left empty, never guessed.",
  },
  {
    title: "Screen",
    body: "One engine computes every ratio in exact decimal arithmetic and decides the verdict. The dashboard, API and scheduled jobs all use that same engine.",
  },
  {
    title: "Explain",
    body: "Each verdict comes with the numbers behind it and a plain-language explanation, plus filing history and alerts when a company's status changes.",
  },
];

/** Public landing page: what HalalLens does, how it decides, and a worked sample. */
export default function LandingPage() {
  const repoUrl = process.env.NEXT_PUBLIC_REPO_URL || "";
  return (
    <>
      <SiteHeader />
      <main>
        <section className="relative overflow-hidden">
          <div className="bg-grid pointer-events-none absolute inset-0" aria-hidden="true" />
          <div className="relative mx-auto grid max-w-6xl items-center gap-12 px-4 pb-20 pt-16 sm:pt-24 lg:grid-cols-[minmax(0,1fr)_28rem]">
            <div className="animate-fade-up">
              <p className="inline-flex items-center gap-2 rounded-full border border-line bg-surface/80 px-3 py-1 font-mono text-xs text-muted">
                <span className="h-1.5 w-1.5 rounded-full bg-brand" aria-hidden="true" />
                Shariah screening for Indian equities
              </p>
              <h1 className="mt-5 text-4xl font-semibold tracking-tight text-fg sm:text-5xl">
                Know whether an Indian stock fits Islamic investing rules,{" "}
                <span className="text-gradient">and why.</span>
              </h1>
              <p className="mt-5 max-w-xl text-lg leading-relaxed text-muted">
                HalalLens screens BSE-listed companies against five AAOIFI-inspired financial ratios,
                shows the exact numbers behind every verdict, and answers &ldquo;insufficient
                data&rdquo; instead of guessing when an input is missing.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Link href="#sample" className={buttonClass("primary", "lg")}>
                  See a sample screening
                </Link>
                <Link href="/login/" className={buttonClass("secondary", "lg")}>
                  Create a free account
                </Link>
              </div>
              <dl className="mt-10 grid max-w-lg grid-cols-3 gap-6 border-t border-line pt-6">
                {[
                  ["5", "ratios per company"],
                  ["3", "possible verdicts"],
                  ["1", "engine decides every verdict"],
                ].map(([value, label]) => (
                  <div key={label}>
                    <dt className="sr-only">{label}</dt>
                    <dd className="font-mono text-2xl font-semibold text-fg">{value}</dd>
                    <dd className="mt-1 text-xs text-muted">{label}</dd>
                  </div>
                ))}
              </dl>
            </div>
            <HeroConsole />
          </div>
        </section>

        <div className="mx-auto max-w-6xl px-4 pb-12">
          <p className="rounded-lg border border-line bg-surface-2 px-4 py-3 text-sm text-muted">
            <span className="font-semibold text-fg">Data status:</span> automatic collection of BSE
            filings is not running in production yet, so few companies have stored results.
            Signed-in users can screen any company by entering its figures, and the sample on this
            page shows the complete output.
          </p>
        </div>

        <section id="method" className="scroll-mt-20 border-y border-line bg-surface">
          <div className="mx-auto max-w-6xl px-4 py-16">
            <p className="font-mono text-xs uppercase tracking-wider text-brand">01 · Method</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-fg">Five ratios, one rule</h2>
            <p className="mt-3 max-w-3xl text-muted">
              A company passes only when every ratio is within its cap. If any ratio is over its
              cap the verdict is non-compliant; if an input is unknown and nothing has failed, the
              verdict is insufficient data.
            </p>
            <div className="mt-8 overflow-x-auto">
              <table className="w-full min-w-[36rem] text-left text-sm">
                <thead>
                  <tr className="border-b border-line text-muted">
                    <th scope="col" className="py-2 pr-4 font-medium">Ratio</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Cap</th>
                    <th scope="col" className="py-2 font-medium">Basis</th>
                  </tr>
                </thead>
                <tbody>
                  {RATIOS.map((ratio) => (
                    <tr key={ratio.name} className="border-b border-line last:border-0">
                      <td className="py-3 pr-4 text-fg">{ratio.name}</td>
                      <td className="py-3 pr-4 font-mono tabular-nums text-fg">{ratio.cap}</td>
                      <td className="py-3 text-muted">{ratio.basis}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-10 grid gap-4 md:grid-cols-3">
              {STEPS.map((step, index) => (
                <Card key={step.title} className="transition hover:-translate-y-0.5 hover:border-brand/40 hover:shadow-md motion-reduce:transform-none">
                  <p className="font-mono text-xs text-brand">0{index + 1}</p>
                  <h3 className="mt-2 font-semibold text-fg">{step.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted">{step.body}</p>
                </Card>
              ))}
            </div>
            <p className="mt-6 text-sm text-muted">
              Read the{" "}
              <Link href="/learn/ratios/" className="text-brand hover:underline">
                ratio walkthrough
              </Link>{" "}
              for the definitions behind each input.
            </p>
          </div>
        </section>

        <section id="sample" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-16">
          <p className="font-mono text-xs uppercase tracking-wider text-brand">02 · Sample</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-fg">A complete screening, end to end</h2>
          <p className="mt-3 max-w-3xl text-muted">
            Two fictional companies with hand-entered figures, run through the same engine and
            explanation code the product uses. The figures are invented; the output is real.
          </p>
          <SampleScreening />
        </section>

        <section className="border-y border-line bg-surface">
          <div className="mx-auto grid max-w-6xl gap-8 px-4 py-16 md:grid-cols-2">
            <div>
              <p className="font-mono text-xs uppercase tracking-wider text-brand">03 · Transparency</p>
              <h2 className="mt-2 text-2xl font-semibold tracking-tight text-fg">Built to be checked</h2>
              <p className="mt-3 text-muted">
                Screening results only matter if you can see how they were reached.
              </p>
            </div>
            <ul className="space-y-3 text-sm leading-relaxed text-muted">
              <li>
                <span className="font-semibold text-fg">Open source.</span> The engine, thresholds and
                tests are public under the MIT licence
                {repoUrl.startsWith("https://") && (
                  <>
                    {" "}
                    (
                    <a href={repoUrl} className="text-brand hover:underline" rel="noopener noreferrer" target="_blank">
                      source code
                    </a>
                    )
                  </>
                )}
                .
              </li>
              <li>
                <span className="font-semibold text-fg">Tested decisions.</span> A table of known inputs
                and expected verdicts runs on every change.
              </li>
              <li>
                <span className="font-semibold text-fg">Payments by Razorpay.</span> Card and bank
                details are entered with Razorpay and never reach HalalLens.
              </li>
              <li>
                <span className="font-semibold text-fg">Accounts.</span> Passwords are stored only as
                salted PBKDF2 hashes, and sign-in sessions only as one-way digests.
              </li>
            </ul>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-4 py-16 text-center">
          <h2 className="text-2xl font-semibold tracking-tight text-fg">Screen a company yourself</h2>
          <p className="mx-auto mt-3 max-w-xl text-muted">
            Manual screening is free with an account. Paid plans add symbol lookup, Explain-Why on
            every verdict, filing history and alerts.
          </p>
          <div className="mt-6 flex flex-wrap justify-center gap-3">
            <Link href="/login/" className={buttonClass("primary", "lg")}>
              Create a free account
            </Link>
            <Link href="/products/" className={buttonClass("secondary", "lg")}>
              Plans and pricing
            </Link>
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
