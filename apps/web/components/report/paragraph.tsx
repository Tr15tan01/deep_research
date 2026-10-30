"use client";

import { Fragment } from "react";

import { Tooltip } from "@/components/ui/primitives";
import type { Paragraph as P, Segment } from "@/lib/types";
import { cn } from "@/lib/utils";

import { useReport } from "./report-context";

export function CiteChip({ n, evidenceIds, context }: { n: number; evidenceIds: string[]; context?: string }) {
  const { open, sourcesByNumber } = useReport();
  const s = sourcesByNumber.get(n);
  return (
    <Tooltip content={s ? <span><span className="font-medium text-text">[{n}] {s.title}</span><br />{s.domain}{s.published_at ? `, ${s.published_at.slice(0, 10)}` : ""}</span> : `Source ${n}`}>
      <button type="button" onClick={() => open({ sourceNumber: n, evidenceIds, context })}
        className="mx-[1px] rounded-[5px] bg-lamp-soft px-[5px] align-[2px] font-sans text-[11.5px] font-semibold leading-[18px] text-lamp-ink transition-colors hover:bg-lamp hover:text-[#2a1d00] focus-visible:bg-lamp"
        aria-label={`Source ${n}${s ? `: ${s.title}` : ""}. Show supporting passage.`}>
        {n}
      </button>
    </Tooltip>
  );
}

const SUPPORT_STYLE: Record<string, string> = {
  partially_supported: "decoration-warn/80 underline decoration-dotted decoration-[1.5px] underline-offset-[5px]",
  not_supported: "decoration-danger underline decoration-wavy decoration-[1.2px] underline-offset-[5px]",
};

const SUPPORT_LABEL: Record<string, string> = {
  supported: "The cited passages support this statement.",
  partially_supported: "Partially supported: some details go beyond the cited passages.",
  not_supported: "Not supported by the cited passages.",
  unverified: "Cited, but not machine-checked against its passages (budget).",
  uncited: "No citation: treat as the writer's synthesis, not sourced fact.",
};

function SegmentView({ seg }: { seg: Segment }) {
  const style = SUPPORT_STYLE[seg.support];
  const text = <span className={cn(style, seg.support === "uncited" && "text-text-2")}>{seg.text}</span>;
  const flagged = style || seg.support === "uncited";
  const evidenceBySource = new Map<number, string[]>();
  // Evidence IDs aren't keyed by source in the segment; the panel narrows them by source.
  seg.sources.forEach((n) => evidenceBySource.set(n, seg.evidence_ids));
  return (
    <>
      {flagged ? (
        <Tooltip content={<span>{SUPPORT_LABEL[seg.support]}{seg.support_note ? <><br /><span className="text-muted">{seg.support_note}</span></> : null}</span>}>
          <span tabIndex={0} className="rounded-sm focus-visible:outline-2">{text}</span>
        </Tooltip>
      ) : text}
      {seg.sources.map((n) => <CiteChip key={n} n={n} evidenceIds={evidenceBySource.get(n) ?? []} context={seg.text} />)}{" "}
    </>
  );
}

export function ParagraphView({ p, as: As = "p", className }: { p: P; as?: "p" | "span" | "div"; className?: string }) {
  return (
    <As className={className}>
      {p.segments.map((s, i) => <Fragment key={i}><SegmentView seg={s} /></Fragment>)}
    </As>
  );
}

export function plainText(p: P): string {
  return p.segments.map((s) => s.text + s.sources.map((n) => `[${n}]`).join("")).join(" ");
}
