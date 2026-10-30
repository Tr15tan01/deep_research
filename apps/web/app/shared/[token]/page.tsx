"use client";

import { use, useMemo, useState } from "react";

import { Logo } from "@/components/brand";
import { ParagraphView } from "@/components/report/paragraph";
import { ReportContext } from "@/components/report/report-context";
import { Notice, Skeleton } from "@/components/ui/primitives";
import { errorMessage } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Report, Source } from "@/lib/types";
import { formatDate, safeHref } from "@/lib/utils";

export default function SharedReport({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const { data, error } = useApi<{ report: Report }>(`/api/v1/shared/${token}`);
  const [, setFocus] = useState<number | null>(null);
  const byNumber = useMemo(() => new Map((data?.report.bibliography ?? []).map((b) => [b.number, { ...b, id: String(b.number), domain: b.domain ?? "" } as unknown as Source])), [data]);
  const r = data?.report;
  return (
    <ReportContext.Provider value={{ jobId: "", sourcesByNumber: byNumber, open: (f) => { setFocus(f.sourceNumber); document.getElementById(`src-${f.sourceNumber}`)?.scrollIntoView({ behavior: "smooth" }); } }}>
      <header className="mx-auto flex h-16 max-w-[900px] items-center px-5"><Logo /></header>
      <main id="main" className="mx-auto max-w-[900px] px-5 pb-24">
        {error ? <Notice tone="danger">{errorMessage(error)}</Notice> : !r ? <Skeleton className="h-96 w-full" /> : (
          <article>
            {r.is_demo && <Notice tone="lamp" className="mb-4">Demo report generated from synthetic sources.</Notice>}
            {r.status === "partial" && <Notice tone="warn" className="mb-4">Partial report: {r.partial_reason}</Notice>}
            <h1 className="display text-[44px]">{r.title}</h1>
            <p className="mt-3 text-text-2">{r.question}</p>
            <p className="mt-2 text-[13px] text-muted">Shared report, version {r.version}, generated {formatDate(r.created_at)}</p>
            <h2 className="headline mt-10 border-b border-line pb-2 text-2xl">Executive summary</h2>
            <div className="prose-report mt-4">{r.executive_summary.map((p) => <ParagraphView key={p.id} p={p} />)}</div>
            {r.sections.map((s) => (
              <section key={s.id}><h2 className="headline mt-10 border-b border-line pb-2 text-2xl">{s.title}</h2>
                <div className="prose-report mt-4">{s.paragraphs.map((p) => <ParagraphView key={p.id} p={p} />)}</div></section>
            ))}
            <h2 className="headline mt-10 border-b border-line pb-2 text-2xl">Sources</h2>
            <ol className="mt-4 space-y-2 text-[14px]">{r.bibliography.map((b) => {
              const href = safeHref(b.url);
              return <li key={b.number} id={`src-${b.number}`}>[{b.number}] {href ? <a className="text-signal hover:underline" href={href} target="_blank" rel="noopener noreferrer nofollow">{b.title}</a> : b.title} <span className="text-muted">{b.domain}</span></li>;
            })}</ol>
          </article>
        )}
      </main>
    </ReportContext.Provider>
  );
}
