"use client";

import Link from "next/link";

import { Badge, Notice, Panel, Skeleton, Stat } from "@/components/ui/primitives";
import { useApi } from "@/lib/hooks";

interface Health { database: { ok: boolean; kind: string }; redis: { ok: boolean; kind: string }; queue_depth: number | null; workers: { id: string; active_jobs: string[] }[]; embedded_worker: boolean; jobs_with_expired_leases: number; config_warnings: string[]; environment: string }

export default function AdminOverview() {
  const h = useApi<Health>("/api/v1/admin/system-health");
  const jobs = useApi<{ counts: Record<string, number>; queue_depth: number | null }>("/api/v1/admin/jobs?limit=1");
  const users = useApi<{ total: number }>("/api/v1/admin/users?limit=1");
  const providers = useApi<{ config: { default: { provider: string; model: string } | null }; credentials: Record<string, { configured: boolean }>; search: { configured: Record<string, boolean> } }>("/api/v1/admin/providers");
  if (!h.data || !jobs.data) return <Skeleton className="h-64 w-full" />;
  const c = jobs.data.counts;
  const failed = c.failed ?? 0;
  const anySearch = Object.entries(providers.data?.search.configured ?? {}).some(([k, v]) => v && k !== "openalex");
  return (
    <div className="space-y-6">
      {!providers.data?.config.default && <Notice tone="warn" title="No default AI model" action={<Link className="text-sm text-signal" href="/admin/providers">Configure</Link>}>Research can&apos;t run until a provider and exact model ID are set.</Notice>}
      {providers.data && !anySearch && <Notice tone="warn" title="No web search provider">Set FIRECRAWL_API_KEY, TAVILY_API_KEY or BRAVE_SEARCH_API_KEY in the server environment.</Notice>}
      {h.data.config_warnings.map((w) => <Notice key={w} tone="warn">{w}</Notice>)}
      <Panel className="grid gap-6 p-6 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="Users" value={users.data?.total ?? "—"} />
        <Stat label="Running" value={(["planning", "searching", "extracting", "verifying", "synthesizing"] as const).reduce((a, k) => a + (c[k] ?? 0), 0)} />
        <Stat label="Queued" value={(c.queued ?? 0) + (c.waiting_for_retry ?? 0)} hint={`Queue depth ${jobs.data.queue_depth ?? "unknown"}`} />
        <Stat label="Completed" value={c.completed ?? 0} />
        <Stat label="Failed" value={failed} hint={failed ? <Link href="/admin/jobs" className="text-signal">Review</Link> : undefined} />
      </Panel>
      <Panel className="flex flex-wrap gap-3 p-6 text-sm">
        <span>Database <Badge tone={h.data.database.ok ? "ok" : "danger"}>{h.data.database.ok ? "up" : "down"}</Badge> <span className="text-muted">{h.data.database.kind}</span></span>
        <span>Redis <Badge tone={h.data.redis.ok ? "ok" : "danger"}>{h.data.redis.ok ? "up" : "down"}</Badge></span>
        <span>Workers <Badge tone={h.data.workers.length || h.data.embedded_worker ? "ok" : "danger"}>{h.data.workers.length || (h.data.embedded_worker ? "embedded" : 0)}</Badge></span>
        <span>Environment <Badge>{h.data.environment}</Badge></span>
      </Panel>
    </div>
  );
}
