"use client";

import { useState } from "react";
import { toast } from "sonner";

import { StatusBadge } from "@/components/research/common";
import { Badge, Button, Panel, Select, Skeleton } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { JobStatus } from "@/lib/types";
import { formatNumber, relativeTime } from "@/lib/utils";

interface J { id: string; user_id: string; kind: string; mode: string; status: JobStatus; stage?: string; attempts: number; dead_lettered: boolean; last_error?: { code: string; message: string } | null; lease?: { owner: string; expires_at: string } | null; usage: { llm_calls?: number; output_tokens?: number }; created_at: string; question_preview: string }

export default function AdminJobs() {
  const [status, setStatus] = useState("");
  const [dead, setDead] = useState("");
  const q = new URLSearchParams({ limit: "100" });
  if (status) q.set("status", status);
  if (dead) q.set("dead_lettered", dead);
  const { data, loading, reload } = useApi<{ items: J[]; counts: Record<string, number>; queue_depth: number | null }>(`/api/v1/admin/jobs?${q}`, [status, dead]);
  async function act(id: string, kind: "retry" | "cancel") {
    try { await api(`/api/v1/admin/jobs/${id}/${kind}`, { method: "POST" }); toast.success(kind === "retry" ? "Re-queued" : "Cancellation requested"); void reload(); }
    catch (e) { toast.error(errorMessage(e)); }
  }
  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Select className="w-auto" aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>{Object.keys(data?.counts ?? {}).map((s) => <option key={s} value={s}>{s} ({data?.counts[s]})</option>)}
        </Select>
        <Select className="w-auto" aria-label="Dead letter" value={dead} onChange={(e) => setDead(e.target.value)}>
          <option value="">Any</option><option value="true">Dead-lettered only</option>
        </Select>
        <Button variant="secondary" size="sm" onClick={async () => { const r = await api<{ redispatched: number }>("/api/v1/admin/jobs/reconcile", { method: "POST" }); toast.success(`Re-dispatched ${r.redispatched} job(s)`); void reload(); }}>Reconcile queue</Button>
        <span className="text-sm text-muted">Queue depth: {data?.queue_depth ?? "unknown"}</span>
      </div>
      {loading && !data ? <Skeleton className="h-64 w-full" /> : (
        <Panel className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-left text-[13px]">
            <thead className="text-[12px] text-muted"><tr><th className="px-4 py-2.5 font-medium">Job</th><th className="px-3 py-2.5 font-medium">Status</th><th className="px-3 py-2.5 font-medium">Attempts</th><th className="px-3 py-2.5 font-medium">Worker lease</th><th className="px-3 py-2.5 font-medium">Usage</th><th className="px-3 py-2.5 font-medium">Error</th><th /></tr></thead>
            <tbody className="divide-y divide-line">{data?.items.map((j) => (
              <tr key={j.id}>
                <td className="max-w-[260px] px-4 py-2"><p className="truncate">{j.question_preview}</p><p className="font-mono text-[11px] text-muted">{j.id} · {j.kind}/{j.mode} · {relativeTime(j.created_at)}</p></td>
                <td className="px-3 py-2"><StatusBadge status={j.status} />{j.dead_lettered && <Badge tone="danger" className="ml-1">dead letter</Badge>}</td>
                <td className="px-3 py-2 tabular-nums">{j.attempts}</td>
                <td className="px-3 py-2 text-[12px] text-muted">{j.lease ? `${j.lease.owner}, until ${relativeTime(j.lease.expires_at)}` : "—"}</td>
                <td className="px-3 py-2 text-[12px] tabular-nums">{formatNumber(j.usage.llm_calls)} calls, {formatNumber(j.usage.output_tokens)} out</td>
                <td className="max-w-[220px] px-3 py-2 text-[12px] text-danger">{j.last_error?.code}</td>
                <td className="whitespace-nowrap px-3 py-2">
                  {["failed", "waiting_for_retry"].includes(j.status) && <Button size="sm" variant="ghost" onClick={() => void act(j.id, "retry")}>Retry</Button>}
                  {!["completed", "failed", "cancelled"].includes(j.status) && <Button size="sm" variant="ghost" onClick={() => void act(j.id, "cancel")}>Cancel</Button>}
                </td>
              </tr>
            ))}</tbody>
          </table>
        </Panel>
      )}
      <p className="mt-3 text-[12.5px] text-muted">Administrators see operational metadata only; report contents remain private to their owners.</p>
    </>
  );
}
