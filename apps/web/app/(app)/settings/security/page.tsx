"use client";

import { Monitor } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { useConfig, useSession } from "@/components/providers";
import { Badge, Button, Field, Input, Panel, Skeleton } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { relativeTime } from "@/lib/utils";

interface S { id: string; created_at: string; last_used_at: string; ip?: string; user_agent?: string; method?: string; current: boolean }

function device(ua?: string): string {
  if (!ua) return "Unknown device";
  const browser = /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Firefox\//.test(ua) ? "Firefox" : /Safari\//.test(ua) ? "Safari" : "Browser";
  const os = /Windows/.test(ua) ? "Windows" : /Mac OS X/.test(ua) ? "macOS" : /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Linux/.test(ua) ? "Linux" : "";
  return `${browser}${os ? ` on ${os}` : ""}`;
}

export default function SecurityPage() {
  const { user } = useSession();
  const config = useConfig();
  const sessions = useApi<{ items: S[] }>("/api/v1/auth/sessions");
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <div className="space-y-6">
      <Panel className="p-6">
        <h2 className="text-lg font-semibold">{user?.has_password ? "Change password" : "Set a password"}</h2>
        <p className="mt-1 text-sm text-text-2">Other sessions are signed out when you change your password.</p>
        <form className="mt-4 grid gap-4 sm:grid-cols-2" onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try { await api("/api/v1/auth/change-password", { json: { current_password: cur || null, new_password: next } }); toast.success("Password changed"); setCur(""); setNext(""); void sessions.reload(); }
          catch (err) { toast.error(errorMessage(err)); } finally { setBusy(false); }
        }}>
          {user?.has_password && <Field label="Current password" htmlFor="cur"><Input id="cur" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} /></Field>}
          <Field label="New password" htmlFor="new" hint="At least 10 characters, mixing letters, digits or symbols."><Input id="new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} /></Field>
          <div className="sm:col-span-2"><Button type="submit" loading={busy} disabled={next.length < 10}>Change password</Button></div>
        </form>
      </Panel>

      {config?.features.google_auth && (
        <Panel className="flex items-center justify-between p-6">
          <div><h2 className="text-lg font-semibold">Google sign-in</h2><p className="text-sm text-text-2">{user?.google_linked ? "Your Google account is linked." : "Sign in with Google using the same verified email to link it."}</p></div>
          {user?.google_linked ? <Badge tone="ok">Linked</Badge> : (
            <Button asChild variant="secondary" size="sm">
              {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- full-page navigation to the OAuth redirect endpoint, not a page */}
              <a href="/api/v1/auth/google/start?next=/settings/security">Link Google</a>
            </Button>
          )}
        </Panel>
      )}

      <Panel className="p-6">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">Active sessions</h2>
          <Button size="sm" variant="secondary" onClick={async () => {
            try { const r = await api<{ revoked: number }>("/api/v1/auth/sessions/revoke-others", { method: "POST" }); toast.success(`Signed out ${r.revoked} other session(s)`); void sessions.reload(); }
            catch (e) { toast.error(errorMessage(e)); }
          }}>Sign out other sessions</Button>
        </div>
        {sessions.loading && !sessions.data ? <Skeleton className="mt-4 h-24 w-full" /> : (
          <ul className="mt-4 divide-y divide-line">
            {sessions.data?.items.map((s) => (
              <li key={s.id} className="flex items-center justify-between gap-3 py-3">
                <div className="flex items-center gap-3">
                  <Monitor className="size-5 text-muted" />
                  <div>
                    <p className="text-sm font-medium">{device(s.user_agent)} {s.current && <Badge tone="signal" className="ml-1">This device</Badge>}</p>
                    <p className="text-[12.5px] text-muted">{s.method === "google" ? "Google" : "Password"} sign-in, active {relativeTime(s.last_used_at)}{s.ip ? `, IP ${s.ip}` : ""}</p>
                  </div>
                </div>
                {!s.current && <Button size="sm" variant="ghost" onClick={async () => { await api(`/api/v1/auth/sessions/${s.id}`, { method: "DELETE" }); void sessions.reload(); }}>Sign out</Button>}
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
