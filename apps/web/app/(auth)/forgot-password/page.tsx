"use client";

import Link from "next/link";
import { useState } from "react";

import { AuthHeading } from "@/components/auth-ui";
import { Button, Field, Input, Notice } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/api/v1/auth/forgot-password", { json: { email } });
      setSent(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  if (sent) return (
    <>
      <AuthHeading title="Check your email">If an account exists for {email}, a reset link is on its way. It expires in 30 minutes.</AuthHeading>
      <Button asChild variant="secondary"><Link href="/login">Back to sign in</Link></Button>
    </>
  );
  return (
    <>
      <AuthHeading title="Reset your password">Enter your email and we&apos;ll send you a link to choose a new password.</AuthHeading>
      {error && <Notice className="mb-5" tone="danger">{error}</Notice>}
      <form onSubmit={submit} className="space-y-4">
        <Field label="Email" htmlFor="email"><Input id="email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Button type="submit" loading={busy} className="w-full">Send reset link</Button>
      </form>
      <p className="mt-8 text-sm"><Link href="/login" className="text-text-2 hover:text-text">Back to sign in</Link></p>
    </>
  );
}
