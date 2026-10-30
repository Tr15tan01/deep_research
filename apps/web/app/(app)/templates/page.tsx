"use client";

import { LayoutTemplate, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/shell";
import { useConfig } from "@/components/providers";
import { Badge, Button, Dialog, DialogContent, EmptyState, Field, Input, Panel, Select, Skeleton, Textarea } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Template } from "@/lib/types";

function TemplateItem({ t, onDelete }: { t: Template; onDelete?: () => void }) {
  const config = useConfig();
  const mode = config?.modes.find((m) => m.key === t.mode)?.label ?? t.mode;
  return (
    <li className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <p className="font-medium">{t.name} <Badge className="ml-1">{mode}</Badge></p>
        {t.description && <p className="text-[13.5px] text-text-2">{t.description}</p>}
        <p className="mt-1.5 font-serif text-[15.5px] italic text-muted">“{t.question_template}”</p>
      </div>
      <div className="flex shrink-0 gap-2">
        <Button asChild size="sm" variant="secondary"><Link href={`/research/new?template=${t.id}`}>Use template</Link></Button>
        {onDelete && <Button size="sm" variant="ghost" onClick={onDelete} aria-label={`Delete template ${t.name}`}><Trash2 /></Button>}
      </div>
    </li>
  );
}

export default function TemplatesPage() {
  const config = useConfig();
  const { data, loading, reload } = useApi<{ system: Template[]; mine: Template[] }>("/api/v1/templates");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", question_template: "", mode: "standard", include: "" });
  const [busy, setBusy] = useState(false);

  async function create() {
    setBusy(true);
    try {
      await api("/api/v1/templates", { json: { name: form.name, description: form.description, question_template: form.question_template, mode: form.mode,
        options: form.include ? { include_domains: form.include.split(/[\s,]+/).filter(Boolean) } : {} } });
      toast.success("Template saved");
      setOpen(false);
      setForm({ name: "", description: "", question_template: "", mode: "standard", include: "" });
      void reload();
    } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(false); }
  }

  return (
    <>
      <PageHeader title="Templates" description="Reusable questions with a mode and options. Use {placeholders} for the parts that change."
        actions={<Button onClick={() => setOpen(true)}><Plus />New template</Button>} />
      {loading && !data ? <Skeleton className="h-64 w-full" /> : (
        <div className="space-y-8">
          <section>
            <h2 className="mb-3 text-sm font-semibold text-text-2">Your templates</h2>
            {data?.mine.length ? (
              <Panel><ul className="divide-y divide-line">{data.mine.map((t) => (
                <TemplateItem key={t.id} t={t} onDelete={async () => { try { await api(`/api/v1/templates/${t.id}`, { method: "DELETE" }); void reload(); } catch (e) { toast.error(errorMessage(e)); } }} />
              ))}</ul></Panel>
            ) : <EmptyState icon={<LayoutTemplate />} title="No saved templates" action={<Button variant="secondary" onClick={() => setOpen(true)}>Create a template</Button>}>Save a question pattern you research often.</EmptyState>}
          </section>
          <section>
            <h2 className="mb-3 text-sm font-semibold text-text-2">Starter templates</h2>
            <Panel><ul className="divide-y divide-line">{data?.system.map((t) => <TemplateItem key={t.id} t={t} />)}</ul></Panel>
          </section>
        </div>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title="New template">
          <div className="space-y-4">
            <Field label="Name" htmlFor="tn"><Input id="tn" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="Description" htmlFor="td" hint="Optional"><Input id="td" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
            <Field label="Question" htmlFor="tq" hint="Use {placeholders}, e.g. Compare {vendor A} and {vendor B}"><Textarea id="tq" rows={3} value={form.question_template} onChange={(e) => setForm({ ...form, question_template: e.target.value })} /></Field>
            <Field label="Mode" htmlFor="tm">
              <Select id="tm" value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}>
                {config?.modes.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
              </Select>
            </Field>
            <Field label="Only these domains" htmlFor="ti" hint="Optional, comma-separated"><Input id="ti" value={form.include} onChange={(e) => setForm({ ...form, include: e.target.value })} /></Field>
            <div className="flex justify-end"><Button loading={busy} disabled={form.name.length < 2 || form.question_template.length < 8} onClick={() => void create()}>Save template</Button></div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
