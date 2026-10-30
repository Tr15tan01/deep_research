import { expect, test } from "@playwright/test";

import { register } from "./helpers";

test("non-admins cannot reach admin APIs", async ({ page }) => {
  await register(page);
  const res = await page.request.get("/api/v1/admin/users");
  expect(res.status()).toBe(403);
});

test("bootstrap admin sees provider configuration without any secret values", async ({ page }) => {
  await register(page, "admin@example.com", "Admin");
  await page.goto("/admin/providers");
  await expect(page.getByRole("heading", { name: "Credentials" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Models" })).toBeVisible();
  const body = await page.request.get("/api/v1/admin/providers");
  expect(body.ok()).toBeTruthy();
  expect(await body.text()).not.toMatch(/sk-|AIza|api_key"\s*:\s*"[^"]+"/);
  await page.goto("/admin/system-health");
  await expect(page.getByText("Dependencies")).toBeVisible();
});
