"use client";

import { FileText, Loader2, ShieldAlert, Trash2, UploadCloud } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { useConfig } from "@/components/providers";
import { api, errorMessage } from "@/lib/api";
import type { Upload } from "@/lib/types";
import { cn, formatBytes } from "@/lib/utils";

const ACCEPT = ".pdf,.docx,.txt,.md,.markdown";

export function Uploader({ selected, onChange, existing, onUploaded }: {
  selected: string[];
  onChange: (ids: string[]) => void;
  existing: Upload[];
  onUploaded: (u: Upload) => void;
}) {
  const config = useConfig();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<string[]>([]);
  const [drag, setDrag] = useState(false);
  const maxMb = config?.limits.max_file_size_mb ?? 20;
  const maxCount = config?.limits.max_uploads_per_job ?? 10;

  async function upload(files: FileList | File[]) {
    for (const f of Array.from(files)) {
      if (f.size > maxMb * 1024 * 1024) { toast.error(`${f.name} is larger than ${maxMb} MB.`); continue; }
      setBusy((b) => [...b, f.name]);
      try {
        const fd = new FormData();
        fd.append("file", f);
        const r = await api<{ upload: Upload }>("/api/v1/uploads", { method: "POST", body: fd });
        onUploaded(r.upload);
        if (selected.length < maxCount) onChange([...selected, r.upload.id]);
        if (r.upload.injection_suspected) toast.warning(`${f.name} contains instruction-like text. It will be treated strictly as data.`);
      } catch (e) {
        toast.error(`${f.name}: ${errorMessage(e)}`);
      } finally {
        setBusy((b) => b.filter((n) => n !== f.name));
      }
    }
  }

  const ready = existing.filter((u) => u.status === "ready");
  return (
    <div className="space-y-3">
      <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); void upload(e.dataTransfer.files); }}
        className={cn("flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-4 py-6 text-center transition-colors",
          drag ? "border-signal bg-signal-soft" : "border-line-strong bg-surface-2")}>
        <UploadCloud className="size-6 text-muted" aria-hidden />
        <p className="text-sm text-text-2">Drop PDF, DOCX, TXT or Markdown files, or{" "}
          <button type="button" className="text-signal underline-offset-4 hover:underline" onClick={() => input.current?.click()}>browse</button>
        </p>
        <p className="text-[12px] text-muted">Up to {maxMb} MB each, {maxCount} per research. Parsed in an isolated sandbox.</p>
        <input ref={input} type="file" accept={ACCEPT} multiple className="sr-only" onChange={(e) => { if (e.target.files) void upload(e.target.files); e.target.value = ""; }} />
      </div>
      {busy.map((n) => (
        <p key={n} className="flex items-center gap-2 text-sm text-muted"><Loader2 className="size-4 animate-spin" />Reading {n}…</p>
      ))}
      {!!ready.length && (
        <ul className="divide-y divide-line rounded-xl border border-line">
          {ready.map((u) => {
            const on = selected.includes(u.id);
            return (
              <li key={u.id} className="flex items-center gap-3 px-3 py-2.5">
                <input id={`up-${u.id}`} type="checkbox" checked={on} disabled={!on && selected.length >= maxCount}
                  onChange={() => onChange(on ? selected.filter((s) => s !== u.id) : [...selected, u.id])}
                  className="size-4 accent-[var(--signal)]" />
                <label htmlFor={`up-${u.id}`} className="flex min-w-0 flex-1 items-center gap-2 text-sm">
                  <FileText className="size-4 shrink-0 text-muted" aria-hidden />
                  <span className="truncate">{u.filename}</span>
                  <span className="shrink-0 text-[12px] text-muted">{formatBytes(u.size)}{u.pages ? `, ${u.pages} pages` : ""}</span>
                  {u.injection_suspected && <ShieldAlert className="size-4 shrink-0 text-warn" aria-label="Contains instruction-like text" />}
                </label>
                <button type="button" aria-label={`Delete ${u.filename}`} className="rounded p-1 text-muted hover:text-danger"
                  onClick={async () => {
                    try { await api(`/api/v1/uploads/${u.id}`, { method: "DELETE" }); onChange(selected.filter((s) => s !== u.id)); onUploaded({ ...u, status: "failed" }); }
                    catch (e) { toast.error(errorMessage(e)); }
                  }}>
                  <Trash2 className="size-4" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
