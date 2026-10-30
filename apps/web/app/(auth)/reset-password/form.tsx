"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { AuthHeading } from "@/components/auth-ui";
import { Button, Field, Input, Notice } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api";

import { passwordRule } from "../register/form";

export function ResetForm() {
  const token = useSearchParams().get("token") ?? "";
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const check = passwordRule.safeParse(pw);
    if (!check.success) return setError(check.error.issues[0]?.message ?? "Choose a stronger password.");
    if (pw !== pw2) return setError("The passwords don't match.");
    setBusy(true);
    setError(null);
    try {
      await api("/api/v1/auth/reset-password", { json: { token, password: pw } });
      setDone(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  if (!token) return <><AuthHeading title="Link incomplete">Open the link from your email again, or request a new one.</AuthHeading><Button asChild variant="secondary"><Link href="/forgot-password">Request a new link</Link></Button></>;
  if (done) return <><AuthHeading title="Password changed">For your security, you&apos;ve been signed out everywhere. Sign in with your new password.</AuthHeading><Button asChild><Link href="/login">Sign in</Link></Button></>;
  return (
    <>
      <AuthHeading title="Choose a new password" />
      {error && <Notice className="mb-5" tone="danger">{error}</Notice>}
      <form onSubmit={submit} className="space-y-4">
        <Field label="New password" htmlFor="pw" hint="At least 10 characters, mixing letters, digits or symbols."><Input id="pw" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
        <Field label="Confirm new password" htmlFor="pw2"><Input id="pw2" type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} /></Field>
        <Button type="submit" loading={busy} className="w-full">Change password</Button>
      </form>
    </>
  );
}
