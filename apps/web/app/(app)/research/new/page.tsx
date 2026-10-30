import { Suspense } from "react";

import { NewResearchForm } from "./form";

export const metadata = { title: "New research" };

export default function NewResearchPage() {
  return <Suspense><NewResearchForm /></Suspense>;
}
