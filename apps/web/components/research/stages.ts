import {
  BookOpenText,
  ChartColumn,
  FileSearch,
  GitCompareArrows,
  Lightbulb,
  ListTree,
  type LucideIcon,
  PenLine,
  ScanSearch,
  ShieldCheck,
} from "lucide-react";

export interface StageDef {
  key: string;
  label: string;
  verb: string;
  icon: LucideIcon;
}

// Ordered as the pipeline actually executes (writing happens before claim verification).
export const STAGES: StageDef[] = [
  { key: "understanding", label: "Understanding the question", verb: "Reading your question", icon: Lightbulb },
  { key: "planning", label: "Creating the research plan", verb: "Planning sub-questions", icon: ListTree },
  { key: "searching", label: "Searching the web", verb: "Searching", icon: ScanSearch },
  { key: "reading", label: "Reading sources", verb: "Reading sources", icon: BookOpenText },
  { key: "comparing", label: "Comparing evidence", verb: "Extracting and checking quotes", icon: GitCompareArrows },
  { key: "gaps", label: "Identifying gaps", verb: "Looking for gaps and contradictions", icon: FileSearch },
  { key: "writing", label: "Writing the report", verb: "Writing", icon: PenLine },
  { key: "verifying", label: "Verifying claims", verb: "Checking claims against their sources", icon: ShieldCheck },
  { key: "visualizing", label: "Generating visualizations", verb: "Building charts from verified data", icon: ChartColumn },
];

export const STAGE_INDEX = Object.fromEntries(STAGES.map((s, i) => [s.key, i])) as Record<string, number>;

export const STATUS_LABEL: Record<string, string> = {
  queued: "Queued",
  planning: "Planning",
  awaiting_approval: "Waiting for your review",
  searching: "Searching",
  extracting: "Reading",
  verifying: "Verifying",
  synthesizing: "Writing",
  completed: "Complete",
  failed: "Stopped",
  cancelled: "Cancelled",
  waiting_for_retry: "Retrying soon",
};
