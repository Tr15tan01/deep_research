"use client";

import { FileSearch, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { PageHeader } from "@/components/app/shell";
import { JobRow } from "@/components/research/common";
import { Button, EmptyState, Input, Panel, Select, Skeleton } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api";
import type { Job } from "@/lib/types";

export default function HistoryPage() {
  const [items, setItems] = useState<Job[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");

  async function load(reset: boolean) {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "25" });
      if (q.trim()) params.set("q", q.trim());
      if (status) params.set("status", status);
      if (!reset && cursor) params.set("before", cursor);
      const r = await api<{ items: Job[]; next_cursor: string | null }>(`/api/v1/research?${params}`);
      setItems((prev) => (reset ? r.items : [...prev, ...r.items]));
      setCursor(r.next_cursor);
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const t = setTimeout(() => void load(true), q ? 250 : 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, status]);

  return (
    <>
      <PageHeader title="History" description="Every research run, newest first." actions={<Button asChild variant="signal"><Link href="/research/new">New research</Link></Button>} />
      <div className="mb-4 flex flex-wrap gap-2">
        <div className="relative w-full max-w-[360px]">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
          <Input className="pl-9" placeholder="Search questions" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search questions" />
        </div>
        <Select className="w-auto" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
          <option value="">All</option><option value="active">Running</option><option value="completed">Complete</option>
          <option value="failed">Stopped</option><option value="cancelled">Cancelled</option><option value="awaiting_approval">Waiting for review</option>
        </Select>
      </div>
      {error && <p className="mb-3 text-danger">{error}</p>}
      {loading && !items.length ? <Skeleton className="h-64 w-full" /> : items.length ? (
        <>
          <Panel><ul className="divide-y divide-line">{items.map((j) => <JobRow key={j.id} job={j} />)}</ul></Panel>
          {cursor && <Button variant="secondary" className="mt-4" loading={loading} onClick={() => void load(false)}>Load more</Button>}
        </>
      ) : (
        <EmptyState icon={<FileSearch />} title={q || status ? "No matching research" : "No research yet"}
          action={!q && !status ? <Button asChild><Link href="/research/new">Start research</Link></Button> : undefined}>
          {q || status ? "Try a different search or filter." : "Your reports will appear here."}
        </EmptyState>
      )}
    </>
  );
}
