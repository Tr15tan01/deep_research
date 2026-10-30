"use client";

import { Check, ChevronDown, CircleAlert, ExternalLink, FileWarning, Globe, RefreshCw, Search, ShieldAlert, Wifi, WifiOff } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useMemo, useRef } from "react";

import { Badge, Button, Collapsible, CollapsibleContent, CollapsibleTrigger, IndeterminateBar, Panel } from "@/components/ui/primitives";
import type { ConnectionState } from "@/lib/hooks";
import { useNow } from "@/lib/hooks";
import type { Job, JobEvent } from "@/lib/types";
import { cn, duration, formatNumber, hostname, parseApiDate, safeHref } from "@/lib/utils";

import { STAGE_INDEX, STAGES } from "./stages";

interface SourceCard {
  number: number;
  id: string;
  title: string;
  url: string;
  domain: string;
  state: "found" | "read" | "inaccessible";
  words?: number;
  verified?: number;
  discarded?: number;
  injection?: boolean;
  contentKind?: string;
  reason?: string;
}

export function deriveRun(events: JobEvent[]) {
  const reached = new Map<string, string>(); // stage -> first timestamp
  let current: string | null = null;
  const sources = new Map<number, SourceCard>();
  let queries = 0;
  let rejectedCandidates = 0;
  let verified = 0;
  let discarded = 0;
  const warnings: JobEvent[] = [];
  let lastQuery: JobEvent | null = null;
  for (const e of events) {
    if (e.type === "stage" && typeof e.data.stage === "string" && STAGE_INDEX[e.data.stage] !== undefined) {
      if (!reached.has(e.data.stage)) reached.set(e.data.stage, e.at);
      current = e.data.stage;
    }
    if (e.type === "query") { queries += 1; lastQuery = e; }
    if (e.type === "sources_rejected") rejectedCandidates += Object.values((e.data.reasons as Record<string, number>) ?? {}).reduce((a, b) => a + b, 0);
    const n = e.data.number as number | undefined;
    if (e.type === "source_found" && n !== undefined) {
      sources.set(n, { number: n, id: String(e.data.source_id), title: e.message, url: String(e.data.url ?? ""), domain: String(e.data.domain ?? ""), state: "found" });
    }
    if (e.type === "source_extracted" && n !== undefined) {
      const s = sources.get(n);
      if (s) Object.assign(s, { state: "read", words: e.data.words as number, injection: !!e.data.injection_suspected, contentKind: e.data.content_kind as string });
    }
    if (e.type === "source_rejected" && n !== undefined) {
      const s = sources.get(n);
      if (s) Object.assign(s, { state: "inaccessible", reason: String(e.data.reason ?? "") });
    }
    if (e.type === "evidence") {
      verified += Number(e.data.verified ?? 0);
      discarded += Number(e.data.discarded ?? 0);
      const s = n !== undefined ? sources.get(n) : undefined;
      if (s) Object.assign(s, { verified: Number(e.data.verified ?? 0), discarded: Number(e.data.discarded ?? 0) });
    }
    if (e.level !== "info") warnings.push(e);
  }
  return { reached, current, sources: [...sources.values()].sort((a, b) => a.number - b.number), queries, rejectedCandidates, verified, discarded, warnings, lastQuery };
}

const EVENT_TONE: Record<string, string> = {
  query: "bg-signal", source_found: "bg-lamp", source_extracted: "bg-lamp", evidence: "bg-ok", stage: "bg-text",
  warning: "bg-warn", query_failed: "bg-warn", retry: "bg-warn", recovery: "bg-signal", failed: "bg-danger",
  contradiction: "bg-warn", gap: "bg-muted", report: "bg-ok", completed: "bg-ok",
};

function ActivityLine({ e }: { e: JobEvent }) {
  const isQuery = e.type === "query" || e.type === "query_failed";
  return (
    <div className="grid grid-cols-[14px_1fr_auto] items-start gap-3 py-1.5 text-[13.5px]">
      <span className={cn("mt-[7px] size-1.5 rounded-full", EVENT_TONE[e.type] ?? (e.level === "warning" ? "bg-warn" : "bg-line-strong"))} aria-hidden />
      <p className={cn("min-w-0 text-text-2", e.level === "warning" && "text-warn", e.level === "error" && "text-danger", e.type === "stage" && "font-medium text-text")}>
        {isQuery ? (
          <>
            {e.type === "query" ? "Searched " : "Search failed: "}
            <code className="break-words rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[12px] text-text">{String(e.data.query ?? "")}</code>
            {e.type === "query" && <span className="text-muted"> — {String(e.data.results ?? 0)} results via {String(e.data.provider ?? "")}{e.data.cached ? " (cached)" : ""}</span>}
          </>
        ) : e.message}
      </p>
      <time className="text-[11.5px] tabular-nums text-muted" dateTime={e.at}>
        {parseApiDate(e.at)?.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
      </time>
    </div>
  );
}

export function ConnectionPill({ conn, onReconnect }: { conn: ConnectionState; onReconnect: () => void }) {
  if (conn === "live") return <Badge tone="signal"><span className="size-1.5 rounded-full bg-signal live-dot" />Live</Badge>;
  if (conn === "closed") return null;
  if (conn === "connecting") return <Badge><Wifi className="size-3.5" />Connecting</Badge>;
  if (conn === "polling") return (
    <span className="flex items-center gap-2"><Badge tone="warn"><RefreshCw className="size-3.5" />Updating every few seconds</Badge>
      <button className="text-[12.5px] text-signal hover:underline" onClick={onReconnect}>Reconnect</button></span>
  );
  return (
    <span className="flex items-center gap-2"><Badge tone="warn"><WifiOff className="size-3.5" />{conn === "offline" ? "Offline" : "Reconnecting"}</Badge>
      <button className="text-[12.5px] text-signal hover:underline" onClick={onReconnect}>Retry now</button></span>
  );
}

export function RunView({ job, events }: { job: Job; events: JobEvent[] }) {
  const reduce = useReducedMotion();
  const now = useNow(1000);
  const run = useMemo(() => deriveRun(events), [events]);
  const streamRef = useRef<HTMLDivElement>(null);
  const running = !["completed", "failed", "cancelled", "awaiting_approval"].includes(job.status);
  const currentIdx = run.current ? STAGE_INDEX[run.current] ?? -1 : -1;
  const started = parseApiDate(job.started_at) ?? parseApiDate(job.created_at);
  const ended = parseApiDate(job.finished_at);
  const elapsed = started ? ((ended?.getTime() ?? now) - started.getTime()) / 1000 : 0;
  const deadline = parseApiDate(job.deadline_at);
  const subq = job.plan?.subquestions.find((s) => s.id === (run.lastQuery?.data.subquestion_id as string | undefined));
  const stageDef = run.current ? STAGES[STAGE_INDEX[run.current] ?? 0] : null;
  const activity = events.filter((e) => !["usage"].includes(e.type));

  useEffect(() => {
    const el = streamRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    if (nearBottom) el.scrollTo({ top: el.scrollHeight, behavior: reduce ? "auto" : "smooth" });
  }, [activity.length, reduce]);

  return (
    <div className="grid gap-6 lg:grid-cols-[250px_1fr] 2xl:grid-cols-[250px_1fr_340px]">
      {/* Stage timeline */}
      <Panel className="h-fit p-4">
        <h2 className="mb-2 px-1 text-[13px] font-semibold text-text-2">Progress</h2>
        <ol aria-label="Research stages">
          {STAGES.map((s, i) => {
            const done = run.reached.has(s.key) && (i < currentIdx || job.status === "completed");
            const active = i === currentIdx && running;
            const reached = run.reached.has(s.key);
            const state = done ? "done" : active ? "active" : reached ? "stopped" : "todo";
            const nextAt = STAGES.slice(i + 1).map((n) => run.reached.get(n.key)).find(Boolean);
            const at = run.reached.get(s.key);
            const took = at && nextAt ? ((parseApiDate(nextAt)?.getTime() ?? 0) - (parseApiDate(at)?.getTime() ?? 0)) / 1000 : null;
            return (
              <li key={s.key} className="relative flex gap-3 py-2 pl-1" aria-current={active ? "step" : undefined}>
                {i < STAGES.length - 1 && <span aria-hidden className={cn("absolute left-[13px] top-9 h-[calc(100%-20px)] w-px", done ? "bg-ok/40" : "bg-line")} />}
                <span className={cn("relative z-10 grid size-[26px] shrink-0 place-items-center rounded-full border",
                  state === "done" && "border-ok/40 bg-ok-soft text-ok",
                  state === "active" && "border-signal bg-signal-soft text-signal live-dot",
                  state === "stopped" && "border-warn/50 bg-warn-soft text-warn",
                  state === "todo" && "border-line bg-surface text-muted")}>
                  {state === "done" ? <Check className="size-3.5" /> : <s.icon className="size-3.5" aria-hidden />}
                </span>
                <span className="min-w-0 pt-0.5">
                  <span className={cn("block text-[13.5px] leading-tight", state === "todo" ? "text-muted" : "text-text")}>{s.label}</span>
                  {took !== null && took >= 0 && <span className="text-[11.5px] tabular-nums text-muted">{duration(took)}</span>}
                  {active && <span className="text-[11.5px] text-signal">In progress</span>}
                </span>
              </li>
            );
          })}
        </ol>
      </Panel>

      {/* Now + activity */}
      <div className="min-w-0 space-y-6">
        <Panel className="p-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-[13px] text-muted">{running ? "Now" : "Last step"}</p>
              <AnimatePresence mode="wait">
                <motion.p key={run.current ?? "queued"} initial={reduce ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                  className="headline mt-0.5 text-[24px]" aria-live="polite">
                  {job.status === "queued" ? "Waiting for a worker" : job.status === "waiting_for_retry" ? "Paused, will retry automatically" : stageDef?.verb ?? "Starting"}
                </motion.p>
              </AnimatePresence>
              {subq && running && <p className="mt-1 text-[13.5px] text-text-2"><span className="text-muted">{subq.id}:</span> {subq.question}</p>}
            </div>
            <div className="text-right">
              <p className="text-[13px] text-muted">Elapsed</p>
              <p className="text-[22px] font-semibold tabular-nums">{duration(elapsed)}</p>
              {running && deadline && <p className="text-[11.5px] text-muted">Time limit {duration(Math.max(0, (deadline.getTime() - now) / 1000))} left</p>}
            </div>
          </div>
          {running && <IndeterminateBar className="mt-4" label="Research in progress" />}
          <dl className="mt-5 grid grid-cols-2 gap-4 border-t border-line pt-4 sm:grid-cols-4">
            {[
              ["Searches", run.queries], ["Sources read", run.sources.filter((s) => s.state === "read").length],
              ["Verified evidence", run.verified], ["Quotes discarded", run.discarded],
            ].map(([k, v]) => (
              <div key={k as string}><dt className="text-[12.5px] text-muted">{k}</dt><dd className="text-xl font-semibold tabular-nums">{formatNumber(v as number)}</dd></div>
            ))}
          </dl>
        </Panel>

        <Panel>
          <div className="flex items-center justify-between border-b border-line px-5 py-3">
            <h2 className="text-[13px] font-semibold text-text-2">Activity</h2>
            <span className="text-[12px] text-muted">{events.length} events</span>
          </div>
          <div ref={streamRef} className="max-h-[460px] overflow-y-auto px-5 py-3" role="log" aria-label="Research activity">
            {activity.length === 0 ? <p className="py-6 text-sm text-muted">Waiting for the first update…</p>
              : activity.map((e) => (
                <motion.div key={e.seq} initial={reduce ? false : { opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
                  <ActivityLine e={e} />
                </motion.div>
              ))}
          </div>
        </Panel>

        {!!run.warnings.length && (
          <Panel className="p-5">
            <h2 className="mb-2 flex items-center gap-2 text-[13px] font-semibold text-text-2"><CircleAlert className="size-4 text-warn" />Warnings and recoveries</h2>
            <ul className="space-y-1.5 text-[13.5px] text-text-2">{run.warnings.slice(-8).map((w) => <li key={w.seq}>{w.message}</li>)}</ul>
          </Panel>
        )}

        <Collapsible>
          <CollapsibleTrigger className="group flex items-center gap-2 text-sm text-muted hover:text-text">
            <ChevronDown className="size-4 transition-transform group-data-[state=open]:rotate-180" />Technical execution trace
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="mt-3 max-h-[420px] overflow-auto rounded-xl border border-line bg-bg-deep p-4 font-mono text-[11.5px] leading-relaxed text-text-2">
              {events.map((e) => (
                <div key={e.seq} className="whitespace-pre-wrap break-all">
                  <span className="text-muted">#{e.seq} {e.at.slice(11, 19)}</span> <span className="text-signal">{e.type}</span> [{e.stage}] {e.message}
                  {Object.keys(e.data).length > 0 && <span className="text-muted"> {JSON.stringify(e.data).slice(0, 400)}</span>}
                </div>
              ))}
              <div className="mt-3 border-t border-line pt-3 text-muted">
                usage: {JSON.stringify(job.usage)}{"\n"}budgets: {JSON.stringify(job.budgets)}{"\n"}models: {JSON.stringify(job.model_config)}
              </div>
            </div>
          </CollapsibleContent>
        </Collapsible>
      </div>

      {/* Sources + plan */}
      <div className="space-y-6 lg:col-span-2 2xl:col-span-1">
        {job.plan && (
          <Panel className="p-5">
            <h2 className="text-[13px] font-semibold text-text-2">Plan</h2>
            <ol className="mt-3 space-y-2.5">
              {job.plan.subquestions.map((s) => (
                <li key={s.id} className="grid grid-cols-[28px_1fr] gap-2 text-[13.5px]">
                  <span className="text-muted">{s.id}</span>
                  <span className={cn(subq?.id === s.id && running && "text-text", "text-text-2")}>{s.question}</span>
                </li>
              ))}
            </ol>
          </Panel>
        )}
        <Panel className="p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-[13px] font-semibold text-text-2">Sources</h2>
            <span className="text-[12px] text-muted">{run.sources.length} selected{run.rejectedCandidates ? `, ${run.rejectedCandidates} set aside` : ""}</span>
          </div>
          {run.sources.length === 0 ? (
            <div className="mt-4 space-y-2">{running && [0, 1, 2].map((i) => <div key={i} className="skeleton h-14 rounded-lg" />)}</div>
          ) : (
            <ul className="mt-3 space-y-2">
              <AnimatePresence initial={false}>
                {run.sources.map((s) => {
                  const href = safeHref(s.url);
                  return (
                    <motion.li key={s.number} layout initial={reduce ? false : { opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }}
                      className={cn("rounded-lg border px-3 py-2.5", s.state === "inaccessible" ? "border-line bg-surface-2/50 opacity-70" : "border-line bg-surface")}>
                      <div className="flex items-start gap-2">
                        <span className={cn("mt-0.5 rounded px-1.5 text-[11px] font-semibold", s.state === "read" ? "bg-lamp-soft text-lamp-ink" : "bg-surface-2 text-muted")}>{s.number}</span>
                        <div className="min-w-0 flex-1">
                          <p className="line-clamp-2 text-[13px] leading-snug">{s.title}</p>
                          <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11.5px] text-muted">
                            {s.url.startsWith("upload://") ? <span>Your document</span> : <span className="flex items-center gap-1"><Globe className="size-3" />{s.domain || hostname(s.url)}</span>}
                            {s.state === "found" && <span>queued to read</span>}
                            {s.state === "read" && <span>{formatNumber(s.words)} words{s.contentKind === "abstract" ? ", abstract only" : ""}</span>}
                            {s.verified !== undefined && <span className="text-ok">{s.verified} verified</span>}
                            {!!s.discarded && <span className="text-warn">{s.discarded} discarded</span>}
                          </p>
                          {s.state === "inaccessible" && <p className="mt-1 flex items-center gap-1 text-[11.5px] text-warn"><FileWarning className="size-3" />Couldn&apos;t access: {s.reason}</p>}
                          {s.injection && <p className="mt-1 flex items-center gap-1 text-[11.5px] text-warn"><ShieldAlert className="size-3" />Instruction-like text, treated as data</p>}
                        </div>
                        {href && <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-muted hover:text-text" aria-label={`Open source ${s.number}`}><ExternalLink className="size-3.5" /></a>}
                      </div>
                    </motion.li>
                  );
                })}
              </AnimatePresence>
            </ul>
          )}
        </Panel>
        <Panel className="p-5">
          <h2 className="text-[13px] font-semibold text-text-2">Usage so far</h2>
          <dl className="mt-3 grid grid-cols-2 gap-y-2 text-[13px]">
            <dt className="text-muted">Model calls</dt><dd className="text-right tabular-nums">{formatNumber(job.usage.llm_calls)}</dd>
            <dt className="text-muted">Output tokens</dt><dd className="text-right tabular-nums">{formatNumber(job.usage.output_tokens)} / {formatNumber(job.budgets.max_output_tokens)}</dd>
            <dt className="text-muted">Searches</dt><dd className="text-right tabular-nums">{formatNumber(job.usage.search_calls)} / {formatNumber(job.budgets.max_search_calls)}</dd>
            <dt className="text-muted">Pages read</dt><dd className="text-right tabular-nums">{formatNumber(job.usage.extracted_pages)}</dd>
            <dt className="text-muted">Retries</dt><dd className="text-right tabular-nums">{job.attempts}</dd>
          </dl>
          {job.model_config?.synthesis && <p className="mt-3 flex items-center gap-1.5 text-[12px] text-muted"><Search className="size-3" />Writing with {job.model_config.synthesis.model}</p>}
        </Panel>
      </div>
    </div>
  );
}
