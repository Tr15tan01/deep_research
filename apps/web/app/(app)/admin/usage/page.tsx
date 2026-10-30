"use client";

import { Notice, Panel, Select, Skeleton } from "@/components/ui/primitives";
import { useApi } from "@/lib/hooks";
import { formatNumber, formatUsd } from "@/lib/utils";
import { useState } from "react";

interface D {
  by_model: { provider: string; model: string; calls: number; errors: number; input_tokens: number; output_tokens: number; cost: number; unknown_cost_calls: number }[];
  by_search_provider: { provider: string; calls: number; errors: number }[];
  top_users: { user_id: string; email?: string; calls: number; cost: number; output_tokens: number }[];
  alerts: { user_id: string; email?: string; calls_24h: number; cost_24h: number; reason: string }[];
  note: string;
}

export default function AdminUsage() {
  const [days, setDays] = useState(30);
  const { data, loading } = useApi<D>(`/api/v1/admin/usage?days=${days}`, [days]);
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted">{data?.note}</p>
        <Select className="w-auto" aria-label="Period" value={days} onChange={(e) => setDays(Number(e.target.value))}>
          <option value={1}>Last 24 hours</option><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option>
        </Select>
      </div>
      {loading && !data ? <Skeleton className="h-64 w-full" /> : data && (
        <>
          {data.alerts.map((a) => <Notice key={a.user_id} tone="warn" title={`Unusual usage: ${a.email ?? a.user_id}`}>{a.reason}: {a.calls_24h} calls, {formatUsd(a.cost_24h)} in 24 h.</Notice>)}
          <Panel className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-[13.5px]">
              <caption className="px-5 pt-4 text-left font-semibold">Models</caption>
              <thead className="text-[12.5px] text-muted"><tr><th className="px-5 py-2.5 font-medium">Model</th><th className="px-3 py-2.5 text-right font-medium">Calls</th><th className="px-3 py-2.5 text-right font-medium">Errors</th><th className="px-3 py-2.5 text-right font-medium">Tokens in / out</th><th className="px-5 py-2.5 text-right font-medium">Est. cost</th></tr></thead>
              <tbody className="divide-y divide-line">{data.by_model.map((m) => (
                <tr key={`${m.provider}:${m.model}`}><td className="px-5 py-2 font-mono text-[12.5px]">{m.provider}/{m.model}</td><td className="px-3 py-2 text-right tabular-nums">{formatNumber(m.calls)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatNumber(m.errors)}</td><td className="px-3 py-2 text-right tabular-nums">{formatNumber(m.input_tokens)} / {formatNumber(m.output_tokens)}</td>
                  <td className="px-5 py-2 text-right tabular-nums">{formatUsd(m.cost)}{m.unknown_cost_calls ? <span className="text-[11.5px] text-warn"> ({m.unknown_cost_calls} unpriced)</span> : null}</td></tr>
              ))}</tbody>
            </table>
          </Panel>
          <div className="grid gap-6 lg:grid-cols-2">
            <Panel className="p-5">
              <h2 className="font-semibold">Search providers</h2>
              <ul className="mt-3 divide-y divide-line text-[13.5px]">{data.by_search_provider.map((s) => (
                <li key={s.provider} className="flex justify-between py-2"><span className="capitalize">{s.provider}</span><span className="tabular-nums text-text-2">{formatNumber(s.calls)} calls, {formatNumber(s.errors)} errors</span></li>
              ))}{!data.by_search_provider.length && <li className="py-2 text-muted">No searches in this period.</li>}</ul>
            </Panel>
            <Panel className="p-5">
              <h2 className="font-semibold">Top users</h2>
              <ul className="mt-3 divide-y divide-line text-[13.5px]">{data.top_users.map((u) => (
                <li key={u.user_id ?? "none"} className="flex justify-between gap-3 py-2"><span className="truncate">{u.email ?? u.user_id}</span><span className="shrink-0 tabular-nums text-text-2">{formatNumber(u.calls)} calls, {formatUsd(u.cost)}</span></li>
              ))}</ul>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
