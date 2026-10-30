import type { Metadata } from "next";

import { PageIntro } from "@/components/marketing/chrome";
import { RunReplay } from "@/components/marketing/replay";

export const metadata: Metadata = { title: "How it works" };

const STEPS = [
  ["Understand the question", "The question is restated, classified and checked for ambiguity. If it's unclear, the plan records the assumptions it makes — or asks you."],
  ["Plan", "The agent breaks the question into sub-questions and search queries. You can review and edit the plan before anything is searched."],
  ["Search and select", "Queries run against the configured search providers (and scholarly indexes for literature reviews). Results are de-duplicated by canonical URL, filtered by your domains and dates, and ranked for relevance and source diversity."],
  ["Read safely", "Pages are fetched through an SSRF-hardened fetcher or a scraping provider, and documents are parsed in an isolated sandbox. Pages that try to instruct the AI are flagged and treated as data."],
  ["Extract and verify evidence", "For each source the model proposes claims with an exact supporting quote. Code — not the model — checks that the quote exists in the page. Unverifiable claims are discarded and counted."],
  ["Find gaps and contradictions", "The agent judges which sub-questions are covered by independent sources, records disagreements, and runs bounded follow-up searches to fill gaps."],
  ["Write with citations", "The report is written only from the verified evidence ledger. Citation markers that don't match stored evidence are removed; uncited sentences are flagged."],
  ["Check support", "Each cited sentence is checked against its passages and labelled supported, partially supported or not supported."],
  ["Chart verified data", "Numbers become charts only when they appear in a verified quote, and each data point links to its source."],
];

export default function HowItWorksPage() {
  return (
    <>
      <PageIntro title="An explicit workflow, not an open-ended loop">
        Research runs as a bounded state machine with a time, search, token and cost budget. It is checkpointed after
        every step, so a restart resumes where it left off.
      </PageIntro>
      <div className="mx-auto max-w-[1200px] px-5">
        <ol className="grid gap-x-12 gap-y-10 border-t border-line pt-12 md:grid-cols-2">
          {STEPS.map(([t, b], i) => (
            <li key={t} className="grid grid-cols-[40px_1fr] gap-3">
              <span className="font-serif text-[28px] leading-none text-lamp" aria-hidden>{i + 1}</span>
              <div>
                <h2 className="text-lg font-semibold">{t}</h2>
                <p className="mt-2 text-[14.5px] leading-relaxed text-text-2">{b}</p>
              </div>
            </li>
          ))}
        </ol>
        <div className="py-20"><RunReplay /></div>
      </div>
    </>
  );
}
