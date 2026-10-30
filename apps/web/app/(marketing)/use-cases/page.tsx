import type { Metadata } from "next";
import Link from "next/link";

import { PageIntro } from "@/components/marketing/chrome";
import { USE_CASES } from "@/components/marketing/content";

export const metadata: Metadata = { title: "Use cases" };

export default function UseCasesPage() {
  return (
    <>
      <PageIntro title="Questions worth a real answer">
        Research modes are tuned for different jobs: comparisons get a cited matrix, literature reviews search scholarly
        indexes, and claim checks look for evidence on both sides.
      </PageIntro>
      <ul className="mx-auto max-w-[1200px] divide-y divide-line border-y border-line px-5 pb-0">
        {USE_CASES.map((u) => (
          <li key={u.title} className="grid gap-4 py-10 md:grid-cols-[1fr_1.3fr]">
            <div>
              <h2 className="headline flex items-center gap-3 text-[28px]"><u.icon className="size-6 text-signal" aria-hidden />{u.title}</h2>
              <p className="mt-3 max-w-[48ch] text-text-2">{u.body}</p>
            </div>
            <div className="rounded-2xl border border-line bg-surface p-6">
              <p className="text-[13px] text-muted">Try asking</p>
              <p className="mt-2 font-serif text-[20px] leading-snug">“{u.example}”</p>
              <Link href={`/register?next=${encodeURIComponent(`/research/new?q=${encodeURIComponent(u.example)}`)}`}
                className="mt-4 inline-block text-sm text-signal underline-offset-4 hover:underline">Research this question</Link>
            </div>
          </li>
        ))}
      </ul>
      <div className="h-24" />
    </>
  );
}
