import PolicyLayout, {
  policyBodyClass,
  policyCardClass,
  policyListClass,
  policyTitleClass,
} from "@/components/policy-layout";
import SupportEmail from "@/components/support-email";

export default function TermsPage() {
  return (
    <PolicyLayout
      title="Terms and Conditions"
      subtitle="These terms govern access to HalalLens and the educational services we provide."
      updatedAt="December 31, 2025"
    >
      <section className={policyCardClass}>
        <h2 className={policyTitleClass}>Overview</h2>
        <p className={`${policyBodyClass} mt-3`}>
          HalalLens provides Shariah compliance screening and education for
          Indian equities. We do not provide investment advice or portfolio
          management. Use the service to inform your own research.
        </p>
      </section>

      <section className={policyCardClass}>
        <h2 className={policyTitleClass}>Accounts and access</h2>
        <ul className={`mt-3 ${policyListClass}`}>
          <li>Keep your login credentials secure and do not share access.</li>
          <li>
            You are responsible for activity conducted through your account.
          </li>
          <li>
            Admin access is reserved for internal use and may be revoked for
            misuse.
          </li>
        </ul>
      </section>

      <section className={policyCardClass}>
        <h2 className={policyTitleClass}>Subscriptions</h2>
        <ul className={`mt-3 ${policyListClass}`}>
          <li>Plans unlock premium research tools and narration.</li>
          <li>
            Trials are available once per account where stated in the plan.
          </li>
          <li>
            Subscriptions are not investment advice and do not guarantee
            accuracy.
          </li>
        </ul>
      </section>

      <section className={policyCardClass}>
        <h2 className={policyTitleClass}>Data sources and accuracy</h2>
        <p className={`${policyBodyClass} mt-3`}>
          We aggregate data from public sources such as BSE and Indian market
          data providers. Despite safeguards, data may be delayed or incomplete.
          Always verify critical information independently.
        </p>
      </section>

      <section className={policyCardClass}>
        <h2 className={policyTitleClass}>Limitation of liability</h2>
        <p className={`${policyBodyClass} mt-3`}>
          HalalLens is provided on an as-is basis. We are not liable for losses
          arising from reliance on the service, data outages, or third-party
          changes.
        </p>
      </section>

      <section className={policyCardClass}>
        <h2 className={policyTitleClass}>Contact</h2>
        <p className={`${policyBodyClass} mt-3`}>
          Reach us at{" "}
          <SupportEmail className="text-cyan-200 hover:text-cyan-100" />{" "}
          for questions about these terms.
        </p>
      </section>
    </PolicyLayout>
  );
}
