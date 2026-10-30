"use client";

import { ArrowLeft, ExternalLink, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { use, useMemo, useState } from "react";

import { PageHeader } from "@/components/app/shell";
import { ReportContext } from "@/components/report/report-context";
import { SourcePanel, TYPE_LABEL, TYPE_TONE } from "@/components/report/source-panel";
import { Badge, Input, Panel, Select, Skeleton, Switch, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { useApi } from "@/lib/hooks";
import type { Evidence, Job, Source } from "@/lib/types";
import { formatDate, formatNumber, safeHref } from "@/lib/utils";

export default function SourcesPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const job = useApi<{ job: Job }>(`/api/v1/research/${id}`);
  const sources = useApi<{ items: Source[] }>(`/api/v1/research/${id}/sources`);
  const [discarded, setDiscarded] = useState(false);
  const evidence = useApi<{ items: Evidence[] }>(`/api/v1/research/${id}/evidence?include_discarded=${discarded}`, [discarded]);
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Source | null>(null);

  const byNumber = useMemo(() => new Map((sources.data?.items ?? []).map((s) => [s.number, s])), [sources.data]);
  const list = (sources.data?.items ?? [])
    .filter((s) => !status || s.status === status)
    .filter((s) => !type || (s.source_type ?? "unknown") === type)
    .filter((s) => !q || `${s.title} ${s.domain} ${s.url}`.toLowerCase().includes(q.toLowerCase()));

  return (
    <ReportContext.Provider value={{ jobId: id, sourcesByNumber: byNumber, open: (f) => setOpen(byNumber.get(f.sourceNumber) ?? null) }}>
      <Link href={`/research/${id}`} className="mb-5 flex items-center gap-1.5 text-sm text-muted hover:text-text"><ArrowLeft className="size-4" />Back to report</Link>
      <PageHeader title="Sources and evidence" description={job.data?.job.question} />
      <Tabs defaultValue="sources">
        <TabsList className="mb-5"><TabsTrigger value="sources">Sources ({sources.data?.items.length ?? 0})</TabsTrigger><TabsTrigger value="evidence">Evidence</TabsTrigger></TabsList>
        <TabsContent value="sources">
          <div className="mb-4 flex flex-wrap gap-2">
            <Input className="h-9 max-w-[280px]" placeholder="Search sources" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search sources" />
            <Select className="h-9 w-auto" aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All statuses</option><option value="extracted">Read</option><option value="inaccessible">Inaccessible</option><option value="candidate">Not read</option>
            </Select>
            <Select className="h-9 w-auto" aria-label="Type" value={type} onChange={(e) => setType(e.target.value)}>
              <option value="">All types</option><option value="primary">Primary</option><option value="secondary">Secondary</option><option value="commentary">Commentary</option><option value="unknown">Unclear</option>
            </Select>
          </div>
          {sources.loading && !sources.data ? <Skeleton className="h-64 w-full" /> : (
            <Panel className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-left text-[13.5px]">
                <thead className="border-b border-line text-[12.5px] text-muted">
                  <tr><th className="px-4 py-2.5 font-medium">#</th><th className="px-4 py-2.5 font-medium">Source</th><th className="px-4 py-2.5 font-medium">Type</th>
                    <th className="px-4 py-2.5 font-medium">Published</th><th className="px-4 py-2.5 font-medium">Status</th><th className="px-4 py-2.5 text-right font-medium">Verified</th><th /></tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {list.map((s) => {
                    const href = safeHref(s.url);
                    return (
                      <tr key={s.id} className="hover:bg-surface-2">
                        <td className="px-4 py-2.5 align-top"><span className="rounded bg-lamp-soft px-1.5 text-[11.5px] font-semibold text-lamp-ink">{s.number}</span></td>
                        <td className="max-w-[420px] px-4 py-2.5 align-top">
                          <button className="text-left font-medium hover:underline" onClick={() => setOpen(s)}>{s.title || s.url}</button>
                          <p className="truncate text-[12px] text-muted">{s.url.startsWith("upload://") ? "Your document" : s.domain}{s.content_kind === "abstract" ? ", abstract only" : ""}</p>
                          {!!s.injection_flags?.length && <p className="flex items-center gap-1 text-[12px] text-warn"><ShieldAlert className="size-3" />Instruction-like text</p>}
                        </td>
                        <td className="px-4 py-2.5 align-top">{s.source_type ? <Badge tone={TYPE_TONE[s.source_type]}>{TYPE_LABEL[s.source_type]}</Badge> : <span className="text-muted">—</span>}</td>
                        <td className="px-4 py-2.5 align-top text-text-2">{s.published_at ? formatDate(s.published_at) : <span className="text-muted">Unknown</span>}</td>
                        <td className="px-4 py-2.5 align-top">
                          {s.status === "extracted" ? <Badge tone="ok">Read</Badge> : s.status === "inaccessible" ? <span title={s.inaccessible_reason ?? ""}><Badge tone="warn">Inaccessible</Badge></span> : <Badge>Not read</Badge>}
                          {s.inaccessible_reason && <p className="mt-1 max-w-[220px] text-[11.5px] text-muted">{s.inaccessible_reason}</p>}
                        </td>
                        <td className="px-4 py-2.5 text-right align-top tabular-nums">{formatNumber(s.verified_evidence)}</td>
                        <td className="px-4 py-2.5 align-top">{href && <a href={href} target="_blank" rel="noopener noreferrer nofollow" aria-label={`Open source ${s.number}`} className="text-muted hover:text-text"><ExternalLink className="size-4" /></a>}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Panel>
          )}
        </TabsContent>
        <TabsContent value="evidence">
          <div className="mb-4 flex items-center gap-3">
            <Switch id="disc" checked={discarded} onCheckedChange={setDiscarded} />
            <label htmlFor="disc" className="text-sm">Include discarded claims (quote not found in the source)</label>
          </div>
          <ul className="space-y-3">
            {(evidence.data?.items ?? []).map((e) => (
              <li key={e.id} className="rounded-xl border border-line bg-surface p-4">
                <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted">
                  <span className="font-semibold text-text">{e.id}</span><span>{e.subquestion_id}</span>
                  <button className="rounded bg-lamp-soft px-1.5 font-semibold text-lamp-ink" onClick={() => setOpen(byNumber.get(e.source_number) ?? null)}>Source {e.source_number}</button>
                  {e.kind === "datapoint" && <Badge tone="signal">Data point</Badge>}
                  {e.stance === "contradicts" && <Badge tone="warn">Contradicts</Badge>}
                  {e.verified ? <Badge tone="ok">Verified ({e.match_method})</Badge> : <Badge tone="danger">Discarded: {e.match_method === "number_not_in_quote" ? "number not in quote" : "quote not found"}</Badge>}
                </div>
                <p className="mt-2">{e.claim}</p>
                <p className="mt-1.5 font-serif text-[15px] text-text-2">“{e.quote}”</p>
              </li>
            ))}
          </ul>
        </TabsContent>
      </Tabs>
      <SourcePanel jobId={id} sourceId={open?.id ?? null} focus={open ? { sourceNumber: open.number, evidenceIds: [] } : null} onClose={() => setOpen(null)} />
    </ReportContext.Provider>
  );
}
