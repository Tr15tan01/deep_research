import type { Metadata } from "next";

import { PageIntro } from "@/components/marketing/chrome";
import { FEATURES } from "@/components/marketing/content";

export const metadata: Metadata = { title: "Features" };

export default function FeaturesPage() {
  return (
    <>
      <PageIntro title="Everything points back to a source">
        Each feature exists to make research faster to produce and easier to check.
      </PageIntro>
      <div className="mx-auto max-w-[1200px] px-5 pb-24">
        <dl className="grid gap-x-12 gap-y-12 border-t border-line pt-12 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.title}>
              <dt className="flex items-center gap-2.5 font-semibold"><f.icon className="size-[18px] text-signal" aria-hidden />{f.title}</dt>
              <dd className="mt-2 text-[14.5px] leading-relaxed text-text-2">{f.body}</dd>
            </div>
          ))}
        </dl>
      </div>
    </>
  );
}
