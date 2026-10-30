import Link from "next/link";

import { Logo } from "@/components/brand";

export default function NotFound() {
  return (
    <main id="main" className="mx-auto flex min-h-dvh max-w-[640px] flex-col justify-center px-5">
      <Logo />
      <h1 className="display mt-10 text-[56px]">Nothing here.</h1>
      <p className="mt-4 text-text-2">The page you asked for doesn&apos;t exist, or you don&apos;t have access to it.</p>
      <Link href="/" className="mt-6 text-signal hover:underline">Go to the home page</Link>
    </main>
  );
}
