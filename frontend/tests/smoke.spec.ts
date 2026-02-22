import { expect, test } from "@playwright/test";

test("sign-in route renders form", async ({ page }) => {
  await page.goto("/auth/signin");

  await expect(page.getByRole("heading", { name: "Sign In" })).toBeVisible();
  await expect(page.getByLabel("Email")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send Magic Link" })).toBeVisible();
});
