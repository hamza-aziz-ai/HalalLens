"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { confirmSignup, takeFragmentParam } from "@/lib/auth";
import { useAuth } from "@/providers/AuthProvider";
import { SetPasswordForm, authCardClass, authPageClass } from "@/components/set-password-form";

/** Opened from the sign-up email: proves the mailbox, then the password is chosen. */
export default function VerifyEmailPage() {
  const router = useRouter();
  const { setUser } = useAuth();
  const [token, setToken] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    // One-time read from the fragment, then cleared from the address bar.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setToken(takeFragmentParam("signup"));
    setChecked(true);
  }, []);

  return (
    <div className={authPageClass}>
      <div className={authCardClass}>
        {token ? (
          <SetPasswordForm
            title="Create your HalalLens account"
            intro="Your email is confirmed. Choose a password to finish."
            submitLabel="Create account"
            onSubmit={async (password) => {
              setUser(await confirmSignup(token, password));
              router.replace("/dashboard");
            }}
          />
        ) : checked ? (
          <p className="text-sm text-slate-300">
            This page needs the link from your sign-up email.{" "}
            <Link href="/login" className="text-cyan-200 hover:text-cyan-100">
              Request a new one
            </Link>
            .
          </p>
        ) : null}
      </div>
    </div>
  );
}
