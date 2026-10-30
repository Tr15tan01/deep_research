"use client";

import { ArrowLeft, Ban, Library, Play, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { useConfig } from "@/components/providers";
import { PlanReview } from "@/components/research/plan-review";
import { StatusBadge } from "@/components/research/common";
import { ConnectionPill, RunView } from "@/components/research/run-view";
import { ReportView } from "@/components/report/report-view";
import { Button, Dialog, DialogContent, Notice, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useJobEvents } from "@/lib/hooks";
import type { Report } from "@/lib/types";
import { formatDate, relativeTime } from "@/lib/utils";

export default function ResearchPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const { events, job, conn, loadError, refreshJob, reconnect } = useJobEvents(id);
  const config = useConfig();
  const [report, setReport] = useState<Report | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);
  const [tab, setTab] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const loadReport = useCallback(async (version?: number) => {
    try {
      const r = await api<{ report: Report }>(`/api/v1/research/${id}/report${version ? `?version=${version}` : ""}`);
      setReport(r.report);
      setReportError(null);
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 404)) setReportError(errorMessage(e));
    }
  }, [id]);

  const reportId = job?.report_id;
  const reportVersion = job?.report_version;
  useEffect(() => { if (reportId) void loadReport(); }, [reportId, reportVersion, loadReport]);

  // Child jobs (exports / regenerations) belong to their parent research.
  useEffect(() => {
    if (job && job.kind !== "research" && job.parent_job_id) router.replace(`/research/${job.parent_job_id}`);
  }, [job, router]);

  useEffect(() => {
    if (tab || !job) return;
    if (job.status === "awaiting_approval") setTab("run");
    else if (reportId && ["completed", "failed", "cancelled"].includes(job.status)) setTab("report");
    else if (!reportId) setTab("run");
  }, [job, reportId, tab]);

  // Switch to the report automatically when a run finishes while being watched.
  useEffect(() => {
    if (job?.status === "completed" && reportId && tab === "run" && events.some((e) => e.type === "completed")) setTab("report");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status, reportId]);

  async function act(kind: "cancel" | "resume") {
    setBusy(kind);
    try {
      await api(`/api/v1/research/${id}/${kind}`, { method: "POST" });
      toast.success(kind === "cancel" ? "Cancellation requested — partial results will be kept" : "Resuming from the last checkpoint");
      await refreshJob();
      if (kind === "resume") { setTab("run"); reconnect(); }
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  async function del() {
    setBusy("delete");
    try {
      await api(`/api/v1/research/${id}`, { method: "DELETE" });
      toast.success("Research deleted");
      router.replace("/history");
    } catch (e) {
      toast.error(errorMessage(e));
      setBusy(null);
    }
  }

  if (loadError) {
    const notFound = loadError instanceof ApiError && loadError.status === 404;
    return (
      <Notice tone={notFound ? "neutral" : "danger"} title={notFound ? "Research not found" : "Couldn't load this research"}
        action={<Button asChild variant="secondary" size="sm"><Link href="/history">Back to history</Link></Button>}>
        {notFound ? "It may have been deleted, or it belongs to another account." : errorMessage(loadError)}
        {loadError instanceof ApiError && loadError.referenceId && <span className="block text-[12px]">Reference: {loadError.referenceId}</span>}
      </Notice>
    );
  }
  if (!job) return <div className="space-y-4"><Skeleton className="h-10 w-2/3" /><Skeleton className="h-6 w-1/3" /><Skeleton className="h-[420px] w-full" /></div>;

  const running = !["completed", "failed", "cancelled", "awaiting_approval"].includes(job.status);

  return (
    <>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3 no-print">
        <Link href="/history" className="flex items-center gap-1.5 text-sm text-muted hover:text-text"><ArrowLeft className="size-4" />History</Link>
        <div className="flex flex-wrap items-center gap-2">
          <ConnectionPill conn={conn} onReconnect={reconnect} />
          <StatusBadge status={job.status} partial={job.partial} />
          {(running || job.status === "awaiting_approval") && !job.cancel_requested && (
            <Button size="sm" variant="secondary" loading={busy === "cancel"} onClick={() => void act("cancel")}><Ban />Cancel</Button>
          )}
          {(job.resumable || job.status === "waiting_for_retry") && (
            <Button size="sm" variant="signal" loading={busy === "resume"} onClick={() => void act("resume")}><Play />{job.status === "waiting_for_retry" ? "Retry now" : "Resume"}</Button>
          )}
          {!running && <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(true)} aria-label="Delete research"><Trash2 /></Button>}
        </div>
      </div>

      {(!report || tab !== "report") && (
        <div className="mb-6">
          <h1 className="display max-w-[30ch] text-[clamp(28px,3.4vw,42px)]">{job.title || job.question}</h1>
          <p className="mt-2 text-[13px] text-muted">{job.mode_label}, started {relativeTime(job.created_at)}{job.parent_job_id && <> — follow-up of <Link className="text-signal hover:underline" href={`/research/${job.parent_job_id}`}>an earlier report</Link></>}</p>
        </div>
      )}

      <div className="mb-6 space-y-2 no-print">
        {job.is_demo && !report && !config?.features.demo_mode && <Notice tone="lamp">Demo mode: synthetic sources and a deterministic demo model.</Notice>}
        {job.status === "waiting_for_retry" && (
          <Notice tone="warn" title="Temporarily paused">
            {job.last_error?.message} Next automatic attempt {job.next_attempt_at ? `at ${formatDate(job.next_attempt_at, { timeStyle: "short" })}` : "soon"} (attempt {job.attempts + 1}). Progress so far is saved.
          </Notice>
        )}
        {job.status === "failed" && (
          <Notice tone="danger" title="Research stopped"
            action={report ? <Button size="sm" variant="secondary" onClick={() => setTab("report")}>View partial findings</Button> : undefined}>
            {job.last_error?.message}{job.dead_lettered ? " Automatic retries are exhausted." : ""}
            {job.resumable ? " Fix the cause, then resume — it will continue from the last checkpoint." : ""}
            {job.last_error?.at && <span className="block text-[12px] text-muted">{formatDate(job.last_error.at, { dateStyle: "medium", timeStyle: "short" })}{job.last_error.code ? `, code ${job.last_error.code}` : ""}</span>}
          </Notice>
        )}
        {job.status === "cancelled" && <Notice title="Cancelled">{report ? "Findings gathered before cancellation are kept as a partial report." : "No findings had been verified yet."}</Notice>}
        {!!job.fallbacks.length && <Notice tone="signal" title="A fallback model was used">{job.fallbacks.map((f) => `${f.task}: ${f.from} → ${f.to} (${f.reason.replace(/_/g, " ")})`).join("; ")}</Notice>}
        {reportError && <Notice tone="danger">{reportError}</Notice>}
      </div>

      {job.status === "awaiting_approval" ? (
        <PlanReview job={job} onApproved={() => { void refreshJob(); reconnect(); }} />
      ) : (
        <Tabs value={tab ?? "run"} onValueChange={setTab}>
          {report && (
            <div className="mb-6 flex items-center justify-between gap-3 no-print">
              <TabsList>
                <TabsTrigger value="report">Report</TabsTrigger>
                <TabsTrigger value="run">Execution</TabsTrigger>
              </TabsList>
              <Button asChild size="sm" variant="ghost"><Link href={`/research/${id}/sources`}><Library />All sources and evidence</Link></Button>
            </div>
          )}
          <TabsContent value="run"><RunView job={job} events={events} /></TabsContent>
          {report && <TabsContent value="report"><ReportView job={job} report={report} reload={(v) => void loadReport(v)} /></TabsContent>}
        </Tabs>
      )}

      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent title="Delete this research?" description="The report, all versions, sources and evidence will be permanently deleted.">
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirmDelete(false)}>Keep it</Button>
            <Button variant="danger" loading={busy === "delete"} onClick={() => void del()}>Delete research</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
