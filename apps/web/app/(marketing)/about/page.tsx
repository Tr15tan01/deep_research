import type { Metadata } from "next";

import { PageIntro } from "@/components/marketing/chrome";

export const metadata: Metadata = { title: "About" };

export default function AboutPage() {
  return (
    <>
      <PageIntro title="Why we built an agent that shows its work">
        Fluent answers are cheap. Checkable ones are not.
      </PageIntro>
      <div className="mx-auto max-w-[1200px] px-5 pb-24">
        <div className="prose-report border-t border-line pt-10">
          <p>Language models write convincing prose about almost anything, including things that aren&apos;t true. For research that feeds a decision, the useful question isn&apos;t “does this sound right?” but “where does this come from, and does the source actually say it?”.</p>
          <p>Deep Research is built around that question. The agent may plan, search and write, but the parts that decide what counts as evidence — matching quotes against retrieved pages, validating citations, enforcing budgets — are ordinary, testable code.</p>
          <p>We would rather show you a gap than fill it with a guess. That&apos;s why reports list what is still unknown, mark contested findings, and keep partial results clearly labelled when a run can&apos;t finish.</p>
        </div>
      </div>
    </>
  );
}
