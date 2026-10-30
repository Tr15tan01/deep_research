"use client";

import { Menu as MenuIcon, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { Logo, ThemeToggle } from "@/components/brand";
import { useSession } from "@/components/providers";
import { Button } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/features", label: "Features" },
  { href: "/how-it-works", label: "How it works" },
  { href: "/use-cases", label: "Use cases" },
  { href: "/security", label: "Security" },
  { href: "/pricing", label: "Pricing", billingOnly: true },
  { href: "/faq", label: "FAQ" },
];

export function MarketingHeader() {
  const { status, config } = useSession();
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const items = NAV.filter((n) => !n.billingOnly || config?.features.billing);
  return (
    <header className="sticky top-0 z-40 border-b border-line/70 glass">
      <div className="mx-auto flex h-16 max-w-[1200px] items-center justify-between gap-6 px-5">
        <Logo />
        <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
          {items.map((n) => (
            <Link key={n.href} href={n.href}
              className={cn("rounded-lg px-3 py-2 text-sm text-text-2 hover:text-text", path === n.href && "text-text")}>
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          {status === "authenticated" ? (
            <Button asChild size="sm"><Link href="/dashboard">Open workspace</Link></Button>
          ) : (
            <>
              <Button asChild variant="ghost" size="sm" className="hidden sm:inline-flex"><Link href="/login">Sign in</Link></Button>
              <Button asChild size="sm"><Link href="/register"><span className="sm:hidden">Start</span><span className="hidden sm:inline">Start researching</span></Link></Button>
            </>
          )}
          <button className="rounded-lg p-2 text-muted md:hidden" aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {open ? <X className="size-5" /> : <MenuIcon className="size-5" />}
          </button>
        </div>
      </div>
      {open && (
        <nav aria-label="Mobile" className="border-t border-line px-5 py-3 md:hidden">
          {items.map((n) => (
            <Link key={n.href} href={n.href} onClick={() => setOpen(false)} className="block rounded-lg px-2 py-2.5 text-text-2">
              {n.label}
            </Link>
          ))}
        </nav>
      )}
    </header>
  );
}

export function MarketingFooter() {
  return (
    <footer className="border-t border-line bg-bg-deep">
      <div className="mx-auto grid max-w-[1200px] gap-10 px-5 py-14 md:grid-cols-[1.4fr_1fr_1fr_1fr]">
        <div className="space-y-3">
          <Logo />
          <p className="max-w-[34ch] text-sm text-muted">
            An evidence-first research agent. Every claim in a report points to the passage it came from.
          </p>
        </div>
        <FooterCol title="Product" links={[["/features", "Features"], ["/how-it-works", "How it works"], ["/use-cases", "Use cases"], ["/pricing", "Pricing"]]} />
        <FooterCol title="Trust" links={[["/security", "Security and privacy"], ["/privacy", "Privacy policy"], ["/terms", "Terms of service"]]} />
        <FooterCol title="Company" links={[["/about", "About"], ["/faq", "FAQ"], ["/contact", "Contact"]]} />
      </div>
      <div className="mx-auto max-w-[1200px] px-5 pb-8 text-[12.5px] text-muted">
        © {new Date().getFullYear()} Deep Research. Reports are research aids, not professional advice.
      </div>
    </footer>
  );
}

function FooterCol({ title, links }: { title: string; links: [string, string][] }) {
  return (
    <div>
      <p className="mb-3 text-sm font-semibold">{title}</p>
      <ul className="space-y-2">
        {links.map(([href, label]) => (
          <li key={href}><Link className="text-sm text-muted hover:text-text" href={href}>{label}</Link></li>
        ))}
      </ul>
    </div>
  );
}

export function PageIntro({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-[1200px] px-5 pb-10 pt-16 md:pt-24">
      <h1 className="display max-w-[18ch] text-[clamp(40px,6vw,72px)]">{title}</h1>
      {children && <div className="mt-6 max-w-[62ch] text-lg text-text-2">{children}</div>}
    </div>
  );
}

export function LegalReviewBanner() {
  return (
    <div className="mx-auto mb-8 max-w-[1200px] px-5">
      <div role="note" className="rounded-xl border border-warn/40 bg-warn-soft px-4 py-3 text-sm text-text">
        Draft for legal review — this text must be reviewed and adapted by qualified counsel before public launch.
      </div>
    </div>
  );
}
