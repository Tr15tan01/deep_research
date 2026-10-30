"use client";

import Link from "next/link";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Panel, Skeleton, Stat } from "@/components/ui/primitives";
import { useApi } from "@/lib/hooks";
import type { Usage, UsageSnapshot } from "@/lib/types";
import { formatDate, formatNumber, formatUsd } from "@/lib/utils";

interface Data {
  snapshot: UsageSnapshot;
  by_day: { day: string; llm_calls: number; search_calls: number; input_tokens: number; output_tokens: number; cost: number }[];
  jobs: { id: string; question: string; status: string; mode: string; created_at: string; usage: Usage }[];
}

export default function UsagePage() {
  const { data, loading } = useApi<Data>("/api/v1/usage?days=30");
  if (loading && !data) return <Skeleton className="h-96 w-full" />;
  if (!data) return null;
  const s = data.snapshot;
  return (
    <div className="space-y-6">
      <Panel className="grid gap-6 p-6 sm:grid-cols-4">
        <Stat label="Plan" value={<span className="text-xl">{s.plan.label}</span>} />
        <Stat label="Runs, last 24 h" value={`${s.jobs_last_24h} / ${s.plan.daily_jobs}`} />
        <Stat label="Running now" value={`${s.active_jobs} / ${s.plan.concurrent_jobs}`} />
        <Stat label="Est. cost this month" value={formatUsd(s.month_cost_usd_est)} hint={s.plan.monthly_cost_usd ? `Budget ${formatUsd(s.plan.monthly_cost_usd)}` : undefined} />
      </Panel>
      <p className="text-[13px] text-muted">{s.cost_note} Calls to models without a configured price are counted but not costed.</p>
      <Panel className="p-6">
        <h2 className="font-semibold">Model output tokens per day</h2>
        <div className="mt-4 h-[220px]">
          {data.by_day.length ? (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.by_day} margin={{ left: 0, right: 8, top: 6 }}>
                <CartesianGrid vertical={false} stroke="var(--line)" />
                <XAxis dataKey="day" tick={{ fill: "var(--muted)", fontSize: 12 }} tickLine={false} axisLine={{ stroke: "var(--line)" }} />
                <YAxis tick={{ fill: "var(--muted)", fontSize: 12 }} tickLine={false} axisLine={false} width={56} />
                <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 10, fontSize: 12 }} formatter={(v) => [formatNumber(Number(v)), "Output tokens"]} />
                <Bar dataKey="output_tokens" fill="var(--series-2)" radius={[4, 4, 0, 0]} maxBarSize={28} />
              </BarChart>
            </ResponsiveContainer>
          ) : <p className="text-sm text-muted">No usage in the last 30 days.</p>}
        </div>
      </Panel>
      <Panel className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-[13.5px]">
          <caption className="px-5 pt-4 text-left font-semibold">Per-run breakdown</caption>
          <thead className="text-[12.5px] text-muted"><tr>
            <th className="px-5 py-2.5 font-medium">Research</th><th className="px-3 py-2.5 text-right font-medium">Model calls</th>
            <th className="px-3 py-2.5 text-right font-medium">Tokens in / out</th><th className="px-3 py-2.5 text-right font-medium">Searches</th>
            <th className="px-3 py-2.5 text-right font-medium">Pages</th><th className="px-5 py-2.5 text-right font-medium">Est. cost</th></tr></thead>
          <tbody className="divide-y divide-line">
            {data.jobs.map((j) => (
              <tr key={j.id}>
                <td className="max-w-[340px] px-5 py-2.5"><Link href={`/research/${j.id}`} className="line-clamp-1 hover:underline">{j.question}</Link><span className="text-[12px] text-muted">{formatDate(j.created_at)}</span></td>
                <td className="px-3 py-2.5 text-right tabular-nums">{formatNumber(j.usage.llm_calls)}</td>
                <td className="px-3 py-2.5 text-right tabular-nums">{formatNumber(j.usage.input_tokens)} / {formatNumber(j.usage.output_tokens)}</td>
                <td className="px-3 py-2.5 text-right tabular-nums">{formatNumber(j.usage.search_calls)}</td>
                <td className="px-3 py-2.5 text-right tabular-nums">{formatNumber(j.usage.extracted_pages)}</td>
                <td className="px-5 py-2.5 text-right tabular-nums">{formatUsd(j.usage.cost_usd_est ?? 0)}{j.usage.cost_unknown_calls ? <span className="text-[11.5px] text-muted"> +{j.usage.cost_unknown_calls} unpriced</span> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}
