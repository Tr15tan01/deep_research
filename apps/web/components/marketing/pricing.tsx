"use client";

import { Check } from "lucide-react";
import Link from "next/link";

import { Button, Skeleton } from "@/components/ui/primitives";
import { useApi } from "@/lib/hooks";
import { formatUsd } from "@/lib/utils";

interface Plan {
  plan: string;
  label: string;
  daily_jobs: number;
  concurrent_jobs: number;
  monthly_cost_usd: number;
  allowed_modes: string[];
  max_uploads_per_job: number;
  purchasable: boolean;
}

export function PricingSection({ standalone = false }: { standalone?: boolean }) {
  const { data, loading } = useApi<{ enabled: boolean; plans: Plan[]; grace_days?: number }>("/api/v1/billing/plans");
  if (loading && standalone) return <div className="mx-auto max-w-[1200px] px-5"><Skeleton className="h-64 w-full" /></div>;
  if (!data?.enabled) {
    return standalone ? (
      <div className="mx-auto max-w-[1200px] px-5 pb-24">
        <p className="max-w-[60ch] text-text-2">
          Paid plans are not enabled on this deployment. Accounts use the usage limits configured by the administrator.
        </p>
        <Button asChild className="mt-6"><Link href="/register">Create an account</Link></Button>
      </div>
    ) : null;
  }
  return (
    <section className="border-t border-line">
      <div className="mx-auto max-w-[1200px] px-5 py-20">
        {!standalone && <h2 className="headline text-[clamp(30px,3.6vw,44px)]">Pricing</h2>}
        <div className="mt-10 grid gap-6 md:grid-cols-2">
          {data.plans.map((p) => (
            <div key={p.plan} className="rounded-2xl border border-line bg-surface p-7">
              <h3 className="headline text-2xl">{p.label}</h3>
              <ul className="mt-5 space-y-2.5 text-[14.5px] text-text-2">
                {[`${p.daily_jobs} research runs per day`, `${p.concurrent_jobs} run(s) at a time`,
                  `Up to ${formatUsd(p.monthly_cost_usd)} of model usage per month (estimated)`,
                  `${p.allowed_modes.length} research modes`, `${p.max_uploads_per_job} documents per run`].map((l) => (
                  <li key={l} className="flex items-start gap-2"><Check className="mt-0.5 size-4 text-ok" aria-hidden />{l}</li>
                ))}
              </ul>
              <Button asChild className="mt-7" variant={p.plan === "free" ? "secondary" : "signal"}>
                <Link href={p.plan === "free" ? "/register" : "/settings/billing"}>{p.plan === "free" ? "Start free" : `Choose ${p.label}`}</Link>
              </Button>
            </div>
          ))}
        </div>
        {data.grace_days ? <p className="mt-6 text-[13px] text-muted">If a payment fails, paid limits continue for {data.grace_days} days while you update your payment method. Your reports are never deleted for non-payment.</p> : null}
      </div>
    </section>
  );
}
