import PolicyLayout, {
  policyBodyClass,
  policyCardClass,
  policyListClass,
  policyTitleClass,
} from "@/components/policy-layout";

export default function RefundPolicyPage() {
  return (
    <PolicyLayout
      title="Cancellation and Refund Policy"
      subtitle="How cancellations and refunds work for HalalLens subscriptions."
      updatedAt="December 31, 2025"
    >
      <section className={policyCardClass}>
        <h2 className={policyTitleClass}>Cancellations</h2>
        <p className={`${policyBodyClass} mt-3`}>
          You may stop using HalalLens at any time. If you cancel during a trial,
          access ends at the trial expiry date. Paid access remains available
          until the current plan period ends.
        </p>
      </section>

      <section className={policyCardClass}>
        <h2 className={policyTitleClass}>Refunds</h2>
        <ul className={`mt-3 ${policyListClass}`}>
          <li>
            Refunds are considered for accidental duplicate payments or
            technical billing errors.
          </li>
          <li>
            Requests should be submitted within 7 days of the payment date.
          </li>
          <li>
            Trial conversions and heavy usage during the period may make a
            refund ineligible.
          </li>
        </ul>
      </section>

      <section className={policyCardClass}>
        <h2 className={policyTitleClass}>How to request</h2>
        <p className={`${policyBodyClass} mt-3`}>
          Email{" "}
          <a
            href="mailto:support@halallens.in"
            className="text-cyan-200 hover:text-cyan-100"
          >
            support@halallens.in
          </a>{" "}
          with your order ID and registered email. We respond within 3 business
          days.
        </p>
      </section>
    </PolicyLayout>
  );
}
