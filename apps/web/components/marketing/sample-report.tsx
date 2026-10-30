"use client";

import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { cn } from "@/lib/utils";

const PASSAGES: Record<number, { source: string; type: string; quote: string }> = {
  1: { source: "stats-office-demo.invalid — Household survey, wave 2", type: "Primary",
    quote: "A demo survey of 1,200 organisations found that 58 percent had adopted remote work practices by 2024." },
  2: { source: "journal-demo.invalid — Panel study", type: "Primary",
    quote: "The Demo Index for Alpha was 55 points in 2024." },
  3: { source: "analyst-demo.invalid — Market note", type: "Secondary",
    quote: "However, a competing demo analysis estimates adoption at only 33 percent, citing a narrower definition." },
};

const DATA = [
  { year: "2022", value: 42, src: 2 },
  { year: "2023", value: 48, src: 2 },
  { year: "2024", value: 55, src: 2 },
];

function Cite({ n, open, setOpen }: { n: number; open: number | null; setOpen: (n: number | null) => void }) {
  return (
    <button onClick={() => setOpen(open === n ? null : n)} aria-expanded={open === n}
      aria-label={`Citation ${n}: show the supporting passage`}
      className={cn("mx-0.5 rounded-[5px] px-1.5 align-[2px] font-sans text-[12px] font-semibold transition-colors",
        open === n ? "bg-lamp text-[#2a1d00]" : "bg-lamp-soft text-lamp-ink hover:bg-lamp/30")}>
      {n}
    </button>
  );
}

export function SampleReport() {
  const [open, setOpen] = useState<number | null>(1);
  const p = open ? PASSAGES[open] : null;
  return (
    <div className="grid gap-6 rounded-2xl border border-line bg-surface p-6 shadow-2 lg:grid-cols-[1.25fr_1fr] lg:p-8">
      <article>
        <p className="text-[12.5px] text-muted">Sample report excerpt, demo mode</p>
        <h3 className="headline mt-2 text-[26px]">Remote work: adoption and its measured costs</h3>
        <div className="prose-report mt-4 text-[17px]">
          <p>
            Most surveyed organisations had adopted some remote work by 2024<Cite n={1} open={open} setOpen={setOpen} />, though estimates depend on
            how adoption is defined: one analysis reports a far lower share using a narrower definition<Cite n={3} open={open} setOpen={setOpen} />.
          </p>
          <p>
            Index values rose steadily over three years<Cite n={2} open={open} setOpen={setOpen} />.
          </p>
        </div>
        <div className="mt-5 min-h-[112px] rounded-xl border border-lamp/30 bg-lamp-soft/60 p-4" aria-live="polite">
          {p ? (
            <>
              <p className="flex items-center justify-between gap-3 text-[12.5px] text-text-2">
                <span>[{open}] {p.source}</span>
                <span className="rounded-full bg-surface px-2 py-0.5 text-[11px]">{p.type}</span>
              </p>
              <blockquote className="mt-2 font-serif text-[16px] leading-snug"><mark className="evidence-mark">{p.quote}</mark></blockquote>
              <p className="mt-2 text-[12px] text-ok">Quote verified verbatim in the retrieved page</p>
            </>
          ) : <p className="text-sm text-muted">Select a citation to see the exact passage behind it.</p>}
        </div>
      </article>
      <figure className="flex flex-col">
        <figcaption className="text-sm font-medium">Demo Index, Alpha <span className="text-muted">(points)</span></figcaption>
        <div className="mt-3 h-[230px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={DATA} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--line)" />
              <XAxis dataKey="year" tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 12 }} />
              <YAxis tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 12 }} />
              <Tooltip cursor={{ fill: "var(--surface-2)" }} contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 10, fontSize: 12 }}
                formatter={(v) => [`${v} points`, "Value"]} />
              <Bar dataKey="value" fill="var(--lamp)" radius={[5, 5, 0, 0]} maxBarSize={46} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-2 text-[12.5px] text-muted">Every bar links to the passage it came from. Source: [2].</p>
      </figure>
    </div>
  );
}
