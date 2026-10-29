import PolicyLayout, {
  policyBodyClass,
  policyCardClass,
  policyListClass,
  policyTitleClass,
} from "@/components/policy-layout";
import SupportEmail from "@/components/support-email";

export default function ContactPage() {
  return (
    <PolicyLayout
      title="Contact Us"
      subtitle="Reach the HalalLens team for support or compliance questions."
      updatedAt="December 31, 2025"
    >
      <section className={policyCardClass}>
        <h2 className={policyTitleClass}>Support</h2>
        <ul className={`mt-3 ${policyListClass}`}>
          <li>
            Email:{" "}
            <SupportEmail className="text-cyan-200 hover:text-cyan-100" />
          </li>
          <li>Response time: within 3 business days.</li>
          <li>Coverage: India market and Shariah screening questions.</li>
        </ul>
      </section>

      <section className={policyCardClass}>
        <h2 className={policyTitleClass}>Business inquiries</h2>
        <p className={`${policyBodyClass} mt-3`}>
          For partnerships or data requests, email{" "}
          <SupportEmail className="text-cyan-200 hover:text-cyan-100" />
          .
        </p>
      </section>
    </PolicyLayout>
  );
}
