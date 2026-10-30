"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { PageHeader } from "@/components/app/shell";
import { useConfig } from "@/components/providers";
import { cn } from "@/lib/utils";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const config = useConfig();
  const tabs = [
    ["/settings", "Account"], ["/settings/security", "Security"], ["/settings/usage", "Usage"],
    ...(config?.features.user_model_selection || config?.features.user_api_keys ? [["/settings/providers", "Models and keys"]] : []),
    ...(config?.features.billing ? [["/settings/billing", "Billing"]] : []),
  ] as [string, string][];
  return (
    <>
      <PageHeader title="Settings" />
      <nav aria-label="Settings" className="mb-8 flex gap-1 overflow-x-auto border-b border-line">
        {tabs.map(([href, label]) => (
          <Link key={href} href={href} aria-current={path === href ? "page" : undefined}
            className={cn("-mb-px whitespace-nowrap border-b-2 px-3 py-2.5 text-sm", path === href ? "border-signal text-text" : "border-transparent text-muted hover:text-text")}>
            {label}
          </Link>
        ))}
      </nav>
      <div className="max-w-[860px]">{children}</div>
    </>
  );
}
