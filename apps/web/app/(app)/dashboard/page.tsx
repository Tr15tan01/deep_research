"use client";

import { ArrowUpRight, FileSearch, Plus } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

import { PageHeader } from "@/components/app/shell";
import { useSession } from "@/components/providers";
import { JobRow } from "@/components/research/common";
import { Button, EmptyState, Panel, Skeleton, Stat } from "@/components/ui/primitives";
import { useApi } from "@/lib/hooks";
import type { Job, Template, UsageSnapshot } from "@/lib/types";
import { formatUsd } from "@/lib/utils";

export default function DashboardPage() {
  const { user } = useSession();
  const active = useApi<{ items: Job[] }>("/api/v1/research?status=active&limit=10");
  const recent = useApi<{ items: Job[] }>("/api/v1/research?limit=8");
  const usage = useApi<{ snapshot: UsageSnapshot }>("/api/v1/usage?days=30");
  const templates = useApi<{ system: Template[]; mine: Template[] }>("/api/v1/templates");

  const activeCount = active.data?.items.length ?? 0;
  const reloadActive = active.reload;
  const reloadRecent = recent.reload;
  useEffect(() => {
    if (!activeCount) return;
    const t = setInterval(() => { void reloadActive(); void reloadRecent(); }, 5000);
    return () => clearInterval(t);
  }, [activeCount, reloadActive, reloadRecent]);

  const finished = recent.data?.items.filter((j) => !active.data?.items.some((a) => a.id === j.id)) ?? [];
  const snap = usage.data?.snapshot;
  const first = (user?.name || "").split(" ")[0];

  return (
    <>
      <PageHeader title={first ? `Good to see you, ${first}` : "Your research"}
        description="Pick up where you left off, or start a new question."
        actions={<Button asChild variant="signal"><Link href="/research/new"><Plus />New research</Link></Button>} />

      <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
        <div className="space-y-6">
          {!!active.data?.items.length && (
            <section aria-labelledby="active-h">
              <h2 id="active-h" className="mb-3 text-sm font-semibold text-text-2">Running now</h2>
              <Panel><ul className="divide-y divide-line">{active.data.items.map((j) => <JobRow key={j.id} job={j} />)}</ul></Panel>
            </section>
          )}
          <section aria-labelledby="recent-h">
            <div className="mb-3 flex items-center justify-between">
              <h2 id="recent-h" className="text-sm font-semibold text-text-2">Recent reports</h2>
              <Link href="/history" className="text-sm text-muted hover:text-text">All history</Link>
            </div>
            {recent.loading && !recent.data ? (
              <Panel className="space-y-3 p-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12 w-full" />)}</Panel>
            ) : finished.length ? (
              <Panel><ul className="divide-y divide-line">{finished.map((j) => <JobRow key={j.id} job={j} />)}</ul></Panel>
            ) : !active.data?.items.length ? (
              <EmptyState icon={<FileSearch />} title="No research yet"
                action={<Button asChild><Link href="/research/new">Ask your first question</Link></Button>}>
                Ask a question and the agent will plan the research, read sources and write a cited report. You can
                leave this page while it works.
              </EmptyState>
            ) : null}
          </section>
        </div>

        <aside className="space-y-6">
          <Panel className="p-5">
            <h2 className="text-sm font-semibold text-text-2">This month</h2>
            {snap ? (
              <div className="mt-4 grid grid-cols-2 gap-5">
                <Stat label="Runs in the last 24 h" value={`${snap.jobs_last_24h}/${snap.plan.daily_jobs}`} />
                <Stat label="Running" value={`${snap.active_jobs}/${snap.plan.concurrent_jobs}`} />
                <Stat label="Estimated model cost" value={formatUsd(snap.month_cost_usd_est)}
                  hint={snap.plan.monthly_cost_usd ? `of ${formatUsd(snap.plan.monthly_cost_usd)} budget` : undefined} />
                <Stat label="Plan" value={<span className="text-lg">{snap.plan.label}</span>} />
              </div>
            ) : <Skeleton className="mt-4 h-24 w-full" />}
            <Link href="/settings/usage" className="mt-5 inline-block text-sm text-muted hover:text-text">Usage details</Link>
          </Panel>
          <Panel className="p-5">
            <h2 className="text-sm font-semibold text-text-2">Start from a template</h2>
            <ul className="mt-3 space-y-1">
              {(templates.data?.system ?? []).slice(0, 5).map((t) => (
                <li key={t.id}>
                  <Link href={`/research/new?template=${t.id}`} className="group flex items-start justify-between gap-3 rounded-lg px-2 py-2 hover:bg-surface-2">
                    <span>
                      <span className="block text-[14px] font-medium">{t.name}</span>
                      <span className="block text-[12.5px] text-muted">{t.description}</span>
                    </span>
                    <ArrowUpRight className="mt-1 size-4 shrink-0 text-muted group-hover:text-text" aria-hidden />
                  </Link>
                </li>
              ))}
            </ul>
          </Panel>
        </aside>
      </div>
    </>
  );
}
