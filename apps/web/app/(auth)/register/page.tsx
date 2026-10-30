import { Suspense } from "react";

import { RegisterForm } from "./form";

export const metadata = { title: "Create an account" };

export default function RegisterPage() {
  return <Suspense><RegisterForm /></Suspense>;
}
