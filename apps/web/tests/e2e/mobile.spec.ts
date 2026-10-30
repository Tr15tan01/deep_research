import { expect, test } from "@playwright/test";

import { register } from "./helpers";

test("landing page fits a phone without horizontal scroll", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("app navigation works on mobile", async ({ page }) => {
  await register(page);
  await page.goto("/research/new");
  await expect(page.locator("textarea").first()).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
