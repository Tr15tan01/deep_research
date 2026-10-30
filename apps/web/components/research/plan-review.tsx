"use client";

import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button, Input, Panel, Textarea } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api";
import type { Job } from "@/lib/types";

interface Draft { question: string; queries: string }

export function PlanReview({ job, onApproved }: { job: Job; onApproved: () => void }) {
  const [items, setItems] = useState<Draft[]>(
    (job.plan?.subquestions ?? []).map((s) => ({ question: s.question, queries: s.queries.join("\n") })));
  const questions = job.assessment?.clarifying_questions ?? [];
  const [answers, setAnswers] = useState<string[]>(questions.map(() => ""));
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  async function approve() {
    const subs = items.filter((i) => i.question.trim().length >= 5)
      .map((i) => ({ question: i.question.trim(), queries: i.queries.split("\n").map((q) => q.trim()).filter(Boolean) }));
    if (!subs.length) { toast.error("Keep at least one sub-question."); return; }
    const clar = [...questions.map((q, i) => (answers[i]?.trim() ? `${q} — ${answers[i]?.trim()}` : "")), notes.trim()].filter(Boolean);
    setBusy(true);
    try {
      await api(`/api/v1/research/${job.id}/approve`, { json: { subquestions: subs, clarifications: clar } });
      toast.success("Plan approved — research is starting");
      onApproved();
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel className="p-6">
      <h2 className="headline text-[26px]">Review the research plan</h2>
      <p className="mt-1 max-w-[70ch] text-text-2">
        Edit the sub-questions and their search queries, then start. Nothing has been searched yet.
      </p>
      {job.plan?.objective && <p className="mt-4 font-serif text-[18px] italic text-text-2">{job.plan.objective}</p>}

      {!!questions.length && (
        <div className="mt-6 space-y-3 rounded-xl border border-lamp/30 bg-lamp-soft/50 p-4">
          <p className="text-sm font-semibold">The agent had a few questions</p>
          {questions.map((q, i) => (
            <div key={q} className="space-y-1.5">
              <label htmlFor={`clar-${i}`} className="text-[13.5px] text-text-2">{q}</label>
              <Input id={`clar-${i}`} value={answers[i] ?? ""} onChange={(e) => setAnswers((a) => a.map((x, j) => (j === i ? e.target.value : x)))} placeholder="Optional answer" />
            </div>
          ))}
          {!!job.assessment?.assumptions_if_unclarified?.length && (
            <p className="text-[12.5px] text-muted">If you skip these, it will assume: {job.assessment.assumptions_if_unclarified.join("; ")}</p>
          )}
        </div>
      )}

      <ol className="mt-6 space-y-4">
        {items.map((it, i) => (
          <li key={i} className="grid gap-3 rounded-xl border border-line p-4 md:grid-cols-[1.4fr_1fr_auto]">
            <div className="space-y-1.5">
              <label htmlFor={`sq-${i}`} className="text-[12.5px] text-muted">Sub-question {i + 1}</label>
              <Textarea id={`sq-${i}`} rows={2} value={it.question} onChange={(e) => setItems((xs) => xs.map((x, j) => (j === i ? { ...x, question: e.target.value } : x)))} />
            </div>
            <div className="space-y-1.5">
              <label htmlFor={`qq-${i}`} className="text-[12.5px] text-muted">Search queries (one per line)</label>
              <Textarea id={`qq-${i}`} rows={2} className="font-mono text-[12.5px]" value={it.queries} onChange={(e) => setItems((xs) => xs.map((x, j) => (j === i ? { ...x, queries: e.target.value } : x)))} />
            </div>
            <Button variant="ghost" size="icon" className="self-start md:mt-6" aria-label={`Remove sub-question ${i + 1}`} onClick={() => setItems((xs) => xs.filter((_, j) => j !== i))}>
              <Trash2 />
            </Button>
          </li>
        ))}
      </ol>
      {items.length < 10 && (
        <Button variant="secondary" size="sm" className="mt-3" onClick={() => setItems((xs) => [...xs, { question: "", queries: "" }])}><Plus />Add sub-question</Button>
      )}
      <div className="mt-6 space-y-1.5">
        <label htmlFor="notes" className="text-[13px] font-medium text-text-2">Anything else the agent should know?</label>
        <Textarea id="notes" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Scope, audience, sources to prioritise…" />
      </div>
      <div className="mt-6 flex justify-end">
        <Button variant="signal" size="lg" loading={busy} onClick={approve}>Approve and start research</Button>
      </div>
    </Panel>
  );
}
