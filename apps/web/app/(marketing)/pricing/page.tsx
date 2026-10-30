import type { Metadata } from "next";

import { PageIntro } from "@/components/marketing/chrome";
import { PricingSection } from "@/components/marketing/pricing";

export const metadata: Metadata = { title: "Pricing" };

export default function PricingPage() {
  return (
    <>
      <PageIntro title="Pay for research, not for seats">
        Limits are enforced on our servers and shown in your usage dashboard. Costs shown are estimates based on the
        current provider price table.
      </PageIntro>
      <PricingSection standalone />
    </>
  );
}
