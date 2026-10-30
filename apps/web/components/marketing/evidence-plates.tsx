"use client";

import { motion, useMotionValue, useReducedMotion, useSpring, useTransform } from "motion/react";
import { useRef } from "react";

import { cn } from "@/lib/utils";

/*
  The hero's single memorable element: retrieved sources as translucent glass plates in an
  isometric stack. Verified passages glow in lamp-gold and connect up to the claim they support;
  a passage that could not be found verbatim is visibly struck out. It is an illustration of the
  product's mechanism, not real research output, and says so.
*/

type Plate = {
  domain: string;
  type: "Primary" | "Secondary" | "Commentary";
  title: string;
  lines: number[];
  passage?: string;
  passageLine?: number;
  rejected?: boolean;
  cite?: number;
};

// Bottom to top. Lower plates sit further back, so their upper part (title + passage) peeks out.
const PLATES: Plate[] = [
  { domain: "industry blog", type: "Commentary", title: "Why everyone is switching", lines: [70, 88, 64, 90, 40],
    passage: "adoption tripled almost overnight", passageLine: 0, rejected: true },
  { domain: "peer-reviewed journal", type: "Primary", title: "Longitudinal panel study", lines: [80, 94, 70, 86, 52],
    passage: "the share of adopters roughly doubled", passageLine: 0, cite: 2 },
  { domain: "statistics office", type: "Primary", title: "Household survey, wave 2", lines: [92, 78, 85, 60, 88],
    passage: "adoption rose from 11% to 23% between waves", passageLine: 1, cite: 1 },
];

export function EvidencePlates({ className }: { className?: string }) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const mx = useMotionValue(0);
  const my = useMotionValue(0);
  const sx = useSpring(mx, { stiffness: 60, damping: 18 });
  const sy = useSpring(my, { stiffness: 60, damping: 18 });
  const rotX = useTransform(sy, [-1, 1], [62, 52]);
  const rotZ = useTransform(sx, [-1, 1], [-42, -34]);

  function onMove(e: React.PointerEvent) {
    if (reduce || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    mx.set(((e.clientX - r.left) / r.width) * 2 - 1);
    my.set(((e.clientY - r.top) / r.height) * 2 - 1);
  }

  return (
    <div ref={ref} onPointerMove={onMove} onPointerLeave={() => { mx.set(0); my.set(0); }}
      className={cn("relative aspect-[1/0.95] w-full select-none", className)}
      role="img" aria-label="Illustration: three sources stacked as glass plates. Two verified passages are highlighted and linked to a claim with citations 1 and 2; a third passage from a blog is struck out because it could not be verified.">
      {/* atmosphere */}
      <div aria-hidden className="absolute inset-[8%] rounded-full opacity-70 blur-3xl"
        style={{ background: "radial-gradient(closest-side, color-mix(in oklab, var(--signal) 22%, transparent), transparent)" }} />
      <div aria-hidden className="absolute inset-0" style={{ perspective: "1700px" }}>
        <motion.div className="absolute left-1/2 top-[62%] h-[50%] w-[64%]"
          style={{ x: "-50%", y: "-50%", rotateX: reduce ? 57 : rotX, rotateZ: reduce ? -38 : rotZ, transformStyle: "preserve-3d" }}>
          {PLATES.map((p, i) => (
            <motion.div key={p.domain}
              initial={reduce ? false : { opacity: 0, z: i * 60 - 140, y: `${(i - 2) * 34}%` }}
              animate={{ opacity: 1, z: i * 60, y: `${(i - 2) * 34}%` }}
              transition={{ delay: 0.15 + i * 0.22, duration: 0.9, ease: [0.2, 0.7, 0.2, 1] }}
              className="absolute inset-0 rounded-[18px] border border-white/15 p-[6%] shadow-[0_30px_60px_-20px_rgba(0,0,0,0.55)]"
              style={{ transformStyle: "preserve-3d", background: "linear-gradient(160deg, color-mix(in oklab, var(--surface) 94%, transparent), color-mix(in oklab, var(--surface-2) 88%, transparent))" }}>
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-2 text-[11px] text-text-2">
                  <span className="size-2 rounded-full" style={{ background: p.rejected ? "var(--muted)" : "var(--signal)" }} />
                  {p.domain}
                </span>
                <span className={cn("rounded-full px-2 py-0.5 text-[10px]", p.rejected ? "bg-danger-soft text-danger" : p.type === "Primary" ? "bg-ok-soft text-ok" : "bg-surface-2 text-muted")}>
                  {p.rejected ? "Quote not found, discarded" : p.type}
                </span>
              </div>
              <p className="mt-3 font-serif text-[15px] leading-tight text-text">{p.title}</p>
              <div className="mt-3 space-y-2">
                {p.lines.map((w, li) => li === p.passageLine && p.passage ? (
                  <motion.p key={li} className={cn("relative text-[11.5px] leading-tight", p.rejected ? "text-muted line-through decoration-danger/70" : "text-lamp-ink")}
                    initial={reduce ? false : { backgroundSize: "0% 100%" }} animate={{ backgroundSize: p.rejected ? "0% 100%" : "100% 100%" }}
                    transition={{ delay: 1.1 + i * 0.25, duration: 0.7 }}
                    style={{ backgroundImage: "linear-gradient(var(--lamp-soft), var(--lamp-soft))", backgroundRepeat: "no-repeat", padding: "1px 3px", borderRadius: 3 }}>
                    “{p.passage}”
                    {p.cite && <sup className="ml-1 font-sans font-semibold text-lamp">[{p.cite}]</sup>}
                  </motion.p>
                ) : (
                  <div key={li} className="h-[6px] rounded-full bg-text/10" style={{ width: `${w}%` }} />
                ))}
              </div>
            </motion.div>
          ))}
        </motion.div>
      </div>
      {/* The claim the verified passages support. */}
      <motion.div initial={reduce ? false : { opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 1.75, duration: 0.6 }}
        className="glass absolute left-[0%] top-[0%] w-[min(330px,62%)] rounded-2xl border border-line-strong p-4 shadow-2">
        <p className="text-[11.5px] text-muted">Key finding</p>
        <p className="mt-1 font-serif text-[16.5px] leading-snug">
          Adoption roughly doubled between the two survey waves.
          <span className="ml-1 inline-flex gap-0.5 align-[2px]">
            {[1, 2].map((n) => (
              <span key={n} className="rounded-[5px] bg-lamp-soft px-1.5 font-sans text-[11px] font-semibold text-lamp-ink">{n}</span>
            ))}
          </span>
        </p>
        <p className="mt-2 flex items-center gap-1.5 text-[11.5px] text-ok">
          <span className="size-1.5 rounded-full bg-ok" />Strong: two independent primary sources
        </p>
      </motion.div>
      <p className="absolute bottom-0 right-0 text-[11px] text-muted">Illustration of how evidence is verified</p>
    </div>
  );
}
