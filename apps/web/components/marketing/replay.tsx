"use client";

import { Check, Play, RotateCcw } from "lucide-react";
import { AnimatePresence, motion, useInView, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";

import { STAGES } from "@/components/research/stages";
import { Button } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

/*
  A replay of a recorded run in demo mode (synthetic sources on reserved .invalid domains).
  It uses the same event vocabulary and stage order the live run view renders.
*/
const SCRIPT: { stage: string; text: string; kind?: "query" | "source" | "warn" | "ok" }[] = [
  { stage: "understanding", text: "Restated: how widely has remote work been adopted, and what does it cost?" },
  { stage: "planning", text: "Plan with 4 sub-questions" },
  { stage: "searching", text: "remote work adoption survey 2024", kind: "query" },
  { stage: "searching", text: "remote work collaboration costs study", kind: "query" },
  { stage: "searching", text: "Found [1] Household survey, wave 2 — stats-office-demo.invalid", kind: "source" },
  { stage: "searching", text: "Found [2] Panel study — journal-demo.invalid", kind: "source" },
  { stage: "reading", text: "Read [1] (1,840 words), [2] (abstract only)" },
  { stage: "reading", text: "[4] contains instruction-like text; treated strictly as data", kind: "warn" },
  { stage: "comparing", text: "[1] 4 verified items" },
  { stage: "comparing", text: "[5] 1 verified, 2 discarded (quote not found in source)", kind: "warn" },
  { stage: "gaps", text: "Contradiction: adoption rate differs by definition" },
  { stage: "gaps", text: "Follow-up round 1: 2 targeted searches" },
  { stage: "writing", text: "Draft written: 31 sentences, 29 cited, 0 invalid citations" },
  { stage: "verifying", text: "Checked 29 statements: 26 supported, 3 partially", kind: "ok" },
  { stage: "visualizing", text: "4 charts from verified data", kind: "ok" },
];

export function RunReplay() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-120px" });
  const reduce = useReducedMotion();
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (inView && step === 0) {
      if (reduce) setStep(SCRIPT.length);
      else setPlaying(true);
    }
  }, [inView, reduce, step]);

  useEffect(() => {
    if (!playing) return;
    if (step >= SCRIPT.length) {
      setPlaying(false);
      return;
    }
    const t = setTimeout(() => setStep((s) => s + 1), 650);
    return () => clearTimeout(t);
  }, [playing, step]);

  const current = SCRIPT[Math.max(0, step - 1)]?.stage ?? "understanding";
  const currentIdx = STAGES.findIndex((s) => s.key === current);
  const done = step >= SCRIPT.length;

  return (
    <div ref={ref} className="grid overflow-hidden rounded-2xl border border-line bg-surface shadow-2 md:grid-cols-[280px_1fr]">
      <ol className="border-b border-line p-5 md:border-b-0 md:border-r" aria-label="Research stages">
        {STAGES.map((s, i) => {
          const state = done || i < currentIdx ? "done" : i === currentIdx && step > 0 ? "active" : "todo";
          return (
            <li key={s.key} className="flex items-center gap-3 py-1.5">
              <span className={cn("grid size-6 place-items-center rounded-full border text-[11px]",
                state === "done" && "border-ok/40 bg-ok-soft text-ok",
                state === "active" && "live-dot border-signal bg-signal-soft text-signal",
                state === "todo" && "border-line text-muted")}>
                {state === "done" ? <Check className="size-3.5" /> : i + 1}
              </span>
              <span className={cn("text-sm", state === "todo" ? "text-muted" : "text-text")}>{s.label}</span>
            </li>
          );
        })}
      </ol>
      <div className="flex min-h-[380px] flex-col">
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <p className="text-sm text-muted">Recorded demo run, synthetic sources</p>
          <Button size="sm" variant="secondary" onClick={() => { setStep(0); setPlaying(true); }} aria-label="Replay the demo run">
            {done ? <RotateCcw /> : <Play />}{done ? "Replay" : "Playing"}
          </Button>
        </div>
        <ul className="flex-1 space-y-1.5 overflow-hidden p-5" aria-live="polite">
          <AnimatePresence initial={false}>
            {SCRIPT.slice(0, step).slice(-9).map((e) => (
              <motion.li key={e.text} layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                className="flex items-start gap-3 text-[13.5px]">
                <span className={cn("mt-[7px] size-1.5 shrink-0 rounded-full",
                  e.kind === "warn" ? "bg-warn" : e.kind === "ok" ? "bg-ok" : e.kind === "source" ? "bg-lamp" : "bg-signal")} />
                {e.kind === "query" ? (
                  <span className="text-text-2">Searched <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[12px] text-text">{e.text}</code></span>
                ) : <span className="text-text-2">{e.text}</span>}
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      </div>
    </div>
  );
}
