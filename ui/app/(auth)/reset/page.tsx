"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { resetPassword, takeFragmentParam } from "@/lib/auth";
import { SetPasswordForm, authCardClass, authPageClass } from "@/components/set-password-form";

/** Opened from the password email: sets a new password and signs out every device. */
export default function ResetPasswordPage() {
  const [token, setToken] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    // One-time read from the fragment, then cleared from the address bar.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setToken(takeFragmentParam("reset"));
    setChecked(true);
  }, []);

  return (
    <div className={authPageClass}>
      <div className={authCardClass}>
        {done ? (
          <p className="text-sm text-slate-300">
            Password set and email confirmed. Every device was signed out.{" "}
            <Link href="/login" className="text-cyan-200 hover:text-cyan-100">
              Sign in
            </Link>
            .
          </p>
        ) : token ? (
          <SetPasswordForm
            title="Set your password"
            intro="Choose a new password. This also confirms your email and signs out every device."
            submitLabel="Set password"
            onSubmit={async (password) => {
              await resetPassword(token, password);
              setDone(true);
            }}
          />
        ) : checked ? (
          <p className="text-sm text-slate-300">
            This page needs the link from your password email.{" "}
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
