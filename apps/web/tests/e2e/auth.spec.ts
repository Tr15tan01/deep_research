import { expect, test } from "@playwright/test";

import { PASSWORD, register, uniqueEmail } from "./helpers";

test("register, sign out, sign back in", async ({ page }) => {
  const email = await register(page);
  await expect(page.getByRole("heading", { name: /good to see you/i })).toBeVisible();

  await page.getByRole("button", { name: /account|profile|user menu/i }).first().click();
  await page.getByRole("menuitem", { name: /sign out/i }).click();
  await expect(page).toHaveURL(/\/login/);

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
});

test("login errors do not reveal whether an account exists", async ({ page }) => {
  const email = await register(page);
  await page.context().clearCookies();
  const attempt = async (e: string) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill(e);
    await page.getByLabel("Password").fill("Wrong-password-123");
    await page.getByRole("button", { name: "Sign in" }).click();
    const alert = page.getByRole("alert").filter({ hasText: /\S/ }).first(); // skip Next's empty route announcer
    await expect(alert).toBeVisible();
    return (await alert.textContent())?.trim();
  };
  const existing = await attempt(email);
  const missing = await attempt(uniqueEmail("nobody"));
  expect(existing).toBeTruthy();
  expect(existing).toEqual(missing);
});

test("Google sign-in is absent when GOOGLE_AUTH_ENABLED=0", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  await expect(page.getByText(/continue with google/i)).toHaveCount(0);
});

test("protected pages redirect signed-out visitors to login", async ({ page }) => {
  await page.goto("/history");
  await expect(page).toHaveURL(/\/login\?next=%2Fhistory/);
});

test("no session tokens are readable by page JavaScript", async ({ page }) => {
  await register(page);
  const visible = await page.evaluate(() => document.cookie);
  expect(visible).not.toMatch(/dr_access|dr_refresh/);
  const stored = await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }));
  expect(stored).not.toMatch(/eyJ[A-Za-z0-9_-]{10,}\./); // no JWTs in web storage
});
