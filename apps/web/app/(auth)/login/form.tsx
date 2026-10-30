"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { AuthHeading, GoogleButton, OAUTH_ERRORS, safeNext } from "@/components/auth-ui";
import { useConfig, useSession } from "@/components/providers";
import { Button, Field, Input, Notice } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api";

const schema = z.object({ email: z.email("Enter a valid email address."), password: z.string().min(1, "Enter your password.") });
type Values = z.infer<typeof schema>;

export function LoginForm() {
  const sp = useSearchParams();
  const router = useRouter();
  const config = useConfig();
  const { reloadUser } = useSession();
  const next = safeNext(sp.get("next"));
  const [error, setError] = useState<string | null>(OAUTH_ERRORS[sp.get("error") ?? ""] ?? (sp.get("error") ? "Sign-in failed. Please try again." : null));
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({ resolver: zodResolver(schema) });

  useEffect(() => {
    // A stale session hint can send us here; clear it so routing doesn't loop.
    if (sp.get("expired")) void api("/api/v1/auth/logout", { method: "POST", retryOn401: false }).catch(() => undefined);
  }, [sp]);

  async function onSubmit(v: Values) {
    setError(null);
    try {
      await api("/api/v1/auth/login", { json: v });
      await reloadUser();
      router.replace(next);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <>
      <AuthHeading title="Welcome back">Sign in to continue your research.</AuthHeading>
      {sp.get("expired") && <Notice className="mb-5" title="Your session ended">Please sign in again.</Notice>}
      {error && <Notice className="mb-5" tone="danger">{error}</Notice>}
      <GoogleButton next={next} />
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <Field label="Email" htmlFor="email" error={errors.email?.message}>
          <Input id="email" type="email" autoComplete="email" aria-invalid={!!errors.email} {...register("email")} />
        </Field>
        <Field label="Password" htmlFor="password" error={errors.password?.message}>
          <Input id="password" type="password" autoComplete="current-password" aria-invalid={!!errors.password} {...register("password")} />
        </Field>
        <div className="flex items-center justify-between pt-1">
          {config?.features.password_reset !== false && <Link href="/forgot-password" className="text-sm text-text-2 hover:text-text">Forgot password?</Link>}
          <Button type="submit" loading={isSubmitting}>Sign in</Button>
        </div>
      </form>
      {config?.features.public_signup !== false && (
        <p className="mt-8 text-sm text-text-2">New here? <Link className="text-signal hover:underline" href={`/register${next !== "/dashboard" ? `?next=${encodeURIComponent(next)}` : ""}`}>Create an account</Link></p>
      )}
    </>
  );
}
