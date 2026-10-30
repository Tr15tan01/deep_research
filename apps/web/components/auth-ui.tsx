"use client";

import { useConfig } from "@/components/providers";

export function AuthHeading({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="mb-8">
      <h1 className="display text-[44px]">{title}</h1>
      {children && <p className="mt-3 text-text-2">{children}</p>}
    </div>
  );
}

export function GoogleButton({ next }: { next?: string }) {
  const config = useConfig();
  if (!config?.features.google_auth) return null;
  if (!config.features.google_auth_configured) {
    return <p className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-[13px] text-muted">Google sign-in is enabled but not configured yet.</p>;
  }
  const href = `/api/v1/auth/google/start${next ? `?next=${encodeURIComponent(next)}` : ""}`;
  return (
    <>
      <a href={href} className="flex h-11 w-full items-center justify-center gap-3 rounded-xl border border-line-strong bg-surface text-sm font-medium hover:bg-surface-2">
        <svg viewBox="0 0 24 24" className="size-[18px]" aria-hidden>
          <path fill="#EA4335" d="M12 10.2v3.9h5.5c-.24 1.4-1.7 4.1-5.5 4.1-3.3 0-6-2.7-6-6.1s2.7-6.1 6-6.1c1.9 0 3.1.8 3.8 1.5l2.6-2.5C16.8 3.5 14.6 2.5 12 2.5 6.8 2.5 2.6 6.7 2.6 12s4.2 9.5 9.4 9.5c5.4 0 9-3.8 9-9.2 0-.6-.1-1.1-.2-1.6H12z" />
        </svg>
        Continue with Google
      </a>
      <div className="my-6 flex items-center gap-3 text-[12.5px] text-muted"><span className="h-px flex-1 bg-line" />or with email<span className="h-px flex-1 bg-line" /></div>
    </>
  );
}

export const OAUTH_ERRORS: Record<string, string> = {
  oauth_cancelled: "Google sign-in was cancelled.",
  oauth_state_mismatch: "That sign-in link expired or was already used. Please try again.",
  oauth_replay: "That sign-in attempt was already used. Please try again.",
  oauth_email_unverified: "Your Google account's email isn't verified.",
  oauth_link_requires_verification: "An account with this email exists but isn't verified. Sign in with your password and verify your email first.",
  account_disabled: "This account is disabled.",
  signup_disabled: "New sign-ups are currently closed.",
  oauth_exchange_failed: "Google sign-in failed. Please try again.",
  oauth_invalid_token: "We couldn't verify your Google identity. Please try again.",
  oauth_unavailable: "Couldn't reach Google. Please try again.",
};

export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return "/dashboard";
  return next;
}
