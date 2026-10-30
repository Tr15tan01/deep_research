import type { Metadata } from "next";

import { LegalReviewBanner, PageIntro } from "@/components/marketing/chrome";

export const metadata: Metadata = { title: "Privacy policy" };

const SECTIONS: [string, React.ReactNode][] = [
  ["What we collect", "Account data (email, name, hashed password or Google identity), the research questions you ask, documents you upload, the reports and sources produced, usage records (tokens, searches, estimated costs), and security logs (sign-ins, IP addresses, audit events)."],
  ["Which providers receive data", <>To run research, we send text to third parties configured by the operator of this deployment: the <strong>AI model provider</strong> (Google Gemini, OpenAI, Anthropic, or an OpenAI-compatible endpoint) receives your question, the plan and excerpts of retrieved pages or uploaded documents; <strong>search providers</strong> (Firecrawl, Tavily, Brave Search, and OpenAlex for scholarly search) receive search queries derived from your question and the URLs to fetch. Uploaded document text is sent to the AI provider only when you include the document in a research run. Payment details are handled by the payment provider (Paddle) and never touch our servers.</>],
  ["What we don't do", "We don't sell personal data, and we don't use your uploaded documents or reports to train AI models. The configured AI providers' own data-use terms apply to the text they process; operators should choose provider plans that do not train on API data."],
  ["Retention", "Reports and sources are kept until you delete them or your account. Uploaded files are deleted automatically after the configured retention period (30 days by default). Temporary tokens expire automatically. Audit logs are kept for security and may outlive deleted accounts without personal details."],
  ["Your rights", "You can export all your data and delete reports, documents or your whole account from Settings. Depending on your location you may have further rights (access, correction, objection); contact us to exercise them."],
  ["Security", "We protect data with encryption in transit, encrypted storage of provider credentials, strict per-account isolation, and the controls described on our Security page."],
  ["Cookies", "We use strictly necessary cookies for sign-in sessions and CSRF protection, and a preference for your theme. We do not use advertising cookies."],
  ["Contact", "Questions about privacy: see the Contact page. [Controller identity, address and supervisory-authority details to be completed by counsel.]"],
];

export default function PrivacyPage() {
  return (
    <>
      <PageIntro title="Privacy policy" />
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
