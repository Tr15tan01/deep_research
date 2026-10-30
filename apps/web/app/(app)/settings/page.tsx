"use client";

import { useState } from "react";
import { toast } from "sonner";

import { useSession } from "@/components/providers";
import { Badge, Button, Dialog, DialogContent, Field, Input, Panel } from "@/components/ui/primitives";
import { api, downloadFile, errorMessage } from "@/lib/api";
import { formatDate } from "@/lib/utils";

export default function AccountPage() {
  const { user, reloadUser } = useSession();
  const [name, setName] = useState(user?.name ?? "");
  const [busy, setBusy] = useState(false);
  const [del, setDel] = useState(false);
  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  if (!user) return null;

  return (
    <div className="space-y-6">
      <Panel className="p-6">
        <h2 className="text-lg font-semibold">Profile</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <Field label="Name" htmlFor="name"><Input id="name" value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Email" htmlFor="email" hint={user.email_verified ? undefined : "Not verified yet"}>
            <div className="flex items-center gap-2"><Input id="email" value={user.email} disabled />{user.email_verified && <Badge tone="ok">Verified</Badge>}</div>
          </Field>
        </div>
        <p className="mt-3 text-[13px] text-muted">Member since {formatDate(user.created_at)}. Role: {user.role.toLowerCase().replace("_", " ")}.</p>
        <Button className="mt-4" loading={busy} disabled={name === user.name} onClick={async () => {
          setBusy(true);
          try { await api("/api/v1/account/profile", { method: "PATCH", json: { name } }); await reloadUser(); toast.success("Profile saved"); }
          catch (e) { toast.error(errorMessage(e)); } finally { setBusy(false); }
        }}>Save profile</Button>
      </Panel>

      <Panel className="p-6">
        <h2 className="text-lg font-semibold">Your data</h2>
        <p className="mt-1 text-sm text-text-2">Download everything we store about your account — reports, sources, evidence, usage and sign-in history — as JSON.</p>
        <Button variant="secondary" className="mt-4" onClick={() => downloadFile("/api/v1/account/export", "deep-research-export.json").catch((e) => toast.error(errorMessage(e)))}>Export my data</Button>
      </Panel>

      <Panel className="border-danger/30 p-6">
        <h2 className="text-lg font-semibold text-danger">Delete account</h2>
        <p className="mt-1 text-sm text-text-2">Permanently deletes your account, reports, sources, documents and usage records. Running research is stopped. This can&apos;t be undone.</p>
        <Button variant="danger" className="mt-4" onClick={() => setDel(true)}>Delete my account</Button>
      </Panel>

      <Dialog open={del} onOpenChange={setDel}>
        <DialogContent title="Delete your account?" description="Everything will be permanently deleted.">
          <div className="space-y-4">
            {user.has_password && <Field label="Password" htmlFor="dpw"><Input id="dpw" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} /></Field>}
            <Field label='Type DELETE to confirm' htmlFor="dc"><Input id="dc" value={confirm} onChange={(e) => setConfirm(e.target.value)} /></Field>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setDel(false)}>Keep my account</Button>
              <Button variant="danger" disabled={confirm !== "DELETE"} loading={busy} onClick={async () => {
                setBusy(true);
                try { await api("/api/v1/account/delete", { json: { password: pw || null, confirm } }); window.location.replace(new URL("/", window.location.origin).toString()); }
                catch (e) { toast.error(errorMessage(e)); setBusy(false); }
              }}>Delete account permanently</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
