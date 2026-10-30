"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Input, Panel, Select, Skeleton } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { User } from "@/lib/types";
import { formatDate, relativeTime } from "@/lib/utils";

type AdminUser = User & { status: string; last_login_at?: string; jobs: number };

export default function AdminUsers() {
  const [q, setQ] = useState("");
  const [skip, setSkip] = useState(0);
  const { data, loading, reload } = useApi<{ items: AdminUser[]; total: number }>(`/api/v1/admin/users?limit=50&skip=${skip}${q ? `&q=${encodeURIComponent(q)}` : ""}`, [q, skip]);
  async function update(id: string, body: Record<string, string>) {
    try { await api(`/api/v1/admin/users/${id}`, { method: "PATCH", json: body }); toast.success("User updated; their sessions were signed out"); void reload(); }
    catch (e) { toast.error(errorMessage(e)); }
  }
  return (
    <>
      <Input className="mb-4 max-w-[320px]" placeholder="Search email or name" value={q} onChange={(e) => { setQ(e.target.value); setSkip(0); }} aria-label="Search users" />
      {loading && !data ? <Skeleton className="h-64 w-full" /> : (
        <Panel className="overflow-x-auto">
          <table className="w-full min-w-[820px] text-left text-[13.5px]">
            <thead className="text-[12.5px] text-muted"><tr><th className="px-5 py-2.5 font-medium">User</th><th className="px-3 py-2.5 font-medium">Role</th><th className="px-3 py-2.5 font-medium">Status</th><th className="px-3 py-2.5 font-medium">Research</th><th className="px-3 py-2.5 font-medium">Last sign-in</th><th className="px-5 py-2.5 font-medium">Joined</th></tr></thead>
            <tbody className="divide-y divide-line">
              {data?.items.map((u) => (
                <tr key={u.id}>
                  <td className="px-5 py-2.5"><p className="font-medium">{u.name || "—"}</p><p className="text-[12.5px] text-muted">{u.email} {!u.email_verified && <Badge tone="warn">unverified</Badge>}</p></td>
                  <td className="px-3 py-2.5"><Select aria-label={`Role for ${u.email}`} className="h-8 w-auto text-[13px]" value={u.role} onChange={(e) => void update(u.id, { role: e.target.value })}>
                    <option value="USER">User</option><option value="CONTENT_MANAGER">Content manager</option><option value="ADMIN">Admin</option></Select></td>
                  <td className="px-3 py-2.5">
                    <Button size="sm" variant={u.status === "active" ? "ghost" : "secondary"} onClick={() => void update(u.id, { status: u.status === "active" ? "disabled" : "active" })}>
                      {u.status === "active" ? "Disable" : "Re-enable"}
                    </Button>
                    {u.status !== "active" && <Badge tone="danger" className="ml-1">disabled</Badge>}
                  </td>
                  <td className="px-3 py-2.5 tabular-nums">{u.jobs}</td>
                  <td className="px-3 py-2.5 text-text-2">{u.last_login_at ? relativeTime(u.last_login_at) : "Never"}</td>
                  <td className="px-5 py-2.5 text-text-2">{formatDate(u.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex items-center justify-between border-t border-line px-5 py-3 text-sm text-muted">
            <span>{data?.total ?? 0} users</span>
            <span className="flex gap-2">
              <Button size="sm" variant="ghost" disabled={skip === 0} onClick={() => setSkip(Math.max(0, skip - 50))}>Previous</Button>
              <Button size="sm" variant="ghost" disabled={(data?.total ?? 0) <= skip + 50} onClick={() => setSkip(skip + 50)}>Next</Button>
            </span>
          </div>
        </Panel>
      )}
    </>
  );
}
