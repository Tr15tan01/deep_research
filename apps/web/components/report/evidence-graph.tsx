"use client";

import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, type SimulationLinkDatum, type SimulationNodeDatum } from "d3-force";
import { useMemo, useState } from "react";

import { Skeleton } from "@/components/ui/primitives";
import { useApi } from "@/lib/hooks";

import { useReport } from "./report-context";

interface GNode extends SimulationNodeDatum { id: string; type: "finding" | "source" | "conflict"; label: string; number?: number; source_type?: string; strength?: string }
interface GEdge { from: string; to: string; type: "supports" | "contradicts" | "position"; evidence_id: string; quote: string }
type L = SimulationLinkDatum<GNode> & GEdge;

const W = 860;
const H = 520;
const TYPE_FILL: Record<string, string> = { primary: "var(--series-5)", secondary: "var(--series-2)", commentary: "var(--series-3)" };

export function EvidenceGraph({ jobId }: { jobId: string }) {
  const { data, loading } = useApi<{ nodes: GNode[]; edges: GEdge[]; note: string }>(`/api/v1/research/${jobId}/graph`);
  const { open } = useReport();
  const [hover, setHover] = useState<string | null>(null);

  const layout = useMemo(() => {
    if (!data) return null;
    const nodes: GNode[] = data.nodes.map((n) => ({ ...n }));
    const links: L[] = data.edges.map((e) => ({ ...e, source: e.from, target: e.to }));
    const sim = forceSimulation(nodes)
      .force("link", forceLink<GNode, L>(links).id((d) => d.id).distance(90).strength(0.6))
      .force("charge", forceManyBody().strength(-260))
      .force("center", forceCenter(W / 2, H / 2))
      .force("collide", forceCollide(28))
      .stop();
    for (let i = 0; i < 300; i++) sim.tick();
    nodes.forEach((n) => { n.x = Math.max(30, Math.min(W - 30, n.x ?? 0)); n.y = Math.max(30, Math.min(H - 30, n.y ?? 0)); });
    return { nodes, links };
  }, [data]);

  if (loading && !data) return <Skeleton className="h-[420px] w-full" />;
  if (!layout || !layout.nodes.length) return <p className="text-sm text-muted">No graph: this report has no key findings linked to verified evidence.</p>;
  const hovered = layout.nodes.find((n) => n.id === hover);
  const connected = new Set(hover ? layout.links.flatMap((l) => {
    const s = (l.source as GNode).id, t = (l.target as GNode).id;
    return s === hover || t === hover ? [s, t] : [];
  }) : []);

  return (
    <div>
      <div className="overflow-hidden rounded-2xl border border-line bg-bg-deep">
        <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Evidence graph linking sources to key findings and conflicts">
          {layout.links.map((l, i) => {
            const s = l.source as GNode, t = l.target as GNode;
            const dim = hover && !(connected.has(s.id) && connected.has(t.id));
            return (
              <line key={i} x1={s.x} y1={s.y} x2={t.x} y2={t.y} strokeWidth={1.5} opacity={dim ? 0.15 : 0.75}
                stroke={l.type === "contradicts" ? "var(--danger)" : l.type === "position" ? "var(--warn)" : "var(--line-strong)"}
                strokeDasharray={l.type === "supports" ? undefined : "5 4"}>
                <title>{`${l.evidence_id}: “${l.quote}”`}</title>
              </line>
            );
          })}
          {layout.nodes.map((n) => {
            const dim = hover && !connected.has(n.id) && hover !== n.id;
            const common = { opacity: dim ? 0.25 : 1, onMouseEnter: () => setHover(n.id), onMouseLeave: () => setHover(null), onFocus: () => setHover(n.id), onBlur: () => setHover(null), tabIndex: 0 };
            if (n.type === "finding") return (
              <g key={n.id} transform={`translate(${n.x},${n.y})`} {...common} role="button" aria-label={`Finding: ${n.label}`}>
                <circle r={16} fill="var(--signal-soft)" stroke="var(--signal)" strokeWidth={2} />
                <text textAnchor="middle" dy={4} fontSize={11} fontWeight={600} fill="var(--text)">{n.id}</text>
              </g>
            );
            if (n.type === "conflict") return (
              <g key={n.id} transform={`translate(${n.x},${n.y}) rotate(45)`} {...common} role="button" aria-label={`Conflict: ${n.label}`}>
                <rect x={-12} y={-12} width={24} height={24} rx={3} fill="var(--warn-soft)" stroke="var(--warn)" strokeWidth={2} />
              </g>
            );
            return (
              <g key={n.id} transform={`translate(${n.x},${n.y})`} {...common} className="cursor-pointer" role="button"
                aria-label={`Source ${n.number}: ${n.label}`} onClick={() => n.number && open({ sourceNumber: n.number, evidenceIds: [] })}
                onKeyDown={(e) => { if (e.key === "Enter" && n.number) open({ sourceNumber: n.number, evidenceIds: [] }); }}>
                <rect x={-14} y={-11} width={28} height={22} rx={6} fill={TYPE_FILL[n.source_type ?? ""] ?? "var(--muted)"} stroke="var(--bg-deep)" strokeWidth={2} />
                <text textAnchor="middle" dy={4} fontSize={11} fontWeight={600} fill="#fff">{n.number}</text>
              </g>
            );
          })}
        </svg>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-[12.5px] text-muted">
        <span className="flex items-center gap-1.5"><span className="size-3 rounded-full border-2 border-signal bg-signal-soft" />Key finding</span>
        {Object.entries(TYPE_FILL).map(([k, v]) => <span key={k} className="flex items-center gap-1.5"><span className="h-3 w-4 rounded" style={{ background: v }} />{k} source</span>)}
        <span className="flex items-center gap-1.5"><span className="size-3 rotate-45 border-2 border-warn bg-warn-soft" />Conflict</span>
        <span>Dashed red: contradicting evidence</span>
      </div>
      <p className="mt-2 min-h-[20px] text-[13px] text-text-2" aria-live="polite">{hovered ? hovered.label : data?.note}</p>
    </div>
  );
}
