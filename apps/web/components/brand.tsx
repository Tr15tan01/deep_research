"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import Link from "next/link";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

import { Menu, MenuContent, MenuItem, MenuTrigger } from "./ui/primitives";

export function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-7", className)} aria-hidden>
      <rect width="32" height="32" rx="8" className="fill-text" />
      <path d="M9 22.5 16 8l7 14.5" fill="none" className="stroke-bg" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="11.5" y="17.5" width="9" height="3" rx="1.2" fill="var(--lamp)" />
    </svg>
  );
}

export function Logo({ href = "/", className }: { href?: string; className?: string }) {
  return (
    <Link href={href} className={cn("flex shrink-0 items-center gap-2.5 rounded-md", className)} aria-label="Deep Research home">
      <Mark />
      <span className="whitespace-nowrap font-serif text-[19px] font-medium tracking-[-0.01em]">Deep Research</span>
    </Link>
  );
}

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const Icon = !mounted ? Moon : theme === "system" ? Monitor : resolvedTheme === "dark" ? Moon : Sun;
  return (
    <Menu>
      <MenuTrigger className={cn("rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-text", className)} aria-label="Change theme">
        <Icon className="size-[18px]" />
      </MenuTrigger>
      <MenuContent>
        <MenuItem onSelect={() => setTheme("light")}><Sun />Light</MenuItem>
        <MenuItem onSelect={() => setTheme("dark")}><Moon />Dark</MenuItem>
        <MenuItem onSelect={() => setTheme("system")}><Monitor />Match system</MenuItem>
      </MenuContent>
    </Menu>
  );
}
