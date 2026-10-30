import { expect, test } from "@playwright/test";

import { register, startResearch, waitForReport } from "./helpers";

test.describe.configure({ mode: "serial" });

test("live research run streams real events and produces a cited report", async ({ page }) => {
  await register(page);
  await startResearch(page, "Compare PostgreSQL and MongoDB for a multi-tenant SaaS analytics workload");

  // Live view: real backend events, honest indeterminate progress.
  await expect(page.getByText("Live", { exact: true })).toBeVisible();
  await expect(page.getByRole("list", { name: "Research stages" })).toBeVisible();
  await expect(page.getByRole("log", { name: "Research activity" }).getByText(/Searched/).first()).toBeVisible({ timeout: 60_000 });
  expect(await page.locator("[aria-valuenow]").count()).toBe(0); // indeterminate only: no fabricated percentages

  await waitForReport(page);
  await expect(page.getByText(/demo report/i).first()).toBeVisible(); // synthetic data is labelled as such
  await expect(page.getByRole("heading", { name: "Key findings", exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "What is still unknown", exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Limitations", exact: true }).first()).toBeVisible();

  // Citation chip → source panel with the verified passage.
  const chip = page.getByRole("button", { name: /^Source \d+: .*Show supporting passage/ }).first();
  await chip.click();
  const panel = page.getByRole("dialog");
  await expect(panel).toBeVisible();
  await expect(panel.getByText(/Verified passages/)).toBeVisible();
  await page.keyboard.press("Escape");

  // Charts: toggle to the data table, which lists source references.
  const tableToggle = page.getByRole("button", { name: "Table" }).first();
  await tableToggle.scrollIntoViewIfNeeded();
  await tableToggle.click();
  await expect(page.getByRole("table").first()).toBeVisible();

  // Markdown export downloads a file containing the citations.
  await page.getByRole("button", { name: /export/i }).click();
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("menuitem", { name: "Markdown" }).click()]);
  const md = await (await download.createReadStream()).toArray();
  const text = Buffer.concat(md as Buffer[]).toString("utf8");
  expect(text).toMatch(/\[\d+\]/);
  expect(text.toLowerCase()).toContain("demo");

  // Sources page lists stored sources.
  await page.getByRole("link", { name: /all sources and evidence/i }).click();
  await expect(page.getByRole("heading", { name: "Sources and evidence" })).toBeVisible();
  await expect(page.getByRole("row")).not.toHaveCount(0);
});

test("leaving a running job and coming back keeps its progress", async ({ page }) => {
  await register(page);
  const url = await startResearch(page, "What does recent research say about four-day work weeks and productivity?");
  await expect(page.getByRole("log", { name: "Research activity" }).getByText(/Understanding the question/)).toBeVisible();
  await page.goto("/dashboard");
  await expect(page.getByText(/four-day work weeks/i).first()).toBeVisible();
  await page.goto(url);
  await waitForReport(page);
});

test("network drop shows connection state and recovers", async ({ page, context }) => {
  await register(page);
  await startResearch(page, "How has residential heat pump adoption in Germany changed since 2020?");
  await expect(page.getByText("Live", { exact: true })).toBeVisible();
  await context.setOffline(true);
  await expect(page.getByText(/offline|reconnecting|updating every few seconds/i).first()).toBeVisible({ timeout: 30_000 });
  await context.setOffline(false);
  await waitForReport(page); // missed events are recovered from the persisted job state
});

test("cancelling keeps the job marked cancelled, never complete", async ({ page }) => {
  await register(page);
  await startResearch(page, "Evaluate managed Kubernetes offerings across the three largest clouds for SLA and autoscaling");
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByText("Cancelled").first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Complete", { exact: true })).toHaveCount(0);
});

test("users cannot open another user's research", async ({ page, browser }) => {
  await register(page);
  const url = await startResearch(page, "Is it true that most startups fail because they run out of cash?");
  const other = await browser.newContext();
  const p2 = await other.newPage();
  await register(p2);
  await p2.goto(url);
  await expect(p2.getByText(/not found|doesn.t exist|no access/i).first()).toBeVisible();
  const res = await p2.request.get(`/api/v1/research/${url.split("/").pop()}`);
  expect(res.status()).toBe(404);
  await other.close();
});
