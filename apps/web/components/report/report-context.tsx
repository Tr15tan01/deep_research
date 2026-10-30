"use client";

import { createContext, useContext } from "react";

import type { Source } from "@/lib/types";

export interface Focus {
  sourceNumber: number;
  evidenceIds: string[];
  context?: string;
}

export interface ReportCtx {
  jobId: string;
  sourcesByNumber: Map<number, Source>;
  open: (f: Focus) => void;
}

export const ReportContext = createContext<ReportCtx | null>(null);

export function useReport(): ReportCtx {
  const v = useContext(ReportContext);
  if (!v) throw new Error("useReport outside ReportContext");
  return v;
}
