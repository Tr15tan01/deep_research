"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Badge, Button, Notice, Panel, Skeleton } from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { UsageSnapshot } from "@/lib/types";
import { formatDate, formatUsd } from "@/lib/utils";

interface Sub { enabled: boolean; usage: UsageSnapshot; subscription: { status: string; plan: string; current_period_end?: string; grace_until?: string; scheduled_change?: unknown } | null }
interface Plans { enabled: boolean; plans: { plan: string; label: string; purchasable: boolean; daily_jobs: number; monthly_cost_usd: number }[] }

export default function BillingPage() {
  const sub = useApi<Sub>("/api/v1/billing/subscription");
  const plans = useApi<Plans>("/api/v1/billing/plans");
  const [busy, setBusy] = useState<string | null>(null);
  if ((sub.loading && !sub.data) || (plans.loading && !plans.data)) return <Skeleton className="h-64 w-full" />;
  if (!sub.data?.enabled) return <Notice title="Billing is not enabled">This deployment uses administrator-configured usage limits. Nothing to pay here.</Notice>;
  const s = sub.data.subscription;

  async function go(path: string, body?: unknown, key = path) {
    setBusy(key);
    try {
      const r = await api<{ checkout_url?: string; portal_url?: string; message?: string; status?: string }>(`/api/v1/billing/${path}`, { json: body ?? {} });
      if (r.checkout_url || r.portal_url) window.location.href = (r.checkout_url || r.portal_url)!;
      else { toast.success(r.message ?? "Updated"); void sub.reload(); }
    } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(null); }
  }

  return (
    <div className="space-y-6">
      {sub.data.usage.notice && <Notice tone="warn" title="Payment issue">{sub.data.usage.notice} Your reports and data are safe.</Notice>}
      <Panel className="p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">Current plan: {sub.data.usage.plan.label}</h2>
            {s ? (
              <p className="mt-1 text-sm text-text-2">
                Status <Badge tone={s.status === "active" || s.status === "trialing" ? "ok" : s.status === "past_due" ? "warn" : "neutral"}>{s.status.replace("_", " ")}</Badge>
                {s.current_period_end && <> — renews {formatDate(s.current_period_end)}</>}
                {s.grace_until && s.status === "past_due" && <> — paid limits continue until {formatDate(s.grace_until)}</>}
                {!!s.scheduled_change && <> — cancellation scheduled</>}
              </p>
            ) : <p className="mt-1 text-sm text-text-2">You&apos;re on the free plan.</p>}
          </div>
          <div className="flex gap-2">
            {s && <Button variant="secondary" loading={busy === "portal"} onClick={() => void go("portal")}>Manage payment</Button>}
            {s && s.status !== "canceled" && <Button variant="ghost" loading={busy === "cancel"} onClick={() => void go("cancel")}>Cancel plan</Button>}
            {s && <Button variant="ghost" loading={busy === "reconcile"} onClick={() => void go("reconcile")}>Refresh status</Button>}
          </div>
        </div>
        <p className="mt-3 text-[12.5px] text-muted">Plan changes take effect when the payment provider confirms them — usually within a minute. Returning from checkout does not by itself change your plan.</p>
      </Panel>
      <div className="grid gap-4 sm:grid-cols-2">
        {plans.data?.plans.map((p) => (
          <Panel key={p.plan} className="p-6">
            <h3 className="headline text-2xl">{p.label}</h3>
            <p className="mt-2 text-sm text-text-2">{p.daily_jobs} runs per day, {formatUsd(p.monthly_cost_usd)} of model usage per month (estimated).</p>
            {p.plan !== "free" && p.purchasable && sub.data?.usage.plan.plan !== p.plan && (
              <Button className="mt-4" variant="signal" loading={busy === `checkout-${p.plan}`} onClick={() => void go("checkout", { plan: p.plan }, `checkout-${p.plan}`)}>Upgrade to {p.label}</Button>
            )}
            {sub.data?.usage.plan.plan === p.plan && <Badge tone="ok" className="mt-4">Current plan</Badge>}
          </Panel>
        ))}
      </div>
    </div>
  );
}
