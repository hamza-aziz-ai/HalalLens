import PolicyLayout, {
  policyBodyClass,
  policyCardClass,
  policyListClass,
  policyTitleClass,
} from "@/components/policy-layout";

export default function PrivacyPage() {
  return (
    <PolicyLayout
      title="Privacy Policy"
      subtitle="How HalalLens collects, uses, and protects your information."
      updatedAt="December 31, 2025"
    >
      <section className={policyCardClass}>
        <h2 className={policyTitleClass}>Information we collect</h2>
        <ul className={`mt-3 ${policyListClass}`}>
          <li>Account details such as email and login provider.</li>
          <li>Subscription status and billing metadata.</li>
          <li>Usage analytics and feature interactions.</li>
          <li>Support requests you send to us.</li>
        </ul>
      </section>

      <section className={policyCardClass}>
        <h2 className={policyTitleClass}>How we use information</h2>
        <ul className={`mt-3 ${policyListClass}`}>
          <li>Deliver access to your subscription plan.</li>
          <li>Improve accuracy of screenings and alerts.</li>
          <li>Respond to support and compliance queries.</li>
          <li>Maintain audit logs and security monitoring.</li>
        </ul>
      </section>

      <section className={policyCardClass}>
        <h2 className={policyTitleClass}>Payments</h2>
        <p className={`${policyBodyClass} mt-3`}>
          Payments are processed by Razorpay. We do not store your card details.
          Razorpay may collect additional information as required for payment
          processing and compliance.
        </p>
      </section>

      <section className={policyCardClass}>
        <h2 className={policyTitleClass}>Data retention</h2>
        <p className={`${policyBodyClass} mt-3`}>
          We retain account data for as long as your account is active or as
          needed for legal and audit purposes. You can request deletion by
          contacting support.
        </p>
      </section>

      <section className={policyCardClass}>
        <h2 className={policyTitleClass}>Contact</h2>
        <p className={`${policyBodyClass} mt-3`}>
          Questions about privacy can be sent to{" "}
          <a
            href="mailto:support@halallens.in"
            className="text-cyan-200 hover:text-cyan-100"
          >
            support@halallens.in
          </a>
          .
        </p>
      </section>
    </PolicyLayout>
  );
}
