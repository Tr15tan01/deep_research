import { MarketingFooter, MarketingHeader } from "@/components/marketing/chrome";

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <MarketingHeader />
      <main id="main" className="flex-1">{children}</main>
      <MarketingFooter />
    </div>
  );
}
