import Link from "next/link";

import { FAQ, FEATURES, SECURITY_POINTS, USE_CASES } from "@/components/marketing/content";
import { EvidencePlates } from "@/components/marketing/evidence-plates";
import { HeroPrompt } from "@/components/marketing/hero-prompt";
import { PricingSection } from "@/components/marketing/pricing";
import { RunReplay } from "@/components/marketing/replay";
import { SampleReport } from "@/components/marketing/sample-report";
import { Button } from "@/components/ui/primitives";

export default function Landing() {
  return (
    <>
      <section className="relative overflow-hidden">
        <div aria-hidden className="grain pointer-events-none absolute inset-0 opacity-60 dark:opacity-100" />
        <div className="relative mx-auto grid max-w-[1200px] items-center gap-12 px-5 pb-20 pt-14 md:pt-20 lg:grid-cols-[1.05fr_1fr] lg:gap-6">
          <div className="max-w-[560px]">
            <h1 className="display text-[clamp(44px,6.4vw,82px)]">Research you can check, line by line.</h1>
            <p className="mt-6 max-w-[48ch] text-[17.5px] leading-relaxed text-text-2">
              Ask a question. An agent plans the research, reads the sources, keeps only the claims it can quote, and
              writes a report where every sentence links to the passage behind it.
            </p>
            <div className="mt-8"><HeroPrompt /></div>
          </div>
          <EvidencePlates className="mx-auto max-w-[600px]" />
        </div>
      </section>

      <section className="border-t border-line bg-bg-deep">
        <div className="mx-auto max-w-[1200px] px-5 py-20">
          <div className="mb-10 max-w-[60ch]">
            <h2 className="headline text-[clamp(30px,3.6vw,44px)]">Watch the work, not a spinner</h2>
            <p className="mt-3 text-text-2">
              Every stage streams from the server as it happens: the queries it runs, the pages it opens, the quotes
              it discards, and the gaps it goes back to fill.
            </p>
          </div>
          <RunReplay />
        </div>
      </section>

      <section className="mx-auto max-w-[1200px] px-5 py-20">
        <div className="mb-10 max-w-[60ch]">
          <h2 className="headline text-[clamp(30px,3.6vw,44px)]">Citations that open the exact passage</h2>
          <p className="mt-3 text-text-2">
            Select a citation to see the sentence it came from, the source type and when it was retrieved. Charts are
            built only from numbers found in verified quotes.
          </p>
        </div>
        <SampleReport />
      </section>

      <section className="border-y border-line bg-bg-deep">
        <div className="mx-auto max-w-[1200px] px-5 py-20">
          <h2 className="headline max-w-[22ch] text-[clamp(30px,3.6vw,44px)]">Built for questions where being wrong is expensive</h2>
          <dl className="mt-12 grid gap-x-12 gap-y-10 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.slice(0, 6).map((f) => (
              <div key={f.title}>
                <dt className="flex items-center gap-2.5 font-semibold"><f.icon className="size-[18px] text-signal" aria-hidden />{f.title}</dt>
                <dd className="mt-2 text-[14.5px] leading-relaxed text-text-2">{f.body}</dd>
              </div>
            ))}
          </dl>
          <Button asChild variant="secondary" className="mt-10"><Link href="/features">See all features</Link></Button>
        </div>
      </section>

      <section className="mx-auto max-w-[1200px] px-5 py-20">
        <h2 className="headline text-[clamp(30px,3.6vw,44px)]">How it compares</h2>
        <div className="mt-8 overflow-x-auto rounded-2xl border border-line">
          <table className="w-full min-w-[640px] border-collapse text-left text-[14px]">
            <caption className="sr-only">Comparison with traditional research workflows</caption>
            <thead className="bg-surface-2 text-text-2">
              <tr>
                <th scope="col" className="px-5 py-3 font-medium">What you get</th>
                <th scope="col" className="px-5 py-3 font-medium">Manual desk research</th>
                <th scope="col" className="px-5 py-3 font-medium">General chat assistant</th>
                <th scope="col" className="px-5 py-3 font-medium text-text">Deep Research</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {[
                ["Sources you can open", "Yes, if you keep notes", "Sometimes; links may not exist", "Always — every citation is a stored, retrieved source"],
                ["Exact supporting passage", "If you copy it", "Rarely", "Required; unverifiable quotes are discarded"],
                ["Disagreements between sources", "Depends on diligence", "Often smoothed over", "Shown side by side with citations"],
                ["Record of how it was done", "Rarely", "No", "Plan, queries, models and budgets saved with the report"],
                ["Time to a first draft", "Hours to days", "Seconds", "Minutes, running in the background"],
              ].map(([k, a, b, c]) => (
                <tr key={k} className="bg-surface">
                  <th scope="row" className="px-5 py-3.5 font-medium">{k}</th>
                  <td className="px-5 py-3.5 text-text-2">{a}</td>
                  <td className="px-5 py-3.5 text-text-2">{b}</td>
                  <td className="px-5 py-3.5">{c}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="border-t border-line bg-bg-deep">
        <div className="mx-auto max-w-[1200px] px-5 py-20">
          <h2 className="headline text-[clamp(30px,3.6vw,44px)]">Where teams use it</h2>
          <ul className="mt-10 divide-y divide-line border-y border-line">
            {USE_CASES.map((u) => (
              <li key={u.title} className="grid gap-3 py-6 md:grid-cols-[280px_1fr_1fr] md:gap-8">
                <p className="flex items-center gap-2.5 font-semibold"><u.icon className="size-[18px] text-signal" aria-hidden />{u.title}</p>
                <p className="text-[14.5px] text-text-2">{u.body}</p>
                <p className="font-serif text-[16px] italic text-text-2">“{u.example}”</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="mx-auto grid max-w-[1200px] gap-12 px-5 py-20 lg:grid-cols-[1fr_1.4fr]">
        <div>
          <h2 className="headline text-[clamp(30px,3.6vw,44px)]">Security and privacy, by default</h2>
          <p className="mt-3 text-text-2">The agent reads the open web on your behalf. We treat that as a hostile environment.</p>
          <Button asChild variant="secondary" className="mt-6"><Link href="/security">How we protect your data</Link></Button>
        </div>
        <dl className="grid gap-8 sm:grid-cols-2">
          {SECURITY_POINTS.map((s) => (
            <div key={s.title}>
              <dt className="flex items-center gap-2.5 font-semibold"><s.icon className="size-[18px] text-signal" aria-hidden />{s.title}</dt>
              <dd className="mt-2 text-[14.5px] leading-relaxed text-text-2">{s.body}</dd>
            </div>
          ))}
        </dl>
      </section>

      <PricingSection />

      <section className="border-t border-line bg-bg-deep">
        <div className="mx-auto grid max-w-[1200px] gap-10 px-5 py-20 lg:grid-cols-[1fr_1.6fr]">
          <h2 className="headline text-[clamp(30px,3.6vw,44px)]">Questions</h2>
          <div className="divide-y divide-line border-y border-line">
            {FAQ.slice(0, 5).map((f) => (
              <details key={f.q} className="group py-4">
                <summary className="cursor-pointer list-none font-medium marker:hidden">
                  <span className="flex items-center justify-between gap-4">{f.q}<span aria-hidden className="text-muted transition-transform group-open:rotate-45">+</span></span>
                </summary>
                <div className="mt-3 max-w-[64ch] text-[14.5px] leading-relaxed text-text-2">{f.a}</div>
              </details>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-[1200px] px-5 py-24">
        <h2 className="display max-w-[16ch] text-[clamp(38px,5vw,64px)]">Start with the question you keep putting off.</h2>
        <div className="mt-8 flex flex-wrap gap-3">
          <Button asChild size="lg" variant="signal"><Link href="/register">Create an account</Link></Button>
          <Button asChild size="lg" variant="secondary"><Link href="/how-it-works">See how it works</Link></Button>
        </div>
      </section>
    </>
  );
}
