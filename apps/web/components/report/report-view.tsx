"use client";

import {
  BookmarkPlus,
  ChevronDown,
  Download,
  FileDown,
  GitCompare,
  Info,
  MessageSquarePlus,
  MoreHorizontal,
  Printer,
  RefreshCcw,
  Share2,
  Sparkles,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { useConfig } from "@/components/providers";
import {
  Badge,
  Button,
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
  Dialog,
  DialogContent,
  Input,
  Menu,
  MenuContent,
  MenuItem,
  MenuSeparator,
  MenuTrigger,
  Notice,
  Panel,
  Select,
  Textarea,
  Tooltip,
} from "@/components/ui/primitives";
import { api, downloadFile, errorMessage } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Job, Report, Source } from "@/lib/types";
import { cn, duration, formatDate, formatNumber, formatUsd, hostname } from "@/lib/utils";

import { ChartCard, MatrixView } from "./charts";
import { EvidenceGraph } from "./evidence-graph";
import { ParagraphView } from "./paragraph";
import { type Focus, ReportContext } from "./report-context";
import { SourcePanel, TYPE_LABEL, TYPE_TONE } from "./source-panel";

const STRENGTH_TONE = { strong: "ok", moderate: "signal", limited: "neutral", contested: "warn", unsupported: "danger" } as const;

async function waitForJob(id: string, onTick?: (status: string) => void): Promise<Job> {
  for (let i = 0; i < 240; i++) {
    const { job } = await api<{ job: Job }>(`/api/v1/research/${id}`);
    onTick?.(job.status);
    if (["completed", "failed", "cancelled"].includes(job.status)) return job;
    await new Promise((r) => setTimeout(r, 1500));
  }
  throw new Error("Timed out waiting for the job.");
}

function SectionHeading({ id, children, actions }: { id: string; children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="group mb-4 mt-14 flex items-baseline justify-between gap-4 border-b border-line pb-2 first:mt-0">
      <h2 id={id} className="headline scroll-mt-24 text-[27px]">{children}</h2>
      {actions}
    </div>
  );
}

export function ReportView({ job, report, reload }: { job: Job; report: Report; reload: (version?: number) => void }) {
  const config = useConfig();
  const router = useRouter();
  const sourcesApi = useApi<{ items: Source[] }>(`/api/v1/research/${job.id}/sources`);
  const versions = useApi<{ items: { version: number; created_at: string; change_note?: string; status: string }[] }>(`/api/v1/research/${job.id}/report/versions`, [report.version]);
  const [focus, setFocus] = useState<Focus | null>(null);
  const [regen, setRegen] = useState<{ id: string; title: string } | null>(null);
  const [regenBusy, setRegenBusy] = useState<string | null>(null);
  const [instruction, setInstruction] = useState("");
  const [followOpen, setFollowOpen] = useState(false);
  const [diffOpen, setDiffOpen] = useState(false);
  const [exporting, setExporting] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"number" | "date">("number");

  const sourceItems = sourcesApi.data?.items;
  const sources = useMemo(() => sourceItems ?? [], [sourceItems]);
  const byNumber = useMemo(() => new Map(sources.map((s) => [s.number, s])), [sources]);
  const focusSource = focus ? byNumber.get(focus.sourceNumber) : undefined;
  const ctx = useMemo(() => ({ jobId: job.id, sourcesByNumber: byNumber, open: setFocus }), [job.id, byNumber]);
  const latestVersion = versions.data?.items[0]?.version ?? report.version;

  const toc = [
    ["summary", "Executive summary"],
    report.key_findings.length ? ["findings", "Key findings"] : null,
    ["quality", "Evidence quality"],
    ...report.sections.map((s) => [`sec-${s.id}`, s.title] as [string, string]),
    report.tables.length ? ["comparison", "Comparison"] : null,
    report.charts.length ? ["charts", "Charts"] : null,
    report.conflicts.length ? ["conflicts", "Conflicting evidence"] : null,
    report.unknowns.length ? ["unknowns", "What is still unknown"] : null,
    report.limitations.length ? ["limitations", "Limitations"] : null,
    report.conclusions.length ? ["conclusions", "Conclusions"] : null,
    report.recommendations.length ? ["recommendations", "Recommendations"] : null,
    report.key_findings.length ? ["graph", "Evidence graph"] : null,
    ["methodology", "Methodology"],
    ["bibliography", "Sources"],
  ].filter(Boolean) as [string, string][];

  const [activeToc, setActiveToc] = useState("summary");
  useEffect(() => {
    const obs = new IntersectionObserver((entries) => {
      const vis = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (vis[0]) setActiveToc(vis[0].target.id);
    }, { rootMargin: "-80px 0px -70% 0px" });
    toc.forEach(([id]) => { const el = document.getElementById(id); if (el) obs.observe(el); });
    return () => obs.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report.id]);

  async function exportAs(kind: "md" | "csv" | "pdf" | "docx") {
    setExporting(kind);
    try {
      if (kind === "md") await downloadFile(`/api/v1/research/${job.id}/export.md?version=${report.version}`, "report.md");
      else if (kind === "csv") await downloadFile(`/api/v1/research/${job.id}/charts.csv?version=${report.version}`, "chart-data.csv");
      else {
        const t = toast.loading(`Preparing ${kind.toUpperCase()}…`);
        try {
          const { export_id } = await api<{ export_id: string }>(`/api/v1/research/${job.id}/exports`, { json: { format: kind, version: report.version } });
          const done = await waitForJob(export_id);
          if (done.status !== "completed") throw new Error(done.last_error?.message ?? "Export failed.");
          await downloadFile(`/api/v1/research/exports/${export_id}?download=true`, `report.${kind}`);
          toast.success(`${kind.toUpperCase()} downloaded`, { id: t });
        } catch (e) {
          toast.error(errorMessage(e), { id: t });
        }
      }
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setExporting(null);
    }
  }

  async function regenerate() {
    if (!regen) return;
    const sec = regen;
    setRegen(null);
    setRegenBusy(sec.id);
    const t = toast.loading(`Rewriting “${sec.title}”…`);
    try {
      const r = await api<{ job: Job }>(`/api/v1/research/${job.id}/report/sections/${sec.id}/regenerate`, { json: { instruction } });
      const done = await waitForJob(r.job.id);
      if (done.status !== "completed") throw new Error(done.last_error?.message ?? "Regeneration failed.");
      toast.success("Section rewritten — saved as a new version", { id: t });
      setInstruction("");
      reload();
    } catch (e) {
      toast.error(errorMessage(e), { id: t });
    } finally {
      setRegenBusy(null);
    }
  }

  async function share() {
    try {
      const r = await api<{ url: string }>(`/api/v1/research/${job.id}/share`, { method: "POST" });
      await navigator.clipboard.writeText(r.url);
      toast.success("Share link copied. Anyone with the link can read this version.");
    } catch (e) { toast.error(errorMessage(e)); }
  }

  async function save(kind: "report" | "source", refId: string) {
    try {
      const r = await api<{ deduplicated?: boolean }>("/api/v1/library/items", { json: { kind, ref_id: refId } });
      toast.success(r.deduplicated ? "Already in your library — linked as a duplicate" : "Saved to library");
    } catch (e) { toast.error(errorMessage(e)); }
  }

  const filtered = sources.filter((s) => s.status === "extracted" || report.bibliography.some((b) => b.number === s.number))
    .filter((s) => !typeFilter || (s.source_type ?? "unknown") === typeFilter)
    .filter((s) => !query || `${s.title} ${s.domain} ${s.publisher ?? ""}`.toLowerCase().includes(query.toLowerCase()))
    .sort((a, b) => sort === "number" ? a.number - b.number : (b.published_at ?? "").localeCompare(a.published_at ?? ""));
  const cv = report.citation_validation;
  const sc = report.support_check;
  const m = report.methodology;

  return (
    <ReportContext.Provider value={ctx}>
      {/* Banners */}
      <div className="space-y-2 no-print">
        {report.is_demo && <Notice tone="lamp" title="Demo report">Generated from synthetic sources by the deterministic demo model. Not real research.</Notice>}
        {report.status === "partial" && (
          <Notice tone="warn" title="Partial report — research did not complete">
            {report.partial_reason}. These are verified findings gathered before it stopped; they were not synthesised into conclusions.
          </Notice>
        )}
        {report.version < latestVersion && (
          <Notice tone="signal" action={<Button size="sm" variant="secondary" onClick={() => reload()}>Show latest</Button>}>
            You&apos;re viewing version {report.version}. The latest is version {latestVersion}.
          </Notice>
        )}
      </div>

      {/* Header */}
      <header className="mb-8 mt-4">
        <h1 className="display max-w-[24ch] text-[clamp(34px,4.4vw,54px)]">{report.title}</h1>
        <p className="mt-3 max-w-[80ch] text-text-2">{report.question}</p>
        <div className="mt-4 flex flex-wrap items-center gap-2 text-[13px] text-muted">
          <Badge>{job.mode_label}</Badge>
          <Tooltip content={`Median source age ${report.freshness.median_age_days ?? "unknown"} days; newest ${report.freshness.newest ?? "n/a"}; ${report.freshness.undated} undated.`}>
            <span><Badge tone={report.freshness.label === "fresh" ? "ok" : report.freshness.label === "dated" ? "warn" : "neutral"}>
              Freshness: {report.freshness.label}
            </Badge></span>
          </Tooltip>
          <span>Generated {formatDate(report.created_at, { dateStyle: "medium", timeStyle: "short" })}</span>
          <span>{report.source_stats.extracted} {report.source_stats.extracted === 1 ? "source" : "sources"} from {report.source_stats.domains} {report.source_stats.domains === 1 ? "domain" : "domains"}</span>
        </div>
        <div className="mt-5 flex flex-wrap gap-2 no-print">
          <Menu>
            <MenuTrigger asChild><Button variant="secondary" size="sm" loading={!!exporting}><Download />Export<ChevronDown /></Button></MenuTrigger>
            <MenuContent align="start">
              <MenuItem onSelect={() => void exportAs("md")}><FileDown />Markdown</MenuItem>
              <MenuItem onSelect={() => void exportAs("pdf")}><FileDown />PDF</MenuItem>
              <MenuItem onSelect={() => void exportAs("docx")}><FileDown />Word (DOCX)</MenuItem>
              <MenuItem onSelect={() => void exportAs("csv")}><FileDown />Chart data (CSV)</MenuItem>
              <MenuSeparator />
              <MenuItem onSelect={() => window.print()}><Printer />Print</MenuItem>
            </MenuContent>
          </Menu>
          <Button size="sm" variant="secondary" onClick={() => setFollowOpen(true)}><MessageSquarePlus />Ask a follow-up</Button>
          <Button size="sm" variant="secondary" onClick={() => void save("report", job.id)}><BookmarkPlus />Save to library</Button>
          {(versions.data?.items.length ?? 0) > 1 && (
            <>
              <Select aria-label="Report version" className="h-8 w-auto py-0 text-[13px]" value={report.version}
                onChange={(e) => reload(Number(e.target.value))}>
                {versions.data?.items.map((v) => <option key={v.version} value={v.version}>Version {v.version}{v.change_note ? ` — ${v.change_note.slice(0, 40)}` : ""}</option>)}
              </Select>
              <Button size="sm" variant="ghost" onClick={() => setDiffOpen(true)}><GitCompare />Compare versions</Button>
            </>
          )}
          {config?.features.public_sharing && <Button size="sm" variant="ghost" onClick={() => void share()}><Share2 />Share</Button>}
        </div>
      </header>

      <div className="grid gap-10 xl:grid-cols-[200px_minmax(0,1fr)] 2xl:grid-cols-[200px_minmax(0,1fr)_320px]">
        {/* TOC */}
        <nav aria-label="Report contents" className="hidden xl:block no-print">
          <ol className="sticky top-8 space-y-0.5 border-l border-line text-[13px]">
            {toc.map(([id, label]) => (
              <li key={id}>
                <a href={`#${id}`} className={cn("-ml-px block border-l py-1 pl-3 leading-snug transition-colors",
                  activeToc === id ? "border-signal text-text" : "border-transparent text-muted hover:text-text")}>
                  <span className="line-clamp-2">{label}</span>
                </a>
              </li>
            ))}
          </ol>
        </nav>

        {/* Article */}
        <article className="min-w-0">
          <SectionHeading id="summary">Executive summary</SectionHeading>
          <div className="prose-report">{report.executive_summary.map((p) => <ParagraphView key={p.id} p={p} />)}</div>

          {!!report.key_findings.length && (
            <>
              <SectionHeading id="findings">Key findings</SectionHeading>
              <ol className="space-y-4">
                {report.key_findings.map((f, i) => (
                  <li key={f.id} className="grid grid-cols-[28px_1fr] gap-3">
                    <span className="font-serif text-[22px] leading-none text-lamp">{i + 1}</span>
                    <div>
                      <ParagraphView p={f} className="prose-report" />
                      {f.strength && (
                        <Tooltip content={<span><strong className="text-text">{f.strength.label}</strong>: {f.strength.basis}<br />{f.strength.independent_domains} independent domain(s), {f.strength.primary_sources} primary source(s). This is a rule-based label, not a probability.</span>}>
                          <span tabIndex={0} className="mt-1.5 inline-block"><Badge tone={STRENGTH_TONE[f.strength.label]}>Evidence: {f.strength.label}</Badge></span>
                        </Tooltip>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            </>
          )}

          <SectionHeading id="quality">Evidence quality</SectionHeading>
          <Panel className="grid gap-6 p-5 sm:grid-cols-2 lg:grid-cols-4">
            {[
              ["Citations checked", `${formatNumber(cv.valid)} valid`, cv.invalid ? `${cv.invalid} invalid marker(s) removed` : "No invalid citations"],
              ["Claim support", `${formatNumber(sc.supported)} of ${formatNumber((sc.checked ?? 0))} supported`, `${sc.partially_supported ?? 0} partial, ${sc.not_supported ?? 0} not supported, ${sc.not_checked ?? 0} not checked`],
              ["Uncited sentences", formatNumber(cv.uncited_sentences), "Shown in muted text"],
              ["Sources", `${report.source_stats.extracted} read`, Object.entries(report.source_stats.by_type).map(([k, v]) => `${v} ${k}`).join(", ") || "—"],
            ].map(([k, v, h]) => (
              <div key={k}><p className="text-[12.5px] text-muted">{k}</p><p className="mt-0.5 text-[18px] font-semibold">{v}</p><p className="text-[12.5px] text-muted">{h}</p></div>
            ))}
          </Panel>
          <p className="mt-3 flex items-start gap-2 text-[13px] text-muted"><Info className="mt-0.5 size-4 shrink-0" />
            Dotted underline: partially supported. Wavy underline: not supported by the cited passage. Citations open the exact quote.
          </p>
          {!!report.warnings.length && (
            <ul className="mb-10 mt-4 space-y-1.5 rounded-xl border border-warn/30 bg-warn-soft/50 px-4 py-3 text-[13.5px] text-text-2">
              {report.warnings.map((w) => <li key={w}>{w}</li>)}
            </ul>
          )}

          {report.sections.map((s) => (
            <section key={s.id}>
              <SectionHeading id={`sec-${s.id}`} actions={
                <Menu>
                  <MenuTrigger className="rounded-md p-1.5 text-muted opacity-70 hover:bg-surface-2 hover:text-text group-hover:opacity-100 no-print" aria-label={`Actions for section ${s.title}`}>
                    {regenBusy === s.id ? <RefreshCcw className="size-4 animate-spin" /> : <MoreHorizontal className="size-4" />}
                  </MenuTrigger>
                  <MenuContent>
                    <MenuItem disabled={!!regenBusy} onSelect={() => setRegen({ id: s.id, title: s.title })}><Sparkles />Regenerate this section</MenuItem>
                  </MenuContent>
                </Menu>
              }>{s.title}</SectionHeading>
              <div className="prose-report">{s.paragraphs.map((p) => <ParagraphView key={p.id} p={p} />)}</div>
              {s.regenerated_at && <p className="mt-2 text-[12px] text-muted">Rewritten {formatDate(s.regenerated_at, { dateStyle: "medium", timeStyle: "short" })}</p>}
            </section>
          ))}

          {!!report.tables.length && (
            <>
              <SectionHeading id="comparison">Comparison</SectionHeading>
              <div className="space-y-6">{report.tables.map((t) => <MatrixView key={t.id} table={t} />)}</div>
            </>
          )}

          {!!report.charts.length && (
            <>
              <SectionHeading id="charts">Charts</SectionHeading>
              <div className="grid gap-5 lg:grid-cols-2">{report.charts.map((c) => <ChartCard key={c.id} spec={c} />)}</div>
            </>
          )}

          {!!report.conflicts.length && (
            <>
              <SectionHeading id="conflicts">Conflicting evidence</SectionHeading>
              <div className="space-y-5">
                {report.conflicts.map((c) => (
                  <div key={c.id} className="border-l-2 border-warn pl-4">
                    <p className="font-semibold">{c.topic}</p>
                    <ParagraphView p={c} className="prose-report mt-1" />
                  </div>
                ))}
              </div>
            </>
          )}

          {!!report.unknowns.length && (
            <>
              <SectionHeading id="unknowns">What is still unknown</SectionHeading>
              <ul className="space-y-3">
                {report.unknowns.map((u) => (
                  <li key={u.question} className="prose-report"><strong className="font-semibold">{u.question}</strong> <span className="text-text-2">{u.why}</span></li>
                ))}
              </ul>
            </>
          )}

          {!!report.limitations.length && (
            <>
              <SectionHeading id="limitations">Limitations</SectionHeading>
              <ul className="prose-report list-disc space-y-1.5 pl-5 marker:text-line-strong">{report.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
            </>
          )}

          {!!report.conclusions.length && (
            <>
              <SectionHeading id="conclusions">Conclusions</SectionHeading>
              <div className="prose-report">{report.conclusions.map((p) => <ParagraphView key={p.id} p={p} />)}</div>
            </>
          )}

          {!!report.recommendations.length && (
            <>
              <SectionHeading id="recommendations">Recommendations</SectionHeading>
              <ul className="prose-report list-disc space-y-2 pl-5 marker:text-line-strong">
                {report.recommendations.map((p) => <li key={p.id}><ParagraphView p={p} as="span" /></li>)}
              </ul>
            </>
          )}

          {!!report.key_findings.length && (
            <section className="no-print">
              <SectionHeading id="graph">Evidence graph</SectionHeading>
              <EvidenceGraph jobId={job.id} />
            </section>
          )}

          <SectionHeading id="methodology">Methodology</SectionHeading>
          <div className="space-y-5 text-[14.5px]">
            <p className="text-text-2">{m.objective}</p>
            <ol className="space-y-2">
              {m.subquestions.map((s) => (
                <li key={s.id} className="grid grid-cols-[36px_1fr_auto] gap-2">
                  <span className="text-muted">{s.id}</span><span>{s.question}{s.missing ? <span className="block text-[12.5px] text-muted">{s.missing}</span> : null}</span>
                  <Badge tone={s.status === "covered" ? "ok" : s.status === "insufficient" ? "warn" : "neutral"}>{s.status}</Badge>
                </li>
              ))}
            </ol>
            <dl className="grid gap-x-6 gap-y-2 rounded-xl border border-line bg-surface p-4 text-[13.5px] sm:grid-cols-[180px_1fr]">
              <dt className="text-muted">Executed</dt><dd>{formatDate(m.executed_at, { dateStyle: "medium", timeStyle: "short" })}{m.duration_seconds ? ` in ${duration(m.duration_seconds)}` : ""}</dd>
              <dt className="text-muted">Search providers</dt><dd>{m.search_providers.join(", ") || "None (documents only)"}</dd>
              <dt className="text-muted">Models</dt>
              <dd>{Object.entries(m.model_config ?? {}).filter(([, v]) => v).map(([k, v]) => `${k}: ${v!.provider}/${v!.model}`).join("; ")}</dd>
              {!!m.fallbacks.length && <><dt className="text-muted">Fallbacks</dt><dd>{m.fallbacks.map((f) => `${f.task}: ${f.from} → ${f.to} (${f.reason})`).join("; ")}</dd></>}
              <dt className="text-muted">Rounds</dt><dd>{m.iterations} search round(s), {m.queries.length} queries, {m.rejected_candidates} candidates set aside</dd>
              <dt className="text-muted">Usage</dt><dd>{formatNumber(m.usage.llm_calls)} model calls, {formatNumber(m.usage.output_tokens)} output tokens, est. {formatUsd(m.usage.cost_usd_est)}{m.usage.cost_unknown_calls ? ` (+${m.usage.cost_unknown_calls} calls without a price)` : ""}</dd>
              {m.plan_edited_by_user && <><dt className="text-muted">Plan</dt><dd>Edited and approved by you</dd></>}
              {!!m.assumptions.length && <><dt className="text-muted">Assumptions</dt><dd>{m.assumptions.join("; ")}</dd></>}
              {m.stop_reason && <><dt className="text-muted">Stopped early</dt><dd>{m.stop_reason}</dd></>}
            </dl>
            <Collapsible>
              <CollapsibleTrigger className="group flex items-center gap-2 text-sm text-muted hover:text-text">
                <ChevronDown className="size-4 transition-transform group-data-[state=open]:rotate-180" />Search history ({m.queries.length})
              </CollapsibleTrigger>
              <CollapsibleContent>
                <ul className="mt-3 divide-y divide-line rounded-xl border border-line text-[13px]">
                  {m.queries.map((q, i) => (
                    <li key={i} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                      <code className="font-mono text-[12px]">{q.query}</code>
                      <span className="text-muted">{q.subq_id}, round {q.iteration + 1}, {q.kind}, {q.error ? <span className="text-warn">{q.error}</span> : `${q.results} results via ${q.provider}${q.from_cache ? " (cached)" : ""}`}</span>
                    </li>
                  ))}
                </ul>
              </CollapsibleContent>
            </Collapsible>
          </div>

          <SectionHeading id="bibliography">Sources</SectionHeading>
          <ol className="space-y-3">
            {report.bibliography.map((b) => (
              <li key={b.number} className="grid grid-cols-[34px_1fr] gap-2 text-[14px]">
                <button onClick={() => setFocus({ sourceNumber: b.number, evidenceIds: [] })} className="self-start rounded-[5px] bg-lamp-soft px-1 text-center text-[12px] font-semibold text-lamp-ink hover:bg-lamp" aria-label={`Open source ${b.number}`}>{b.number}</button>
                <div className={cn(!b.cited && "opacity-70")}>
                  <p className="font-medium leading-snug">{b.title}</p>
                  <p className="text-[12.5px] text-muted">
                    {[b.publisher || b.domain, b.author, b.published_at ? formatDate(b.published_at) : "no date", b.source_type ? TYPE_LABEL[b.source_type] : null,
                      b.content_kind === "abstract" ? "abstract only" : null, !b.cited ? "read but not cited" : null].filter(Boolean).join(", ")}
                  </p>
                  <p className="truncate text-[12.5px] text-muted">{b.url.startsWith("upload://") ? "Your uploaded document" : b.url}</p>
                </div>
              </li>
            ))}
          </ol>
        </article>

        {/* Source sidebar */}
        <aside className="hidden 2xl:block no-print" aria-label="Sources">
          <div className="sticky top-8 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold">Sources</h2>
              <span className="text-[12px] text-muted">{filtered.length}</span>
            </div>
            <Input placeholder="Filter by title or publisher" value={query} onChange={(e) => setQuery(e.target.value)} className="h-9" aria-label="Filter sources" />
            <div className="flex gap-2">
              <Select aria-label="Source type" className="h-9 text-[13px]" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
                <option value="">All types</option><option value="primary">Primary</option><option value="secondary">Secondary</option>
                <option value="commentary">Commentary</option><option value="unknown">Unclear</option>
              </Select>
              <Select aria-label="Sort" className="h-9 text-[13px]" value={sort} onChange={(e) => setSort(e.target.value as "number" | "date")}>
                <option value="number">By number</option><option value="date">Newest first</option>
              </Select>
            </div>
            <ul className="max-h-[calc(100vh-220px)] space-y-1.5 overflow-y-auto pr-1">
              {filtered.map((s) => (
                <li key={s.id} className="group rounded-lg border border-line bg-surface p-2.5 text-[13px] hover:border-line-strong">
                  <button className="w-full text-left" onClick={() => setFocus({ sourceNumber: s.number, evidenceIds: [] })}>
                    <span className="flex items-start gap-2">
                      <span className="rounded bg-lamp-soft px-1.5 text-[11px] font-semibold text-lamp-ink">{s.number}</span>
                      <span className="line-clamp-2 leading-snug">{s.title || hostname(s.url)}</span>
                    </span>
                    <span className="mt-1 flex flex-wrap items-center gap-1.5 pl-7 text-[11.5px] text-muted">
                      {s.source_type && <Badge tone={TYPE_TONE[s.source_type]} className="text-[10.5px]">{s.source_type}</Badge>}
                      <span>{s.publisher || s.domain}</span>
                      {s.published_at && <span>{s.published_at.slice(0, 10)}</span>}
                      {s.relevance !== undefined && s.relevance !== null && <span>relevance {s.relevance}/3</span>}
                    </span>
                  </button>
                  {!s.url.startsWith("upload://") && (
                    <button className="mt-1 pl-7 text-[11.5px] text-muted opacity-0 hover:text-text group-hover:opacity-100 focus:opacity-100" onClick={() => void save("source", s.id)}>Save source</button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </aside>
      </div>

      <SourcePanel jobId={job.id} sourceId={focusSource?.id ?? null} focus={focus} onClose={() => setFocus(null)} />

      <Dialog open={!!regen} onOpenChange={(o) => !o && setRegen(null)}>
        <DialogContent title="Regenerate section" description={regen?.title}>
          <p className="text-sm text-text-2">The section is rewritten from the same verified evidence, excluding any citations you flagged as wrong. The result is saved as a new version; the current one stays available.</p>
          <label htmlFor="instr" className="mt-4 block text-[13px] font-medium text-text-2">Instructions (optional)</label>
          <Textarea id="instr" rows={3} className="mt-1.5" value={instruction} onChange={(e) => setInstruction(e.target.value)} placeholder="e.g. Focus on costs, be more concise" />
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setRegen(null)}>Cancel</Button>
            <Button onClick={() => void regenerate()}>Regenerate section</Button>
          </div>
        </DialogContent>
      </Dialog>

      <FollowUpDialog jobId={job.id} open={followOpen} onOpenChange={setFollowOpen} />
      {diffOpen && <DiffDialog jobId={job.id} versions={versions.data?.items.map((v) => v.version) ?? []} onClose={() => setDiffOpen(false)} />}
    </ReportContext.Provider>
  );
}

function FollowUpDialog({ jobId, open, onOpenChange }: { jobId: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [mode, setMode] = useState("quick");
  const [busy, setBusy] = useState(false);
  async function go() {
    setBusy(true);
    try {
      const question = mode === "counterarguments" && q.trim().length < 12 ? "" : q.trim();
      const r = await api<{ job: Job }>(`/api/v1/research/${jobId}/followup`, { json: { question: question || "Find the strongest counterarguments to this report", mode } });
      router.push(`/research/${r.job.id}`);
    } catch (e) {
      toast.error(errorMessage(e));
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Ask a follow-up" description="Starts a new run that reuses this report's sources and searches for anything new.">
        <div className="space-y-4">
          <fieldset className="grid gap-2 sm:grid-cols-3">
            <legend className="sr-only">Follow-up type</legend>
            {([["quick", "Follow-up question"], ["counterarguments", "Find counterarguments"], ["verify_claim", "Verify a claim"]] as [string, string][]).map(([k, l]) => (
              <label key={k} className={cn("cursor-pointer rounded-lg border px-3 py-2 text-[13px]", mode === k ? "border-signal bg-signal-soft" : "border-line")}>
                <input type="radio" name="fmode" className="sr-only" checked={mode === k} onChange={() => setMode(k)} />{l}
              </label>
            ))}
          </fieldset>
          <Textarea rows={3} value={q} onChange={(e) => setQ(e.target.value)} aria-label="Follow-up question"
            placeholder={mode === "verify_claim" ? "Paste the claim to check" : mode === "counterarguments" ? "Optional: which position to challenge" : "What do you want to know next?"} />
          <div className="flex justify-end">
            <Button onClick={() => void go()} loading={busy} disabled={mode !== "counterarguments" && q.trim().length < 8}>Start follow-up</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function DiffDialog({ jobId, versions, onClose }: { jobId: string; versions: number[]; onClose: () => void }) {
  const sorted = [...versions].sort((a, b) => a - b);
  const [a, setA] = useState(sorted[sorted.length - 2] ?? 1);
  const [b, setB] = useState(sorted[sorted.length - 1] ?? 1);
  const { data, loading } = useApi<{ changes: { section_id: string; title_a: string; title_b: string; diff: string[] }[] }>(
    a !== b ? `/api/v1/research/${jobId}/report/diff?a=${a}&b=${b}` : null, [a, b]);
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="Compare versions" className="w-[min(860px,calc(100vw-24px))]">
        <div className="flex items-center gap-2 text-sm">
          <Select aria-label="From version" className="w-auto" value={a} onChange={(e) => setA(Number(e.target.value))}>{sorted.map((v) => <option key={v} value={v}>Version {v}</option>)}</Select>
          <span className="text-muted">to</span>
          <Select aria-label="To version" className="w-auto" value={b} onChange={(e) => setB(Number(e.target.value))}>{sorted.map((v) => <option key={v} value={v}>Version {v}</option>)}</Select>
        </div>
        <div className="mt-4 space-y-4">
          {loading && <p className="text-sm text-muted">Comparing…</p>}
          {data && !data.changes.length && <p className="text-sm text-muted">No section text changed between these versions.</p>}
          {data?.changes.map((c) => (
            <div key={c.section_id} className="rounded-xl border border-line">
              <p className="border-b border-line px-4 py-2 text-sm font-semibold">{c.title_b || c.title_a}</p>
              <pre className="max-h-[300px] overflow-auto whitespace-pre-wrap px-4 py-3 font-mono text-[12px] leading-relaxed">
                {c.diff.map((line, i) => (
                  <span key={i} className={cn("block", line.startsWith("+") && "bg-ok-soft text-ok", line.startsWith("-") && "bg-danger-soft text-danger", line.startsWith("@@") && "text-muted")}>{line}</span>
                ))}
              </pre>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
