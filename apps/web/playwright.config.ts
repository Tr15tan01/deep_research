// End-to-end tests drive the real stack: FastAPI (demo providers, in-memory DB, embedded
// worker) behind the production Next.js build. DEMO providers are deterministic and labelled
// synthetic — these tests prove the product works end to end, not that real providers answer.
// Live-provider checks live in apps/api/tests (marked `live`) and tests/eval (--live).
import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const API_PORT = Number(process.env.E2E_API_PORT ?? 8100);
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 3100);
const apiDir = path.resolve(here, "../api");
const python = process.env.E2E_PYTHON ?? path.join(apiDir, ".venv/bin/python");
// E2E_INTERNAL_TOKEN=… runs the suite in the free-hosting topology: the API rejects anything without the
// shared token, so every request must flow through the web proxy (see render.yaml).
const internalToken = process.env.E2E_INTERNAL_TOKEN ?? "";

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] }, testIgnore: /mobile\.spec/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /mobile\.spec/ },
  ],
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --port ${API_PORT}`,
      cwd: apiDir,
      url: `http://localhost:${API_PORT}/health/ready`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: {
        ENV_FILE: "/dev/null",
        APP_ENV: "development",
        MONGODB_URI: "mongomock://",
        REDIS_URL: "",
        DEMO_MODE: "1",
        AI_PROVIDER: "demo",
        SEARCH_PROVIDER: "demo",
        EMBEDDED_WORKER: "1",
        DEMO_STEP_DELAY_MS: "250",
        WORKER_POLL_SECONDS: "1",
        FRONTEND_URL: `http://localhost:${WEB_PORT}`,
        AUTH_SECRET: "e2e-only-secret-not-for-production-0123456789",
        ADMIN_BOOTSTRAP_EMAILS: "admin@example.com",
        UPLOAD_DIR: path.join(here, "test-results/uploads"),
        RATE_LIMIT_ENABLED: "0",
        GOOGLE_AUTH_ENABLED: "0",
        LOG_LEVEL: "WARNING",
        INTERNAL_PROXY_TOKEN: internalToken,
      },
    },
    {
      command: process.env.E2E_SKIP_BUILD ? `npx next start --port ${WEB_PORT}` : `npm run build && npx next start --port ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 240_000,
      env: { API_INTERNAL_URL: `localhost:${API_PORT}`, INTERNAL_PROXY_TOKEN: internalToken },
    },
  ],
});
