"use client";

import { Badge, Button, Panel, Skeleton } from "@/components/ui/primitives";
import { useApi } from "@/lib/hooks";
import { relativeTime } from "@/lib/utils";

interface H { database: { ok: boolean; kind: string }; redis: { ok: boolean; kind: string }; queue_depth: number | null; workers: { id: string; active_jobs: string[]; concurrency: number; started_at: string; seen_at: string }[]; embedded_worker: boolean; jobs_with_expired_leases: number; config_warnings: string[]; flags: Record<string, boolean>; environment: string }
interface Dep { database: boolean; redis: boolean; ai_configured: boolean; search_configured: boolean; smtp_configured: boolean; google_auth: boolean | string }

export default function SystemHealth() {
  const h = useApi<H>("/api/v1/admin/system-health");
  const d = useApi<Dep>("/api/v1/admin/dependencies");
  if (!h.data) return <Skeleton className="h-64 w-full" />;
  const ok = (b: boolean | string) => <Badge tone={b === true ? "ok" : b === "disabled" ? "neutral" : "danger"}>{b === true ? "OK" : b === "disabled" ? "Disabled" : "Problem"}</Badge>;
  return (
    <div className="space-y-6">
      <div className="flex justify-end"><Button size="sm" variant="secondary" onClick={() => { void h.reload(); void d.reload(); }}>Refresh</Button></div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel className="p-5">
          <h2 className="font-semibold">Dependencies</h2>
          <dl className="mt-3 grid grid-cols-[1fr_auto] gap-y-2 text-[13.5px]">
            <dt>Database <span className="text-muted">({h.data.database.kind})</span></dt><dd>{ok(h.data.database.ok)}</dd>
            <dt>Redis <span className="text-muted">({h.data.redis.kind})</span></dt><dd>{ok(h.data.redis.ok)}</dd>
            {d.data && <><dt>AI provider configured</dt><dd>{ok(d.data.ai_configured)}</dd>
              <dt>Search provider configured</dt><dd>{ok(d.data.search_configured)}</dd>
              <dt>Email (SMTP)</dt><dd>{ok(d.data.smtp_configured)}</dd>
              <dt>Google sign-in</dt><dd>{ok(d.data.google_auth)}</dd></>}
            <dt>Queue depth</dt><dd className="tabular-nums">{h.data.queue_depth ?? "unknown"}</dd>
            <dt>Jobs with expired leases</dt><dd className="tabular-nums">{h.data.jobs_with_expired_leases}</dd>
          </dl>
        </Panel>
        <Panel className="p-5">
          <h2 className="font-semibold">Workers</h2>
          {h.data.embedded_worker && <p className="mt-2 text-sm text-warn">Embedded development worker is running inside the API process.</p>}
          <ul className="mt-3 divide-y divide-line text-[13.5px]">
            {h.data.workers.map((w) => (
              <li key={w.id} className="py-2"><p className="font-mono text-[12.5px]">{w.id}</p>
                <p className="text-[12.5px] text-muted">{w.active_jobs.length}/{w.concurrency} busy, seen {relativeTime(w.seen_at)}, up since {relativeTime(w.started_at)}</p></li>
            ))}
            {!h.data.workers.length && !h.data.embedded_worker && <li className="py-2 text-danger">No workers have reported in. Queued research will not run until a worker is started.</li>}
          </ul>
        </Panel>
      </div>
      <Panel className="p-5">
        <h2 className="font-semibold">Feature flags <span className="font-normal text-muted">({h.data.environment})</span></h2>
        <div className="mt-3 flex flex-wrap gap-2">{Object.entries(h.data.flags).map(([k, v]) => <Badge key={k} tone={v ? "signal" : "neutral"}>{k}={v ? 1 : 0}</Badge>)}</div>
        {h.data.config_warnings.map((w) => <p key={w} className="mt-2 text-sm text-warn">{w}</p>)}
      </Panel>
    </div>
  );
}
