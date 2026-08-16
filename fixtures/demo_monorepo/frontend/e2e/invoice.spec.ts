import { expect, test } from "@playwright/test";

test("invoice page load path", async ({ page }) => {
  await page.goto("/invoices/1");
  await page.request.get("/api/invoices/1");
  await expect(page.getByRole("heading")).toBeVisible();
});
