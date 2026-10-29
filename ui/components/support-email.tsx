/**
 * The support address shown on the policy and contact pages. Set at build
 * time (NEXT_PUBLIC_SUPPORT_EMAIL; production compose derives it from the
 * domain), never hardcoded, so a fork or a buyer only changes configuration.
 */
export const SUPPORT_EMAIL = process.env.NEXT_PUBLIC_SUPPORT_EMAIL || "";

export default function SupportEmail({ className }: { className?: string }) {
  if (!SUPPORT_EMAIL) {
    return <span className={className}>our support team</span>;
  }
  return (
    <a href={`mailto:${SUPPORT_EMAIL}`} className={className}>
      {SUPPORT_EMAIL}
    </a>
  );
}
