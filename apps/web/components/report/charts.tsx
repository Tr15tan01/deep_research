"use client";

import { Table2 } from "lucide-react";
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge, Button } from "@/components/ui/primitives";
import type { ChartPoint, ChartSpec, MatrixTable } from "@/lib/types";
import { formatNumber } from "@/lib/utils";

import { CiteChip } from "./paragraph";
import { useReport } from "./report-context";

const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)", "var(--series-5)", "var(--series-6)"];
const AXIS = { fill: "var(--muted)", fontSize: 12 };
const TOOLTIP_STYLE = { background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 10, fontSize: 12.5, color: "var(--text)" };

function Sources({ nums, ids }: { nums: number[]; ids: string[] }) {
  return <>{nums.map((n) => <CiteChip key={n} n={n} evidenceIds={ids} />)}</>;
}

function DataTable({ spec }: { spec: ChartSpec }) {
  return (
    <div className="mt-3 overflow-x-auto rounded-lg border border-line">
      <table className="w-full text-left text-[13px]">
        <caption className="sr-only">Data for {spec.title}</caption>
        <thead className="bg-surface-2 text-muted">
          <tr>{spec.series.length > 1 && <th className="px-3 py-2 font-medium">Series</th>}
            <th className="px-3 py-2 font-medium">{spec.x_label || "Category"}</th>
            <th className="px-3 py-2 text-right font-medium">{spec.y_label || "Value"}{spec.unit && spec.unit !== spec.y_label ? ` (${spec.unit})` : ""}</th>
            <th className="px-3 py-2 font-medium">Sources</th></tr>
        </thead>
        <tbody className="divide-y divide-line">
          {spec.series.flatMap((s) => s.points.map((p) => (
            <tr key={`${s.name}-${p.x}`}>
              {spec.series.length > 1 && <td className="px-3 py-1.5">{s.name}</td>}
              <td className="px-3 py-1.5">{p.label ? <span title={p.label}>{p.x}</span> : p.x}</td>
              <td className="px-3 py-1.5 text-right tabular-nums">{formatNumber(p.y, 2)}{p.estimated && <Badge tone="warn" className="ml-2">estimated</Badge>}</td>
              <td className="px-3 py-1.5">{p.sources.length ? <Sources nums={p.sources} ids={p.evidence_ids} /> : <span className="text-muted">—</span>}</td>
            </tr>
          )))}
        </tbody>
      </table>
    </div>
  );
}

export function ChartCard({ spec }: { spec: ChartSpec }) {
  const { open } = useReport();
  const [table, setTable] = useState(false);
  const openPoint = (p?: ChartPoint) => {
    const n = p?.sources?.[0];
    if (n !== undefined) open({ sourceNumber: n, evidenceIds: p?.evidence_ids ?? [] });
  };
  const allSources = [...new Set(spec.series.flatMap((s) => s.points.flatMap((p) => p.sources)))].sort((a, b) => a - b);
  const single = spec.series[0];

  // Recharts wants rows; for multi-series lines, pivot by x.
  const xs = [...new Set(spec.series.flatMap((s) => s.points.map((p) => p.x)))];
  const rows = xs.map((x) => {
    const row: Record<string, unknown> = { x };
    spec.series.forEach((s, i) => {
      const p = s.points.find((q) => q.x === x);
      if (p) { row[`s${i}`] = p.y; row[`p${i}`] = p; }
    });
    return row;
  });

  return (
    <figure className="rounded-2xl border border-line bg-surface p-5">
      <div className="flex items-start justify-between gap-4">
        <figcaption>
          <p className="font-semibold">{spec.title}</p>
          <p className="text-[12.5px] text-muted">
            {spec.kind === "data" ? "From verified quotes" : "About this research's sources"}{spec.unit ? `, ${spec.unit}` : ""}
          </p>
        </figcaption>
        <Button size="sm" variant="ghost" onClick={() => setTable((t) => !t)} aria-pressed={table}><Table2 />{table ? "Chart" : "Table"}</Button>
      </div>
      {table ? <DataTable spec={spec} /> : (
        <div className="mt-4 h-[260px]" role="img" aria-label={`${spec.title}. Use the Table button for the data and sources.`}>
          <ResponsiveContainer width="100%" height="100%">
            {spec.type === "donut" ? (
              <PieChart>
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Legend wrapperStyle={{ fontSize: 12.5, color: "var(--text-2)" }} />
                <Pie data={single?.points ?? []} dataKey="y" nameKey="x" innerRadius="58%" outerRadius="84%" paddingAngle={2}
                  stroke="var(--surface)" strokeWidth={2} label={({ name, value }) => `${name}: ${value}`} labelLine={false}
                  onClick={(d) => openPoint((d as unknown as { payload: ChartPoint }).payload)} cursor="pointer">
                  {(single?.points ?? []).map((p, i) => <Cell key={p.x} fill={SERIES[i % SERIES.length]} />)}
                </Pie>
              </PieChart>
            ) : spec.type === "line" ? (
              <LineChart data={rows} margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
                <CartesianGrid vertical={false} stroke="var(--line)" />
                <XAxis dataKey="x" tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--line)" }} />
                <YAxis tick={AXIS} tickLine={false} axisLine={false} width={48} label={spec.y_label ? { value: spec.y_label, angle: -90, position: "insideLeft", fill: "var(--muted)", fontSize: 12 } : undefined} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                {spec.series.length > 1 && <Legend wrapperStyle={{ fontSize: 12.5 }} />}
                {spec.series.map((s, i) => (
                  <Line key={s.name} type="monotone" dataKey={`s${i}`} name={s.name} stroke={SERIES[i % SERIES.length]} strokeWidth={2}
                    dot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)", fill: SERIES[i % SERIES.length] }}
                    activeDot={{ r: 6, cursor: "pointer", onClick: (_e: unknown, dot: unknown) => openPoint((dot as { payload?: Record<string, ChartPoint> })?.payload?.[`p${i}`]) }}
                    connectNulls />
                ))}
              </LineChart>
            ) : (
              <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
                <CartesianGrid vertical={false} stroke="var(--line)" />
                <XAxis dataKey="x" tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--line)" }} interval={0} />
                <YAxis tick={AXIS} tickLine={false} axisLine={false} width={48} allowDecimals />
                <Tooltip cursor={{ fill: "var(--surface-2)" }} contentStyle={TOOLTIP_STYLE}
                  formatter={(v) => [`${formatNumber(Number(v), 2)}${spec.unit ? ` ${spec.unit}` : ""}`, spec.y_label || "Value"]}
                  labelFormatter={(l, payload) => (payload?.[0]?.payload as { p0?: ChartPoint })?.p0?.label || String(l)} />
                {spec.series.map((s, i) => (
                  <Bar key={s.name} dataKey={`s${i}`} name={s.name} fill={SERIES[i % SERIES.length]} radius={[4, 4, 0, 0]} maxBarSize={44}
                    cursor="pointer" onClick={(d) => openPoint((d as unknown as { payload: Record<string, ChartPoint> }).payload[`p${i}`])} />
                ))}
              </BarChart>
            )}
          </ResponsiveContainer>
        </div>
      )}
      <div className="mt-3 space-y-1 text-[12.5px] text-muted">
        {allSources.length > 0 && <p>Sources: <Sources nums={allSources.slice(0, 20)} ids={[]} />{allSources.length > 20 ? ` and ${allSources.length - 20} more` : ""}</p>}
        {spec.notes.map((n) => <p key={n}>{n}</p>)}
        {spec.kind === "data" && <p>Select a bar or point to open the passage the number came from.</p>}
      </div>
    </figure>
  );
}

export function MatrixView({ table }: { table: MatrixTable }) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-line">
      <table className="w-full min-w-[560px] border-collapse text-left text-[14px]">
        <caption className="sr-only">{table.title}</caption>
        <thead className="bg-surface-2">
          <tr>
            <th scope="col" className="px-4 py-3 text-[13px] font-medium text-muted">Attribute</th>
            {table.columns.map((c) => <th key={c} scope="col" className="px-4 py-3 font-semibold">{c}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-line bg-surface">
          {table.rows.map((r) => (
            <tr key={r.attribute}>
              <th scope="row" className="px-4 py-3 align-top text-[13.5px] font-medium text-text-2">{r.attribute}</th>
              {r.cells.map((c, i) => (
                <td key={i} className="px-4 py-3 align-top">
                  {c.evidence_ids.length ? (
                    <span>{c.value}<Sources nums={c.sources} ids={c.evidence_ids} /></span>
                  ) : <span className="text-muted">Not found in sources</span>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {table.notes.map((n) => <p key={n} className="border-t border-line px-4 py-2 text-[12.5px] text-muted">{n}</p>)}
    </div>
  );
}
