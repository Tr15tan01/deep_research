"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { useSession } from "@/components/providers";
import { Button } from "@/components/ui/primitives";

const EXAMPLES = [
  "Compare the leading vector databases for a 50M-document search workload",
  "What does recent research say about four-day work weeks and productivity?",
  "Is it true that most startups fail because of running out of cash?",
];

export function HeroPrompt() {
  const { status } = useSession();
  const router = useRouter();
  const [q, setQ] = useState("");

  function go(question: string) {
    const target = `/research/new?q=${encodeURIComponent(question.trim())}`;
    router.push(status === "authenticated" ? target : `/register?next=${encodeURIComponent(target)}`);
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); if (q.trim().length >= 8) go(q); }} className="w-full">
      <label htmlFor="hero-q" className="sr-only">Your research question</label>
      <div className="rounded-2xl border border-line-strong bg-surface p-2 shadow-2 focus-within:border-signal">
        <textarea id="hero-q" value={q} onChange={(e) => setQ(e.target.value)} rows={2} maxLength={4000}
          placeholder="What do you want to find out?"
          onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && q.trim().length >= 8) go(q); }}
          className="w-full resize-none bg-transparent px-3 py-2 text-[16px] leading-relaxed placeholder:text-muted focus:outline-none" />
        <div className="flex items-center justify-between gap-3 px-2 pb-1">
          <span className="text-[12.5px] text-muted">Plans, searches and verifies before it writes.</span>
          <Button type="submit" variant="signal" disabled={q.trim().length < 8}>Start research</Button>
        </div>
      </div>
      <ul className="mt-4 flex flex-col gap-2" aria-label="Example questions">
        {EXAMPLES.map((ex) => (
          <li key={ex}>
            <button type="button" onClick={() => setQ(ex)} className="text-left text-[13.5px] text-text-2 underline decoration-line-strong underline-offset-4 hover:text-text hover:decoration-signal">
              {ex}
            </button>
          </li>
        ))}
      </ul>
    </form>
  );
}
