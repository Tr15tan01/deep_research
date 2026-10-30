"use client";

import { CheckCircle2, KeyRound, Plus, RefreshCcw, Trash2, XCircle } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Field, Input, Notice, Panel, Select, Skeleton, Switch } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { cn, relativeTime } from "@/lib/utils";

type Provider = "gemini" | "openai" | "anthropic" | "openai_compatible" | "demo";
interface Ref { provider: Provider; model: string }
interface Allowed extends Ref { label: string }
interface Price { input_per_mtok_usd: number; output_per_mtok_usd: number; as_of: string; source_note: string }
interface Caps { context_window: number; max_output_tokens: number; supports_json_schema: boolean; supports_tools: boolean; supports_streaming: boolean; supports_temperature: boolean; supports_system_prompt: boolean; source: string; notes: string[] }
interface Data {
  config: { default: Ref | null; tasks: Record<string, Ref | null>; cheap: Ref | null; fallback: Ref | null; allowed_user_models: Allowed[]; openai_compatible_base_url: string; capability_overrides: Record<string, Partial<Caps>>; pricing: Record<string, Price> };
  credentials: Record<string, { configured: boolean; source: string; masked: string; updated_at?: string }>;
  capabilities: Record<string, Caps>;
  health: Record<string, Record<string, string> | null>;
  search: { configured: Record<string, boolean>; primary: string; fallback_enabled: boolean; health: Record<string, Record<string, string> | null>;
    credentials: Record<string, { configured: boolean; source: string; masked: string; updated_at?: string }> };
  policy: Record<string, boolean>;
}

const SEARCH_LABELS: Record<string, string> = { firecrawl: "Firecrawl", tavily: "Tavily", brave: "Brave Search", openalex: "OpenAlex", demo: "Demo (synthetic)" };
const PROVIDERS: [Provider, string][] = [["gemini", "Google Gemini"], ["openai", "OpenAI"], ["anthropic", "Anthropic"], ["openai_compatible", "OpenAI-compatible"]];
const TASKS: [string, string][] = [["planning", "Planning"], ["extraction", "Source extraction"], ["verification", "Verification"], ["synthesis", "Writing (synthesis)"], ["charts", "Comparison and charts"]];

function HealthLine({ h }: { h: Record<string, string> | null | undefined }) {
  if (!h) return <span className="text-[12.5px] text-muted">No calls recorded yet</span>;
  const ok = Number(h.last_ok_at ?? 0), err = Number(h.last_error_at ?? 0);
  const healthy = ok >= err;
  return (
    <span className="flex flex-wrap items-center gap-2 text-[12.5px] text-muted">
      <Badge tone={healthy ? "ok" : "warn"}>{healthy ? "Last call succeeded" : `Last error: ${(h.last_error_kind ?? "").replace(/_/g, " ")}`}</Badge>
      {ok > 0 && <span>OK {relativeTime(new Date(ok * 1000).toISOString())}</span>}
      {err > 0 && <span>error {relativeTime(new Date(err * 1000).toISOString())}</span>}
      {h.last_latency_ms && <span>{h.last_latency_ms} ms</span>}
      <span>{h.ok ?? 0} ok / {h.errors ?? 0} errors (7 days)</span>
    </span>
  );
}

function ModelPicker({ value, onChange, allowEmpty, label, id }: { value: Ref | null; onChange: (r: Ref | null) => void; allowEmpty?: string; label: string; id: string }) {
  const [provider, setProvider] = useState<Provider>(value?.provider ?? "gemini");
  const [model, setModel] = useState(value?.model ?? "");
  return (
    <div className="grid gap-2 sm:grid-cols-[170px_1fr]">
      <Select id={`${id}-p`} aria-label={`${label} provider`} value={value ? provider : allowEmpty ? "" : provider} onChange={(e) => {
        const p = e.target.value as Provider | "";
        if (!p) { onChange(null); return; }
        setProvider(p);
        if (model) onChange({ provider: p, model });
      }}>
        {allowEmpty && <option value="">{allowEmpty}</option>}
        {PROVIDERS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        {provider === "demo" && <option value="demo">Demo (synthetic)</option>}
      </Select>
      <Input id={id} aria-label={`${label} exact model ID`} placeholder="Exact model ID, e.g. as listed by the provider" value={model}
        onChange={(e) => { setModel(e.target.value); onChange(e.target.value.trim() ? { provider, model: e.target.value.trim() } : allowEmpty ? null : value); }} />
    </div>
  );
}

export default function AdminProviders() {
  const { data, loading, reload } = useApi<Data>("/api/v1/admin/providers");
  const [draft, setDraft] = useState<Data["config"] | null>(null);
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [tests, setTests] = useState<Record<string, { ok: boolean; message?: string; latency_ms?: number; error?: string; sample?: string }>>({});
  const [discovered, setDiscovered] = useState<Record<string, { id: string; display_name?: string; context_window?: number; max_output_tokens?: number }[]>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [priceDraft, setPriceDraft] = useState({ provider: "gemini", model: "", input: "", output: "", as_of: new Date().toISOString().slice(0, 10), note: "" });

  if (loading && !data) return <Skeleton className="h-96 w-full" />;
  if (!data) return null;
  const cfg = draft ?? data.config;
  const edit = (patch: Partial<Data["config"]>) => setDraft({ ...cfg, ...patch });

  async function saveConfig() {
    setBusy("save");
    try {
      const clear = (["default", "cheap", "fallback"] as const).filter((k) => !cfg[k] && data!.config[k]);
      await api("/api/v1/admin/providers", { method: "PUT", json: { default: cfg.default, tasks: cfg.tasks, cheap: cfg.cheap, fallback: cfg.fallback,
        allowed_user_models: cfg.allowed_user_models, openai_compatible_base_url: cfg.openai_compatible_base_url, clear } });
      toast.success("Provider configuration saved");
      setDraft(null);
      void reload();
    } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(null); }
  }
  async function saveKey(p: string, value: string | null) {
    setBusy(`key-${p}`);
    try { await api("/api/v1/admin/providers/keys", { method: "PUT", json: { provider: p, api_key: value } }); setKeys({ ...keys, [p]: "" }); toast.success(value ? "Key saved (encrypted)" : "Key removed"); void reload(); }
    catch (e) { toast.error(errorMessage(e)); } finally { setBusy(null); }
  }
  async function test(ref: Ref) {
    const k = `${ref.provider}:${ref.model}`;
    setBusy(`test-${k}`);
    try { const r = await api<{ ok: boolean }>("/api/v1/admin/providers/test", { json: ref }); setTests({ ...tests, [k]: r }); void reload(); }
    catch (e) { toast.error(errorMessage(e)); } finally { setBusy(null); }
  }
  async function discover(p: string) {
    setBusy(`disc-${p}`);
    try {
      const r = await api<{ ok: boolean; models: { id: string }[]; message?: string }>(`/api/v1/admin/providers/${p}/models`);
      if (!r.ok) toast.error(r.message ?? "Discovery failed"); else { setDiscovered({ ...discovered, [p]: r.models }); toast.success(`${r.models.length} models found`); }
    } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(null); }
  }
  async function savePrice(remove?: string) {
    try {
      const [provider, model] = remove ? [remove.split(":")[0], remove.split(":").slice(1).join(":")] : [priceDraft.provider, priceDraft.model.trim()];
      await api("/api/v1/admin/pricing", { method: "PUT", json: { provider, model, price: remove ? null : {
        input_per_mtok_usd: Number(priceDraft.input), output_per_mtok_usd: Number(priceDraft.output), as_of: priceDraft.as_of, source_note: priceDraft.note } } });
      toast.success(remove ? "Price removed" : "Price saved");
      void reload();
    } catch (e) { toast.error(errorMessage(e)); }
  }
  async function saveCaps(key: string, caps: Partial<Caps> | null) {
    const [provider, ...rest] = key.split(":");
    try { await api("/api/v1/admin/providers/capabilities", { method: "PUT", json: { provider, model: rest.join(":"), override: caps } }); toast.success("Capabilities updated"); void reload(); }
    catch (e) { toast.error(errorMessage(e)); }
  }

  const refsInUse = [cfg.default, cfg.cheap, cfg.fallback, ...Object.values(cfg.tasks ?? {}), ...cfg.allowed_user_models].filter(Boolean) as Ref[];
  const uniqueRefs = [...new Map(refsInUse.map((r) => [`${r.provider}:${r.model}`, r])).values()];

  return (
    <div className="space-y-8">
      {data.policy.demo_mode && <Notice tone="lamp" title="Demo mode is on">Research uses the deterministic demo provider; these settings apply once DEMO_MODE=0.</Notice>}

      <section>
        <h2 className="headline mb-3 text-2xl">Credentials</h2>
        <p className="mb-4 max-w-[75ch] text-sm text-text-2">Keys set as environment variables take precedence and are read-only here. Keys saved here are encrypted with the server&apos;s ENCRYPTION_KEYS and never sent back to the browser.</p>
        <div className="grid gap-4 lg:grid-cols-2">
          {PROVIDERS.map(([p, label]) => {
            const c = data.credentials[p];
            return (
              <Panel key={p} className="space-y-3 p-5">
                <div className="flex items-center justify-between gap-2">
                  <p className="flex items-center gap-2 font-semibold"><KeyRound className="size-4 text-muted" />{label}</p>
                  {c?.configured ? <Badge tone="ok">{c.source === "environment" ? "From environment" : "Stored"} {c.masked}</Badge> : <Badge tone="warn">No key</Badge>}
                </div>
                <HealthLine h={data.health[p]} />
                {c?.source !== "environment" && (
                  <div className="flex gap-2">
                    <Input type="password" autoComplete="off" placeholder={c?.configured ? "Replace key" : "Paste API key"} aria-label={`${label} API key`}
                      value={keys[p] ?? ""} onChange={(e) => setKeys({ ...keys, [p]: e.target.value })} />
                    <Button loading={busy === `key-${p}`} disabled={(keys[p] ?? "").length < 8} onClick={() => void saveKey(p, keys[p] ?? "")}>Save</Button>
                    {c?.configured && <Button variant="ghost" size="icon" aria-label={`Remove ${label} key`} onClick={() => void saveKey(p, null)}><Trash2 /></Button>}
                  </div>
                )}
                {p === "openai_compatible" && (
                  <Field label="Base URL" htmlFor="ocb" hint="For example https://my-gateway.example.com/v1">
                    <Input id="ocb" value={cfg.openai_compatible_base_url} onChange={(e) => edit({ openai_compatible_base_url: e.target.value })} />
                  </Field>
                )}
                <Button size="sm" variant="ghost" loading={busy === `disc-${p}`} disabled={!c?.configured} onClick={() => void discover(p)}><RefreshCcw />List available models</Button>
                {!!discovered[p]?.length && (
                  <div className="max-h-[180px] overflow-y-auto rounded-lg border border-line">
                    {discovered[p]!.map((m) => (
                      <button key={m.id} className="flex w-full items-center justify-between px-3 py-1.5 text-left text-[12.5px] hover:bg-surface-2"
                        onClick={() => { navigator.clipboard.writeText(m.id); toast.success(`Copied ${m.id}`); }}>
                        <span className="font-mono">{m.id}</span>
                        <span className="text-muted">{m.context_window ? `${Math.round(m.context_window / 1000)}k ctx` : ""}</span>
                      </button>
                    ))}
                  </div>
                )}
              </Panel>
            );
          })}
        </div>
      </section>

      <section>
        <h2 className="headline mb-3 text-2xl">Models</h2>
        <Panel className="space-y-6 p-6">
          <Field label="Default model" htmlFor="def" hint="Used for every task without a specific model below.">
            <ModelPicker id="def" label="Default" value={cfg.default} onChange={(r) => edit({ default: r })} />
          </Field>
          <div className="grid gap-5 lg:grid-cols-2">
            {TASKS.map(([t, l]) => (
              <Field key={t} label={l} htmlFor={`t-${t}`}>
                <ModelPicker id={`t-${t}`} label={l} allowEmpty="Use default" value={cfg.tasks?.[t] ?? null}
                  onChange={(r) => edit({ tasks: { ...cfg.tasks, [t]: r } })} />
              </Field>
            ))}
          </div>
          <Field label="Cheaper model for routine sub-tasks" htmlFor="cheap" hint="Used for question assessment, and for extraction/verification when no task model is set.">
            <ModelPicker id="cheap" label="Cheap" allowEmpty="None" value={cfg.cheap} onChange={(r) => edit({ cheap: r })} />
          </Field>
          <Field label="Fallback model" htmlFor="fb" hint={`Used only when the primary fails (outage, rate limit, quota, invalid key) and AI_FALLBACK_ENABLED=1 (currently ${data.policy.fallback_enabled ? "on" : "off"}). Every switch is recorded and shown to the user; job budgets still apply.`}>
            <ModelPicker id="fb" label="Fallback" allowEmpty="No fallback" value={cfg.fallback} onChange={(r) => edit({ fallback: r })} />
          </Field>
          <div>
            <p className="text-[13px] font-medium text-text-2">Models users may choose {data.policy.allow_user_model_selection ? "" : <span className="text-muted">(user selection is disabled by policy)</span>}</p>
            <ul className="mt-2 space-y-2">
              {cfg.allowed_user_models.map((m, i) => (
                <li key={i} className="grid gap-2 sm:grid-cols-[1fr_200px_auto]">
                  <ModelPicker id={`al-${i}`} label="Allowed" value={m} onChange={(r) => r && edit({ allowed_user_models: cfg.allowed_user_models.map((x, j) => (j === i ? { ...x, ...r } : x)) })} />
                  <Input aria-label="Display label" placeholder="Label" value={m.label} onChange={(e) => edit({ allowed_user_models: cfg.allowed_user_models.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)) })} />
                  <Button variant="ghost" size="icon" aria-label="Remove" onClick={() => edit({ allowed_user_models: cfg.allowed_user_models.filter((_, j) => j !== i) })}><Trash2 /></Button>
                </li>
              ))}
            </ul>
            <Button size="sm" variant="secondary" className="mt-2" onClick={() => edit({ allowed_user_models: [...cfg.allowed_user_models, { provider: "gemini", model: "", label: "" }] })}><Plus />Add model</Button>
          </div>
          <div className="flex items-center justify-end gap-2 border-t border-line pt-4">
            {draft && <Button variant="ghost" onClick={() => setDraft(null)}>Discard changes</Button>}
            <Button loading={busy === "save"} disabled={!draft} onClick={() => void saveConfig()}>Save model configuration</Button>
          </div>
        </Panel>
      </section>

      <section>
        <h2 className="headline mb-3 text-2xl">Connection tests and capabilities</h2>
        <p className="mb-4 max-w-[75ch] text-sm text-text-2">A test sends a tiny real request to the exact model. Capabilities start from conservative provider defaults, are refined by discovered limits, and can be overridden.</p>
        <div className="space-y-3">
          {uniqueRefs.filter((r) => r.model).map((r) => {
            const k = `${r.provider}:${r.model}`;
            const caps = data.capabilities[k];
            const t = tests[k];
            return (
              <Panel key={k} className="p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="font-mono text-[13px]">{r.provider} / {r.model}</p>
                  <div className="flex items-center gap-2">
                    {t && (t.ok ? <span className="flex items-center gap-1 text-sm text-ok"><CheckCircle2 className="size-4" />Connected, {t.latency_ms} ms</span>
                      : <span className="flex items-center gap-1 text-sm text-danger"><XCircle className="size-4" />{t.message}</span>)}
                    <Button size="sm" variant="secondary" loading={busy === `test-${k}`} onClick={() => void test(r)}>Test connection</Button>
                  </div>
                </div>
                {caps && <CapsEditor caps={caps} onSave={(c) => void saveCaps(k, c)} onReset={() => void saveCaps(k, null)} />}
              </Panel>
            );
          })}
          {!uniqueRefs.filter((r) => r.model).length && <p className="text-sm text-muted">Save a model above to test it.</p>}
        </div>
      </section>

      <section>
        <h2 className="headline mb-3 text-2xl">Pricing table</h2>
        <p className="mb-4 max-w-[75ch] text-sm text-text-2">Provider prices change. Enter the current price per million tokens and the date you checked it; costs shown to users are estimates from this table.</p>
        <Panel className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-[13.5px]">
            <thead className="text-[12.5px] text-muted"><tr><th className="px-5 py-2.5 font-medium">Model</th><th className="px-3 py-2.5 text-right font-medium">Input / 1M</th><th className="px-3 py-2.5 text-right font-medium">Output / 1M</th><th className="px-3 py-2.5 font-medium">As of</th><th className="px-3 py-2.5 font-medium">Note</th><th /></tr></thead>
            <tbody className="divide-y divide-line">
              {Object.entries(data.config.pricing).map(([k, p]) => (
                <tr key={k}><td className="px-5 py-2 font-mono text-[12.5px]">{k}</td><td className="px-3 py-2 text-right">${p.input_per_mtok_usd}</td><td className="px-3 py-2 text-right">${p.output_per_mtok_usd}</td><td className="px-3 py-2">{p.as_of}</td><td className="px-3 py-2 text-muted">{p.source_note}</td>
                  <td className="px-3 py-2"><Button size="icon" variant="ghost" aria-label={`Remove price for ${k}`} onClick={() => void savePrice(k)}><Trash2 /></Button></td></tr>
              ))}
              <tr>
                <td className="px-5 py-2"><div className="flex gap-1.5">
                  <Select aria-label="Provider" className="h-9 w-[130px]" value={priceDraft.provider} onChange={(e) => setPriceDraft({ ...priceDraft, provider: e.target.value })}>{PROVIDERS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>
                  <Input aria-label="Model ID" className="h-9" placeholder="model id" value={priceDraft.model} onChange={(e) => setPriceDraft({ ...priceDraft, model: e.target.value })} /></div></td>
                <td className="px-3 py-2"><Input aria-label="Input price" className="h-9 w-24" type="number" min={0} step="0.01" value={priceDraft.input} onChange={(e) => setPriceDraft({ ...priceDraft, input: e.target.value })} /></td>
                <td className="px-3 py-2"><Input aria-label="Output price" className="h-9 w-24" type="number" min={0} step="0.01" value={priceDraft.output} onChange={(e) => setPriceDraft({ ...priceDraft, output: e.target.value })} /></td>
                <td className="px-3 py-2"><Input aria-label="Price checked on" className="h-9" type="date" value={priceDraft.as_of} onChange={(e) => setPriceDraft({ ...priceDraft, as_of: e.target.value })} /></td>
                <td className="px-3 py-2"><Input aria-label="Source note" className="h-9" placeholder="source" value={priceDraft.note} onChange={(e) => setPriceDraft({ ...priceDraft, note: e.target.value })} /></td>
                <td className="px-3 py-2"><Button size="sm" disabled={!priceDraft.model || priceDraft.input === "" || priceDraft.output === ""} onClick={() => void savePrice()}>Add</Button></td>
              </tr>
            </tbody>
          </table>
        </Panel>
      </section>

      <section>
        <h2 className="headline mb-3 text-2xl">Search providers</h2>
        <Panel className="divide-y divide-line">
          {["firecrawl", "tavily", "brave", "openalex"].map((p) => {
            const c = data.search.credentials?.[p];
            const label = SEARCH_LABELS[p] ?? p;
            return (
              <div key={p} className="space-y-3 px-5 py-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span className="flex items-center gap-2 font-medium">{label}{data.search.primary === p && <Badge tone="signal">Primary</Badge>}</span>
                  <span className="flex flex-wrap items-center gap-3">
                    <HealthLine h={data.search.health[p]} />
                    {p === "openalex" ? <Badge tone={data.search.configured[p] ? "ok" : "neutral"}>{data.search.configured[p] ? "Enabled (no key needed)" : "Disabled"}</Badge>
                      : c?.configured ? <Badge tone="ok">{c.source === "environment" ? "From environment" : "Stored"} {c.masked}</Badge>
                        : <Badge tone="neutral">Not configured</Badge>}
                  </span>
                </div>
                {p !== "openalex" && c?.source !== "environment" && (
                  <div className="flex max-w-[640px] gap-2">
                    <Input type="password" autoComplete="off" placeholder={c?.configured ? "Replace key" : "Paste API key"} aria-label={`${label} API key`}
                      value={keys[p] ?? ""} onChange={(e) => setKeys({ ...keys, [p]: e.target.value })} />
                    <Button loading={busy === `key-${p}`} disabled={(keys[p] ?? "").length < 8} onClick={() => void saveKey(p, keys[p] ?? "")}>Save</Button>
                    {c?.configured && <Button variant="ghost" size="icon" aria-label={`Remove ${label} key`} onClick={() => void saveKey(p, null)}><Trash2 /></Button>}
                  </div>
                )}
              </div>
            );
          })}
          <p className="px-5 py-3 text-[12.5px] text-muted">One key is enough. Keys saved here are encrypted and shared with the workers; environment variables (FIRECRAWL_API_KEY, TAVILY_API_KEY, BRAVE_SEARCH_API_KEY) take precedence. If the primary provider has no key, the next configured one is used (fallback is {data.search.fallback_enabled ? "on" : "off"}).</p>
        </Panel>
      </section>
    </div>
  );
}

function CapsEditor({ caps, onSave, onReset }: { caps: Caps; onSave: (c: Partial<Caps>) => void; onReset: () => void }) {
  const [c, setC] = useState<Caps>(caps);
  const bools: [keyof Caps, string][] = [["supports_json_schema", "Native JSON schema"], ["supports_tools", "Tool calling"], ["supports_streaming", "Streaming"], ["supports_temperature", "Temperature"], ["supports_system_prompt", "System prompt"]];
  const dirty = JSON.stringify(c) !== JSON.stringify(caps);
  return (
    <div className="mt-4 grid gap-4 border-t border-line pt-4 md:grid-cols-[1fr_1fr_2fr]">
      <Field label="Context window (tokens)" htmlFor={`cw-${caps.context_window}`}><Input id={`cw-${caps.context_window}`} type="number" value={c.context_window} onChange={(e) => setC({ ...c, context_window: Number(e.target.value) })} /></Field>
      <Field label="Max output tokens" htmlFor={`mo-${caps.max_output_tokens}`}><Input id={`mo-${caps.max_output_tokens}`} type="number" value={c.max_output_tokens} onChange={(e) => setC({ ...c, max_output_tokens: Number(e.target.value) })} /></Field>
      <div className="flex flex-wrap gap-x-5 gap-y-2 pt-6">
        {bools.map(([k, l]) => (
          <label key={k} className="flex items-center gap-2 text-[13px]"><Switch checked={Boolean(c[k])} onCheckedChange={(v) => setC({ ...c, [k]: v })} />{l}</label>
        ))}
      </div>
      <div className="flex items-center justify-between gap-2 md:col-span-3">
        <p className={cn("text-[12.5px]", caps.source === "default" ? "text-warn" : "text-muted")}>
          Source: {caps.source}{caps.source === "default" ? " (assumed — verify or discover)" : ""}. {caps.notes.join(" ")}
        </p>
        <span className="flex gap-2">
          {caps.source === "admin" && <Button size="sm" variant="ghost" onClick={onReset}>Reset</Button>}
          <Button size="sm" variant="secondary" disabled={!dirty} onClick={() => onSave({ context_window: c.context_window, max_output_tokens: c.max_output_tokens, supports_json_schema: c.supports_json_schema, supports_tools: c.supports_tools, supports_streaming: c.supports_streaming, supports_temperature: c.supports_temperature, supports_system_prompt: c.supports_system_prompt })}>Save capabilities</Button>
        </span>
      </div>
    </div>
  );
}
