import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  vi.restoreAllMocks();
  if (typeof document === "undefined") return; // node-environment tests (e.g. the API proxy)
  cleanup();
  document.cookie.split(";").forEach((c) => {
    document.cookie = c.split("=")[0]!.trim() + "=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
  });
});
