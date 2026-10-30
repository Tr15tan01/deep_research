"use client";

import { CheckCircle2, XCircle } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { AuthHeading } from "@/components/auth-ui";
import { useSession } from "@/components/providers";
import { Button, IndeterminateBar } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api";

export function VerifyEmail() {
  const token = useSearchParams().get("token");
  const { reloadUser, status } = useSession();
  const [state, setState] = useState<"working" | "ok" | "error">("working");
  const [msg, setMsg] = useState("");
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    if (!token) { setState("error"); setMsg("This link is missing its token."); return; }
    api("/api/v1/auth/verify-email", { json: { token } })
      .then(() => { setState("ok"); void reloadUser(); })
      .catch((e) => { setState("error"); setMsg(errorMessage(e)); });
  }, [token, reloadUser]);

  if (state === "working") return <><AuthHeading title="Verifying…" /><IndeterminateBar label="Verifying email" /></>;
  if (state === "ok") return (
    <>
      <CheckCircle2 className="mb-5 size-8 text-ok" aria-hidden />
      <AuthHeading title="Email verified">You can now start research.</AuthHeading>
      <Button asChild><Link href={status === "authenticated" ? "/dashboard" : "/login"}>{status === "authenticated" ? "Open workspace" : "Sign in"}</Link></Button>
    </>
  );
  return (
    <>
      <XCircle className="mb-5 size-8 text-danger" aria-hidden />
      <AuthHeading title="This link didn't work">{msg}</AuthHeading>
      <p className="text-sm text-text-2">Sign in and use “Resend verification email” to get a new link.</p>
      <Button asChild variant="secondary" className="mt-6"><Link href="/login">Sign in</Link></Button>
    </>
  );
}
