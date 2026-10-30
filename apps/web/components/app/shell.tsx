"use client";

import {
  Bell,
  BookMarked,
  FileClock,
  LayoutDashboard,
  LayoutTemplate,
  LogOut,
  Menu as MenuIcon,
  Plus,
  Settings,
  Shield,
  User as UserIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Logo, ThemeToggle } from "@/components/brand";
import { useSession } from "@/components/providers";
import {
  Button,
  Dialog,
  DialogContent,
  IndeterminateBar,
  Menu,
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuSeparator,
  MenuTrigger,
  Notice,
} from "@/components/ui/primitives";
import { api, errorMessage } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { cn, relativeTime } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/history", label: "History", icon: FileClock },
  { href: "/library", label: "Library", icon: BookMarked },
  { href: "/templates", label: "Templates", icon: LayoutTemplate },
  { href: "/settings", label: "Settings", icon: Settings },
];

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const path = usePathname();
  const { user } = useSession();
  const items = [...NAV, ...(user?.role === "ADMIN" ? [{ href: "/admin", label: "Admin", icon: Shield }] : [])];
  return (
    <nav aria-label="Workspace" className="space-y-0.5">
      {items.map((n) => {
        const active = path === n.href || (n.href !== "/dashboard" && path.startsWith(n.href + "/")) || (n.href === "/history" && path.startsWith("/research/") && path !== "/research/new");
        return (
          <Link key={n.href} href={n.href} onClick={onNavigate} aria-current={active ? "page" : undefined}
            className={cn("flex items-center gap-3 rounded-lg px-3 py-2 text-[14px] text-text-2 transition-colors hover:bg-surface-2 hover:text-text",
              active && "bg-surface-2 text-text")}>
            <n.icon className={cn("size-[17px]", active ? "text-signal" : "text-muted")} aria-hidden />
            {n.label}
          </Link>
        );
      })}
    </nav>
  );
}

function Notifications() {
  const { data, reload } = useApi<{ items: { id: string; title: string; body: string; link: string; read: boolean; created_at: string }[]; unread: number }>("/api/v1/notifications");
  useEffect(() => {
    const t = setInterval(() => void reload(), 30000);
    return () => clearInterval(t);
  }, [reload]);
  return (
    <Menu onOpenChange={(o) => { if (!o && data?.unread) void api("/api/v1/notifications/read-all", { method: "POST" }).then(reload); }}>
      <MenuTrigger className="relative rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-text" aria-label={`Notifications${data?.unread ? `, ${data.unread} unread` : ""}`}>
        <Bell className="size-[18px]" />
        {!!data?.unread && <span className="absolute right-1.5 top-1.5 size-2 rounded-full bg-lamp" />}
      </MenuTrigger>
      <MenuContent>
        <div className="w-[320px]">
          <MenuLabel>Notifications</MenuLabel>
          {!data?.items.length && <p className="px-2.5 py-4 text-sm text-muted">Nothing yet. You&apos;ll be notified here when research finishes.</p>}
          {data?.items.slice(0, 8).map((n) => (
            <MenuItem key={n.id} asChild>
              <Link href={n.link} className="flex-col !items-start">
                <span className={cn("text-sm", !n.read && "font-semibold text-text")}>{n.title}</span>
                <span className="line-clamp-2 text-[12.5px] text-muted">{n.body}</span>
                <span className="text-[11.5px] text-muted">{relativeTime(n.created_at)}</span>
              </Link>
            </MenuItem>
          ))}
        </div>
      </MenuContent>
    </Menu>
  );
}

function UserMenu() {
  const { user, signOut } = useSession();
  return (
    <Menu>
      <MenuTrigger className="flex items-center gap-2 rounded-lg p-1 pr-2 hover:bg-surface-2" aria-label="Account menu">
        <span className="grid size-8 place-items-center rounded-full bg-surface-2 text-[13px] font-semibold text-text">
          {(user?.name || user?.email || "?").slice(0, 1).toUpperCase()}
        </span>
      </MenuTrigger>
      <MenuContent>
        <MenuLabel>{user?.email}</MenuLabel>
        <MenuItem asChild><Link href="/settings"><UserIcon />Account</Link></MenuItem>
        <MenuItem asChild><Link href="/settings/usage"><FileClock />Usage</Link></MenuItem>
        <MenuSeparator />
        <MenuItem onSelect={() => void signOut()}><LogOut />Sign out</MenuItem>
      </MenuContent>
    </Menu>
  );
}

function Banners() {
  const { user, config } = useSession();
  const [busy, setBusy] = useState(false);
  return (
    <div className="space-y-2 empty:hidden">
      {config?.features.demo_mode && (
        <Notice tone="lamp" title="Demo mode">Research uses synthetic sources and a deterministic demo model. Results are not real research.</Notice>
      )}
      {config && !config.features.demo_mode && (!config.setup.ai_ready || !config.setup.search_ready) && (
        <Notice tone="warn" title="Setup needed"
          action={user?.role === "ADMIN" ? <Button asChild size="sm" variant="secondary"><Link href="/admin/providers">Configure providers</Link></Button> : undefined}>
          {!config.setup.ai_ready ? "No AI model is configured. " : ""}{!config.setup.search_ready ? "No web search provider is configured. " : ""}
          {user?.role === "ADMIN" ? "Add credentials to start research." : "An administrator needs to finish setup before research can run."}
        </Notice>
      )}
      {user && config?.features.email_verification && !user.email_verified && (
        <Notice tone="signal" title="Verify your email to start research"
          action={<Button size="sm" variant="secondary" loading={busy} onClick={async () => {
            setBusy(true);
            try { await api("/api/v1/auth/resend-verification", { method: "POST" }); toast.success("Verification email sent"); }
            catch (e) { toast.error(errorMessage(e)); } finally { setBusy(false); }
          }}>Resend verification email</Button>}>
          We sent a link to {user.email}.
        </Notice>
      )}
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { status } = useSession();
  const router = useRouter();
  const path = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    if (status === "anonymous") router.replace(`/login?expired=1&next=${encodeURIComponent(path)}`);
  }, [status, router, path]);

  if (status !== "authenticated") {
    return (
      <div className="grid min-h-dvh place-items-center">
        <div className="w-48 space-y-3 text-center">
          <IndeterminateBar label="Loading your workspace" />
          <p className="text-sm text-muted">Loading your workspace…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[248px_1fr]">
      <aside className="sticky top-0 hidden h-dvh flex-col gap-6 border-r border-line bg-bg-deep px-4 py-5 lg:flex no-print">
        <Logo href="/dashboard" className="px-1" />
        <Button asChild variant="signal" className="w-full justify-start"><Link href="/research/new"><Plus />New research</Link></Button>
        <NavLinks />
        <div className="mt-auto flex items-center justify-between border-t border-line pt-4">
          <UserMenu />
          <div className="flex items-center"><Notifications /><ThemeToggle /></div>
        </div>
      </aside>
      <div className="min-w-0">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-line px-4 glass lg:hidden no-print">
          <div className="flex items-center gap-2">
            <button onClick={() => setMobileOpen(true)} className="rounded-lg p-2 text-muted" aria-label="Open navigation"><MenuIcon className="size-5" /></button>
            <Logo href="/dashboard" />
          </div>
          <div className="flex items-center"><Notifications /><ThemeToggle /><UserMenu /></div>
        </header>
        <Dialog open={mobileOpen} onOpenChange={setMobileOpen}>
          <DialogContent title="Navigate" side="right">
            <Button asChild variant="signal" className="mb-4 w-full"><Link href="/research/new" onClick={() => setMobileOpen(false)}><Plus />New research</Link></Button>
            <NavLinks onNavigate={() => setMobileOpen(false)} />
          </DialogContent>
        </Dialog>
        <main id="main" className="mx-auto w-full max-w-[1320px] px-4 py-6 md:px-8 md:py-8">
          <div className="mb-6 no-print"><Banners /></div>
          {children}
        </main>
      </div>
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="headline text-[34px] md:text-[40px]">{title}</h1>
        {description && <p className="mt-1.5 max-w-[70ch] text-text-2">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
