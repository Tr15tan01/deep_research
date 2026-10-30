import { expect, type Page } from "@playwright/test";

export const PASSWORD = "correct-horse-battery-42";

export function uniqueEmail(prefix = "user"): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

export async function register(page: Page, email = uniqueEmail(), name = "E2E Tester"): Promise<string> {
  await page.goto("/register");
  await page.getByLabel("Name").fill(name);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: /create account|sign up|register/i }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  return email;
}

export async function startResearch(page: Page, question: string): Promise<string> {
  await page.goto("/research/new");
  await page.locator("textarea").first().fill(question);
  await page.getByRole("button", { name: /start research/i }).click();
  await expect(page).toHaveURL(/\/research\/job_/);
  return page.url();
}

export async function waitForReport(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { name: "Executive summary" })).toBeVisible({ timeout: 90_000 });
}
