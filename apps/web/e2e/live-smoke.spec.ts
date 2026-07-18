import { expect, test } from "@playwright/test";

/**
 * Live-stack smoke: hits real API via compose web (no fetch/WebSocket mocks).
 * Run after `docker compose up` with SYNTHORA_AUTH_MODE=none.
 */

test("home loads pipelines from live API", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: /ask a research question/i }),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("radiogroup", { name: "pipeline" })).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByText("Fast research")).toBeVisible();
  await expect(
    page.getByRole("button", { name: /start research/i }),
  ).toBeVisible();
});
