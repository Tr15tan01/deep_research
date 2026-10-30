"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Field, Input, Notice, Panel, Select, Skeleton } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api";
import { useApi } from "@/lib/hooks";

interface M { selection_enabled: boolean; byok_enabled: boolean; default: { provider: string; model: string } | null; allowed: { provider: string; model: string; label: string }[]; own_keys: { provider: string; masked: string }[]; demo_mode: boolean }

export default function UserProvidersPage() {
  const { data, loading, reload } = useApi<M>("/api/v1/models");
  const [provider, setProvider] = useState("openai");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  if (loading && !data) return <Skeleton className="h-64 w-full" />;
  if (!data) return null;
  return (
    <div className="space-y-6">
      <Panel className="p-6">
        <h2 className="text-lg font-semibold">Models</h2>
        <p className="mt-1 text-sm text-text-2">Default: {data.default ? <strong>{data.default.provider} / {data.default.model}</strong> : "not configured"}.</p>
        {data.selection_enabled ? (
          data.allowed.length ? (
            <ul className="mt-3 space-y-1.5 text-sm">{data.allowed.map((m) => <li key={`${m.provider}:${m.model}`}><Badge>{m.provider}</Badge> {m.label || m.model}</li>)}</ul>
          ) : <p className="mt-2 text-sm text-muted">Your administrator hasn&apos;t approved additional models yet.</p>
        ) : <p className="mt-2 text-sm text-muted">Model selection is managed by your administrator.</p>}
        <p className="mt-3 text-[13px] text-muted">Choose a model per run under “Advanced options” when starting research.</p>
      </Panel>
      {data.byok_enabled && (
        <Panel className="p-6">
          <h2 className="text-lg font-semibold">Your own API keys</h2>
          <p className="mt-1 text-sm text-text-2">Keys are encrypted on our servers, never shown again, and used only for runs where you choose “Use my own API key”.</p>
          {!!data.own_keys.length && (
            <ul className="mt-4 divide-y divide-line rounded-xl border border-line">
              {data.own_keys.map((k) => (
                <li key={k.provider} className="flex items-center justify-between px-4 py-2.5 text-sm">
                  <span>{k.provider} <span className="text-muted">{k.masked}</span></span>
                  <Button size="sm" variant="ghost" onClick={async () => { await api("/api/v1/models/own-key", { method: "PUT", json: { provider: k.provider, api_key: null } }); void reload(); }}>Remove</Button>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-4 grid gap-3 sm:grid-cols-[160px_1fr_auto] sm:items-end">
            <Field label="Provider" htmlFor="pv"><Select id="pv" value={provider} onChange={(e) => setProvider(e.target.value)}><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="gemini">Google Gemini</option></Select></Field>
            <Field label="API key" htmlFor="key"><Input id="key" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} /></Field>
            <Button loading={busy} disabled={key.length < 8} onClick={async () => {
              setBusy(true);
              try { await api("/api/v1/models/own-key", { method: "PUT", json: { provider, api_key: key } }); setKey(""); toast.success("Key saved"); void reload(); }
              catch (e) { toast.error(errorMessage(e)); } finally { setBusy(false); }
            }}>Save key</Button>
          </div>
        </Panel>
      )}
      {data.demo_mode && <Notice tone="lamp">Demo mode is on; runs use the deterministic demo model regardless of these settings.</Notice>}
    </div>
  );
}
