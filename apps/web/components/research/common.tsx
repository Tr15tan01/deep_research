"use client";

import { AlertTriangle, CheckCircle2, CircleSlash, Clock, Loader2, PauseCircle, RefreshCw } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/primitives";
import type { Job } from "@/lib/types";
import { cn, relativeTime } from "@/lib/utils";

import { STATUS_LABEL } from "./stages";

export function StatusBadge({ status, partial }: { status: Job["status"]; partial?: boolean }) {
  const label = partial && status !== "completed" ? `${STATUS_LABEL[status] ?? status} · partial results` : STATUS_LABEL[status] ?? status;
  if (status === "completed") return <Badge tone="ok"><CheckCircle2 className="size-3.5" />{label}</Badge>;
  if (status === "failed") return <Badge tone="danger"><AlertTriangle className="size-3.5" />{label}</Badge>;
  if (status === "cancelled") return <Badge tone="neutral"><CircleSlash className="size-3.5" />{label}</Badge>;
  if (status === "awaiting_approval") return <Badge tone="lamp"><PauseCircle className="size-3.5" />{label}</Badge>;
  if (status === "waiting_for_retry") return <Badge tone="warn"><RefreshCw className="size-3.5" />{label}</Badge>;
  if (status === "queued") return <Badge tone="neutral"><Clock className="size-3.5" />{label}</Badge>;
  return <Badge tone="signal"><Loader2 className="size-3.5 animate-spin" />{label}</Badge>;
}

export function JobRow({ job, compact }: { job: Job; compact?: boolean }) {
  return (
    <li>
      <Link href={`/research/${job.id}`}
        className="group grid gap-1.5 px-4 py-3.5 transition-colors hover:bg-surface-2 sm:grid-cols-[1fr_auto] sm:items-center sm:gap-6">
        <div className="min-w-0">
          <p className={cn("truncate font-serif text-[17px] leading-snug text-text group-hover:text-text", compact && "text-[16px]")}>
            {job.title || job.question}
          </p>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-muted">
            <span>{job.mode_label}</span>
            <span>{relativeTime(job.created_at)}</span>
            {job.is_demo && <span className="text-lamp">Demo data</span>}
            {job.report_version && job.report_version > 1 && <span>Version {job.report_version}</span>}
          </p>
        </div>
        <StatusBadge status={job.status} partial={job.partial} />
      </Link>
    </li>
  );
}
