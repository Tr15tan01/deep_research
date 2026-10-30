"use client";

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main id="main" className="mx-auto flex min-h-dvh max-w-[640px] flex-col justify-center px-5">
      <h1 className="display text-[44px]">This page failed to load.</h1>
      <p className="mt-4 text-text-2">Your research is safe — it runs on the server. Try again, or go back to your dashboard.</p>
      {error.digest && <p className="mt-2 text-[13px] text-muted">Reference: {error.digest}</p>}
      <div className="mt-6 flex gap-4">
        <button onClick={reset} className="rounded-lg bg-text px-4 py-2 text-sm font-medium text-bg">Try again</button>
        <a href="/dashboard" className="px-2 py-2 text-sm text-signal">Dashboard</a>
      </div>
    </main>
  );
}
