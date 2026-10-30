import type { Metadata } from "next";

import { LegalReviewBanner, PageIntro } from "@/components/marketing/chrome";

export const metadata: Metadata = { title: "Terms of service" };

const SECTIONS: [string, string][] = [
  ["The service", "Deep Research is a software tool that searches public sources and documents you provide, and generates research reports with citations. Reports are produced with the help of AI models and can contain errors."],
  ["No professional advice", "Reports are research aids. They are not legal, medical, financial or other professional advice. Verify important conclusions against the cited sources and consult a qualified professional where appropriate."],
  ["Your account", "Keep your credentials secure. You are responsible for activity under your account. Tell us promptly about unauthorised use."],
  ["Acceptable use", "Do not use the service to break the law, infringe others' rights, harass or target individuals, attempt to bypass access controls or paywalls, overload the service, or research how to cause serious harm. We may refuse or stop research that violates this policy."],
  ["Your content", "You keep the rights to documents you upload and the questions you ask. You grant us the limited permission needed to process them to provide the service. We do not use your uploaded documents to train models."],
  ["Third-party content", "Reports quote and link third-party sources. Those sources belong to their owners, and their accuracy is their own. Respect the original publishers' terms when reusing material."],
  ["Usage limits and billing", "Plans and limits are described in the product. Costs shown are estimates. If paid plans are enabled, subscriptions renew until cancelled; cancellations take effect at the end of the billing period."],
  ["Availability", "We work to keep the service reliable but do not guarantee it will be uninterrupted. Research runs can fail; partial results are labelled as such."],
  ["Termination", "You can delete your account at any time. We may suspend accounts that violate these terms."],
  ["Liability", "To the extent permitted by law, the service is provided “as is” and our liability is limited. [Jurisdiction-specific terms to be completed by counsel.]"],
];

export default function TermsPage() {
  return (
    <>
      <PageIntro title="Terms of service" />
      <LegalReviewBanner />
      <div className="mx-auto max-w-[1200px] px-5 pb-24">
        <div className="prose-report space-y-8">
          {SECTIONS.map(([t, b]) => (
            <section key={t}><h2 className="font-sans text-lg font-semibold">{t}</h2><p className="mt-2">{b}</p></section>
          ))}
        </div>
      </div>
    </>
  );
}
