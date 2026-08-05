import { expect, test } from "@playwright/test";

test("golden path: search → compare → save → run", async ({ page }) => {
  await page.goto("/#/search");

  await page.getByPlaceholder("Search papers").fill("neural plasticity");
  await page.getByPlaceholder("Search papers").press("Enter");

  await expect(page.getByText("Longitudinal analysis of neural plasticity under AI assistance", { exact: true })).toBeVisible();
  await expect(page.getByText("Established evidence")).toBeVisible();

  await page.goto("/#/search");
  await expect(page.getByText("Established evidence")).toBeVisible();
  await page.getByLabel(/Select Longitudinal analysis/).check();
  await page.getByLabel(/Select Cognitive offloading/).check();
  await page.getByRole("button", { name: /compare \(2\)/i }).click();

  await expect(page).toHaveURL(/#\/compare\?paper_ids=/);
  await expect(page.getByText("Longitudinal analysis of neural plasticity under AI assistance", { exact: true })).toBeVisible();
  await expect(page.getByText("Cognitive offloading and digital tool interaction: a systematic review", { exact: true })).toBeVisible();

  await page.goto("/#/search?q=cognitive");
  await expect(page.getByText("Established evidence")).toBeVisible();
  await page.getByRole("button", { name: /save search/i }).click();
  await page.getByLabel("Name").fill("Smoke test search");
  await page.getByRole("button", { name: /^save$/i }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await page.goto("/#/saved-searches");
  await expect(page.getByText("Smoke test search")).toBeVisible();
  await page.getByRole("button", { name: /run/i }).first().click();
  await expect(page).toHaveURL(/#\/search\?/);
  await expect(page.getByText("Established evidence")).toBeVisible();
});
