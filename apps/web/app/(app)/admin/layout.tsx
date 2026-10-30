"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { PageHeader } from "@/components/app/shell";
import { useSession } from "@/components/providers";
import { Notice } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

const TABS: [string, string][] = [["/admin", "Overview"], ["/admin/providers", "AI providers"], ["/admin/users", "Users"], ["/admin/usage", "Usage"], ["/admin/jobs", "Jobs"], ["/admin/system-health", "System health"]];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { user } = useSession();
  const path = usePathname();
  if (user?.role !== "ADMIN") return <Notice tone="danger" title="Administrators only">You don&apos;t have access to this area.</Notice>;
  return (
    <>
      <PageHeader title="Administration" />
      <nav aria-label="Admin" className="mb-8 flex gap-1 overflow-x-auto border-b border-line">
        {TABS.map(([href, label]) => (
          <Link key={href} href={href} aria-current={path === href ? "page" : undefined}
            className={cn("-mb-px whitespace-nowrap border-b-2 px-3 py-2.5 text-sm", path === href ? "border-signal text-text" : "border-transparent text-muted hover:text-text")}>{label}</Link>
        ))}
      </nav>
      {children}
    </>
  );
}
