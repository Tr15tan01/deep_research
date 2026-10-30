"use client";

import { ChevronDown, Clock, Settings2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "@/components/app/shell";
import { useConfig, useSession } from "@/components/providers";
import { Uploader } from "@/components/research/uploader";
import {
  Button,
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
  Field,
  Input,
  Notice,
  Select,
  Switch,
  Textarea,
} from "@/components/ui/primitives";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Job, Template, Upload } from "@/lib/types";
import { cn } from "@/lib/utils";

const SOURCE_PREFS = [
  ["official", "Official and government"], ["academic", "Academic"], ["statistics", "Statistics"],
  ["documentation", "Documentation"], ["industry", "Industry"], ["news", "News"],
] as const;

function splitDomains(v: string): string[] {
  return v.split(/[\s,]+/).map((d) => d.trim()).filter(Boolean);
}

export function NewResearchForm() {
  const sp = useSearchParams();
  const router = useRouter();
  const config = useConfig();
  const { user } = useSession();
  const templates = useApi<{ system: Template[]; mine: Template[] }>("/api/v1/templates");
  const uploadsApi = useApi<{ items: Upload[] }>(config?.features.uploads ? "/api/v1/uploads" : null);
  const models = useApi<{ selection_enabled: boolean; byok_enabled: boolean; default: { provider: string; model: string } | null; allowed: { provider: string; model: string; label: string }[]; own_keys: { provider: string }[] }>("/api/v1/models");

  const [question, setQuestion] = useState(sp.get("q") ?? "");
  const [mode, setMode] = useState("standard");
  const [include, setInclude] = useState("");
  const [exclude, setExclude] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [language, setLanguage] = useState("");
  const [prefs, setPrefs] = useState<string[]>([]);
  const [reviewPlan, setReviewPlan] = useState(false);
  const [uploadIds, setUploadIds] = useState<string[]>([]);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [maxSources, setMaxSources] = useState("");
  const [maxMinutes, setMaxMinutes] = useState("");
  const [model, setModel] = useState("");
  const [useOwnKey, setUseOwnKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [idemKey] = useState(() => crypto.randomUUID());

  useEffect(() => { if (uploadsApi.data) setUploads(uploadsApi.data.items); }, [uploadsApi.data]);

  // Apply a template from ?template=
  useEffect(() => {
    const tid = sp.get("template");
    if (!tid || !templates.data) return;
    const t = [...templates.data.system, ...templates.data.mine].find((x) => x.id === tid);
    if (!t) return;
    setQuestion((q) => q || t.question_template);
    setMode(t.mode);
    const o = t.options ?? {};
    if (Array.isArray(o.include_domains)) setInclude((o.include_domains as string[]).join(", "));
    if (Array.isArray(o.exclude_domains)) setExclude((o.exclude_domains as string[]).join(", "));
    if (typeof o.review_plan === "boolean") setReviewPlan(o.review_plan);
  }, [sp, templates.data]);

  const modes = config?.modes ?? [];
  const current = modes.find((m) => m.key === mode);
  const placeholders = /\{[^}]+\}/.test(question);
  const tooShort = question.trim().length < 8;
  const needsDocs = mode === "documents" && uploadIds.length === 0;

  const estimate = useMemo(() => {
    if (!current) return null;
    const [lo, hi] = current.estimated_minutes;
    return `Usually ${lo}–${hi} minutes, up to ${current.limits.max_search_calls} searches and ${current.limits.max_sources} sources.`;
  }, [current]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (tooShort || placeholders || needsDocs) return;
    setBusy(true);
    setError(null);
    const options: Record<string, unknown> = { review_plan: reviewPlan };
    if (include.trim()) options.include_domains = splitDomains(include);
    if (exclude.trim()) options.exclude_domains = splitDomains(exclude);
    if (dateFrom) options.date_from = dateFrom;
    if (dateTo) options.date_to = dateTo;
    if (language) options.language = language;
    if (prefs.length) options.source_preferences = prefs;
    if (uploadIds.length) options.upload_ids = uploadIds;
    const bo: Record<string, number> = {};
    if (Number(maxSources) > 0) bo.max_sources = Number(maxSources);
    if (Number(maxMinutes) > 0) bo.max_duration_seconds = Math.round(Number(maxMinutes) * 60);
    if (Object.keys(bo).length) options.budget_overrides = bo;
    if (model) { const [provider, ...rest] = model.split(":"); options.model = { provider, model: rest.join(":") }; }
    if (useOwnKey) options.use_own_key = true;
    try {
      const r = await api<{ job: Job }>("/api/v1/research", {
        json: { question: question.trim(), mode, options, template_id: sp.get("template") ?? undefined },
        headers: { "Idempotency-Key": idemKey },
      });
      router.push(`/research/${r.job.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, null, errorMessage(err)));
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="New research" description="Describe what you need to know. Be specific about scope, time period and what a good answer looks like." />
      <form onSubmit={submit} className="grid gap-8 xl:grid-cols-[1fr_320px]">
        <div className="space-y-8">
          {error && (
            <Notice tone="danger" title="Research couldn't start"
              action={error.code === "ai_not_configured" || error.code === "search_not_configured" || error.code === "ai_key_missing"
                ? (user?.role === "ADMIN" ? <Button asChild size="sm" variant="secondary"><Link href="/admin/providers">Configure providers</Link></Button> : undefined)
                : error.code === "email_not_verified" ? <Button asChild size="sm" variant="secondary"><Link href="/settings">Account settings</Link></Button> : undefined}>
              {error.message}{error.referenceId ? <span className="block text-[12px] text-muted">Reference: {error.referenceId}</span> : null}
            </Notice>
          )}
          <div>
            <label htmlFor="question" className="sr-only">Research question</label>
            <Textarea id="question" value={question} onChange={(e) => setQuestion(e.target.value)} rows={6} maxLength={4000}
              placeholder="For example: How do the three largest managed Kubernetes services compare on pricing, autoscaling limits and SLA terms?"
              className="min-h-[170px] rounded-2xl px-5 py-4 font-serif text-[20px] leading-relaxed" autoFocus />
            <div className="mt-2 flex justify-between text-[12.5px] text-muted">
              <span>{placeholders ? <span className="text-warn">Replace the {"{placeholders}"} with your specifics.</span> : "Press Start when you're ready — you can leave this page while it runs."}</span>
              <span className="tabular-nums">{question.length}/4000</span>
            </div>
          </div>

          <fieldset>
            <legend className="mb-3 text-sm font-semibold text-text-2">Research mode</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {modes.filter((m) => !["counterarguments"].includes(m.key)).map((m) => (
                <label key={m.key} className={cn("flex cursor-pointer gap-3 rounded-xl border px-4 py-3 transition-colors",
                  mode === m.key ? "border-signal bg-signal-soft" : "border-line bg-surface hover:border-line-strong")}>
                  <input type="radio" name="mode" value={m.key} checked={mode === m.key} onChange={() => setMode(m.key)} className="mt-1 accent-[var(--signal)]" />
                  <span>
                    <span className="block text-[14.5px] font-medium">{m.label}</span>
                    <span className="block text-[12.5px] leading-snug text-muted">{m.description}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          {config?.features.uploads && (
            <section>
              <h2 className="mb-3 text-sm font-semibold text-text-2">Your documents {mode === "documents" ? "" : <span className="font-normal text-muted">(optional)</span>}</h2>
              <Uploader selected={uploadIds} onChange={setUploadIds} existing={uploads}
                onUploaded={(u) => setUploads((prev) => [u, ...prev.filter((p) => p.id !== u.id)].filter((p) => p.status !== "failed"))} />
            </section>
          )}

          <Collapsible>
            <CollapsibleTrigger className="group flex items-center gap-2 text-sm font-medium text-text-2 hover:text-text">
              <Settings2 className="size-4" />Advanced options<ChevronDown className="size-4 transition-transform group-data-[state=open]:rotate-180" />
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-5 grid gap-5 sm:grid-cols-2">
              <Field label="Only these domains" htmlFor="inc" hint="Comma-separated, e.g. who.int, nih.gov"><Input id="inc" value={include} onChange={(e) => setInclude(e.target.value)} /></Field>
              <Field label="Exclude domains" htmlFor="exc" hint="Comma-separated"><Input id="exc" value={exclude} onChange={(e) => setExclude(e.target.value)} /></Field>
              <Field label="Published after" htmlFor="df"><Input id="df" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} /></Field>
              <Field label="Published before" htmlFor="dt"><Input id="dt" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} /></Field>
              <Field label="Language of sources" htmlFor="lang">
                <Select id="lang" value={language} onChange={(e) => setLanguage(e.target.value)}>
                  <option value="">Any</option><option value="en">English</option><option value="de">German</option><option value="fr">French</option>
                  <option value="es">Spanish</option><option value="it">Italian</option><option value="pt">Portuguese</option><option value="ja">Japanese</option>
                </Select>
              </Field>
              <fieldset className="space-y-1.5">
                <legend className="text-[13px] font-medium text-text-2">Prefer sources</legend>
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {SOURCE_PREFS.map(([k, l]) => (
                    <button key={k} type="button" aria-pressed={prefs.includes(k)} onClick={() => setPrefs((p) => p.includes(k) ? p.filter((x) => x !== k) : [...p, k])}
                      className={cn("rounded-full border px-2.5 py-1 text-[12.5px]", prefs.includes(k) ? "border-signal bg-signal-soft text-text" : "border-line text-text-2")}>{l}</button>
                  ))}
                </div>
              </fieldset>
              <Field label="Maximum sources" htmlFor="ms" hint={current ? `Mode limit: ${current.limits.max_sources}` : undefined}>
                <Input id="ms" type="number" min={1} max={current?.limits.max_sources} value={maxSources} onChange={(e) => setMaxSources(e.target.value)} />
              </Field>
              <Field label="Maximum minutes" htmlFor="mm" hint={current ? `Mode limit: ${Math.round((current.limits.max_duration_seconds ?? 0) / 60)}` : undefined}>
                <Input id="mm" type="number" min={1} value={maxMinutes} onChange={(e) => setMaxMinutes(e.target.value)} />
              </Field>
              {models.data?.selection_enabled && !!models.data.allowed.length && (
                <Field label="Model" htmlFor="model" hint="Used for planning and writing. Approved by your administrator.">
                  <Select id="model" value={model} onChange={(e) => setModel(e.target.value)}>
                    <option value="">Default{models.data.default ? ` (${models.data.default.model})` : ""}</option>
                    {models.data.allowed.map((m) => <option key={`${m.provider}:${m.model}`} value={`${m.provider}:${m.model}`}>{m.label || m.model}</option>)}
                  </Select>
                </Field>
              )}
              {models.data?.byok_enabled && !!models.data.own_keys.length && (
                <div className="flex items-center justify-between gap-3 rounded-xl border border-line px-4 py-3 sm:col-span-2">
                  <span className="text-sm">Use my own API key for this run</span>
                  <Switch checked={useOwnKey} onCheckedChange={setUseOwnKey} aria-label="Use my own API key" />
                </div>
              )}
            </CollapsibleContent>
          </Collapsible>
        </div>

        <aside className="space-y-4 xl:sticky xl:top-8 xl:self-start">
          <div className="rounded-2xl border border-line bg-surface p-5">
            <p className="flex items-center gap-2 text-sm font-semibold"><Clock className="size-4 text-muted" />{current?.label ?? "Research"}</p>
            {estimate && <p className="mt-2 text-[13.5px] text-text-2">{estimate}</p>}
            <p className="mt-2 text-[12.5px] text-muted">Estimates vary with source availability. Budgets are hard limits enforced on the server.</p>
            <div className="mt-4 flex items-center justify-between gap-3 border-t border-line pt-4">
              <label htmlFor="review" className="text-sm">Review the plan before searching</label>
              <Switch id="review" checked={reviewPlan} onCheckedChange={setReviewPlan} />
            </div>
            <Button type="submit" variant="signal" size="lg" className="mt-5 w-full" loading={busy} disabled={tooShort || placeholders || needsDocs}>
              Start research
            </Button>
            {needsDocs && <p className="mt-2 text-[12.5px] text-warn">Attach at least one document for this mode.</p>}
          </div>
          {config?.features.demo_mode && (
            <Notice tone="lamp">Demo mode is on: sources and the model are synthetic.</Notice>
          )}
        </aside>
      </form>
    </>
  );
}
