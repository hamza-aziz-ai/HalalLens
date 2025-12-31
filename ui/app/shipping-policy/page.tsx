import PolicyLayout, {
  policyBodyClass,
  policyCardClass,
  policyTitleClass,
} from "@/components/policy-layout";

export default function ShippingPolicyPage() {
  return (
    <PolicyLayout
      title="Shipping Policy"
      subtitle="HalalLens is a digital service and does not ship physical goods."
      updatedAt="December 31, 2025"
    >
      <section className={policyCardClass}>
        <h2 className={policyTitleClass}>Digital delivery</h2>
        <p className={`${policyBodyClass} mt-3`}>
          HalalLens is delivered electronically. Access is provisioned
          immediately after a successful payment or when a trial is activated.
        </p>
      </section>

      <section className={policyCardClass}>
        <h2 className={policyTitleClass}>No physical shipping</h2>
        <p className={`${policyBodyClass} mt-3`}>
          We do not ship any physical items. There are no shipping charges.
        </p>
      </section>
    </PolicyLayout>
  );
}
