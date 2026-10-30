import { Logo, ThemeToggle } from "@/components/brand";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative flex min-h-dvh flex-col">
      <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -right-40 -top-40 size-[620px] rounded-full opacity-40 blur-3xl"
          style={{ background: "radial-gradient(closest-side, color-mix(in oklab, var(--signal) 25%, transparent), transparent)" }} />
      </div>
      <header className="relative mx-auto flex h-16 w-full max-w-[1200px] items-center justify-between px-5">
        <Logo />
        <ThemeToggle />
      </header>
      <main id="main" className="relative flex flex-1 items-start justify-center px-5 pb-16 pt-6 md:pt-14">
        <div className="w-full max-w-[420px]">{children}</div>
      </main>
    </div>
  );
}
