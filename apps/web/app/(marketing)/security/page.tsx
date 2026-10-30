import type { Metadata } from "next";

import { PageIntro } from "@/components/marketing/chrome";
import { SECURITY_POINTS } from "@/components/marketing/content";

export const metadata: Metadata = { title: "Security and privacy" };

const DETAILS: [string, string[]][] = [
  ["Accounts and sessions", ["Passwords are hashed with Argon2id.", "Sessions use short-lived access tokens and rotating refresh tokens in HttpOnly cookies; reuse of an old refresh token signs the session out.", "Every state-changing request needs a CSRF token and an allowed origin.", "Sign-in, registration and password-reset endpoints are rate limited, and responses don't reveal whether an account exists."]],
  ["Isolation", ["Every database query is scoped to the signed-in account; other users' reports, sources, uploads and usage return “not found”.", "Administrators see operational job metadata, not report contents."]],
  ["Fetching the web", ["Only http and https on ports 80 and 443.", "Hostnames are resolved and every address is checked; private, loopback, link-local, carrier-grade NAT and cloud metadata ranges are blocked.", "Connections are pinned to the validated address, and redirects are re-validated hop by hop.", "Response size and time are capped."]],
  ["AI safety", ["Retrieved text is wrapped as untrusted data with randomised delimiters.", "The model has no tools that act on your behalf; outputs are schema-validated.", "Citations must match stored evidence and URLs come only from search results, never from model output."]],
  ["Uploads", ["PDF, DOCX, TXT and Markdown only, with signature checks and size limits.", "Parsing runs in a separate process with CPU, memory and file-write limits; archive bombs are rejected.", "Files get server-generated names, are stored outside any web root, and are deleted after the retention period."]],
  ["Your controls", ["Export all of your data as JSON.", "Delete individual reports and documents, or your whole account.", "Uploaded documents are never used to train models."]],
];

export default function SecurityPage() {
  return (
    <>
      <PageIntro title="We assume the web is hostile">
        A research agent reads untrusted pages all day. These are the controls that keep that from becoming your problem.
      </PageIntro>
      <div className="mx-auto max-w-[1200px] px-5 pb-24">
        <dl className="grid gap-10 border-t border-line pt-12 sm:grid-cols-2 lg:grid-cols-4">
          {SECURITY_POINTS.map((s) => (
            <div key={s.title}>
              <dt className="flex items-center gap-2.5 font-semibold"><s.icon className="size-[18px] text-signal" aria-hidden />{s.title}</dt>
              <dd className="mt-2 text-[14.5px] leading-relaxed text-text-2">{s.body}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-16 grid gap-10 md:grid-cols-2">
          {DETAILS.map(([t, items]) => (
            <section key={t}>
              <h2 className="headline text-2xl">{t}</h2>
              <ul className="mt-4 list-disc space-y-2 pl-5 text-[14.5px] text-text-2 marker:text-line-strong">
                {items.map((i) => <li key={i}>{i}</li>)}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </>
  );
}
