"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { MailCheck } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { AuthHeading, GoogleButton, safeNext } from "@/components/auth-ui";
import { useConfig, useSession } from "@/components/providers";
import { Button, Field, Input, Notice } from "@/components/ui/primitives";
import { api, errorMessage, fieldErrors } from "@/lib/api";

export const passwordRule = z.string()
  .min(10, "Use at least 10 characters.")
  .max(256)
  .refine((p) => [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(p)).length >= 3,
    "Use at least three of: lowercase, uppercase, a digit, a symbol.");

const schema = z.object({
  name: z.string().max(120).optional(),
  email: z.email("Enter a valid email address."),
  password: passwordRule,
});
type Values = z.infer<typeof schema>;

export function RegisterForm() {
  const sp = useSearchParams();
  const router = useRouter();
  const config = useConfig();
  const { reloadUser } = useSession();
  const next = safeNext(sp.get("next"));
  const [error, setError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const { register, handleSubmit, setError: setFieldError, formState: { errors, isSubmitting } } = useForm<Values>({ resolver: zodResolver(schema) });

  async function onSubmit(v: Values) {
    setError(null);
    try {
      const r = await api<{ status: string }>("/api/v1/auth/register", { json: v });
      if (r.status === "verification_required") {
        setSentTo(v.email);
        return;
      }
      await reloadUser();
      router.replace(next);
    } catch (e) {
      const fields = fieldErrors(e);
      const known = (["name", "email", "password"] as const).filter((f) => fields[f]);
      if (known.length) {
        for (const f of known) {
          setFieldError(f, { message: f === "email" ? "Enter an email address that can receive mail." : fields[f] });
        }
        return;
      }
      setError(errorMessage(e));
    }
  }

  if (config && !config.features.public_signup) {
    return (<><AuthHeading title="Sign-ups are closed" /><p className="text-text-2">This workspace isn&apos;t accepting new accounts right now. <Link className="text-signal" href="/login">Sign in</Link> if you already have one.</p></>);
  }
  if (sentTo) {
    return (
      <>
        <MailCheck className="mb-5 size-8 text-signal" aria-hidden />
        <AuthHeading title="Check your inbox">We sent a verification link to <strong className="text-text">{sentTo}</strong>. It expires in 24 hours.</AuthHeading>
        <p className="text-sm text-muted">Didn&apos;t get it? Check spam, or sign in and request a new link.</p>
        <Button asChild variant="secondary" className="mt-6"><Link href="/login">Go to sign in</Link></Button>
      </>
    );
  }
  return (
    <>
      <AuthHeading title="Create your account">Your first report is a few minutes away.</AuthHeading>
      {error && <Notice className="mb-5" tone="danger">{error}</Notice>}
      <GoogleButton next={next} />
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <Field label="Name" htmlFor="name" hint="Optional">
          <Input id="name" autoComplete="name" {...register("name")} />
        </Field>
        <Field label="Email" htmlFor="email" error={errors.email?.message}>
          <Input id="email" type="email" autoComplete="email" aria-invalid={!!errors.email} {...register("email")} />
        </Field>
        <Field label="Password" htmlFor="password" error={errors.password?.message} hint="At least 10 characters, mixing letters, digits or symbols.">
          <Input id="password" type="password" autoComplete="new-password" aria-invalid={!!errors.password} {...register("password")} />
        </Field>
        <Button type="submit" className="w-full" loading={isSubmitting}>Create account</Button>
        <p className="text-[12.5px] text-muted">By continuing you agree to the <Link href="/terms" className="underline">terms</Link> and <Link href="/privacy" className="underline">privacy policy</Link>.</p>
      </form>
      <p className="mt-8 text-sm text-text-2">Already have an account? <Link className="text-signal hover:underline" href="/login">Sign in</Link></p>
    </>
  );
}
