"use client";

import { Check, Copy, ExternalLink, Flag, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Dialog, DialogContent, Skeleton } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { SourceDetail } from "@/lib/types";
import { formatDate, safeHref } from "@/lib/utils";

import type { Focus } from "./report-context";

export const TYPE_TONE = { primary: "ok", secondary: "neutral", commentary: "warn", unknown: "neutral" } as const;
export const TYPE_LABEL: Record<string, string> = { primary: "Primary source", secondary: "Secondary source", commentary: "Commentary", unknown: "Type unclear" };

export function citationText(d: SourceDetail["source"]): string {
  const parts = [d.author, d.title, d.publisher || d.domain, d.published_at ? d.published_at.slice(0, 10) : "n.d.", d.url,
    d.retrieved_at ? `retrieved ${formatDate(d.retrieved_at)}` : null].filter(Boolean);
  return parts.join(". ") + ".";
}

export function SourcePanel({ jobId, sourceId, focus, onClose }: { jobId: string; sourceId: string | null; focus: Focus | null; onClose: () => void }) {
  const { data, loading, error } = useApi<SourceDetail>(sourceId ? `/api/v1/research/${jobId}/sources/${sourceId}` : null, [sourceId]);
  const [copied, setCopied] = useState(false);
  const [flagged, setFlagged] = useState<string[]>([]);
  const focusIds = new Set(focus?.evidenceIds ?? []);
  const passages = (data?.passages ?? []).filter((p) => p.verified)
    .sort((a, b) => Number(focusIds.has(b.evidence_id)) - Number(focusIds.has(a.evidence_id)));
  const s = data?.source;
  const href = safeHref(s?.final_url || s?.url);

  async function flag(eid: string) {
    try {
      await api(`/api/v1/research/${jobId}/feedback`, { json: { kind: "citation_incorrect", evidence_id: eid, note: focus?.context?.slice(0, 500) ?? "" } });
      setFlagged((f) => [...f, eid]);
      toast.success("Flagged. Regenerate the section to rewrite it without this evidence.");
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  return (
    <Dialog open={!!sourceId} onOpenChange={(o) => !o && onClose()}>
      <DialogContent side="right" title={focus ? `Source ${focus.sourceNumber}` : "Source"} description={s?.title}>
        {loading && !data ? <div className="space-y-3"><Skeleton className="h-6 w-2/3" /><Skeleton className="h-24 w-full" /><Skeleton className="h-24 w-full" /></div>
          : error ? <p className="text-danger">{errorMessage(error)}</p>
          : s && (
            <div className="space-y-6">
              <div className="flex flex-wrap gap-1.5">
                {s.source_type && <Badge tone={TYPE_TONE[s.source_type]}>{TYPE_LABEL[s.source_type]}</Badge>}
                {s.content_kind === "abstract" && <Badge tone="warn">Abstract only</Badge>}
                {s.is_demo && <Badge tone="lamp">Synthetic demo source</Badge>}
                {!!s.injection_flags?.length && <Badge tone="warn"><ShieldAlert className="size-3" />Instruction-like text</Badge>}
                {typeof s.metadata?.scholarly_label === "string" && <Badge>{s.metadata.scholarly_label}</Badge>}
              </div>
              <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1.5 text-[13.5px]">
                <dt className="text-muted">Publisher</dt><dd>{s.publisher || s.domain}</dd>
                <dt className="text-muted">Author</dt><dd>{s.author || "Not stated"}</dd>
                <dt className="text-muted">Published</dt><dd>{s.published_at ? formatDate(s.published_at) : "No date found"}{s.published_at_basis ? <span className="text-muted"> ({s.published_at_basis})</span> : null}</dd>
                <dt className="text-muted">Retrieved</dt><dd>{formatDate(s.retrieved_at, { dateStyle: "medium", timeStyle: "short" })} via {s.extract_provider || s.provider}</dd>
                {s.source_type_reason && <><dt className="text-muted">Type basis</dt><dd className="text-text-2">{s.source_type_reason}{s.source_type_basis && s.source_type_basis !== "model" ? ` (${s.source_type_basis})` : ""}</dd></>}
                {s.reliability_notes && <><dt className="text-muted">Notes</dt><dd className="text-text-2">{s.reliability_notes}</dd></>}
              </dl>
              <div className="flex flex-wrap gap-2">
                {href && <Button asChild size="sm" variant="secondary"><a href={href} target="_blank" rel="noopener noreferrer nofollow"><ExternalLink />Open original</a></Button>}
                <Button size="sm" variant="ghost" onClick={async () => { await navigator.clipboard.writeText(citationText(s)); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
                  {copied ? <Check /> : <Copy />}{copied ? "Copied" : "Copy citation"}
                </Button>
              </div>
              {!!s.injection_flags?.length && (
                <p className="rounded-lg border border-warn/30 bg-warn-soft px-3 py-2 text-[12.5px] text-text-2">
                  This page contains text that tries to instruct an AI (for example: “{s.injection_flags[0]?.slice(0, 120)}”). It was treated strictly as data.
                </p>
              )}
              <section>
                <h3 className="mb-3 text-sm font-semibold">Verified passages {passages.length ? `(${passages.length})` : ""}</h3>
                {!passages.length && <p className="text-sm text-muted">No verified passages were extracted from this source.</p>}
                <ul className="space-y-4">
                  {passages.map((p) => (
                    <li key={p.evidence_id} className={`rounded-xl border p-4 ${focusIds.has(p.evidence_id) ? "border-lamp/50 bg-lamp-soft/30" : "border-line"}`}>
                      <p className="flex items-center justify-between gap-2 text-[12px] text-muted">
                        <span>{p.evidence_id}{p.subquestion_id ? `, ${p.subquestion_id}` : ""}{p.stance === "contradicts" ? ", contradicts" : ""}</span>
                        <span>{p.match_method === "exact" ? "Exact match" : p.match_method === "normalized" ? "Matched (formatting differs)" : "Close match"}</span>
                      </p>
                      <p className="mt-2 font-serif text-[16px] leading-relaxed text-text-2">
                        {p.context_before && <span className="text-muted">…{p.context_before.slice(-160)}</span>}
                        <mark className="evidence-mark text-text">{p.quote}</mark>
                        {p.context_after && <span className="text-muted">{p.context_after.slice(0, 160)}…</span>}
                      </p>
                      <p className="mt-2 text-[13px] text-text-2"><span className="text-muted">Claim: </span>{p.claim}</p>
                      <div className="mt-2 flex justify-end">
                        <Button size="sm" variant="ghost" disabled={flagged.includes(p.evidence_id)} onClick={() => void flag(p.evidence_id)}>
                          <Flag />{flagged.includes(p.evidence_id) ? "Flagged" : "Citation is wrong"}
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
              {data.excerpt && !passages.length && (
                <section>
                  <h3 className="mb-2 text-sm font-semibold">Beginning of the retrieved text</h3>
                  <p className="whitespace-pre-line text-[13px] text-muted">{data.excerpt.slice(0, 900)}</p>
                </section>
              )}
            </div>
          )}
      </DialogContent>
    </Dialog>
  );
}
