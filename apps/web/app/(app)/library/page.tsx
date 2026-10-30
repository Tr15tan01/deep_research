"use client";

import { BookMarked, ExternalLink, FileText, Globe, Plus, Tag, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/shell";
import { Badge, Button, Dialog, DialogContent, EmptyState, Field, Input, Panel, Select, Skeleton } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { cn, formatDate, safeHref } from "@/lib/utils";

interface Item { id: string; kind: "report" | "source"; ref_id: string; job_id?: string; title: string; url?: string; domain?: string; tags: string[]; collection_ids: string[]; note: string; created_at: string; source_type?: string; published_at?: string; duplicates?: string[] }
interface Lib { items: Item[]; collections: { id: string; name: string; description: string }[]; tags: string[] }

export default function LibraryPage() {
  const [q, setQ] = useState("");
  const [tag, setTag] = useState("");
  const [colId, setColId] = useState("");
  const [kind, setKind] = useState("");
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (tag) params.set("tag", tag);
  if (colId) params.set("collection_id", colId);
  if (kind) params.set("kind", kind);
  const { data, loading, reload } = useApi<Lib>(`/api/v1/library?${params}`, [q, tag, colId, kind]);
  const [newCol, setNewCol] = useState(false);
  const [colName, setColName] = useState("");
  const [editing, setEditing] = useState<Item | null>(null);
  const [tagsText, setTagsText] = useState("");

  async function addCollection() {
    try { await api("/api/v1/library/collections", { json: { name: colName } }); setColName(""); setNewCol(false); void reload(); }
    catch (e) { toast.error(errorMessage(e)); }
  }
  async function saveItem(it: Item, patch: Partial<Item>) {
    try { await api(`/api/v1/library/items/${it.id}`, { method: "PATCH", json: patch }); void reload(); }
    catch (e) { toast.error(errorMessage(e)); }
  }

  return (
    <>
      <PageHeader title="Library" description="Reports and sources you've saved, organised into collections and tags." />
      <div className="grid gap-6 lg:grid-cols-[220px_1fr]">
        <aside className="space-y-4">
          <div>
            <div className="mb-2 flex items-center justify-between"><h2 className="text-sm font-semibold text-text-2">Collections</h2>
              <button className="rounded p-1 text-muted hover:text-text" onClick={() => setNewCol(true)} aria-label="New collection"><Plus className="size-4" /></button></div>
            <ul className="space-y-0.5 text-sm">
              <li><button className={cn("w-full rounded-lg px-2.5 py-1.5 text-left", !colId ? "bg-surface-2 text-text" : "text-text-2 hover:bg-surface-2")} onClick={() => setColId("")}>Everything</button></li>
              {data?.collections.map((c) => (
                <li key={c.id} className="group flex items-center">
                  <button className={cn("flex-1 rounded-lg px-2.5 py-1.5 text-left", colId === c.id ? "bg-surface-2 text-text" : "text-text-2 hover:bg-surface-2")} onClick={() => setColId(c.id)}>{c.name}</button>
                  <button className="p-1 text-muted opacity-0 hover:text-danger group-hover:opacity-100" aria-label={`Delete collection ${c.name}`}
                    onClick={async () => { await api(`/api/v1/library/collections/${c.id}`, { method: "DELETE" }); if (colId === c.id) setColId(""); void reload(); }}><Trash2 className="size-3.5" /></button>
                </li>
              ))}
            </ul>
          </div>
          {!!data?.tags.length && (
            <div>
              <h2 className="mb-2 text-sm font-semibold text-text-2">Tags</h2>
              <div className="flex flex-wrap gap-1.5">{data.tags.map((t) => (
                <button key={t} onClick={() => setTag(tag === t ? "" : t)} aria-pressed={tag === t}
                  className={cn("rounded-full border px-2 py-0.5 text-[12px]", tag === t ? "border-signal bg-signal-soft" : "border-line text-text-2")}>{t}</button>
              ))}</div>
            </div>
          )}
        </aside>
        <div>
          <div className="mb-4 flex flex-wrap gap-2">
            <Input className="max-w-[320px]" placeholder="Search titles, notes, tags" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search library" />
            <Select className="w-auto" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Type"><option value="">Reports and sources</option><option value="report">Reports</option><option value="source">Sources</option></Select>
          </div>
          {loading && !data ? <Skeleton className="h-64 w-full" /> : data?.items.length ? (
            <Panel><ul className="divide-y divide-line">
              {data.items.map((it) => {
                const href = it.kind === "report" ? `/research/${it.ref_id}` : safeHref(it.url);
                return (
                  <li key={it.id} className="flex flex-col gap-2 px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <p className="flex items-center gap-2 font-medium">
                        {it.kind === "report" ? <FileText className="size-4 text-muted" /> : <Globe className="size-4 text-muted" />}
                        {it.kind === "report" ? <Link href={href ?? "#"} className="hover:underline">{it.title}</Link> : <span>{it.title}</span>}
                      </p>
                      <p className="mt-0.5 text-[12.5px] text-muted">
                        {it.kind === "source" && <>{it.domain}{it.published_at ? `, ${formatDate(it.published_at)}` : ""}{it.source_type ? `, ${it.source_type}` : ""}{it.duplicates?.length ? `, also cited in ${it.duplicates.length} other report(s)` : ""} — </>}
                        saved {formatDate(it.created_at)}
                      </p>
                      <div className="mt-1.5 flex flex-wrap gap-1">{it.tags.map((t) => <Badge key={t}>{t}</Badge>)}
                        {it.collection_ids.map((c) => <Badge key={c} tone="signal">{data.collections.find((x) => x.id === c)?.name}</Badge>)}</div>
                      {it.note && <p className="mt-1.5 text-[13.5px] text-text-2">{it.note}</p>}
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      {it.kind === "source" && href && <Button asChild size="icon" variant="ghost"><a href={href} target="_blank" rel="noopener noreferrer nofollow" aria-label="Open source"><ExternalLink /></a></Button>}
                      {it.kind === "source" && it.job_id && <Button asChild size="sm" variant="ghost"><Link href={`/research/${it.job_id}`}>Report</Link></Button>}
                      <Button size="icon" variant="ghost" aria-label="Edit tags" onClick={() => { setEditing(it); setTagsText(it.tags.join(", ")); }}><Tag /></Button>
                      <Button size="icon" variant="ghost" aria-label="Remove from library" onClick={async () => { await api(`/api/v1/library/items/${it.id}`, { method: "DELETE" }); void reload(); }}><Trash2 /></Button>
                    </div>
                  </li>
                );
              })}
            </ul></Panel>
          ) : (
            <EmptyState icon={<BookMarked />} title={q || tag || colId ? "Nothing matches" : "Your library is empty"}>
              {q || tag || colId ? "Try another filter." : "Use “Save to library” on a report, or “Save source” in a report's source list."}
            </EmptyState>
          )}
        </div>
      </div>
      <Dialog open={newCol} onOpenChange={setNewCol}>
        <DialogContent title="New collection">
          <Field label="Name" htmlFor="cn"><Input id="cn" value={colName} onChange={(e) => setColName(e.target.value)} /></Field>
          <div className="mt-4 flex justify-end"><Button disabled={!colName.trim()} onClick={() => void addCollection()}>Create collection</Button></div>
        </DialogContent>
      </Dialog>
      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent title="Organise item" description={editing?.title}>
          {editing && (
            <div className="space-y-4">
              <Field label="Tags" htmlFor="tg" hint="Comma-separated"><Input id="tg" value={tagsText} onChange={(e) => setTagsText(e.target.value)} /></Field>
              <fieldset><legend className="mb-2 text-[13px] font-medium text-text-2">Collections</legend>
                <div className="space-y-1.5">{data?.collections.map((c) => (
                  <label key={c.id} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" className="accent-[var(--signal)]" checked={editing.collection_ids.includes(c.id)}
                      onChange={(e) => setEditing({ ...editing, collection_ids: e.target.checked ? [...editing.collection_ids, c.id] : editing.collection_ids.filter((x) => x !== c.id) })} />{c.name}
                  </label>
                ))}{!data?.collections.length && <p className="text-sm text-muted">No collections yet.</p>}</div>
              </fieldset>
              <div className="flex justify-end"><Button onClick={() => { void saveItem(editing, { tags: tagsText.split(",").map((t) => t.trim()).filter(Boolean), collection_ids: editing.collection_ids }); setEditing(null); }}>Save</Button></div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
