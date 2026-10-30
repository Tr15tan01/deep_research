import type { Metadata } from "next";

import { PageIntro } from "@/components/marketing/chrome";

export const metadata: Metadata = { title: "Contact" };

const EMAIL = process.env.NEXT_PUBLIC_CONTACT_EMAIL || "";
const SECURITY_EMAIL = process.env.NEXT_PUBLIC_SECURITY_EMAIL || EMAIL;

export default function ContactPage() {
  return (
    <>
      <PageIntro title="Get in touch">
        Questions about the product, a deployment or your data? Write to us and include the reference ID from any
        error message you saw.
      </PageIntro>
      <div className="mx-auto grid max-w-[1200px] gap-6 px-5 pb-24 md:grid-cols-2">
        <section className="rounded-2xl border border-line bg-surface p-6">
          <h2 className="text-lg font-semibold">General and support</h2>
          {EMAIL ? <a className="mt-2 inline-block text-signal underline-offset-4 hover:underline" href={`mailto:${EMAIL}`}>{EMAIL}</a>
            : <p className="mt-2 text-text-2">This deployment hasn&apos;t published a contact address yet (set NEXT_PUBLIC_CONTACT_EMAIL).</p>}
        </section>
        <section className="rounded-2xl border border-line bg-surface p-6">
          <h2 className="text-lg font-semibold">Security reports</h2>
          <p className="mt-2 text-text-2">Please report vulnerabilities privately and give us reasonable time to fix them before disclosure.</p>
          {SECURITY_EMAIL && <a className="mt-2 inline-block text-signal underline-offset-4 hover:underline" href={`mailto:${SECURITY_EMAIL}`}>{SECURITY_EMAIL}</a>}
        </section>
      </div>
    </>
  );
}
