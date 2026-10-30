import type { Metadata } from "next";

import { PageIntro } from "@/components/marketing/chrome";
import { FAQ } from "@/components/marketing/content";

export const metadata: Metadata = { title: "FAQ" };

export default function FaqPage() {
  return (
    <>
      <PageIntro title="Frequently asked questions" />
      <div className="mx-auto max-w-[860px] px-5 pb-24">
        <div className="divide-y divide-line border-y border-line">
          {FAQ.map((f) => (
            <details key={f.q} className="group py-5">
              <summary className="cursor-pointer list-none text-[17px] font-medium marker:hidden">
                <span className="flex items-center justify-between gap-4">{f.q}<span aria-hidden className="text-muted transition-transform group-open:rotate-45">+</span></span>
              </summary>
              <div className="mt-3 max-w-[66ch] leading-relaxed text-text-2">{f.a}</div>
            </details>
          ))}
        </div>
      </div>
    </>
  );
}
